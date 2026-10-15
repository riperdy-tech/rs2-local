"""Engine v2.2's discount rate (REGISTRATION_wacc_v22.md rev 2; SPEC_rebuild AL.54-AL.59).  v1's `discount_rate.py` is a frozen gate-2 file and is
not changed; this module is used only by engine v2.2.

Operating family:
  (a) market-value weights: D = debt on the latest balance sheet filed before T (the latest 10-Q's current + non-current debt plus the annual finance
      lease, else the annual total), E = price at T x the point-in-time share count; Hamada relevers the industry's unlevered beta on D/E_market.
  (b) k_d = rf_T + s_r(T): r = the rating of interest coverage (EBIT / GROSS interest expense, base fiscal year) by Damodaran's large non-financial
      thresholds (January 2026, retrospective for that component, AL.57); s_r(T) = AAA10Y + w_r (BAA10Y - AAA10Y) for investment grade, BAA10Y +
      (d_r - d_BBB) below it, the CCC spread for CC, C and D (flagged `distressed_debt`); d from the January column of year(T).  A missing, zero or
      negative gross interest with debt is refused, unless D/(D+E) < 5%: then k_d = rf + s_AAA(T), flagged `kd_immaterial_floor` (AL.57).
  (c) WACC - g_T >= 2.0 points, else refused.
Financial family: the cost of equity is v1's (the industry's levered beta), unchanged; only (c) on k_e - g_T applies (`check_min_gap`).
Every refusal raises DiscountRefusal naming its reason; nothing is floored silently.

    python -m valuation.discount_rate_v2 build-tables DAMODARAN_DIR FRED_DIR OUT_DIR      (writes ratings_v22.json and anchors_v22.json, hashed)"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .common import InputError, parse_date, terminal_growth_rate
from .discount_rate import DiscountRate, cost_of_equity, relever_beta
from .pit_data import PIT_VALID

RATINGS = ("Aaa/AAA", "Aa2/AA", "A1/A+", "A2/A", "A3/A-", "Baa2/BBB", "Ba1/BB+", "Ba2/BB", "B1/B+", "B2/B", "B3/B-", "Caa/CCC", "Ca2/CC", "C2/C", "D2/D")
INVESTMENT_GRADE = RATINGS[:6]
DISTRESSED = ("Ca2/CC", "C2/C", "D2/D")
CCC = "Caa/CCC"
MIN_GAP = 0.02                      # registration 2c (operator AL.55)
IMMATERIAL_DEBT_WEIGHT = 0.05       # registration 2b (operator AL.57)
GROSS_INTEREST_TAGS = ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt")    # AL.59; never InterestIncomeExpenseNet
ANNUAL_DAYS = (330, 400)


class DiscountRefusal(InputError):
    """The discount rate cannot be formed under v2.2's rules: the valuation is refused with this reason."""


# ---- the tables (built once from the downloaded files, hashed) ----------------------------------------------------------------------

def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _pct(s: str) -> float:
    return float(s.strip().rstrip("%")) / 100.0


def parse_ratings_html(path: Path) -> Tuple[List[Tuple[float, str]], Dict[str, float]]:
    """([(lower bound of coverage, rating)], {rating: spread}) of the large non-financial table on Damodaran's ratings page."""
    t = Path(path).read_text(encoding="latin-1")
    thresholds, spreads = [], {}
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
        if len(cells) >= 4 and cells[2] in RATINGS:
            thresholds.append((float(cells[0]), cells[2]))
            spreads[cells[2]] = _pct(cells[3])
    if sorted(r for _, r in thresholds) != sorted(RATINGS):
        raise InputError(f"ratings page: expected the 15 ratings, found {[r for _, r in thresholds]}")
    return sorted(thresholds), spreads


def parse_spread_archive(paths: List[Path], disagreements: Optional[list] = None) -> Dict[int, Dict[str, float]]:
    """{year: {rating: January default spread}} from Damodaran's archived bondspreads files (one column per January).  Files are read in name order
    (the archive's order of publication) and the EARLIEST-published value of a (year, rating) is kept; a later file that differs is listed in
    `disagreements` (AL.60: one, January 2022 CC, a rating v2.2 never reads)."""
    import openpyxl
    out: Dict[int, Dict[str, float]] = {}
    for p in paths:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        for ws in wb.worksheets:
            hdr = None
            for row in ws.iter_rows(values_only=True):
                cells = [c for c in row if c is not None]
                if not cells:
                    continue
                if cells[0] == "Rating is":
                    if hdr is not None:
                        break
                    hdr = list(row)
                    continue
                if hdr is not None and cells[0] in RATINGS:
                    for h, c in zip(hdr, row):
                        if isinstance(h, str) and h.replace(":", "").strip().startswith("Spread") and isinstance(c, (int, float)):
                            y = int(h.replace(":", "").split()[-1])
                            prev = out.setdefault(y, {}).get(cells[0])
                            if prev is None:
                                out[y][cells[0]] = float(c)
                            elif abs(prev - float(c)) > 1e-9 and disagreements is not None:
                                disagreements.append({"year": y, "rating": cells[0], "kept": prev, "later_file": Path(p).name, "later_value": float(c)})
    return out


def read_fred_csv(path: Path) -> Dict[str, float]:
    with open(path, newline="", encoding="utf-8") as fh:
        return {r[0]: float(r[1]) / 100.0 for r in list(csv.reader(fh))[1:] if len(r) > 1 and r[1] not in ("", ".")}


def build_tables(damodaran_dir: Path, fred_dir: Path, out_dir: Path) -> dict:
    damodaran_dir, fred_dir, out_dir = Path(damodaran_dir), Path(fred_dir), Path(out_dir)
    html_p = damodaran_dir / "ratings_current.html"
    thresholds, spreads_2026 = parse_ratings_html(html_p)
    arch = sorted(damodaran_dir.glob("bondspreads*.xlsx"))
    disagreements: list = []
    by_year = parse_spread_archive(arch, disagreements)
    by_year.setdefault(2026, {}).update(spreads_2026)
    for y, d in by_year.items():
        missing = [r for r in RATINGS if r not in d]
        if missing:
            raise InputError(f"spreads of January {y} lack {missing}")
    ratings = {"rule": "thresholds: Damodaran's large non-financial table, January 2026, for every date (retrospective for this component, AL.57); "
                       "spreads: the January column of year(T) (AL.56)",
               "thresholds": thresholds, "spreads_by_year": {str(y): by_year[y] for y in sorted(by_year)}, "archive_disagreements": disagreements,
               "sources": {p.name: _sha(p) for p in [html_p] + arch}}
    aaa = read_fred_csv(fred_dir / "AAA10Y.csv")
    baa = read_fred_csv(fred_dir / "BAA10Y.csv")
    anchors = {"rule": "FRED AAA10Y and BAA10Y (Moody's seasoned yields minus the 10-year Treasury), fractions; read as the last observation strictly before T",
               "AAA10Y": aaa, "BAA10Y": baa, "sources": {"AAA10Y.csv": _sha(fred_dir / "AAA10Y.csv"), "BAA10Y.csv": _sha(fred_dir / "BAA10Y.csv")}}
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, obj in (("ratings_v22.json", ratings), ("anchors_v22.json", anchors)):
        raw = json.dumps(obj, indent=1, sort_keys=True).encode("utf-8")
        (out_dir / name).write_bytes(raw)
        meta[name] = hashlib.sha256(raw).hexdigest()
    return meta


class CreditTables:
    """The built tables, loaded once: rating(coverage), spread(rating, T)."""

    def __init__(self, root: Path):
        root = Path(root)
        self.ratings = json.loads((root / "ratings_v22.json").read_text(encoding="utf-8"))
        self.anchors = json.loads((root / "anchors_v22.json").read_text(encoding="utf-8"))
        self.thresholds = [(float(lo), r) for lo, r in self.ratings["thresholds"]]
        self._dates = {k: sorted(v) for k, v in self.anchors.items() if k in ("AAA10Y", "BAA10Y")}
        self.sha = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in ("ratings_v22.json", "anchors_v22.json")}

    def rating(self, coverage: float) -> str:
        out = self.thresholds[0][1]
        for lo, r in self.thresholds:
            if coverage > lo:
                out = r
        return out

    def anchor(self, series: str, asof) -> Tuple[float, str]:
        """The last observation strictly before `asof`."""
        cut = (parse_date(asof) - timedelta(days=1)).isoformat()
        ds = self._dates[series]
        import bisect
        i = bisect.bisect_right(ds, cut) - 1
        if i < 0:
            raise DiscountRefusal(f"discount: no {series} observation before {asof}")
        d = ds[i]
        return self.anchors[series][d], d

    def january_spreads(self, asof) -> Tuple[int, Dict[str, float]]:
        y = parse_date(asof).year
        d = self.ratings["spreads_by_year"].get(str(y))
        if d is None:
            raise DiscountRefusal(f"discount: no January {y} spread table")
        return y, d

    def spread(self, rating: str, asof) -> Tuple[float, dict]:
        y, d = self.january_spreads(asof)
        aaa, aaa_d = self.anchor("AAA10Y", asof)
        baa, baa_d = self.anchor("BAA10Y", asof)
        r = CCC if rating in DISTRESSED else rating
        if r in INVESTMENT_GRADE:
            w = (d[r] - d["Aaa/AAA"]) / (d["Baa2/BBB"] - d["Aaa/AAA"])
            s = aaa + w * (baa - aaa)
        else:
            s = baa + (d[r] - d["Baa2/BBB"])
        return s, {"rating_used": r, "january_table": y, "AAA10Y": [aaa, aaa_d], "BAA10Y": [baa, baa_d]}


# ---- inputs read from the point-in-time store ---------------------------------------------------------------------------------------

def gross_interest_at(company, base_period: str, asof) -> Tuple[Optional[float], Optional[str]]:
    """(value, tag): the gross interest expense of the fiscal year ending `base_period`, as known at `asof`, the first of GROSS_INTEREST_TAGS with a
    current (not superseded, not after T) USD value of an annual duration; (None, None) when none is filed."""
    if company is None:
        return None, None
    end = str(base_period)[:10]
    recs = company.facts_table(asof, tags=set(GROSS_INTEREST_TAGS))
    for tag in GROSS_INTEREST_TAGS:
        best = None
        for x in recs:
            if x["tag"] != tag or x["unit"] != "USD" or x["state"] != PIT_VALID or x["instant"] or str(x["end"])[:10] != end:
                continue
            days = (parse_date(x["end"]) - parse_date(x["start"])).days
            if not (ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]):
                continue
            if best is None or (x["filed"], x["accession"]) > (best["filed"], best["accession"]):
                best = x
        if best is not None:
            return float(best["value"]), tag
    return None, None


def latest_balance_debt(st: dict, quarter_records: List[dict], asof) -> Tuple[Optional[float], str, List[str]]:
    """(D, basis, flags): the debt of the latest balance sheet filed before `asof`.  A 10-Q after the annual base with both debt components gives
    current + non-current debt plus the annual finance lease; a later 10-Q missing a component gives the annual total, flagged `debt_annual_only`."""
    annual = st.get("debt_incl_finance_leases")
    base = str(st.get("base_period"))[:10]
    t = parse_date(asof).isoformat()
    by_end: Dict[str, Dict[str, float]] = {}
    for r in quarter_records or []:
        if r.get("field") in ("debt_current", "debt_lt_noncurrent") and str(r.get("filed")) < t and str(r.get("period_end"))[:10] > base:
            by_end.setdefault(str(r["period_end"])[:10], {})[r["field"]] = float(r["value"])
    if not by_end:
        return annual, "annual", []
    end = max(by_end)
    q = by_end[end]
    if "debt_current" in q and "debt_lt_noncurrent" in q:
        fl = (annual - st["debt"]) if (annual is not None and st.get("debt") is not None) else 0.0
        return q["debt_current"] + q["debt_lt_noncurrent"] + fl, f"10-Q {end}", []
    return annual, "annual", ["debt_annual_only"]


# ---- the discount rate ---------------------------------------------------------------------------------------------------------------

def check_min_gap(rate: float, rf: float, family: str) -> float:
    """Registration 2c: refuse when the discount rate is within MIN_GAP of terminal growth."""
    gT = terminal_growth_rate(rf)
    if rate - gT < MIN_GAP:
        what = "WACC" if family == "operating" else "the cost of equity"
        raise DiscountRefusal(f"discount: {what} {rate:.4f} within {MIN_GAP:.1%} of terminal growth {gT:.4f}")
    return gT


def operating_discount_rate(st: dict, asof, *, industry: str, price: Optional[float], shares: Optional[float], gross_interest: Optional[float],
                            gross_interest_tag: Optional[str], quarter_records: List[dict], rf_provider, beta_provider, erp_provider,
                            tables: CreditTables) -> DiscountRate:
    asof_d = parse_date(asof)
    flags: List[str] = []
    if not price or not shares or price <= 0 or shares <= 0:
        raise DiscountRefusal("discount: no market capitalisation (price or share count missing)")
    E = price * shares
    D, debt_basis, f = latest_balance_debt(st, quarter_records, asof_d)
    flags += f
    if D is None:
        raise DiscountRefusal("discount: no balance sheet debt before T")
    D = max(D, 0.0)
    de = D / E
    dv = D / (D + E)
    tax = st["tax_rate"]
    rf, rf_label = rf_provider(asof_d)
    bu, b_label, b_meta = beta_provider(asof_d, industry)
    erp, e_label, e_meta = erp_provider(asof_d)
    detail = {"debt": D, "debt_basis": debt_basis, "market_cap": E, "debt_weight": dv, "gross_interest": gross_interest, "gross_interest_tag": gross_interest_tag}
    if D == 0.0:
        kd = None
    else:
        ebit = st.get("operating_income")
        usable = gross_interest is not None and gross_interest > 0 and ebit is not None
        if not usable:
            if dv < IMMATERIAL_DEBT_WEIGHT:
                s, sd = tables.spread("Aaa/AAA", asof_d)
                kd = rf + s
                flags.append("kd_immaterial_floor")
                detail.update(rating=None, spread=s, spread_detail=sd)
            elif gross_interest is None:
                raise DiscountRefusal("discount: debt with no gross interest expense filed")
            elif gross_interest <= 0:
                raise DiscountRefusal(f"discount: gross interest expense not positive ({gross_interest})")
            else:
                raise DiscountRefusal("discount: no operating income for interest coverage")
        else:
            cov = ebit / gross_interest
            rating = tables.rating(cov)
            if rating in DISTRESSED:
                flags.append("distressed_debt")
            s, sd = tables.spread(rating, asof_d)
            kd = rf + s
            detail.update(coverage=cov, rating=rating, spread=s, spread_detail=sd)
    bl = relever_beta(bu, tax, de)
    coe = cost_of_equity(rf, bl, erp)
    w = coe if kd is None else (1.0 - dv) * coe + dv * kd * (1.0 - tax)
    gT = check_min_gap(w, rf, "operating")
    detail.update(g_terminal=gT, wacc_minus_gT=w - gT, flags=flags)
    return DiscountRate(asof=asof_d.isoformat(), rf=rf, erp=erp, beta_unlevered=bu, de_ratio=de, de_basis="market", tax=tax, beta_levered=bl, coe=coe,
                        kd_pretax=kd, wacc=w,
                        sources={"rf": rf_label, "beta": b_label, "beta_meta": b_meta, "erp": e_label, "erp_meta": e_meta, "industry": industry,
                                 "v22": detail, "tables_sha256": tables.sha},
                        warnings=[f"v2.2 discount rate (REGISTRATION_wacc_v22 rev 2): {x}" for x in flags])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "build-tables":
        print(json.dumps(build_tables(Path(a[1]), Path(a[2]), Path(a[3])), indent=1))
    else:
        sys.exit(__doc__)

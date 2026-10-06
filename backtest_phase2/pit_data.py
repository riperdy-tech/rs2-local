"""Backtest registration sections 4.2-4.7 and 5: the point-in-time inputs of one valuation date.

Builds, for T = the last trading day of June of year Y, the name-date table every arm consumes (`pop`), the universe U(T)
membership with the reason for every exclusion, the as-of-T aggregate for the market-rate solve, and the survivorship
census.  It reads: the cut-down extractor output H(T), the side file of the cut (cover-page shares, share-count filing
dates, 10-K flag), the monthly price download, today's screener labels, and the MRI anchor artifact.  It never reads a
return and never imports a revision of the reference code; the only price after T that it touches is a presence test at
T+36 months (registration 5, "prices at T and at T+36 months").

A fiscal year's `rows` come straight from the extractor; the company is identified by CIK (stored tickers are for the price
lookups only and never appear in a report).
"""
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import aggregate as agg_mod
from .arms import FINANCIAL_SECTORS, adjusted_loading, owner_earnings
from .common import (PriceBook, add_months, is_num, month_index, parse_date, split_in_month, split_product, ym, ym_add)

REVENUE_FLOOR = 1e8        # 5: revenue at L of at least $100M
CAP_FLOOR = 3e8            # 5: cap(T) of at least $300M
MAX_STALE_MONTHS = 15      # 4.2


def load_tools(tree):
    """Import the corpus base-rate modules (identical in both revisions: same git blob) from `tree`; returns (br, gp, rs2_data, mri_sector_id)."""
    tree = Path(tree)
    for p in (str(tree / "tools"), str(tree)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import base_rates as br
    import growth_persistence as gp
    import rs2_data
    return br, gp, rs2_data


class Memo:
    """Memoise the corpus functions the production block calls once per name, so a date's corpus is read once.  Same results."""

    @staticmethod
    def install(br, gp):
        import functools
        if not getattr(gp, "_memoised", False):
            gp.realized_forward_buckets = functools.lru_cache(maxsize=None)(gp.realized_forward_buckets)
            br._file_sha = functools.lru_cache(maxsize=None)(br._file_sha)
            gp._memoised = True


def base_year(rows, period_end, T):
    """4.2: (L, FYE iso, None) or (None, None, reason).  L = the latest fiscal year in H(T) if it ended within the 15 months before T."""
    years = sorted(int(y) for y, r in (rows or {}).items() if str(y).isdigit() and isinstance(r, dict))
    if not years:
        return None, None, "no_rows"
    L = years[-1]
    fye = (period_end or {}).get(str(L))
    if not fye:
        return None, None, "no_fiscal_year_end"
    d = parse_date(fye)
    if d < add_months(T, -MAX_STALE_MONTHS) or d > T:
        return None, None, "stale"
    return L, fye, None


def shares_filing_date(dil, fye, value):
    """(filed iso or None, how).  The filing date of the diluted-share figure of the fiscal year ending `fye`: among the
    annual share-count facts ending on that date, the latest filing of the one whose value equals the row's."""
    cands = [e for e in (dil or []) if e[2] == fye]
    exact = [e for e in cands if is_num(e[3]) and is_num(value) and float(e[3]) == float(value)]
    if exact:
        return max(e[4] for e in exact), "exact"
    if cands:
        return max(e[4] for e in cands), "period_only"
    return None, "unknown"


def adjusted_diluted_shares(shares_L, filed, events, year, fye):
    """4.3: diluted weighted-average shares of L as filed, times the split ratios with ex-dates after the figure's filing date and
    on or before T.  (adjusted shares, filing date used, ambiguity: a split in the filing's own month)."""
    when = filed if filed else fye
    prod = split_product(events, ym(when), f"{year}-06")
    return float(shares_L) * prod, split_in_month(events, ym(when))


def cover_shares(cover, events, year):
    """4.3: the dei cover-page count of the latest filing on or before T (every entry of the latest cover date, summed: the
    company's total over classes), times the splits with ex-dates after the cover-page date and on or before T.
    (adjusted shares or None, the cover date, ambiguity)."""
    if not cover:
        return None, None, False
    end = max(e[0] for e in cover if e[0])
    vals = [e[1] for e in cover if e[0] == end and is_num(e[1]) and e[1] > 0]
    if not vals:
        return None, None, False
    return float(sum(vals)) * split_product(events, ym(end), f"{year}-06"), end, split_in_month(events, ym(end))


SHARE_COUNT_RATIO = 100.0     # amendment A1


def share_scale_conflict(cover_adj, shares_adj):
    """Amendment A1: True when the cover-page count and the company's own filed diluted count, both adjusted to T's split basis,
    differ by a factor of 100 or more in either direction (ratio >= 100 or <= 0.01).  Such a company has no reliable share count: it
    is not valued in any arm, leaves the universe and the aggregate, and is counted.  (The SEC cover facts carry scale slips, a count
    tagged in thousands or worse; the registration's literal cap(T) turns them into caps of $10^15 and more.)"""
    if not (is_num(cover_adj) and is_num(shares_adj) and cover_adj > 0 and shares_adj > 0):
        return False
    r = cover_adj / shares_adj
    return r >= SHARE_COUNT_RATIO or r <= 1.0 / SHARE_COUNT_RATIO


def revenue_years(rows, L):
    """Amendment A2: the number of fiscal years with revenue > 0 in the 8-year window L-7..L (the record's depth)."""
    n = 0
    for y in range(L - 7, L + 1):
        r = (rows.get(str(y)) or {}).get("revenue")
        n += int(is_num(r) and r > 0)
    return n


def dtb3_mean(daily, fye):
    """y_L: the mean of DTB3 over the 12 months ending at L's fiscal year end (observations in (FYE - 12 months, FYE])."""
    lo, hi = add_months(parse_date(fye), -12), parse_date(fye)
    vals = [v for d, v in daily if lo < parse_date(d) <= hi and is_num(v)]
    return sum(vals) / len(vals) if vals else None


class Context:
    """Everything that does not depend on the date."""

    def __init__(self, bt_root, tree, labels_path=None, share_guard=True):
        self.share_guard = share_guard         # False: the registration's literal cap(T), scale slips and all
        self.root = Path(bt_root)
        self.book = PriceBook.load(self.root / "prices" / "prices_monthly_raw.json")
        self.labels = json.loads((labels_path or self.root / "pit" / "universe" / "labels.json").read_text(encoding="utf-8"))
        self.anchors = json.loads((self.root / "mri" / "pit_anchors.json").read_text(encoding="utf-8"))
        self.br, self.gp, self.rs2_data = load_tools(tree)
        Memo.install(self.br, self.gp)

    def hist(self, year):
        return json.loads((self.root / "pit" / f"H_{year}" / "fundamentals_history.json").read_text(encoding="utf-8"))

    def side(self, year, T):
        return json.loads((self.root / "pit" / "cut" / f"side_{T}.json").read_text(encoding="utf-8"))


def synthetic_m(ctx, year, rows, L, hist_dir):
    """4.6: the conditional base-rate median for the growth just delivered (revenue growth of L over L-1), else the size-bucket
    5-year median, both from the H(T) corpus with max_fiscal_year = Y-1, exactly as capability_test.py:1501-1519.
    Returns (m as a fraction or None, source)."""
    yrs = sorted(int(y) for y in rows if str(y).isdigit())
    rl = rows.get(str(L), {}).get("revenue")
    latest_rev = rl
    g0 = None
    if (L - 1) in yrs:
        rprev = rows.get(str(L - 1), {}).get("revenue")
        if is_num(rl) and is_num(rprev) and rprev > 0:
            g0 = rl / rprev - 1
    max_fy = int(year) - 1
    g_stats = None
    if g0 is not None:
        _lbl, g_stats = ctx.gp.persistence_for_growth(g0, sd=hist_dir, max_fiscal_year=max_fy)
    med = (g_stats or {}).get("median") if g_stats else None
    src = "conditional"
    if med is None:
        _sz, table = ctx.br.base_rate_table(latest_rev, sd=hist_dir, max_fiscal_year=max_fy)
        med = ((table or {}).get(5) or {}).get("p50")
        src = "size_bucket"
    if not isinstance(med, (int, float)):
        return None, "none"
    return med / 100.0, src


def build_date(ctx, year, census=None):
    """The inputs of one valuation date.  Returns a dict with `pop` (the arms' name-dates), `agg` (the aggregate), `tallies`."""
    a = ctx.anchors["dates"][year]
    T = parse_date(a["T"])
    Tm = f"{year}-06"
    Tm36 = f"{int(year) + 3}-06"
    hdir = ctx.root / "pit" / f"H_{year}"
    h = ctx.hist(year)
    hist, prov = h["tickers"], h["provenance"]
    side = ctx.side(year, a["T"])
    period_end, untagged_map = prov.get("period_end", {}), prov.get("untagged_fields", {})
    runs, tag_names = prov.get("runs", {}), prov.get("_tags")
    book = ctx.book
    rf_eff = max(a["rf"], a["gA"])
    tally = Counter()
    amb = Counter()
    reps = {}                      # cik -> candidate representative (largest cap)
    shadow = {}                    # cik -> undetermined-basis ticker (never valued; counted only)
    agg_items = []
    per_ticker = {}
    for t in sorted(ctx.labels):
        lab = ctx.labels[t]
        cik = lab.get("cik")
        if cik is None:
            tally["no_cik"] += 1
            continue
        rows = hist.get(t)
        if rows is None:
            tally["no_history_by_T"] += 1
            continue
        sd_ = side.get(cik) or {}
        if not lab.get("has_financials_file", True):
            tally["no_screener_fx_label"] += 1
            continue
        if lab.get("fx") is not None:
            tally["fx_not_usd"] += 1
            continue
        if not book.has_ticker(t):
            tally["yahoo_no_data" if t in book.empty else "not_in_price_file"] += 1
            continue
        price = book.price_at_T(t, year)
        if price is None:
            tally["no_price_at_T"] += 1
            continue
        L, fye, why = base_year(rows, period_end.get(t), T)
        events = book.events(t)
        # shares: the diluted count of L (needs L) and the cover-page count (needs none)
        dil_sh = dil_filed = dil_how = None
        shares_adj = None
        amb_d_ = False
        if L is not None:
            sh = rows[str(L)].get("shares_diluted")
            if is_num(sh) and sh > 0:
                dil_filed, dil_how = shares_filing_date(sd_.get("dil"), fye, sh)
                shares_adj, amb_d_ = adjusted_diluted_shares(sh, dil_filed, events, year, fye)
                amb["diluted_shares_split_in_filing_month"] += int(amb_d_)
                amb["diluted_shares_filing_date_" + dil_how] += 1
        cov, cov_end, amb_c = cover_shares(sd_.get("cover"), events, year)
        if ctx.share_guard and share_scale_conflict(cov, shares_adj):
            tally["share_count_scale_conflict"] += 1
            continue
        undetermined = ctx.share_guard and bool((shares_adj is not None and amb_d_) or (cov is not None and amb_c))
        if cov is not None:
            amb["cover_shares_split_in_cover_month"] += int(amb_c)
            cap_shares, cap_src = cov, "cover"
        elif shares_adj is not None:
            cap_shares, cap_src = shares_adj, "diluted"
        else:
            tally["no_shares_for_cap"] += 1
            continue
        cap = price * cap_shares
        rec = {"ticker": t, "cik": cik, "price": price, "cap": cap, "cap_src": cap_src, "cover_end": cov_end, "rows": rows,
               "L": L, "fye": fye, "L_why": why, "shares": shares_adj, "dil_filed": dil_filed, "dil_how": dil_how,
               "sector": lab.get("sector"), "untagged": untagged_map.get(t) or [], "k10": bool(sd_.get("k10"))}
        if undetermined:
            # C-2: a split in the month of the filing (or of the cover date) leaves the share basis undetermined: the name is not valued in
            # any arm and is not in the aggregate; it is counted under its own key, and kept in `shadow` only to count how many would
            # have been in the universe.
            tally["share_basis_undetermined"] += 1
            curs = shadow.get(cik)
            if curs is None or cap > curs["cap"]:
                shadow[cik] = rec
            continue
        agg_items.append({"ticker": t, "cik": cik, "market_cap": cap, "rows": rows})
        cur = reps.get(cik)
        if cur is None:
            reps[cik] = rec
        elif cap > cur["cap"]:
            tally["share_class_duplicate"] += 1
            reps[cik] = rec
        else:
            tally["share_class_duplicate"] += 1
    # ---- the aggregate (4.7): every USD reporter with a market cap, classes collapsed inside build_aggregate
    agg, agg_stats = agg_mod.build_aggregate(agg_items, as_of=a["T"])
    agg_cik_t = {c["cik"]: c.pop("ticker_key") for c in agg["constituents"]}
    # ---- the universe and the arms' population
    pop, ustat = [], Counter()
    loadings = a["raw_loadings"]
    def classify(r):
        """(u_reason or None, has_loading, raw beta): the first failing step of U(T) for a company's representative."""
        raw = loadings.get(ctx.rs2_data.mri_sector_id(r["sector"]) or "")
        has_load = is_num(raw)
        if not r["k10"]:
            return "not_10k_filer", has_load, raw
        if r["L"] is None:
            return "L_undefined_" + r["L_why"], has_load, raw
        rowL = r["rows"][str(r["L"])]
        rev = rowL.get("revenue")
        oe = owner_earnings(rowL)
        if not is_num(rev):
            u = "revenue_missing"
        elif not rev >= REVENUE_FLOOR:
            u = "revenue_below_100M"
        elif not r["cap"] >= CAP_FLOOR:
            u = "cap_below_300M"
        elif not (book.has_bar(r["ticker"], Tm) and book.has_bar(r["ticker"], Tm36)):
            u = "no_price_at_T_plus_36"
        elif not has_load:
            u = "no_loading"
        elif oe is None:
            u = "owner_earnings_missing"
        elif not oe > 0:
            u = "owner_earnings_not_positive"
        else:
            u = None
        return u, has_load, raw

    for cik, r in sorted(shadow.items()):
        if cik not in reps and classify(r)[0] is None:
            ustat["share_basis_undetermined_would_be_in_U"] += 1
    for cik, r in sorted(reps.items()):
        u_reason, has_load, raw = classify(r)
        if not r["k10"]:
            ustat["not_10k_filer"] += 1
        elif r["L"] is None:
            ustat["L_undefined_" + r["L_why"]] += 1
        if r["L"] is None:
            continue
        rowL = r["rows"][str(r["L"])]
        rev = rowL.get("revenue")
        oe = owner_earnings(rowL)
        if r["k10"]:
            ustat["U" if u_reason is None else u_reason] += 1
        if not has_load:
            ustat["no_loading_any_name_with_L"] += 1
            continue                      # no loading, no value in any arm
        m, m_src = synthetic_m(ctx, year, r["rows"], r["L"], hdir)
        dc_tags = {}
        pv = (runs.get(r["ticker"]) or {}).get("debt_current")
        if pv and tag_names:
            ys = [int(y) for y in r["rows"] if str(y).isdigit()]
            ordered = sorted((int(x[0]), int(x[1])) for x in pv)
            for y in ys:
                idx = None
                for first, ti in ordered:
                    if y >= first:
                        idx = ti
                if idx is not None and 0 <= idx < len(tag_names):
                    dc_tags[y] = tag_names[idx]
        nm = {"cik": cik, "ticker": r["ticker"], "rows": {y: row for y, row in r["rows"].items()}, "L": r["L"], "fye": r["fye"],
              "stub_months": (T - parse_date(r["fye"])).days / 30.4375, "untagged": r["untagged"], "dc_tags": dc_tags,
              "shares": r["shares"], "price": r["price"], "cap": r["cap"], "cap_src": r["cap_src"], "sector": r["sector"],
              "raw_beta": float(raw), "adjL": adjusted_loading(float(raw)), "m": m, "m_src": m_src,
              "y_L": dtb3_mean(a["dtb3_daily"], r["fye"]), "in_U": u_reason is None, "u_reason": u_reason,
              "revenue_L": rev, "oe_L": oe, "rev_years": revenue_years(r["rows"], r["L"]), "in_aggregate": cik in agg_cik_t, "dil_filed": r["dil_filed"], "dil_how": r["dil_how"]}
        pop.append(nm)
    return {"year": year, "T": a["T"], "rf": a["rf"], "pi": a["pi"], "gA": a["gA"], "rf_eff": rf_eff, "pop": pop,
            "agg": agg, "agg_stats": agg_stats, "agg_cik_ticker": agg_cik_t, "tally_pre_collapse": dict(tally),
            "universe": dict(ustat), "ambiguities": dict(amb), "reps": len(reps)}


def save_date(out_dir, res):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    y = res["year"]
    with open(out_dir / f"inputs_{y}.pkl", "wb") as f:
        pickle.dump(res, f, protocol=4)
    (out_dir / f"aggregate_{y}.json").write_text(json.dumps(res["agg"]), encoding="utf-8")
    summary = {k: res[k] for k in ("year", "T", "rf", "pi", "gA", "rf_eff", "agg_stats", "tally_pre_collapse", "universe", "ambiguities", "reps")}
    summary["pop"] = len(res["pop"])
    (out_dir / f"summary_{y}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

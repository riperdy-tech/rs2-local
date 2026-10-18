"""x_margin_basis.py - the earnings-margin basis facts of desk schema 25.2 (BRIEF_SF_short_form.md items 4 and 5).

Pure functions: rows, estimates and filed lines in, dicts out. It imports only throughcycle_record (the record's own X arithmetic), reads no file and never
defaults a missing figure: a year or a line that is not held is stated as not held, and 0.0 is a value.

The earnings margin is the desk's X basis: (net income + after-tax amortization of acquired intangibles) / revenue, after interest and tax, not the operating margin.

history(): X / revenue per filed year (the record's window), shown as filed and without one-offs. One-offs are the filed impairment and restructuring lines
(IMPAIRMENT_TAGS, RESTRUCTURING_TAGS), added back after tax at the record's tax rate for that year (throughcycle_record.tax_rate). The lines of one group are NOT
additive: a filer tags the same charge under a total and under a component (DAC 2018: AssetImpairmentCharges and ImpairmentOfLongLivedAssetsHeldForUse both
210,715,000), so the largest positive line of a group is the one counted and the others are listed, not counted. Disjoint impairment lines (goodwill and
long-lived assets of one year) are therefore understated, never overstated; every year says so (`group_rule`).

consensus_margins(): the X-basis margin the consensus EPS levels imply for years 1 and 2: EPS x the desk's share count over the consensus revenue, the quantities the
DEFAULTS levels are built from (consensus_reference.build: the vendor's current- and next-FY EPS and revenue averages, the share-count default, revenue attributed
by pi, the next-FY revenue dropped on a vendor revenue-basis break). The interest on the cash is NOT taken out (the reference removes it for its owner-earnings
levels; the declared earnings margin is after interest, so is this).

basis_check(): the ratio of each declared year-1 and year-2 margin to the consensus-implied one, flagged outside BASIS_BAND (registered 2026-10-18 before any run).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

import throughcycle_record

BASIS_WORDS = ("earnings margin = net income plus after-tax amortization of acquired intangibles, divided by revenue; after interest and tax; "
               "not the operating margin")
BASIS_BAND = (0.67, 1.5)          # registered with the short form (BRIEF_SF, item 5), before any run
EPS = 1e-12                       # a ratio equal to a band edge is inside it (the bridge checks' convention)

# us-gaap tags of the filed one-off lines. Two groups; the lines of a group are alternatives for the same charge (see the module text).
IMPAIRMENT_TAGS = ("GoodwillImpairmentLoss", "GoodwillAndIntangibleAssetImpairment", "AssetImpairmentCharges", "TangibleAssetImpairmentCharges",
                   "ImpairmentOfLongLivedAssetsHeldForUse", "ImpairmentOfLongLivedAssetsToBeDisposedOf",
                   "ImpairmentOfIntangibleAssetsExcludingGoodwill", "ImpairmentOfIntangibleAssetsFiniteLived",
                   "ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill", "ImpairmentOfRealEstate")
RESTRUCTURING_TAGS = ("RestructuringCharges",)
ANNUAL_FORMS = ("10-K", "20-F", "40-F")       # prefix match (10-K405, 10-K/A)
ANNUAL_DAYS = (340, 380)
GROUP_RULE = "largest positive filed line of each group counted; the others listed, not counted"


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _days(start: str, end: str) -> Optional[int]:
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except (TypeError, ValueError):
        return None


def _is_annual(r: Dict[str, Any]) -> bool:
    if not str(r.get("form", "")).startswith(ANNUAL_FORMS):
        return False
    d = _days(r.get("start") or "", r.get("end") or "")
    return d is not None and ANNUAL_DAYS[0] <= d <= ANNUAL_DAYS[1]


def annual_rows(us_gaap: Dict[str, Any], tag: str, end: str) -> List[Dict[str, Any]]:
    """The annual-report rows of `tag` whose period ends `end`."""
    out = []
    for rows in (((us_gaap or {}).get(tag) or {}).get("units") or {}).values():
        out += [r for r in rows if isinstance(r, dict) and r.get("end") == end and _is_annual(r) and _num(r.get("val"))]
    return out


def covered_ends(us_gaap: Dict[str, Any]) -> set:
    """Every period end for which the filed companyfacts hold an annual-report row of any us-gaap tag: the years the file speaks for."""
    ends = set()
    for body in (us_gaap or {}).values():
        for rows in (body.get("units") or {}).values():
            for r in rows:
                if isinstance(r, dict) and r.get("end") and _is_annual(r):
                    ends.add(r["end"])
    return ends


def one_off_lines(us_gaap: Optional[Dict[str, Any]], end: Optional[str], covered: Optional[set] = None) -> Dict[str, Any]:
    """The filed one-off lines of the fiscal year ending `end`. {"status": "filed" | "none_filed" | "not_held", "lines": [...], "impairment_b",
    "restructuring_b", "one_offs_b"}. `not_held`: no companyfacts file, no period end, or the file holds no annual report for that period end (it cannot
    say that nothing was filed). Each line: {tag, group, value_b, form, filed, accn, counted, note}; the latest-filed row of a tag is the line (a
    restatement replaces the first filing). A line at or below 0 is listed, never counted."""
    out = {"status": "not_held", "lines": [], "impairment_b": 0.0, "restructuring_b": 0.0, "one_offs_b": 0.0, "group_rule": GROUP_RULE}
    if us_gaap is None or not end:
        return out
    cov = covered if covered is not None else covered_ends(us_gaap)
    if end not in cov:
        return out
    lines = []
    for group, tags in (("impairment", IMPAIRMENT_TAGS), ("restructuring", RESTRUCTURING_TAGS)):
        for tag in tags:
            rows = annual_rows(us_gaap, tag, end)
            if not rows:
                continue
            r = max(rows, key=lambda x: (str(x.get("filed") or ""), str(x.get("accn") or "")))
            lines.append({"tag": tag, "group": group, "value_b": r["val"] / 1e9, "form": r.get("form"), "filed": r.get("filed"), "accn": r.get("accn"),
                          "counted": False, "note": None})
    for group in ("impairment", "restructuring"):
        pos = [ln for ln in lines if ln["group"] == group and ln["value_b"] > 0]
        for ln in lines:
            if ln["group"] == group and ln["value_b"] <= 0:
                ln["note"] = "not counted: not a positive charge"
        if pos:
            top = max(pos, key=lambda x: x["value_b"])
            top["counted"] = True
            for ln in pos:
                if ln is not top:
                    ln["note"] = "not counted: the group's largest line is counted"
            out[f"{group}_b"] = top["value_b"]
    out["lines"] = lines
    out["one_offs_b"] = out["impairment_b"] + out["restructuring_b"]
    out["status"] = "filed" if out["one_offs_b"] > 0 else "none_filed"
    return out


def history(rows: Dict[Any, Dict[str, Any]], untagged: Sequence[str], period_ends: Dict[Any, str], us_gaap: Optional[Dict[str, Any]],
            base_year: Optional[int] = None, window_years: int = throughcycle_record.WINDOW_YEARS) -> Dict[str, Any]:
    """The X-basis margin per filed year of the record's window (L-7..L), as filed and without one-offs.

    `rows` are the record's own rows (the consolidated view the through-cycle record is measured on), `untagged` the filer's untagged fields, `period_ends`
    {year: "YYYY-MM-DD"} (the screener history's provenance), `us_gaap` the filed companyfacts' us-gaap block or None when none is held. A year whose X or
    revenue is not defined is left out (stamped in `skipped`). {"base_year", "years": [...], "skipped": [...], "stamps": [...], "tax": ..., "basis": ...}."""
    norm = throughcycle_record.normalise_rows(rows)
    held = sorted(y for y in norm if base_year is None or y <= base_year)
    out: Dict[str, Any] = {"basis": BASIS_WORDS, "base_year": None, "years": [], "skipped": [], "stamps": [], "sec_facts_held": us_gaap is not None,
                           "tax": "the record's tax rate of that year: tax_provision over pretax_income clipped to [0, 0.35], 0.21 when it cannot be computed",
                           "x_source": "screener fundamentals_history: net income + amortization of acquired intangibles x (1 - tax rate); net income alone where the "
                                       "filer tags amortization but a year's value is missing (amortization_gap)"}
    if not held:
        out["stamps"].append("x_margin_history_no_rows")
        return out
    L = held[-1]
    out["base_year"] = L
    cov = covered_ends(us_gaap) if us_gaap is not None else None
    if us_gaap is None:
        out["stamps"].append("one_off_lines_not_held")
    for y in range(L - window_years + 1, L + 1):
        row = norm.get(y)
        if row is None:
            continue
        rev = row.get("revenue")
        x, gap = throughcycle_record.earnings_detail(row, tuple(untagged or ()))
        if not (_num(rev) and rev > 0) or x is None:
            out["skipped"].append({"fy": y, "why": "revenue not positive or net income missing"})
            continue
        tax = throughcycle_record.tax_rate(row)
        end = (period_ends or {}).get(str(y)) or (period_ends or {}).get(y)
        oo = one_off_lines(us_gaap, end, cov)
        added = oo["one_offs_b"] * 1e9 * (1.0 - tax)
        out["years"].append({
            "fy": y, "period_end": end, "revenue_b": rev / 1e9, "x_b": x / 1e9, "x_margin": x / rev, "amortization_gap": bool(gap), "tax_rate": tax,
            "one_offs_status": oo["status"], "one_off_lines": oo["lines"], "impairment_b": oo["impairment_b"], "restructuring_b": oo["restructuring_b"],
            "one_offs_after_tax_b": added / 1e9, "x_margin_ex_one_offs": (x + added) / rev})
    if not out["years"]:
        out["stamps"].append("x_margin_history_no_defined_year")
    if any(y["amortization_gap"] for y in out["years"]):
        out["stamps"].append("amortization_gap:" + "/".join(str(y["fy"]) for y in out["years"] if y["amortization_gap"]))
    return out


# ---- the consensus-implied margin of years 1 and 2 ----------------------------------------------------------------------------------------------

def _est(estimates: Optional[Dict[str, Any]], key: str, kind: str) -> Dict[str, Any]:
    return (((estimates or {}).get(key) or {}).get(kind)) or {}


def consensus_margins(estimates: Optional[Dict[str, Any]], shares: Any, pi: Any = 1.0, vendor_break: bool = False) -> Dict[str, Any]:
    """{"y1": {...} | None, "y2": {...} | None, "stamps": [...], "reason": str | None}. A year is computable when the vendor has analysts behind its EPS and its
    revenue average and the share count is positive. y1 is the vendor's current FY, y2 its next FY (the reference's years 1 and 2); `vendor_break` drops the
    next-FY revenue (input_scope.drop_next_fy_revenue). Revenue is multiplied by pi (the common shares' share), as input_scope.attribute_estimates does."""
    out: Dict[str, Any] = {"y1": None, "y2": None, "stamps": [], "reason": None,
                           "method": "consensus EPS average x the share-count default over the consensus revenue average (pi-attributed); interest on cash not removed"}
    if not (_num(shares) and shares > 0):
        out["reason"] = "no positive share count"
        return out
    if not isinstance(estimates, dict) or not estimates:
        out["reason"] = "no consensus estimates"
        return out
    p = float(pi) if _num(pi) and pi > 0 else 1.0
    for label, key in (("y1", "0y"), ("y2", "+1y")):
        eps, rev = _est(estimates, key, "eps"), _est(estimates, key, "revenue")
        if label == "y2" and vendor_break:
            out["stamps"].append("consensus_y2_revenue_dropped_vendor_basis_break")
            continue
        if not (eps.get("analysts") and _num(eps.get("avg"))):
            out["stamps"].append(f"consensus_{label}_no_eps")
            continue
        if not (rev.get("analysts") and _num(rev.get("avg")) and rev["avg"] > 0):
            out["stamps"].append(f"consensus_{label}_no_revenue")
            continue
        earn = float(eps["avg"]) * float(shares)
        revenue = float(rev["avg"]) * p
        out[label] = {"eps_avg": float(eps["avg"]), "eps_analysts": int(eps["analysts"]), "revenue_b": revenue / 1e9, "revenue_analysts": int(rev["analysts"]),
                      "x_earnings_b": earn / 1e9, "x_margin": earn / revenue}
    if out["y1"] is None and out["y2"] is None:
        out["reason"] = "no year with both an EPS and a revenue consensus"
    return out


# ---- the basis flag ---------------------------------------------------------------------------------------------------------------------------

def basis_check(margins_1_5: Optional[Sequence[Any]], consensus: Optional[Dict[str, Any]], band: Sequence[float] = BASIS_BAND) -> Dict[str, Any]:
    """The declared margins of years 1 and 2 against the consensus-implied ones. {"band", "status", "years": {"1": {...}, "2": {...}}, "gaps": [...]}.
    status: "checked" | "no_basis_check_no_consensus" (no consensus margin for either year) | "no_basis_check_consensus_margin_not_positive". A year whose
    consensus margin is not positive is not checked (a ratio to it means nothing). Outside the band: the year is a gap (`outside_band` true) and `gaps` lists it with its values.
    Nothing is refused, clamped or changed; 0.0 is a value."""
    lo, hi = float(band[0]), float(band[1])
    out: Dict[str, Any] = {"band": [lo, hi], "status": "no_basis_check_no_consensus", "years": {}, "gaps": []}
    cons = consensus or {}
    declared = list(margins_1_5 or [])
    for n, label in ((1, "y1"), (2, "y2")):
        c = cons.get(label)
        cm = c.get("x_margin") if isinstance(c, dict) else None
        d = declared[n - 1] if len(declared) >= n else None
        if not _num(cm):
            continue
        rec: Dict[str, Any] = {"declared": d if _num(d) else None, "consensus": cm, "ratio": None, "outside_band": None}
        if not _num(d):
            rec["note"] = "no declared margin"
        elif not cm > 0:
            rec["note"] = "consensus_margin_not_positive"
        else:
            rec["ratio"] = d / cm
            rec["outside_band"] = bool(rec["ratio"] < lo - EPS or rec["ratio"] > hi + EPS)
        out["years"][str(n)] = rec
        if rec["outside_band"]:
            out["gaps"].append({"year": n, "declared": d, "consensus": cm, "ratio": rec["ratio"]})
    if any(r["ratio"] is not None for r in out["years"].values()):
        out["status"] = "checked"
    elif out["years"]:
        out["status"] = "no_basis_check_consensus_margin_not_positive"
    return out

"""throughcycle_record.py - the company's own record, measured from its fiscal-year rows.

Revision 17 (brief B and its fixes B2). The consensus reference and the desk value the long run (years 6
and after) from what the company's own history says, not from a rule of thumb:

- earnings before acquired-intangible amortization, X_y = net income + amortization x (1 - tax rate)
  (F1): the earnings the long run capitalizes and the margin it reverts toward;
- what it earns on the tangible invested capital that produced them, before interest (F2): R_y = (X_y +
  interest x (1 - t)) / average IC, IC = tangible equity + debt - cash - investments; the share of the
  last eight years in which that beat the cost of equity (p), and the resulting return on new investment;
- whether the record shows a demand-driven earnings downturn (F5): a year in which revenue fell at least
  5% and X fell at least a third from a positive prior-year X, and the median margin the earnings would
  revert toward;
- the growth of its own revenue (Theil-Sen slope of ln revenue on fiscal year);
- the working capital its revenue carries (median NWC / revenue), short-term debt subtracted once (F4).

Pure functions: fiscal-year rows in, a dict out. It imports nothing of ours (the pack and the
reference import it), it never reads a file, and it never defaults a missing figure except where a rule
below says so and a stamp records it: a year whose inputs are not all held is missing, and a statistic
with too few years is None, stamped.

Rows are {fiscal_year: {field: number | None}} as fundamentals_history.json holds them (a year may
be an int or a digit string). `untagged_fields` is the ticker's provenance marker from the
extractor: a field listed there is one the filer never tagged in any year, which the valuation reads
as "none held" (0); a null in a series the filer does tag is a gap, not a zero.

The 5% revenue and one-third earnings thresholds of the cycle test were chosen (by the reviewer, brief B2
F5) after looking at named development companies (MU, STX, NUE, KMT, PIPR, KALU, UGI, SITM, ADI, HWM, LIND
flagged; AAPL, ANET, APH, FIX, AMD, GEV, LAMR, GOOG, AMZN, META, DELL, MPWR, CLS, AVGO, GD, HAE, FIVE, EZPW
not). They are not derived from the whole book.
"""

import math

WINDOW_YEARS = 8        # W = L-7..L
CYCLE_MAX_YEARS = 12    # the cycle test looks at up to 12 held years <= L
R_MIN_YEARS = 3         # defined return years needed for R_tc
CYCLE_MIN_TESTED = 3    # years that must be testable for "no cycle" to mean anything (brief C7); fewer are stamped
M_MIN_YEARS = 5         # defined margin years needed for m_tc
G_MIN_YEARS = 5         # years with revenue > 0 needed for the Theil-Sen growth
NWC_MIN_YEARS = 5       # defined working-capital years needed for nwc_intensity
TAX_DEFAULT = 0.21      # when the tax rate cannot be computed
TAX_MAX = 0.35
CYCLE_REVENUE_FALL = 0.05        # F5: revenue down at least 5% ...
CYCLE_EARNINGS_FALL = 1.0 / 3.0  # ... and X down at least a third from a positive prior year
STB_EQUAL_TOL = 0.005            # F4: separate borrowings equal to current debt within 0.5% are the same debt
# F4: the extractor's documented additive case - debt_current resolved from a current-portion-of-long-term-debt
# tag leaves short-term borrowings a separate liability
CURRENT_PORTION_TAGS = frozenset({"LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                                  "CurrentPortionOfLongtermBorrowings"})

INF = math.inf


def _num(v):
    """v as a float when it is a real number, else None. 0.0 is a value."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return None if math.isnan(v) else float(v)


def median(values):
    """Median of numbers that may be +/-inf. An even count averages its two middle values; when
    they are -inf and +inf there is no median and None is returned. None for no values."""
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return xs[mid]
    a, b = xs[mid - 1], xs[mid]
    if a == b:
        return a
    if a == -INF and b == INF:
        return None
    return (a + b) / 2.0


def theil_sen(points):
    """Median of the pairwise slopes (y_j - y_i) / (x_j - x_i) over [(x, y), ...] with distinct x.
    None when there are fewer than two points."""
    pts = sorted(points)
    slopes = [(pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0])
              for i in range(len(pts)) for j in range(i + 1, len(pts)) if pts[j][0] != pts[i][0]]
    return median(slopes) if slopes else None


def normalise_rows(rows):
    """{int fiscal year: row dict}, dropping anything that is not a year row."""
    out = {}
    for y, row in (rows or {}).items():
        if str(y).isdigit() and isinstance(row, dict):
            out[int(y)] = row
    return out


def resolve_run_tags(runs, tag_names, years):
    """{year: tag name} for a field's provenance runs ([[first_year, tag_index, state], ...], each run holding
    until the next one's first year) and the provenance's `_tags` list. A year before the first run has no
    entry. Pure: the caller passes the structures out of fundamentals_history.json."""
    if not runs or not tag_names:
        return {}
    ordered = sorted((int(r[0]), int(r[1])) for r in runs)
    out = {}
    for y in years:
        idx = None
        for first, ti in ordered:
            if int(y) >= first:
                idx = ti
        if idx is not None and 0 <= idx < len(tag_names):
            out[int(y)] = tag_names[idx]
    return out


def tax_rate(row):
    """tax_provision / pretax_income clipped to [0, TAX_MAX]; TAX_DEFAULT when it cannot be computed."""
    pretax, tax = _num(row.get("pretax_income")), _num(row.get("tax_provision"))
    if pretax is None or tax is None or pretax == 0:
        return TAX_DEFAULT
    return min(TAX_MAX, max(0.0, tax / pretax))


def tangible_equity_detail(row, untagged=()):
    """(tangible equity, partial). equity - goodwill - intangibles ex goodwill. A field in `untagged` counts as
    0. A null in a field the filer does tag is a gap: only the field that is known is subtracted (neither
    when both are null), and the year is `partial` (F3). None when equity is missing."""
    eq = _num(row.get("equity"))
    if eq is None:
        return None, False
    gw = 0.0 if "goodwill" in untagged else _num(row.get("goodwill"))
    ia = 0.0 if "intangibles_ex_goodwill" in untagged else _num(row.get("intangibles_ex_goodwill"))
    partial = gw is None or ia is None
    return eq - (0.0 if gw is None else gw) - (0.0 if ia is None else ia), partial


def tangible_equity(row, untagged=()):
    """Tangible equity of a year (see `tangible_equity_detail`), None when equity is missing."""
    return tangible_equity_detail(row, untagged)[0]


def earnings_detail(row, untagged=()):
    """(X, gap). X = net income + amortization of acquired intangibles x (1 - tax rate): the earnings before that
    non-cash charge (F1). Untagged amortization counts 0; a null in a series the filer does tag uses net income
    for that year and the year is a `gap`. None when net income is missing."""
    ni = _num(row.get("net_income"))
    if ni is None:
        return None, False
    if "amortization_intangibles" in untagged:
        return ni, False
    am = _num(row.get("amortization_intangibles"))
    if am is None:
        return ni, True
    return ni + am * (1.0 - tax_rate(row)), False


def adjusted_earnings(row, untagged=()):
    """X of a year (see `earnings_detail`), None when net income is missing."""
    return earnings_detail(row, untagged)[0]


def short_term_debt(row, dc_tag=None):
    """Short-term debt subtracted once (F4): debt_current, plus short_term_borrowings_separate only when the
    year's debt_current tag is a current-portion-of-long-term-debt tag (CURRENT_PORTION_TAGS) and the two
    differ by more than 0.5%; with no debt_current, the separate borrowings alone; nothing held is 0. Without
    the tag (no provenance) debt_current alone."""
    dc, stb = _num(row.get("debt_current")), _num(row.get("short_term_borrowings_separate"))
    if dc is None:
        return 0.0 if stb is None else stb
    if (stb is not None and dc_tag in CURRENT_PORTION_TAGS
            and abs(stb - dc) > STB_EQUAL_TOL * max(abs(stb), abs(dc))):
        return dc + stb
    return dc


def invested_capital(row, untagged=(), dc_tag=None):
    """Tangible invested capital (F2): tangible equity + total debt - cash - short-term investments - long-term
    investments. Total debt = debt_lt_noncurrent (else lt_debt) + `short_term_debt`; leases are excluded; a null
    debt or investment component counts 0. None when equity or cash is missing."""
    te = tangible_equity(row, untagged)
    cash = _num(row.get("cash"))
    if te is None or cash is None:
        return None
    lt = _num(row.get("debt_lt_noncurrent"))
    if lt is None:
        lt = _num(row.get("lt_debt"))
    inv = 0.0
    for field in ("st_investments", "lt_investments"):
        v = _num(row.get(field))
        inv += 0.0 if v is None else v
    return te + (0.0 if lt is None else lt) + short_term_debt(row, dc_tag) - cash - inv


def return_numerator(row, untagged=()):
    """Earnings before interest available to the capital (F2): X + interest expense x (1 - tax rate); a null
    interest counts 0. None when net income is missing."""
    x = adjusted_earnings(row, untagged)
    if x is None:
        return None
    interest = _num(row.get("interest_expense"))
    return x + (0.0 if interest is None else interest) * (1.0 - tax_rate(row))


def return_series(rows, untagged=(), dc_tags=None):
    """{year: R_y} over every year in `rows` (None where missing): the numerator over the average of IC_{y-1}
    and IC_y, or IC_y alone when the prior year is missing or not positive. IC_y <= 0: +inf when the numerator is
    positive, else -inf. `dc_tags` is {year: debt_current tag} for F4 (None: debt_current alone)."""
    tags = dc_tags or {}
    ic = {y: invested_capital(row, untagged, tags.get(y)) for y, row in rows.items()}
    out = {}
    for y in sorted(rows):
        num = return_numerator(rows[y], untagged)
        cap = ic[y]
        if cap is None or num is None:
            out[y] = None
        elif cap <= 0:
            out[y] = INF if num > 0 else -INF
        else:
            prev = ic.get(y - 1)
            k = (prev + cap) / 2.0 if prev is not None and prev > 0 else cap
            out[y] = num / k
    return out


def net_working_capital(row, dc_tag=None):
    """(current assets - cash - short-term investments) - (current liabilities - short-term debt), the short-term
    debt subtracted once (`short_term_debt`, F4). Short-term investments null count 0; current assets, current
    liabilities and cash are required."""
    ca, cl, cash = _num(row.get("current_assets")), _num(row.get("current_liabilities")), _num(row.get("cash"))
    if ca is None or cl is None or cash is None:
        return None
    sti = _num(row.get("st_investments"))
    return (ca - cash - (0.0 if sti is None else sti)) - (cl - short_term_debt(row, dc_tag))


def cycle_years(rows, base_year, untagged=()):
    """(years, tested): the fiscal years among the latest CYCLE_MAX_YEARS held years <= base_year in which revenue
    fell by at least CYCLE_REVENUE_FALL from the prior year AND X fell by at least CYCLE_EARNINGS_FALL from a
    positive prior-year X (F5), and how many years could be tested (a prior year held, both revenues positive, both
    X defined)."""
    held = sorted(y for y in rows if y <= base_year)[-CYCLE_MAX_YEARS:]
    hits, tested = [], 0
    for y in held:
        prev = rows.get(y - 1)
        if prev is None:
            continue
        rev, rev0 = _num(rows[y].get("revenue")), _num(prev.get("revenue"))
        x, x0 = adjusted_earnings(rows[y], untagged), adjusted_earnings(prev, untagged)
        if rev is None or rev0 is None or rev0 <= 0 or x is None or x0 is None:
            continue
        tested += 1
        if x0 > 0 and rev <= rev0 * (1.0 - CYCLE_REVENUE_FALL) + 1e-12 * abs(rev0) \
                and x <= x0 * (1.0 - CYCLE_EARNINGS_FALL) + 1e-12 * abs(x0):
            hits.append(y)
    return hits, tested


def analyse(rows, r, untagged_fields=(), base_year=None, debt_current_tags=None):
    """Every statistic of the record, with the years it used.

    r is the name's cost-of-equity anchor; base_year is L (default: the newest year held). The window W is
    L-7..L. `debt_current_tags` is {year: the tag debt_current resolved from} (F4). Returns a dict:
      base_year, window, r,
      R (every held year <= L -> return on tangible invested capital or None), r_years (defined years in W),
      R_tc, p, p_years (years in W with R_y > r), ronic_t,
      cycle (True / False, None when no year could be tested), cycle_years (the years with both falls),
      cycle_year (the latest of them), cycle_tested (years that could be tested; fewer than CYCLE_MIN_TESTED
      stamps `cycle_not_testable`: the cycle is what it was, "no" still says nothing about a record that short),
      m_tc (median X / revenue), m_years, g_rev, g_rev_years, nwc_intensity, nwc_years,
      amortization_gap_years, tangible_equity_partial_years (held years <= L within the cycle look-back),
      stamps (["record_not_available"] when R_tc is None; "amortization_gap:<years>" and
      "tangible_equity_partial:<years>" when a year used net income for X or a partial tangible equity;
      "cycle_not_testable" when fewer than CYCLE_MIN_TESTED years could be tested for the cycle).
    """
    untagged = frozenset(untagged_fields or ())
    rows = normalise_rows(rows)
    held = sorted(y for y in rows if base_year is None or y <= base_year)
    out = {"base_year": None, "window": None, "r": r, "R": {}, "r_years": [], "R_tc": None, "p": None,
           "p_years": [], "ronic_t": None, "cycle": None, "cycle_years": [], "cycle_year": None,
           "cycle_tested": 0, "m_tc": None, "m_years": [], "g_rev": None, "g_rev_years": [],
           "nwc_intensity": None, "nwc_years": [], "amortization_gap_years": [],
           "tangible_equity_partial_years": [], "stamps": [], "untagged_fields": sorted(untagged)}
    if not held:
        out["stamps"].append("record_not_available")
        return out
    L = held[-1]
    W = list(range(L - WINDOW_YEARS + 1, L + 1))
    used = {y: rows[y] for y in held}
    tags = {int(y): t for y, t in (debt_current_tags or {}).items()}
    out["base_year"], out["window"] = L, [W[0], W[-1]]

    look = held[-CYCLE_MAX_YEARS:]
    out["amortization_gap_years"] = [y for y in look if earnings_detail(used[y], untagged)[1]]
    out["tangible_equity_partial_years"] = [y for y in look if tangible_equity_detail(used[y], untagged)[1]]
    for name, years in (("amortization_gap", out["amortization_gap_years"]),
                        ("tangible_equity_partial", out["tangible_equity_partial_years"])):
        if years:
            out["stamps"].append(name + ":" + "/".join(str(y) for y in years))

    R = return_series(used, untagged, tags)
    out["R"] = R
    r_w = {y: R.get(y) for y in W if R.get(y) is not None}
    out["r_years"] = sorted(r_w)
    if len(r_w) >= R_MIN_YEARS:
        out["R_tc"] = median(list(r_w.values()))
    if r is not None:
        out["p_years"] = sorted(y for y, v in r_w.items() if v > r)
        # p is a share of the window's eight years, missing years counting as not above; with no defined
        # year there is no record to take a share of, so None
        out["p"] = len(out["p_years"]) / float(WINDOW_YEARS) if r_w else None
        if out["R_tc"] is None:
            out["ronic_t"] = r
        elif out["R_tc"] == INF:
            out["ronic_t"] = INF
        else:
            out["ronic_t"] = r + out["p"] * max(0.0, out["R_tc"] - r)
    if out["R_tc"] is None:
        out["stamps"].append("record_not_available")

    hits, tested = cycle_years(used, L, untagged)
    out["cycle_tested"] = tested
    out["cycle_years"] = hits
    out["cycle_year"] = hits[-1] if hits else None
    out["cycle"] = None if tested == 0 else bool(hits)
    if tested < CYCLE_MIN_TESTED:
        out["stamps"].append("cycle_not_testable")

    margins = {}
    for y in W:
        row = rows.get(y)
        if row is None:
            continue
        rev, x = _num(row.get("revenue")), adjusted_earnings(row, untagged)
        if rev is not None and rev > 0 and x is not None:
            margins[y] = x / rev
    out["m_years"] = sorted(margins)
    if len(margins) >= M_MIN_YEARS:
        out["m_tc"] = median(list(margins.values()))

    pts = []
    for y in W:
        row = rows.get(y)
        rev = _num(row.get("revenue")) if row is not None else None
        if rev is not None and rev > 0:
            pts.append((y, math.log(rev)))
    out["g_rev_years"] = [y for y, _ in pts]
    if len(pts) >= G_MIN_YEARS:
        out["g_rev"] = theil_sen(pts)

    nwc = {}
    for y in W:
        row = rows.get(y)
        if row is None:
            continue
        rev, v = _num(row.get("revenue")), net_working_capital(row, tags.get(y))
        if rev is not None and rev > 0 and v is not None:
            nwc[y] = v / rev
    out["nwc_years"] = sorted(nwc)
    if len(nwc) >= NWC_MIN_YEARS:
        out["nwc_intensity"] = median(list(nwc.values()))
    return out

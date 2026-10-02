"""input_scope.py - the input-scope rules of brief_input_scope_fixes.md (pack revision 20, facts version 8, gate version 8).

Three errors of scope in what the reference was handed, fixed as rules for every company and never per ticker (operator ruling (a),
2026-10-02). Every rule here changes an INPUT of the frozen engine (ruling 1): `consensus_reference.build`, `long_run_value`, the desk's
`unbundled_dcf`, the closure's solve and `throughcycle_record` are not touched.

- Fix 1b (noncontrolling interests, brief 1.3): pi, the common shareholders' share of the consolidated business in the base year
  (`nci_share`); every level `build` receives except net income is multiplied by pi (`attribute_fy_base`, `attribute_cash`,
  `attribute_estimates`); the record reads consolidated net income and equity (`record_view`), stamping `record_scope_mixed:<years>`
  where a window year falls back to the company's own figures while noncontrolling interests are filed.
- Fix 1c (the per-share check, brief 1.4): the ASC 260 identity N_common = EPS_diluted x S_diluted in the base year, to the reporting
  precision of the three facts (`per_share_check`).
- Fix 2b (customer money, brief 2.3): annotation only (`customer_money`); the cash term reads the screener's unrestricted `cash`.
- Fix 3 (the vendor's revenue-basis break, brief 3.2): `vendor_revenue_basis`, on the thresholds frozen in vendor_break_rule.json
  (sha256 checked on load, a mismatch refuses); on a break `build` gets the estimates without the next-FY revenue entry
  (`drop_next_fy_revenue`).

Pure functions: rows, provenance and estimates in, dicts out. No file is read except the threshold file, no number is defaulted with
`or` (0.0 is a value), and a missing input is stated, never guessed.

The screener history's field contract read here (owner: the screener history's schema, brief 1.2(b), 2.2(b)): year rows may carry
`net_income_incl_nci`, `equity_incl_nci`, `cash_restricted`, `customer_money_assets`, `customer_money_liabilities`,
`insurance_reserves`; the per-share check reads `eps_diluted`, `net_income_available_to_common_diluted` and `preferred_dividends`
(NOT in the brief's contract: see `PER_SHARE_FIELDS`); the provenance block carries `ni_scope`, `equity_scope` and `cash_scope` as
provenance[<key>][<ticker>][<year>] = <scope string>. The screener follow-up (rev19/brief_screener_scope_followup.md, items 2-4): `equity`
is the company's own on every rung, with `equity_scope` parent | parent_derived | no_nci_filed | nci_zero_filed | nci_unknown; `ni_scope`
gains nci_zero_filed (an NCI element filed at zero: ProfitLoss is the parent's figure); `cash_scope` gains
cash_unresolved_securities_segregated (a null cell).
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import consensus_reference
import throughcycle_record

# ---- the field contract -----------------------------------------------------------------------------------------------------------

NCI_FIELDS = ("net_income_incl_nci", "equity_incl_nci")
MONEY_FIELDS = ("cash_restricted", "customer_money_assets", "customer_money_liabilities", "insurance_reserves")
# Fix 1c's three facts. The brief's field contract (1.2(b)) does not name them; these are the names this module reads. Until the
# screener history carries them every name is `per_share_basis_untested` (the brief's own outcome for a missing fact).
PER_SHARE_FIELDS = ("eps_diluted", "net_income_available_to_common_diluted", "preferred_dividends")
HISTORY_FIELDS = NCI_FIELDS + MONEY_FIELDS + PER_SHARE_FIELDS

NI_SCOPES = ("parent", "parent_derived", "no_nci_filed", "nci_zero_filed", "nci_unknown")
EQUITY_SCOPES = ("parent", "parent_derived", "no_nci_filed", "nci_zero_filed", "nci_unknown")
# the equity scopes whose `equity` is the company's own figure: the only years the equity split (and the no-NCI test) may read
PARENT_EQUITY_SCOPES = ("parent", "parent_derived", "no_nci_filed", "nci_zero_filed")
# scopes under which no noncontrolling interest is held (a filed zero is a value: "the NCI is zero")
NO_NCI_SCOPES = ("no_nci_filed", "nci_zero_filed")
CASH_SCOPES = ("unrestricted_line", "ifrs_cash_and_equivalents", "derived_minus_restricted", "total_no_restricted_filed", "cash_unresolved",
               "cash_unresolved_securities_segregated")

# stamps
NCI_UNMEASURED = "nci_share_unmeasured"
NCI_FIELDS_ABSENT = "nci_scope_fields_absent"
RECORD_MIXED = "record_scope_mixed"
PER_SHARE_UNVERIFIED = "per_share_basis_unverified"
PER_SHARE_UNTESTED = "per_share_basis_untested"
MONEY_EXCLUDED = "customer_money_excluded"
LIABILITIES_EXCEED = "customer_liabilities_exceed_separate_assets"
INSURANCE_FLOAT = "insurance_float_present"
VENDOR_BREAK = "vendor_revenue_basis_break"
VENDOR_UNTESTED = "vendor_revenue_step_untested"
# the two stamps the gate reads (depth_gates, GATE_VERSION 8)
GATE_STAMPS = (NCI_UNMEASURED, PER_SHARE_UNVERIFIED)


def _num(v):
    """v as a float when it is a finite real number, else None. 0.0 is a value."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def scope_by_year(hist_doc, t, key):
    """{int fiscal year: scope string} of the history's provenance[key][t] (key "ni_scope" or "cash_scope"); {} when absent."""
    block = (((hist_doc or {}).get("provenance") or {}).get(key) or {}).get(t) or {}
    return {int(y): v for y, v in block.items() if str(y).isdigit()}


# ---- Fix 1b: pi ---------------------------------------------------------------------------------------------------------------------

def nci_share(row, ni_scope=None, year=None, equity_scope=None):
    """Brief 1.3(a): pi, the common shareholders' share of the consolidated business in the base year (`row` is its history row,
    `ni_scope` and `equity_scope` its provenance scopes). Returns {"pi", "basis", "year", "ni_parent", "ni_incl_nci", "equity",
    "equity_incl_nci", "ni_scope", "equity_scope", "stamps"}:
      ni_split      pi = net_income / net_income_incl_nci when both > 0, capped at 1;
      equity_split  else pi = equity / equity_incl_nci when both > 0, capped at 1, and only when `equity_scope` says `equity` is the
                    company's own (PARENT_EQUITY_SCOPES; the screener follow-up, item 2): an nci_unknown equity, or one with no scope, is
                    not read;
      no_nci        else pi = 1 when ni_scope is no_nci_filed or nci_zero_filed, or the income statement shows no noncontrolling
                    interest (net_income_incl_nci equals net_income, or is null while ni_scope is "parent": no consolidated figure and no
                    NCI line is filed beside the company's own) and no NCI equity is held (equity_scope no_nci_filed or nci_zero_filed, or
                    a parent-scope equity that equals equity_incl_nci);
      unmeasured    else pi = 1, stamp `nci_share_unmeasured`;
      nci_unknown   ni_scope is nci_unknown (the base year's net income is the consolidated figure, kept and marked): pi = 1, stamp
                    `nci_share_unmeasured`;
      scope_fields_absent  the row carries neither net_income_incl_nci nor equity_incl_nci at all (a history written before Fix 1a):
                    pi = 1, stamp `nci_scope_fields_absent`."""
    row = row or {}
    ni, ni_c = _num(row.get("net_income")), _num(row.get("net_income_incl_nci"))
    eq, eq_c = _num(row.get("equity")), _num(row.get("equity_incl_nci"))
    out = {"pi": 1.0, "basis": None, "year": year, "ni_parent": ni, "ni_incl_nci": ni_c, "equity": eq, "equity_incl_nci": eq_c,
           "ni_scope": ni_scope, "equity_scope": equity_scope, "stamps": []}
    if not any(k in row for k in NCI_FIELDS):
        out["basis"] = "scope_fields_absent"
        out["stamps"].append(NCI_FIELDS_ABSENT)
        return out
    if ni_scope == "nci_unknown":
        out["basis"] = "nci_unknown"
        out["stamps"].append(NCI_UNMEASURED)
        return out
    if ni is not None and ni_c is not None and ni > 0 and ni_c > 0:
        out["pi"], out["basis"] = min(1.0, ni / ni_c), "ni_split"
        return out
    parent_equity = equity_scope in PARENT_EQUITY_SCOPES
    if parent_equity and eq is not None and eq_c is not None and eq > 0 and eq_c > 0:
        out["pi"], out["basis"] = min(1.0, eq / eq_c), "equity_split"
        return out
    income_shows_none = ((ni is not None and ni_c is not None and ni == ni_c) or (ni is not None and ni_c is None and ni_scope == "parent"))
    no_nci_equity = equity_scope in NO_NCI_SCOPES or (parent_equity and eq is not None and eq_c is not None and eq == eq_c)
    if ni_scope in NO_NCI_SCOPES or (income_shows_none and no_nci_equity):
        out["basis"] = "no_nci"
        return out
    out["basis"] = "unmeasured"
    out["stamps"].append(NCI_UNMEASURED)
    return out


def _attributes(pi):
    return pi is not None and pi != 1.0


def attribute_fy_base(ref_fy, fy_rec, pi):
    """Brief 1.3(b): the base fiscal year's levels the reference receives, attributed. Net income stays the company's own (the parent's
    figure is already the common shareholders' share); every other level is multiplied by pi: owner earnings = net_income + pi x (D&A -
    capex), X = net_income + pi x (X - net_income) (the after-tax acquired-intangible amortization), D&A, capex, revenue. `ref_fy` is
    `_fiscal_year_base`'s base dict (None passes); pi = 1 returns it unchanged."""
    if ref_fy is None or not _attributes(pi):
        return ref_fy
    out = dict(ref_fy)
    ni = _num((fy_rec or {}).get("net_income"))
    da, cx = ref_fy.get("da"), ref_fy.get("capex")
    if ref_fy.get("base") is not None:
        out["base"] = ni + pi * (da - cx)
    x = ref_fy.get("x")
    if x is not None and ni is not None:
        out["x"] = ni + pi * (x - ni)
    for k in ("da", "capex", "revenue"):
        if ref_fy.get(k) is not None:
            out[k] = pi * ref_fy[k]
    return out


def attribute_cash(cash, pi):
    """Brief 1.3(b): the cash term's cash and interest, multiplied by pi (a copy; pi = 1 or no cash term returns it unchanged)."""
    if cash is None or not _attributes(pi):
        return cash
    out = dict(cash)
    if _num(out.get("cash")) is not None:
        out["cash"] = pi * out["cash"]
    if _num(out.get("interest")) is not None:
        out["interest"] = pi * out["interest"]
    return out


def attribute_amount(v, pi):
    """A level (cash plus short-term investments, an owner-earnings level) multiplied by pi; None passes, pi = 1 returns it unchanged."""
    if v is None or not _attributes(pi):
        return v
    return pi * v


def attribute_estimates(estimates, pi):
    """Brief 1.3(b): a copy of the vendor's estimates whose revenue LEVELS (avg, low, high, year_ago of 0y and +1y) are multiplied by pi;
    every growth rate and every EPS figure is untouched (EPS is already per common share). pi = 1 returns `estimates` itself."""
    if not isinstance(estimates, dict) or not _attributes(pi):
        return estimates
    out = copy.deepcopy(estimates)
    for key in ("0y", "+1y"):
        rev = (out.get(key) or {}).get("revenue")
        if not isinstance(rev, dict):
            continue
        for f in ("avg", "low", "high", "year_ago"):
            if _num(rev.get(f)) is not None:
                rev[f] = pi * rev[f]
    return out


# ---- Fix 1b: the record's rows on the consolidated basis ----------------------------------------------------------------------------

def _fell_back(row):
    return ((_num(row.get("net_income")) is not None and _num(row.get("net_income_incl_nci")) is None)
            or (_num(row.get("equity")) is not None and _num(row.get("equity_incl_nci")) is None))


def _nci_filed(row, scope, equity_scope=None):
    """True when the row shows that an element of the noncontrolling-interest list is filed for its year: a derived or unknown net-income
    or equity scope, a consolidated equity that differs from the company's own or that could not be resolved beside it (brief 1.2(b):
    equity_incl_nci is null only when an element is filed and neither the inclusive tag nor the sum resolves), or a consolidated net income
    that differs."""
    eq, eq_c = _num(row.get("equity")), _num(row.get("equity_incl_nci"))
    ni, ni_c = _num(row.get("net_income")), _num(row.get("net_income_incl_nci"))
    return (scope in ("parent_derived", "nci_unknown") or equity_scope in ("parent_derived", "nci_unknown") or (eq is not None and eq_c is None)
            or (eq is not None and eq_c is not None and eq_c != eq) or (ni is not None and ni_c is not None and ni_c != ni))


def record_view(rows, ni_scope_by_year=None, base_year=None, equity_scope_by_year=None):
    """Brief 1.3(b): (view, mixed_years). `view` is a copy of the history's rows in which each year's `net_income` is
    `net_income_incl_nci` and `equity` is `equity_incl_nci` where those are not null, so the record's returns, margins, cycle test and
    working capital are ratios on one basis (P3). A row that carries neither field (written before Fix 1a) is passed as it is.
    `mixed_years` are the years of the record's eight-year window (to `base_year`, default the newest) that fall back to the company's own
    figure while noncontrolling interests are filed for that year (`record_scope_mixed`)."""
    scope = ni_scope_by_year or {}
    escope = equity_scope_by_year or {}
    years = sorted(int(y) for y in (rows or {}) if str(y).isdigit())
    L = base_year if base_year is not None else (years[-1] if years else None)
    window = set(range(L - throughcycle_record.WINDOW_YEARS + 1, L + 1)) if L is not None else set()
    view, mixed = {}, []
    for y, row in (rows or {}).items():
        if not (str(y).isdigit() and isinstance(row, dict)) or not any(k in row for k in NCI_FIELDS):
            view[y] = row
            continue
        r = dict(row)
        if _num(row.get("net_income_incl_nci")) is not None:
            r["net_income"] = row["net_income_incl_nci"]
        if _num(row.get("equity_incl_nci")) is not None:
            r["equity"] = row["equity_incl_nci"]
        view[y] = r
        if int(y) in window and _fell_back(row) and _nci_filed(row, scope.get(int(y)), escope.get(int(y))):
            mixed.append(int(y))
    return view, sorted(mixed)


def mixed_stamp(years):
    return f"{RECORD_MIXED}:" + "/".join(str(y) for y in years) if years else None


# ---- Fix 1c: the per-share check ------------------------------------------------------------------------------------------------------

EPS_MIN = 0.05          # below it the half-cent of EPS rounding alone exceeds 10%
EPS_ROUNDING = 0.005    # EPS is reported to the cent
COUNT_PRECISION = 0.005  # net income and share counts: at most 0.5% for a count reported in tenths of millions


def per_share_check(row, year=None):
    """Brief 1.4: the ASC 260 identity N_common = EPS_diluted x S_diluted in the base year. N_common is the net income available to common
    stockholders (diluted) when filed, else net income less preferred dividends when those are filed, else net income; EPS_diluted the
    filed diluted EPS; S_diluted the filed weighted-average diluted share count (`shares_diluted`). The tolerance comes from the reporting
    precision of the three facts, X = 0.005 / |EPS| + 0.005. Returns {"status": "verified" | "unverified" | "untested", "year",
    "n_common", "n_common_source", "eps_filed", "shares_diluted", "eps_implied" (N_common / S_diluted), "gap" (N_common / (EPS x S) - 1),
    "tolerance", "stamps"}: untested (`per_share_basis_untested`) without EPS, shares or a net income, or with |EPS| below $0.05;
    unverified (`per_share_basis_unverified`) when |gap| > X."""
    row = row or {}
    eps, s = _num(row.get("eps_diluted")), _num(row.get("shares_diluted"))
    avail, pref, ni = (_num(row.get("net_income_available_to_common_diluted")), _num(row.get("preferred_dividends")),
                       _num(row.get("net_income")))
    if avail is not None:
        n, src = avail, "available_to_common"
    elif ni is not None and pref is not None:
        n, src = ni - pref, "net_income_less_preferred_dividends"
    elif ni is not None:
        n, src = ni, "net_income"
    else:
        n, src = None, None
    out = {"status": "untested", "year": year, "n_common": n, "n_common_source": src, "eps_filed": eps, "shares_diluted": s,
           "eps_implied": None, "gap": None, "tolerance": None, "stamps": []}
    if eps is None or s is None or not s > 0 or n is None or abs(eps) < EPS_MIN:
        out["stamps"].append(PER_SHARE_UNTESTED)
        return out
    tol = EPS_ROUNDING / abs(eps) + COUNT_PRECISION
    gap = n / (eps * s) - 1.0
    out.update(eps_implied=n / s, gap=gap, tolerance=tol)
    if abs(gap) > tol:
        out["status"] = "unverified"
        out["stamps"].append(PER_SHARE_UNVERIFIED)
    else:
        out["status"] = "verified"
    return out


# ---- Fix 2b: customer money (annotation only) -----------------------------------------------------------------------------------------

def customer_money(row, financial):
    """Brief 2.3: the balances outside the unrestricted cash line, as annotations; no number of the reference changes. Returns
    {"cash_restricted", "assets", "liabilities", "insurance_reserves", "gap", "stamps"}: `customer_money_excluded` when restricted cash or
    customer money is filed; `customer_liabilities_exceed_separate_assets` with `gap` when the customer liabilities exceed the customer
    assets plus restricted cash (a null counts nothing there); `insurance_float_present` when insurance reserves are filed for a company the
    engine treats as non-financial (`financial` False)."""
    row = row or {}
    r, a, l, ins = (_num(row.get("cash_restricted")), _num(row.get("customer_money_assets")), _num(row.get("customer_money_liabilities")),
                    _num(row.get("insurance_reserves")))
    out = {"cash_restricted": r, "assets": a, "liabilities": l, "insurance_reserves": ins, "gap": None, "stamps": []}
    if r is not None or a is not None or l is not None:
        out["stamps"].append(MONEY_EXCLUDED)
    if l is not None:
        separate = (a if a is not None else 0.0) + (r if r is not None else 0.0)
        if l > separate:
            out["gap"] = l - separate
            out["stamps"].append(LIABILITIES_EXCEED)
    if ins is not None and not financial:
        out["stamps"].append(INSURANCE_FLOAT)
    return out


# ---- Fix 3: the vendor's revenue-basis break --------------------------------------------------------------------------------------------

RULE_PATH = Path(__file__).resolve().parent / "vendor_break_rule.json"
RULE_SHA256 = "edd178cdea29e6246669df7622fafe667cefdc05230b58e022e3844a1271e3be"
_RULE = {}


def break_rule(path=None, sha256=RULE_SHA256):
    """The frozen thresholds (brief 3.2; review_r19c/vendor_break_rule.json, frozen 2026-10-02 20:03 KST). The file's sha256 is checked
    every time it is read: a file that differs is refused (RuntimeError), never used."""
    p = Path(path) if path is not None else RULE_PATH
    key = (str(p), sha256)
    if key not in _RULE:
        raw = p.read_bytes()
        got = hashlib.sha256(raw).hexdigest()
        if got != sha256:
            raise RuntimeError(f"refused: the vendor revenue-basis threshold file {p} has sha256 {got}, not the frozen {sha256}")
        d = json.loads(raw.decode("utf-8"))
        _RULE[key] = {k: float(d[k]) for k in ("rev_step_lo", "rev_step_hi", "k_lo", "k_hi")}
    return dict(_RULE[key])


def vendor_revenue_basis(estimates, rule=None):
    """Brief 3.2: s = ln(R1 / R0) (the vendor's two revenue averages, `vendor_revenue`) and k = ln((1 + c2) / (R1 / R0)) (c2 the next-FY EPS
    growth as `consensus_earnings_growth` returns it). Testable where both exist and EPS growth is usable; a break UP is s > s_hi and
    k < k_lo, DOWN s < s_lo and k > k_hi. Returns {"status": "consistent" | "break_up" | "break_down" | "untested" | "not_available",
    "s", "k", "r0", "r1", "c2", "stamps"}: `vendor_revenue_basis_break` on a break; `vendor_revenue_step_untested` (annotation only) when
    the step cannot be tested and s lies outside [s_lo, s_hi]."""
    vr = consensus_reference.vendor_revenue(estimates)
    out = {"status": "not_available", "s": None, "k": None, "r0": None, "r1": None, "c2": None, "stamps": []}
    if vr is None:
        return out
    rule = break_rule() if rule is None else rule
    s = math.log(vr[1] / vr[0])
    out.update(s=s, r0=vr[0], r1=vr[1])
    _c1, c2, why = consensus_reference.consensus_earnings_growth(estimates)
    if why is not None:
        out["status"] = "untested"
        if not rule["rev_step_lo"] <= s <= rule["rev_step_hi"]:
            out["stamps"].append(VENDOR_UNTESTED)
        return out
    k = math.log((1.0 + c2) / (vr[1] / vr[0]))
    out.update(k=k, c2=c2)
    if s > rule["rev_step_hi"] and k < rule["k_lo"]:
        out["status"] = "break_up"
    elif s < rule["rev_step_lo"] and k > rule["k_hi"]:
        out["status"] = "break_down"
    else:
        out["status"] = "consistent"
    if out["status"].startswith("break"):
        out["stamps"].append(VENDOR_BREAK)
    return out


def drop_next_fy_revenue(estimates):
    """Brief 3.2, on a break: a copy of the estimates whose +1y revenue entry is empty, so `revenue_growth_next_fy` and `vendor_revenue`
    are None and `build` takes its documented no-revenue branch (years 3-5 at the base-rate median, the long run on the owner-earnings
    ratio)."""
    out = copy.deepcopy(estimates)
    if isinstance(out.get("+1y"), dict):
        out["+1y"]["revenue"] = {}
    return out


# ---- the base year's scope, in one place for the pack and `reference_inputs` -------------------------------------------------------

def base_year_scope(rows, hist_doc, t, financial):
    """Everything the base year (the newest year of `rows`) says about scope: {"year", "nci", "per_share", "money", "cash_scope",
    "ni_scope"}; the record's mixed years are the record's own (`record_view`)."""
    years = sorted(int(y) for y in (rows or {}) if str(y).isdigit())
    L = years[-1] if years else None
    row = (rows.get(str(L)) or {}) if L is not None else {}
    ni_scope = scope_by_year(hist_doc, t, "ni_scope").get(L)
    equity_scope = scope_by_year(hist_doc, t, "equity_scope").get(L)
    return {"year": L, "nci": nci_share(row, ni_scope, L, equity_scope), "per_share": per_share_check(row, L),
            "money": customer_money(row, financial), "cash_scope": scope_by_year(hist_doc, t, "cash_scope").get(L), "ni_scope": ni_scope,
            "equity_scope": equity_scope}


def record_view_for(rows, hist_doc, t, base_year):
    """`record_view` with the ticker's net-income and equity scopes read from the history's provenance (the one call the pack's record
    and `reference_inputs`' record share)."""
    return record_view(rows, scope_by_year(hist_doc, t, "ni_scope"), base_year, scope_by_year(hist_doc, t, "equity_scope"))


def gate_stamps(facts):
    """The input-scope stamps of a pack's facts that a verdict row carries for the gate (`input_scope_stamps`): every stamp of
    nci_attribution, per_share_basis, customer_money and vendor_revenue_basis, sorted; None when the facts carry none of the four (a facts
    dict from before facts version 8, or a text read)."""
    f = facts or {}
    blocks = [f.get(k) for k in ("nci_attribution", "per_share_basis", "customer_money", "vendor_revenue_basis")]
    if all(b is None for b in blocks):
        return None
    out = set()
    for b in blocks:
        out.update((b or {}).get("stamps") or [])
    return sorted(out)


# ---- the text (pack revision 20) ------------------------------------------------------------------------------------------------------

def _pct(x):
    return f"{x * 100:.1f}%"


def _money(v, fmt_b):
    return fmt_b(v) if v is not None else "not filed"


_BASIS_TXT = {"ni_split": "net-income split", "equity_split": "equity split"}


def nci_text_due(nci, mixed_years):
    """Brief 1.3(d): the NCI text prints only when pi < 1, the base year's net income is derived or unknown in scope, pi is unmeasured,
    or the record is mixed."""
    return (nci["pi"] < 1.0 or nci.get("ni_scope") in ("parent_derived", "nci_unknown") or NCI_UNMEASURED in nci["stamps"]
            or bool(mixed_years))


def upper_bound_clause(nci):
    """Brief 1.3(a): the reference line's clause for an unmeasured share (and for a base year whose net income scope is unknown)."""
    if nci.get("basis") == "nci_unknown":
        return ("noncontrolling interests are filed but the base year's net income is the consolidated figure (the company's own share is "
                "not filed): this value includes their share of every level, net income included, an upper bound")
    return ("noncontrolling interests are filed but the common shareholders' share cannot be measured (neither the net-income nor the equity "
            "split is filed): this value includes their share of every level except net income, an upper bound")


def nci_data_line(nci, mixed_years, fmt_b):
    """Brief 1.3(d): DATA 5's NONCONTROLLING INTERESTS line (`fmt_b` formats dollars as $B)."""
    y = nci.get("year")
    if NCI_UNMEASURED in nci["stamps"]:
        text = f"- NONCONTROLLING INTERESTS: FY{y}: " + upper_bound_clause(nci) + f" ({NCI_UNMEASURED})"
    else:
        derived = (" (consolidated net income less the noncontrolling interests' share, as filed)"
                   if nci.get("ni_scope") == "parent_derived" else "")
        basis = _BASIS_TXT.get(nci["basis"], nci["basis"])
        if nci["basis"] == "equity_split":
            basis += (f": equity attributable to the company {_money(nci['equity'], fmt_b)} of consolidated "
                      f"{_money(nci['equity_incl_nci'], fmt_b)}")
        text = (f"- NONCONTROLLING INTERESTS: FY{y} net income attributable to the company {_money(nci['ni_parent'], fmt_b)}{derived} of "
                f"consolidated {_money(nci['ni_incl_nci'], fmt_b)} (π = {_pct(nci['pi'])}, {basis}); the reference values the consolidated "
                f"business and attributes π of it to the common shares")
    if mixed_years:
        text += (f"; the record's returns, margins and working capital use consolidated net income and equity except "
                 f"FY{', FY'.join(str(x) for x in mixed_years)}, where only the company's own figures are filed ({mixed_stamp(mixed_years)})")
    return text


def pi_clause(nci):
    """Brief 1.3(d): the reference line's attribution clause (pi < 1 only)."""
    return f"consolidated business attributed to the common shares at π = {_pct(nci['pi'])}" if nci["pi"] < 1.0 else None


def per_share_figures(ps):
    """The two figures of an unverified per-share check, as printed (brief 1.4)."""
    what = {"available_to_common": "net income available to common stockholders",
            "net_income_less_preferred_dividends": "net income less preferred dividends",
            "net_income": "net income"}[ps["n_common_source"]]
    return (f"FY{ps['year']} {what} / filed diluted shares = ${ps['eps_implied']:,.2f} against the filed diluted EPS ${ps['eps_filed']:,.2f} "
            f"({ps['gap'] * 100:+.2f}%, beyond the reporting precision of ±{ps['tolerance'] * 100:.2f}%)")


def per_share_data_line(ps):
    """Brief 1.4: DATA 2's line for an unverified per-share check."""
    return (f"- PER-SHARE CHECK: {per_share_figures(ps)}: the per-share basis of the filed figures is not verified ({PER_SHARE_UNVERIFIED})")


def per_share_clause(ps):
    return f"per-share basis not verified: {per_share_figures(ps)}"


def cash_note(cash_scope, money, fmt_b):
    """Brief 2.3: what the cash clause and DATA 6's cash line add: the scope when it is not the unrestricted line, the excluded amounts,
    and the two annotations. None when there is nothing to say."""
    parts = []
    if cash_scope is not None and cash_scope != "unrestricted_line":
        parts.append(f"cash_scope {cash_scope}")
    excl = []
    if money["cash_restricted"] is not None:
        excl.append(f"restricted cash {fmt_b(money['cash_restricted'])}")
    if money["assets"] is not None:
        excl.append(f"customer money held {fmt_b(money['assets'])}")
    if money["liabilities"] is not None:
        excl.append(f"customer liabilities {fmt_b(money['liabilities'])}")
    if excl:
        parts.append("excludes " + ", ".join(excl) + f" ({MONEY_EXCLUDED})")
    if money["gap"] is not None:
        parts.append(f"customer liabilities exceed the separate customer assets and restricted cash by {fmt_b(money['gap'])}: the "
                     f"unrestricted line may be funding customer obligations ({LIABILITIES_EXCEED})")
    if INSURANCE_FLOAT in money["stamps"]:
        parts.append(f"insurance reserves {fmt_b(money['insurance_reserves'])} ({INSURANCE_FLOAT})")
    return "; ".join(parts) if parts else None


def years35_break_text(vb):
    """Brief 3.3: the years 3-5 clause on a break."""
    return (f"years 3-5 fade from the base-rate median: the vendor's next-FY revenue step ({(vb['r1'] / vb['r0'] - 1) * 100:+.1f}%) is not "
            f"carried by its EPS step ({vb['c2'] * 100:+.1f}%), a change of level, not a growth rate")


def years35_untested_clause(vb):
    """Brief 3.3: the one clause for a step outside the band that cannot be tested."""
    return (f"the vendor's next-FY revenue step ({(vb['r1'] / vb['r0'] - 1) * 100:+.1f}%) could not be tested against its EPS step "
            f"(consensus EPS growth is not usable here)")

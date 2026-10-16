"""Structured pack facts object and sidecar serialization.

Replaces regex scraping of pack text in downstream consumers while preserving
verbatim extraction logic for backwards compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from math import inf, isinf
from typing import Any

# S3 5.2: the DEFAULTS block's consensus_implied_value band uses the same FAR_LOW/FAR_HIGH the
# desk's R10 check does (3.5) - one constant, not a copy. consensus_reference.py lives at
# repo_root/tools and imports nothing of ours, so this import is a leaf, not a cycle.
_REPO_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_REPO_TOOLS) not in sys.path:
    sys.path.insert(0, str(_REPO_TOOLS))
import consensus_reference  # noqa: E402
import pi_text  # noqa: E402
import throughcycle_record  # noqa: E402

FACTS_VERSION = 11
SIDECAR = "_pack_facts.json"

KEYS: list[str] = [
    "consensus_implied_value",
    "years35_p90",
    "reference_status",
    "levels",
    "base_window",
    "next_fy_revenue_growth",
    "shares_outstanding",
    "net_debt_b",
    "terminal_g_default",
    "interest_expense_latest_b",
    "owner_earnings_source",
    "coe_anchor",
    "filed_shares_diluted",
    "filed_shares_fy",
    # version 3 (S3 3.1): five new facts already printed at revision-14 print sites, plus the four
    # share-count keys of 5.11 (never printed before revision 15; None until that briefing work lands).
    "terminal_g_anchor",
    "base_rate_5y",
    "owner_earnings_default_b",
    "cash_basis_b",
    "revenue_cagr_5y_pct",
    "shares_default",
    "shares_dilution_factor",
    "shares_dilution_period",
    "shares_warning",
    # version 4 (S2c): SECTION 8 consensus estimates status
    "consensus_data_status",
    # version 5 (revision 17, brief B): the through-cycle package. `terminal_ronic` is the Base's default
    # terminal return on new investment (a fraction, or +inf); `long_run` the reference's year-5 earnings
    # and the company's record (see `long_run_members`); `working_capital` the reference's five
    # deductions ($B, years 1-5) or None; `base_year_cap` the one-time item removed from the base year
    # (a dict) or None when none was.
    "terminal_ronic",
    "long_run",
    "working_capital",
    "base_year_cap",
    # revision 17, brief C4: the factor that turns the last filed diluted share count into today's when a split came
    # after the last filing (4.0 for a 4-for-1 split, 0.25 for a 1-for-4 reverse split), else None. Same revision,
    # so the version stays 5.
    "split_after_last_filing",
    # revision 17, brief F4: the fiscal-year owner-earnings base the reference grows from ($B, the reference's base_cf), or
    # None. The desk reads it to tell an owner-earnings base from the cash basis (brief F6). Same revision: the version
    # stays 5, and an older sidecar reads it as None.
    "reference_base_b",
    # version 6 (revision 18, brief 1.7): the excess cash the reference adds at face and the desk adds to every scenario
    # ($B: the base fiscal year's cash and short-term investments for a non-financial company, 0.0 for a financial one,
    # None when the cash term is not available). An older sidecar or block reads it as None.
    "excess_cash",
    # revision 18 (review condition): where the premium behind coe_anchor comes from - "closure" (the live reference's rs2
    # closure premium) or "damodaran_point_in_time" (a point-in-time pack, whose closure premium cannot be rebuilt for a past
    # date) - or None when there is no cost of equity.
    "coe_premium_source",
    # revision 19 (AT10 fix item 3): the base fiscal year's cash and short-term investments as filed ($B), for every sector,
    # or None when `cash` is null. The desk refuses an excess_cash above it. An older sidecar or block reads it as None.
    "base_year_cash_and_investments_b",
    # version 7 (revision 19, brief D4): the facts the price-implied solver reads and the DEFAULTS run's own block. `rf_eff` (the risk-free rate the
    # cost of equity is built on) and `nominal_gdp_trend` (the ceiling of the terminal_g search) are the desk's bounds; `reference_path` is the
    # DEFAULTS run's five growth rates at full precision (a levels name: year 1 at 0, year 2 at the level); `price_implied_price` the price the
    # DEFAULTS run was solved at; `price_implied_defaults` what the `price_implied` line prints (see pi_text.quantize_block). The first four are
    # SIDECAR_ONLY: nothing prints them, so a text cannot give them back and the parity check leaves them out.
    "rf_eff",
    "nominal_gdp_trend",
    "reference_path",
    "price_implied_defaults",
    "price_implied_price",
    # version 8 (pack revision 20, brief_input_scope_fixes.md 1.3(c), 1.4, 2.3, 3.3): the input scope of the reference. `nci_attribution`
    # {pi, basis, year, ni_parent_b, ni_incl_nci_b, equity_b, equity_incl_nci_b, stamps} and the base year's `ni_scope` (Fix 1b);
    # `per_share_basis` {status, year, n_common_b, n_common_source, eps_filed, shares_diluted, eps_implied, gap, tolerance, stamps}
    # (Fix 1c); `cash_scope`, `cash_restricted_b`, `customer_money` {assets_b, liabilities_b, gap_b, stamps} and `insurance_reserves_b`
    # (Fix 2b); `vendor_revenue_basis` {status, s, k} (Fix 3). All SIDECAR_ONLY: the DEFAULTS block does not print them (its
    # nci_attribution line is display-only), so a text read gives None and the parity check leaves them out.
    "nci_attribution",
    "ni_scope",
    "per_share_basis",
    "cash_scope",
    "cash_restricted_b",
    "customer_money",
    "insurance_reserves_b",
    "vendor_revenue_basis",
    # version 9 (pack revision 21, brief_rev21.md P3): the PRIMARY SOURCES items the pack printed, per item {id, type, form, accession, filed, period,
    # url, sha256 of its text, chars}; [] when the section printed `not available`. SIDECAR_ONLY: the pack text carries the items' text, not their
    # hashes, so a text read gives None and the parity check leaves it out.
    "primary_sources",
    # version 10 (pack revision 24, PHASE_4_REV24_MUSE.md R24.2): `reference_withheld` is True when the pack does not print the CONSENSUS-IMPLIED
    # VALUE (stage A; the desk's R10 gate is then off) and None for an older pack; a text read gives it from the revision marker. `reference_line`
    # is the reference's SECTION 8 line that was not printed (stage B shows its inputs), or None. SIDECAR_ONLY: the text does not carry it.
    "reference_withheld",
    "reference_line",
    # version 11 (pack revision 24 step 2b, BRIEF_R24_S2b_ranges_gate.md): `long_run_defaults_withheld` is True when the pack prints no default
    # for a long-run judgment (terminal_g, terminal_ronic, the long-run margin and its price-implied run; the pilot arms iii and the revision-24
    # pack) and None otherwise (the rev22 arm, an older pack); a text read gives it from the revision marker, as reference_withheld. The other
    # three are SIDECAR_ONLY: `population_ranges` the POPULATION RANGES section's figures (tools/population_ranges.ranges_for's dict, which the
    # plausibility gate reads), `pilot_arm` the pilot's arm ("rev22", "iii_p50", "iii_no_p50", or None outside the pilot) and `ranges_show_p50`
    # whether the section printed P50.
    "long_run_defaults_withheld",
    "population_ranges",
    "pilot_arm",
    "ranges_show_p50",
    # revision 25 (Stage 0.3, SPEC_rev25_normalization_bridge.md section 8): `desk_schema` is "25.1" for the pilot arms r25_b and r25_c (the desk values
    # a perpetual equity scenario through the normalization bridge) and None for every other arm and pack. SIDECAR_ONLY: no pack text prints it.
    "desk_schema",
]

# keys the DEFAULTS text does not carry: a frozen replay reads them from the sidecar, and a text read gives None (parity ignores them)
SIDECAR_ONLY = ("rf_eff", "nominal_gdp_trend", "reference_path", "price_implied_price",
                "nci_attribution", "ni_scope", "per_share_basis", "cash_scope", "cash_restricted_b", "customer_money", "insurance_reserves_b",
                "vendor_revenue_basis", "primary_sources", "reference_line", "population_ranges", "pilot_arm", "ranges_show_p50", "desk_schema")
# revision 24 (R24.2): the facts a stage-A DEFAULTS block does not print; a text read of such a block gives None for them, so the CIV is taken from
# the facts or the sidecar, never from text, and the parity check leaves them out when either side is a withheld-reference pack
WITHHELD_KEYS = ("consensus_implied_value", "reference_status")
_FIRST_WITHHELD_REVISION = 24
# revision 24 step 2b: the long-run defaults a withheld-defaults block does not print (the facts keep them for the logged reference benchmark), and
# the long_run members of the reference's margin rule it drops; a text read gives None for them, and the parity check leaves them out
WITHHELD_LONG_RUN_KEYS = ("terminal_g_default", "terminal_ronic", "price_implied_defaults", "working_capital")
# step 2c (ruling 12): `working_capital` (the reference's five deductions, its revenue path) is not printed in a withheld-defaults block either: the desk
# deducts working capital on each scenario's own revenue path, and the block prints the display line working_capital_intensity instead
WITHHELD_LONG_RUN_MEMBERS = ("om_5", "m_long", "margin_ratio")
# long_run members the DEFAULTS block never prints and the parity check never compares: the verdict's full stamps, and (revision 24 step 2b) the
# base fiscal year's earnings margin and revenue the desk reads when the facts hold no year-5 revenue (ruling 3) and the implied trajectory needs
LONG_RUN_UNPRINTED = ("stamps_full", "x_L", "rev_L", "revenue_path", "oe_path", "oe_base")
# (step 2c, ruling 12 of step 2b: `revenue_path`, the consensus revenue of years 0-5, and `oe_path`, the consensus owner earnings of years 1-5 it pairs
# with, $B, the common shares' share; the desk builds each scenario's own revenue path from them for the working-capital deduction. Step 2d: `oe_base`,
# the base oe_path was grown from - the reference's owner-earnings base, a levels name's year-1 level - which the desk normalizes the path at)
# version 8's keys (and version 9's primary_sources), None on every text read (legacy or DEFAULTS)
_SCOPE_KEYS = ("nci_attribution", "ni_scope", "per_share_basis", "cash_scope", "cash_restricted_b", "customer_money", "insurance_reserves_b",
               "vendor_revenue_basis", "primary_sources")

# The revision marker (S1's from_text dispatch, section 5.1's line format). The DEFAULTS reader
# serves every revision from 15 on: a later revision changes what the model is told, not this format.
_REVISION_RE = re.compile(r"\(pack revision (\d+)\)")
_FIRST_DEFAULTS_REVISION = 15
# Revision 17: from this revision on the DEFAULTS block carries terminal_ronic, long_run and
# working_capital lines (and base_year_cap when the cap applied); an older block has none of them.
_FIRST_THROUGHCYCLE_REVISION = 17

_DICT_KEYS = ("levels", "base_window", "base_rate_5y", "long_run")

_TERM_ANCHOR_RE = re.compile(r"Long-run nominal growth anchor for terminal_g:\s*([\d.]+)%")
_BASE_RATE_5Y_RE = re.compile(
    r"5y sustained growth, this size bucket \(n=\d+\):\s*"
    r">=10%/yr (-?[\d.]+)%, >=20%/yr (-?[\d.]+)%, >=30%/yr (-?[\d.]+)%, median (-?[\d.]+)%, p90 (-?[\d.]+)%")
_OE_DEFAULT_RE = re.compile(r"\[Arithmetic\] OWNER EARNINGS \(default base_cf\):[^\n]*?=\s*\$(-?[\d.,]+)B")
_CASH_BASIS_RE = re.compile(r"\[Arithmetic\] CASH BASIS \(alternative base_cf\):[^\n]*?=\s*\$(-?[\d.,]+)B")
_REV_CAGR_5Y_RE = re.compile(r"Revenue CAGR, trailing 5 fiscal years:\s*([+-]?[\d.]+)%")

_CIV_RE = re.compile(r"CONSENSUS-IMPLIED VALUE \(reference, not a forecast\): \$([\d,]+\.\d+) per share")
_P90_COND_RE = re.compile(r"realized next-5y revenue CAGR[^\n]*?p90 (-?[\d.]+)%")
_P90_SIZE_RE = re.compile(r"5y sustained growth, this size bucket[^\n]*?p90 (-?[\d.]+)%")

_LEVELS_RE = re.compile(r"Consensus cash-flow levels: year 1 \$(-?[\d.,]+)B, year 2 \$(-?[\d.,]+)B")
_RANGE_RE = re.compile(r"Bull year 2 \$(-?[\d.,]+)B and Bear year 2 \$(-?[\d.,]+)B")

_WINDOW_RE = re.compile(r"BASE WINDOW CHECK: base_window_gap ([+\-]?\d+)%")
_WINDOW_ALT_RE = re.compile(
    r"On the TTM window the consensus path is worth \$([\d,]+\.\d+) per share, "
    r"year-2 cash-flow level \$(-?[\d.,]+)B"
)

_SHARES_RE = re.compile(r"[-*]?\s*Shares outstanding:\s*([0-9,]+(?:\.[0-9]+)?)", re.I)
_NET_DEBT_RE = re.compile(r"NET DEBT \((?:default )?net_debt for the firm frame[^)]*\):[^\n]*?= (-?)\$(-?[\d.,]+)B")
_TERM_DEF_RE = re.compile(r"TERMINAL-GROWTH DEFAULT for this name:\s*([\d.]+)%")
_TERM_ANC_RE = re.compile(r"Long-run nominal growth anchor for terminal_g:\s*([\d.]+)%")

_OE_SOURCE_RE = re.compile(r"OWNER EARNINGS \(default base_cf\):[^\n]*?\(owner_earnings_source: ([\w+]+)\)")
_COE_ANCHOR_RE = re.compile(r"COE ANCHOR for this name:[^\n]*?= ([\d.]+)%")


def empty() -> dict[str, Any]:
    """Return an empty facts dict with version 1 and source None."""
    d: dict[str, Any] = {"version": FACTS_VERSION, "source": None}
    for k in KEYS:
        if k in _DICT_KEYS:
            d[k] = {}
        else:
            d[k] = None
    return d


def revision_of(pack_text: str | None) -> int | None:
    """The revision number the pack text's first line carries ("(pack revision N)"), or None without a marker (revision 24 step 2c)."""
    m = _REVISION_RE.search((pack_text or "").split("\n", 1)[0])
    return int(m.group(1)) if m else None


def is_revision_15(pack_text: str | None) -> bool:
    """True when `pack_text`'s first line carries a revision marker of 15 or later (5.1), so a
    revision-16 pack is read as revision 15 is. The single check `from_text` dispatches on and
    S3 5.12 uses (`contract_fill.fill(..., allow_blend=...)`)."""
    t = pack_text or ""
    m = _REVISION_RE.search(t.split("\n", 1)[0])
    return m is not None and int(m.group(1)) >= _FIRST_DEFAULTS_REVISION


def from_text(pack_text: str | None) -> dict[str, Any]:
    """Parse structured facts from pack text. A text from revision 15 on (first line carries the
    marker "(pack revision N)", N >= 15) is read only from its DEFAULTS block; any other text uses
    the legacy readers verbatim (revisions up to 14, recorded packs, frozen battery packs)."""
    t = pack_text or ""
    if is_revision_15(t):
        return _from_defaults_block(t)
    return _from_legacy_text(t)


def _from_legacy_text(t: str) -> dict[str, Any]:
    """S1's legacy readers, plus one new legacy pattern per version-3 key that already has a
    revision-14 print site (3.1). The four share-count keys of 5.11 have no revision-14 print site,
    so they are never found here and stay None."""
    m_civ = _CIV_RE.search(t)
    civ = float(m_civ.group(1).replace(",", "")) if m_civ else None

    m_p90 = _P90_COND_RE.search(t) or _P90_SIZE_RE.search(t)
    p90 = float(m_p90.group(1)) / 100.0 if m_p90 else None

    ref_status = None
    if m_civ:
        ref_status = "used"
    else:
        m_stat = re.search(r"reference_status: (outside_fence_(?:above|below))", t)
        if m_stat:
            ref_status = m_stat.group(1)
        elif "CONSENSUS-IMPLIED VALUE: not available" in t:
            ref_status = "not_available"

    levels: dict[str, float] = {}
    m_lev = _LEVELS_RE.search(t)
    if m_lev:
        levels["year1"], levels["year2"] = (float(x.replace(",", "")) for x in m_lev.groups())
    m_rng = _RANGE_RE.search(t)
    if m_rng:
        levels["bull2"], levels["bear2"] = (float(x.replace(",", "")) for x in m_rng.groups())

    base_window: dict[str, Any] = {}
    m_win = _WINDOW_RE.search(t)
    if m_win:
        base_window = {"gap": int(m_win.group(1)) / 100.0, "ttm_value": None, "ttm_year2": None}
        m_win_alt = _WINDOW_ALT_RE.search(t)
        if m_win_alt:
            base_window["ttm_value"] = float(m_win_alt.group(1).replace(",", ""))
            base_window["ttm_year2"] = float(m_win_alt.group(2).replace(",", ""))

    # Legacy semantics (3d02fbd next_fy_revenue_growth): the first "next FY" row whose growth cell
    # parses wins; a row without a parsable growth cell is skipped, not the end of the search.
    next_fy_rev = None
    for line in t.splitlines():
        line_clean = line.strip()
        if not line_clean.startswith("|"):
            continue
        cells = [c.strip() for c in line_clean.split("|")]
        if len(cells) > 6 and cells[1].lower() == "next fy":
            m_g = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", cells[6])
            if m_g:
                try:
                    next_fy_rev = round(float(m_g.group(1)) / 100.0, 6)
                    break
                except (ValueError, TypeError):
                    pass

    m_sh = _SHARES_RE.search(t)
    shares = float(m_sh.group(1).replace(",", "")) if m_sh else None

    net_debt = None
    m_nd = _NET_DEBT_RE.search(t)
    if m_nd:
        v = float(m_nd.group(2).replace(",", ""))
        net_debt = -abs(v) if m_nd.group(1) or m_nd.group(2).startswith("-") else v

    term_g = None
    m_tdef = _TERM_DEF_RE.search(t)
    if m_tdef:
        term_g = float(m_tdef.group(1)) / 100.0
    else:
        m_tanc = _TERM_ANC_RE.search(t)
        if m_tanc:
            term_g = float(m_tanc.group(1)) / 100.0

    # Legacy semantics (3d02fbd _pack_interest_expense_b): the first "| FY |" header naming interest
    # expense decides, and its last numeric row wins. One declared deviation: where that header has
    # no exact "interest expense" cell the legacy reader raised ValueError; this returns None, because
    # from_text runs on every pack and a raise here would stop the whole run.
    interest_exp = None
    lines = t.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("| FY |") and "interest expense" in ln:
            cols = [c.strip() for c in ln.strip().strip("|").split("|")]
            if "interest expense" in cols:
                k = cols.index("interest expense")
                for row in lines[i + 2:]:
                    if not row.startswith("|"):
                        break
                    cells = [c.strip() for c in row.strip().strip("|").split("|")]
                    m = re.match(r"\$(-?[\d.,]+)B", cells[k]) if len(cells) > k else None
                    if m:
                        interest_exp = float(m.group(1).replace(",", ""))
            break

    oe_source = None
    m_oe = _OE_SOURCE_RE.search(t)
    if m_oe:
        oe_source = m_oe.group(1)
    elif "[Arithmetic] OWNER EARNINGS (default base_cf):" in t:
        oe_source = "ttm_filed"

    coe = None
    m_coe = _COE_ANCHOR_RE.search(t)
    if m_coe:
        coe = float(m_coe.group(1)) / 100.0

    filed_shares = None
    filed_fy = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("| FY |"):
            cols = [c.strip() for c in ln.strip().strip("|").split("|")]
            if "wtd-avg shares" in cols:
                k = cols.index("wtd-avg shares")
                for row in lines[i + 2:]:
                    if not row.strip().startswith("|"):
                        break
                    cells = [c.strip() for c in row.strip().strip("|").split("|")]
                    # A year row starts with the four-digit fiscal year SECTION 6B prints (str(y));
                    # any other row is not a year row and is skipped, never parsed for digits.
                    if len(cells) > k and re.fullmatch(r"\d{4}", cells[0]):
                        c_clean = cells[k].replace(",", "").strip()
                        if re.match(r"^-?\d+(?:\.\d+)?$", c_clean):
                            filed_shares = float(c_clean)
                            filed_fy = int(cells[0])
                break

    term_g_anchor = None
    m_tanc2 = _TERM_ANCHOR_RE.search(t)
    if m_tanc2:
        term_g_anchor = float(m_tanc2.group(1)) / 100.0

    base_rate_5y: dict[str, float] = {}
    m_br5y = _BASE_RATE_5Y_RE.search(t)
    if m_br5y:
        base_rate_5y = {
            "share_ge_10": float(m_br5y.group(1)),
            "share_ge_20": float(m_br5y.group(2)),
            "share_ge_30": float(m_br5y.group(3)),
            "p50": float(m_br5y.group(4)),
            "p90": float(m_br5y.group(5)),
        }

    oe_default_b = None
    m_oedef = _OE_DEFAULT_RE.search(t)
    if m_oedef:
        oe_default_b = float(m_oedef.group(1).replace(",", ""))

    cash_basis_b = None
    m_cb = _CASH_BASIS_RE.search(t)
    if m_cb:
        cash_basis_b = float(m_cb.group(1).replace(",", ""))

    rev_cagr_5y = None
    m_rc5y = _REV_CAGR_5Y_RE.search(t)
    if m_rc5y:
        rev_cagr_5y = float(m_rc5y.group(1))

    consensus_data_status = None
    for ln in t.splitlines():
        ln_s = ln.strip()
        if ln_s.startswith("- CONSENSUS ESTIMATES: not available") and "stale (> 45 days)" in ln_s:
            consensus_data_status = "stale"
            break
        elif ln_s.startswith("- CONSENSUS ESTIMATES: not available") and "enrich record missing" in ln_s:
            consensus_data_status = "enrich_missing"
            break
        elif ln_s.startswith("- CONSENSUS ESTIMATES: not available") and "the vendor fetch failed" in ln_s:
            consensus_data_status = "fetch_error"
            break
        elif ln_s.startswith("- CONSENSUS ESTIMATES: not available") and "yfinance estimates unavailable" in ln_s:
            consensus_data_status = "estimates_unavailable"
            break
        elif ln_s.startswith("- CONSENSUS ESTIMATES   [yfinance, fetched"):
            consensus_data_status = "ok"
            break
        elif ln_s.startswith("## SECTION 8 - CONSENSUS & MULTIPLES   [not available (point-in-time)"):
            consensus_data_status = "point_in_time"
            break

    return {
        "version": FACTS_VERSION,
        "source": "text",
        "consensus_implied_value": civ,
        "years35_p90": p90,
        "reference_status": ref_status,
        "levels": levels,
        "base_window": base_window,
        "next_fy_revenue_growth": next_fy_rev,
        "shares_outstanding": shares,
        "net_debt_b": net_debt,
        "terminal_g_default": term_g,
        "interest_expense_latest_b": interest_exp,
        "owner_earnings_source": oe_source,
        "coe_anchor": coe,
        "filed_shares_diluted": filed_shares,
        "filed_shares_fy": filed_fy,
        "terminal_g_anchor": term_g_anchor,
        "base_rate_5y": base_rate_5y,
        "owner_earnings_default_b": oe_default_b,
        "cash_basis_b": cash_basis_b,
        "revenue_cagr_5y_pct": rev_cagr_5y,
        # 5.11 (Package C, not yet built): no revision-14 print site exists for these, so the
        # legacy reader never finds them.
        "shares_default": None,
        "shares_dilution_factor": None,
        "shares_dilution_period": None,
        "shares_warning": None,
        "consensus_data_status": consensus_data_status,
        # revision 17: no revision-14 print site exists for these
        "terminal_ronic": None,
        "long_run": {},
        "working_capital": None,
        "base_year_cap": None,
        "split_after_last_filing": None,
        "reference_base_b": None,
        "excess_cash": None,
        "coe_premium_source": None,
        "base_year_cash_and_investments_b": None,
        "rf_eff": None, "nominal_gdp_trend": None, "reference_path": None, "price_implied_defaults": None, "price_implied_price": None,
        **{k: None for k in _SCOPE_KEYS},
        "reference_withheld": None, "reference_line": None,
        "long_run_defaults_withheld": None, "population_ranges": None, "pilot_arm": None, "ranges_show_p50": None,
        "desk_schema": None,
    }


# S3 5.2: the DEFAULTS block's line grammar is `- <key>: <value> | <explanation>`, one fact per
# line. `render_defaults_block` and `_from_defaults_block` are built together so they are exact
# inverses (round-tripped by test_pack_rev15.py): every formatter below has a matching parser.
_NA = "not available"


def _dv_money(v):
    """$B, 3 decimals (e.g. owner_earnings_default_b, cash_basis_b, net_debt_b)."""
    return f"{v:,.3f}" if isinstance(v, (int, float)) else _NA


def _dv_money6(v):
    """$B, 6 decimals ($1,000): reference_base_b, which the desk compares within 2% (a small company's base is
    a few $M)."""
    return f"{v:,.6f}" if isinstance(v, (int, float)) else _NA


def _dv_count(v):
    """A share count, comma-grouped, 0 decimals."""
    return f"{v:,.0f}" if isinstance(v, (int, float)) else _NA


def _dv_rate2(v):
    """A fraction printed as a percent rate, 2 decimals, no sign (coe_anchor, terminal_g_*)."""
    return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else _NA


def _dv_growth1(v):
    """A fraction printed as a signed percent growth rate, 1 decimal."""
    return f"{v * 100:+.1f}%" if isinstance(v, (int, float)) else _NA


def _dv_pct1(v):
    """A fraction printed as an unsigned percent, 1 decimal (years35_p90: never negative)."""
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else _NA


def _dv_str(v):
    return v if isinstance(v, str) and v.strip() else _NA


def _dp_num(raw, pct=False):
    """The inverse of the `_dv_*` formatters above, for a scalar."""
    s = raw.strip()
    if s.lower() == _NA:
        return None
    v = float(s.rstrip("%").replace(",", ""))
    return v / 100.0 if pct else v


def _dp_str(raw):
    s = raw.strip()
    return None if s.lower() == _NA else s


# ---------------------------------------------------------------------------------------------
# Revision 17 (brief B): the four through-cycle facts. Each value the build stamps is quantized to
# the precision the DEFAULTS block prints, by the functions below, so the facts a build holds and
# the facts read back from its own text are equal (the parity check) - and so the desk, which
# reads the facts, agrees with the reference, which computes at full precision, to the cent.
# ---------------------------------------------------------------------------------------------

def q_b(x: float) -> float:
    """A $B figure at the six decimals the DEFAULTS block prints ($1,000)."""
    return float(f"{x:.6f}")


def q_rate(x: float) -> float:
    """A fraction at four decimals of a percent, the way the DEFAULTS block prints it (+/-inf pass)."""
    return x if isinf(x) else float(f"{x * 100:.4f}") / 100.0


def q_months(x: float) -> float:
    return float(f"{x:.4f}")


def q_ratio(x: float) -> float:
    return float(f"{x:.6f}")


def _q(v, fn):
    return None if v is None else fn(v)


LONG_RUN_MEMBERS = ("cycle", "cycle_year", "cycle_years", "e5", "oe5", "m5", "m_tc", "m_years", "r_tc", "r_years", "p",
                    "g_rev", "g_rev_years", "terminal_g_basis", "ni_over_oe", "x_over_oe", "nwc_intensity", "nwc_years",
                    "stub_months", "stamps",
                    # brief F4, revision 18: the operating-margin record and the reference's margin rule (om_trend, the trend
                    # level the margin moves to; revision 17's margin_cell, margin_fraction, r8, r3, r_blend and retention
                    # are gone)
                    "om_tc", "om_trend", "om_L", "om_years", "om_shape", "om_basis", "om_5", "m_long", "margin_ratio")
# a member a DEFAULTS block written before revision 17's brief C7 (x_over_oe), brief F or revision 18 (the rest) does not
# print: read as None, not an error. A revision-17 block's removed members (margin_cell, margin_fraction, r8, r3, r_blend,
# retention) are ignored on read.
_LONG_RUN_NEW_MEMBERS = ("om_tc", "om_trend", "om_L", "om_years", "om_shape", "om_basis", "om_5", "m_long", "margin_ratio")
_LONG_RUN_OPTIONAL_ON_READ = ("x_over_oe",) + _LONG_RUN_NEW_MEMBERS
# how a new member is quantized, printed and read back: margins and rates as rates, the ratios as ratios
_LR_RATES = ("m5", "m_tc", "r_tc", "g_rev", "nwc_intensity", "om_tc", "om_trend", "om_L", "om_5", "m_long")
_LR_RATIOS = ("ni_over_oe", "x_over_oe", "margin_ratio")
_LR_YEARS = ("m_years", "r_years", "g_rev_years", "nwc_years", "om_years")


def _stamp_years(text: str) -> list[int] | None:
    """The years of a year-list stamp body: "2016/2017/2018" (the record's own form) or "2016-2018,2021" (the
    DEFAULTS form). None when `text` is neither."""
    years: list[int] = []
    for tok in re.split(r"[/,]", text):
        m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", tok)
        if not m:
            return None
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if hi < lo:
            return None
        years.extend(range(lo, hi + 1))
    return sorted(set(years))


def _year_runs(years: list[int]) -> str:
    """[2019, 2020, 2023] -> "2019-2020,2023"."""
    runs: list[list[int]] = []
    for y in years:
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def compact_stamps(stamps, window=None) -> list[str]:
    """Revision 17, brief C7: the DEFAULTS form of the record's stamps. A year-list stamp ("amortization_gap:2016/2017/...")
    keeps only the years inside `window` ([first, last], the record's eight-year window; all years when None) and prints
    its runs as ranges ("amortization_gap:2022-2025", "tangible_equity_partial:2019-2020,2023"); a year-list stamp
    with no year left is dropped; every other stamp is unchanged. Reads both forms, so it is idempotent."""
    out: list[str] = []
    for s in stamps or []:
        name, sep, body = str(s).partition(":")
        years = _stamp_years(body) if sep else None
        if years is None:
            out.append(str(s))
            continue
        if window:
            years = [y for y in years if window[0] <= y <= window[1]]
        if years:
            out.append(f"{name}:{_year_runs(years)}")
    return out


def quantize_long_run(d: dict[str, Any] | None) -> dict[str, Any]:
    """The `long_run` fact from raw values: every member of LONG_RUN_MEMBERS (None when unknown),
    numbers at their printed precision. e5 and oe5 come in $B. {} for None or an empty dict.
      cycle True/False/None, cycle_year int/None (the latest year with both falls), cycle_years the list of
      such years, e5/oe5 $B, m5/m_tc/r_tc/g_rev/nwc_intensity fractions
      (r_tc may be +/-inf), m_years/r_years/g_rev_years/nwc_years [first, last, n] or None, p (a
      multiple of 1/8), terminal_g_basis "revenue_trend"/"consensus_fallback", ni_over_oe and x_over_oe ratios (the
      base window's net income, and its earnings before acquired-intangible amortization, over its owner earnings),
      stub_months, stamps a list of strings in the DEFAULTS form (`compact_stamps`). Brief F4, revision 18: om_tc/om_trend/om_L/
      om_5/m_long (the operating-margin record, its trend level and the margins the reference's rule moves), om_years
      [first, last, n] or None, om_shape "swing"/"trend", om_basis "with_amortization"/"without_amortization" (brief F2.1: "pretax_with_amortization"/
      "pretax_without_amortization" where the company files no operating line), margin_ratio a ratio. `stamps_full`, when the raw
      values carry it, is the record's full stamp list for the verdict: it is not printed and not compared."""
    if not d:
        return {}
    out: dict[str, Any] = {}
    for k in LONG_RUN_MEMBERS:
        v = d.get(k)
        if k in ("e5", "oe5"):
            v = _q(v, q_b)
        elif k in _LR_RATES:
            v = _q(v, q_rate)
        elif k == "p":
            v = _q(v, lambda x: float(f"{x:.3f}"))
        elif k in _LR_RATIOS:
            v = _q(v, q_ratio)
        elif k == "stub_months":
            v = _q(v, q_months)
        elif k in _LR_YEARS:
            v = [int(x) for x in v] if v else None
        elif k == "cycle_year":
            v = int(v) if v is not None else None
        elif k == "cycle_years":
            v = [int(x) for x in v] if v else []
        elif k == "stamps":
            v = compact_stamps(v)
        out[k] = v
    if d.get("stamps_full"):
        out["stamps_full"] = list(d["stamps_full"])
    # revision 24 step 2b (ruling 3 of step 2a): the base fiscal year's filed earnings margin (x_L) and revenue ($B, the common shares' share where
    # the facts are attributed); kept for the desk, never printed
    if d.get("x_L") is not None:
        out["x_L"] = q_rate(d["x_L"])
    if d.get("rev_L") is not None:
        out["rev_L"] = q_b(d["rev_L"])
    for k in ("revenue_path", "oe_path"):                  # step 2c: kept for the desk's own-path working capital, never printed
        if isinstance(d.get(k), (list, tuple)):
            out[k] = [q_b(x) for x in d[k]]
    if d.get("oe_base") is not None:                       # step 2d: the base oe_path was grown from, kept with it, never printed
        out["oe_base"] = q_b(d["oe_base"])
    return out


_NONE = "none"


def _dv_rate4(v):
    """A fraction as a percent at four decimals; +inf reads "unlimited"; None reads not available."""
    if not isinstance(v, (int, float)):
        return _NA
    return "unlimited" if v == inf else f"{v * 100:.4f}%"


def _dp_rate4(raw):
    s = raw.strip()
    if s.lower() == _NA:
        return None
    if s == "unlimited":
        return inf
    return float(s.rstrip("%")) / 100.0


def _lr_rate(v):
    """A long_run rate member: percent at four decimals, +inf/-inf spelled, none for None."""
    if v is None:
        return _NONE
    if v == inf:
        return "+inf"
    if v == -inf:
        return "-inf"
    return f"{v * 100:.4f}%"


def _lr_years(v):
    return _NONE if not v else f"{v[0]}-{v[1]}:{v[2]}"


def _fnum(v, fmt):
    return _NONE if v is None else format(v, fmt)


def _render_long_run(lr: dict[str, Any], withhold_long_run: bool = False) -> str:
    """The long_run members as `name=value, ...` (`, `-separated; values carry no comma). `withhold_long_run` (revision 24 step 2b): the members
    of the reference's margin rule (om_5, m_long, margin_ratio) are not printed."""
    if not lr:
        return _NA
    cyc = lr.get("cycle")
    parts = [
        "cycle=" + (_NONE if cyc is None else ("yes" if cyc else "no")),
        "cycle_year=" + _fnum(lr.get("cycle_year"), "d"),
        "cycle_years=" + (";".join(str(y) for y in lr["cycle_years"]) if lr.get("cycle_years") else _NONE),
        "e5=" + _fnum(lr.get("e5"), ".6f"),
        "oe5=" + _fnum(lr.get("oe5"), ".6f"),
        "m5=" + _lr_rate(lr.get("m5")),
        "m_tc=" + _lr_rate(lr.get("m_tc")),
        "m_years=" + _lr_years(lr.get("m_years")),
        "r_tc=" + _lr_rate(lr.get("r_tc")),
        "r_years=" + _lr_years(lr.get("r_years")),
        "p=" + _fnum(lr.get("p"), ".3f"),
        "g_rev=" + _lr_rate(lr.get("g_rev")),
        "g_rev_years=" + _lr_years(lr.get("g_rev_years")),
        "terminal_g_basis=" + (lr.get("terminal_g_basis") or _NONE),
        "ni_over_oe=" + _fnum(lr.get("ni_over_oe"), ".6f"),
        "x_over_oe=" + _fnum(lr.get("x_over_oe"), ".6f"),
        "nwc_intensity=" + _lr_rate(lr.get("nwc_intensity")),
        "nwc_years=" + _lr_years(lr.get("nwc_years")),
        "stub_months=" + _fnum(lr.get("stub_months"), ".4f"),
        "om_tc=" + _lr_rate(lr.get("om_tc")),
        "om_trend=" + _lr_rate(lr.get("om_trend")),
        "om_L=" + _lr_rate(lr.get("om_L")),
        "om_years=" + _lr_years(lr.get("om_years")),
        "om_shape=" + (lr.get("om_shape") or _NONE),
        "om_basis=" + (lr.get("om_basis") or _NONE),
        "om_5=" + _lr_rate(lr.get("om_5")),
        "m_long=" + _lr_rate(lr.get("m_long")),
        "margin_ratio=" + _fnum(lr.get("margin_ratio"), ".6f"),
        "stamps=" + (";".join(compact_stamps(lr["stamps"])) if lr.get("stamps") else _NONE),
    ]
    if withhold_long_run:
        parts = [x for x in parts if x.split("=", 1)[0] not in WITHHELD_LONG_RUN_MEMBERS]
    return ", ".join(parts)


def _parse_long_run(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.lower() == _NA:
        return {}
    raw_members = {}
    for member in s.split(", "):
        k, _, v = member.partition("=")
        raw_members[k.strip()] = v.strip()
    out: dict[str, Any] = {}
    for k in LONG_RUN_MEMBERS:
        v = raw_members.get(k)
        if v is None and k in _LONG_RUN_OPTIONAL_ON_READ:
            out[k] = None
            continue
        if v is None:
            raise ValueError(f"revision-17 DEFAULTS long_run has no {k!r} member")
        if v == _NONE:
            out[k] = [] if k in ("stamps", "cycle_years") else None
        elif k == "cycle":
            out[k] = v == "yes"
        elif k == "cycle_year":
            out[k] = int(v)
        elif k == "cycle_years":
            out[k] = [int(x) for x in v.split(";")]
        elif k in ("e5", "oe5", "stub_months", "p") or k in _LR_RATIOS:
            out[k] = float(v)
        elif k in _LR_RATES:
            out[k] = inf if v == "+inf" else (-inf if v == "-inf" else float(v.rstrip("%")) / 100.0)
        elif k in _LR_YEARS:
            mm = re.fullmatch(r"(\d{4})-(\d{4}):(\d+)", v)
            if not mm:
                raise ValueError(f"revision-17 DEFAULTS long_run {k}={v!r} is not first-last:n")
            out[k] = [int(x) for x in mm.groups()]
        elif k == "stamps":
            out[k] = compact_stamps(v.split(";"))      # reads the record's "2016/2017" form and the ranges alike
        else:                                    # terminal_g_basis, om_shape, om_basis
            out[k] = v
    return out


def _render_working_capital(wc) -> str:
    return ", ".join(f"{x:.6f}" for x in wc) if wc else _NA


def _parse_working_capital(raw: str):
    s = raw.strip()
    if s.lower() == _NA:
        return None
    return [float(x) for x in s.split(", ")]


_CAP_MEMBERS = ("removed", "ni_filed", "ni_capped", "eps_filed", "eps_vendor")


def quantize_base_year_cap(d: dict[str, Any] | None) -> dict[str, float] | None:
    """The `base_year_cap` fact from consensus_reference.base_year_cap's dict (money in dollars,
    per-share figures in dollars): $B at six decimals, EPS at four."""
    if not d:
        return None
    return {"removed": q_b(d["removed"] / 1e9), "ni_filed": q_b(d["ni_filed"] / 1e9),
            "ni_capped": q_b(d["ni_capped"] / 1e9), "eps_filed": float(f"{d['eps_filed']:.4f}"),
            "eps_vendor": float(f"{d['eps_vendor']:.4f}")}


def _render_base_year_cap(c) -> str:
    return (f"removed={c['removed']:.6f}, ni_filed={c['ni_filed']:.6f}, ni_capped={c['ni_capped']:.6f}, "
            f"eps_filed={c['eps_filed']:.4f}, eps_vendor={c['eps_vendor']:.4f}")


def _parse_base_year_cap(raw: str) -> dict[str, float]:
    got = dict(m.strip().split("=", 1) for m in raw.strip().split(", "))
    return {k: float(got[k]) for k in _CAP_MEMBERS}


def _dv_split(m) -> str:
    """The split multiplier as printed: `4` for a 4-for-1 split, `1/4` for a 1-for-4 reverse split."""
    return f"{m:g}" if m >= 1 else f"1/{1 / m:g}"


def _dp_split(raw: str) -> float:
    s = raw.strip()
    if s.startswith("1/"):
        return 1.0 / float(s[2:])
    return float(s)


def _split_explanation(m, confirmed=True) -> str:
    """The split_after_last_filing line's sentence (brief F7). `confirmed`: the company is in the United States and the
    vendor's restated fiscal-year EPS agrees with the filed one (DATA 7 says the same); otherwise the count may equally be
    a different share unit, such as depositary shares, and the sentence says only what is measured."""
    k = m if m >= 1 else 1 / m
    if confirmed:
        if m >= 1:
            return (f"the vendor's share count is {m:g} times the last filed diluted count (DATA 7): the filed per-share "
                    f"figures in DATA 5 and 6 are pre-split, and the BASE-YEAR CHECK uses the "
                    f"filed count x {m:g}")
        return (f"the vendor's share count is 1/{k:g} of the last filed diluted count (DATA 7, a reverse split): the "
                f"filed per-share figures in DATA 5 and 6 are pre-split, and the BASE-YEAR CHECK "
                f"uses the filed count / {k:g}")
    of = f"{m:g} times" if m >= 1 else f"1/{k:g} of"
    use = f"x {m:g}" if m >= 1 else f"/ {k:g}"
    return (f"the vendor's share count is {of} the last filed diluted count (DATA 7): a split after the last filing, or "
            f"a different share unit such as depositary shares; the filed per-share figures in DATA 5 and 6 are on the "
            f"filed unit, and the BASE-YEAR CHECK uses the filed count {use}")


def _years_txt(v) -> str:
    return "the years it holds" if not v else f"FY{v[0]}-FY{v[1]}, {v[2]} years"


def _terminal_g_explanation(f: dict[str, Any]) -> str:
    """The terminal_g_default line's sentence: where the default comes from (brief B section 3)."""
    lr = f.get("long_run") or {}
    tail = "more than 0.5 points away needs terminal_reason"
    basis = lr.get("terminal_g_basis")
    if basis == "revenue_trend" and lr.get("g_rev") is not None:
        yrs = lr.get("g_rev_years")
        span = f"FY{yrs[0]}-FY{yrs[1]}" if yrs else "the years it holds"
        return (f"from your own revenue trend {span}: {lr['g_rev'] * 100:.2f}%/yr, held between breakeven "
                f"inflation and the anchor; {tail}")
    if basis == "consensus_fallback":
        return (f"the next-FY consensus revenue growth rule (your record holds fewer than 5 years of revenue "
                f"or breakeven inflation is missing); {tail}")
    return f"the Base terminal_g; {tail}"


def _terminal_ronic_explanation(f: dict[str, Any], no_marker: bool = False) -> str:
    lr = f.get("long_run") or {}
    tail = "a Base terminal_ronic more than 2 points away needs terminal_reason"
    if no_marker:
        return f"not available: {consensus_reference.NO_MARKER_REASON}; {tail}"
    if "record_not_available" in (lr.get("stamps") or []):
        return (f"the Base terminal return on new investment; your record has fewer than 3 years of returns "
                f"on tangible invested capital, so it is the cost of equity and growth adds no value; {tail}")
    return (f"the Base terminal return on new investment: the cost of equity plus p times the excess over it "
            f"of r_tc, your record's median return on tangible invested capital (both in long_run; p is "
            f"the share of your last eight years above the cost of equity); "
            f"{tail}")


def _long_run_start_clause(f: dict[str, Any]) -> str:
    """The DEFAULTS long_run text's account of where the return on new investment starts. Revision 24 step 2d (cross-check 19, ruling 1): the
    desk starts at r_tc as measured when it is above 0 (+inf included), else at the terminal return itself
    (`consensus_reference.long_run_returns`, through `financial_model_tool._long_run_inputs`); it was max(cost of equity, r_tc)."""
    r_tc = (f.get("long_run") or {}).get("r_tc")
    if isinstance(r_tc, (int, float)) and not isinstance(r_tc, bool) and r_tc > 0:
        return "fades from r_tc (your record's 8-year median return on tangible invested capital) to"
    return ("is held from year 6 (r_tc, your record's 8-year median return on tangible invested capital, is not above zero or is not "
            "available) at")


def _working_capital_explanation(f: dict[str, Any], no_marker: bool = False, withhold_reference: bool = False) -> str:
    lr = f.get("long_run") or {}
    if no_marker:
        return f"not available: {consensus_reference.NO_MARKER_REASON}"
    if not f.get("working_capital"):
        if withhold_reference:          # revision 24 step 2b: a withheld-reference block never says "the reference"
            return ("no working-capital deduction: the pack has no consensus revenue path or your record holds fewer than 5 years with a "
                    "classified balance sheet")
        return ("no working-capital deduction: the reference has no revenue path or your record holds fewer "
                "than 5 years with a classified balance sheet")
    nwc = lr.get("nwc_intensity")
    share = f"{nwc * 100:.2f}% of each year's revenue change" if isinstance(nwc, (int, float)) else "your record's median"
    if withhold_reference:
        return (f"the working capital the consensus revenue path ties up in years 1-5, $B ({share}, median of "
                f"{_years_txt(lr.get('nwc_years'))}; years 1-2 the consensus revenue, years 3-5 next-FY revenue growth fading toward the "
                f"base-rate median), which the desk deducts from every scenario's owner earnings "
                f"unless base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or "
                f"reference_base_b (a base that matches an owner-earnings figure is owner earnings)")
    return (f"the working capital the reference's revenue growth ties up in years 1-5, $B ({share}, median of "
            f"{_years_txt(lr.get('nwc_years'))}), which the desk deducts from every scenario's owner earnings "
            f"unless base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or "
            f"reference_base_b (a base that matches an owner-earnings figure is owner earnings)")


def _working_capital_intensity_line(f: dict[str, Any], no_marker: bool = False) -> str:
    """Revision 24 step 2c (ruling 12 of step 2b): the withheld-defaults block's working-capital line. The desk deducts, in years 1-5, the record's
    intensity times each year's change in the scenario's own revenue path (the consensus revenue path, years 1-2 the consensus revenue and years
    3-5 next-FY revenue growth fading toward the base-rate median, scaled year by year by the scenario's owner earnings over the consensus owner
    earnings); this line prints the intensity, never the reference's schedule. A display line: no facts key is read from it."""
    lr = f.get("long_run") or {}
    nwc, rp = lr.get("nwc_intensity"), lr.get("revenue_path")
    if no_marker:
        return f"- working_capital_intensity: {_NA} | not available: {consensus_reference.NO_MARKER_REASON}"
    if not isinstance(nwc, (int, float)) or isinstance(nwc, bool) or not rp:
        why = ("your record holds fewer than 5 years with a classified balance sheet" if not isinstance(nwc, (int, float)) or isinstance(nwc, bool)
               else "the pack has no consensus revenue path")
        return f"- working_capital_intensity: {_NA} | no working-capital deduction: {why}"
    return (f"- working_capital_intensity: {nwc * 100:.2f}% | your record's median net working capital over revenue ({_years_txt(lr.get('nwc_years'))}); "
            f"in years 1-5 the desk deducts this share of each year's revenue change on each scenario's own revenue path: the consensus revenue "
            f"path (years 1-2 the consensus revenue, years 3-5 next-FY revenue growth fading toward the base-rate median) scaled year by year by "
            f"that scenario's owner earnings over the consensus owner earnings, so a scenario that grows faster ties up more; not when base_cf is "
            f"within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or reference_base_b (a base that matches an owner-earnings "
            f"figure is owner earnings)")


_NCI_BASIS_TXT = {"ni_split": "net-income split", "equity_split": "equity split", "no_nci": "no noncontrolling interest",
                  "unmeasured": "not measurable", "nci_unknown": "not measurable"}


def _nci_defaults_line(f: dict[str, Any]) -> str | None:
    """Revision 20 (brief_input_scope_fixes.md 1.3(d)): the DEFAULTS block's display-only attribution line (it carries no facts key the
    reader parses), printed when pi < 1, pi is not measurable, the base year's net income scope is derived or unknown, or the record is
    mixed - the cases in which the pack prints its NONCONTROLLING INTERESTS line. None otherwise."""
    n = f.get("nci_attribution")
    if not isinstance(n, dict) or not isinstance(n.get("pi"), (int, float)):
        return None
    stamps = n.get("stamps") or []
    unmeasured = "nci_share_unmeasured" in stamps
    mixed = any(str(x).startswith("record_scope_mixed") for x in stamps)
    if not (n["pi"] < 1.0 or unmeasured or mixed or f.get("ni_scope") in ("parent_derived", "nci_unknown")):
        return None
    basis = _NCI_BASIS_TXT.get(n.get("basis"), n.get("basis"))
    if unmeasured:
        return (f"- nci_attribution: π = 100.0% ({basis}, FY{n.get('year')}) | the noncontrolling interests' share cannot be measured, "
                f"so the defaults below are not attributed and include it: an upper bound (NONCONTROLLING INTERESTS, DATA 5)")
    return (f"- nci_attribution: π = {n['pi'] * 100:.1f}% ({basis}, FY{n.get('year')}) | the defaults are the common shares' share of the "
            f"consolidated business (π applied): owner_earnings_default_b, excess_cash, base_year_cash_and_investments_b, reference_base_b, "
            f"levels, working_capital and long_run's e5 and oe5; net income is the company's own; cash_basis_b and the DATA tables are the "
            f"filed figures")


def render_defaults_block(facts: dict[str, Any], split_confirmed: bool | None = None, no_marker: bool = False,
                          withhold_reference: bool = False, withhold_long_run: bool = False) -> str:
    """S3 5.2: the DEFAULTS block, the last block of the pack, printed immediately before the
    TASK. Prints every one of the `KEYS` (one fact per line; revision 17: `base_year_cap` only when
    the cap applied, `split_after_last_filing` only when a split was detected), plus two display-only lines that carry no facts key: the fixed rule lines
    `cash_flow_life` and `price`. The reader (`_from_defaults_block`) ignores display lines.
    Revision 17 removed the `default_exit_multiple` display line: the desk has no exit multiple.
    `split_confirmed` (brief F7, not a fact): whether the split after the last filing is confirmed (a US company whose
    vendor EPS agrees); it chooses the split line's sentence, and None reads as not confirmed. `no_marker` (revision 18, amendment 2,
    not a fact): the history holds no tangible-capital provenance marker for the name, so the three lines derived from its record
    (terminal_ronic, long_run, working_capital) print "not available" and say why. `withhold_reference` (revision 24, R24.2, stage A): the
    consensus_implied_value and reference_status lines are not printed; the facts keep both. `withhold_long_run` (revision 24 step 2b,
    BRIEF_R24_S2b_ranges_gate.md item 2): a long-run judgment gets no default - the terminal_g_default, terminal_ronic and price_implied lines are
    not printed, the long_run line drops the reference's margin rule (om_5, m_long, margin_ratio) and explains the record and the desk's long run,
    and the levels and next_fy_revenue_growth lines print the consensus as evidence (the desk holds nothing at them); the facts keep every value."""
    f = facts

    def line(key, value, explanation):
        return f"- {key}: {value} | {explanation}"

    lines = [
        line("shares_outstanding", _dv_count(f.get("shares_outstanding")),
             "DATA 2, the vendor's basic count"),
        line("shares_dilution_factor",
             f"{f['shares_dilution_factor']:.4f}" if isinstance(f.get("shares_dilution_factor"), (int, float)) else _NA,
             "the company's own diluted EPS (basic / diluted EPS); applied when it is at least 1.05"),
        line("shares_dilution_period", _dv_str(f.get("shares_dilution_period")),
             "the filed period the factor comes from"),
        line("shares_default", _dv_count(f.get("shares_default")),
             "the desk's shares_diluted unless you pass another count with shares_reason"),
        line("shares_warning", _dv_str(f.get("shares_warning")),
             "when present, the desk asks for shares_reason on every call"),
        line("filed_shares_diluted", _dv_count(f.get("filed_shares_diluted")),
             "DATA 6B's latest filed diluted average; with after-interest flows it counts a "
             "convertible's interest twice"),
        line("filed_shares_fy",
             str(int(f["filed_shares_fy"])) if isinstance(f.get("filed_shares_fy"), (int, float)) else _NA,
             "the fiscal year of that average"),
        line("owner_earnings_default_b", _dv_money(f.get("owner_earnings_default_b")),
             "the Base base_cf; more than 2% away needs base_cf_reason"),
        line("owner_earnings_source", _dv_str(f.get("owner_earnings_source")),
             "where that default comes from"),
        line("excess_cash", _dv_money6(f.get("excess_cash")),
             "$B: the base fiscal year's cash and short-term investments at face (0 for a financial company; not "
             "available when the cash term could not be computed, see long_run stamps), which the desk adds per share to "
             "every scenario's value; the owner-earnings default and "
             + ("reference_base_b" if withhold_reference else "the reference base")      # revision 24 step 2b: never "the reference"
             + " exclude the after-tax interest "
             "on it; a different amount needs excess_cash_reason; the desk refuses an amount above "
             "base_year_cash_and_investments_b"),
        line("base_year_cash_and_investments_b", _dv_money6(f.get("base_year_cash_and_investments_b")),
             "the base fiscal year's cash and short-term investments as filed; the desk refuses an excess_cash above it "
             "(cash after the valuation date is already in the cash flows)"),
        line("cash_basis_b", _dv_money(f.get("cash_basis_b")),
             "the alternative base (includes working-capital swings)"),
        line("reference_base_b", _dv_money6(f.get("reference_base_b")),
             # revision 24 step 2a: a withheld-reference block never names the reference
             "the fiscal-year owner-earnings base" if withhold_reference
             else "the fiscal-year owner-earnings base the CONSENSUS-IMPLIED VALUE grows from"),
    ]
    nci_line = _nci_defaults_line(f)
    if nci_line:
        lines.append(nci_line)

    bw = f.get("base_window") or {}
    bw_parts = []
    if isinstance(bw.get("gap"), (int, float)):
        bw_parts.append(f"gap={bw['gap'] * 100:+.0f}%")
    if isinstance(bw.get("ttm_value"), (int, float)) and not withhold_reference:
        # revision 24 step 2a: the TTM window's value is the reference times 1 + gap; a withheld-reference block does not print it (the facts
        # keep it, and parity leaves it out)
        bw_parts.append(f"ttm_value={bw['ttm_value']:,.2f}")
    if isinstance(bw.get("ttm_year2"), (int, float)):
        bw_parts.append(f"ttm_year2={bw['ttm_year2']:.3f}")
    lines.append(line("base_window", ", ".join(bw_parts) if bw_parts else _NA,
                      "information only: the desk's arithmetic does not depend on the window"))

    lines.append(line("coe_anchor", _dv_rate2(f.get("coe_anchor")),
                      "the Base discount rate; more than 1.5 points away needs coe_adjustment_reason"))
    if withhold_reference:
        # revision 24 step 2b: a withheld-reference block never says "the reference"
        lines.append(line("coe_premium_source", _dv_str(f.get("coe_premium_source")),
                          "where the premium behind coe_anchor comes from: live packs use rs2's closure premium; point-in-time packs use "
                          "Damodaran's premium, because the closure premium cannot be rebuilt for a past date"))
    else:
        lines.append(line("coe_premium_source", _dv_str(f.get("coe_premium_source")),
                          "where the premium behind coe_anchor comes from: the live reference uses rs2's closure premium; "
                          "point-in-time packs use Damodaran's premium, because the live reference's closure premium cannot be "
                          "rebuilt for a past date"))
    if not withhold_long_run:
        lines.append(line("terminal_g_default", _dv_rate2(f.get("terminal_g_default")),
                          _terminal_g_explanation(f)))
    lines.append(line("terminal_g_anchor", _dv_rate2(f.get("terminal_g_anchor")),
                      "the long-run nominal growth anchor"))
    if not withhold_long_run:
        lines.append(line("terminal_ronic", _dv_rate4(f.get("terminal_ronic")),
                          _terminal_ronic_explanation(f, no_marker)))
    lr_series = throughcycle_record.margin_series_name((f.get("long_run") or {}).get("om_basis"))
    if withhold_long_run:
        lines.append(line("long_run", _render_long_run(f.get("long_run") or {}, withhold_long_run=True),
                          f"not available: {consensus_reference.NO_MARKER_REASON}" if no_marker else
                          "your record and the year-5 anchor of the desk's long run, not defaults: the desk values years 6 on from X_5 (earnings "
                          "before acquired-intangible amortization; e5 and m5 are the year-5 earnings and earnings margin at the consensus estimates of years 1-2 "
                          "and next-FY revenue growth fading toward the base-rate median in years 3-5, "
                          "and with no year-5 revenue m5 is your base fiscal year's filed earnings margin), pays for growth at a return that "
                          + _long_run_start_clause(f) + " your terminal_ronic, and moves each scenario's earnings margin from its year-5 margin "
                          "to your long_run_margin by the end of the fade; m_tc is your record's 8-year median earnings margin, om_tc, om_L and "
                          f"om_trend its 8-year median, base-year and trend-level {lr_series} margins, r_tc and p its returns on tangible "
                          "invested capital, g_rev its revenue trend; you choose long_run_margin, fade_years, terminal_g and terminal_ronic "
                          "(POPULATION RANGES)"))
    else:
        lines.append(line("long_run", _render_long_run(f.get("long_run") or {}),
                          f"not available: {consensus_reference.NO_MARKER_REASON}" if no_marker else
                          "The desk values years 6 on from X_5 (earnings before acquired-intangible "
                          "amortization), pays for growth at a return that " + _long_run_start_clause(f) + " "
                          "terminal_ronic, and moves the margin from m5 to m_long by year 10 (margin_ratio = m_long / "
                          f"m5; none means the margin is held): om_5, the {lr_series} margin the consensus implies at "
                          f"year 5, moves all the way to om_trend, the trend level of your record's 8-year {lr_series} "
                          "margin (to zero for a loss record). The members are the record "
                          "behind it."))

    lines.append(line("net_debt_b", _dv_money(f.get("net_debt_b")),
                      "the firm frame's net debt; another figure needs net_debt_reason (the "
                      "pack's flows are after interest: value them in the equity frame)"))
    lines.append(line("interest_expense_latest_b", _dv_money(f.get("interest_expense_latest_b")),
                      "the firm frame's interest_addback is at most this"))
    lines.append(line("consensus_data_status", _dv_str(f.get("consensus_data_status")),
                      "ok, or why DATA 8 prints no consensus estimates"))

    civ = f.get("consensus_implied_value")
    if not withhold_reference:          # revision 24 (R24.2): stage A prints neither line
        if isinstance(civ, (int, float)) and not consensus_reference.reference_in_force(f.get("reference_status")):
            # revision 18 (brief 1.5): outside the street-target fence the value is printed as a level check only
            civ_expl = ("outside the street-target fence (reference_status): a level check only; no Base band and no "
                        "guidance_deviation_reason apply to it")
        elif isinstance(civ, (int, float)):
            lo, hi = civ * consensus_reference.FAR_LOW, civ * consensus_reference.FAR_HIGH
            civ_expl = (f"a Base value outside {consensus_reference.FAR_LOW:g}-"
                       f"{consensus_reference.FAR_HIGH:g} of it ({lo:,.2f}-{hi:,.2f}) needs "
                       f"guidance_deviation_reason")
        else:
            civ_expl = (f"a Base value outside {consensus_reference.FAR_LOW:g}-"
                       f"{consensus_reference.FAR_HIGH:g} of it needs guidance_deviation_reason")
        lines.append(line("consensus_implied_value",
                          f"{civ:,.2f}" if isinstance(civ, (int, float)) else _NA, civ_expl))
        lines.append(line("reference_status", _dv_str(f.get("reference_status")),
                          "whether the reference is shown, fenced, not available, or not meaningful (a value of zero "
                          "or less)"))

    lv = f.get("levels") or {}
    lv_parts = [f"{k}={lv[k]:.3f}" for k in ("year1", "year2", "bull2", "bear2")
                if isinstance(lv.get(k), (int, float))]
    if withhold_long_run:
        lines.append(line("levels", ", ".join(lv_parts) if lv_parts else _NA,
                          "what analysts forecast: the consensus cash-flow levels of years 1 and 2 ($B), bull2 and bear2 from the high and "
                          "low EPS estimates; evidence for your own years 1-2, not levels the desk holds; a Bull or Bear more than 15% from "
                          "bull2 or bear2 needs scenario_deviation_reason"))
    else:
        lines.append(line("levels", ", ".join(lv_parts) if lv_parts else _NA,
                          "the desk holds the Base's years 1-2 at year1 and year2 unless you pass "
                          "guidance_deviation_reason (a Base year 2 more than 5% away); a Bull or Bear "
                          "more than 15% from bull2 or bear2 needs scenario_deviation_reason"))
        lines.append(line("price_implied", pi_text.render_line_value(f.get("price_implied_defaults")),
                          "at the DEFAULTS, the value of each judgment input at which the Base equals today's price, the other inputs held; "
                          "the desk returns the same for your own inputs on every run; a verdict of undervalued or overvalued needs a crux on "
                          "one of them (TASK item 6)"))
    cap_fact = f.get("base_year_cap")
    if cap_fact:
        lines.append(line("base_year_cap", _render_base_year_cap(cap_fact),
                          "the base year's filed EPS was more than 2% above the analysts' year-ago EPS, so "
                          "the reference takes base net income as that year-ago EPS times the filed diluted "
                          "shares and lowers its owner-earnings base by removed ($B)"))
    split_fact = f.get("split_after_last_filing")
    if split_fact:
        lines.append(line("split_after_last_filing", _dv_split(split_fact),
                          _split_explanation(split_fact, split_confirmed is True)))
    if withhold_long_run:
        lines.append(_working_capital_intensity_line(f, no_marker))      # step 2c: a display line, no facts key
    else:
        lines.append(line("working_capital", _render_working_capital(f.get("working_capital")),
                          _working_capital_explanation(f, no_marker, withhold_reference)))

    lines.append(line("next_fy_revenue_growth", _dv_growth1(f.get("next_fy_revenue_growth")),
                      "what analysts forecast for next fiscal year's revenue growth; evidence, not a cap: the desk holds no year at it"
                      if withhold_long_run else
                      "Base years 3-5 above it need guidance_deviation_reason, or the desk holds "
                      "them at it"))
    lines.append(line("years35_p90", _dv_pct1(f.get("years35_p90")),
                      "growth above the base-rate p90 needs dated, company-specific evidence (a "
                      "flag, not a veto)"))

    br = f.get("base_rate_5y") or {}
    br_parts = [f"{k}={br[k]:.1f}%" for k in ("share_ge_10", "share_ge_20", "share_ge_30", "p50", "p90")
                if isinstance(br.get(k), (int, float))]
    lines.append(line("base_rate_5y", ", ".join(br_parts) if br_parts else _NA,
                      "the desk ranks the market-implied growth against it"))

    rc5 = f.get("revenue_cagr_5y_pct")
    lines.append(line("revenue_cagr_5y_pct", f"{rc5:+.1f}%" if isinstance(rc5, (int, float)) else _NA,
                      "the desk compares the market-implied growth with it"))

    lines.append('- cash_flow_life: required on every desk call ("perpetual" or years), with '
                 'cash_flow_life_reason')
    lines.append("- price: a Bull value below today's price needs bull_below_price_reason; a "
                 "Bear value above it needs bear_above_price_reason")

    header = ("## DEFAULTS   [each desk input takes this value unless you pass another; a "
             "departure needs the named reason, and the desk asks for it]")
    return header + "\n" + "\n".join(lines)


def _from_defaults_block(t: str) -> dict[str, Any]:
    """Read a revision-15 text's DEFAULTS block (S3 5.2). Raises ValueError when no DEFAULTS
    block is found, or when a facts-key line is missing from it — a revision-15 text never falls
    back to the legacy readers, and the reader never guesses a key."""
    m = re.search(r"^## DEFAULTS\b.*$(\n(?:^-.*$\n?)*)", t, re.MULTILINE)
    if not m:
        raise ValueError("revision-15 text has no DEFAULTS block")
    block = m.group(0)

    def _val(key):
        mm = re.search(rf"^- {re.escape(key)}: (.*?) \| ", block, re.MULTILINE)
        if not mm:
            raise ValueError(f"revision-15 DEFAULTS block has no {key!r} line")
        return mm.group(1)

    def _num(key, pct=False):
        return _dp_num(_val(key), pct=pct)

    def _str(key):
        return _dp_str(_val(key))

    m_rev = _REVISION_RE.search(t.split("\n", 1)[0])
    throughcycle = m_rev is not None and int(m_rev.group(1)) >= _FIRST_THROUGHCYCLE_REVISION
    withheld = m_rev is not None and int(m_rev.group(1)) >= _FIRST_WITHHELD_REVISION
    # revision 24 step 2b: a revision-24 block prints no long-run default (a rev22-arm pack carries the revision-22 marker)

    def _opt(key):
        """A revision-17 line: required from revision 17 on, read when present before it (a block
        rendered by this module under an older marker), else None. base_year_cap and split_after_last_filing print only
        when they apply; reference_base_b (brief F4) is optional on read because a revision-17 text written before it
        existed has no such line."""
        mm = re.search(rf"^- {re.escape(key)}: (.*?) \| ", block, re.MULTILINE)
        if mm:
            return mm.group(1)
        if withheld and key in ("terminal_ronic", "price_implied", "working_capital"):
            return None                 # revision 24 step 2b: not printed; None, never from text
        if throughcycle and key not in ("base_year_cap", "split_after_last_filing", "reference_base_b", "excess_cash", "coe_premium_source",
                                  "base_year_cash_and_investments_b", "price_implied"):
            raise ValueError(f"revision-17 DEFAULTS block has no {key!r} line")
        return None

    shares_outstanding = _num("shares_outstanding")
    shares_dilution_factor = _num("shares_dilution_factor")
    shares_dilution_period = _str("shares_dilution_period")
    shares_default = _num("shares_default")
    shares_warning = _str("shares_warning")
    filed_shares_diluted = _num("filed_shares_diluted")
    _fsfy_raw = _val("filed_shares_fy").strip()
    filed_shares_fy = None if _fsfy_raw.lower() == _NA else int(_fsfy_raw.replace(",", ""))
    owner_earnings_default_b = _num("owner_earnings_default_b")
    owner_earnings_source = _str("owner_earnings_source")
    cash_basis_b = _num("cash_basis_b")

    bw_raw = _val("base_window").strip()
    base_window: dict[str, Any] = {}
    if bw_raw.lower() != _NA:
        # Once the BASE WINDOW CHECK has printed at all, the build always carries all three
        # members (build_pack sets "ttm_value"/"ttm_year2" to an explicit None alongside "gap"
        # when there is no usable TTM alternative) — so a member missing from the rendered line
        # is None, not absent, matching the source dict's shape exactly (the 0.0 rule: explicit
        # None is a value here, distinct from the empty-dict "not printed at all" case above).
        base_window = {"gap": None, "ttm_value": None, "ttm_year2": None}
        # split members on ", " first — ttm_value can itself carry a comma (money, `:,.2f`), so a
        # single regex over the whole string cannot draw the member boundary reliably.
        for member in bw_raw.split(", "):
            mm = re.match(r"(gap|ttm_value|ttm_year2)=(.+)$", member.strip())
            if not mm:
                continue
            bk, bv = mm.groups()
            base_window[bk] = (float(bv.rstrip("%")) / 100.0) if bk == "gap" else float(bv.replace(",", ""))

    coe_anchor = _num("coe_anchor", pct=True)
    terminal_g_default = None if withheld else _num("terminal_g_default", pct=True)
    terminal_g_anchor = _num("terminal_g_anchor", pct=True)
    net_debt_b = _num("net_debt_b")
    interest_expense_latest_b = _num("interest_expense_latest_b")
    consensus_data_status = _str("consensus_data_status")

    # revision 24 (R24.2): a stage-A block prints neither line; the value and the status come from the facts or the sidecar, never from text
    consensus_implied_value = None if withheld else _num("consensus_implied_value")
    reference_status = None if withheld else _str("reference_status")

    lv_raw = _val("levels").strip()
    levels: dict[str, float] = {}
    if lv_raw.lower() != _NA:
        for mm in re.finditer(r"(year1|year2|bull2|bear2)=(-?[\d.,]+)", lv_raw):
            lk, lv = mm.groups()
            levels[lk] = float(lv.replace(",", ""))

    # next_fy_revenue_growth is stamped at its print site as round(x, 6) (capability_test.py's
    # `facts["next_fy_revenue_growth"] = round(float(f"{g*100:+.1f}")/100.0, 6)`), unlike every
    # other pct-scaled fact here (coe_anchor, terminal_g_*, years35_p90), which stay at whatever
    # precision their own `float(...)/100.0` division gives — so this one key needs the same
    # round(x, 6) on the way back in, or the two float reprs of "the same" value can differ.
    _nfrg = _num("next_fy_revenue_growth", pct=True)
    next_fy_revenue_growth = round(_nfrg, 6) if _nfrg is not None else None
    years35_p90 = _num("years35_p90", pct=True)

    br_raw = _val("base_rate_5y").strip()
    base_rate_5y: dict[str, float] = {}
    if br_raw.lower() != _NA:
        for mm in re.finditer(r"(share_ge_10|share_ge_20|share_ge_30|p50|p90)=(-?[\d.]+)%", br_raw):
            rk, rv = mm.groups()
            base_rate_5y[rk] = float(rv)

    revenue_cagr_5y_pct = _num("revenue_cagr_5y_pct")   # stored as a percent number, not a fraction

    _tr = _opt("terminal_ronic")
    terminal_ronic = _dp_rate4(_tr) if _tr is not None else None
    _lr = _opt("long_run")
    long_run = _parse_long_run(_lr) if _lr is not None else {}
    _wc = _opt("working_capital")
    working_capital = _parse_working_capital(_wc) if _wc is not None else None
    _cap = _opt("base_year_cap")
    base_year_cap = _parse_base_year_cap(_cap) if _cap is not None else None
    _split = _opt("split_after_last_filing")
    split_after_last_filing = _dp_split(_split) if _split is not None else None
    _rb = _opt("reference_base_b")
    reference_base_b = _dp_num(_rb) if _rb is not None else None
    _cps = _opt("coe_premium_source")
    coe_premium_source = _dp_str(_cps) if _cps is not None else None
    _ec = _opt("excess_cash")
    excess_cash = _dp_num(_ec) if _ec is not None else None
    _bc = _opt("base_year_cash_and_investments_b")
    base_year_cash_and_investments_b = _dp_num(_bc) if _bc is not None else None
    _pi = _opt("price_implied")
    price_implied_defaults = pi_text.parse_line_value(_pi) if _pi is not None else None

    return {
        "version": FACTS_VERSION,
        "source": "defaults_block",
        "consensus_implied_value": consensus_implied_value,
        "years35_p90": years35_p90,
        "reference_status": reference_status,
        "levels": levels,
        "base_window": base_window,
        "next_fy_revenue_growth": next_fy_revenue_growth,
        "shares_outstanding": shares_outstanding,
        "net_debt_b": net_debt_b,
        "terminal_g_default": terminal_g_default,
        "interest_expense_latest_b": interest_expense_latest_b,
        "owner_earnings_source": owner_earnings_source,
        "coe_anchor": coe_anchor,
        "filed_shares_diluted": filed_shares_diluted,
        "filed_shares_fy": filed_shares_fy,
        "terminal_g_anchor": terminal_g_anchor,
        "base_rate_5y": base_rate_5y,
        "owner_earnings_default_b": owner_earnings_default_b,
        "cash_basis_b": cash_basis_b,
        "revenue_cagr_5y_pct": revenue_cagr_5y_pct,
        "shares_default": shares_default,
        "shares_dilution_factor": shares_dilution_factor,
        "shares_dilution_period": shares_dilution_period,
        "shares_warning": shares_warning,
        "consensus_data_status": consensus_data_status,
        "terminal_ronic": terminal_ronic,
        "long_run": long_run,
        "working_capital": working_capital,
        "base_year_cap": base_year_cap,
        "split_after_last_filing": split_after_last_filing,
        "reference_base_b": reference_base_b,
        "excess_cash": excess_cash,
        "coe_premium_source": coe_premium_source,
        "base_year_cash_and_investments_b": base_year_cash_and_investments_b,
        "rf_eff": None, "nominal_gdp_trend": None, "reference_path": None,
        "price_implied_defaults": price_implied_defaults, "price_implied_price": None,
        **{k: None for k in _SCOPE_KEYS},
        "reference_withheld": True if withheld else None, "reference_line": None,
        "long_run_defaults_withheld": True if withheld else None,
        "population_ranges": None, "pilot_arm": None, "ranges_show_p50": None,
        "desk_schema": None,
    }


def write_sidecar(run_dir: str | Path, facts: dict[str, Any]) -> Path:
    """Write run_dir / SIDECAR as JSON."""
    p = Path(run_dir) / SIDECAR
    p.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def read_sidecar(d: str | Path) -> dict[str, Any] | None:
    """Read SIDECAR from d, returning None if absent. A malformed file raises. An older sidecar
    (written before a KEYS key existed) gets that key set to None — every key, not only S2b's
    two share keys (3.1's "Older sidecars" rule)."""
    p = Path(d) / SIDECAR
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    for k in KEYS:
        if k not in data:
            data[k] = None
    return data


def parity(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Return sorted list of KEYS whose values differ (source and version ignored). Revision 24: WITHHELD_KEYS are left out when either side is a
    withheld-reference pack (its text does not carry them); step 2b: WITHHELD_LONG_RUN_KEYS (and the long_run margin-rule members) when either
    side withheld the long-run defaults."""
    mismatches: list[str] = []
    withheld = a.get("reference_withheld") is True or b.get("reference_withheld") is True
    lr_withheld = a.get("long_run_defaults_withheld") is True or b.get("long_run_defaults_withheld") is True

    def _cmp(k, v):
        # `stamps_full` is the verdict's copy of the record's stamps: the DEFAULTS block prints the window's only; revision 24 step 2b: x_L and
        # rev_L are never printed, and a withheld-defaults block drops the reference's margin-rule members
        if k == "long_run" and isinstance(v, dict):
            drop = LONG_RUN_UNPRINTED + (WITHHELD_LONG_RUN_MEMBERS if lr_withheld else ())
            return {m: x for m, x in v.items() if m not in drop}
        # revision 24 step 2a: a withheld-reference block does not print the TTM window's value (the reference times 1 + gap)
        if k == "base_window" and withheld and isinstance(v, dict):
            return {m: x for m, x in v.items() if m != "ttm_value"}
        return v

    for k in KEYS:
        if k in SIDECAR_ONLY or (withheld and k in WITHHELD_KEYS) or (lr_withheld and k in WITHHELD_LONG_RUN_KEYS):
            continue
        if _cmp(k, a.get(k)) != _cmp(k, b.get(k)):
            mismatches.append(k)
    return sorted(mismatches)

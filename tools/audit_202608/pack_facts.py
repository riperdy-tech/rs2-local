"""Structured pack facts object and sidecar serialization.

Replaces regex scraping of pack text in downstream consumers while preserving
verbatim extraction logic for backwards compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

# S3 5.2: the DEFAULTS block's consensus_implied_value band uses the same FAR_LOW/FAR_HIGH the
# desk's R10 check does (3.5) - one constant, not a copy. consensus_reference.py lives at
# repo_root/tools and imports nothing of ours, so this import is a leaf, not a cycle.
_REPO_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_REPO_TOOLS) not in sys.path:
    sys.path.insert(0, str(_REPO_TOOLS))
import consensus_reference  # noqa: E402

FACTS_VERSION = 4
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
]

# The revision-15 marker (S1's from_text dispatch, section 5.1's line format).
_REV15_MARKER = "(pack revision 15)"

_DICT_KEYS = ("levels", "base_window", "base_rate_5y")

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


def is_revision_15(pack_text: str | None) -> bool:
    """True when `pack_text`'s first line carries the revision-15 marker (5.1). The single check
    `from_text` dispatches on and S3 5.12 uses (`contract_fill.fill(..., allow_blend=...)`)."""
    t = pack_text or ""
    return _REV15_MARKER in t.split("\n", 1)[0]


def from_text(pack_text: str | None) -> dict[str, Any]:
    """Parse structured facts from pack text. A revision-15 text (first line carries the marker
    "(pack revision 15)") is read only from its DEFAULTS block; any other text uses the legacy
    readers verbatim (revisions up to 14, recorded packs, frozen battery packs)."""
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
    }


# S3 5.2: the DEFAULTS block's line grammar is `- <key>: <value> | <explanation>`, one fact per
# line. `render_defaults_block` and `_from_defaults_block` are built together so they are exact
# inverses (round-tripped by test_pack_rev15.py): every formatter below has a matching parser.
_NA = "not available"


def _dv_money(v):
    """$B, 3 decimals (e.g. owner_earnings_default_b, cash_basis_b, net_debt_b)."""
    return f"{v:,.3f}" if isinstance(v, (int, float)) else _NA


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


def render_defaults_block(facts: dict[str, Any], default_exit_multiple: float | None = None) -> str:
    """S3 5.2: the DEFAULTS block, the last block of the pack, printed immediately before the
    TASK. Prints every one of the 24 `KEYS` (one fact per line), plus three display-only lines
    that carry no facts key: `default_exit_multiple` and the two fixed rule lines `cash_flow_life`
    and `price`. The reader (`_from_defaults_block`) ignores display lines.

    `default_exit_multiple` is the caller's own already-computed value (SECTION 1.5's, from
    `_default_exit_multiple_line`'s full-precision `coe_anchor_pct`/`terminal_g` inputs) — not
    recomputed here from `facts["coe_anchor"]`/`facts["terminal_g_default"]`, which are already
    quantized to 2 decimal places and would round the multiple differently (measured: 20.11x from
    the rounded facts against the EZPW worked example's 20.12x from the SECTION 1.5 inputs)."""
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
        line("cash_basis_b", _dv_money(f.get("cash_basis_b")),
             "the alternative base (includes working-capital swings)"),
    ]

    bw = f.get("base_window") or {}
    bw_parts = []
    if isinstance(bw.get("gap"), (int, float)):
        bw_parts.append(f"gap={bw['gap'] * 100:+.0f}%")
    if isinstance(bw.get("ttm_value"), (int, float)):
        bw_parts.append(f"ttm_value={bw['ttm_value']:,.2f}")
    if isinstance(bw.get("ttm_year2"), (int, float)):
        bw_parts.append(f"ttm_year2={bw['ttm_year2']:.3f}")
    lines.append(line("base_window", ", ".join(bw_parts) if bw_parts else _NA,
                      "when printed, base_cf_reason names the window you judge representative "
                      "and the item behind the gap"))

    lines.append(line("coe_anchor", _dv_rate2(f.get("coe_anchor")),
                      "the Base discount rate; more than 1.5 points away needs coe_adjustment_reason"))
    lines.append(line("terminal_g_default", _dv_rate2(f.get("terminal_g_default")),
                      "the Base terminal_g; more than 0.5 points away needs terminal_reason"))
    lines.append(line("terminal_g_anchor", _dv_rate2(f.get("terminal_g_anchor")),
                      "the long-run nominal growth anchor"))

    dex_val = (f"{default_exit_multiple:.2f}x" if isinstance(default_exit_multiple, (int, float))
              else _NA)
    lines.append(line("default_exit_multiple", dex_val,
                      "(1 + g) / (rate - g) at the defaults; a Base multiple implying terminal "
                      "growth more than 0.5 points from terminal_g_default needs terminal_reason"))

    lines.append(line("net_debt_b", _dv_money(f.get("net_debt_b")),
                      "the firm frame's net debt; another figure needs net_debt_reason (the "
                      "pack's flows are after interest: value them in the equity frame)"))
    lines.append(line("interest_expense_latest_b", _dv_money(f.get("interest_expense_latest_b")),
                      "the firm frame's interest_addback is at most this"))
    lines.append(line("consensus_data_status", _dv_str(f.get("consensus_data_status")),
                      "ok, or why DATA 8 prints no consensus estimates"))

    civ = f.get("consensus_implied_value")
    if isinstance(civ, (int, float)):
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
                      "whether the reference is shown, fenced or not available"))

    lv = f.get("levels") or {}
    lv_parts = [f"{k}={lv[k]:.3f}" for k in ("year1", "year2", "bull2", "bear2")
                if isinstance(lv.get(k), (int, float))]
    lines.append(line("levels", ", ".join(lv_parts) if lv_parts else _NA,
                      "a Base year-2 cash flow more than 15% from year2 needs "
                      "guidance_deviation_reason; a Bull or Bear more than 15% from bull2 or "
                      "bear2 needs scenario_deviation_reason"))

    lines.append(line("next_fy_revenue_growth", _dv_growth1(f.get("next_fy_revenue_growth")),
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
    terminal_g_default = _num("terminal_g_default", pct=True)
    terminal_g_anchor = _num("terminal_g_anchor", pct=True)
    # default_exit_multiple: derived, not a facts key — the reader ignores display lines.
    net_debt_b = _num("net_debt_b")
    interest_expense_latest_b = _num("interest_expense_latest_b")
    consensus_data_status = _str("consensus_data_status")

    consensus_implied_value = _num("consensus_implied_value")
    reference_status = _str("reference_status")

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
    """Return sorted list of KEYS whose values differ (source and version ignored)."""
    mismatches: list[str] = []
    for k in KEYS:
        if a.get(k) != b.get(k):
            mismatches.append(k)
    return sorted(mismatches)

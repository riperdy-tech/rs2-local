"""Structured pack facts object and sidecar serialization.

Replaces regex scraping of pack text in downstream consumers while preserving
verbatim extraction logic for backwards compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

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


def from_text(pack_text: str | None) -> dict[str, Any]:
    """Parse structured facts from pack text. A revision-15 text (first line carries the marker
    "(pack revision 15)") is read only from its DEFAULTS block; any other text uses the legacy
    readers verbatim (revisions up to 14, recorded packs, frozen battery packs)."""
    t = pack_text or ""
    first_line = t.split("\n", 1)[0]
    if _REV15_MARKER in first_line:
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


def _from_defaults_block(t: str) -> dict[str, Any]:
    """Read a revision-15 text's DEFAULTS block (section 5.2 of the S3 brief). That block is
    Package C and is not built by this repository yet (PACK_REVISION stays 14), so no real pack
    reaches this path today; it exists so the reader is ready, and is exercised by hand-written
    text in tests. Raises ValueError when no DEFAULTS block is found — a revision-15 text never
    falls back to the legacy readers."""
    m = re.search(r"^## DEFAULTS\b.*$(\n(?:^-.*$\n?)*)", t, re.MULTILINE)
    if not m:
        raise ValueError("revision-15 text has no DEFAULTS block")
    block = m.group(0)

    def _num(pattern, group=1, pct=False):
        mm = re.search(pattern, block)
        if not mm:
            return None
        raw = mm.group(group)
        if raw is None or raw.strip().lower() == "not available":
            return None
        v = float(raw.strip().rstrip("%").replace(",", ""))
        if pct:
            v = v / 100.0
        return v

    def _present(name):
        mm = re.search(rf"^- {re.escape(name)}: (.+)$", block, re.MULTILINE)
        return mm.group(1) if mm else None

    shares_outstanding = _num(r"shares_outstanding: <([^>]+)>")
    shares_default = _num(r"shares_default: <([^>]+)>")
    sdf_line = _present("shares_dilution_factor")
    shares_dilution_factor, shares_dilution_period = None, None
    if sdf_line and not sdf_line.startswith("not available"):
        m_sdf = re.match(r"<([^>]+)> \(<([^>]+)>:", sdf_line)
        if m_sdf:
            shares_dilution_factor = float(m_sdf.group(1))
            shares_dilution_period = m_sdf.group(2)
    sw_line = _present("shares_warning")
    shares_warning = None
    if sw_line:
        m_sw = re.match(r"<([^>]+)>", sw_line)
        if m_sw and m_sw.group(1).strip().lower() != "not available":
            shares_warning = m_sw.group(1)

    oe_line = _present("owner_earnings_default_b")
    oe_default_b, oe_source = None, None
    if oe_line:
        m_oe = re.match(r"<([^>]+)> \(<([^>]+)>\)", oe_line)
        if m_oe and m_oe.group(1).strip().lower() != "not available":
            oe_default_b = float(m_oe.group(1).replace(",", ""))
            oe_source = m_oe.group(2)
    cash_basis_b = _num(r"cash_basis_b: <([^>]+)>,")

    win_line = _present("base_window")
    base_window: dict[str, Any] = {}
    if win_line and not win_line.startswith("not available"):
        m_win = re.match(
            r"gap <([^>]+)>, ttm_value <([^>]+)>, ttm_year2 <([^>]+)>", win_line)
        if m_win:
            g, tv, ty = m_win.groups()
            if g.strip().lower() != "not available":
                base_window["gap"] = float(g.rstrip("%")) / 100.0
            base_window["ttm_value"] = (None if tv.strip().lower() == "not available"
                                        else float(tv.replace(",", "")))
            base_window["ttm_year2"] = (None if ty.strip().lower() == "not available"
                                        else float(ty.replace(",", "")))

    m_coe_raw = re.search(r"coe_anchor: <([^>]+)>", block)
    coe_anchor = None
    if m_coe_raw and m_coe_raw.group(1).strip().lower() != "not available":
        coe_anchor = float(m_coe_raw.group(1).rstrip("%")) / 100.0

    tg_line = _present("terminal_g_default")
    terminal_g_default, terminal_g_anchor = None, None
    if tg_line:
        m_tg = re.match(r"<([^>]+)> \(terminal_g_anchor: <([^>]+)>\)", tg_line)
        if m_tg:
            if m_tg.group(1).strip().lower() != "not available":
                terminal_g_default = float(m_tg.group(1).rstrip("%")) / 100.0
            if m_tg.group(2).strip().lower() != "not available":
                terminal_g_anchor = float(m_tg.group(2).rstrip("%")) / 100.0

    vf_line = _present("valuation_frame")
    net_debt_b, interest_expense_latest_b = None, None
    if vf_line:
        m_ie = re.search(r"interest_expense_latest_b: <([^>]+)>", vf_line)
        if m_ie and m_ie.group(1).strip().lower() != "not available":
            interest_expense_latest_b = float(m_ie.group(1).replace(",", ""))
        m_nd = re.search(r"net_debt_b: <([^>]+)>", vf_line)
        if m_nd and m_nd.group(1).strip().lower() != "not available":
            net_debt_b = float(m_nd.group(1).replace(",", ""))

    civ_line = _present("consensus_implied_value")
    consensus_implied_value, reference_status = None, None
    if civ_line:
        m_civ = re.match(r"<([^>]+)> \(<([^>]+)>\)", civ_line)
        if m_civ and m_civ.group(1).strip().lower() != "not available":
            consensus_implied_value = float(m_civ.group(1).replace(",", ""))
            reference_status = m_civ.group(2)

    lv_line = _present("levels")
    levels: dict[str, float] = {}
    if lv_line and not lv_line.startswith("not available"):
        for mm in re.finditer(r"(year1|year2|bull2|bear2) <([^>]+)>", lv_line):
            k, v = mm.groups()
            if v.strip().lower() != "not available":
                levels[k] = float(v.replace(",", ""))

    next_fy_revenue_growth = _num(r"next_fy_revenue_growth: <([^>]+)>", pct=True)
    years35_p90 = _num(r"years35_p90: <([^>]+)>", pct=True)

    br_line = _present("base_rate_5y")
    base_rate_5y: dict[str, float] = {}
    if br_line and not br_line.startswith("not available"):
        for mm in re.finditer(r"(p50|p90|share_ge_10|share_ge_20|share_ge_30) <([^>]+)>", br_line):
            k, v = mm.groups()
            if v.strip().lower() != "not available":
                base_rate_5y[k] = float(v.strip().rstrip("%").replace(",", ""))

    # stored as a percent number (9.1), not a fraction — matches the revision-14 print site's units
    revenue_cagr_5y_pct = _num(r"revenue_cagr_5y_pct: <([^>]+)>")

    # S2c: read only from its own line. An absent line is None, never inferred from another key:
    # the gate fails a None status closed on gate_version >= 6.
    cds_line = _present("consensus_data_status")
    consensus_data_status = None
    if cds_line:
        m_cds = re.match(r"<([^>]+)>", cds_line)
        if m_cds and m_cds.group(1).strip().lower() != "not available":
            consensus_data_status = m_cds.group(1).strip()

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
        "owner_earnings_source": oe_source,
        "coe_anchor": coe_anchor,
        # Package C has not defined a DEFAULTS line for these two (5.2 is a draft, unreviewed);
        # SECTION 6B's format does not change in this step, so the S1 legacy reader still applies.
        "filed_shares_diluted": _from_legacy_text(t)["filed_shares_diluted"],
        "filed_shares_fy": _from_legacy_text(t)["filed_shares_fy"],
        "terminal_g_anchor": terminal_g_anchor,
        "base_rate_5y": base_rate_5y,
        "owner_earnings_default_b": oe_default_b,
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

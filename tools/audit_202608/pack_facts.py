"""Structured pack facts object and sidecar serialization.

Replaces regex scraping of pack text in downstream consumers while preserving
verbatim extraction logic for backwards compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

FACTS_VERSION = 2
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
]

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
        if k in ("levels", "base_window"):
            d[k] = {}
        else:
            d[k] = None
    return d


def from_text(pack_text: str | None) -> dict[str, Any]:
    """Parse structured facts from pack text using legacy readers verbatim."""
    t = pack_text or ""
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
    }


def write_sidecar(run_dir: str | Path, facts: dict[str, Any]) -> Path:
    """Write run_dir / SIDECAR as JSON."""
    p = Path(run_dir) / SIDECAR
    p.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def read_sidecar(d: str | Path) -> dict[str, Any] | None:
    """Read SIDECAR from d, returning None if absent. A malformed file raises."""
    p = Path(d) / SIDECAR
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    for k in ("filed_shares_diluted", "filed_shares_fy"):
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

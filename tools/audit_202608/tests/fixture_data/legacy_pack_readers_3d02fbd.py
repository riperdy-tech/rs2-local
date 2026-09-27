"""The pack-text readers of consensus_valuation.py at commit 3d02fbd, copied verbatim (source lines
926-967, 993-1027 and 1065-1143 of that file), used only as the oracle in
test_pack_facts_legacy_oracle.py. S1 moved these readers into pack_facts.from_text "verbatim"; this
copy is what "verbatim" is checked against. Do not edit it: it is a record, not code under test."""
import re


_CIV_RE = re.compile(r"CONSENSUS-IMPLIED VALUE \(reference, not a forecast\): \$([\d,]+\.\d+) per share")
_P90_COND_RE = re.compile(r"realized next-5y revenue CAGR[^\n]*?p90 (-?[\d.]+)%")
_P90_SIZE_RE = re.compile(r"5y sustained growth, this size bucket[^\n]*?p90 (-?[\d.]+)%")


_LEVELS_RE = re.compile(r"Consensus cash-flow levels: year 1 \$(-?[\d.,]+)B, year 2 \$(-?[\d.,]+)B")
_RANGE_RE = re.compile(r"Bull year 2 \$(-?[\d.,]+)B and Bear year 2 \$(-?[\d.,]+)B")


def _pack_levels(pack_text):
    """E18: the consensus year-1 and year-2 cash-flow levels ($B) the pack prints, and the Bull and
    Bear year-2 levels when there is a consensus range. {} for a pack printing none (revision <= 9)."""
    t = pack_text or ""
    out = {}
    m = _LEVELS_RE.search(t)
    if m:
        out["year1"], out["year2"] = (float(x.replace(",", "")) for x in m.groups())
    m = _RANGE_RE.search(t)
    if m:
        out["bull2"], out["bear2"] = (float(x.replace(",", "")) for x in m.groups())
    return out


_WINDOW_RE = re.compile(r"BASE WINDOW CHECK: base_window_gap ([+\-]?\d+)%")
_WINDOW_ALT_RE = re.compile(r"On the TTM window the consensus path is worth \$([\d,]+\.\d+) per share, "
                            r"year-2 cash-flow level \$(-?[\d.,]+)B")


def _pack_window(pack_text):
    """Whole-book test: the BASE WINDOW CHECK the pack prints when the fiscal-year and TTM windows
    are more than 15% apart: {'gap', 'ttm_value', 'ttm_year2'}, or {} when none is printed."""
    t = pack_text or ""
    m = _WINDOW_RE.search(t)
    if not m:
        return {}
    out = {"gap": int(m.group(1)) / 100.0, "ttm_value": None, "ttm_year2": None}
    m = _WINDOW_ALT_RE.search(t)
    if m:
        out["ttm_value"] = float(m.group(1).replace(",", ""))
        out["ttm_year2"] = float(m.group(2).replace(",", ""))
    return out

def _pack_reference(pack_text):
    """(consensus-implied value per share, years-3-5 p90 as a fraction) printed in this pack, or
    None for either. Read from the text so frozen battery packs are checked the same way."""
    t = pack_text or ""
    m = _CIV_RE.search(t)
    civ = float(m.group(1).replace(",", "")) if m else None
    m = _P90_COND_RE.search(t) or _P90_SIZE_RE.search(t)
    p90 = float(m.group(1)) / 100.0 if m else None
    return civ, p90


def next_fy_revenue_growth(pack_text: str) -> float | None:
    """Read next-FY consensus revenue growth from the CONSENSUS ESTIMATES table in pack_text.

    The table row '| next FY |' carries revenue growth in its sixth cell (e.g. '+0.9%').
    Returns the rate as a float fraction (e.g. 0.009), or None if unavailable or unparseable.
    """
    if not pack_text:
        return None
    for line in pack_text.splitlines():
        line_clean = line.strip()
        if not line_clean.startswith("|"):
            continue
        cells = [c.strip() for c in line_clean.split("|")]
        # cells: ['', 'next FY', 'revenue avg', 'low', 'high', 'analysts', 'growth', ...]
        if len(cells) > 6 and cells[1].lower() == "next fy":
            growth_str = cells[6]
            m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", growth_str)
            if m:
                try:
                    return round(float(m.group(1)) / 100.0, 6)
                except (ValueError, TypeError):
                    pass
    return None

def _num_b(v):
    """A dollar or share figure in billions (the desk takes billions; raw counts are converted)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 1e9 if abs(x) > 1e6 else x


def _pack_shares_b(pack_text):
    m = re.search(r"[-*]?\s*Shares outstanding:\s*([0-9,]+(?:\.[0-9]+)?)", pack_text or "", re.I)
    return _num_b(m.group(1).replace(",", "")) if m else None


def _pack_net_debt_b(pack_text):
    """SECTION 6's NET DEBT default in $B (negative = net cash), or None."""
    m = re.search(r"NET DEBT \((?:default )?net_debt for the firm frame[^)]*\):[^\n]*?= (-?)\$(-?[\d.,]+)B", pack_text or "")
    if not m:
        return None
    v = float(m.group(2).replace(",", ""))
    return -abs(v) if m.group(1) or m.group(2).startswith("-") else v


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pack_terminal_g(pack_text):
    """SECTION 1.5's TERMINAL-GROWTH DEFAULT when printed, else the long-run growth anchor, as a decimal, or None."""
    m_def = re.search(r"TERMINAL-GROWTH DEFAULT for this name:\s*([\d.]+)%", pack_text or "")
    if m_def:
        return float(m_def.group(1)) / 100.0
    m = re.search(r"Long-run nominal growth anchor for terminal_g:\s*([\d.]+)%", pack_text or "")
    return float(m.group(1)) / 100.0 if m else None


def _pack_interest_expense_b(pack_text):
    """The latest filed interest expense in SECTION 5's fiscal-year table, in $B, or None."""
    lines = (pack_text or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("| FY |") and "interest expense" in ln:
            cols = [c.strip() for c in ln.strip().strip("|").split("|")]
            k = cols.index("interest expense")
            val = None
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                m = re.match(r"\$(-?[\d.,]+)B", cells[k]) if len(cells) > k else None
                if m:
                    val = float(m.group(1).replace(",", ""))
            return val
    return None


def _pack_reference_status(pack_text):
    """E15: "used", "outside_fence_above" / "outside_fence_below", "not_available", or None when the
    pack prints no CONSENSUS-IMPLIED VALUE line at all (the point-in-time path, older packs)."""
    t = pack_text or ""
    if _CIV_RE.search(t):
        return "used"
    m = re.search(r"reference_status: (outside_fence_(?:above|below))", t)
    if m:
        return m.group(1)
    return "not_available" if "CONSENSUS-IMPLIED VALUE: not available" in t else None


def _pack_owner_earnings_source(pack_text):
    """E14: where the pack's OWNER EARNINGS default came from - "ttm_filed", a fallback token
    such as "fy_ni+vendor_capex", or None when the pack prints no default."""
    t = pack_text or ""
    m = re.search(r"OWNER EARNINGS \(default base_cf\):[^\n]*?\(owner_earnings_source: ([\w+]+)\)", t)
    if m:
        return m.group(1)
    return "ttm_filed" if "[Arithmetic] OWNER EARNINGS (default base_cf):" in t else None


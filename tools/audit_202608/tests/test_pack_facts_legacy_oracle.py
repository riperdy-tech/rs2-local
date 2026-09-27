"""Reviewer's check (2026-09-28): `pack_facts.from_text` must return what the legacy prose readers
returned, because brief S1 moved them "verbatim".

The oracle is `fixture_data/legacy_pack_readers_3d02fbd.py`, a verbatim copy of those readers at
commit 3d02fbd. A2 (22 recorded packs) and A3 (291 rebuilt names) found no difference on real packs;
these crafted texts reach the branches real packs do not.

One deviation is deliberate and pinned below. The legacy interest-expense reader raised ValueError
when a '| FY |' header carried 'interest expense' only inside a longer cell. `from_text` returns
None there instead: it now runs on every pack (main()'s parity check and every frozen pack), so a
raise would stop the whole run, where the legacy reader was called only for firm-frame samples.
"""
import importlib.util
from pathlib import Path

import pytest

import capability_test
import pack_facts

_FIXTURE = Path(__file__).resolve().parent / "fixture_data"
_spec = importlib.util.spec_from_file_location(
    "legacy_pack_readers_3d02fbd", _FIXTURE / "legacy_pack_readers_3d02fbd.py")
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)


def _legacy_view(t):
    """The legacy readers' answers, keyed like the facts object (shares compared in billions,
    the unit the legacy share reader returned)."""
    civ, p90 = legacy._pack_reference(t)
    return {
        "consensus_implied_value": civ,
        "years35_p90": p90,
        "reference_status": legacy._pack_reference_status(t),
        "levels": legacy._pack_levels(t),
        "base_window": legacy._pack_window(t),
        "next_fy_revenue_growth": legacy.next_fy_revenue_growth(t),
        "shares_b": legacy._pack_shares_b(t),
        "net_debt_b": legacy._pack_net_debt_b(t),
        "terminal_g_default": legacy._pack_terminal_g(t),
        "interest_expense_latest_b": legacy._pack_interest_expense_b(t),
        "owner_earnings_source": legacy._pack_owner_earnings_source(t),
    }


def _new_view(t):
    f = pack_facts.from_text(t)
    sh = f["shares_outstanding"]
    out = {k: f[k] for k in ("consensus_implied_value", "years35_p90", "reference_status", "levels",
                             "base_window", "next_fy_revenue_growth", "net_debt_b", "terminal_g_default",
                             "interest_expense_latest_b", "owner_earnings_source")}
    out["shares_b"] = legacy._num_b(sh) if sh is not None else None
    return out


EST_HEADER = ("| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | EPS analysts | growth |\n"
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")

# The estimates table prints no next-FY growth (0 analysts), and a later table row also starts
# with "next FY". The legacy reader skipped the first row and read the second.
NEXT_FY_SECOND_ROW = (
    "## SECTION 8 - CONSENSUS & MULTIPLES\n- CONSENSUS ESTIMATES   [yfinance]\n" + EST_HEADER +
    "| current FY | $1.675B | $1.670B | $1.688B | 5 | +31.5% | $2.03 | $2.00 | $2.09 | 4 | +42.1% |\n"
    "| next FY | not available | not available | not available | not available | not available | $2.21 | $2.20 | $2.26 | 4 | +9.0% |\n"
    "\n## SECTION 11 - DEEP RESEARCH BRIEF\n"
    "| metric | a | b | c | d | growth |\n| --- | --- | --- | --- | --- | --- |\n"
    "| next FY | x | y | z | w | +5.0% |\n")

NEXT_FY_FIRST_ROW = (
    "## SECTION 8 - CONSENSUS & MULTIPLES\n" + EST_HEADER +
    "| next FY | $1.834B | $1.789B | $1.899B | 5 | +9.5% | $2.21 | $2.20 | $2.26 | 4 | +9.0% |\n"
    "| next FY | x | y | z | w | +5.0% |\n")

FY_TABLE = (
    "## SECTION 5 - FISCAL-YEAR INCOME & CASH FLOW\n"
    "| FY | revenue | interest expense | SBC |\n| --- | --- | --- | --- |\n"
    "| 2023 | $1.049B | $0.016B | $0.010B |\n"
    "| 2024 | $1.162B | $-0.002B | $0.010B |\n"
    "| 2025 | $1.274B | not available | $0.012B |\n")

MISC = (
    "- Shares outstanding: 61,413,000   [source: vendor financials]\n"
    "- Long-run nominal growth anchor for terminal_g: 3.75%  (asof 2026-09-23)\n"
    "- TERMINAL-GROWTH DEFAULT for this name: 2.34% — next-FY consensus revenue growth is below the anchor\n"
    "- [Arithmetic] NET DEBT (net_debt for the firm frame, which needs a pre-interest flow): total debt $0.518B"
    " − cash $0.470B − short-term investments $0.000B (none filed) = -$0.048B (negative = net cash).\n"
    "- [Arithmetic] OWNER EARNINGS (default base_cf): FY net income $0.110B + D&A (FY2025) $0.033B − vendor"
    " capex $0.039B = $0.104B (owner_earnings_source: fy_ni+vendor_capex). Stock compensation is already expensed.\n"
    "- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $58.92 per share — the analysts' own"
    " path. Consensus cash-flow levels: year 1 $0.147B, year 2 $0.160B — your Base; Bull year 2 $0.164B and"
    " Bear year 2 $0.159B at the next-FY EPS high and low (4 analysts).\n"
    "- [Arithmetic] BASE WINDOW CHECK: base_window_gap -22%. On the TTM window the consensus path is worth"
    " $41.10 per share, year-2 cash-flow level $0.125B.\n"
    "- 5y sustained growth, this size bucket (n=6052): >=10%/yr 26.7%, >=20%/yr 6.8%, >=30%/yr 2.2%,"
    " median 5.6%, p90 16.7%\n")

FENCED = ("- CONSENSUS-IMPLIED VALUE: not used — lands below the fence (reference_status: outside_fence_below).\n"
          "- Shares outstanding: 0\n")

NOT_AVAILABLE = ("- CONSENSUS-IMPLIED VALUE: not available — cost of equity not above terminal growth\n"
                 "- OWNER EARNINGS (default base_cf): not available — TTM capex missing; declare your base and why.\n"
                 "- Long-run nominal growth anchor for terminal_g: not available  (MRI anchor missing)\n")

TEXTS = {
    "gev_golden": (_FIXTURE / "golden_pack_GEV_rev14.md").read_text(encoding="utf-8"),
    "gev_golden_plus_task": ((_FIXTURE / "golden_pack_GEV_rev14.md").read_text(encoding="utf-8")
                             + "\n\n---\n\n" + capability_test.TASK + capability_test.RESEARCH_ADDENDUM),
    "next_fy_second_row": NEXT_FY_SECOND_ROW,
    "next_fy_first_row": NEXT_FY_FIRST_ROW,
    "fy_table": FY_TABLE,
    "misc": MISC,
    "fenced": FENCED,
    "not_available": NOT_AVAILABLE,
    "empty": "",
}


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_from_text_equals_legacy_readers(name):
    t = TEXTS[name]
    assert _new_view(t) == _legacy_view(t)


def test_next_fy_reads_past_a_row_without_growth_as_legacy_did():
    assert pack_facts.from_text(NEXT_FY_SECOND_ROW)["next_fy_revenue_growth"] == 0.05
    assert pack_facts.from_text(NEXT_FY_FIRST_ROW)["next_fy_revenue_growth"] == 0.095


def test_interest_header_without_exact_cell_is_none_not_a_raise():
    t = ("| FY | revenue | interest expense (net) |\n| --- | --- | --- |\n| 2025 | $1.000B | $0.050B |\n\n"
         + FY_TABLE)
    with pytest.raises(ValueError):
        legacy._pack_interest_expense_b(t)
    assert pack_facts.from_text(t)["interest_expense_latest_b"] is None


def test_latest_numeric_interest_expense_is_read():
    assert pack_facts.from_text(FY_TABLE)["interest_expense_latest_b"] == -0.002


def test_task_text_does_not_disturb_the_readers():
    """main() checks parity against the pack with the TASK appended; the TASK must not match any
    reader. Revision 15 rewrites the TASK, so this pins it for that change."""
    base = pack_facts.from_text(TEXTS["gev_golden"])
    assert pack_facts.parity(base, pack_facts.from_text(TEXTS["gev_golden_plus_task"])) == []

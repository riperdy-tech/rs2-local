"""Revision 10 small fixes (operator ruling 2026-09-26), each from a (b) joint review."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import contract_fill  # noqa: E402


# S3 A+B (brief §4.1, §3.8, §4.2, §3.3):
# - the 1.10x/0.90x direction band moved into contract_fill.label (verdict_label is now derived);
# - the takeover-offer sentence and the null-reason rule carry the same doctrine, reworded;
# - the "cash basis [Arithmetic]" / owner-CF doctrine moved to the desk's base_cf_reason argument
#   (named here, not asserted on pack text, since SECTION 3's wording is package C, out of scope);
# - "Base years 1-2 reach those levels..." and the guidance-range fallback are the Growth sub-bullet.
def test_the_task_states_the_direction_band_the_takeover_rule_and_null_reasons():
    assert contract_fill.label(110.0, 100.0) == "undervalued"    # 1.10x
    assert contract_fill.label(109.9, 100.0) == "hold"
    assert contract_fill.label(89.9, 100.0) == "overvalued"      # just past 0.90x
    assert contract_fill.label(90.1, 100.0) == "hold"
    assert "If a public takeover offer is pending, value the business standalone" in cap.TASK
    assert 'A reason is evidence, never text such as "no deviation"; leave a reason out when none is needed.' in cap.TASK
    fm = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")
    assert "base_cf_reason" in fm["function"]["parameters"]["properties"]
    assert "owner CF" not in cap.TASK
    # revision 17: the desk holds the Base's years 1-2 at the levels instead of asking for a reason
    assert "the desk holds the Base's years 1-2 at the consensus cash-flow levels in DEFAULTS unless you give the reason DEFAULTS names for a departure" in cap.TASK
    assert "anchor Bull and Bear to the top and bottom of the company's own guidance range" in cap.TASK


def test_the_base_year_check_and_eps_analyst_count(screener_data_stub, monkeypatch):
    import rs2_data
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00",
          "estimates": {"0y": {"eps": {"avg": 20.0, "low": 18.0, "high": 22.0, "analysts": 25, "growth": 0.13,
                                       "year_ago": 17.70},
                               "revenue": {"avg": 41e9, "low": 40e9, "high": 42e9, "analysts": 24, "growth": 0.08,
                                           "year_ago": 38068000000}},
                        "+1y": {"eps": {"avg": 24.0, "low": 21.0, "high": 27.0, "analysts": 23, "growth": 0.20},
                                "revenue": {"avg": 45e9, "low": 43e9, "high": 47e9, "analysts": 22, "growth": 0.10}}}}
    orig = rs2_data.load_json
    monkeypatch.setattr(rs2_data, "load_json", lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p)
                        else orig(p))
    pack = str(cap.build_pack("GEV"))
    line = next(l for l in pack.splitlines() if "BASE-YEAR CHECK" in l)
    fy_eps = 4.884e9 / 276e6           # the fixture's FY2025 net income / diluted shares = $17.70
    assert f"${fy_eps:.2f}" in line and "year-ago EPS of $17.70" in line and "+0% apart" in line
    assert "| EPS analysts |" in pack and "| $20.00 | $18.00 | $22.00 | 25 |" in pack
    # review B4: without a vintage match the two EPS figures are not on one basis
    del en["estimates"]["0y"]["revenue"]["year_ago"]
    line = next(l for l in str(cap.build_pack("GEV")).splitlines() if "BASE-YEAR CHECK" in l)
    assert line.startswith("- BASE-YEAR CHECK: not available") and "not available to check" in line

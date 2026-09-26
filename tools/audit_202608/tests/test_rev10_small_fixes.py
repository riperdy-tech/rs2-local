"""Revision 10 small fixes (operator ruling 2026-09-26), each from a (b) joint review."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import capability_test as cap  # noqa: E402


def test_the_task_states_the_direction_band_the_takeover_rule_and_null_reasons():
    assert "undervalued means Base IV at least 1.10x today's price, overvalued at most 0.90x" in cap.TASK
    assert "If a public takeover offer for the company is pending, value the business standalone" in cap.TASK
    assert "Reason fields take null when no reason is needed" in cap.TASK
    assert "`cash basis [Arithmetic]`" in cap.TASK and "owner CF" not in cap.TASK
    assert "Base years 1-2 reach those levels from whatever base you declare" in cap.TASK
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

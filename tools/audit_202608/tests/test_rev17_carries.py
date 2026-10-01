"""Revision 17, brief C7: three small carries from brief B2's review.

  a. the long_run DEFAULTS stamps list only the eight window years, as ranges; the facts (the verdict) keep the full list;
     the facts parser reads both forms;
  b. `cycle_not_testable` when fewer than three years could be tested for the cycle;
  c. a desk call without a reference scales the long run by X / owner earnings (`long_run_base_ratio_x`) when the base
     year's amortization is known, else by net income / owner earnings (`long_run_base_ratio_ni`).
"""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import pack_facts  # noqa: E402
import throughcycle_record as tc  # noqa: E402
from test_throughcycle_desk import EZPW_BASE_CF, EZPW_PATH, _direct  # noqa: E402
from test_throughcycle_record import R, history, row  # noqa: E402
from test_throughcycle_reference import _synthetic_pack  # noqa: E402

FULL = "/".join(str(y) for y in range(2014, 2026))


# ---- (a) the stamps -----------------------------------------------------------------------------------------------

def test_compact_stamps_keep_the_window_and_print_runs_as_ranges():
    window = [2018, 2025]
    assert pack_facts.compact_stamps([f"amortization_gap:{FULL}"], window) == ["amortization_gap:2018-2025"]
    assert pack_facts.compact_stamps(["tangible_equity_partial:2014/2015/2019/2020/2023"], window) == \
        ["tangible_equity_partial:2019-2020,2023"]
    assert pack_facts.compact_stamps(["amortization_gap:2022/2023/2024/2025"], window) == ["amortization_gap:2022-2025"]
    assert pack_facts.compact_stamps(["amortization_gap:2021"], window) == ["amortization_gap:2021"]      # one year: no range
    # a stamp with no year left in the window is dropped; every other stamp is untouched and keeps its place
    assert pack_facts.compact_stamps(["tangible_equity_partial:2014/2015", "record_not_available",
                                      "cycle_not_testable"], window) == ["record_not_available", "cycle_not_testable"]
    assert pack_facts.compact_stamps(None) == [] and pack_facts.compact_stamps([]) == []


def test_compact_stamps_read_both_forms_and_are_idempotent():
    once = pack_facts.compact_stamps([f"amortization_gap:{FULL}", "tangible_equity_partial:2019-2020,2023"], [2018, 2025])
    assert once == ["amortization_gap:2018-2025", "tangible_equity_partial:2019-2020,2023"]
    assert pack_facts.compact_stamps(once, [2018, 2025]) == once
    assert pack_facts.compact_stamps(once) == once
    # no window: every year stays (the parser's and the renderer's use)
    assert pack_facts.compact_stamps([f"amortization_gap:{FULL}"]) == ["amortization_gap:2014-2025"]


def _lr(stamps, **kw):
    raw = {"cycle": False, "cycle_year": None, "cycle_years": [], "e5": None, "oe5": None, "m5": None, "m_tc": None,
           "m_years": None, "r_tc": 0.12, "r_years": [2018, 2025, 8], "p": 0.5, "g_rev": None, "g_rev_years": None,
           "terminal_g_basis": "consensus_fallback", "ni_over_oe": 1.1, "x_over_oe": 1.2, "nwc_intensity": None,
           "nwc_years": None, "stub_months": 8.0, "stamps": stamps}
    raw.update(kw)
    return pack_facts.quantize_long_run(raw)


def test_the_defaults_value_prints_ranges_and_the_parser_reads_them_and_the_old_form_back():
    lr = _lr([f"amortization_gap:{FULL}", "tangible_equity_partial:2019/2020/2023"])
    assert lr["stamps"] == ["amortization_gap:2014-2025", "tangible_equity_partial:2019-2020,2023"]
    printed = pack_facts._render_long_run(lr)
    assert "stamps=amortization_gap:2014-2025;tangible_equity_partial:2019-2020,2023" in printed
    assert pack_facts._parse_long_run(printed) == lr
    # a block written before brief C7 (year lists with slashes, no x_over_oe member) reads as the same facts
    old = printed.replace("stamps=amortization_gap:2014-2025;tangible_equity_partial:2019-2020,2023",
                          f"stamps=amortization_gap:{FULL};tangible_equity_partial:2019/2020/2023")
    old = old.replace(", x_over_oe=1.200000", "")
    assert "x_over_oe" not in old
    parsed = pack_facts._parse_long_run(old)
    assert parsed["stamps"] == lr["stamps"] and parsed["x_over_oe"] is None
    assert {k: v for k, v in parsed.items() if k != "x_over_oe"} == {k: v for k, v in lr.items() if k != "x_over_oe"}


def test_the_facts_keep_the_full_list_for_the_verdict_and_parity_ignores_it():
    lr = _lr(["amortization_gap:2018-2025"], stamps_full=[f"amortization_gap:{FULL}"])
    assert lr["stamps"] == ["amortization_gap:2018-2025"] and lr["stamps_full"] == [f"amortization_gap:{FULL}"]
    assert "stamps_full" not in pack_facts._render_long_run(lr) and FULL not in pack_facts._render_long_run(lr)
    facts = dict(pack_facts.empty(), long_run=lr)
    parsed = dict(pack_facts.empty(), long_run=pack_facts._parse_long_run(pack_facts._render_long_run(lr)))
    assert pack_facts.parity(facts, parsed) == []
    other = dict(parsed, long_run=dict(parsed["long_run"], stamps=["amortization_gap:2019-2025"]))
    assert pack_facts.parity(facts, other) == ["long_run"]          # a printed member still counts
    # the verdict carries the whole long_run fact, full list included
    _, st = cv.scenario_checks(Path("nowhere"), {"base_iv": 1.0}, None, "", 1.0, facts=facts)
    assert st["long_run_facts"]["stamps_full"] == [f"amortization_gap:{FULL}"]


def test_in_the_pack_the_block_lists_the_window_and_the_facts_the_twelve_years(screener_data_stub, monkeypatch):
    pack = _synthetic_pack(monkeypatch, drop_goodwill=True)         # goodwill null in every year: partial, 2014-2025
    lr = pack.facts["long_run"]
    # revision 18: the suite's bill rate is "not available" (conftest), so the cash term is stamped after the record's
    assert lr["stamps"] == ["tangible_equity_partial:2018-2025", "cash_term_not_available_no_bill_rate"]
    assert lr["stamps_full"] == [f"tangible_equity_partial:{FULL}", "cash_term_not_available_no_bill_rate"]
    line = next(l for l in str(pack).splitlines() if l.startswith("- long_run: "))
    assert "stamps=tangible_equity_partial:2018-2025;cash_term_not_available_no_bill_rate |" in line
    assert "2014" not in line.split(" | ")[0]
    assert pack_facts.parity(pack.facts, pack_facts.from_text(str(pack))) == []


# ---- (b) cycle_not_testable ---------------------------------------------------------------------------------------

def _rows(n_years, fall_last=False):
    """n_years consecutive rows ending 2025; the last year's revenue and earnings fall by more than the cycle test's
    thresholds when `fall_last`."""
    def make(y):
        last = y == 2025 and fall_last
        return row(y, revenue=800.0 if last else 1000.0, ni=40.0 if last else 100.0, ca=350.0, cl=200.0, cash=100.0)
    return history(2025 - n_years + 1, 2025, make)


@pytest.mark.parametrize("n_years, tested", [(1, 0), (2, 1), (3, 2)])
def test_fewer_than_three_testable_years_is_stamped_and_the_cycle_is_what_it_was(n_years, tested):
    rec = tc.analyse(_rows(n_years), R)
    assert rec["cycle_tested"] == tested and "cycle_not_testable" in rec["stamps"]
    assert rec["cycle"] is (None if tested == 0 else False)          # unchanged: no year tested reads none, none flagged reads no


def test_a_flagged_year_among_two_tested_keeps_the_cycle_yes_and_the_stamp():
    rec = tc.analyse(_rows(3, fall_last=True), R)
    assert rec["cycle_tested"] == 2 and rec["cycle"] is True and rec["cycle_years"] == [2025]
    assert "cycle_not_testable" in rec["stamps"]


def test_three_testable_years_carry_no_stamp():
    rec = tc.analyse(_rows(4), R)
    assert rec["cycle_tested"] == 3 and "cycle_not_testable" not in rec["stamps"]
    assert tc.CYCLE_MIN_TESTED == 3


def test_the_stamp_follows_the_other_stamps_and_a_missing_record_has_no_cycle_test():
    rec = tc.analyse(_rows(2), R)
    assert rec["stamps"] == ["cycle_not_testable"] or rec["stamps"][-1] == "cycle_not_testable"
    assert tc.analyse({}, R)["stamps"] == ["record_not_available"]             # nothing held: no cycle test to stamp


def test_a_record_of_twelve_years_carries_no_stamp_in_the_pack(screener_data_stub, monkeypatch):
    pack = _synthetic_pack(monkeypatch)
    assert "cycle_not_testable" not in pack.facts["long_run"]["stamps"]
    assert "cycle_not_testable" not in str(pack)


# ---- (c) the base ratio -------------------------------------------------------------------------------------------

OE5 = EZPW_BASE_CF * math.prod(1 + g for g in EZPW_PATH)


def test_without_a_reference_the_x_ratio_wins_when_the_amortization_is_known():
    res = _direct(EZPW_PATH, ronic=0.135, long_run={"x_over_oe": 1.25, "ni_over_oe": 0.9})
    assert "long_run_base_ratio_x" in res["stamps"] and "long_run_base_ratio_ni" not in res["stamps"]
    assert res["long_run"]["year5_earnings"] == pytest.approx(1.25 * OE5, abs=1e-4)


def test_without_x_it_scales_by_net_income_as_today_and_stamps_which():
    res = _direct(EZPW_PATH, ronic=0.135, long_run={"x_over_oe": None, "ni_over_oe": 0.9})
    assert "long_run_base_ratio_ni" in res["stamps"] and "long_run_base_ratio_x" not in res["stamps"]
    assert res["long_run"]["year5_earnings"] == pytest.approx(0.9 * OE5, abs=1e-4)
    assert "long_run_base_ratio_ni" in _direct(EZPW_PATH, ronic=0.135, long_run={"ni_over_oe": 0.9})["stamps"]
    # a non-positive x is no x: the net-income ratio still applies; with neither, owner earnings as before
    assert "long_run_base_ratio_ni" in _direct(EZPW_PATH, ronic=0.135, long_run={"x_over_oe": -0.1, "ni_over_oe": 0.9})["stamps"]
    none = _direct(EZPW_PATH, ronic=0.135, long_run={"x_over_oe": -0.1, "ni_over_oe": -0.2})
    assert "long_run_on_owner_earnings" in none["stamps"]
    assert none["long_run"]["year5_earnings"] == pytest.approx(OE5, abs=1e-4)


def test_a_reference_in_the_facts_still_takes_precedence_over_both_ratios():
    lr = {"e5": 0.4, "oe5": 0.3, "m5": None, "x_over_oe": 1.25, "ni_over_oe": 0.9}
    res = _direct(EZPW_PATH, ronic=0.135, long_run=lr)
    assert not any(s.startswith("long_run_base_ratio") for s in res["stamps"])


def test_x_over_owner_earnings_from_the_base_year_amortization():
    fy = {"net_income": 999.0, "amortization_intangibles": 40.0, "pretax_income": 100.0, "tax_provision": 25.0}
    # the window's net income 200 (not the year's 999) plus the year's amortization after its 25% tax rate: X = 230
    assert cap._x_over_owner_earnings(200.0, 250.0, fy, ()) == pytest.approx(230.0 / 250.0)
    # a filer that never tags the amortization: it is known to be none, X = net income
    assert cap._x_over_owner_earnings(200.0, 250.0, dict(fy, amortization_intangibles=None), ("amortization_intangibles",)) == \
        pytest.approx(200.0 / 250.0)
    # a null in a series the filer does tag is a gap: the desk then uses net income
    assert cap._x_over_owner_earnings(200.0, 250.0, dict(fy, amortization_intangibles=None), ()) is None
    # zero amortization is a value, not a gap
    assert cap._x_over_owner_earnings(200.0, 250.0, dict(fy, amortization_intangibles=0.0), ()) == pytest.approx(0.8)
    assert cap._x_over_owner_earnings(200.0, -1.0, fy, ()) is None            # owner earnings not positive
    assert cap._x_over_owner_earnings(200.0, 0.0, fy, ()) is None
    assert cap._x_over_owner_earnings(-50.0, 250.0, fy, ()) is None           # X = -50 + 30 is still negative
    assert cap._x_over_owner_earnings(200.0, 250.0, None, ()) is None and cap._x_over_owner_earnings(200.0, 250.0, {}, ()) is None


def test_the_pack_carries_the_x_ratio_and_the_desk_uses_it(screener_data_stub, monkeypatch):
    pack = _synthetic_pack(monkeypatch)
    lr = pack.facts["long_run"]
    assert lr["ni_over_oe"] is not None and lr["x_over_oe"] is not None and lr["x_over_oe"] > lr["ni_over_oe"]
    oe = pack.facts["owner_earnings_default_b"] * 1e9
    # X - net income = the synthetic base year's amortization (0.05B) after its 25% tax rate
    assert (lr["x_over_oe"] - lr["ni_over_oe"]) * oe == pytest.approx(0.05e9 * 0.75, rel=2e-3)
    assert "x_over_oe=" in str(pack) and pack_facts.parity(pack.facts, pack_facts.from_text(str(pack))) == []
    # a filer that never tags the amortization: X = net income
    untagged = _synthetic_pack(monkeypatch, untagged=["amortization_intangibles"]).facts["long_run"]
    assert untagged["x_over_oe"] == pytest.approx(untagged["ni_over_oe"], rel=1e-6)


def test_a_short_record_stamps_cycle_not_testable_through_the_pack(screener_data_stub, monkeypatch):
    from test_review_b1_b4 import _gev_pack

    def three_years(d):
        for y in list(d["tickers"]["GEV"]):
            if str(y).isdigit() and int(y) < 2023:
                del d["tickers"]["GEV"][y]
        return d

    with monkeypatch.context() as m:
        pack = _gev_pack(m, (12, 31, "ttm"), 38068000000, hist_edit=three_years)
    lr = cap.LAST_PACK_FACTS["long_run"]
    assert "cycle_not_testable" in lr["stamps"] and "cycle_not_testable" in lr["stamps_full"]
    line = next(l for l in pack.splitlines() if l.startswith("- long_run: "))
    assert "cycle_not_testable" in line.split(" | ")[0]
    assert pack_facts.parity(cap.LAST_PACK_FACTS, pack_facts.from_text(pack)) == []

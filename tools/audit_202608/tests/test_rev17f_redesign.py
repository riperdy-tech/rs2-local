"""Revision 17, brief F (the redesigned reference): one owner for the rates, the operating-margin record, the margin rule, the
blended return and its retention, the desk that reads both from the facts, a value that is not meaningful, the working-capital
basis, the share-count wording, and the two carries from brief C (the loop guard's clause, the desk continuation in the
single-turn sessions - the latter is in test_turn_metrics.py and test_window_fix.py).

Fixtures are synthetic (numbers written for the test) except the share-count cases, which use brief D's pinned data
(fixture_data/split_wording: MNST, IESC, POWL and EMBJ).
"""
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import throughcycle_record as tc  # noqa: E402
from test_review_b1_b4 import _byc, _gev_pack as _gev_pack_in  # noqa: E402
from test_throughcycle_record import R, history, row  # noqa: E402
from test_throughcycle_reference import (COE, GA, MEDIAN5, REDUCTION, _synthetic_pack, ref_long_run_margin)  # noqa: E402

B = 1e9
INF = math.inf
# brief F2.4: the file is pinned by its content (sha256 of the canonical JSON), so git's line-ending handling cannot break it.
# Provenance: brief E3 (Amendment 1) wrote v2 as bytes with sha256 6d18ca892d33ef77376b8a1294dc44b6cf94fbf1bd1894691049d16440bf46f8 (CRLF);
# its parent, brief E's v1, has sha256 c8decac70057a7e0484ef0bd1ddfccc6ac0607cb486deb6d15a2bff12e91a04e. v2 differs from v1 only in cells.loss.
CALIBRATION_RAW_SHA256 = "6d18ca892d33ef77376b8a1294dc44b6cf94fbf1bd1894691049d16440bf46f8"
CALIBRATION_CONTENT_SHA256 = "c112690fa8ddd108df738c4df926a64358b27bb1ce019adc6abd74d3cbb30151"
FIX = Path(__file__).resolve().parent / "fixture_data" / "split_wording"


# ---- F0, revision 18: the calibration file is unused ------------------------------------------------------------------------

def test_the_calibration_file_stays_on_disk_unused_and_its_loader_the_blend_and_the_caps_are_gone():
    """Revision 18 (brief 1.1, 1.2): the five margin fractions, the blend weight and the retention caps are not read by any
    code. The file stays on disk, byte for byte (nothing is deleted), and the loader, the capped returns and their
    constants are gone."""
    path = Path(tc.__file__).resolve().parent / "reference_calibration_v2.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == CALIBRATION_CONTENT_SHA256
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw.replace(b"\n", b"\r\n")).hexdigest() == CALIBRATION_RAW_SHA256
    for gone in ("calibration", "CALIBRATION_FILE", "retention_cap", "capped_return", "R_CAP_LOW", "R_CAP_HIGH", "CELL_NAMES",
                 "RETENTION_BUCKETS", "R3_MIN_YEARS"):
        assert not hasattr(tc, gone), gone
    repo = HERE.parent
    sources = list((repo / "tools").glob("*.py")) + list((repo / "tools" / "audit_202608").glob("*.py")) + list(repo.glob("*.py"))
    assert len(sources) > 20
    offenders = [p.name for p in sources if "CALIBRATION_FILE" in p.read_text(encoding="utf-8", errors="replace")]
    assert offenders == [], offenders


# ---- F1: the operating-margin record --------------------------------------------------------------------------------------

OI = {2018: 100.0, 2019: 110.0, 2020: 90.0, 2021: 120.0, 2022: 100.0, 2023: 90.0, 2024: 100.0, 2025: 200.0}


def _op_rows(oi=None, amort=20.0, first=2014, **kw):
    """Revenue 1000 every year; operating income `oi` ({year: value}, 100 where not given); acquired-intangible
    amortization `amort` (a number, or a {year: value} with None for a gap)."""
    oi = {**OI, **(oi or {})}
    a = (lambda y: amort.get(y)) if isinstance(amort, dict) else (lambda y: amort)
    return history(first, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=oi.get(y, 100.0), amort=a(y), **kw))


def test_the_operating_margin_is_operating_income_plus_amortization_over_revenue():
    rec = tc.analyse(_op_rows(), R)
    # OM_y = (oi + 20) / 1000 for 2018-2025: .12 .13 .11 .14 .12 .11 .12 .22 -> median .12, base year .22
    assert rec["om_basis"] == "with_amortization" and rec["om_years"] == list(range(2018, 2026))
    assert rec["om_tc"] == pytest.approx(0.12) and rec["om_L"] == pytest.approx(0.22)
    # the year-by-year values equal to the median are dropped, the rest alternate + - + - +: four crossings, a swing
    assert rec["om_crossings"] == 4 and rec["om_shape"] == "swing"
    assert not any(s.startswith("operating_margin") for s in rec["stamps"])
    # x_L is the base year's earnings margin (X = 100 + 20 x (1 - 0.21), the default tax rate) and tax_L its tax rate
    assert rec["x_L"] == pytest.approx(115.8 / 1000.0) and rec["tax_L"] == tc.TAX_DEFAULT
    # a year with revenue not above 0 is undefined
    assert tc.operating_margin(row(2025, revenue=0.0, oi=10.0)) is None and tc.operating_margin(row(2025, revenue=-5.0, oi=10.0)) is None
    assert tc.operating_margin(row(2025, revenue=100.0, oi=None)) is None
    assert tc.operating_margin(row(2025, revenue=100.0, oi=0.0, amort=0.0)) == 0.0            # 0.0 is a value


def test_an_untagged_amortization_field_counts_zero_and_a_gap_in_a_tagged_series_makes_the_year_undefined():
    untagged = tc.analyse(_op_rows(amort=None), R, untagged_fields=["amortization_intangibles"])
    assert untagged["om_basis"] == "with_amortization" and untagged["om_L"] == pytest.approx(0.20)   # 200 / 1000
    assert untagged["om_years"] == list(range(2018, 2026)) and not any(s.startswith("operating_margin") for s in untagged["stamps"])
    gap = tc.analyse(_op_rows(amort={y: (None if y == 2021 else 20.0) for y in range(2014, 2026)}), R)
    assert gap["om_years"] == [2018, 2019, 2020, 2022, 2023, 2024, 2025]                              # 2021 undefined, seven left
    assert gap["om_basis"] == "with_amortization" and gap["om_tc"] == pytest.approx(0.12)


def test_fewer_than_five_strict_years_or_an_undefined_base_year_fall_back_to_operating_income_over_revenue():
    # amortization tagged but null in four of the eight window years: four strict years, so the plain series for every year
    few = tc.analyse(_op_rows(amort={y: (None if y in (2019, 2020, 2021, 2022) else 20.0) for y in range(2014, 2026)}), R)
    assert few["om_basis"] == "without_amortization" and few["om_years"] == list(range(2018, 2026))
    assert "operating_margin_without_amortization" in few["stamps"]
    assert few["om_L"] == pytest.approx(0.20) and few["om_tc"] == pytest.approx(0.10)                # (oi) / 1000 for every year
    # the base year's own amortization is a gap: seven strict years but none at L, so the plain series too
    at_l = tc.analyse(_op_rows(amort={y: (None if y == 2025 else 20.0) for y in range(2014, 2026)}), R)
    assert at_l["om_basis"] == "without_amortization" and at_l["om_L"] == pytest.approx(0.20)
    assert "operating_margin_without_amortization" in at_l["stamps"]


def test_no_operating_margin_record_when_even_the_fallback_has_too_few_years_or_none_at_the_base_year():
    for oi in ({y: None for y in (2018, 2019, 2020, 2021)},                     # four years of operating income
               {2025: None}):                                                   # none in the base year
        rec = tc.analyse(_op_rows(oi=oi), R)
        assert rec["om_tc"] is None and rec["om_L"] is None and rec["om_years"] is None and rec["om_shape"] is None
        assert rec["om_basis"] is None and rec["om_crossings"] is None
        # brief F2.1: neither the operating nor the pre-tax line gives a record, so the stamp names neither
        assert "margin_record_not_available" in rec["stamps"]
        assert "operating_margin_record_not_available" not in rec["stamps"] and "margin_record_pretax" not in rec["stamps"]
        assert "operating_margin_without_amortization" not in rec["stamps"]
    # nothing held at all
    assert "margin_record_not_available" not in tc.analyse({}, R)["stamps"]      # the record itself is not available


# ---- F2.1: the pre-tax margin record, for a company with no operating-income line -------------------------------------------

PT = {2018: 100.0, 2019: 110.0, 2020: 90.0, 2021: 120.0, 2022: 100.0, 2023: 90.0, 2024: 100.0, 2025: 200.0}


def _pt_rows(pt=None, amort=20.0, first=2014, oi=None, **kw):
    """Like `_op_rows`, but a company that files pre-tax income and no operating-income line (`oi`, None every year unless
    given as {year: value}): revenue 1000, pre-tax income `pt` ({year: value}, 100 where not given)."""
    pt = {**PT, **(pt or {})}
    a = (lambda y: amort.get(y)) if isinstance(amort, dict) else (lambda y: amort)
    return history(first, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=(oi or {}).get(y), pretax=pt.get(y, 100.0),
                                              amort=a(y), **kw))


def test_a_company_with_no_operating_line_gets_the_pretax_margin_record_with_the_same_definition_and_cells():
    rec = tc.analyse(_pt_rows(), R)
    # PT_y = (pre-tax income + 20) / 1000 for 2018-2025: .12 .13 .11 .14 .12 .11 .12 .22, median .12, base year .22
    assert rec["om_basis"] == "pretax_with_amortization" and rec["om_years"] == list(range(2018, 2026))
    assert rec["om_tc"] == pytest.approx(0.12) and rec["om_L"] == pytest.approx(0.22)
    assert rec["om_crossings"] == 4 and rec["om_shape"] == "swing"
    assert "margin_record_pretax" in rec["stamps"]
    assert "margin_record_not_available" not in rec["stamps"] and not any(s.startswith("operating_margin") for s in rec["stamps"])
    # the earnings margin the margin rule converts from is the base year's X / revenue, whichever line the record is on
    assert rec["x_L"] == pytest.approx(115.8 / 1000.0) and rec["tax_L"] == tc.TAX_DEFAULT
    # the series' pieces: 0.0 is a value; revenue must be positive; an untagged amortization counts 0; a tagged gap is undefined
    assert tc.pretax_margin(row(2025, revenue=100.0, oi=None, pretax=0.0, amort=0.0)) == 0.0
    assert tc.pretax_margin(row(2025, revenue=0.0, oi=None, pretax=10.0)) is None
    assert tc.pretax_margin(row(2025, revenue=100.0, oi=None, pretax=None)) is None
    assert tc.pretax_margin(row(2025, revenue=100.0, oi=None, pretax=10.0, amort=None)) is None
    assert tc.pretax_margin(row(2025, revenue=100.0, oi=None, pretax=10.0, amort=None), ("amortization_intangibles",)) == 0.1
    assert tc.pretax_margin_plain(row(2025, revenue=100.0, oi=None, pretax=-4.0)) == -0.04 and tc.pretax_margin_plain(row(2025, oi=None)) is None


def test_the_pretax_record_has_the_same_strict_then_plain_fallback_and_an_untagged_amortization_counts_zero():
    untagged = tc.analyse(_pt_rows(amort=None), R, untagged_fields=["amortization_intangibles"])
    assert untagged["om_basis"] == "pretax_with_amortization" and untagged["om_L"] == pytest.approx(0.20)   # 200 / 1000
    assert untagged["om_years"] == list(range(2018, 2026)) and "margin_record_pretax" in untagged["stamps"]
    # amortization tagged but null in four of the eight window years: four strict years, so pre-tax income / revenue for every year
    few = tc.analyse(_pt_rows(amort={y: (None if y in (2019, 2020, 2021, 2022) else 20.0) for y in range(2014, 2026)}), R)
    assert few["om_basis"] == "pretax_without_amortization" and few["om_years"] == list(range(2018, 2026))
    assert few["om_L"] == pytest.approx(0.20) and few["om_tc"] == pytest.approx(0.10)                    # pretax / 1000
    assert "margin_record_pretax" in few["stamps"] and "operating_margin_without_amortization" not in few["stamps"]
    # the base year's own amortization is a gap: seven strict years but none at L, so the plain series too
    at_l = tc.analyse(_pt_rows(amort={y: (None if y == 2025 else 20.0) for y in range(2014, 2026)}), R)
    assert at_l["om_basis"] == "pretax_without_amortization" and at_l["om_L"] == pytest.approx(0.20)


def test_the_operating_record_comes_first_and_the_pretax_one_only_when_neither_operating_series_gives_a_record():
    both = tc.analyse(_op_rows(pretax=50.0), R)
    assert both["om_basis"] == "with_amortization" and both["om_L"] == pytest.approx(0.22)          # the operating values
    assert "margin_record_pretax" not in both["stamps"]
    # operating income held in four years only (four are too few, with or without amortization): the pre-tax line is used
    four = {y: (100.0 if y >= 2022 else None) for y in range(2014, 2026)}
    rec = tc.analyse(_pt_rows(oi=four), R)
    assert rec["om_basis"] == "pretax_with_amortization" and "margin_record_pretax" in rec["stamps"]
    # neither line has five years: the record is not available, whatever it once was called
    short = tc.analyse(_pt_rows(pt={y: None for y in (2018, 2019, 2020, 2021)}), R)
    assert short["om_tc"] is None and short["om_L"] is None and short["om_basis"] is None and short["om_shape"] is None
    assert "margin_record_not_available" in short["stamps"] and "margin_record_pretax" not in short["stamps"]


def test_the_model_visible_name_of_the_margin_series_follows_om_basis():
    assert tc.margin_series_name("pretax_with_amortization") == tc.margin_series_name("pretax_without_amortization") == "pre-tax"
    assert tc.margin_series_name("with_amortization") == tc.margin_series_name("without_amortization") == "operating"
    assert tc.margin_series_name(None) == "operating"                                      # an older block has no basis


def test_crossings_drop_values_equal_to_the_median_and_count_sign_changes():
    assert tc.crossings({2018: 0.2, 2019: 0.1, 2020: 0.2, 2021: 0.1}, 0.15) == 3
    assert tc.crossings({2018: 0.2, 2019: 0.2, 2020: 0.1, 2021: 0.1}, 0.15) == 1
    assert tc.crossings({2018: 0.2, 2019: 0.3, 2020: 0.4}, 0.15) == 0
    assert tc.crossings({2018: 0.2, 2019: 0.15, 2020: 0.1}, 0.15) == 1                # the equal value is dropped, not a crossing
    assert tc.crossings({2018: 0.2, 2019: 0.15, 2020: 0.25}, 0.15) == 0               # ... and does not split a run
    assert tc.crossings({2020: 0.1, 2018: 0.2, 2019: 0.1}, 0.15) == 1                 # ordered by year, not by insertion
    assert tc.crossings({}, 0.15) == 0
    # the shape: two or more crossings swing, one or none trends
    two = _op_rows(oi={2018: 200.0, 2019: 50.0, 2020: 200.0, 2021: 200.0, 2022: 200.0, 2023: 50.0, 2024: 50.0, 2025: 50.0})
    assert tc.analyse(two, R)["om_crossings"] == 3 and tc.analyse(two, R)["om_shape"] == "swing"
    one = _op_rows(oi={2018: 200.0, 2019: 200.0, 2020: 200.0, 2021: 200.0, 2022: 50.0, 2023: 50.0, 2024: 50.0, 2025: 50.0})
    assert tc.analyse(one, R)["om_crossings"] == 1 and tc.analyse(one, R)["om_shape"] == "trend"


def test_the_cycle_test_is_still_computed_as_an_annotation():
    rows = history(2014, 2025, lambda y: row(y, revenue=(700.0 if y == 2022 else 1000.0), ni=(30.0 if y == 2022 else 100.0)))
    rec = tc.analyse(rows, R)
    assert rec["cycle"] is True and rec["cycle_years"] == [2022] and rec["cycle_year"] == 2022


# ---- F3, revision 18: returns on new capital - the original rule -------------------------------------------------------------

def _return_rows(ni_by_year, equity=500.0, **kw):
    return history(2014, 2025, lambda y: row(y, ni=ni_by_year(y), equity=equity, **kw))


def test_the_uncapped_returns_set_r_tc_and_ronic_t_and_the_blend_members_are_gone():
    # 2018-2022 an infinite return (negative capital, positive profit), 2023-2025 the -inf side
    rows = history(2014, 2025, lambda y: row(y, ni=(100.0 if y <= 2022 else -10.0), equity=200.0, goodwill=250.0,
                                              intangibles=50.0))
    rec = tc.analyse(rows, R)
    assert rec["R_tc"] == INF and rec["p"] == 5 / 8
    assert rec["ronic_t"] == INF                                          # +inf when R_tc is +inf, whatever p is
    # a finite return above the old cap: R = 100 / 40 = 2.5 (tangible capital 40), kept as it is
    high = tc.analyse(_return_rows(lambda y: 100.0, equity=40.0), R)
    assert high["R_tc"] == pytest.approx(2.5) and high["p"] == 1.0
    assert high["ronic_t"] == pytest.approx(R + 1.0 * (2.5 - R))
    for rec_ in (rec, high):
        assert not any(k in rec_ for k in ("r8", "r3", "r_blend", "retention"))
        assert "returns_blend_without_recent" not in rec_["stamps"]


@pytest.mark.parametrize("years_above", [2, 5, 8])
def test_ronic_t_is_r_plus_p_times_the_excess_of_r_tc_over_r(years_above):
    above = set(range(2025 - years_above + 1, 2026))
    rec = tc.analyse(_return_rows(lambda y: 150.0 if y in above else 20.0), R)          # R = 0.30 above r, 0.04 below
    p = years_above / 8.0
    r_tc = 0.30 if years_above >= 5 else 0.04                                          # the window's median
    assert rec["p"] == p and rec["R_tc"] == pytest.approx(r_tc)
    assert rec["ronic_t"] == pytest.approx(R + p * max(0.0, r_tc - R))
    if r_tc < R:
        assert rec["ronic_t"] == R                                                     # a median below r: growth earns its cost


def test_a_median_of_minus_inf_or_a_thin_record_leaves_ronic_t_at_the_cost_of_equity():
    losing = tc.analyse(history(2014, 2025, lambda y: row(y, ni=-10.0, equity=200.0, goodwill=250.0, intangibles=50.0)), R)
    assert losing["R_tc"] == -INF and losing["ronic_t"] == R and not math.isnan(losing["ronic_t"])
    # a p of 0 against +inf cannot arise from a median of +inf, but 0 x inf must never be computed: R_tc = +inf is read first
    thin = tc.analyse(history(2024, 2025, lambda y: row(y, ni=100.0, equity=500.0)), R)
    assert thin["R_tc"] is None and "record_not_available" in thin["stamps"] and thin["ronic_t"] == R


def test_ronic_0_is_r_tc_as_measured_above_0_else_the_terminal_return_and_the_reference_carries_the_records_ronic_t():
    """Revision 24 step 2d (cross-check 19, ruling 1): RONIC_0 is R_tc as measured when above 0 (it was max(coe, R_tc)), stamped
    ronic_start_below_rate below coe; at or below 0 the fade starts at RONIC_T (the record's ronic_t), stamped ronic_start_from_terminal."""
    for r_tc, expect0, stamp in ((0.05, 0.05, "ronic_start_below_rate"), (0.20, 0.20, None), (INF, INF, None),
                                 (-INF, 0.13, "ronic_start_from_terminal"), (0.0, 0.13, "ronic_start_from_terminal")):
        rec = dict(REDUCTION, R_tc=r_tc, ronic_t=0.13)
        ref = cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=rec, base_ni=1.2 * B, base_revenue=10.0 * B,
                       stub_months=8.5, anchor=GA)
        assert ref["ronic0"] == expect0 and ref["terminal_ronic"] == 0.13
        assert [x for x in ref["stamps"] if x in cr.RONIC_STAMPS] == ([stamp] if stamp else [])
    # an older record that still carries r_blend: it is not read
    old = cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=dict(REDUCTION, R_tc=0.20, r_blend=0.50, ronic_t=0.13),
                   base_ni=1.2 * B, base_revenue=10.0 * B, stub_months=8.5, anchor=GA)
    assert old["ronic0"] == 0.20
    none = cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=dict(REDUCTION, R_tc=None, ronic_t=COE,
                                                                        stamps=["record_not_available"]),
                    base_ni=1.2 * B, base_revenue=10.0 * B, stub_months=8.5, anchor=GA)
    assert none["ronic0"] == COE and "record_not_available" in none["stamps"] and "ronic_start_from_terminal" in none["stamps"]


def _est():
    from test_throughcycle_reference import EST
    return EST


def test_the_desk_reads_r_tc_from_the_facts_else_the_terminal_return_and_ignores_an_older_blocks_r_blend():
    """Revision 24 step 2d (cross-check 19, ruling 1): RONIC_0 is r_tc as measured when above 0, else RONIC_T (the scenario's terminal_ronic,
    else r); it was max(r, r_tc), else r."""
    r = 0.09
    assert fmt._long_run_inputs({"r_tc": 0.50}, 1.0, None, r)[2] == 0.50                           # r_tc as measured
    assert fmt._long_run_inputs({"r_blend": 0.20, "r_tc": 0.50}, 1.0, None, r)[2] == 0.50          # r_blend is not read
    assert fmt._long_run_inputs({"r_blend": 0.20}, 1.0, None, r)[2] == r                           # ... even alone (RONIC_T = r)
    low = fmt._long_run_inputs({"r_tc": 0.05}, 1.0, None, r)
    assert low[2] == 0.05 and "ronic_start_below_rate" in low[4]                                   # below r: as measured, stamped
    assert fmt._long_run_inputs({"r_tc": INF}, 1.0, None, r)[2] == INF
    neg = fmt._long_run_inputs({"r_tc": -INF}, 1.0, 0.12, r)
    assert neg[2] == 0.12 and "ronic_start_from_terminal" in neg[4]                                # not above 0: the terminal return
    assert fmt._long_run_inputs({}, 1.0, None, r)[2] == r and fmt._long_run_inputs(None, 1.0, None, r)[2] == r
    assert fmt._long_run_inputs({"r_tc": 0.0}, 1.0, 0.12, r)[2] == 0.12                            # 0.0 is a value: not above 0
    # revision 24 step 2a (ruling 1): the facts' margin ratio is not read; the ratio is the analyst's long_run_margin over the scenario's
    # year-5 earnings margin (E5 0.3 on the facts' year-5 revenue 0.3 / 0.1 = 3.0: 10%), only with a reference; no reference: none, stamped
    lr = {"e5": 0.3, "oe5": 0.28, "m5": 0.1, "margin_ratio": 0.655}
    assert fmt._long_run_inputs(lr, 0.28, None, r)[1] is None
    assert fmt._long_run_inputs(lr, 0.28, None, r, 0.0655)[1] == pytest.approx(0.655)
    assert fmt._long_run_inputs(lr, 0.28, None, r, 0.0)[1] == 0.0
    assert fmt._long_run_inputs({"e5": 0.3, "oe5": 0.28, "m5": 0.1, "m_tc": 0.06, "cycle": True}, 1.0, None, r)[1] is None
    no_ref = fmt._long_run_inputs({"margin_ratio": 0.655, "ni_over_oe": 0.9}, 1.0, None, r, 0.0655)
    assert no_ref[1] is None and "long_run_margin_not_applied_no_revenue" in no_ref[4]
    # RONIC_T: the scenario's, else the facts', else r
    assert fmt._long_run_inputs(lr, 1.0, 0.11, r)[3] == 0.11 and fmt._long_run_inputs(lr, 1.0, None, r)[3] == r


# ---- F2, revision 18: the margin rule - full reversion to the trend level -----------------------------------------------------

def _rec(**kw):
    return dict(dict(om_tc=0.10, om_trend=0.10, om_L=0.20, om_shape="swing", x_L=0.16, tax_L=0.21), **kw)


def test_the_additive_conversion_by_hand_on_one_fixture():
    """om_L 20%, x_L 16%, m5 15%, tax 21%, trend level 10%: OM_5 = 18.73%, OM_long = 10% (all the way, not a fraction of the
    gap), m_long = 15% + 0.79 x (10% - 18.73%) = 8.10%, ratio 0.540."""
    r = cr.margin_rule(_rec(), 0.15)
    assert r["target"] == 0.10 and r["om_trend"] == 0.10
    assert round(r["om_5"] * 100, 2) == 18.73                                        # 0.20 + (0.15 - 0.16) / 0.79
    assert round(r["m_long"] * 100, 2) == 8.10 and round(r["ratio"], 3) == 0.540
    assert r["reason"] is None and r["stamps"] == [] and "cell" not in r and "fraction" not in r


def _by_hand(om_trend, om_L, x_L, tax_L, m5):
    om_5 = om_L + (m5 - x_L) / (1 - tax_L) if x_L is not None else om_L
    target = max(0.0, om_trend)
    return om_5, target, max(0.0, m5 + (1 - tax_L) * (target - om_5))


@pytest.mark.parametrize("om_trend, om_L, x_L, m5", [
    (0.10, 0.20, 0.16, 0.15),         # OM_5 about 18.7%, above the trend level 10%: the margin moves down
    (0.20, 0.10, 0.08, 0.09),         # OM_5 about 11.3%, below the trend level 20%: up
    (-0.02, 0.05, 0.04, 0.05),        # a negative trend level: the target is zero
    (0.0, 0.05, 0.04, 0.05),          # 0.0 is a value
])
def test_the_margin_moves_all_the_way_to_the_floored_trend_level(om_trend, om_L, x_L, m5):
    r = cr.margin_rule(_rec(om_trend=om_trend, om_L=om_L, x_L=x_L), m5)
    om_5, target, m_long = _by_hand(om_trend, om_L, x_L, 0.21, m5)
    assert r["target"] == target and r["om_5"] == pytest.approx(om_5)
    assert r["m_long"] == pytest.approx(m_long) and r["ratio"] == pytest.approx(m_long / m5)
    assert (r["ratio"] < 1) == (target < om_5)                                          # above the level moves down, below up


def test_the_median_and_the_shape_no_longer_move_the_margin():
    base = cr.margin_rule(_rec(), 0.15)
    for kw in (dict(om_tc=0.50), dict(om_tc=-0.50), dict(om_shape="trend"), dict(om_tc=None, om_shape=None)):
        assert cr.margin_rule(_rec(**kw), 0.15)["m_long"] == base["m_long"]


def test_the_anchor_is_the_filed_operating_margin_when_the_earnings_margin_is_unknown():
    r = cr.margin_rule(_rec(x_L=None), 0.15)
    assert r["om_5"] == 0.20 and r["stamps"] == ["margin_rule_filed_anchor"]
    assert r["m_long"] == pytest.approx(0.15 + 0.79 * (0.10 - 0.20))
    # exactly at the trend level: the margin does not move
    at_level = cr.margin_rule(_rec(x_L=None, om_L=0.10), 0.15)
    assert at_level["m_long"] == 0.15 and at_level["ratio"] == 1.0


def test_the_long_run_margin_is_floored_at_zero_never_toward_a_loss():
    # a negative trend level with a 20% operating margin against a 5% earnings margin: the move to zero would take the
    # earnings margin to 0.05 + 0.79 x (0 - 0.20) < 0
    r = cr.margin_rule(_rec(om_trend=-0.01, om_L=0.20, x_L=0.05), 0.05)
    assert r["target"] == 0.0 and r["m_long"] == 0.0 and r["ratio"] == 0.0
    # through the reference: the margin factor runs to 0 at year 10
    rec = dict(REDUCTION, om_tc=-0.01, om_trend=-0.01, om_L=0.20, om_shape="trend", x_L=0.05, tax_L=0.21)
    ref = cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=rec, base_ni=1.2 * B, base_revenue=10.0 * B,
                   stub_months=8.5, anchor=GA)
    m5 = ref["long_run"]["m5"]
    assert ref["margin_ratio"] is not None and ref["m_long"] >= 0.0
    assert cr.margin_rule(rec, m5)["ratio"] == ref["margin_ratio"]


def test_no_margin_rule_when_the_year_5_margin_is_not_positive():
    for m5 in (0.0, -0.01):
        r = cr.margin_rule(_rec(), m5)
        assert r["ratio"] is None and r["target"] is None and r["m_long"] is None
        assert r["stamps"] == ["margin_rule_year5_margin_not_positive"] and "not positive" in r["reason"]


def test_no_margin_rule_without_a_trend_level_and_the_reference_carries_the_records_stamp():
    r = cr.margin_rule(dict(om_tc=None, om_trend=None, om_L=None, om_shape=None, x_L=0.1, tax_L=0.2), 0.15)
    assert r["ratio"] is None and r["om_5"] is None and "too few years of operating or pre-tax margin" in r["reason"]
    # brief F2.1: the record's stamp is margin_record_not_available; the older stamp still rides on the reference
    for stamp in ("margin_record_not_available", "operating_margin_record_not_available"):
        rec = dict(REDUCTION, om_tc=None, om_trend=None, om_L=None, stamps=[stamp])
        ref = cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=rec, base_ni=1.2 * B, base_revenue=10.0 * B,
                       stub_months=8.5, anchor=GA)
        assert ref["margin_ratio"] is None and stamp in ref["stamps"]
        assert "earnings margin held at" in cr.pack_line(ref, 1.1 * B, COE, GA, lambda v: f"{v / B:.3f}", anchor=GA)


def test_no_margin_rule_for_a_current_operating_loss_in_a_profitable_record():
    r = cr.margin_rule(_rec(om_L=-0.05, x_L=-0.03), 0.02)              # OM_5 = -0.05 + (0.02 + 0.03) / 0.79 = +0.013: a profit
    assert r["ratio"] is not None
    r = cr.margin_rule(_rec(om_L=-0.05, x_L=0.02), 0.02)               # OM_5 = -0.05 + 0 = -0.05
    assert r["ratio"] is None and r["target"] is None and r["om_5"] == pytest.approx(-0.05)
    assert r["stamps"] == ["margin_rule_unmeasured_current_loss"] and "the rule does not cover" in r["reason"]
    # OM_5 = 0 is not a profit either
    assert cr.margin_rule(_rec(om_L=0.0, x_L=None), 0.05)["stamps"] == ["margin_rule_filed_anchor",
                                                                     "margin_rule_unmeasured_current_loss"]


def test_a_current_loss_holds_the_margin_a_negative_trend_level_included():
    # the guards are unchanged: a margin that is still a loss at year 5 is outside the rule, so it must not lift m5
    r = cr.margin_rule(_rec(om_trend=-0.02, om_L=-0.05, x_L=None), 0.05)
    assert r["ratio"] is None and r["target"] is None and r["m_long"] is None
    assert r["om_5"] == -0.05 and r["stamps"] == ["margin_rule_filed_anchor", "margin_rule_unmeasured_current_loss"]
    assert r["reason"] == ("this company's 8-year trend-level operating margin is a loss and the consensus implies an operating "
                           "loss at year 5, which the rule does not cover")
    assert cr.margin_rule(_rec(om_trend=-0.02, om_L=0.0, x_L=None), 0.05)["ratio"] is None                # OM_5 = 0
    r = cr.margin_rule(_rec(om_trend=-0.02, om_L=-0.05, x_L=0.02), 0.02)                                 # OM_5 = -0.05 + 0 / 0.79
    assert r["ratio"] is None and r["stamps"] == ["margin_rule_unmeasured_current_loss"]
    # a negative trend level whose consensus margin is a profit at year 5 moves to zero
    r = cr.margin_rule(_rec(om_trend=-0.02, om_L=-0.05, x_L=-0.03), 0.02)                                # OM_5 = -0.05 + 0.05 / 0.79 = +0.013
    assert r["target"] == 0.0 and r["ratio"] is not None and r["stamps"] == []
    # through the reference: the margin is held at m5 and the stamp rides on the reference
    rec = dict(REDUCTION, om_tc=-0.02, om_trend=-0.02, om_L=-0.05, om_shape="trend", x_L=None, tax_L=0.21)
    ref = cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=rec, base_ni=1.2 * B, base_revenue=10.0 * B,
                   stub_months=8.5, anchor=GA)
    assert ref["margin_ratio"] is None and ref["long_run"]["margin_ratio"] is None
    assert ref["stamps"].count("margin_rule_unmeasured_current_loss") == 1


def test_no_margin_rule_without_a_revenue_path():
    no_rev = {k: dict(v, revenue={"analysts": 0}) for k, v in _est().items()}
    ref = cr.build(1.1 * B, no_rev, COE, GA, 500e6, MEDIAN5, record=dict(REDUCTION, om_tc=0.06, om_trend=0.06, om_L=0.17,
                                                                        om_shape="trend", x_L=0.12, tax_L=0.25),
                   base_ni=1.2 * B, base_revenue=10.0 * B)
    assert ref["long_run_path"] == "owner_earnings_ratio" and ref["margin"] is None and ref["margin_ratio"] is None
    assert ref["om_5"] is None and ref["long_run"]["margin_ratio"] is None


def _line(ref):
    return cr.pack_line(ref, 1.1 * B, COE, GA, lambda v: f"{v / B:.3f}", anchor=GA)


def _pct(x, nd=1):
    return f"{x * 100:.{nd}f}%"


def test_the_explanations_say_where_the_margin_moved_and_why_it_did_not():
    def ref_for(**kw):
        rec = dict(REDUCTION, om_tc=0.06, om_trend=0.06, om_L=0.17, om_shape="swing", x_L=0.12, tax_L=0.25)
        rec.update(kw)
        return cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=rec, base_ni=1.2 * B, base_revenue=10.0 * B,
                        stub_months=8.5, anchor=GA)
    m5 = lambda ref: ref["long_run"]["m5"]
    for shape in ("swing", "trend"):
        ref = ref_for(om_shape=shape)                                   # the shape no longer changes the sentence
        assert ("earnings margin moving from " + _pct(m5(ref)) + " to " + _pct(ref["m_long"]) + " by year 10: the operating "
                "margin moves to the trend level of your 8-year record (6.0%) by year 10 (the consensus implies "
                + _pct(ref["om_5"]) + " at year 5)") in _line(ref)
    loss = ref_for(om_trend=-0.02)
    assert "moves to the trend level of your 8-year record (0.0%) by year 10" in _line(loss)             # floored at zero
    held = ref_for(om_L=-0.05, x_L=0.129)
    assert held["stamps"].count("margin_rule_unmeasured_current_loss") == 1
    assert ("earnings margin held at " + _pct(m5(held)) + ": this company's 8-year trend-level operating margin is positive but "
            "the consensus implies an operating loss at year 5, which the rule does not cover") in _line(held)
    off = ref_for(om_trend=None, om_L=None)
    assert ("earnings margin held at " + _pct(m5(off)) + ": your record holds too few years of operating or pre-tax "
            "margin to measure its trend level") in _line(off)
    loss_held = ref_for(om_trend=-0.02, om_L=-0.05, x_L=0.129)
    assert ("earnings margin held at " + _pct(m5(loss_held)) + ": this company's 8-year trend-level operating margin is a loss "
            "and the consensus implies an operating loss at year 5, which the rule does not cover") in _line(loss_held)
    # the revision-17 wording is gone
    assert "closed" not in _line(ref_for()) and "of such a gap" not in _line(ref_for())


def test_the_explanations_name_the_pretax_margin_when_the_record_is_on_the_pretax_line_and_the_arithmetic_is_the_same():
    def ref_for(basis, **kw):
        rec = dict(REDUCTION, om_tc=0.06, om_trend=0.06, om_L=0.17, om_shape="swing", x_L=0.12, tax_L=0.25, om_basis=basis)
        rec.update(kw)
        return cr.build(1.1 * B, _est(), COE, GA, 500e6, MEDIAN5, record=rec, base_ni=1.2 * B, base_revenue=10.0 * B,
                        stub_months=8.5, anchor=GA)
    m5 = lambda ref: ref["long_run"]["m5"]
    for basis in ("pretax_with_amortization", "pretax_without_amortization"):
        pre, op = ref_for(basis), ref_for("with_amortization")
        assert pre["margin_ratio"] == op["margin_ratio"] and pre["m_long"] == op["m_long"] and pre["value"] == op["value"]
        assert ("earnings margin moving from " + _pct(m5(pre)) + " to " + _pct(pre["m_long"]) + " by year 10: the pre-tax "
                "margin moves to the trend level of your 8-year record (6.0%) by year 10 (the consensus implies "
                + _pct(pre["om_5"]) + " at year 5)") in _line(pre)
        assert "operating margin" not in _line(pre)
    held = ref_for("pretax_with_amortization", om_L=-0.05, x_L=0.129)
    assert ("earnings margin held at " + _pct(m5(held)) + ": this company's 8-year trend-level pre-tax margin is positive but the "
            "consensus implies a pre-tax loss at year 5, which the rule does not cover") in _line(held)
    loss_held = ref_for("pretax_without_amortization", om_trend=-0.02, om_L=-0.05, x_L=0.129)
    assert ("this company's 8-year trend-level pre-tax margin is a loss and the consensus implies a pre-tax loss at year 5, "
            "which the rule does not cover") in _line(loss_held)
    # the record's stamps ride on the reference
    stamped = ref_for("pretax_with_amortization", stamps=["margin_record_pretax"])
    assert "margin_record_pretax" in stamped["stamps"]


# ---- F4: the facts ---------------------------------------------------------------------------------------------------------

RAW_NEW = {"om_tc": 0.1049999, "om_trend": 0.0899999, "om_L": 0.19999999, "om_years": [2018, 2025, 8], "om_shape": "swing",
           "om_basis": "with_amortization", "om_5": 0.18734177, "m_long": 0.08821357, "margin_ratio": 0.65475710766}


def test_the_new_long_run_members_quantize_print_read_back_and_compare_like_their_neighbours():
    lr = pack_facts.quantize_long_run(dict(RAW_NEW))
    assert lr["om_tc"] == pytest.approx(0.105) and lr["om_L"] == pytest.approx(0.2) and lr["om_5"] == pytest.approx(0.187342)
    assert lr["margin_ratio"] == 0.654757                                                                           # ratios: six places
    assert lr["m_long"] == pytest.approx(0.088214) and lr["om_trend"] == pytest.approx(0.09)                        # rates: 4 places of a percent
    assert lr["om_years"] == [2018, 2025, 8] and lr["om_shape"] == "swing"
    assert not any(k in lr for k in ("margin_cell", "margin_fraction", "r8", "r3", "r_blend", "retention"))
    f = dict(pack_facts.empty(), long_run=lr, coe_anchor=0.09, terminal_g_default=0.03)
    block = pack_facts.render_defaults_block(f)
    line = next(l for l in block.splitlines() if l.startswith("- long_run: "))
    for member in ("om_tc=10.5000%", "om_trend=9.0000%", "om_L=20.0000%", "om_years=2018-2025:8", "om_shape=swing",
                   "om_basis=with_amortization", "om_5=18.7342%", "m_long=8.8214%", "margin_ratio=0.654757"):
        assert member in line, member
    for gone in ("margin_cell", "margin_fraction", "r8=", "r3=", "r_blend", "retention"):
        assert gone not in line, gone
    back = pack_facts.from_text("# DATA PACK - X   (pack revision 17)\n\n" + block)
    assert pack_facts.parity(f, back) == []
    assert back["long_run"]["om_tc"] == lr["om_tc"] and back["long_run"]["margin_ratio"] == lr["margin_ratio"]
    # parity compares them like the others
    other = dict(f, long_run=dict(lr, margin_ratio=0.5))
    assert pack_facts.parity(f, other) == ["long_run"]
    assert pack_facts.parity(f, dict(f, long_run=dict(lr, om_shape="trend"))) == ["long_run"]
    # none for every one of them prints and reads back as none; a block without them (older) reads them as none
    empty = pack_facts.quantize_long_run({"cycle": None})
    assert all(empty[m] is None for m in pack_facts._LONG_RUN_NEW_MEMBERS)
    members = line.split(" | ")[0]
    old = re.sub(r", om_tc=.*?, margin_ratio=[^,]*", "", members)
    assert "om_tc" not in old and old != members
    older = pack_facts._parse_long_run(old.split(": ", 1)[1])
    assert all(older[m] is None for m in pack_facts._LONG_RUN_NEW_MEMBERS)


def test_the_long_run_explanation_names_the_series_the_margin_record_is_on():
    def explanation(**kw):
        f = dict(pack_facts.empty(), long_run=pack_facts.quantize_long_run(dict(RAW_NEW, **kw)), coe_anchor=0.09, terminal_g_default=0.03)
        line = next(l for l in pack_facts.render_defaults_block(f).splitlines() if l.startswith("- long_run: "))
        return line.split(" | ", 1)[1], line
    operating, _ = explanation()
    assert ("om_5, the operating margin the consensus implies at year 5, moves all the way to om_trend, the trend level of your "
            "record's 8-year operating margin (to zero for a loss record).") in operating
    for basis in ("pretax_with_amortization", "pretax_without_amortization"):
        text, line = explanation(om_basis=basis)
        assert ("om_5, the pre-tax margin the consensus implies at year 5, moves all the way to om_trend, the trend level of your "
                "record's 8-year pre-tax margin (to zero for a loss record).") in text
        assert "operating margin" not in text and ("om_basis=" + basis) in line
        block = pack_facts.render_defaults_block(dict(pack_facts.empty(), long_run=pack_facts.quantize_long_run(dict(RAW_NEW, om_basis=basis))))
        assert pack_facts.from_text("# DATA PACK - X   (pack revision 17)\n\n" + block)["long_run"]["om_basis"] == basis


def test_reference_base_b_is_a_printed_fact_read_back_as_none_from_an_older_sidecar_or_block(tmp_path):
    assert "reference_base_b" in pack_facts.KEYS and pack_facts.FACTS_VERSION == 12      # revision 24 step 2b: 10 -> 11
    assert pack_facts.empty()["reference_base_b"] is None
    f = dict(pack_facts.empty(), reference_base_b=pack_facts.q_b(0.0939412345))
    block = pack_facts.render_defaults_block(f)
    assert "- reference_base_b: 0.093941 | the fiscal-year owner-earnings base the CONSENSUS-IMPLIED VALUE grows from" in block
    assert pack_facts.from_text("# DATA PACK - X   (pack revision 17)\n\n" + block)["reference_base_b"] == 0.093941
    none = pack_facts.render_defaults_block(pack_facts.empty())
    assert "- reference_base_b: not available | " in none
    assert pack_facts.from_text("# DATA PACK - X   (pack revision 17)\n\n" + none)["reference_base_b"] is None
    # an older sidecar (written before the key existed) and an older block (no line) read None
    sidecar = dict(pack_facts.empty())
    del sidecar["reference_base_b"]
    (tmp_path / pack_facts.SIDECAR).write_text(json.dumps(sidecar), encoding="utf-8")
    assert pack_facts.read_sidecar(tmp_path)["reference_base_b"] is None
    older = "\n".join(l for l in none.splitlines() if not l.startswith("- reference_base_b"))
    assert pack_facts.from_text("# DATA PACK - X   (pack revision 17)\n\n" + older)["reference_base_b"] is None


# ---- the pack and the desk on the reference's own inputs (brief D's dev_desk_identity construction) --------------------------

def _pack_and_reference(monkeypatch, op_margins):
    calls = []
    real = cr.build

    def recording(*a, **k):
        out = real(*a, **k)
        calls.append(out)
        return out
    monkeypatch.setattr(cr, "build", recording)
    pack = _synthetic_pack(monkeypatch, op_margins=op_margins)
    return pack, calls[-1]


def _desk_value(text, ref):
    """The desk's Base value on the reference's own inputs: its fiscal-year base and growth path at full precision, and the
    facts as the DEFAULTS block prints them (the precision the desk receives)."""
    parsed = pack_facts.from_text(text)
    lv = ref["levels"]
    base = ref["base_cf"] / B
    ctx = {"price": 1e6, "shares_default_b": parsed["shares_default"] / B, "coe_anchor": parsed["coe_anchor"],
           "terminal_g_default": parsed["terminal_g_default"], "terminal_g_anchor": parsed["terminal_g_anchor"],
           "owner_earnings_default_b": base, "levels": {"year1": lv[0] / B, "year2": lv[1] / B},
           "terminal_ronic": parsed["terminal_ronic"], "long_run": parsed["long_run"],
           "working_capital": parsed["working_capital"], "cash_basis_b": parsed["cash_basis_b"],
           "reference_base_b": parsed["reference_base_b"]}
    sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": list(ref["path"]), "wacc": w}
    reasons = {k: "diagnostic" for k in ("cash_flow_life_reason", "base_cf_reason", "scenario_deviation_reason",
                                         "bull_below_price_reason", "bear_above_price_reason", "terminal_reason",
                                         "coe_adjustment_reason", "shares_reason")}
    call = dict(reasons, scenarios=[sc("Base", 0.4, parsed["coe_anchor"]), sc("Bull", 0.3, parsed["coe_anchor"] - 0.0005),
                                    sc("Bear", 0.3, parsed["coe_anchor"] + 0.0005)],
                terminal_g=parsed["terminal_g_default"], fade_years=5, sbc_treatment="deducted_in_cf", cash_flow_life="perpetual",
                long_run_margin=ref_long_run_margin(ref))
    out = fmt.execute_financial_model(call, ctx)
    assert "error" not in out, out.get("error")
    return out["scenario_dcfs"][0]["dcf"], parsed


# operating margins of the twelve-year fixture (2014-2025); the window 2018-2025
PEAK_SWING = {2018: 0.10, 2019: 0.11, 2020: 0.09, 2021: 0.12, 2022: 0.10, 2023: 0.09, 2024: 0.10, 2025: 0.20}
TROUGH_TREND = {2018: 0.22, 2019: 0.21, 2020: 0.20, 2021: 0.20, 2022: 0.20, 2023: 0.19, 2024: 0.20, 2025: 0.08}
LOSS_RECORD = {2018: -0.05, 2019: -0.04, 2020: -0.06, 2021: -0.03, 2022: -0.05, 2023: -0.04, 2024: -0.02, 2025: 0.02}


@pytest.mark.parametrize("op_margins, direction", [
    (PEAK_SWING, "down"),
    (TROUGH_TREND, "up"),
    (LOSS_RECORD, "down"),
], ids=["peak-swing", "trough-trend", "loss-record"])
def test_the_desk_run_on_the_references_own_inputs_equals_the_reference_to_half_a_cent(screener_data_stub, monkeypatch,
                                                                                    op_margins, direction):
    pack, ref = _pack_and_reference(monkeypatch, op_margins)
    f = pack.facts
    assert f["reference_status"] == "used", f["reference_status"]
    assert ref["margin_ratio"] is not None and (ref["margin_ratio"] < 1) == (direction == "down")
    lr = f["long_run"]
    assert lr["margin_ratio"] == pack_facts.q_ratio(ref["margin_ratio"])
    assert lr["om_shape"] in ("swing", "trend") and lr["om_basis"] == "with_amortization" and lr["om_years"] == [2018, 2025, 8]
    assert lr["om_trend"] is not None and lr["r_tc"] is not None and "r_blend" not in lr
    assert f["reference_base_b"] == pack_facts.q_b(ref["base_cf"] / B)
    assert pack_facts.parity(f, pack_facts.from_text(str(pack))) == []
    dcf, _ = _desk_value(str(pack), ref)
    assert "working_capital_deducted" in dcf["stamps"]
    assert dcf["long_run"]["margin_ratio"] == pytest.approx(ref["margin_ratio"], abs=1e-4)
    assert abs(dcf["per_share_iv"] - ref["value"]) <= 0.0051, (dcf["per_share_iv"], ref["value"])
    # the explanation of the pack's own line
    text = str(pack)
    clause = next(l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE (reference" in l)
    assert "earnings margin moving from " in clause and "moves to the trend level of your 8-year record" in clause and "closed" not in clause


# ---- F5: a zero or negative value is never a reference ---------------------------------------------------------------------

@pytest.mark.parametrize("forced", [-12.34, 0.0, 0.004, -0.004])
def test_a_value_of_zero_or_less_prints_no_number_has_status_not_meaningful_and_is_not_fenced(screener_data_stub, monkeypatch, forced):
    real = cr.build

    def negative(*a, **k):
        out = real(*a, **k)
        return dict(out, value=forced)
    monkeypatch.setattr(cr, "build", negative)
    fenced = []
    monkeypatch.setattr(cap, "_reference_outside_fence", lambda value, band: (fenced.append(value), (None, None))[1])
    pack = _synthetic_pack(monkeypatch)
    f, text = pack.facts, str(pack)
    assert f["reference_status"] == "not_meaningful" and f["consensus_implied_value"] is None
    assert fenced == [], "the fence is not evaluated for a value that is not meaningful"
    line = next(l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE" in l)
    assert line.startswith("- CONSENSUS-IMPLIED VALUE: not meaningful — the consensus path and this company's record give "
                           "no positive value")
    assert "CONSENSUS-IMPLIED VALUE (reference" not in text and "per share, the analysts' own earnings path" not in text
    assert "12.34" not in text and "BASE WINDOW CHECK" not in text                     # no number, and no window value either
    assert "- reference_status: not_meaningful | " in text and "- consensus_implied_value: not available | " in text
    # levels, long_run and working_capital are still printed; the reference's base too
    assert f["levels"].get("year1") and f["long_run"]["e5"] is not None and f["working_capital"] is not None
    assert f["reference_base_b"] is not None and f["long_run"]["margin_ratio"] is not None
    parsed = pack_facts.from_text(text)
    assert pack_facts.parity(f, parsed) == [] and parsed["reference_status"] == "not_meaningful"
    # stamped on the verdict, and no reference check follows from it
    flags, stamps = cv.scenario_checks(Path("nowhere"), {"base_iv": 100.0}, None, text, 100.0, facts=f)
    assert stamps["consensus_reference_status"] == "not_meaningful"


def test_a_positive_value_still_prints_and_is_used(screener_data_stub, monkeypatch):
    pack = _synthetic_pack(monkeypatch)
    assert pack.facts["reference_status"] == "used" and pack.facts["consensus_implied_value"] > 0
    # brief F2.3: the reference_status explanation now names the status, so the words occur once, there, and the printed
    # not-meaningful line does not
    text = str(pack)
    assert "CONSENSUS-IMPLIED VALUE: not meaningful" not in text
    assert text.count("not meaningful") == 1 and "or not meaningful (a value of zero or less)" in text


def test_the_not_meaningful_line_names_the_references_own_reason_or_stamps():
    assert cr.not_meaningful_line({"reason": None, "stamps": ["long_run_floor", "margin_rule_filed_anchor"]}) == (
        "- CONSENSUS-IMPLIED VALUE: not meaningful — the consensus path and this company's record give no positive value "
        "(long_run_floor, margin_rule_filed_anchor)")
    assert cr.not_meaningful_line({"reason": "a reason", "stamps": []}).endswith("no positive value (a reason)")
    assert cr.not_meaningful_line({"reason": None, "stamps": []}).endswith("no positive value")


# ---- F6: the working-capital basis (brief D's W9 case) ---------------------------------------------------------------------

W9_EST = {"0y": {"revenue": {"avg": 1.08 * B, "analysts": 12, "growth": 0.08, "year_ago": 1.0 * B},
                 "eps": {"avg": 2.25, "analysts": 12, "growth": 0.125, "year_ago": 2.0}},
          "+1y": {"revenue": {"avg": 1.16 * B, "analysts": 12, "growth": 0.0741},
                  "eps": {"avg": 2.5, "analysts": 12, "growth": 0.1111}}}
W9_FY_BASE, W9_CASH_BASIS = 93.94e6, 93e6


def _w9_reference():
    rec = dict(REDUCTION, R_tc=0.15, r_blend=0.15, ronic_t=0.12, nwc_intensity=0.10)
    return cr.build(W9_FY_BASE, W9_EST, COE, GA, 50e6, MEDIAN5, record=rec, base_ni=100e6, base_revenue=1.0 * B,
                    stub_months=8.5, anchor=GA)


def _w9_desk(ref, **ctx_over):
    lv = ref["levels"]
    lr = ref["long_run"]
    ctx = {"price": 1e6, "shares_default_b": 0.05, "coe_anchor": COE, "terminal_g_default": GA, "terminal_g_anchor": GA,
           "owner_earnings_default_b": 0.0885, "cash_basis_b": W9_CASH_BASIS / B, "reference_base_b": W9_FY_BASE / B,
           "levels": {"year1": lv[0] / B, "year2": lv[1] / B}, "terminal_ronic": ref["terminal_ronic"],
           "long_run": {"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "m5": lr["m5"], "margin_ratio": ref["margin_ratio"],
                        "r_tc": 0.15, "stub_months": 8.5, "revenue_path": ([x / B for x in ref["revenue"]] if ref.get("revenue") else None),
                              "oe_path": ([x / B for x in ref["oe_path"]] if ref.get("revenue") else None), "oe_base": (cr.oe_base(ref) / B if ref.get("revenue") else None), "nwc_intensity": ref["nwc_intensity"]},  # step 2c: the consensus revenue path and its owner earnings (the desk's own-path working capital); step 2d: their base
           "working_capital": [x / B for x in ref["wc"]]}
    ctx.update(ctx_over)
    sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": W9_FY_BASE / B, "explicit_growth": list(ref["path"]), "wacc": w}
    call = {"scenarios": [sc("Base", 0.4, COE), sc("Bull", 0.3, COE - 0.0005), sc("Bear", 0.3, COE + 0.0005)],
            "terminal_g": GA, "fade_years": 5, "sbc_treatment": "deducted_in_cf", "cash_flow_life": "perpetual",
            "cash_flow_life_reason": "d", "base_cf_reason": "the fiscal-year base", "scenario_deviation_reason": "d",
            "bull_below_price_reason": "d", "bear_above_price_reason": "d", "terminal_reason": "d", "coe_adjustment_reason": "d",
            "shares_reason": "d", "long_run_margin": ref_long_run_margin(ref)}
    out = fmt.execute_financial_model(call, ctx)
    assert "error" not in out, out.get("error")
    return out["scenario_dcfs"][0]["dcf"]


def test_w9_a_fiscal_year_base_near_the_cash_basis_still_deducts_working_capital_and_the_desk_equals_the_reference():
    """FY base 93.94M, cash basis 93M (1.0% apart): revision 17's desk read the Base as cash-basis and skipped the deduction the
    reference makes (brief D, one name: 21.87 against 18.24)."""
    ref = _w9_reference()
    assert abs(W9_FY_BASE / W9_CASH_BASIS - 1) < 0.02 and ref["wc"] is not None
    new = _w9_desk(ref)
    # the base is within 2% of the cash basis and of the reference's own base: owner earnings, deducted, and stamped
    assert "working_capital_deducted" in new["stamps"] and "wc_in_base" not in new["stamps"]
    assert "wc_basis_ambiguous_owner_earnings" in new["stamps"]
    assert abs(new["per_share_iv"] - ref["value"]) <= 0.0051, (new["per_share_iv"], ref["value"])
    # the defect: without reference_base_b (an older sidecar) the Base is read as cash-basis and the value is higher
    old = _w9_desk(ref, reference_base_b=None)
    assert "wc_in_base" in old["stamps"] and old["working_capital_deducted"] is None
    assert old["per_share_iv"] > ref["value"] + 0.5


def test_a_base_within_two_percent_of_an_owner_earnings_figure_is_owner_earnings():
    ref = _w9_reference()
    # near the cash basis AND the DEFAULTS owner earnings: owner earnings, deducted, stamped
    both = _w9_desk(ref, reference_base_b=None, owner_earnings_default_b=0.0935)
    assert "working_capital_deducted" in both["stamps"] and "wc_basis_ambiguous_owner_earnings" in both["stamps"]
    assert "wc_in_base" not in both["stamps"]
    # near the cash basis and away from both owner-earnings figures: cash basis, no deduction, stamped as before
    cash_only = _w9_desk(ref, reference_base_b=0.0885)
    assert "wc_in_base" in cash_only["stamps"] and cash_only["working_capital_deducted"] is None
    assert "wc_basis_ambiguous_owner_earnings" not in cash_only["stamps"]
    # exactly 2% is within: 0.020001 tolerance as before
    edge = _w9_desk(ref, reference_base_b=W9_FY_BASE / B / 1.0199)
    assert "wc_in_base" not in edge["stamps"] and "working_capital_deducted" in edge["stamps"]
    outside = _w9_desk(ref, reference_base_b=W9_FY_BASE / B / 1.0300)
    assert "wc_in_base" in outside["stamps"]
    # a zero or missing figure is not an owner-earnings match
    assert "wc_in_base" in _w9_desk(ref, reference_base_b=0.0, owner_earnings_default_b=0.0885)["stamps"]


def test_the_desk_context_carries_reference_base_b_from_the_facts_and_the_task_says_the_rule():
    assert ("unless your base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or reference_base_b "
            "(a base that matches an owner-earnings figure is owner earnings).") in cap.TASK
    assert "unless your base_cf is within 2% of cash_basis_b, which already carries it" not in cap.TASK
    assert "not within 2% of owner_earnings_default_b or reference_base_b (a base that matches an owner-earnings figure is owner earnings)" \
        in pack_facts._working_capital_explanation(dict(pack_facts.empty(), working_capital=[0.1] * 5))


# ---- F7: the share-count wording -------------------------------------------------------------------------------------------

def _case(t):
    c = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))["cases"][t]
    return c, c["history"], json.loads((FIX / f"financials_{t}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("t, k", [("MNST", 2), ("IESC", 2), ("POWL", 3)])
def test_briefs_ds_three_us_splits_are_confirmed(t, k):
    c, h, fin = _case(t)
    split = cap._split_after_last_filing(c["vendor_shares"], h)
    assert split["k"] == k and split["reverse"] is False and split["fy"] == 2025
    assert c["country"] == "United States" and cap._split_confirmed(split, h, fin, c["country"]) is True
    split["confirmed"] = True
    x, z = h["2025"]["shares_diluted"] / 1e6, c["vendor_shares"] / 1e6
    assert cap._split_sentence(split) == (f"a {k}-for-1 split (filed FY2025 {x:.1f}M -> vendor {z:.1f}M; the vendor's restated "
                                          f"FY2025 EPS agrees); filed per-share figures in DATA 5 and 6 are pre-split.")


def test_the_3_for_1_case_by_the_numbers():
    c, h, fin = _case("POWL")
    assert fin["Annual_Income_Statement"][0]["DilutedEPS"] == 4.953333
    filed = h["2025"]["net_income"] / h["2025"]["shares_diluted"]
    assert filed == pytest.approx(14.8555, abs=1e-4) and abs(4.953333 * 3 / filed - 1) < 0.03


def test_a_depositary_share_case_gets_the_neutral_form_because_the_company_is_not_american():
    c, h, fin = _case("EMBJ")
    split = cap._split_after_last_filing(c["vendor_shares"], h)
    assert split["k"] == 4 and split["reverse"] is True and c["country"] != "United States"
    assert fin["Annual_Income_Statement"][0]["DilutedEPS"] == 1.922
    # vendor EPS 1.922 against the filed 0.49 per ordinary share: the EPS agrees at k = 4 (the ADS is four ordinary shares) ...
    filed = h["2025"]["net_income"] / h["2025"]["shares_diluted"]
    assert abs(1.922 * split["multiplier"] / filed - 1) < 0.03
    # ... which is why the country decides: not a US company, not confirmed
    assert cap._split_confirmed(split, h, fin, c["country"]) is False
    assert cap._split_confirmed(split, h, fin, "United States") is True
    split["confirmed"] = False
    assert cap._split_sentence(split) == (
        "the vendor's share count is 1/4 of the filed diluted count (filed FY2025 732.4M -> vendor 178.0M): a split after the "
        "last filing, or a different share unit such as depositary shares; the filed per-share figures in DATA 5 and 6 are on "
        "the filed unit.")


def test_a_us_split_whose_vendor_eps_does_not_agree_gets_the_neutral_form_and_so_does_a_missing_country_or_year():
    c, h, fin = _case("MNST")
    split = cap._split_after_last_filing(c["vendor_shares"], h)
    unrestated = json.loads(json.dumps(fin))
    unrestated["Annual_Income_Statement"][0]["DilutedEPS"] = h["2025"]["net_income"] / h["2025"]["shares_diluted"]   # pre-split EPS
    assert cap._split_confirmed(split, h, unrestated, "United States") is False
    split["confirmed"] = False
    assert cap._split_sentence(split).startswith("the vendor's share count is 2x the filed diluted count (filed FY2025 984.5M "
                                                 "-> vendor 1959.1M): a split after the last filing, or a different share unit")
    assert cap._split_confirmed(split, h, fin, None) is False and cap._split_confirmed(split, h, fin, "Unknown") is False
    assert cap._split_confirmed(split, h, dict(fin, Annual_Income_Statement=[]), "United States") is False
    assert cap._split_confirmed(split, h, {}, "United States") is False
    other_year = json.loads(json.dumps(fin))
    other_year["Annual_Income_Statement"][0]["Date"] = "2026-03-31"
    assert cap._split_confirmed(split, h, other_year, "United States") is False       # not the same fiscal year
    assert cap._split_sentence(None) is None


def test_the_defaults_explanation_follows_the_same_two_forms():
    conf, neutral = pack_facts._split_explanation(2.0, True), pack_facts._split_explanation(2.0, False)
    assert conf == ("the vendor's share count is 2 times the last filed diluted count (DATA 7): the filed per-share figures in "
                    "DATA 5 and 6 are pre-split, and the BASE-YEAR CHECK uses the filed count x 2")
    assert neutral == ("the vendor's share count is 2 times the last filed diluted count (DATA 7): a split after the last filing, "
                       "or a different share unit such as depositary shares; the filed per-share figures in DATA 5 and 6 are on "
                       "the filed unit, and the BASE-YEAR CHECK uses the filed count x 2")
    assert pack_facts._split_explanation(0.25, True) == (
        "the vendor's share count is 1/4 of the last filed diluted count (DATA 7, a reverse split): the filed per-share figures "
        "in DATA 5 and 6 are pre-split, and the BASE-YEAR CHECK uses the filed count / 4")
    assert pack_facts._split_explanation(0.25, False) == (
        "the vendor's share count is 1/4 of the last filed diluted count (DATA 7): a split after the last filing, or a different "
        "share unit such as depositary shares; the filed per-share figures in DATA 5 and 6 are on the filed unit, and the "
        "BASE-YEAR CHECK uses the filed count / 4")
    f = dict(pack_facts.empty(), split_after_last_filing=4.0)
    assert "are pre-split" in pack_facts.render_defaults_block(f, split_confirmed=True)
    for arg in (False, None):
        block = pack_facts.render_defaults_block(f, split_confirmed=arg)
        assert "a split after the last filing, or a different share unit such as depositary shares" in block
        assert "are pre-split" not in block


def test_the_country_comes_from_the_screeners_stocks_json(tmp_path, monkeypatch):
    (tmp_path / "stocks.json").write_text(json.dumps([{"symbol": "AAA", "country": "United States"},
                                                       {"symbol": "BBB", "country": "Brazil"}, {"symbol": "CCC"}, "junk"]),
                                          encoding="utf-8")
    monkeypatch.setattr(cap, "SD", tmp_path)
    assert cap._screener_country("AAA") == "United States" and cap._screener_country("BBB") == "Brazil"
    assert cap._screener_country("CCC") is None and cap._screener_country("ZZZ") is None
    monkeypatch.setattr(cap, "SD", tmp_path / "nowhere")
    assert cap._screener_country("AAA") is None


def _gev_pack(monkeypatch, *a, **k):
    with monkeypatch.context() as m:
        return _gev_pack_in(m, *a, **k)


def _vendor(shares, eps):
    return lambda f: dict(f, Shares_Outstanding=shares,
                          Annual_Income_Statement=[dict(f["Annual_Income_Statement"][0], DilutedEPS=eps)]
                          + list(f["Annual_Income_Statement"][1:]))


GEV_EPS = 4.884e9 / 276e6


@pytest.mark.usefixtures("screener_data_stub")
def test_the_pack_says_split_only_for_a_us_company_and_otherwise_the_neutral_form_everywhere(monkeypatch):
    def pack_for(country, eps):
        return _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=_vendor(552e6, eps), eps_year_ago=GEV_EPS / 2,
                         country=country)
    neutral_7 = ("After the last filing: the vendor's share count is 2x the filed diluted count (filed FY2025 276.0M -> vendor "
                 "552.0M): a split after the last filing, or a different share unit such as depositary shares; the filed "
                 "per-share figures in DATA 5 and 6 are on the filed unit.")
    # a depositary-share company: the EPS agrees, the country does not
    ads = pack_for("Brazil", GEV_EPS / 2)
    assert neutral_7 in ads and "restated FY2025 EPS agrees" not in ads and "are pre-split" not in ads
    assert "the filed count x 2 for the share-count difference after the last filing (DATA 7)" in _byc(ads)
    assert "for the split after the last filing" not in _byc(ads)
    line = next(l for l in ads.splitlines() if l.startswith("- split_after_last_filing"))
    assert line == ("- split_after_last_filing: 2 | the vendor's share count is 2 times the last filed diluted count (DATA 7): a "
                    "split after the last filing, or a different share unit such as depositary shares; the filed per-share "
                    "figures in DATA 5 and 6 are on the filed unit, and the BASE-YEAR CHECK uses the "
                    "filed count x 2")
    # a US company whose vendor EPS was not restated (still the filed 17.70), and one whose country the screener lacks
    for country, eps in (("United States", 17.69), (None, GEV_EPS / 2)):
        text = pack_for(country, eps)
        assert neutral_7 in text and "are pre-split" not in text
    # the confirmed case: the same inputs with the country and the restated EPS
    yes = pack_for("United States", GEV_EPS / 2)
    assert ("After the last filing: a 2-for-1 split (filed FY2025 276.0M -> vendor 552.0M; the vendor's restated FY2025 EPS "
            "agrees); filed per-share figures in DATA 5 and 6 are pre-split.") in yes
    assert "the filed count x 2 for the split after the last filing (DATA 7)" in _byc(yes)
    assert "are pre-split, and the BASE-YEAR CHECK uses the filed count x 2" in yes
    # the multiplier and the arithmetic do not depend on the wording
    for text in (ads, yes):
        assert next(l for l in text.splitlines() if l.startswith("- split_after_last_filing")).startswith("- split_after_last_filing: 2 |")
        assert "our filed FY2025 EPS is $8.85" in _byc(text)


# ---- F8, item 7: the loop guard's clause -----------------------------------------------------------------------------------

def test_the_loop_guard_replaces_the_generic_clause_before_its_own_sentence():
    generic = fmt._refusal([], [{"reason": "bear_above_price_reason", "why": "w"}])
    advised = fmt._refusal([], [{"reason": "bear_above_price_reason", "why": "w"}], advice={"bear_above_price_reason": "Advice."})
    assert generic["error"].endswith(fmt.REFUSAL_GENERIC_CLAUSE) and advised["error"].endswith(fmt.REFUSAL_ADVISED_CLAUSE)
    assert fmt.REFUSAL_GENERIC_CLAUSE == " Call again with the same inputs and these reasons, or change an input with dated evidence."
    assert fmt.REFUSAL_ADVISED_CLAUSE == " Call again with the same inputs and these reasons."
    sentence = "Changing inputs has not cleared bear_above_price_reason. Give the reasons named above with the inputs you have."
    for refusal in (generic, advised):
        first, window = at.desk_loop_guard(refusal, "call-1", None)
        assert first["error"] == refusal["error"]                                      # the first refusal is untouched
        second, window = at.desk_loop_guard(refusal, "call-2", window)
        head = refusal["error"].removesuffix(fmt.REFUSAL_GENERIC_CLAUSE).removesuffix(fmt.REFUSAL_ADVISED_CLAUSE)
        assert second["error"] == head + fmt.REFUSAL_ADVISED_CLAUSE + " " + sentence
        assert ", or change an input" not in second["error"]
    # no guard sentence, no rewrite: a repeat of the same call keeps the generic clause
    again, _ = at.desk_loop_guard(generic, "call-2", window)
    assert again["error"].endswith(fmt.REFUSAL_GENERIC_CLAUSE)

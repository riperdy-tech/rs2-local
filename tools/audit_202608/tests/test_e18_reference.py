"""Phase 4 E18 (ADI (b) joint review with Fable, 2026-09-25): the CONSENSUS-IMPLIED VALUE is built
on the last full fiscal year, the period consensus growth is measured from, and rolled forward to
today; its year-1 and year-2 cash-flow levels are printed and are what the base case is checked
against. The TTM base with fiscal-year growth counted part of the current year twice: ADI's
reference was $399, the fiscal-year-consistent value about $312 at year end, $342 today.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))

import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import pack_facts  # noqa: E402


# Revision 17: the reference's long run needs the company's record. With RONIC_T = +inf, no cycle, no working
# capital and base net income = owner earnings (D&A = capex) it reduces to revision 16's arithmetic, so the
# tests in this module that pin revision-16 numbers build through this wrapper and keep their assertions.
_REDUCTION = {"R_tc": float("inf"), "ronic_t": float("inf"), "cycle": False, "m_tc": None,
              "nwc_intensity": None, "stamps": []}


def _build(base_cf, *args, **kw):
    return cr.build(base_cf, *args, **dict({"record": _REDUCTION, "base_ni": base_cf}, **kw))

B = 1e9
ADI_EST = {"0y": {"eps": {"avg": 12.89, "low": 12.35, "high": 14.31, "analysts": 29, "growth": 0.655, "year_ago": 7.79},
                  "revenue": {"growth": 0.373, "analysts": 29}},
           "+1y": {"eps": {"avg": 16.34, "low": 14.0, "high": 19.0, "analysts": 29, "growth": 0.268, "year_ago": 12.89},
                   "revenue": {"growth": 0.204, "analysts": 29}}}
ADI_FY_BASE = (2.267 + 1.999 - 0.534) * B     # FY2025 net income + D&A - capex, $3.732B


def _fmt_b(v):
    return f"${v / 1e9:.3f}B"


def test_adi_fiscal_year_reference_lands_where_the_review_computed_it():
    at_ye = _build(ADI_FY_BASE, ADI_EST, 0.1045, 0.0375, 0.484565465 * B, 0.096)
    rolled = _build(ADI_FY_BASE, ADI_EST, 0.1045, 0.0375, 0.484565465 * B, 0.096, stub_months=10.8)
    assert 300 <= at_ye["value"] <= 324           # Fable: about $312 at the fiscal year end
    assert 330 <= rolled["value"] <= 354          # and about $342 rolled forward to today
    assert abs(rolled["value"] / at_ye["value"] - 1.1045 ** 0.9) < 1e-6
    y1, y2 = rolled["levels"]
    assert abs(y1 / B - 3.732 * 1.655) < 0.01 and abs(y2 / B - 3.732 * 1.655 * 1.268) < 0.01   # $7.83B
    assert rolled["path"][2:] == cr._years35(0.204, 0.096)


def test_years_3_to_5_never_rise_above_next_fy_revenue_growth():
    # GPOR (b): next-FY revenue +1.4% against a conditional median of 15.1% made the path RISE to
    # 15.1% by year 5; the target is now min(median, next-FY revenue growth)
    assert cr._years35(0.014, 0.151) == [0.014, 0.014, 0.014]
    down = cr._years35(0.204, 0.096)
    assert down[0] > down[1] > down[2] == 0.096
    assert cr._years35(None, 0.056) == [0.056, 0.056, 0.056]


def test_range_levels_need_three_analysts_and_a_real_range():
    y2 = 7.83 * B
    bull, bear, n = cr.range_levels(ADI_EST, y2)
    assert n == 29 and abs(bull / y2 - 19.0 / 16.34) < 1e-9 and abs(bear / y2 - 14.0 / 16.34) < 1e-9
    one = {"+1y": {"eps": {"avg": 6.48, "low": 6.48, "high": 6.48, "analysts": 1}}}
    assert cr.range_levels(one, y2) is None                  # LAMR/LIND: no range


# S3 C (brief §5.6): pack_line's text is now typed, pipe-separated clauses, so the legacy regex
# readers (pack_facts._LEVELS_RE / _RANGE_RE / _CIV_RE, wrapped by cv._pack_levels /
# _pack_reference) no longer match a freshly-built line — as designed: those regexes exist to
# parse OLD, already-recorded revision-14 pack text, and pack_line's OUTPUT changed unconditionally
# (not gated by PACK_REVISION), so no fresh pack_line() call produces their old phrasing any more.
# `consensus_ratios` / `check_sample_harness_rules` / `reference_window` already accept a `facts`
# dict directly for exactly this reason; these tests build one from `ref` instead of round-tripping
# through text.
def _facts_from_ref(ref):
    f = pack_facts.empty()
    f["consensus_implied_value"] = ref.get("value")
    lv = ref.get("levels")
    if lv:
        f["levels"] = {"year1": lv[0] / B, "year2": lv[1] / B}
        rng = ref.get("range")
        if rng:
            f["levels"]["bull2"], f["levels"]["bear2"] = rng[0] / B, rng[1] / B
    return f


def test_the_pack_line_prints_levels_the_harness_reads_back():
    ref = _build(ADI_FY_BASE, ADI_EST, 0.1045, 0.0375, 0.484565465 * B, 0.096, stub_months=10.8,
                   base_label="FY2025, the last full fiscal year, ended 2025-11-01")
    line = cr.pack_line(ref, ADI_FY_BASE, 0.1045, 0.0375, _fmt_b)
    assert "rolled forward 11 months" in line and "FY2025, the last full fiscal year" in line
    facts = _facts_from_ref(ref)
    assert abs(facts["levels"]["year2"] - ref["levels"][1] / B) < 0.001
    assert "bull2" in facts["levels"] and "bear2" in facts["levels"]
    assert abs(facts["consensus_implied_value"] - ref["value"]) < 0.01   # the value prefix is unchanged


def _pack_facts_dict(ref):
    return _facts_from_ref(ref)


def test_the_years12_check_is_a_level_check():
    facts = _pack_facts_dict(_build(ADI_FY_BASE, ADI_EST, 0.1045, 0.0375, 0.484565465 * B, 0.096, stub_months=10.8))
    # ADI s2 (b): the TTM base on the consensus rates lands 28% above the year-2 level
    s2 = {"base_cf_used": 4.771, "stage1_growth_path": [0.655, 0.268, 0.168, 0.132, 0.096]}
    assert abs(cv.consensus_ratios(s2, {"estimates": ADI_EST}, facts=facts)["years12_ratio"] - 1.28) < 0.01
    # ADI s1 (b): a cash-basis FY base at +28/+21% lands 22% below it
    s1 = {"base_cf_used": 3.957, "stage1_growth_path": [0.28, 0.21, 0.17, 0.11, 0.09]}
    assert abs(cv.consensus_ratios(s1, {"estimates": ADI_EST}, facts=facts)["years12_ratio"] - 0.78) < 0.01
    # a TTM base that reaches the level is on the anchor
    ok = {"base_cf_used": 4.771, "stage1_growth_path": [0.2946, 0.268, 0.168, 0.132, 0.096]}
    assert abs(cv.consensus_ratios(ok, {"estimates": ADI_EST}, facts=facts)["years12_ratio"] - 1.0) < 0.01


def test_the_harness_flags_a_year2_off_the_level_without_a_reason():
    facts = _pack_facts_dict(_build(ADI_FY_BASE, ADI_EST, 0.1045, 0.0375, 0.484565465 * B, 0.096, stub_months=10.8))

    def flags(sc):
        _, _, fl = cv.check_sample_harness_rules(dict({"base_iv": 342.0, "bull_iv": 400.0, "bear_iv": 200.0}, **sc),
                                                 382.61, enrich_data={"estimates": ADI_EST}, facts=facts)
        return fl
    s2 = {"base_cf_used": 4.771, "stage1_growth_path": [0.655, 0.268, 0.168, 0.132, 0.096]}
    assert "years12_off_consensus_earnings" in flags(s2)
    assert "years12_off_consensus_earnings" not in flags(dict(s2, guidance_deviation_reason="dated evidence"))
    ok = {"base_cf_used": 4.771, "stage1_growth_path": [0.2946, 0.268, 0.168, 0.132, 0.096]}
    assert "years12_off_consensus_earnings" not in flags(ok)

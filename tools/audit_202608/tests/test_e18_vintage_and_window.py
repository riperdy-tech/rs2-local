"""E18 fixes from the whole-book test (2026-09-26, Fable's rulings a and b).

a. The period comes from the consensus vintage: the vendor's year-ago revenue for the current year
   names the fiscal year its estimates start from (EPAC, PSMT, MU: the filed FY2025 to the dollar,
   so their 12.9-month-old fiscal year still anchors consensus). A vendor that has moved past an
   unfiled year gets the EPS levels; a base that is not positive (LIVN) too.
b. The fiscal-year and TTM windows: when the TTM differs from the fiscal-year base grown by
   consensus for the quarters between them by more than 15%, both references are printed and the
   analyst names the window; the harness checks against the nearer one.
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
                  "revenue": {"growth": 0.373, "analysts": 29, "year_ago": 11019707000.0}},
           "+1y": {"eps": {"avg": 16.34, "low": 14.0, "high": 19.0, "analysts": 29, "growth": 0.268, "year_ago": 12.89},
                   "revenue": {"growth": 0.204, "analysts": 29}}}
SH = 0.484565465 * B


def _fmt_b(v):
    return f"${v / 1e9:.3f}B"


# ---- a. the vintage ----------------------------------------------------------------------------

def test_the_vendor_year_ago_revenue_names_the_base_year():
    est = {"0y": {"revenue": {"year_ago": 616899000.0}}}
    assert cr.vintage_aligned(est, 616899000) is True                   # EPAC: FY2025 still current
    assert cr.vintage_aligned(est, 616899000 * 1.021) is False           # the vendor starts elsewhere
    assert cr.vintage_aligned({"0y": {"revenue": {"year_ago": 36.8e9}}}, 28.2e9) is False   # SAP vs FY2017
    assert cr.vintage_aligned({}, 616899000) is None and cr.vintage_aligned(est, None) is None


def test_a_rolled_vintage_values_the_eps_levels_with_its_reason():
    why = "consensus has moved past FY2026, which ended 2026-08-31 and is not yet in our filings (fy_rolled_unfiled)"
    ref = _build(None, ADI_EST, 0.1045, 0.0375, SH, 0.096, da=2.0 * B, capex=0.5 * B,
                   stub_months=0.9, levels_reason=why)
    assert ref["method"] == "levels" and ref["value"] > 0 and ref["levels_reason"] == why
    y1, y2 = ref["levels"]
    assert abs(y1 - (12.89 * SH + 1.5 * B)) < 1 and abs(y2 - (16.34 * SH + 1.5 * B)) < 1
    line = cr.pack_line(ref, None, 0.1045, 0.0375, _fmt_b)
    # S3 C (brief §5.6): pack_line's clauses are lower-cased and pipe-separated now.
    assert f"years 1-2 are consensus EPS x diluted shares + D&A - capex because {why}" in line
    assert "rolled forward 1 months" in line
    assert _fmt_b(y2) in line   # the line prints the year-2 level it computed


def test_a_base_that_is_not_positive_goes_to_the_eps_levels():
    # LIVN: FY2025 net loss of $242M from a one-off; the consensus EPS levels are positive
    ref = _build(-0.277 * B, ADI_EST, 0.1045, 0.0375, SH, 0.096, da=0.046 * B, capex=0.081 * B,
                   stub_months=8.8)
    assert ref["method"] == "levels" and ref["value"] > 0
    assert ref["levels_reason"] == "the fiscal-year owner-earnings base is not positive"


def test_a_positive_base_with_usable_growth_is_unchanged():
    ref = _build(3.732 * B, ADI_EST, 0.1045, 0.0375, SH, 0.096, stub_months=10.8)
    assert ref["method"] == "growth" and ref["levels_reason"] is None and 330 <= ref["value"] <= 354


# ---- b. the two windows ------------------------------------------------------------------------

def _adi():
    return _build(3.732 * B, ADI_EST, 0.1045, 0.0375, SH, 0.096, stub_months=10.8)


def test_adi_gap_is_the_period_effect_not_a_window_gap():
    # FY $3.733B grown by +65.5% for two quarters is $4.80B; the TTM is $4.771B: the E18 period
    # effect itself, which the fiscal-year reference already handles
    win = cr.window_check(_adi(), 3.732 * B, 4.771 * B, 2)
    assert abs(win["gap"]) < 0.01 and win["flag"] is False and win["ttm_value"] is None
    assert cr.window_line(win, _adi(), 4.771 * B, "2026-05-02", _fmt_b) is None


def test_a_one_off_in_one_window_prints_both_references():
    ref = _adi()
    ttm = 3.732 * B * 1.655 ** 0.5 * 1.56          # a TTM carrying a 56% one-off (GOOG's shape)
    win = cr.window_check(ref, 3.732 * B, ttm, 2)
    assert win["flag"] and abs(win["gap"] - 0.56) < 1e-9
    assert abs(win["ttm_value"] - ref["value"] * 1.56) < 1e-6
    assert abs(win["ttm_levels"][1] - ref["levels"][1] * 1.56) < 1
    line = cr.window_line(win, ref, ttm, "2026-05-02", _fmt_b)
    # S3 C (brief §5.6): the line is now pipe-separated clauses, not sentences ending in ".".
    assert line.startswith("- [Arithmetic] BASE WINDOW CHECK: base_window_gap +56% | ")
    assert f"${win['ttm_value']:,.2f} per share" in line
    assert _fmt_b(win["ttm_levels"][1]) in line


def test_a_ttm_that_is_not_positive_prints_no_second_reference():
    win = cr.window_check(_adi(), 3.732 * B, -0.1 * B, 2)
    assert win["flag"] and win["ttm_value"] is None
    line = cr.window_line(win, _adi(), -0.1 * B, "2026-05-02", _fmt_b)
    # S3 C (brief §5.6): the clause is now lower-cased.
    assert "the TTM window's owner earnings are not positive" in line


def test_no_window_check_without_the_growth_method_or_a_ttm():
    assert cr.window_check({"method": "levels", "value": 1.0}, 1.0, 1.0, 2) is None
    assert cr.window_check(_adi(), 3.732 * B, None, 2) is None
    assert cr.window_check(_adi(), 3.732 * B, 4.771 * B, None) is None


# ---- the harness against the two windows --------------------------------------------------------

def _pack_with_window(ttm_mult=1.56):
    ref = _adi()
    ttm = 3.732 * B * 1.655 ** 0.5 * ttm_mult
    win = cr.window_check(ref, 3.732 * B, ttm, 2)
    return (cr.pack_line(ref, 3.732 * B, 0.1045, 0.0375, _fmt_b) + "\n"
            + cr.window_line(win, ref, ttm, "2026-05-02", _fmt_b)), ref, win


# S3 C (brief §5.6): pack_line/window_line's text is no longer parseable by the legacy regex
# readers (see the module-level note above _facts_from_ref-style fixes in test_e18_reference.py);
# `reference_window` / `consensus_ratios` take `facts` directly for exactly this case.
def _facts_with_window(ref, win):
    f = pack_facts.empty()
    f["consensus_implied_value"] = ref["value"]
    f["levels"] = {"year1": ref["levels"][0] / B, "year2": ref["levels"][1] / B}
    f["base_window"] = {"gap": win["gap"], "ttm_value": win["ttm_value"],
                        "ttm_year2": win["ttm_levels"][1] / B}
    return f


def test_the_harness_checks_against_the_fiscal_year_reference_only():
    """Revision 17 (brief B 6): the nearer-window choice is gone. A sample near the TTM window's reference is
    still compared with the fiscal-year reference; the gap stays as information (base_window_gap)."""
    pack, ref, win = _pack_with_window()
    facts = _facts_with_window(ref, win)
    near_ttm = {"base_iv": win["ttm_value"] * 1.02}
    r = cv.consensus_ratios(dict(near_ttm, base_cf_used=3.732 * 1.655 ** 0.5 * 1.56,
                                 stage1_growth_path=[0.2946, 0.268, 0.1, 0.1, 0.1]),
                            {"estimates": ADI_EST}, facts=facts)
    assert r["base_window_gap"] == 0.56
    assert abs(r["base_to_civ"] - near_ttm["base_iv"] / ref["value"]) < 0.001
    assert "reference_window_used" not in r and "reference_window_value" not in r
    assert abs(r["consensus_implied_value"] - ref["value"]) < 0.01


def test_both_windows_printed_needs_a_named_window():
    pack, ref, win = _pack_with_window()

    def flags(**sc):
        _, _, fl = cv.check_sample_harness_rules(dict({"base_iv": ref["value"], "bull_iv": ref["value"] * 1.2,
                                                       "bear_iv": ref["value"] * 0.7}, **sc),
                                                 382.61, enrich_data={"estimates": ADI_EST}, pack_text=pack)
        return fl
    # revision 17: the window no longer changes the Base's arithmetic, so the flag that asked for a named window is gone
    assert "base_window_without_reason" not in flags()
    assert "base_window_without_reason" not in flags(base_cf_reason="none")
    assert "base_window_without_reason" not in flags(base_cf_reason="the TTM holds a one-off gain")
    plain = cr.pack_line(ref, 3.732 * B, 0.1045, 0.0375, _fmt_b)
    _, _, fl = cv.check_sample_harness_rules({"base_iv": ref["value"]}, 382.61,
                                             enrich_data={"estimates": ADI_EST}, pack_text=plain)
    assert "base_window_without_reason" not in fl

"""Phase 4 E15 (joint review with Fable, 2026-09-25): a CONSENSUS-IMPLIED VALUE outside the
harness's frozen fail-fast fence (0.5x the discounted street low, 2x the discounted street high) is
not used. The three commodity names' references were 3.6-6.2x their prices, far above the street's
own targets; every other name's reference, AMD's and FIX's included, sat inside the fence.
"""
import capability_test as cap
import consensus_valuation as cv

BAND = lambda lo, hi, stale=False: {"low": lo, "high": hi, "stale": stale}


def test_the_three_commodity_references_fall_above_the_fence():
    assert cap._reference_outside_fence(75.60, BAND(14.5, 14.5))[0] == "above"      # FSM
    assert cap._reference_outside_fence(564.78, BAND(186.0, 253.0))[0] == "above"   # GPOR
    side, fence = cap._reference_outside_fence(463.69, BAND(76.0, 140.0))           # AU
    assert side == "above" and round(fence[0], 2) == 34.55 and round(fence[1], 2) == 254.55


def test_every_reference_the_design_was_checked_on_stays_inside():
    for v, lo, hi in ((42.08, 42.0, 43.0), (188.35, 151.0, 170.0), (19.24, 29.0, 40.0), (88.18, 85.0, 115.0),
                      (399.32, 365.0, 675.0), (520.27, 365.0, 1250.0), (1892.88, 1910.0, 2500.0)):
        assert cap._reference_outside_fence(v, BAND(lo, hi))[0] is None, v   # UGI LAMR LIND APH ADI AMD FIX


def test_below_the_fence_and_no_fence_without_a_fresh_band():
    assert cap._reference_outside_fence(5.0, BAND(40.0, 50.0))[0] == "below"
    assert cap._reference_outside_fence(564.78, BAND(186.0, 253.0, stale=True)) == (None, None)
    assert cap._reference_outside_fence(564.78, None) == (None, None)
    assert cap._reference_outside_fence(None, BAND(186.0, 253.0)) == (None, None)


def test_the_status_stamp_reads_the_pack():
    used = ("- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $42.08 per share — the "
            "analysts' own earnings path at our discount rate.")
    above = ("- CONSENSUS-IMPLIED VALUE: not used — the consensus path carried forward at our discount rate "
             "lands above the fence [$84.55, $460.00] built from the street's targets (0.5× the lowest and 2× "
             "the highest analyst target, each discounted by 10%), so it is not a credible summary of the "
             "consensus (reference_status: outside_fence_above).")
    assert cv._pack_reference_status(used) == "used"
    assert cv._pack_reference_status(above) == "outside_fence_above"
    assert cv._pack_reference_status("- CONSENSUS-IMPLIED VALUE: not available — owner-earnings base missing") \
        == "not_available"
    assert cv._pack_reference_status("") is None
    # a reference that is not used is not a reference: no base_to_civ, no consensus-gap flag
    assert cv._pack_reference(above)[0] is None and "$460.00" not in used


def test_the_stamp_rides_on_every_sample(tmp_path):
    above = "- CONSENSUS-IMPLIED VALUE: not used — ... (reference_status: outside_fence_above)."
    _, st = cv.scenario_checks(tmp_path, {}, None, above, None)
    assert st["consensus_reference_status"] == "outside_fence_above"

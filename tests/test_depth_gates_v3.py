"""depth_gates v3 (Phase 4 (b), 2026-09-26): the street fence, the 150% margin-of-safety bar, a
desk-less basis sample and a low-effort rescue each make a verdict non-actionable; the row keeps
its verdict. And the verdict writer judges only the samples consensus_valuation counted.

FSM's gate-test verdict ("undervalued" at $63.95 against $11.64, 5.6x the price) passed every
v2 reason; only its gate-test provenance kept it out of the book.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_ORIG_STDOUT = sys.stdout
import depth_pipeline as dp  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT
import depth_gates as dg  # noqa: E402
import valuation_backbone as vb  # noqa: E402

V3 = ["outside_street_fence", "mos_beyond_150pct", "desk_not_used", "low_effort_rescue"]


def _clean(**over):
    base = {"direction": "hold", "gate_version": dg.GATE_VERSION, "n_basis": 2,
            "fiduciary_verdict": "PASS", "kelly_fraction_pct": 0.0, "spread_pct": 5.0,
            "run_source": "orchestrator",
            "producer_class": {"status": "ok", "depleting": False, "sector": "Technology",
                               "industry": "Software - Infrastructure", "source": "stocks.csv@test"},
            "consensus_data_status": "ok",
            "street_fence": {"low": 10.0, "high": 20.0}}
    base.update(over)
    return base


def _v3(v):
    return [r for r in dg.assess(v)[1] if r in V3]


def test_gate_version_is_seven():
    assert dg.GATE_VERSION == 8          # revision 19: reason 19, directional_without_valid_crux; pack revision 20: reasons 20-21


def test_sample_failed_reason():
    v = _clean(flags=["SAMPLE_FAILED:1:window_exhausted_twice"])
    assert dg.assess(v) == (False, ["sample_failed"])
    assert "sample_failed" not in dg.assess(_clean(flags=[]))[1]


def test_discovery_failed_reason():
    v = _clean(flags=["discovery_failed:brief_not_delivered"])
    assert dg.assess(v) == (False, ["discovery_failed"])
    assert "discovery_failed" not in dg.assess(_clean(flags=[]))[1]


# ---- one case per new reason --------------------------------------------------------------

def test_undervalued_above_the_fence_high():
    v = _clean(direction="undervalued", median_iv=30.0, street_fence={"low": 5.0, "high": 26.0})
    assert dg.assess(v) == (False, ["outside_street_fence"])


def test_overvalued_below_the_fence_low():
    v = _clean(direction="overvalued", median_iv=4.0, street_fence={"low": 5.0, "high": 26.0})
    assert dg.assess(v) == (False, ["outside_street_fence"])


@pytest.mark.parametrize("direction, median", [("undervalued", 26.0), ("overvalued", 5.0),
                                               ("hold", 300.0), ("undervalued", 4.0)])
def test_the_fence_is_one_sided_and_inclusive(direction, median):
    # a buy below the fence low is not a fence problem, a hold is never fenced, and the edges pass
    v = _clean(direction=direction, median_iv=median, street_fence={"low": 5.0, "high": 26.0})
    assert "outside_street_fence" not in dg.assess(v)[1]


def test_no_fence_on_the_row_is_no_fence_reason():
    v = _clean(direction="undervalued", median_iv=1e6)
    del v["street_fence"]
    assert "outside_street_fence" not in dg.assess(v)[1]
    v["street_fence"] = None
    assert "outside_street_fence" not in dg.assess(v)[1]


def test_mos_beyond_150pct():
    assert dg.assess(_clean(mos_vs_base_pct=150.1)) == (False, ["mos_beyond_150pct"])
    assert dg.assess(_clean(mos_vs_base_pct=150.0)) == (True, [])
    assert dg.assess(_clean(mos_vs_base_pct=None)) == (True, [])


@pytest.mark.parametrize("flag", ["desk_not_used", "iv_not_desk_backed"])
def test_a_desk_less_basis_sample(flag):
    assert dg.assess(_clean(flags=[flag])) == (False, ["desk_not_used"])


def test_a_low_effort_rescue():
    assert dg.assess(_clean(flags=["LOW_EFFORT_RESCUE"])) == (False, ["low_effort_rescue"])


def test_information_flags_gate_nothing():
    v = _clean(flags=["no_street_fence", "desk_less_sample_excluded:2", "FORCED_REPORT",
                      "scenario_not_desk_backed:bull"])
    assert dg.assess(v) == (True, [])


def test_non_numeric_fields_do_not_raise():
    v = _clean(direction="undervalued", median_iv="63.9", mos_vs_base_pct="442",
               street_fence={"low": None, "high": "26"})
    assert _v3(v) == []


# ---- the (b) records: the rule was set on FSM and is checked, not tuned, on the rest ---------
# direction, median_iv, mos_vs_base_pct and the fence from the saved verdicts and the target
# caches of the (b) run (fence = 0.5x low / 1.10, 2x high / 1.10). Flags are left out: the saved
# rows predate the desk-backed rule, and those reasons have their own tests.

B_RECORDS = [
    ("FSM", "undervalued", 63.945, 442.0, (6.59, 26.36), ["outside_street_fence", "mos_beyond_150pct"]),
    ("GPOR", "undervalued", 417.46, 162.4, (84.55, 460.0), ["mos_beyond_150pct"]),
    ("AU", "hold", 279.68, 225.9, (34.55, 254.55), ["mos_beyond_150pct"]),
    ("ADI", "hold", 318.67, 4.4, (165.91, 1227.27), []),
    ("APH", "hold", 88.14, 6.1, (38.64, 209.09), []),
    ("LIND", "overvalued", 19.135, -30.6, (13.18, 72.73), []),
    ("LAMR", "undervalued", 166.36, 15.8, (68.64, 309.09), []),
    ("UGI", "undervalued", 42.12, 15.8, (19.09, 78.18), []),
    ("FIX", "hold", 1801.47, 0.4, (868.18, 4545.45), []),
    ("AMD", "overvalued", 509.99, -15.6, (165.91, 2272.73), []),
]


@pytest.mark.parametrize("t, direction, median, mos, fence, expected", B_RECORDS,
                         ids=[r[0] for r in B_RECORDS])
def test_b_records(t, direction, median, mos, fence, expected):
    v = _clean(direction=direction, median_iv=median, mos_vs_base_pct=mos,
               street_fence={"low": fence[0], "high": fence[1]})
    assert _v3(v) == expected


# ---- the fence and its stamp ----------------------------------------------------------------

def test_street_fence_is_the_fail_fast_rule(monkeypatch):
    monkeypatch.setattr(vb, "_consensus_band", lambda t: {"low": 14.5, "high": 14.5, "n": 3,
                                                           "age_days": 1.7, "stale": False,
                                                           "source": "openbb"})
    f = vb.street_fence("FSM")
    assert (f["low"], f["high"]) == (6.59, 26.36)
    assert f["n_targets"] == 3 and f["source"] == "openbb" and len(f["asof"]) == 10


@pytest.mark.parametrize("band", [None, {"low": 14.5, "high": 14.5, "stale": True},
                                  {"low": None, "high": 20.0, "stale": False},
                                  {"low": 0, "high": 20.0, "stale": False}])
def test_no_sane_fresh_band_is_no_fence(monkeypatch, band):
    monkeypatch.setattr(vb, "_consensus_band", lambda t: band)
    assert vb.street_fence("X") is None


def test_every_row_is_stamped_with_its_fence(monkeypatch):
    monkeypatch.setattr(vb, "street_fence", lambda t: {"low": 6.59, "high": 26.36})
    v = {"ticker": "FSM", "price": 11.635, "direction": "undervalued", "flags": ["x"]}
    dp.stamp_and_route(v, "FSM", "gate_test")
    assert v["street_fence"] == {"low": 6.59, "high": 26.36}
    assert v["flags"] == ["x"]


def test_a_row_without_a_fence_says_so(monkeypatch):
    monkeypatch.setattr(vb, "street_fence", lambda t: None)
    v = {"ticker": "X", "price": 10.0, "direction": "hold"}
    dp.stamp_and_route(v, "X", "gate_test")
    assert v["street_fence"] is None and "no_street_fence" in v["flags"]
    assert "outside_street_fence" not in dg.assess(v)[1]


# ---- the verdict writer judges the samples consensus_valuation counted ----------------------

def _gpor_doc():
    # GPOR (b): s1 desk-backed, its memorandum forced at low effort; s2 no desk call at all
    return {"ticker": "GPOR", "price": 156.22, "samples_run": 2, "converged": False,
            "median_iv": 409.92, "spread_pct": None,
            "runs": [
                {"sample": 1, "iv": 409.92, "plausible": True, "truncated": False,
                 "forced_report": True, "flags": [], "basis": True},
                {"sample": 2, "iv": 425.0, "plausible": True, "truncated": False,
                 "flags": ["desk_not_used", "iv_not_desk_backed"], "basis": False},
            ],
            "scorecard": {"median_iv": 409.92}}


def test_a_sample_consensus_valuation_left_out_stays_out_of_the_verdict():
    v = dp.band_verdict(_gpor_doc())
    assert v["n_basis"] == 1 and v["iv_band_low"] == v["iv_band_high"] == 409.92
    assert "desk_not_used" not in v["flags"] and "iv_not_desk_backed" not in v["flags"]
    assert "desk_less_sample_excluded:2" in v["flags"] and "LOW_EFFORT_RESCUE" in v["flags"]
    reasons = dg.assess(dict(v, gate_version=dg.GATE_VERSION, run_source="orchestrator"))[1]
    assert "single_sample" not in reasons and "low_effort_rescue" in reasons   # n_basis 1 no longer gates (2026-10-06)
    assert "desk_not_used" not in reasons


def test_a_doc_from_before_the_stamp_keeps_the_old_rule():
    doc = _gpor_doc()
    for r in doc["runs"]:
        del r["basis"]
    v = dp.band_verdict(doc)
    assert v["n_basis"] == 2 and "desk_not_used" in v["flags"]
    assert "desk_not_used" in dg.assess(dict(v, gate_version=dg.GATE_VERSION))[1]

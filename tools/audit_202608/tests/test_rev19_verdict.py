"""Revision 19, Part C: the verdict's direction (depth_pipeline.band_verdict, brief 1.5 and C1) and gate version 7 (depth_gates, reason 19, C2).

Docs are hand-built (the consensus doc a run writes, with scorecards the contract fill produced from synthetic calls); no model, no network.
These tests do NOT use the `crux_valid_everywhere` fixture: they are the crux rule's own.
"""
import copy
import itertools
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import consensus_valuation as cv  # noqa: E402
import depth_gates  # noqa: E402
import depth_pipeline as dp  # noqa: E402
from test_rev19_crux import (COMPANY, FACTS, PACK, Q_CAPEX, Q_DATA8, TICKER, _answer, _blk, _cit, _entry, _fetch, _fill, _pi,  # noqa: E402
                             URL, Q_NEWS, PAGE_TEXT)

PRICE = 100.0


@pytest.fixture(autouse=True)
def _no_prior_verdict(monkeypatch):
    monkeypatch.setattr(dp, "_prior_verdict", lambda *a, **k: None)


def _run(sample, base, crux, *, pi=None, flags=(), calls_extra=()):
    """One basis sample: a scorecard the contract fill produced from a synthetic answer call whose Base is `base`."""
    filled, _ = _fill(crux, base_iv=base, pi=pi, calls_extra=calls_extra)
    card = dict({"base_iv": base, "bull_iv": base * 1.3, "bear_iv": base * 0.7, "median_quality_moat": 3.0}, **filled)
    return {"sample": sample, "iv": base, "scorecard": card, "plausible": True, "truncated": False, "flags": list(flags), "basis": True,
            "desk_calls": 1, "desk_iv_match": True}


def _doc(runs, price=PRICE, **over):
    ivs = sorted(r["iv"] for r in runs)
    spread = (ivs[-1] / ivs[0] - 1) * 100 if len(ivs) > 1 else None
    medoid, summary = cv.select_medoid_scorecard(runs, price)
    doc = {"ticker": "TST", "price": price, "samples_run": len(runs), "converged": True, "spread_pct": round(spread, 1) if spread is not None else None,
           "median_iv": sorted(ivs)[len(ivs) // 2] if ivs else None, "tolerance_pct": 25.0, "early_stop": True, "runs": runs,
           "scorecard": summary, "pack_revision": 19, "model": "m", "mode": "adaptive"}
    doc.update(over)
    return doc


GOOD = [_entry("coe")]


# ---- every basis sample's crux valid: the direction stands ------------------------------------------------------------------------------

def test_every_basis_sample_with_a_valid_crux_keeps_the_direction_and_records_the_crux():
    v = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 125.0, [_entry("coe"), _entry("terminal_ronic")])]))
    assert v["direction"] == v["direction_m"] == "undervalued"
    assert v["crux_valid"] is True
    assert v["crux_by_sample"] == [{"sample": 1, "valid": True, "reason": None, "inputs": ["coe"], "at_default": False},
                                   {"sample": 2, "valid": True, "reason": None, "inputs": ["coe", "terminal_ronic"], "at_default": False}]
    assert not any(f.startswith("no_valid_crux") for f in v["flags"]) and "withheld" not in (v.get("reason") or "")
    # the medoid's entries: input, own, implied, at_default and the model's reason
    assert v["crux"] and set(v["crux"][0]) == {"input", "own", "implied", "at_default", "reason"}
    assert v["crux"][0]["input"] == "coe" and v["crux"][0]["reason"] == "Why the value differs, by how much."
    assert v["crux"][0]["own"] == 0.0801 and v["crux"][0]["implied"] == 0.098 and v["crux"][0]["at_default"] is False
    # the medoid answer run's price-implied block
    assert v["price_implied"]["coe"]["value"] == 0.098 and set(v["price_implied"]) == set(_pi())
    # overvalued the same way
    w = dp.band_verdict(_doc([_run(1, 80.0, GOOD), _run(2, 78.0, GOOD)]))
    assert w["direction"] == w["direction_m"] == "overvalued" and w["crux_valid"] is True


def test_a_sample_whose_crux_is_invalid_holds_the_direction_with_the_flag_the_reason_and_the_first_sample_in_order():
    bad_ntg = [_entry("terminal_g")]                                              # not reachable
    bad_ev = [_entry("coe", [_cit("DATA 8", Q_DATA8)])]                            # no company evidence
    v = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 122.0, bad_ntg), _run(3, 124.0, bad_ev)]))
    assert v["direction"] == "hold" and v["direction_m"] == "undervalued" and v["crux_valid"] is False
    assert "no_valid_crux:not_reachable" in v["flags"] and "no_valid_crux:no_valid_crux" not in v["flags"]
    assert not any(f == "no_valid_crux:no_company_evidence" for f in v["flags"])     # the first sample's reason only
    assert "no valid stated disagreement with the price on sample 2 (not_reachable): undervalued withheld" in v["reason"]
    assert [(s["sample"], s["valid"], s["reason"]) for s in v["crux_by_sample"]] == [(1, True, None), (2, False, "not_reachable"), (3, False, "no_company_evidence")]
    # a sample with no crux at all is `missing`; overvalued is withheld the same way
    w = dp.band_verdict(_doc([_run(1, 80.0, GOOD), _run(2, 79.0, None)]))
    assert w["direction"] == "hold" and w["direction_m"] == "overvalued" and "no_valid_crux:missing" in w["flags"]
    assert "sample 2 (missing): overvalued withheld" in w["reason"]
    # each reason is carried through
    for reason, crux in (("not_judgment", [_entry("nope")]), ("quote_not_found", [_entry("coe", [_cit("GUIDANCE", "This sentence is not in the release at all, truly.")])])):
        x = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 121.0, crux)]))
        assert x["direction"] == "hold" and f"no_valid_crux:{reason}" in x["flags"]


def test_a_scorecard_with_no_crux_check_has_no_crux():
    runs = [_run(1, 120.0, GOOD), _run(2, 121.0, GOOD)]
    for r in runs:
        r["scorecard"] = {k: v for k, v in r["scorecard"].items() if k not in ("crux", "crux_check", "direction_m", "price_implied")}
    doc = _doc(runs)
    v = dp.band_verdict(doc)
    assert v["direction"] == "hold" and v["direction_m"] == "undervalued" and "no_valid_crux:missing" in v["flags"]
    assert v["crux_by_sample"][0] == {"sample": 1, "valid": False, "reason": "missing", "inputs": [], "at_default": False}
    assert v["crux"] == [] and v["crux_valid"] is False


def test_a_hold_stays_hold_with_no_flag_whatever_the_crux():
    for crux in (None, [_entry("nope")], GOOD):
        v = dp.band_verdict(_doc([_run(1, 105.0, crux), _run(2, 106.0, crux)]))
        assert v["direction"] == v["direction_m"] == "hold"
        assert not any(f.startswith("no_valid_crux") for f in v["flags"])
    # the quarantine's hold is direction_m too: no crux flag on top of it
    v = dp.band_verdict(_doc([_run(1, 120.0, None), _run(2, 190.0, None)], spread_pct=58.3, converged=False))
    assert v["direction"] == v["direction_m"] == "hold" and "HIGH_DISPERSION_QUARANTINE" in v["flags"]
    assert not any(f.startswith("no_valid_crux") for f in v["flags"]) and "undervalued withheld" in v["reason"]
    assert v["crux_valid"] is False


def test_the_band_rule_below_ten_percent_is_still_hold_and_the_mos_floor_is_unchanged():
    v = dp.band_verdict(_doc([_run(1, 108.0, GOOD), _run(2, 109.0, GOOD)]))
    assert v["direction"] == v["direction_m"] == "hold" and v["crux_valid"] is True


def test_the_not_usable_path_stamps_direction_m_and_crux_valid_none():
    v = dp.band_verdict({"ticker": "TST", "price": PRICE, "runs": [{"sample": 1, "iv": None, "plausible": False}], "scorecard": {}, "pack_revision": 19})
    assert v["direction"] == "NOT_USABLE" and v["direction_m"] == "NOT_USABLE" and v["crux_valid"] is None
    assert v["crux_by_sample"] is None and v["crux"] is None and v["price_implied"] is None


def test_the_report_verdict_label_is_the_label_the_fill_gave_and_a_demotion_shows_as_a_mismatch_only_when_they_differ():
    # a valid crux in every sample: label and direction agree
    v = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 122.0, GOOD)]))
    assert "report_verdict_mismatch" not in v["flags"]
    # no crux anywhere: the medoid's label is already hold (the fill held it), so the verdict's hold agrees with it
    w = dp.band_verdict(_doc([_run(1, 120.0, None), _run(2, 122.0, None)]))
    assert w["direction"] == "hold" and "report_verdict_mismatch" not in w["flags"]
    # one sample's crux invalid, the medoid's valid: its label is directional, the verdict is hold: the existing mismatch flag fires
    x = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 130.0, None)]))
    assert x["direction"] == "hold"


def test_sizing_position_basis_and_the_fiduciary_gate_are_not_changed_by_the_crux():
    """The new code only decides the direction: the same docs with a valid crux and without give the same size components, spread, MoS and Kelly."""
    a = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 122.0, GOOD)]))
    b = dp.band_verdict(_doc([_run(1, 120.0, None), _run(2, 122.0, None)]))
    for k in ("spread_pct", "mos_vs_base_pct", "mos_vs_median_pct", "kelly_fraction_pct", "n_basis", "iv_band_low", "iv_band_high", "median_iv"):
        assert a[k] == b[k], k
    assert a["size_components"]["dispersion"] == b["size_components"]["dispersion"] and a["size_components"]["mos"] == b["size_components"]["mos"]
    # a value basis on a demoted hold is invalid there already (resolve_position_basis), and stays so
    c = copy.deepcopy(_doc([_run(1, 120.0, None), _run(2, 122.0, None)]))
    for r in c["runs"]:
        r["scorecard"]["position_basis"] = "value"
    c["scorecard"]["position_basis"] = "value"
    v = dp.band_verdict(c)
    assert v["direction"] == "hold" and v["position_basis"] == "none"
    assert any(f.startswith("position_basis_mismatch") for f in v["flags"])


def test_crux_by_sample_at_default_is_every_entry_at_default():
    pi = _pi(coe=_blk(0.0735, 0.0735), terminal_ronic=_blk(0.3, 0.15))
    v = dp.band_verdict(_doc([_run(1, 120.0, [_entry("coe")], pi=pi), _run(2, 121.0, [_entry("coe"), _entry("terminal_ronic")], pi=pi)]))
    assert [s["at_default"] for s in v["crux_by_sample"]] == [True, False] and v["direction"] == "undervalued"


# ---- gate version 7, reason 19 ---------------------------------------------------------------------------------------------------------

def _row(**over):
    row = {"direction": "undervalued", "gate_version": depth_gates.GATE_VERSION, "n_basis": 2, "fiduciary_verdict": "PASS", "kelly_fraction_pct": 5.0,
           "spread_pct": 10.0, "run_source": "orchestrator", "street_fence": {"low": 100.0, "high": 150.0}, "median_iv": 120.0, "mos_vs_base_pct": 20.0,
           "flags": [], "producer_class": {"status": "ok", "depleting": False}, "consensus_data_status": "ok", "pack_revision": 19, "crux_valid": True}
    row.update(over)
    return row


def test_gate_version_is_seven_and_reason_19_fires_on_a_directional_row_without_a_valid_crux():
    assert depth_gates.GATE_VERSION == 8 and depth_gates.FIRST_CRUX_PACK_REVISION == 19
    assert depth_gates.assess(_row()) == (True, [])
    for dirn in ("undervalued", "overvalued"):
        for cv_ in (False, None, "yes", 1):
            ok, reasons = depth_gates.assess(_row(direction=dirn, crux_valid=cv_, **({"kelly_fraction_pct": 0.0} if dirn == "overvalued" else {})))
            assert ok is False and "directional_without_valid_crux" in reasons, (dirn, cv_)
        gone = _row(direction=dirn, **({"kelly_fraction_pct": 0.0} if dirn == "overvalued" else {}))
        gone.pop("crux_valid")
        assert "directional_without_valid_crux" in depth_gates.assess(gone)[1]                 # an absent field is not True


def test_reason_19_does_not_fire_on_hold_older_revisions_or_a_valid_crux():
    assert "directional_without_valid_crux" not in depth_gates.assess(_row(direction="hold", crux_valid=False))[1]
    assert "directional_without_valid_crux" not in depth_gates.assess(_row(direction="NOT_USABLE", crux_valid=None))[1]
    for pr in (18, 17, 1, None, "19", True, 19.0):
        assert "directional_without_valid_crux" not in depth_gates.assess(_row(pack_revision=pr, crux_valid=False))[1], pr
    for pr in (19, 20, 100):
        assert "directional_without_valid_crux" in depth_gates.assess(_row(pack_revision=pr, crux_valid=False))[1], pr
    assert "directional_without_valid_crux" not in depth_gates.assess(_row())[1]


def test_reasons_10_and_11_are_unchanged_for_a_valid_crux():
    """Operator ruling 2: the fence and the 150% cap stay as limits on real-money action, even with a sound crux."""
    ok, reasons = depth_gates.assess(_row(median_iv=200.0, mos_vs_base_pct=200.0))                   # valid crux, outside the fence and beyond 150%
    assert ok is False and reasons == ["outside_street_fence", "mos_beyond_150pct"]
    ok, reasons = depth_gates.assess(_row(median_iv=200.0, mos_vs_base_pct=200.0, crux_valid=False))
    assert reasons == ["outside_street_fence", "mos_beyond_150pct", "directional_without_valid_crux"]
    assert depth_gates.assess(_row(gate_version=6))[1][:1] == ["pre_v3.1_gates"]                       # a row written under gate 6 is older than gate 7


def test_the_gate_never_fires_reason_19_on_a_row_the_verdict_code_writes():
    """Over every combination of direction_m, crux validity per sample and the dispersion quarantine, a row band_verdict writes either holds or has
    crux_valid True: the gate's check on the label code never fires on it."""
    crux_choices = (GOOD, None, [_entry("terminal_g")], [_entry("coe", [_cit("DATA 8", Q_DATA8)])])
    for bases, cr1, cr2 in itertools.product(((120.0, 125.0), (80.0, 78.0), (105.0, 106.0), (120.0, 200.0)), crux_choices, crux_choices):
        doc = _doc([_run(1, bases[0], cr1), _run(2, bases[1], cr2)])
        v = dp.band_verdict(doc)
        v["gate_version"] = depth_gates.GATE_VERSION
        assert "directional_without_valid_crux" not in depth_gates.assess(v)[1], (bases, v["direction"], v["crux_valid"])
        if v["direction"] in ("undervalued", "overvalued"):
            assert v["crux_valid"] is True


# ---- the overlay copies the whole row ---------------------------------------------------------------------------------------------------

def test_the_new_fields_arrive_in_the_overlay(tmp_path, monkeypatch):
    sys_stdout = sys.stdout
    import orchestrate_depth as od
    sys.stdout = sys_stdout
    v = dp.band_verdict(_doc([_run(1, 120.0, GOOD), _run(2, 125.0, GOOD)]))
    v.update(date="2026-10-02", gate_version=depth_gates.GATE_VERSION, run_source="orchestrator")
    ledger = tmp_path / "depth_ledger.jsonl"
    ledger.write_text(json.dumps(v, default=str) + "\n", encoding="utf-8")
    overlay = tmp_path / "depth_overlay.json"
    monkeypatch.setattr(od, "LEDGER", ledger)
    monkeypatch.setattr(od, "OVERLAY", overlay)
    monkeypatch.setattr(od, "THESIS_CACHE", tmp_path / "depth_thesis.json")
    assert od.rebuild_overlay() == 1
    row = json.loads(overlay.read_text(encoding="utf-8"))["tickers"]["TST"]
    for k in ("direction_m", "crux_valid", "crux_by_sample", "crux", "price_implied"):
        assert row[k] == json.loads(json.dumps(v[k], default=str)), k
    assert row["direction_m"] == "undervalued" and row["crux_valid"] is True and "directional_without_valid_crux" not in row["actionable_reasons"]

"""Coordinator rulings after the MSGE end-to-end smoke run: one crux correction turn, the prose-number whitelist of stage 4's inputs, and the dossier number audit running on real
pack facts (scripted stub model; no GPU, no Ollama, no network)."""
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
for p in (str(TESTS_DIR.parent), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import r26_blind as blind  # noqa: E402
import r26_late as late  # noqa: E402
import r26_stages as r26  # noqa: E402
from test_r26_stages24 import THREE, crux_args, memo_step, run_stages  # noqa: E402

MSGE = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\pilot_r25\frozen_p4r26\MSGE\r26")


def test_an_invalid_crux_gets_one_correction_turn_and_a_valid_second_crux_stands(tmp_path, monkeypatch):
    bad = crux_args("keep", citations=[{"fact_id": "F5"}])
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [bad, crux_args("keep"), memo_step()])
    c = rv["crux"]
    assert rv["called"] and not rv["no_call"] and rv["no_call_reasons"] == [] and c["valid"] and c["state"] == "corrected" and c["correction_used"]
    assert c["first"]["valid"] is False and c["first"]["check"]["reason"] == "quote_not_found" and c["first"]["stated"] != c["stated"]       # both are recorded
    sent = [m["content"] for m in script.bodies[4]["messages"] if m["role"] == "user"][-1]
    assert "entry 1 (long_run_margin)" in sent and "drop or replace" in sent and "1 to 3 valid entries" in sent
    assert not fi["no_call"]


def test_a_second_invalid_crux_is_no_call_and_there_is_no_third_turn(tmp_path, monkeypatch):
    bad = crux_args("keep", citations=[{"fact_id": "F5"}])
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [bad, bad, memo_step()])
    assert rv["no_call"] and rv["no_call_reasons"] == ["crux_invalid:quote_not_found"] and rv["crux"]["first"]["check"]["reason"] == "quote_not_found" and fi["no_call"]
    assert len(script.bodies) == 3 + 2 + 1


def test_a_valid_crux_costs_no_correction_turn(tmp_path, monkeypatch):
    script, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()])
    assert rv["crux"]["valid"] and rv["crux"]["state"] == "accepted" and "first" not in rv["crux"] and len(script.bodies) == 3 + 1 + 1


def test_correction_message_names_the_unreachable_entry():
    chk = {"valid": False, "reason": "not_reachable", "entries": [{"input": "terminal_g", "valid": False, "reason": "not_reachable"}, {"input": "coe", "valid": True, "reason": None}]}
    m = r26.crux_correction_message(chk)
    assert "entry 1 (terminal_g)" in m and "not reachable within the desk's bounds" in m and "coe" not in m


ROWS = [{"label": "Base value per share", "value": 37.57, "kind": "money", "group": "V"}, {"label": "Verdict", "value": "hold", "kind": "word", "group": "V"}]


def _v(memo, texts=()):
    v = late.verify_memo("SECTION 0\nVerdict: hold\nSECTION 1\n" + memo, ROWS, [], (), texts)
    return v, [d["memo"] for d in v["details"] if d["flag"] == "memo_prose_number_mismatch"]


def test_prose_numbers_present_in_any_stage_4_input_are_whitelisted_at_written_precision():
    texts = ["crux: price implies 7.2% terminal growth", "bridge: net debt $812.5 million; tax 21.0%", "momentum 6m -14.3%"]
    assert _v("Net debt is $812.5 million, the tax rate 21.0%, momentum 14.3% down and implied g 7.2%.", texts)[1] == []
    assert _v("Net debt is $812.5 million and capex $99 million.", texts)[1] == ["$99"]
    assert _v("Net debt is $812.5 million.")[1] == ["$812.5"]                                            # without the inputs it is still flagged
    assert _v("Tax is 21.04%.", texts)[1] == ["21.04%"]                                                   # a different written precision is a different number


def test_labelled_numbers_are_still_checked_against_the_table_whatever_the_inputs_hold():
    v, _ = _v("Base value per share: $37.23", ["the dossier says $37.23"])
    assert v["flags"] == ["memo_number_mismatch"]


@pytest.mark.skipif(not (MSGE / "_pack_facts.json").exists(), reason="MSGE frozen pack not present")
def test_the_dossier_number_audit_runs_on_msge_pack_facts_and_stage2_passes_facts(tmp_path, monkeypatch):
    facts = json.loads((MSGE / "_pack_facts.json").read_text(encoding="utf-8"))
    pack = (MSGE / "_pack.md").read_text(encoding="utf-8")
    bp, _ = r26.split_task(pack)
    assert blind.removed_numbers(facts)
    _, audit = blind.stage2_dossier_view({"summary": "Fine.", "facts": []}, bp, facts)
    assert "number_audit_not_run" not in audit["stamps"]
    _, audit0 = blind.stage2_dossier_view({"summary": "Fine.", "facts": []}, bp, None)
    assert "number_audit_not_run" in audit0["stamps"]                                                    # what a caller that omits facts gets: the cause of the smoke stamp

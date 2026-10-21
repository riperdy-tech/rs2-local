"""Iteration-1 findings of the revision-26 benchmark (2026-10-21): a non-positive owner earnings is a data no_call decided before any model call (OGE, HNRG, PTCT ended every stage-2 sample
desk_error), the desk's error text is always recorded, the memo's verdict line is read wherever SECTION 0 is, the crux form message names exactly the inputs the stage offered, and reveal.json
records the verification of every crux entry. No GPU, no Ollama, no network."""
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(AUDIT_DIR.parent), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import crux_check  # noqa: E402
import llm_provider as prov  # noqa: E402
import r26_forecast as rf  # noqa: E402
import r26_late as late  # noqa: E402
import r26_stages as r26  # noqa: E402
from test_r26_forecast import DBAR  # noqa: E402
from test_r26_stage1 import Script  # noqa: E402
from test_r26_stages24 import THREE, PRICE, crux_args, dossier, memo_step, run_stages, valuation  # noqa: E402
from test_rev25_bridge import LR, _ctx  # noqa: E402


# ---------------------------------------------------------------- 1. a non-positive base_cf

@pytest.mark.parametrize("oe", [-0.054, -1e-9, 0.0])
def test_a_non_positive_owner_earnings_is_a_data_no_call_with_no_model_call(tmp_path, monkeypatch, oe):
    facts = {"long_run": dict(LR), "owner_earnings_default_b": oe, "population_ranges": {"family": "operating"}, "op_margin_bar": dict(DBAR, basis="operating")}
    u = r26.valuation_inputs(facts, PRICE, _ctx(price=PRICE, desk_schema=None))
    assert u["base_cf"] is None and u["base_cf_unavailable"].startswith("base_cf_unavailable") and repr(oe) in u["base_cf_unavailable"] and "not positive" in u["base_cf_unavailable"]
    script = Script()
    monkeypatch.setattr(prov, "chat", script)
    kw = dict(run_dir=tmp_path, model="m", dossier=dossier(), valuation=u, op_margin_bar=DBAR, verbose=False)
    f2 = r26.run_stage2(blind_pack="B", seed=1, **kw)
    r2 = r26.run_stage3(blind_pack="B", forecasts=f2, **kw)
    assert script.bodies == [] and f2["samples"] == [] and f2["base_cf_unavailable"] and r2["no_call_reasons"] == ["base_cf_unavailable"]


def test_a_positive_owner_earnings_is_still_valued():
    facts = {"long_run": dict(LR), "owner_earnings_default_b": 1e-9, "population_ranges": {"family": "operating"}}
    assert r26.valuation_inputs(facts, PRICE, {})["base_cf"] == 1e-9


def test_the_desk_error_text_is_never_absent():
    d = rf.desk_error_text
    assert d({"error": "base_cf must be positive", "missing": ["x"]}) == "base_cf must be positive"
    assert d({"error": None, "missing": ["a (b)", "c"]}) == "a (b); c"
    assert d({"error": "", "missing": "only this"}) == "only this"
    assert "no error text" in d({"validation_error": True}) and d({"validation_error": True}).strip()
    assert d(None).strip()


def test_a_desk_refusal_is_recorded_with_its_text(tmp_path, monkeypatch):
    """The path OGE took (before the pre-check): a refused desk run is a desk_error sample whose valuation says why, in every sample."""
    val = valuation()
    val["base_cf"] = -0.054                                                                 # what the pack held, passed straight to the desk
    monkeypatch.setattr(prov, "chat", Script(*THREE))
    fc = r26.run_stage2(run_dir=tmp_path, model="m", dossier=dossier(), blind_pack="B", seed=3, valuation=val, op_margin_bar=DBAR, verbose=False)
    assert [s["status"] for s in fc["samples"]] == ["desk_error"] * 3
    for s in fc["samples"]:
        assert "base_cf must be positive" in s["valuation"]["message"] and s["base_value"] is None
    assert fc["median_index"] is None


def test_trim_valuation_always_carries_the_message_of_a_failed_valuation():
    assert r26.trim_valuation({"status": "desk_error", "desk": {"validation_error": True}, "scenarios": {}})["message"].strip()
    assert r26.trim_valuation({"status": "valuation_error", "scenarios": {}})["message"].strip()
    assert "message" not in r26.trim_valuation({"status": "ok", "scenarios": {}})


# ---------------------------------------------------------------- 3. the memo's verdict line

HEADS = json.loads((TESTS_DIR / "fixture_data" / "r26_iter1_memo_heads.json").read_text(encoding="utf-8"))
REAL = {"MSGE": "overvalued", "BUD": "undervalued", "GOLD": "undervalued", "ITGR": "overvalued", "TASK": "no_call", "MCY": "no_call"}


@pytest.mark.parametrize("name", sorted(REAL))
def test_the_verdict_line_of_the_real_memos_is_read(name):
    """The heads of the six iteration-1 memos (everything before SECTION 1), as the model wrote them: a first line `Verdict: <word>` with SECTION 0 headed after it, or not headed."""
    assert late._verdict_word(HEADS[name]["head"]) == REAL[name]
    assert late._verdict_word(HEADS[name]["head"] + "\nSECTION 1. Business\nbody mentions undervalued") == REAL[name]


@pytest.mark.parametrize("memo,word", [
    ("Verdict: overvalued\nThe desk...\n\nSECTION 1. x", "overvalued"),
    ("**Verdict:** Overvalued\n\nSECTION 1", "overvalued"),
    ("## Verdict - FAIRLY VALUED\nSECTION 1", "hold"),
    ("> *Verdict*: no-call (crux invalid)\nSECTION 1", "no_call"),
    ("- `Verdict`: No call\nSECTION 1", "no_call"),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nnothing else", "hold"),                                     # the earlier layout still reads
    ("## SECTION 0. Overview\n\nThe desk's verdict is undervalued here.\n\nSECTION 1", "undervalued"),     # a headed SECTION 0 without a verdict line: the old rule
    ("Some intro\nSECTION 1\nVerdict: undervalued", None),                                               # a verdict after SECTION 1 is not the head's
    ("The company is overvalued.\n\nSECTION 1", None),                                                   # no verdict line, no SECTION 0
    ("", None),
])
def test_the_verdict_line_forms(memo, word):
    assert late._verdict_word(memo) == word


def test_the_verifier_no_longer_reports_a_memo_verdict_of_none_for_a_first_line_verdict():
    rows = [{"label": "Verdict", "value": "overvalued", "kind": "word", "group": "V"}]
    assert late.verify_memo(HEADS["MSGE"]["head"], rows)["flags"] == []
    assert late.verify_memo(HEADS["MSGE"]["head"], [dict(rows[0], value="hold")])["details"][0]["memo"] == "overvalued"


# ---------------------------------------------------------------- 4. the crux form message

def _entry(**over):
    e = {"input": "coe", "reason": "why", "citations": [{"source": "DATA 5", "date": "2026-10-01", "quote": "q" * 40}]}
    e.update(over)
    return e


def test_the_crux_form_message_names_exactly_the_inputs_the_stage_offered():
    offered = late.CRUX_INPUTS
    missing = crux_check.form_problems([{k: v for k, v in _entry().items() if k != "input"}], "2026-10-20", offered)
    assert missing == [f"crux[1].input (one of {', '.join(offered)})"] and "growth_years_3_5" not in missing[0] and "year2_level" not in missing[0]
    stale = crux_check.form_problems([_entry(input="year2_level")], "2026-10-20", offered)
    assert len(stale) == 1 and "not offered on this desk path" in stale[0] and "growth_years_3_5" not in stale[0].split("one of")[1]
    assert crux_check.form_problems([_entry(input="coe")], "2026-10-20", offered) == []
    assert "growth_years_3_5" in crux_check.form_problems([_entry(input="zzz")], "2026-10-20")[0]       # the production desk (no `inputs`) still lists its seven


def test_a_stage_3_form_failure_message_lists_the_offered_inputs(tmp_path, monkeypatch):
    bad = crux_args("keep")
    del bad["tool_calls"][0]["function"]["arguments"]["crux"][0]["input"]
    _, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [bad, bad], stages=(2, 3))
    msg = " ".join(rv["crux"]["form_problems"])
    assert f"one of {', '.join(late.CRUX_INPUTS)}" in msg and "growth_years_3_5" not in msg and "year2_level" not in msg


# ---------------------------------------------------------------- 5. the verification detail of every crux entry

def test_crux_entry_details_record_the_reachability_and_why_not():
    pi = {"coe": {"value": 0.059, "reachable": True, "own": 0.0927, "bound": {"low": 0.051, "high": 0.25, "value_low": 118.9, "value_high": 18.5}, "side": None, "stamps": []},
          "terminal_g": {"value": None, "reachable": False, "own": 0.0375, "bound": {"low": 0.0, "high": 0.0447, "value_low": 18.39, "value_high": 21.24}, "side": "below", "stamps": []},
          "year2_level": {"value": None, "reachable": False, "own": 0.1, "bound": {"low": None, "high": None, "value_low": None, "value_high": None}, "side": None,
                          "not_available": "not applicable under desk schema 25.1"}}
    chk = {"valid": False, "reason": "not_reachable", "entries": [
        {"input": "coe", "own": 0.0927, "implied": 0.059, "reachable": True, "valid": True, "reason": None},
        {"input": "terminal_g", "own": 0.0375, "implied": None, "reachable": False, "valid": False, "reason": "not_reachable"},
        {"input": "year2_level", "own": 0.1, "implied": None, "reachable": False, "valid": False, "reason": "not_reachable"},
        {"input": None, "own": None, "implied": None, "reachable": False, "valid": False, "reason": "not_judgment"}]}
    d = r26.crux_entry_details(chk, pi, 8.22)
    assert [(e["input"], e["reachable"], e["valid"], e["implied"], e["reason"]) for e in d] == [
        ("coe", True, True, 0.059, None), ("terminal_g", False, False, None, "not_reachable"), ("year2_level", False, False, None, "not_reachable"), (None, False, False, None, "not_judgment")]
    assert d[0]["not_computable"] is None and d[0]["bound"]["high"] == 0.25
    assert "not reachable" in d[1]["not_computable"] and "below" in d[1]["not_computable"] and "18.39" in d[1]["not_computable"] and "21.24" in d[1]["not_computable"]
    assert d[2]["not_computable"].startswith("not available: not applicable")
    assert d[3]["not_computable"] == "the entry names no input"
    assert r26.crux_entry_details(chk, None, 8.22)[0]["not_computable"] == "no price_implied block for this input"
    assert r26.crux_entry_details(None, pi, 1.0) == []


def test_reveal_json_records_the_entries_of_the_first_and_the_corrected_crux(tmp_path, monkeypatch):
    bad = crux_args("keep", citations=[{"fact_id": "F5"}])                                               # the quote of F5 is not in its page: quote_not_found
    _, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [bad, crux_args("keep"), memo_step()], stages=(2, 3))
    on_disk = json.loads((tmp_path / "reveal.json").read_text(encoding="utf-8"))
    for crux in (rv["crux"], on_disk["crux"]):
        assert crux["state"] == "corrected" and len(crux["entries"]) == 1 and len(crux["first"]["entries"]) == 1
        first, final = crux["first"]["entries"][0], crux["entries"][0]
        for e in (first, final):
            assert set(e) >= {"input", "own", "reachable", "valid", "implied", "not_computable", "bound", "side", "reason"}
            assert e["input"] == "long_run_margin" and e["reachable"] is True and e["implied"] is not None and e["not_computable"] is None
        assert (first["valid"], first["reason"]) == (False, "quote_not_found") and (final["valid"], final["reason"]) == (True, None)


# ---------------------------------------------------------------- iteration 2: no positive share count (KOF, a 20-F filer whose DATA 2 count is filed as 0)

@pytest.mark.parametrize("sh", [None, 0.0, -1.0])
def test_no_positive_share_count_is_a_data_no_call_with_no_model_call(tmp_path, monkeypatch, sh):
    facts = {"long_run": dict(LR), "owner_earnings_default_b": 0.5, "population_ranges": {"family": "operating"}, "op_margin_bar": dict(DBAR, basis="operating"),
             "shares_warning": "DATA 2's count is filed as 0"}
    ctx = dict(_ctx(price=PRICE, desk_schema=None), shares_default_b=sh)
    u = r26.valuation_inputs(facts, PRICE, ctx)
    assert u["base_cf"] == 0.5 and u["shares_unavailable"].startswith("shares_unavailable") and "filed as 0" in u["shares_unavailable"]
    assert u["bridge_unavailable"] is None                       # decided before the bridge: one reason per name
    script = Script()
    monkeypatch.setattr(prov, "chat", script)
    kw = dict(run_dir=tmp_path, model="m", dossier=dossier(), valuation=u, op_margin_bar=DBAR, verbose=False)
    f2 = r26.run_stage2(blind_pack="B", seed=1, **kw)
    r2 = r26.run_stage3(blind_pack="B", forecasts=f2, **kw)
    assert script.bodies == [] and f2["samples"] == [] and f2["shares_unavailable"] and r2["no_call_reasons"] == ["shares_unavailable"]


def test_a_positive_share_count_raises_no_shares_no_call():
    facts = {"long_run": dict(LR), "owner_earnings_default_b": 0.5, "population_ranges": {"family": "operating"}}
    assert r26.valuation_inputs(facts, PRICE, dict(_ctx(price=PRICE, desk_schema=None), shares_default_b=0.048))["shares_unavailable"] is None

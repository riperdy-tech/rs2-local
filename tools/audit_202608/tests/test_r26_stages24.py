"""Brief R26-A2, SPEC revision 26 sections 2-4: stage 2 (the blind forecast, K = 3), stage 3 (the reveal), stage 4 (the memorandum and the verifier), and the four stages
end to end on a fixture name, all with a scripted stub model (no GPU, no Ollama, no network)."""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(AUDIT_DIR.parent), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import contract_fill  # noqa: E402
import crux_check  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import llm_provider as prov  # noqa: E402
import r26_forecast as rf  # noqa: E402
import r26_late as late  # noqa: E402
import r26_stages as r26  # noqa: E402
from test_r26_forecast import DBAR, DFACTS, desk_forecast  # noqa: E402
from test_r26_stage1 import PACK, PAGE_TEXT, PAGE_URL, Script, _fact, call, stub_world  # noqa: E402,F401
from test_rev25_bridge import BASE_CF, LR, _ctx  # noqa: E402

PRICE = 400.0
RUN_DATE = "2026-10-19"
QUOTE = "Operating revenues increased by $12.2 million, to $274.4 million in the three months ended June 30, 2026."


# ---------------------------------------------------------------- fixtures

def dossier():
    def f(i, usable, dur, **kw):
        d = {"fact_id": f"F{i}", "source": "pack:primary-p1", "quote": "q", "entity": "XYZ", "metric": "operating revenues", "period": "Q2 2026", "value": 1.0,
             "unit": "USD m", "basis": "filed_gaap", "duration_years": dur, "usable": usable, "unusable_reason": None if usable else "quote not found in its source"}
        d.update(kw)
        return d
    return {"facts": [f(1, True, 4.7), f(2, True, "ongoing"), f(3, False, None)], "summary": "XYZ makes things.", "done": True, "incomplete": False,
            "counts": {"facts": 3, "usable": 2, "unusable": 1}}


def valuation(price=PRICE, bridge=None):
    return {"rev0": 100.0, "base_cf": BASE_CF, "bridge_facts": dict(DFACTS if bridge is None else bridge), "desk_params": r26.default_desk_params(),
            "desk_context": _ctx(price=price, desk_schema=None), "price": price, "min_mos": None, "run_date": RUN_DATE}


def fcast(m=0.40, **over):
    """desk_forecast() with the Base's near-term and long-run operating margin m (Bull +2 points, Bear -3 points)."""
    f = desk_forecast()
    for n, d in (("Base", 0.0), ("Bull", 0.02), ("Bear", -0.03)):
        s = f["scenarios"][n]
        s["near_term"]["op_margin"] = [m + d, m + d]
        s["long_run_margin_op"] = m + d
        s["normalized"]["baseline"] = "last"
        s["normalized"]["reason"] = "REASON-MARKER of stage two"
    f.update(over)
    return f


def sub(fc):
    return call("submit_forecast", **fc)


def cons_op(y1_op):
    """A consensus_corrected whose year-1 operating-basis equivalent (by the bridge) is y1_op."""
    r1, r2 = 110.0, 118.8
    x = lambda op, r: (op - 2.0 / r) * 0.75 + 0.75 * 1.0 / r
    return {"status": "ok", "x_margins": [x(y1_op, r1), x(y1_op, r2)], "revenue": [r1, r2], "op_margins": "pending_bridge"}


def crux_args(decision="keep", **over):
    e = {"input": "long_run_margin", "reason": "the long-run margin is what the filings support",
         "citations": [{"source": f"page:{PAGE_URL}", "date": "2026-08-04", "quote": QUOTE}]}
    e.update(over)
    return call("state_crux", crux=[e], decision=decision)


FETCH = [{"tool": "fetch_page", "params": {"url": PAGE_URL}, "url": PAGE_URL, "text": PAGE_TEXT}]


def memo_step(verdict=None, extra="", contract=None, mutate=None):
    """A stage-4 reply: SECTION 0 and every line of the frozen table copied under SECTION 1 (so every labelled number is the table's), then the contract."""
    def step(body):
        text = body["messages"][0]["content"]
        blk = text.split("FROZEN DESK TABLE")[1].split("\n\n")[0]
        lines = [ln for ln in blk.split("\n")[1:] if re.match(r"^[A-Z][^:\n]+: .+$", ln)]
        v = verdict or next(ln.split(": ", 1)[1] for ln in lines if ln.startswith("Verdict: "))
        word = "no call" if v == "no_call" else v
        memo = f"SECTION 0 - VERDICT\nVerdict: {word}. Because the table says so.\n\nSECTION 1 - THE NUMBERS\n" + "\n".join(lines) + "\n" + extra
        if mutate:
            memo = mutate(memo)
        c = contract if contract is not None else {"cycle_evidence": "none", "margin_persistence": "structural", "thesis_invalidation_trigger": "revenue growth below zero"}
        return {"role": "assistant", "content": memo + "\n```json:underwriting\n" + json.dumps(c) + "\n```\n"}
    return step


def run_stages(tmp_path, monkeypatch, steps, *, fcs=None, price=PRICE, cc=None, bridge=None, stages=(2, 3, 4), seed=700, dossier_=None):
    """Stages 2-4 over a scripted model. Returns (script, forecasts, reveal, final)."""
    script = Script(*steps)
    monkeypatch.setattr(prov, "chat", script)
    val = valuation(price, bridge)
    d = dossier_ or dossier()
    kw = dict(run_dir=tmp_path, model="m", dossier=d, valuation=val, op_margin_bar=DBAR, verbose=False)
    fc = r26.run_stage2(blind_pack="BLIND PACK TEXT", seed=seed, **kw)
    rv = r26.run_stage3(consensus_corrected=cc, blind_pack="BLIND PACK TEXT", fetch_calls=FETCH, company="Danaos Corporation", ticker="DAC", facts={}, forecasts=fc, seed=seed, **kw) \
        if 3 in stages else None
    fi = r26.run_stage4(facts={}, blind_pack="BLIND PACK TEXT", fetch_calls=FETCH, company="Danaos Corporation", ticker="DAC", forecasts=fc, reveal=rv, seed=seed, **kw) \
        if 4 in stages else None
    return script, fc, rv, fi


THREE = [sub(fcast(0.40)), sub(fcast(0.41)), sub(fcast(0.39))]          # three hold-direction samples at PRICE


# ---------------------------------------------------------------- stage 2

def test_the_stage_2_tool_schema_is_the_spec_s_submit_forecast():
    t = late.SUBMIT_FORECAST_TOOL["function"]
    assert t["name"] == "submit_forecast" and t["parameters"]["required"] == ["discount_rate", "frame", "scenarios"]
    props = t["parameters"]["properties"]
    assert props["frame"]["enum"] == ["equity", "firm"] and set(props["scenarios"]["properties"]) == {"Base", "Bull", "Bear"}
    sc = props["scenarios"]["properties"]["Base"]["properties"]
    assert set(sc) == {"near_term", "normalized", "transition", "transition_year", "long_run_margin_op", "terminal_g", "terminal_ronic", "fade_years", "prob", "long_run_fact_ids"}
    assert set(sc["near_term"]["properties"]) == {"rev_growth", "op_margin", "fact_ids"}
    assert set(sc["normalized"]["properties"]) == {"year", "rev_growth", "baseline", "delta_pts", "fact_ids", "reason"}
    assert sc["normalized"]["properties"]["baseline"]["enum"] == ["min", "p25", "median", "p75", "max", "last"]
    assert sc["transition"]["enum"] == ["linear", "step_at_year", "hold_then_linear"]
    assert sc["near_term"]["properties"]["rev_growth"]["minItems"] == 2 == sc["near_term"]["properties"]["op_margin"]["maxItems"]
    blob = json.dumps(t)
    assert "minimum" not in blob and "maximum" not in blob                       # structure and enums only, no bound on a number
    assert rf.validate_forecast(fcast(), dossier()) == []                       # what the schema describes is what C's validator accepts


def test_k_equals_3_sessions_with_seeds_s_s1_s2_each_fresh_from_the_same_inputs(tmp_path, monkeypatch):
    script, fc, _, _ = run_stages(tmp_path, monkeypatch, THREE, stages=(2,), seed=700)
    assert [b["options"]["seed"] for b in script.bodies] == [700, 701, 702] and fc["seeds"] == [700, 701, 702] and fc["k"] == 3
    firsts = [b["messages"] for b in script.bodies]
    assert all(len(m) == 1 and m[0]["role"] == "user" for m in firsts) and firsts[0] == firsts[1] == firsts[2]
    text = firsts[0][0]["content"]
    assert text.startswith("BLIND PACK TEXT") and "RESEARCH DOSSIER" in text and "FILED OPERATING MARGIN HISTORY" in text and "STAGE 2 OF 4" in text
    assert [t["function"]["name"] for t in script.bodies[0]["tools"]] == ["submit_forecast"]
    assert "[F3] metric" not in text and "[F1] XYZ" in text and "UNUSABLE FACTS" in text and "F3" in text
    for lbl in ("MARKET PRICE", "CONSENSUS", "default"):
        assert lbl not in text.split("STAGE 2 OF 4")[0].replace("BLIND PACK TEXT", "")
    assert [s["status"] for s in fc["samples"]] == ["valued"] * 3 and fc["median_index"] == 0 and fc["aggregate"]["median"] == pytest.approx(fc["samples"][0]["base_value"])


def test_one_structure_repair_turn_per_session_then_the_sample_is_dropped(tmp_path, monkeypatch):
    bad = fcast()
    del bad["scenarios"]["Bull"]["near_term"]
    bad2 = fcast()
    bad2["scenarios"]["Base"]["normalized"]["year"] = 9
    script, fc, _, _ = run_stages(tmp_path, monkeypatch, [sub(bad), sub(fcast(0.40)),                     # sample 1: one repair, then valid
                                                          sub(bad), sub(bad2),                              # sample 2: a second failure -> forecast_invalid, no third turn
                                                          sub(fcast(0.39))], stages=(2,))
    s1, s2, s3 = fc["samples"]
    assert s1["status"] == "valued" and s1["repair_used"] and s1["submissions"] == 2
    assert s2["status"] == "forecast_invalid" and s2["submissions"] == 2 and s2["forecast"] is None and s2["base_value"] is None and s2["ended"] == "closed"
    assert any(p["problem"] == "normalized_year_out_of_range" for p in s2["problems"])
    assert s3["status"] == "valued" and not s3["repair_used"]
    assert len(script.bodies) == 5                                                       # 2 + 2 + 1 turns: no third attempt for sample 2
    repair = [m["content"] for m in script.bodies[1]["messages"] if m["role"] == "tool"][0]
    assert "Bull.near_term" in repair and "one correction" in repair
    assert fc["aggregate"]["dropped"] == [1] and fc["aggregate"]["n"] == 2


def test_a_turn_without_a_tool_call_gets_one_nudge_then_the_sample_has_no_forecast(tmp_path, monkeypatch):
    script, fc, _, _ = run_stages(tmp_path, monkeypatch, [{"role": "assistant", "content": "I think it is worth a lot."}, {"role": "assistant", "content": "Still."},
                                                          sub(fcast()), sub(fcast()), ], stages=(2,))
    assert fc["samples"][0]["status"] == "no_forecast" and fc["samples"][0]["ended"] == "no_tool_call" and script.bodies[1]["messages"][-1]["content"] == r26.SUBMIT_NUDGE


def test_forecasts_json_contents_and_the_sample_records(tmp_path, monkeypatch):
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, THREE, stages=(2,))
    on_disk = json.loads((tmp_path / "forecasts.json").read_text("utf-8"))
    assert on_disk["schema"] == "r26.forecasts.v1" and on_disk["spread"] == pytest.approx(fc["spread"]) and on_disk["median_index"] == 0
    bv = on_disk["base_values"]
    want = [r26._value(fcast(m), valuation(), DBAR)["base_value"] for m in (0.40, 0.41, 0.39)]          # an independent recompute of each sample's Base
    assert bv == pytest.approx(want, rel=1e-12) and on_disk["spread"] == pytest.approx((max(want) - min(want)) / sorted(want)[1])
    s = on_disk["samples"][0]
    assert s["forecast"]["scenarios"]["Base"]["normalized"]["baseline"] == "last"
    assert [r["year"] for r in s["valuation"]["scenarios"]["Base"]["bridge"]["rows"]] == [1, 2, 3, 4, 5]
    assert s["valuation"]["scenarios"]["Base"]["bridge"]["assumptions"] and s["valuation"]["values"]["Base"] == pytest.approx(s["base_value"])
    assert [a["fact_id"] for a in s["alt_paths"]] == ["F1"] and s["alt_paths"][0]["label"] == "alt_path_after_evidence_expiry" and s["alt_paths"][0]["value"] is not None
    assert s["valuation"]["scenarios"]["Base"]["path"]["normalized"]["value"] == pytest.approx(0.40)
    assert on_disk["valuation_inputs"]["bridge_facts"] == DFACTS and on_disk["op_margin_bar"] == DBAR


def test_an_unusable_fact_cited_is_stamped_and_an_unmeasured_tax_rate_leaves_the_sample_unvalued(tmp_path, monkeypatch):
    f = fcast()
    f["scenarios"]["Base"]["near_term"]["fact_ids"] = ["F3"]
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [sub(f), sub(fcast()), sub(fcast())], stages=(2,), bridge=dict(DFACTS, tax_rate=None))
    assert "cites_unusable_fact:F3" in fc["samples"][0]["stamps"]
    assert [s["status"] for s in fc["samples"]] == ["bridge_unavailable_tax"] * 3 and fc["median_index"] is None and fc["samples"][0]["base_value"] is None


# ---------------------------------------------------------------- stage 3

def test_stage_3_sees_the_numbers_only_never_the_stage_2_reason_and_nothing_of_the_other_sessions(tmp_path, monkeypatch):
    script, fc, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()], cc=cons_op(0.45))
    body = script.bodies[3]
    assert len(body["messages"]) == 1
    text = body["messages"][0]["content"]
    assert "REASON-MARKER" not in text and "makes things" in text                          # the dossier is handed over, the stage-2 reasoning is not
    assert "MARKET PRICE: $400.00" in text and "PRICE-IMPLIED INPUTS" in text and "BASIS-CORRECTED CONSENSUS" in text and "DIAGNOSTICS" in text
    assert "BASE VALUES OF THE THREE STAGE-2 SAMPLES" in text and "the median" in text and "STAGE 3 OF 4" in text and RUN_DATE in text
    assert "BLIND PACK TEXT" not in text and "FILED OPERATING MARGIN HISTORY" not in text
    assert sorted(t["function"]["name"] for t in body["tools"]) == ["state_crux", "submit_forecast"]
    assert body["options"]["seed"] == 700
    # no session sees another stage's messages
    for b in script.bodies:
        assert len(b["messages"]) <= 3 and b["messages"][0]["role"] == "user"
    assert "STAGE 2 OF 4" not in text and "STAGE 4 OF 4" not in text


def test_keep_records_the_pre_value_and_no_pull(tmp_path, monkeypatch):
    _, fc, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()], cc=cons_op(0.45))
    assert rv["called"] and rv["decision"] == "keep" and not rv["no_call"] and rv["final_source"] == "stage2_median" and rv["post"] is None and rv["pull"] is None
    assert rv["pre"]["base_value"] == pytest.approx(fc["samples"][fc["median_index"]]["base_value"]) and rv["crux"]["valid"] is True
    assert rv["consensus"]["status"] == "ok" and rv["consensus"]["years"][1]["op"] == pytest.approx(0.45)
    assert rv["diagnostics"]["alt_paths"][0]["fact_id"] == "F1" and rv["diagnostics"]["consensus_divergence"][0]["gap_pts"] == pytest.approx((0.40 - 0.45) * 100)
    assert json.loads((tmp_path / "reveal.json").read_text("utf-8"))["final_forecast"] == rv["final_forecast"]


def revision(m1, ids=("F2",), reason="the ongoing contract was underweighted"):
    f = fcast(0.40)
    f["scenarios"]["Base"]["near_term"]["op_margin"] = [m1, 0.40]
    return call("submit_forecast", **f, revision_fact_ids=list(ids), revision_reason=reason)


def test_one_revision_is_valued_and_the_pull_ratio_is_recorded(tmp_path, monkeypatch):
    _, fc, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("revise"), revision(0.42), memo_step()], cc=cons_op(0.45))
    rev = rv["revision"]
    assert rev["submitted"] and rev["accepted"] and rev["fact_ids"] == ["F2"] and rv["final_source"] == "stage3_revision"
    assert rv["post"]["base_value"] != rv["pre"]["base_value"] and rv["post"]["forecast"]["scenarios"]["Base"]["near_term"]["op_margin"] == [0.42, 0.40]
    item = next(i for i in rv["pull"] if i["scenario"] == "Base" and i["item"] == "op_margin_y1")
    assert (item["pre"], item["post"], item["consensus"]) == (0.40, 0.42, pytest.approx(0.45)) and item["pull_ratio"] == pytest.approx(0.4)
    assert rf.pull_ratio(0.40, 0.42, 0.45) == item["pull_ratio"]
    assert not any(i["item"] == "op_margin_y2" and i["scenario"] == "Base" for i in rv["pull"])         # unchanged margins are not listed
    assert fi["verdict"]["r26"]["post_reveal_base"] == pytest.approx(rv["post"]["base_value"]) and fi["verdict"]["r26"]["pre_reveal_base"] == pytest.approx(rv["pre"]["base_value"])


def test_a_pull_is_null_when_consensus_is_not_comparable_or_equal_to_the_pre_value(tmp_path, monkeypatch):
    nc = {"status": "consensus_not_comparable", "reason": "fewer than 3 analysts"}
    _, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("revise"), revision(0.42), memo_step()], cc=nc)
    assert rv["consensus"]["status"] == "not_comparable" and rv["consensus"]["reason"] == "fewer than 3 analysts"
    assert all(i["pull_ratio"] is None and i["consensus"] is None for i in rv["pull"])


def test_a_second_submit_is_refused_once_and_the_stage_closes(tmp_path, monkeypatch):
    two = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "submit_forecast", "arguments": {**fcast(0.43), "revision_fact_ids": ["F1"], "revision_reason": "x"}}},
                                                              {"function": {"name": "submit_forecast", "arguments": {**fcast(0.44), "revision_fact_ids": ["F1"], "revision_reason": "y"}}}]}
    script, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("revise"), two, memo_step()])
    assert len(script.bodies) == 6 and rv["revision"]["second_call_refused"] and rv["ended"] == "closed"            # 3 + 2 stage-3 turns + stage 4: nothing after the refusal
    tool_msgs = [m["content"] for m in script.bodies[-1]["messages"] if m["role"] == "tool"]
    assert rv["revision"]["accepted"] is True


def test_a_revision_without_a_cited_fact_is_not_accepted(tmp_path, monkeypatch):
    _, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("revise"), revision(0.42, ids=()), memo_step()], cc=cons_op(0.45))
    assert rv["revision"]["submitted"] and not rv["revision"]["accepted"] and rv["final_source"] == "stage2_median" and rv["post"] is None and rv["pull"] is None
    assert any(p["field"] == "revision_fact_ids" for p in rv["revision"]["problems"])
    _, _, rv2, _ = run_stages(tmp_path / "b", monkeypatch, THREE + [crux_args("revise"), revision(0.42, ids=("F99",)), memo_step()])
    assert not rv2["revision"]["accepted"] and rv2["revision"]["problems"][0]["problem"] == "fact_id_not_in_dossier"


def test_no_call_when_the_samples_split_by_direction_and_no_model_call_is_made(tmp_path, monkeypatch):
    script, fc, rv, fi = run_stages(tmp_path, monkeypatch, [sub(fcast(0.46)), sub(fcast(0.30)), sub(fcast(0.40)), memo_step()])
    assert rv["no_call"] and rv["no_call_reasons"] == ["samples_split_by_direction"] and not rv["called"] and rv["directions"] == ["undervalued", "overvalued", "hold"]
    assert len(script.bodies) == 4                                                       # three stage-2 sessions and the memo: stage 3 called no model
    assert fi["no_call"] and fi["verdict"]["no_call"]["reasons"] == ["samples_split_by_direction"] and fi["verdict"]["verdict_label"] == "hold"
    assert fi["actionable"] is False and "no_call" in fi["non_actionable_reasons"]
    assert "No call" in script.bodies[-1]["messages"][0]["content"] and "Verdict: no_call" in script.bodies[-1]["messages"][0]["content"]
    assert fi["verifier"]["flags"] == []                                                 # the memo said NO CALL, as the table did


def test_no_call_when_the_crux_is_invalid_after_the_stage(tmp_path, monkeypatch):
    bad = crux_args("keep", citations=[{"source": f"page:{PAGE_URL}", "date": "2026-08-04", "quote": "An invented sentence that appears nowhere in that page at all."}])
    _, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [bad, memo_step()])
    assert rv["called"] and rv["no_call"] and rv["no_call_reasons"] == ["crux_invalid:quote_not_found"] and rv["crux"]["valid"] is False
    assert fi["no_call"] and fi["actionable"] is False and fi["verdict"]["verdict_label"] == "hold" and fi["verdict"]["r26"]["actionable"] is False


def test_a_malformed_crux_is_returned_once_then_stands_as_invalid(tmp_path, monkeypatch):
    short = crux_args("keep", citations=[{"source": f"page:{PAGE_URL}", "date": "2026-08-04", "quote": "too short"}])
    script, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [short, short, memo_step()])
    assert rv["crux"]["state"] == "form_failed" and rv["crux"]["valid"] is False and rv["no_call"] and rv["no_call_reasons"][0].startswith("crux_invalid:crux_form")
    assert "malformed" in [m["content"] for m in script.bodies[4]["messages"] if m["role"] == "tool"][0]


def test_no_crux_at_all_is_no_call(tmp_path, monkeypatch):
    _, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [{"role": "assistant", "content": "ok"}, {"role": "assistant", "content": "ok"}, memo_step()])
    assert rv["no_call"] and rv["no_call_reasons"] == ["crux_invalid:missing"] and rv["crux"]["state"] == "not_stated"


def test_no_valued_sample_is_no_call_and_stage_4_still_records_it(tmp_path, monkeypatch):
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, [sub(fcast())] * 3, bridge=dict(DFACTS, tax_rate=None))
    assert rv["no_call_reasons"] == ["no_valued_sample"] and fi["status"] == "no_forecast" and fi["actionable"] is False and len(script.bodies) == 3


# ---------------------------------------------------------------- stage 4

def test_every_numeric_contract_field_comes_from_code(tmp_path, monkeypatch):
    liar = {"base_iv": 1.0, "bull_iv": 2.0, "base_probability": 0.9, "kelly_fraction_pct": 77, "conviction_score": 14.0, "business_quality_moat": 5.0, "reentry_tranches": {"tranche_1_starter": 1, "tranche_2_core": 2},
            "near_term_earnings": 99.0, "verdict_label": "undervalued", "margin_persistence": "structural", "cycle_evidence": "text", "momentum_flip_condition": {"metric": "mom_6m", "comparator": ">", "threshold": 0.1, "window_days": 5}}
    _, fc, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step(contract=liar)], cc=cons_op(0.45))
    v = fi["verdict"]
    pub = r26.published_values(r26._value(rv["final_forecast"], valuation(), DBAR))
    assert (v["base_iv"], v["bull_iv"], v["bear_iv"]) == (pub["Base"], pub["Bull"], pub["Bear"]) and v["base_probability"] == 0.5 and v["bull_probability"] == 0.25
    assert v["verdict_label"] == "hold" and v["kelly_fraction_pct"] is not None and v["near_term_earnings"] != 99.0 and v["normalized_earnings"] is not None
    assert "conviction_score" not in v and "business_quality_moat" not in v and "reentry_tranches" not in v
    assert fi["contract_text"] == {"margin_persistence": "structural", "cycle_evidence": "text", "momentum_flip_condition": liar["momentum_flip_condition"]}
    r = v["r26"]
    assert v["pilot_arm"] == "r26" and v["desk_schema"] == "26" and v["pack_revision"] == 26 and r["contract_unfilled"] == ["conviction_score", "business_quality_moat", "reentry_tranches"]
    assert r["model_typed_numbers_in"] == ["momentum_flip_condition"] and r["actionable"] is True and fi["actionable"] is True and fi["flags"] == []
    # the report the harness parses: the memo plus a contract block whose numbers are the code's
    blk = json.loads(re.search(r"```json:underwriting\s*(\{.*?\})\s*```", fi["report"], re.S).group(1))
    assert blk["base_iv"] == pub["Base"] and blk["verdict_label"] == "hold" and "conviction_score" not in blk
    # contract_fill agrees with the table (the same desk call)
    filled, _ = contract_fill.fill(list(FETCH) + [fi["desk_call"]], {}, {}, PRICE, allow_blend=False, pack_text="BLIND PACK TEXT", company="Danaos Corporation")
    assert filled["base_iv"] == pub["Base"] and filled["crux_check"]["valid"] is True
    on_disk = json.loads((tmp_path / "final.json").read_text("utf-8"))
    assert on_disk["pilot_arm"] == "r26" and on_disk["desk_schema"] == "26" and on_disk["verdict"]["base_iv"] == pub["Base"]


def test_stage_4_is_a_fresh_session_with_no_tools_and_the_named_inputs(tmp_path, monkeypatch):
    script, _, _, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()], cc=cons_op(0.45))
    b = script.bodies[-1]
    text = b["messages"][0]["content"]
    assert len(b["messages"]) == 1 and "tools" not in b and "STAGE 4 OF 4" in text
    for part in ("RESEARCH DOSSIER", "FROZEN DESK TABLE", "CONVERSION TABLE", "Crux valid: True", "STAGE-2 SPREAD", "DIAGNOSTICS"):
        assert part in text, part
    assert "REASON-MARKER" not in text and "MARKET PRICE" not in text and "BASIS-CORRECTED CONSENSUS" not in text
    assert "Base value per share: $" in text and "Base operating margin year 1: " in text and "Base transition: linear" in text and "Base baseline: last" in text


def test_a_wrong_labelled_number_is_flagged_and_makes_the_result_non_actionable(tmp_path, monkeypatch):
    bump = lambda memo: re.sub(r"Base value per share: \$[\d,.]+", "Base value per share: $999.99", memo)
    _, _, _, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step(mutate=bump)])
    assert fi["verifier"]["flags"] == ["memo_number_mismatch"] and fi["actionable"] is False and "memo_number_mismatch" in fi["non_actionable_reasons"]
    assert fi["verifier"]["details"][0]["label"] == "Base value per share" and fi["verdict"]["base_iv"] != 999.99            # annotate, never change


def test_a_wrong_verdict_word_is_flagged(tmp_path, monkeypatch):
    _, _, _, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step(verdict="undervalued")])
    assert fi["verifier"]["flags"] == ["memo_verdict_mismatch"] and fi["actionable"] is False


def test_a_wrong_transition_or_baseline_label_is_flagged(tmp_path, monkeypatch):
    sw = lambda memo: memo.replace("Base transition: linear", "Base transition: step_at_year").replace("Base baseline: last", "Base baseline: median")
    _, _, _, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step(mutate=sw)])
    assert fi["verifier"]["flags"] == ["memo_forecast_mismatch"] and {d["label"] for d in fi["verifier"]["details"]} == {"Base transition", "Base baseline"}


def test_a_missing_contract_block_or_memo_is_stamped_and_not_actionable(tmp_path, monkeypatch):
    step = lambda body: {"role": "assistant", "content": "SECTION 0\nVerdict: hold\nSECTION 1\nnothing else"}
    _, _, _, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), step])
    assert "contract_block_missing" in fi["non_actionable_reasons"] and fi["actionable"] is False and fi["contract_text"] == {}
    _, _, _, fi2 = run_stages(tmp_path / "b", monkeypatch, THREE + [crux_args("keep"), lambda body: {"role": "assistant", "content": ""}])
    assert fi2["status"] == "memo_missing" and "memo_missing" in fi2["verifier"]["flags"] and fi2["actionable"] is False


# ---------------------------------------------------------------- the verifier on its own

ROWS = [{"label": "Verdict", "value": "hold", "kind": "word", "group": "V"}, {"label": "Base value per share", "value": 409.61, "kind": "usd", "group": "V"},
        {"label": "Price", "value": 400.0, "kind": "usd", "group": "V"}, {"label": "Base probability", "value": 0.5, "kind": "pct", "group": "V"},
        {"label": "Base operating margin year 1", "value": 0.1234, "kind": "pct", "group": "B"}, {"label": "Base transition", "value": "linear", "kind": "enum", "group": "B"},
        {"label": "Base baseline", "value": "median", "kind": "enum", "group": "B"}, {"label": "Base fade years", "value": 4, "kind": "int", "group": "B"}]


@pytest.mark.parametrize("memo,flags", [
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share: $409.61", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share of $409.6", []),                       # within rounding
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share is about $410", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share: $409.7", ["memo_number_mismatch"]),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share: $409.615", ["memo_number_mismatch"]),  # more precise than the table
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase operating margin year 1: 12.3%", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase operating margin year 1: 12%", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase operating margin year 1: 12.4%", ["memo_number_mismatch"]),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase probability: 50%", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase probability: 0.5", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase probability: 60%", ["memo_number_mismatch"]),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nThe price-implied growth of 3% and Price-implied value 5", []),    # a label word inside another phrase is no statement
    ("SECTION 0\nVerdict: hold\nSECTION 1\nPrice: $400 and the Base fade years: 4", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase fade years: 5", ["memo_number_mismatch"]),
    ("SECTION 0\nVerdict: overvalued\nSECTION 1\nx", ["memo_verdict_mismatch"]),
    ("SECTION 1\nno section zero", ["memo_verdict_mismatch"]),
    ("SECTION 0\nThe verdict is fairly valued.\nSECTION 1\nx", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase transition: linear; Base baseline: median", []),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase transition: hold_then_linear", ["memo_forecast_mismatch"]),
    ("SECTION 0\nVerdict: hold\nSECTION 1\nBase baseline is p75", ["memo_forecast_mismatch"]),
])
def test_the_verifier(memo, flags):
    assert late.verify_memo(memo, ROWS)["flags"] == flags


def test_the_verifier_annotates_and_reads_the_memo_only():
    rows, memo = copy.deepcopy(ROWS), "SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share: $1.00"
    r = late.verify_memo(memo, rows)
    assert rows == ROWS and r["details"] == [{"flag": "memo_number_mismatch", "label": "Base value per share", "memo": "$1.00", "table": "$409.61"}]


# ---------------------------------------------------------------- the pieces

def test_dossier_facts_sources_become_crux_sources():
    assert r26.translate_source("pack:primary-p1") == "PRIMARY P1" and r26.translate_source("pack:data-5") == "DATA 5" and r26.translate_source("pack:data-6a") == "DATA 6A"
    assert r26.translate_source("pack:guidance-consensus") == "GUIDANCE" and r26.translate_source("page:https://x.test/a") == "https://x.test/a"
    assert r26.translate_source("query:Q3") == "query:Q3" and r26.translate_source("pack:defaults") == "pack:defaults"


def test_bridge_facts_from_a_history_row_measure_nothing_it_cannot():
    row = {"pretax_income": 100e9, "tax_provision": 25e9, "interest_expense": 5e9, "amortization_intangibles": 4e9}
    f = r26.bridge_facts_from_row(row, ())
    assert (f["net_interest"], f["tax_rate"], f["amortization_0"]) == (5.0, 0.25, 4.0) and "net_interest_is_gross_interest_expense" in f["stamps"]
    g = r26.bridge_facts_from_row({"pretax_income": -5e9, "tax_provision": 1e9, "interest_expense": 5e9}, ("amortization_intangibles",))
    assert g["tax_rate"] is None and g["amortization_0"] == 0.0
    h = r26.bridge_facts_from_row({"pretax_income": 100e9, "tax_provision": 50e9}, ())
    assert h["tax_rate"] == 0.35 and h["net_interest"] is None and h["amortization_0"] is None


def test_the_consensus_adapter():
    cv = late.consensus_view(cons_op(0.45), DFACTS)
    assert cv["status"] == "ok" and cv["years"][1]["op"] == pytest.approx(0.45)
    assert late.consensus_view({"status": "ok", "x_margins": {"1": 0.1}, "op_margins": {"1": 0.2}}, DFACTS)["years"][1]["op"] == 0.2
    assert late.consensus_view({"consensus_not_comparable": "base-year ratio outside [0.5, 2]"}, DFACTS)["status"] == "not_comparable"
    assert late.consensus_view(None, DFACTS)["status"] == "unavailable"


def test_the_three_task_texts_name_no_company_number_and_state_the_rules():
    t2, t3, t4 = late.STAGE2_TASK, late.STAGE3_TASK, late.STAGE4_TASK
    assert "operating income divided by revenue" in t2 and "Code converts" in t2 and "percentage points" in t2 and "a whole number from 3 to 5" in t2
    assert "long_run_margin_op" in t2 and "fade_years" in t2 and "baseline plus a delta" in t2
    assert "audit of the market" in t3 and "at least one dossier fact" in t3 and "state_crux" in t3 and "only one revision" in t3.lower() or "one revision only" in t3
    assert "never restate a number" in t4 and "Code fills every number" in t4
    for t in (t2, t4):
        assert not re.search(r"\$\s?\d|\d+(\.\d+)?%", t)


def test_the_stage_inputs_are_the_spec_s_and_nothing_else():
    with pytest.raises(ValueError, match="may not be handed"):
        r26.fresh_messages("stage2", {"blind_pack": "", "price": 5})
    with pytest.raises(ValueError, match="may not be handed"):
        r26.fresh_messages("stage3", {"dossier": {}, "stage2_reasoning": "x"})
    with pytest.raises(ValueError, match="may not be handed"):
        r26.fresh_messages("stage4", {"dossier": {}, "consensus_corrected": "x"})
    assert r26.ALLOWED_INPUTS["stage3"] >= {"median_forecast", "consensus_corrected", "price_implied_inputs"} and "median_forecast" not in r26.ALLOWED_INPUTS["stage4"]


# ---------------------------------------------------------------- the four stages end to end on a fixture name

def test_the_four_stages_end_to_end(tmp_path, monkeypatch, stub_world):
    f1 = _fact(fact_id="F1", source="pack:primary-p1", quote="Operating revenues increased by $12.2 million.", value=12.2, unit="USD m", entity="XYZ", metric="operating revenues",
               period="Q2 2026", duration_years=4.7)
    f2 = _fact(fact_id="F2", source=f"page:{PAGE_URL}", quote=QUOTE, value=274.4, entity="Danaos Corporation", metric="operating revenues", duration_years="ongoing")
    steps = [call("fetch_page", url=PAGE_URL), call("register_facts", facts=[f1, f2], done=True, research_summary="Danaos charters ships."),
             *THREE, crux_args("revise"), revision(0.42), memo_step()]
    script = Script(*steps)
    monkeypatch.setattr(prov, "chat", script)
    facts = {"long_run": dict(LR), "owner_earnings_default_b": BASE_CF, "op_margin_bar": DBAR, "consensus_corrected": cons_op(0.45), "r26_bridge_facts": dict(DFACTS), "pilot_arm": "r26"}
    report, think, meta = r26.run_sample("m", PACK, tmp_path / "s1", facts=facts, price=PRICE, desk_context=_ctx(price=PRICE, desk_schema=None), seed=700, ticker="DAC",
                                         company="Danaos Corporation", verbose=False)
    d = tmp_path / "s1"
    for name in ("dossier.json", "forecasts.json", "reveal.json", "final.json", "_research_snapshot.json"):
        assert (d / name).exists(), name
    assert think == "" and "```json:underwriting" in report and report.startswith("SECTION 0")
    assert [b["options"]["seed"] for b in script.bodies[2:5]] == [700, 701, 702]
    assert meta["r26"]["stage1"]["usable"] == 2 and meta["r26"]["stage3"]["final_source"] == "stage3_revision" and meta["r26"]["stage4"]["actionable"] is True
    # the turn log: every model turn of every stage
    names = sorted(p.name for p in (d / "turns").glob("*.json") if p.name != "run_hashes.json") if (d / "turns").exists() else []
    snap = json.loads((d / "_research_snapshot.json").read_text("utf-8"))
    desk = [c for c in snap["calls"] if c.get("tool") == "run_financial_model"]
    fi = json.loads((d / "final.json").read_text("utf-8"))
    assert len(desk) == 1 and desk[0]["scenario_dcfs"][0]["dcf"]["per_share_iv"] == fi["verdict"]["base_iv"]
    # the harness can score the report: the contract block carries code's numbers
    import consensus_valuation as cv
    card = cv.extract_scorecard(report, PRICE)
    assert card["base_iv"] == fi["verdict"]["base_iv"] and card["verdict_label"] == "hold"
    info = cv.extract_desk_snapshot_metrics(snapshot=d, base_iv=card["base_iv"], scorecard=card, facts={})
    assert info["desk_calls"] == 1 and info["desk_iv_match"] is True
    assert fi["verdict"]["r26"]["final_source"] == "stage3_revision"


# ---------------------------------------------------------------- logging, stamps and arguments

def test_every_model_turn_is_logged_under_its_stage_label(tmp_path, monkeypatch):
    import turn_log
    seen = []
    script = Script(*(THREE + [crux_args("keep"), memo_step()]))

    def spy(body, timeout):
        seen.append(turn_log.active())
        return script(body, timeout)

    monkeypatch.setattr(prov, "chat", spy)
    val = valuation()
    kw = dict(run_dir=tmp_path, model="m", dossier=dossier(), valuation=val, op_margin_bar=DBAR, verbose=False)
    fc = r26.run_stage2(blind_pack="B", seed=1, **kw)
    rv = r26.run_stage3(blind_pack="B", fetch_calls=FETCH, company="Danaos Corporation", ticker="DAC", facts={}, forecasts=fc, **kw)
    r26.run_stage4(facts={}, blind_pack="B", fetch_calls=FETCH, company="Danaos Corporation", ticker="DAC", forecasts=fc, reveal=rv, **kw)
    assert [a[1] for a in seen] == ["stage2_k1", "stage2_k2", "stage2_k3", "stage3", "stage4"] and all(a[0] == tmp_path / "turns" for a in seen)


def test_tool_arguments_given_as_a_json_string_are_read(tmp_path, monkeypatch):
    as_str = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "submit_forecast", "arguments": json.dumps(fcast())}}]}
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [as_str, sub(fcast()), sub(fcast())], stages=(2,))
    assert fc["samples"][0]["status"] == "valued"


def test_fewer_valued_samples_than_k_is_stamped(tmp_path, monkeypatch):
    bad = fcast()
    del bad["scenarios"]["Bull"]
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [sub(bad), sub(bad), sub(fcast()), sub(fcast())], stages=(2,))
    assert fc["stamps"] == ["samples_valued:2_of_3"] and fc["median_index"] == 1 and "elapsed_s" in fc


def test_a_missing_code_owned_input_is_named():
    with pytest.raises(r26.R26InputError, match="owner_earnings_default_b"):
        r26.valuation_inputs({"long_run": dict(LR)}, 10.0, {})
    with pytest.raises(r26.R26InputError, match="long_run.rev_L"):
        r26.valuation_inputs({"owner_earnings_default_b": 1.0, "long_run": {}}, 10.0, {})
    v = r26.valuation_inputs({"owner_earnings_default_b": 1.0, "long_run": dict(LR), "r26_bridge_facts": {"family": "financial"}}, 10.0, {"run_date": "2026-01-01"})
    assert v["rev0"] == LR["rev_L"] and v["bridge_facts"] == {"family": "financial"} and v["run_date"] == "2026-01-01"


def test_a_pack_without_the_operating_margin_bar_fails_the_sample_by_name(tmp_path, monkeypatch, stub_world):
    monkeypatch.setattr(prov, "chat", Script(call("register_facts", facts=[], done=True, research_summary="s")))
    with pytest.raises(r26.R26InputError, match="op_margin_bar"):
        r26.run_sample("m", PACK, tmp_path, facts={"long_run": dict(LR), "owner_earnings_default_b": BASE_CF}, price=PRICE, desk_context={}, seed=1, verbose=False)

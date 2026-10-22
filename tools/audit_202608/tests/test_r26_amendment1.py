"""SPEC revision 26, section 9 (Amendment 1), parts B and C: the reachability of the crux shown up front (B1), validated singly and jointly along the ray with the outcome codes
reachable / jointly_reachable / beyond_reach (B2), the syntax-only repair turn that does not use the one correction (B3), and the per-name actionability rule on the three blind
samples (C). A scripted stub model; no GPU, no Ollama, no network."""
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(AUDIT_DIR.parent), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import financial_model_tool as fmt  # noqa: E402
import r26_late as late  # noqa: E402
import r26_stages as r26  # noqa: E402
from test_r26_forecast import DBAR  # noqa: E402
from test_r26_stage1 import call  # noqa: E402
from test_r26_stages24 import THREE, crux_args, fcast, memo_step, run_stages, sub, valuation  # noqa: E402

# The fixture Base is worth 409.61. Alone, long_run_margin reaches at most 1068.31 and terminal_ronic at most 486.55 (coe, terminal_g: not available on this path; fade at most 423.60).
P_JOINT = 1103.0       # long_run_margin alone closes 95% of the way to this price; with terminal_ronic together the price is reached
P_BEYOND = 3000.0      # not reached by any named input, alone or together


def entry(inp, fid="F4"):
    return {"input": inp, "reason": f"the filings support {inp}", "citations": [{"fact_id": fid}]}


def crux2(*entries, decision="keep"):
    return call("state_crux", crux=list(entries), decision=decision)


def pi_of(price, names=None):
    val = valuation(price)
    if names:
        val["desk_context"] = dict(val["desk_context"], pi_joint=names)
    return r26._value(fcast(0.40), val, DBAR)["desk"]["price_implied"]


# ---------------------------------------------------------------- B2: the solver, the ray

def test_joint_ray_reaches_a_price_that_one_input_closes_95_percent_of_the_way_to():
    pi = pi_of(P_JOINT, ["long_run_margin", "terminal_ronic"])
    base = 409.6050219453864
    assert not pi["long_run_margin"]["reachable"] and not pi["terminal_ronic"]["reachable"]
    closed = (pi["long_run_margin"]["bound"]["value_high"] - base) / (P_JOINT - base)
    assert closed == pytest.approx(0.95, abs=0.005)                          # TASK-like: one input alone gets 95% of the way
    j = pi["joint"]
    assert j["computable"] and j["reachable"] and 0.0 < j["t"] < 1.0 and j["excluded"] == {}
    assert j["value_at_t"] == pytest.approx(P_JOINT, abs=0.01) and j["value_at_1"] > P_JOINT
    # the values at t are on the ray from the analyst's values toward the price-favourable bounds, one shared fraction
    lrm0, lrm_fav = pi["long_run_margin"]["own"], j["favourable"]["long_run_margin"]["input"]
    assert j["values"]["long_run_margin"] == pytest.approx(lrm0 + j["t"] * (lrm_fav - lrm0))
    u0, u_fav = 0.1 / pi["terminal_ronic"]["own"], 0.0                       # the ronic ray runs in its charge wacc / RONIC, to "unlimited"
    assert j["favourable"]["terminal_ronic"]["input"] == "unlimited" and j["values"]["terminal_ronic"] == pytest.approx(0.1 / (u0 + j["t"] * (u_fav - u0)))


def test_joint_ray_t_is_the_smallest_fraction_that_reaches_the_price():
    j = pi_of(P_JOINT, ["long_run_margin", "terminal_ronic"])["joint"]
    just_before = pi_of(P_JOINT, ["long_run_margin", "terminal_ronic"])["joint"]                    # deterministic
    assert just_before["t"] == j["t"]
    # a price the Base already is at is reached at t = 0
    z = pi_of(409.6050219453864, ["long_run_margin", "terminal_ronic"])["joint"]
    assert z["reachable"] and z["t"] == pytest.approx(0.0, abs=1e-6)


def test_joint_ray_beyond_every_input_is_not_reached_and_says_which_side():
    j = pi_of(P_BEYOND, ["long_run_margin", "terminal_ronic", "fade_years"])["joint"]
    assert j["computable"] and not j["reachable"] and j["t"] is None and j["values"] is None and j["side"] == "above" and j["value_at_1"] < P_BEYOND


def test_joint_ray_leaves_out_an_input_the_path_cannot_move_and_says_so():
    j = pi_of(500.0, ["terminal_ronic", "coe"])["joint"]
    assert j["used"] == ["terminal_ronic"] and "rf_eff" in j["excluded"]["coe"] and not j["reachable"]
    none = pi_of(500.0, ["coe", "terminal_g"])["joint"]
    assert none["computable"] is False and none["used"] == []


def test_other_arms_are_untouched_the_joint_block_exists_only_when_asked():
    assert "joint" not in pi_of(P_JOINT)
    a, b = pi_of(P_JOINT), pi_of(P_JOINT, ["long_run_margin"])
    assert {k: v for k, v in b.items() if k != "joint"} == a                  # asking changes nothing else in the block
    blk = a["long_run_margin"]
    assert fmt.pi_favourable_end(blk, 409.6, P_JOINT) == {"end": "high", "input": 1.0, "value": blk["bound"]["value_high"]}
    assert fmt.pi_favourable_end(blk, 409.6, 100.0) == {"end": "low", "input": 0.0, "value": blk["bound"]["value_low"]}
    assert fmt.pi_favourable_end(a["coe"], 409.6, 100.0) is None


# ---------------------------------------------------------------- B1: shown up front

def test_stage_3_shows_each_offered_input_reach_and_value_at_its_favourable_bound_before_the_model_answers(tmp_path, monkeypatch):
    script, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux2(entry("long_run_margin"), entry("terminal_ronic")), memo_step()], price=P_JOINT)
    text = script.bodies[3]["messages"][1]["content"]
    assert "REACH OF EACH OFFERED INPUT ALONE" in text
    lrm = next(ln for ln in text.split("\n") if ln.strip().startswith("long_run_margin: the price"))
    assert "cannot be reached by this input alone" in lrm and "favourable bound (100.00%)" in lrm and "$1068.31" in lrm and "$1103.00" in lrm
    assert "coe: not available" in text and "fade_years: the price cannot be reached" in text
    assert "Beside each offered input the reveal shows, before you answer" in text and "jointly reachable" in text and "beyond the reach of every input you named" in text
    assert rv["crux"]["reach"]["single"][0]["favourable"]["value"] == pytest.approx(1068.3130833926289)


def test_a_reachable_price_shows_reachable_for_that_input():
    lines = late.reachability_lines(pi_of(P_JOINT - 400), 409.6, P_JOINT - 400)
    assert next(x for x in lines if x.startswith("long_run_margin")).startswith("long_run_margin: the price can be reached by this input alone.")


# ---------------------------------------------------------------- B2: validation and the outcome codes

def test_a_crux_whose_inputs_each_reach_is_reachable_and_runs_no_joint_test(tmp_path, monkeypatch):
    _, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()], price=P_JOINT - 400)
    c = rv["crux"]
    assert c["valid"] and c["reach_outcome"] == "reachable" and c["reach"]["joint"] is None and "beyond_reach" not in rv and rv["no_call_reasons"] == []
    assert "beyond_reach_review_required" not in fi["non_actionable_reasons"]


def test_one_unreachable_input_is_jointly_reachable_with_the_second_and_the_crux_is_valid(tmp_path, monkeypatch):
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux2(entry("long_run_margin"), entry("terminal_ronic")), memo_step()], price=P_JOINT)
    c = rv["crux"]
    assert c["valid"] and c["reach_outcome"] == "jointly_reachable" and not rv["no_call"] and "first" not in c and len(script.bodies) == 3 + 1 + 1       # no correction turn
    j = c["reach"]["joint"]
    assert j["reachable"] and 0 < j["t"] < 1 and set(j["values"]) == {"long_run_margin", "terminal_ronic"} and j["value_at_t"] == pytest.approx(P_JOINT, abs=0.01)
    assert [s["reachable"] for s in c["reach"]["single"]] == [False, False] and all(e["valid"] and e["reason"] is None for e in c["check"]["entries"])
    assert not rv.get("beyond_reach") and "price_beyond_every_input_reach" not in fi["flags"] and "beyond_reach_review_required" not in fi["non_actionable_reasons"]
    assert "moved together toward their price-favourable bounds they do" in script.bodies[-1]["messages"][1]["content"]


def test_beyond_reach_is_valid_when_every_quote_verifies_and_is_published_non_actionable(tmp_path, monkeypatch):
    _, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux2(entry("long_run_margin"), entry("terminal_ronic")), memo_step()], price=P_BEYOND)
    c = rv["crux"]
    assert c["valid"] and c["reach_outcome"] == "beyond_reach" and c["reach"]["joint"]["reachable"] is False
    assert not rv["no_call"] and rv["no_call_reasons"] == [] and rv["beyond_reach"] and rv["flags"] == ["price_beyond_every_input_reach"]
    assert all(e["valid"] for e in c["check"]["entries"]) and c["check"]["valid"]
    assert not fi["no_call"] and fi["verdict"]["verdict_label"] == "overvalued"                              # the verdict is published, directional
    assert "price_beyond_every_input_reach" in fi["flags"] and "beyond_reach_review_required" in fi["non_actionable_reasons"] and fi["actionable"] is False
    assert fi["verdict"]["r26"]["actionable"] is False and "beyond_reach_review_required" in fi["verdict"]["r26"]["non_actionable_reasons"]


def test_a_single_entry_crux_that_cannot_reach_is_beyond_reach_not_invalid(tmp_path, monkeypatch):
    _, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()], price=P_BEYOND)
    assert rv["crux"]["valid"] and rv["crux"]["reach_outcome"] == "beyond_reach" and fi["actionable"] is False


def test_beyond_reach_with_an_unverified_quote_is_an_invalid_crux_and_gets_the_one_correction(tmp_path, monkeypatch):
    bad = crux2(entry("long_run_margin", "F5"), entry("terminal_ronic"))
    good = crux2(entry("long_run_margin"), entry("terminal_ronic"))
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [bad, good, memo_step()], price=P_BEYOND)
    c = rv["crux"]
    assert c["state"] == "corrected" and c["correction_used"] and c["valid"] and c["first"]["valid"] is False and c["first"]["check"]["reason"] == "quote_not_found"
    assert c["first"]["reach_outcome"] == "beyond_reach" and c["first"]["check"]["entries"][0]["reason"] == "quote_not_found"           # the quote failure, not not_reachable
    assert c["reach_outcome"] == "beyond_reach" and rv["beyond_reach"] and "beyond_reach_review_required" in fi["non_actionable_reasons"]
    assert len(script.bodies) == 3 + 2 + 1


def test_the_entry_quote_failure_in_a_jointly_reachable_crux_is_still_no_call_after_the_one_correction(tmp_path, monkeypatch):
    bad = crux2(entry("long_run_margin"), entry("terminal_ronic", "F5"))
    _, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [bad, bad, memo_step()], price=P_JOINT)
    assert rv["no_call"] and rv["no_call_reasons"] == ["crux_invalid:quote_not_found"] and rv["crux"]["reach_outcome"] == "jointly_reachable" and not rv.get("beyond_reach")


# ---------------------------------------------------------------- B3: the syntax-only repair

def test_a_form_failure_gets_one_syntax_repair_that_does_not_use_the_content_correction(tmp_path, monkeypatch):
    malformed = crux_args("keep", input="bogus_input")
    bad_content = crux_args("keep", citations=[{"fact_id": "F5"}])
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [malformed, bad_content, crux_args("keep"), memo_step()])
    c = rv["crux"]
    assert c["form_repair_used"] and c["correction_used"] and c["state"] == "corrected" and c["valid"] and not rv["no_call"]            # both were available and both ran
    assert len(script.bodies) == 3 + 3 + 1
    repair = [m["content"] for m in script.bodies[4]["messages"] if m["role"] == "tool"][-1]
    assert "syntax-only repair" in repair and "does not use your one correction" in repair


def test_a_malformed_corrected_crux_gets_one_syntax_repair_and_then_stands(tmp_path, monkeypatch):
    bad_content = crux_args("keep", citations=[{"fact_id": "F5"}])
    malformed = crux_args("keep", input="bogus_input")
    script, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [bad_content, malformed, crux_args("keep"), memo_step()])
    c = rv["crux"]
    assert c["valid"] and c["state"] == "corrected" and c["correction_form_repair_used"] and len(script.bodies) == 3 + 1 + 2 + 1
    assert "syntax-only repair" in [m["content"] for m in script.bodies[5]["messages"] if m["role"] == "tool"][-1]


def test_never_more_than_one_of_each(tmp_path, monkeypatch):
    bad_content = crux_args("keep", citations=[{"fact_id": "F5"}])
    malformed = crux_args("keep", input="bogus_input")
    # first session: two malformed calls stand as invalid; no correction turn follows (the crux never became content to correct)
    s1, _, rv1, _ = run_stages(tmp_path / "a", monkeypatch, THREE + [malformed, malformed, memo_step()])
    assert rv1["no_call"] and rv1["crux"]["state"] == "form_failed" and len(s1.bodies) == 3 + 2 + 1
    # correction session: one malformed corrected crux is repaired once; a second malformed stands as invalid and there is no further turn
    s2, _, rv2, _ = run_stages(tmp_path / "b", monkeypatch, THREE + [bad_content, malformed, malformed, memo_step()])
    assert rv2["no_call"] and rv2["no_call_reasons"][0].startswith("crux_invalid:crux_form") and len(s2.bodies) == 3 + 1 + 2 + 1


# ---------------------------------------------------------------- C: per-name actionability

def test_samples_agreeing_in_direction_within_20_percent_add_no_reason():
    assert r26.samples_actionability_reasons({"base_values": [400.0, 410.0, 390.0], "spread": 0.0488}, 400.0) == []
    assert r26.samples_actionability_reasons({"base_values": [400.0, 410.0, 390.0], "spread": 0.20}, 400.0) == []           # at 20% is allowed


def test_spread_above_20_percent_and_a_direction_split_are_reasons():
    assert r26.samples_actionability_reasons({"base_values": [400.0, 410.0, 390.0], "spread": 0.2001}, 400.0) == ["samples_spread_above_20pct"]
    assert r26.samples_actionability_reasons({"base_values": [300.0, 400.0, 500.0], "spread": 0.5}, 400.0) == ["samples_direction_split", "samples_spread_above_20pct"]
    assert r26.samples_actionability_reasons({"base_values": [400.0, 410.0, 390.0], "spread": None}, 400.0) == ["samples_spread_undefined"]
    # one over and one hold is not a split under the band rule
    assert "samples_direction_split" not in r26.samples_actionability_reasons({"base_values": [300.0, 400.0, 405.0], "spread": 0.3}, 400.0)


def test_a_wide_spread_makes_the_name_non_actionable_with_its_reason_and_keeps_every_other_condition(tmp_path, monkeypatch):
    wide = [sub(fcast(0.40)), sub(fcast(0.41)), sub(fcast(0.25))]
    _, fc, rv, fi = run_stages(tmp_path, monkeypatch, wide + [crux_args("keep"), memo_step()])
    assert fc["spread"] > 0.20 and not fi["no_call"]
    assert "samples_spread_above_20pct" in fi["non_actionable_reasons"] and fi["actionable"] is False and fi["verdict"]["r26"]["actionable"] is False
    _, fc2, _, fi2 = run_stages(tmp_path / "n", monkeypatch, THREE + [crux_args("keep"), memo_step()])
    assert fc2["spread"] <= 0.20 and not any(r.startswith("samples_") for r in fi2["non_actionable_reasons"])


# ---------------------------------------------------------------- the joint search assumes no monotonicity

def test_joint_search_scans_a_grid_and_records_the_range_seen_for_a_true_beyond_reach():
    j = pi_of(P_JOINT, ["long_run_margin", "terminal_ronic", "fade_years"])["joint"]
    assert not j["reachable"] and j["grid_points"] == 121 and j["min_value_seen"] == pytest.approx(409.6050219453864) and j["max_value_seen"] == pytest.approx(j["value_at_1"]) and j["max_value_seen"] < P_JOINT


def test_joint_search_finds_a_crossing_in_the_middle_of_a_non_monotone_ray():
    blocks = {"long_run_margin": {"bound": {"low": 0.0, "high": 1.0, "value_low": 50.0, "value_high": 400.0}}}
    raw = lambda lrm=None, **kw: 100.0 + 400.0 * lrm * (1.0 - lrm) * 4.0 / 4.0 * 1.0 - 100.0 * lrm if lrm is not None else 100.0   # rises then falls back below the price
    j = fmt._joint_ray(raw, blocks, ["long_run_margin"], 150.0, 100.0, 0.1, 0.03, 4, 0.15, 0.0)
    assert j["reachable"] and 0.0 < j["t"] < 0.5 and j["value_at_1"] < 150.0 and j["value_at_t"] == pytest.approx(150.0, abs=0.01)
    assert j["max_value_seen"] > 150.0

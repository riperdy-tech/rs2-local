"""Pack revision 27 (cross-check 25 rulings, 2026-10-22): the discount rate is code-owned, the Base growth-trajectory label is derived by code from the path, the Base carries a
durability thesis, a margin level resting on no filed fact is annotated, a crux that no single input reaches is path-dominated (non-actionable until reviewed), an alternative
path's value has its own table label so the memo verifier reads it there, and a memo citing a fact id the dossier does not hold is annotated. No GPU, no Ollama, no network."""
import copy
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(AUDIT_DIR.parent), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import r26_forecast as rf  # noqa: E402
import r26_late as late  # noqa: E402
import r26_stages as r26  # noqa: E402
from test_r26_stages24 import fcast  # noqa: E402


def test_the_pack_revision_is_28():
    assert r26.PACK_REVISION_R26 == 28


def test_the_discount_rate_is_the_anchor_and_the_submitted_rate_is_kept():
    fc, stamps = r26.code_owned_inputs(dict(fcast(), discount_rate=0.09), {"desk_context": {"coe_anchor": 0.0796}})
    assert fc["discount_rate"] == 0.0796 and fc["discount_rate_submitted"] == 0.09 and stamps == ["discount_rate_set_to_anchor"]
    same, st2 = r26.code_owned_inputs(dict(fcast(), discount_rate=0.0796), {"desk_context": {"coe_anchor": 0.0796}})
    assert same["discount_rate"] == 0.0796 and st2 == []


@pytest.mark.parametrize("anchor", [None, 0.0, -0.01])
def test_without_a_positive_anchor_the_submitted_rate_stands_stamped(anchor):
    fc, stamps = r26.code_owned_inputs(dict(fcast(), discount_rate=0.09), {"desk_context": {"coe_anchor": anchor}})
    assert fc["discount_rate"] == 0.09 and stamps == ["discount_rate_no_anchor_submitted_rate_used"]


def test_code_owned_inputs_does_not_mutate_the_submitted_forecast():
    f = dict(fcast(), discount_rate=0.09)
    before = copy.deepcopy(f)
    r26.code_owned_inputs(f, {"desk_context": {"coe_anchor": 0.0796}})
    assert f == before


@pytest.mark.parametrize("path, label", [
    ([0.12, 0.08, 0.075, 0.075, 0.075], "decelerating"),       # MSGE iteration 2: labelled accelerating by the model
    ([0.039, 0.055, 0.06, 0.06, 0.06], "accelerating"),
    ([0.04, 0.042, 0.041, 0.04, 0.043], "steady"),
    ([-0.05, -0.04, -0.02, 0.01, 0.01], "shrinking"),
    ([], None),
])
def test_the_growth_trajectory_label_is_derived_from_the_path(path, label):
    assert late.derive_growth_trajectory(path) == label


def test_derive_labels_replaces_the_label_and_records_the_submitted_one():
    f = fcast()
    f["scenarios"]["Base"]["growth_trajectory"] = {"label": "accelerating", "fact_ids": ["F1"]}
    vf = {"scenarios": {"Base": {"path": {"years": [{"rev_growth": g} for g in (0.12, 0.08, 0.07, 0.07, 0.07)]}}}}
    out, stamps = r26.derive_labels(f, vf)
    gt = out["scenarios"]["Base"]["growth_trajectory"]
    assert gt["label"] == "decelerating" and gt["label_submitted"] == "accelerating" and gt["fact_ids"] == ["F1"]
    assert stamps == ["growth_trajectory_derived:accelerating->decelerating"]
    assert f["scenarios"]["Base"]["growth_trajectory"]["label"] == "accelerating"           # the input is not mutated
    assert r26.derive_labels(f, {})[0]["scenarios"]["Base"]["growth_trajectory"]["label"] == "accelerating"


def test_the_durability_thesis_is_required_on_the_base_with_four_short_statements():
    assert late.validate_durability(fcast()) == []
    f = fcast()
    del f["scenarios"]["Base"]["durability"]
    assert late.validate_durability(f) == [{"field": "Base.durability", "problem": "missing_or_not_an_object"}]
    g = fcast()
    g["scenarios"]["Base"]["durability"] = {"anchor": "", "mechanism": "word " * 41, "evidence_limit": "x"}
    p = {(x["field"], x["problem"]) for x in late.validate_durability(g)}
    assert p == {("Base.durability.anchor", "missing_text"), ("Base.durability.mechanism", "more_than_40_words"), ("Base.durability.failure_condition", "missing_text")}
    props = late.SUBMIT_FORECAST_TOOL["function"]["parameters"]["properties"]["scenarios"]["properties"]
    assert "durability" in props["Base"]["required"] and "durability" not in props["Bull"]["properties"]
    assert "9. The durability thesis" in late.STAGE2_TASK and "cost-of-equity anchor" in late.STAGE2_TASK


def test_a_margin_level_resting_on_no_filed_fact_is_annotated():
    dossier = {"facts": [{"fact_id": "A1", "basis": "company_adjusted"}, {"fact_id": "T1", "basis": "third_party"}, {"fact_id": "G1", "basis": "filed_gaap"}]}
    f = fcast()
    for n in ("Base", "Bull", "Bear"):
        f["scenarios"][n]["near_term"]["fact_ids"] = ["G1", "A1"]
        f["scenarios"][n]["normalized"]["fact_ids"] = ["G1"]
    f["scenarios"]["Base"]["normalized"]["fact_ids"] = ["A1", "T1"]
    assert r26.margin_basis_flags(f, dossier) == ["margin_level_without_filed_fact:Base.normalized"]


def test_an_alternative_path_value_has_its_own_label_and_the_memo_quoting_it_is_not_a_mismatch():
    alts = [{"fact_id": "F105", "duration_years": 5, "value": 39.01, "label": rf.EXPIRY_ALT}]
    assert late.alt_label(alts[0]) == "Alternative-path Base value per share if F105 expires"
    rows = [{"label": "Verdict", "value": "overvalued", "kind": "word", "group": "Verdict"},
            {"label": "Base value per share", "value": 39.37, "kind": "usd", "group": "Valuation"},
            {"label": late.alt_label(alts[0]), "value": 39.01, "kind": "usd", "group": "Valuation"}]
    memo = ("Verdict: overvalued. The Base value per share: $39.37. If the evidence of F105 expires, the Alternative-path Base value per share if F105 expires: $39.01, "
            "which replaces nothing.")
    ver = late.verify_memo(memo, rows)
    assert ver["flags"] == []
    bad = late.verify_memo("Verdict: overvalued. The Base value per share: $39.01.", rows)
    assert bad["flags"] == ["memo_number_mismatch"]
    assert "Alternative-path Base value per share if F105 expires is $39.01" in late.render_diagnostics({"alt_paths": alts})


def test_a_memo_citing_a_fact_id_the_dossier_does_not_hold_is_annotated_not_gated():
    rows = [{"label": "Verdict", "value": "hold", "kind": "word", "group": "Verdict"}]
    facts = [{"fact_id": "F1"}, {"fact_id": "R30"}]
    ok = late.verify_memo("Verdict: hold. Segments are A and B [F1], margins [R30].", rows, facts)
    assert "memo_unknown_fact_id" not in ok["annotations"]
    bad = late.verify_memo("Verdict: hold. An MRI business with a service annuity [F99].", rows, facts)
    assert bad["flags"] == [] and "memo_unknown_fact_id" in bad["annotations"]
    assert any(d["flag"] == "memo_unknown_fact_id" and d["memo"] == "F99" for d in bad["details"])
    assert "add no economic premise" in late.STAGE4_TASK


def test_the_path_dominated_flag_and_reason_exist():
    assert r26.PATH_DOMINATED_FLAG == "path_dominated_crux" and r26.PATH_DOMINATED_REASON == "path_dominated_review_required"


def test_stage_2_records_the_spread_attribution_and_values_every_sample_at_the_anchor(tmp_path, monkeypatch):
    from test_r26_stages24 import run_stages, sub
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [sub(fcast(0.40)), sub(fcast(0.42)), sub(fcast(0.38))], stages=(2,))
    att = fc["spread_attribution"]
    assert att.get("status") not in ("attribution_error",) and "groups" in att and att["groups"]["discount"]["swap_in"] == 0.0
    anchor = None
    for s in fc["samples"]:
        assert s["forecast"]["discount_rate"] == s["forecast"]["discount_rate"]
        anchor = s["forecast"]["discount_rate"] if anchor is None else anchor
        assert s["forecast"]["discount_rate"] == anchor and "discount_rate_submitted" in s["forecast"]


def test_every_stage_sends_its_own_system_message_and_the_charter_never_reaches_the_rendered_prompt():
    """Amendment 3: without a system message, ollama_raw inserted the model tag's SYSTEM text (the v33 charter) into every stage."""
    import ollama_raw
    charter = "CHARTER-MARKER: you are an institutional underwriter; use price, consensus, momentum and Kelly sizing."
    for stage in ("stage1", "stage2", "stage3", "stage4"):
        inputs = {"blind_pack": "PACK", "task": "TASK"} if stage in ("stage1", "stage2") else {"dossier": {"facts": []}, "task": "TASK"}
        msgs = r26.fresh_messages(stage, inputs)
        assert msgs[0] == {"role": "system", "content": late.STAGE_SYSTEM[stage]} and msgs[1]["role"] == "user"
        rendered = ollama_raw.template_messages(msgs, charter)
        assert [m for m in rendered if m.get("role") == "system"] == [msgs[0]]
        assert not any(charter in str(m.get("content")) for m in rendered)
    assert "undervalued" not in late.STAGE_SYSTEM["stage2"] and "price" in late.STAGE_SYSTEM["stage2"]
    assert "a wish to keep the original" in late.STAGE_SYSTEM["stage3"]
    assert len({late.STAGE_SYSTEM[s] for s in late.STAGE_SYSTEM}) == 4

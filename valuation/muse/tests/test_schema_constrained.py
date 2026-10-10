"""Addendum AD (R4 and the run-1 taxonomy): the JSON schemas of the Muse calls, the D-part citations, and the prompt/checker contract.

The real-fixture tests use one saved answer of gate-2 run 1 (`data/run1_p1_027904.json`, a behaviour fixture of the sealed engineering pilot; no outcome): the
model nested bull_case/bear_case inside "inputs" and lost one closing brace, and cited the parts D1/D2/D4 of section D, which the old checker refused.
"""
import json
from pathlib import Path

import pytest

from valuation.muse import checkers as ck, jsonschemas as js, prompting
from valuation.muse.runner import MuseRunner
from valuation.muse.schema import muse_inputs

FIXTURE = json.loads((Path(__file__).parent / "data" / "run1_p1_027904.json").read_text(encoding="utf-8"))
P1_INPUTS = ["g1", "growth_persistence"]


# ---- a minimal validator for the JSON-schema subset jsonschemas.py uses (no third-party package is installed) ----------------------------------

def errors(inst, sch, path="$"):
    if "anyOf" in sch:
        return [] if any(not errors(inst, s, path) for s in sch["anyOf"]) else [f"{path}: no anyOf branch matches"]
    t = sch.get("type")
    kinds = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "null": type(None)}
    if t is not None:
        if isinstance(inst, bool) and t in ("integer", "number") or not isinstance(inst, kinds[t]):
            return [f"{path}: not {t}"]
    out = []
    if "enum" in sch and inst not in sch["enum"]:
        out.append(f"{path}: {inst!r} not in enum")
    if t == "string":
        if len(inst) < sch.get("minLength", 0) or len(inst) > sch.get("maxLength", 10 ** 9):
            out.append(f"{path}: length {len(inst)}")
    if t in ("integer", "number"):
        if inst < sch.get("minimum", -1e300) or inst > sch.get("maximum", 1e300):
            out.append(f"{path}: {inst} out of range")
    if t == "array":
        if len(inst) < sch.get("minItems", 0) or len(inst) > sch.get("maxItems", 10 ** 9):
            out.append(f"{path}: {len(inst)} items")
        for k, v in enumerate(inst):
            out += errors(v, sch["items"], f"{path}[{k}]")
    if t == "object":
        props = sch.get("properties", {})
        for r in sch.get("required", []):
            if r not in inst:
                out.append(f"{path}: missing {r}")
        for k, v in inst.items():
            if k in props:
                out += errors(v, props[k], f"{path}.{k}")
            elif sch.get("additionalProperties") is False:
                out.append(f"{path}: unexpected {k}")
    return out


def reshaped_answer():
    """The run-1 answer as the schema forces it: the brace restored and bull_case/bear_case moved to the top level (content unchanged)."""
    nested = json.loads(FIXTURE["raw_content"] + "}")["inputs"]
    out = {"inputs": {k: nested[k] for k in P1_INPUTS}}
    out.update({k: nested[k] for k in ("bull_case", "bear_case")})
    return out


def evidence():
    return ck.Evidence(FIXTURE["sections"])


# ---- the run-1 failure, reproduced ---------------------------------------------------------------------------------------------------------------

def test_the_raw_run1_answer_is_invalid_json_and_its_nested_shape_breaks_the_schema():
    obj, err = ck.parse_json(FIXTURE["raw_content"])
    assert obj is None and err is not None                                           # one closing brace short
    nested = json.loads(FIXTURE["raw_content"] + "}")
    sch = js.pass1_schema("P1", P1_INPUTS, "operating", js.citation_labels(FIXTURE["sections"]))
    errs = errors(nested, sch)
    assert any("unexpected bull_case" in e for e in errs) and any("missing bull_case" in e for e in errs)


def test_the_reshaped_real_answer_passes_the_schema_and_the_new_checker_with_its_d_part_citations():
    ans = reshaped_answer()
    labels = js.citation_labels(FIXTURE["sections"])
    assert labels == ["F", "Q", "D", "S", "D1", "D2", "D3", "D4"]
    assert errors(ans, js.pass1_schema("P1", P1_INPUTS, "operating", labels)) == []
    cited = {c["section"] for e in ans["inputs"].values() for c in e["citations"]}
    assert {"D1", "D2", "D4"} <= cited                                                # what the old checker refused
    assert ck.check_pass1("P1", ans, "operating", P1_INPUTS, evidence()) == []


def test_a_d_part_quote_must_be_found_in_that_part_and_r_is_never_a_section():
    ev = evidence()
    ans = reshaped_answer()
    c = next(c for e in ans["inputs"].values() for c in e["citations"] if c["section"] == "D4")
    assert ck.check_citation(c, ev, "t") is None
    assert ck.check_citation(dict(c, section="D"), ev, "t") is None                  # plain D searches all of section D
    wrong = ck.check_citation(dict(c, section="D3"), ev, "t")
    assert wrong is not None and wrong.code == "quote"                               # the quote is in D4, not D3
    missing = ck.check_citation(dict(c, section="D9"), ev, "t")
    assert missing is not None and "has no part D9" in missing.message
    r = ck.check_citation(dict(c, section="R"), ev, "t")
    assert r is not None and r.code == "schema"
    assert ck.base_section("D12") == "D" and ck.base_section("D") == "D" and ck.base_section("DX") == "DX" and ck.base_section(None) is None


def test_a_d_part_quote_counts_as_section_d_for_hard_evidence_and_for_the_pool():
    ev = evidence()
    q = "For the December quarter, we expect total revenue growth of 2 percent to 4 percent over last year"
    assert ck.qualifies(q)
    assert ck.hard_evidence([{"section": "D4", "quote": q}], ev)
    pooled = ck.Evidence({"S": FIXTURE["sections"]["S"]}, [("D4", q)])                # P5 shows no D: a pass-1 D4 quote may be re-cited as D4 or D
    assert ck.check_citation({"section": "D4", "quote": q}, pooled, "t") is None
    assert ck.check_citation({"section": "D", "quote": q}, pooled, "t") is None
    assert ck.check_citation({"section": "Q", "quote": q}, pooled, "t") is not None   # Q was neither shown nor pooled


def test_d_subsections_split_at_the_pack_markers_only():
    text = "[D1] Annual report, filed 2025-02-11\nAlpha text [D9] inline is not a marker\n\n[D2] Release\nBeta"
    parts = ck.d_subsections(text)
    assert list(parts) == ["D1", "D2"] and "inline is not a marker" in parts["D1"] and parts["D2"].endswith("Beta")
    assert ck.d_subsections(None) == {} and ck.d_subsections("no markers") == {}


# ---- the schemas against the checker, every prompt and family ------------------------------------------------------------------------------

def entry(section="D1", quote="Delta generated record September quarter revenue", pct=60):
    return {"percentile": pct, "width": "normal", "reasons": ["a reason"], "citations": [{"section": section, "quote": quote}]}


@pytest.mark.parametrize("family", ["operating", "financial"])
def test_every_schema_accepts_a_checker_shaped_answer_and_rejects_the_nested_extras(family):
    labels = ["F", "Q", "D", "S", "D1", "D2"]
    names = muse_inputs(family)
    for prompt, extra in (("P1", {"bull_case": {"text": "Up.", "citation": {"section": "D1", "quote": "Delta generated record"}},
                                  "bear_case": {"text": "Down.", "citation": {"section": "F", "quote": "Revenue | 40,704.0"}}}),
                          ("P2", {"character": {"value": "structural", "reasons": "why", "citations": [{"section": "D2", "quote": "some exact text"}]}}),
                          ("P3", {}),
                          ("P4", {"risks": [{"risk": "r", "input": names[0], "citation": {"section": "S", "quote": "Size: revenue 1"}}] * 3})):
        ans = {"inputs": {n: entry() for n in names[:2]}, **extra}
        sch = js.pass1_schema(prompt, names[:2], family, labels)
        assert errors(ans, sch) == [], prompt
        if extra:
            k = next(iter(extra))
            nested = {"inputs": {**ans["inputs"], k: extra[k]}}
            assert errors(nested, sch), prompt                                       # the run-1 shape cannot be produced
    syn = {"inputs": {n: entry() for n in names[:2]}, "changes": [{"input": names[0], "reason": "coherence"}], "coherence": "ok"}
    assert errors(syn, js.synthesis_schema(names[:2], labels)) == []
    assert errors(dict(syn, inputs={**syn["inputs"], "coherence": "x"}), js.synthesis_schema(names[:2], labels))


def test_the_schemas_never_offer_r_and_enforce_the_checkers_bounds():
    sch = js.pass1_schema("P1", P1_INPUTS, "operating", js.citation_labels({"F": "", "D": "[D1] x\n", "S": "", "R": ""}))
    cit = sch["properties"]["inputs"]["properties"]["g1"]["properties"]["citations"]["items"]
    assert "R" not in cit["properties"]["section"]["enum"] and "Q" not in cit["properties"]["section"]["enum"]   # Q not shown, R never evidence
    assert cit["properties"]["quote"]["minLength"] == ck.QUOTE_MIN and cit["properties"]["quote"]["maxLength"] == ck.QUOTE_MAX
    g1 = sch["properties"]["inputs"]["properties"]["g1"]["properties"]
    assert g1["percentile"]["minimum"] == 5 and g1["percentile"]["maximum"] == 95 and g1["reasons"]["maxItems"] == ck.MAX_REASONS


def test_the_redteam_schema_keep_revise_and_the_round_one_request():
    labels = ["F", "D", "S", "D1"]
    keep = {"market_case": "x" * 25, "decision": "keep", "new_quote": None, "named_error": None}
    revise = {"market_case": "y" * 25, "decision": "revise", **entry(), "new_quote": None, "named_error": {"reason_index": 2, "why_wrong": "z" * 25}}
    r1 = js.redteam_schema(P1_INPUTS, labels, 1, ["F", "D"])
    assert errors({"inputs": {"g1": keep, "growth_persistence": revise}}, r1) == []
    assert errors({"request_sections": ["D"]}, r1) == []
    assert errors({"request_sections": ["Q"]}, r1)                                   # Q not requestable for this pack
    r2 = js.redteam_schema(P1_INPUTS, labels, 2)
    assert errors({"request_sections": ["D"]}, r2)                                   # no request in round 2
    assert errors({"inputs": {"g1": dict(keep, market_case="short"), "growth_persistence": keep}}, r2)   # MARKET_CASE_MIN stated by the schema
    assert errors({"inputs": {"g1": dict(revise, percentile=None), "growth_persistence": keep}}, r2)


def test_response_format_is_the_openai_json_schema_field():
    rf = js.response_format({"type": "object"}, "P1")
    assert rf == {"type": "json_schema", "json_schema": {"name": "P1", "schema": {"type": "object"}, "strict": True}}


# ---- the contract: the prompt says exactly what the checker and the schema accept ------------------------------------------------------------

def test_the_rendered_examples_offer_exactly_the_schema_labels_and_never_r():
    for labels in (["F", "Q", "D", "S", "D1", "D2"], ["F", "D", "S"], ["S"]):
        for p in ("P1", "P2", "P3", "P4", "P5", "P6"):
            ex = prompting._example(p, P1_INPUTS, "operating", labels)
            if p != "P6":                                                            # P6's example names no section (its schema does)
                assert '"<' + "|".join(labels) + '>"' in ex
            assert "|R>" not in ex and "<F|Q|D|S|R>" not in ex


def test_p5_no_longer_invites_quotes_from_r():
    t = prompting.read_template("P5")
    assert "section S or R" not in t and "never a source of quotes" in t


# ---- the runner sends the schema on both attempts --------------------------------------------------------------------------------------------

class Seq:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def chat(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        return {"choices": [{"message": {"content": self.answers.pop(0), "reasoning_content": "r"}, "finish_reason": "stop"}], "usage": {}}


def test_the_runner_sends_and_saves_response_format_on_both_attempts(tmp_path):
    rf = js.response_format({"type": "object"}, "X")
    r = MuseRunner(Seq('{"a": 2}', '{"a": 1}'), tmp_path)
    res = r.call("X", "hello", lambda o: [] if o.get("a") == 1 else [ck.Issue("schema", "a must be 1")], response_format=rf)
    assert res.ok and res.retried
    assert all(q["response_format"] == rf for q in r.client.requests) and len(r.client.requests) == 2
    saved = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(tmp_path.glob("*_request.json"))]
    assert all(s["response_format"] == rf for s in saved)
    r2 = MuseRunner(Seq('{"a": 1}'), tmp_path / "b")
    r2.call("Y", "hi", lambda o: [])
    assert "response_format" not in r2.client.requests[0]                               # absent unless given


# ---- Addendum AD.10: the ticker as of T, and the audit's review classes -----------------------------------------------------------------------

def test_a_ticker_is_shown_only_when_a_document_accepted_before_t_names_it():
    from valuation.muse.pack_v2 import header_text, ticker_as_of_t
    base = {"name": "AMBAC FINANCIAL GROUP INC", "ticker": "OSG", "ticker_source": "current_record"}
    doc = "[D1] Annual report\nAmbac (NYSE: AMBC) provides financial guarantees."
    w = ticker_as_of_t(base, doc)
    assert w["ticker"] is None and w["ticker_source"] == "withheld" and w["ticker_withheld"] == "OSG"
    h = header_text("2025-10-31", w, "financial")
    assert "Company: AMBAC FINANCIAL GROUP INC\n" in h and "OSG" not in h
    v = ticker_as_of_t(dict(base, ticker="AMBC"), doc)
    assert v["ticker"] == "AMBC" and v["ticker_source"] == "verified_in_filing"
    assert ticker_as_of_t(dict(base, ticker="AMB"), doc)["ticker_source"] == "withheld"                         # whole-word match only
    assert ticker_as_of_t(dict(base, ticker_source="as_of_T"), None)["ticker"] == "OSG"                         # an as-of-T stamp is kept


def test_the_audit_reviews_model_text_and_fiscal_labels_but_keeps_code_text_strict():
    from datetime import date
    from valuation.muse import leakage_audit as la
    asof = date(2025, 10, 31)
    p5 = ("Analysis date: 2025-10-31\n-- P1 --\ng1: position P70, width normal\n  reason 1: Company is guiding calendar 2026 revenue with pricing power\n"
          '  cited [D2]: "we expect 2026 revenue of $2.6 billion"\nThe outlook for 2027 is code-built text.\n')
    fs = la.scan_prompt_text(p5, asof, "P5", pass1=True)
    assert [f.match for f in fs if f.severity == "violation"] == ["2027"]                                       # only the code-built line
    assert {f.match for f in fs if f.severity == "review"} >= {"2026", "pricing"}
    hdr = la.scan_section("D", "[D1] 8-K Item 2.02 earnings release, filed 2025-09-03, Q2 2026\nbody", asof, "pack")
    assert hdr and all(f.severity == "review" for f in hdr if f.kind == "date_after_T")
    late = la.scan_section("D", "[D1] 8-K Item 2.02 earnings release, filed 2025-11-03, Q2 2026\nbody", asof, "pack")
    assert any(f.severity == "violation" for f in late)                                                         # filed after T: still a violation
    pk = {"header": "Analysis date: 2025-10-31\nCompany: X", "sections": {}, "r": {},
          "manifest": {"identity": {"name_source": "as_of_T", "ticker_source": "withheld", "industry_source": "as_of_T"}}}
    assert not [f for f in la.audit_pack(pk, asof) if f.kind == "identity"]
    pk["manifest"]["identity"]["ticker_source"] = "current_record"
    assert [f for f in la.audit_pack(pk, asof) if f.kind == "identity"]


def test_a_date_in_model_text_must_be_grounded_in_the_filings_addendum_ae4():
    from datetime import date
    from valuation.muse import leakage_audit as la
    asof = date(2025, 10, 31)
    p5 = "Analysis date: 2025-10-31\n-- P1 --\n  reason 1: guidance for calendar 2026 revenue\n  reason 2: the 2027 merger closes\n"
    fs = la.scan_prompt_text(p5, asof, "P5", pass1=True, grounding="We expect calendar 2026 revenue of $2.6 billion.")
    by = {f.match: f.severity for f in fs if f.kind == "date_after_T"}
    assert by == {"2026": "review", "2027": "violation"}                             # 2027 is in no filing shown: ungrounded future
    plain = {f.match: f.severity for f in la.scan_prompt_text(p5, asof, "P5", pass1=True) if f.kind == "date_after_T"}
    assert plain == {"2026": "review", "2027": "review"}                              # without grounding text nothing changes

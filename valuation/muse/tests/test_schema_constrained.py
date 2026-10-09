"""Addendum AC: schema-constrained decoding and the D-document labels.  Mock model only: no server is started.

  - every Muse request carries `response_format` (the JSON schema of the checker's own shape), on the retry too; the other spelling is the fallback, never "no constraint";
  - the extras (bull_case, bear_case, character, risks, changes, coherence) sit OUTSIDE "inputs" in every schema, and the mock's own answers conform to the schemas it was sent;
  - an answer in the OLD nested shape (extras among the inputs, an extra closing brace) fails the checks and is retried with the checker's message;
  - a citation may name a document of section D ("D1", "D2", ...): the quote is looked up in that document only.
"""
import json
import re

import pytest

from valuation.muse import checkers as ck
from valuation.muse import prompting
from valuation.muse.checkers import Evidence, Issue
from valuation.muse.pipeline import run_company
from valuation.muse.runner import MuseRunner, MuseTransportError
from valuation.muse.tests import fixtures as fx


# ---- a small validator for the subset of JSON schema the module uses (the jsonschema package is not installed) -----------------------------

def valid(inst, sch, path="$"):
    """[] when `inst` satisfies `sch`, else the list of violations."""
    if "anyOf" in sch:
        errs = [valid(inst, s, path) for s in sch["anyOf"]]
        return [] if any(not e for e in errs) else [f"{path}: matches none of the {len(errs)} alternatives"] + [x for e in errs for x in e]
    t = sch.get("type")
    if t == "null":
        return [] if inst is None else [f"{path}: not null"]
    if t == "object":
        if not isinstance(inst, dict):
            return [f"{path}: not an object"]
        out = [f"{path}: missing {k}" for k in sch.get("required", []) if k not in inst]
        for k, v in inst.items():
            if k not in sch["properties"]:
                if sch.get("additionalProperties") is False:
                    out.append(f"{path}: unexpected key {k!r}")
            else:
                out += valid(v, sch["properties"][k], f"{path}.{k}")
        return out
    if t == "array":
        if not isinstance(inst, list):
            return [f"{path}: not an array"]
        out = []
        if len(inst) < sch.get("minItems", 0) or len(inst) > sch.get("maxItems", 10 ** 9):
            out.append(f"{path}: {len(inst)} items")
        for i, x in enumerate(inst):
            out += valid(x, sch["items"], f"{path}[{i}]")
        return out
    if t == "string":
        if not isinstance(inst, str):
            return [f"{path}: not a string"]
        if "enum" in sch and inst not in sch["enum"]:
            return [f"{path}: {inst!r} not in enum"]
        if "pattern" in sch and not re.search(sch["pattern"], inst):
            return [f"{path}: {inst!r} does not match the pattern"]
        return []
    if t == "number":
        return [] if isinstance(inst, (int, float)) and not isinstance(inst, bool) else [f"{path}: not a number"]
    if t == "integer":
        return [] if isinstance(inst, int) and not isinstance(inst, bool) else [f"{path}: not an integer"]
    raise AssertionError(f"validator does not know {sch}")


def schema_of(request):
    rf = request["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    return rf["json_schema"]["schema"]


def run(tmp_path, client, price=None):
    return run_company(pit=fx.make_pit(), identity=fx.IDENTITY, priors=fx.LabeledPlaceholderPriors(), disc_factory=fx.disc_factory, client=client, run_dir=tmp_path / "run",
                       price_info=price, documents=fx.docs(), quarters=fx.quarters(), n_draws=200, seed=11, industry_context=fx.INDUSTRY_CONTEXT)


def realistic_price(tmp_path):
    p = run(tmp_path / "probe", fx.ScriptedMuse())["pass1"]["iv_per_share"]["p50"]
    return {"price": p, "market_cap": p * 100.0, "currency": "USD"}


class Seq:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def chat(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return {"choices": [{"message": {"content": a}, "finish_reason": "stop"}], "usage": {}}


def ok_validator(o):
    return [] if o.get("a") == 1 else [Issue("schema", "a must be 1")]


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}


# ---- the request ---------------------------------------------------------------------------------------------------------------------

def test_the_schema_is_sent_as_response_format_on_the_first_attempt_and_on_the_retry(tmp_path):
    c = Seq('{"a": 2}', '{"a": 1}')
    res = MuseRunner(c, tmp_path).call("P1", "u", ok_validator, schema=SCHEMA)
    assert res.ok and res.retried and len(c.requests) == 2
    for req in c.requests:
        assert req["response_format"] == {"type": "json_schema", "json_schema": {"name": "muse_answer", "strict": True, "schema": SCHEMA}}
    saved = json.loads((tmp_path / "01_P1_a1_request.json").read_text(encoding="utf-8"))
    assert saved["response_format"]["json_schema"]["schema"] == SCHEMA                    # the record holds what was sent
    calls = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["response_format"] for x in calls] == ["json_schema", "json_schema"] and not any(x["style_fallback"] for x in calls)


def test_a_call_without_a_schema_sends_no_response_format(tmp_path):
    c = Seq('{"a": 1}')
    MuseRunner(c, tmp_path).call("P1", "u", ok_validator)
    assert "response_format" not in c.requests[0]


def test_when_the_server_rejects_the_spelling_the_other_spelling_of_the_same_schema_is_sent_once(tmp_path):
    c = Seq(MuseTransportError("HTTP 400 from http://x: response_format type must be one of text or json_object"), '{"a": 1}', '{"a": 1}')
    r = MuseRunner(c, tmp_path)
    assert r.call("P1", "u", ok_validator, schema=SCHEMA).ok
    assert c.requests[0]["response_format"]["type"] == "json_schema" and c.requests[1]["response_format"] == {"type": "json_object", "schema": SCHEMA}
    assert r.call("P2", "u", ok_validator, schema=SCHEMA).ok and c.requests[2]["response_format"]["type"] == "json_object"          # sticky: not retried per call
    calls = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["style_fallback"] for x in calls] == [True, False] and calls[0]["response_format"] == "json_object"
    saved = json.loads((tmp_path / "01_P1_a1_request.json").read_text(encoding="utf-8"))
    assert saved["response_format"]["type"] == "json_object"                              # the file holds the request that was answered


def test_the_fallback_never_becomes_an_unconstrained_request(tmp_path):
    e = MuseTransportError("HTTP 400 from http://x: schema not supported")
    c = Seq(e, e)
    with pytest.raises(MuseTransportError):
        MuseRunner(c, tmp_path).call("P1", "u", ok_validator, schema=SCHEMA)
    assert len(c.requests) == 2 and all("response_format" in q for q in c.requests)
    # an unrelated transport failure, and a rejection that does not name the constraint, are not swallowed
    for err in (MuseTransportError("cannot reach http://x: refused"), MuseTransportError("HTTP 400 from http://x: context too long")):
        c = Seq(err)
        with pytest.raises(MuseTransportError):
            MuseRunner(c, tmp_path / "b").call("P1", "u", ok_validator, schema=SCHEMA)
        assert len(c.requests) == 1


# ---- the schemas: the checker's shape, extras OUTSIDE "inputs" ------------------------------------------------------------------

def test_every_request_of_a_full_run_carries_a_schema_and_the_mock_answers_conform_to_it(tmp_path):
    price = realistic_price(tmp_path)
    c = fx.ScriptedMuse(plan={"g1": (95, "narrow")}, p5={"ronic": (70, "normal")}, p6={"g1": dict(percentile=75, new_quote="designs and sells", needs_d=True)})
    sent = []
    inner = c.chat

    def spy(request):
        resp = inner(request)
        sent.append((fx.identify(request["messages"][1]["content"]), request, resp["choices"][0]["message"]["content"]))
        return resp
    c.chat = spy
    r = run(tmp_path, c, price)
    assert r["status"] == "ok"
    kinds = [k for k, _, _ in sent]
    assert kinds[:5] == ["P1", "P2", "P3", "P4", "P5"] and kinds.count("P6") == 2
    for k, req, content in sent:
        assert "response_format" in req, k
        errs = valid(json.loads(content), schema_of(req))
        assert errs == [], (k, errs)
    by = {}
    for k, req, _ in sent:
        by.setdefault(k, schema_of(req))
    assert set(by["P1"]["properties"]) == {"inputs", "bull_case", "bear_case"} and set(by["P2"]["properties"]) == {"inputs", "character"}
    assert set(by["P3"]["properties"]) == {"inputs"} and set(by["P4"]["properties"]) == {"inputs", "risks"}
    assert set(by["P5"]["properties"]) == {"inputs", "changes", "coherence"}
    assert set(by["P6"]["anyOf"][1]["properties"]) == {"request_sections"}                   # round 1 may ask for sections
    p6_round2 = [schema_of(req) for k, req, _ in sent if k == "P6"][1]
    assert "anyOf" not in p6_round2 and set(p6_round2["properties"]) == {"inputs"}           # round 2 may not
    # the inputs object of every schema holds the inputs asked and nothing else
    assert set(by["P1"]["properties"]["inputs"]["properties"]) == {"g1", "growth_persistence"}
    assert by["P1"]["properties"]["inputs"]["additionalProperties"] is False and set(by["P1"]["required"]) == {"inputs", "bull_case", "bear_case"}


def _pack():
    from valuation.common import build_state
    from valuation.muse.pack_v2 import build_pack
    pit = fx.make_pit()
    st = build_state(pit)
    st.update(fx.INDUSTRY_CONTEXT)
    ps = fx.LabeledPlaceholderPriors().for_company("operating", st, pit.asof)
    return build_pack(pit, "operating", fx.IDENTITY, ps, state=st, documents=fx.docs(), quarters=fx.quarters(), cik=None)


def test_the_schemas_force_the_extras_out_of_inputs_and_reject_the_old_nested_shape():
    rd = prompting.render_pass1("P1", _pack(), "operating")
    ans = fx.ScriptedMuse().answer("P1", rd.user)
    assert valid(ans, rd.schema) == []
    nested = {"inputs": dict(ans["inputs"], bull_case=ans["bull_case"], bear_case=ans["bear_case"])}       # the shape the first 38 companies produced
    errs = valid(nested, rd.schema)
    assert any("unexpected key 'bull_case'" in e for e in errs) and any("missing bull_case" in e for e in errs)
    r_cited = dict(ans, bull_case={"text": "t", "citation": {"section": "R", "quote": "x"}})
    assert any("pattern" in e for e in valid(r_cited, rd.schema))                                           # R cannot be cited
    d_label = dict(ans, bull_case={"text": "t", "citation": {"section": "D2", "quote": "x"}})
    assert valid(d_label, rd.schema) == []                                                                  # a document label can


def test_a_mock_that_returns_the_old_nested_shape_fails_the_checks_and_is_retried_with_the_message(tmp_path):
    def p1(user, attempt, req):
        ans = fx.ScriptedMuse().answer("P1", user)
        if attempt == 1:
            return {"inputs": dict(ans["inputs"], bull_case=ans.pop("bull_case"), bear_case=ans.pop("bear_case"))}
        return ans
    c = fx.ScriptedMuse(hooks={"P1": p1})
    r = run(tmp_path, c)
    assert r["calls"][0]["call"] == "P1" and r["calls"][0]["ok"] and r["calls"][0]["retried"]
    retry = c.requests[1]["messages"][3]["content"]
    assert "unexpected input 'bull_case'" in retry and "bull_case must be an object" in retry
    # and when it never corrects itself the call is not ok
    def always_nested(user, attempt, req):
        ans = fx.ScriptedMuse().answer("P1", user)
        return {"inputs": dict(ans["inputs"], bull_case=ans.pop("bull_case"), bear_case=ans.pop("bear_case"))}
    r2 = run(tmp_path / "again", fx.ScriptedMuse(hooks={"P1": always_nested}))
    assert r2["calls"][0]["ok"] is False


def test_the_prompts_state_the_exact_shape():
    for p in ("P1", "P2", "P3", "P4", "P5", "P6"):
        t = prompting.read_template(p)
        assert "THE SHAPE OF THE ANSWER" in t and "section R cannot be cited" in t and '"D2"' in t
    for p in ("P1", "P2", "P4", "P5"):
        assert "never inside it" in prompting.read_template(p)


# ---- the D-document labels ---------------------------------------------------------------------------------------------------------

D_TEXT = ("[D1] Annual report (Form 10-K): business description, filed 2026-02-28\nThe company designs and sells widgets for industrial customers worldwide.\n\n"
          "[D2] Annual report (Form 10-K): outlook, filed 2026-02-28\nThe company has a signed supply agreement for 12 GW of capacity and a backlog of $4.2 billion.\n\n"
          "[D3] 8-K Item 2.02 earnings release, filed 2026-02-20\nRevenue for the fourth quarter was $1,234.5 million, up 8.1% compared with the prior year.")
EV = Evidence({"S": "Size: revenue 410 million.", "D": D_TEXT})


def cit(section, quote):
    return {"section": section, "quote": quote}


def test_the_documents_of_section_d_are_separable():
    assert list(ck.split_documents(D_TEXT)) == ["D1", "D2", "D3"]
    assert "designs and sells widgets" in ck.split_documents(D_TEXT)["D1"] and "supply agreement" not in ck.split_documents(D_TEXT)["D1"]
    assert ck.split_documents("no headers at all") == {}


def test_the_real_pack_writes_the_document_headers_the_checker_splits_on():
    pack = _pack()
    assert list(ck.split_documents(pack.sections["D"])) == ["D1", "D2", "D3"]


def test_a_quote_cited_as_d2_is_verified_in_document_2_only():
    assert ck.check_citation(cit("D2", "signed supply agreement for 12 GW of capacity"), EV, "c") is None
    assert ck.check_citation(cit("D", "signed supply agreement for 12 GW of capacity"), EV, "c") is None              # the whole of D still works
    wrong = ck.check_citation(cit("D1", "signed supply agreement for 12 GW of capacity"), EV, "c")                    # real text, wrong document
    assert wrong is not None and wrong.code == "quote" and "section D1" in wrong.message
    assert ck.check_citation(cit("D3", "Revenue for the fourth quarter was $1,234.5 million"), EV, "c") is None


def test_a_document_that_does_not_exist_is_refused_with_the_labels_that_do():
    iss = ck.check_citation(cit("D7", "signed supply agreement for 12 GW of capacity"), EV, "c")
    assert iss.code == "section" and "D1, D2, D3" in iss.message
    nod = Evidence({"S": "s"})
    assert ck.check_citation(cit("D", "x" * 20), nod, "c").code == "section"                                          # no section D at all
    assert ck.check_citation(cit("D2", "signed supply agreement for 12 GW"), nod, "c").code == "section"
    for bad in ("D0x", "DD", "D1.2", "R", "R1"):
        assert ck.check_citation(cit(bad, "signed supply agreement for 12 GW"), EV, "c").code == "schema"


def test_d_labels_count_as_section_d_for_hard_evidence_and_the_character_rule():
    quote = "signed supply agreement for 12 GW of capacity and a backlog"
    e = {"percentile": 95, "width": "narrow", "reasons": ["r"], "citations": [cit("D2", quote)]}
    assert ck.check_entry("g1", e, EV) == []                                                                         # outside P10..P90 with a D2 commitment
    weak = {"percentile": 95, "width": "narrow", "reasons": ["r"], "citations": [cit("D1", "designs and sells widgets for industrial customers")]}
    assert [i.code for i in ck.check_entry("g1", weak, EV)] == ["hard_evidence"]
    p2 = {"inputs": {"margin_target": dict(e, percentile=50), "margin_retention": dict(e, percentile=50)},
          "character": {"value": "structural", "reasons": "durable", "citations": [cit("D1", "designs and sells widgets for industrial customers")]}}
    assert ck.check_pass1("P2", p2, "operating", ["margin_target", "margin_retention"], EV) == []


def test_the_pool_keeps_the_label_a_quote_was_verified_under():
    q = "signed supply agreement for 12 GW of capacity"
    ev5 = Evidence({"S": "Size: revenue 410 million."}, [("D2", q)])                                                 # P5 shows no D
    assert ck.check_citation(cit("D2", q), ev5, "c") is None and ck.check_citation(cit("D", q), ev5, "c") is None
    other = ck.check_citation(cit("D3", q), ev5, "c")
    assert other is not None and other.code == "section"                                                              # D3 was never verified there
    ev5b = Evidence({"S": "Size: revenue 410 million."}, [("D", q)])
    assert ck.check_citation(cit("D2", q), ev5b, "c") is None                                                         # a plain-D quote was found in D

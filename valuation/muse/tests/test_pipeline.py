"""The two passes end to end with a MOCK model (canned JSON built from each prompt), placeholder priors and rates: test-only, no value is a valuation."""
import json

import pytest

from valuation.muse import leakage_audit as la
from valuation.muse.pipeline import run_company
from valuation.muse.runner import MuseTransportError
from valuation.muse.tests import fixtures as fx

PRICE = {"price": fx.PRICE_SENTINEL, "market_cap": fx.MCAP_SENTINEL, "currency": "USD"}


def run(tmp_path, client, price=PRICE, pit=None, **kw):
    pit = pit or fx.make_pit()
    return run_company(pit=pit, identity=fx.IDENTITY, priors=fx.LabeledPlaceholderPriors(), disc_factory=fx.disc_factory, client=client,
                       run_dir=tmp_path / "run", price_info=price, documents=fx.docs(), quarters=fx.quarters(), n_draws=200, seed=11, industry_context=fx.INDUSTRY_CONTEXT, **kw)


def kinds(client):
    return [fx.identify(r["messages"][1]["content"]) for r in client.requests]


@pytest.fixture
def realistic_price(tmp_path):
    """A price near the code-only median value per share, so the reverse valuation has something to find."""
    r = run(tmp_path / "probe", fx.ScriptedMuse(), price=None)
    p = r["pass1"]["iv_per_share"]["p50"]
    return {"price": p, "market_cap": p * 100.0, "currency": "USD"}


def test_pass1_and_pass2_call_sequence_and_a_clean_run(tmp_path, realistic_price):
    c = fx.ScriptedMuse()
    r = run(tmp_path, c, price=realistic_price)
    assert r["status"] == "ok" and kinds(c) == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert r["family"] == "operating" and r["placeholder_priors"] is True and r["final"]["placeholder"] is True
    assert set(r["pass1"]["positions"]) == {"g1", "growth_persistence", "margin_target", "margin_retention", "ronic", "g_terminal"}
    assert all(p["status"] == "anchored" for p in r["final"]["positions"].values()) and r["final"]["unanchored_inputs"] == []
    assert (tmp_path / "run" / "result.json").exists() and (tmp_path / "run" / "pack.json").exists() and (tmp_path / "run" / "run_manifest.json").exists()


def test_all_p50_normal_gives_the_code_only_distribution(tmp_path, realistic_price):
    r = run(tmp_path, fx.ScriptedMuse(), price=realistic_price)
    assert r["final"]["iv_per_share"]["p50"] == pytest.approx(r["code_only"]["iv_per_share"]["p50"], rel=1e-9)


def test_the_financial_family_skips_p3(tmp_path):
    c = fx.ScriptedMuse()
    r = run(tmp_path, c, pit=fx.make_pit(sic="6021"))
    assert r["family"] == "financial" and r["status"] == "ok" and kinds(c) == ["P1", "P2", "P4", "P5", "P6"]
    assert set(r["pass1"]["positions"]) == {"g1", "growth_persistence", "rote_target", "rote_retention", "g_terminal"}


def test_no_pass1_prompt_contains_the_price_the_market_cap_or_any_value(tmp_path):
    c = fx.ScriptedMuse()
    r = run(tmp_path, c)
    assert r["status"] == "ok"
    p6 = [q["messages"][1]["content"] for q in c.requests if fx.identify(q["messages"][1]["content"]) == "P6"][0]
    assert "8,731.43" in p6 and "873,143,000" in p6                                       # the price reaches pass 2 only
    for q in c.requests:
        user = q["messages"][1]["content"]
        if fx.identify(user) == "P6":
            continue
        whole = json.dumps(q)
        for s in ("8731.43", "8,731.43", "873,143,000", "873143000"):
            assert s not in whole
        assert la.scan_prompt_text(user, la.date.fromisoformat(fx.ASOF), "p", pass1=True) == []         # no forbidden word, no later date, header exact
        assert "intrinsic" not in user.lower() and "market cap" not in user.lower()
    assert r["stamps"] == [s for s in r["stamps"] if "price_string_collision" not in s]


def test_a_pass1_answer_that_fails_is_retried_with_the_checkers_message(tmp_path):
    def p1(user, attempt, req):
        if attempt == 1:
            return {"inputs": {"g1": {"percentile": 99, "width": "normal", "reasons": ["r"], "citations": []}}}
        return fx.ScriptedMuse().answer("P1", user)
    c = fx.ScriptedMuse(hooks={"P1": p1})
    r = run(tmp_path, c)
    assert r["calls"][0]["call"] == "P1" and r["calls"][0]["ok"] and r["calls"][0]["retried"]
    retry = c.requests[1]["messages"][3]["content"]
    assert "percentile must be a number from 5 to 95" in retry and "citations must be a list" in retry and "growth_persistence is missing" in retry


def test_a_failed_input_after_the_retry_is_unanchored_at_the_priors_p50_with_width_wide(tmp_path):
    def bad(user, attempt, req):
        return "not json at all"
    c = fx.ScriptedMuse(hooks={"P2": bad, "P5": bad})
    r = run(tmp_path, c)
    assert r["status"] == "ok"
    for n in ("margin_target", "margin_retention"):
        p = r["final"]["positions"][n]
        assert (p["percentile"], p["width"], p["status"]) == (50.0, "normal", "unanchored") and p["stamps"][0].startswith("unanchored:")
    assert r["final"]["positions"]["g1"]["status"] == "anchored"
    assert r["final"]["unanchored_inputs"] == ["margin_retention", "margin_target"]
    assert [x["call"] for x in r["calls"]][:2] == ["P1", "P2"] and r["calls"][1]["ok"] is False


def test_p5_rescues_an_input_that_pass1_could_not_place(tmp_path):
    c = fx.ScriptedMuse(hooks={"P2": lambda u, a, r: "not json"})
    r = run(tmp_path, c)
    assert r["final"]["positions"]["margin_target"]["status"] == "anchored" and r["final"]["positions"]["margin_target"]["source"] == "P5"


def test_a_position_outside_p10_p90_without_hard_evidence_is_unanchored(tmp_path):
    def p1(user, attempt, req):
        a = fx.ScriptedMuse(plan={"g1": (95, "normal")}).answer("P1", user)
        a["inputs"]["g1"]["citations"] = [c for c in a["inputs"]["g1"]["citations"] if c["section"] != "D"]
        return a
    c = fx.ScriptedMuse(hooks={"P1": p1, "P5": lambda u, a, r: "nope"})
    r = run(tmp_path, c)
    g = r["final"]["positions"]["g1"]
    assert g["status"] == "unanchored" and g["percentile"] == 50.0 and "hard_evidence" in json.dumps(r["calls"][0]["issues"])


def test_a_hard_evidence_position_is_kept_counted_and_moves_the_value(tmp_path, realistic_price):
    c = fx.ScriptedMuse(plan={"g1": (95, "narrow")})
    r = run(tmp_path, c, price=realistic_price)
    g = r["final"]["positions"]["g1"]
    assert g["status"] == "anchored" and g["percentile"] == 95 and g["hard_evidence"] is True and r["final"]["n_hard_evidence_positions"] == 1
    assert r["final"]["iv_per_share"]["p50"] > r["code_only"]["iv_per_share"]["p50"]


def test_p5_changes_are_applied_and_must_be_listed(tmp_path):
    c = fx.ScriptedMuse(p5={"ronic": (70, "normal")})
    r = run(tmp_path, c)
    assert r["final"]["positions"]["ronic"]["percentile"] == 70 and r["final"]["positions"]["ronic"]["source"] == "P5"
    assert r["calls"][4]["call"] == "P5" and r["calls"][4]["ok"]
    unlisted = fx.ScriptedMuse(hooks={"P5": lambda u, a, req: dict(fx.ScriptedMuse(p5={"ronic": (70, "normal")}).answer("P5", u), changes=[])})
    r2 = run(tmp_path / "b", unlisted)
    assert r2["calls"][4]["ok"] is False and "has no entry in changes" in json.dumps(r2["calls"][4]["issues"])


def test_the_final_assembly_has_every_output_of_the_spec(tmp_path, realistic_price):
    r = run(tmp_path, fx.ScriptedMuse(), price=realistic_price)
    f = r["final"]
    for k in ("iv_per_share", "prob_iv_above_price", "prob_iv_above_1.2x_price", "prob_iv_below_0.8x_price", "tv_share_p50", "model_disagreement",
              "n_hard_evidence_positions", "extraordinary_flags", "unanchored_inputs"):
        assert k in f
    assert 0.0 <= f["prob_iv_above_price"] <= 1.0 and f["prob_iv_above_1.2x_price"] <= f["prob_iv_above_price"] <= 1.0 - f["prob_iv_below_0.8x_price"] + 1e-9
    assert {"p10", "p50", "p90"} <= set(f["iv_per_share"]) and f["tv_share_p50"] is not None
    assert set(r["reverse"]["inputs"]) == set(r["final"]["positions"]) and r["reverse"]["inputs"]["g1"]["status"] in ("ok", "not_reachable")
    assert "market_de_sensitivity" in f and f["market_de_sensitivity"]["market_de"] > 0
    assert "anchoring" in r["redteam"]


def test_a_price_far_from_any_value_flags_extraordinary_assumptions(tmp_path):
    r = run(tmp_path, fx.ScriptedMuse())
    assert r["final"]["extraordinary_flags"] and all(v["status"] == "not_reachable" for v in r["reverse"]["inputs"].values() if v["input"] in
                                                      r["final"]["extraordinary_flags"])


def test_red_team_refuses_a_revision_without_new_evidence_and_the_pass1_position_stands(tmp_path, realistic_price):
    c = fx.ScriptedMuse(p6={"g1": dict(percentile=75)})
    r = run(tmp_path, c, price=realistic_price)
    d = next(x for x in r["redteam"]["decisions"] if x["input"] == "g1")
    assert d["proposed"] and not d["accepted"] and "refused" in d["reason"]
    assert r["final"]["positions"]["g1"]["percentile"] == 50.0
    assert r["redteam"]["anchoring"]["n_proposed"] == 1 and r["redteam"]["anchoring"]["n_refused"] == 1


def test_red_team_accepts_a_revision_with_a_new_quote_after_asking_for_section_d(tmp_path, realistic_price):
    c = fx.ScriptedMuse(p6={"g1": dict(percentile=75, new_quote="designs and sells", needs_d=True)})
    r = run(tmp_path, c, price=realistic_price)
    assert kinds(c) == ["P1", "P2", "P3", "P4", "P5", "P6", "P6"]                          # one request round
    first, second = [q["messages"][1]["content"] for q in c.requests[-2:]]
    assert "=== SECTION D" not in first and "provided on request" in first and "=== SECTION D" in second and "no further requests" in second.lower()
    g = r["final"]["positions"]["g1"]
    assert g["percentile"] == 75 and g["source"] == "P6" and "revision_evidence: new_quote" in g["stamps"]


def test_red_team_named_error_counts_only_away_from_the_price(tmp_path, realistic_price):
    """Addendum AE.1: a named error can move a position away from the price; toward the price it needs a new filing quote."""
    r = run(tmp_path, fx.ScriptedMuse(p6={"ronic": dict(percentile=30, named_error=True)}), price=realistic_price)
    d = next(x for x in r["redteam"]["decisions"] if x["input"] == "ronic")
    assert d["proposed"] and d["named_error"] and not d["new_quote"]
    if d["toward_price"]:
        assert not d["accepted"] and "Addendum AE.1" in d["reason"] and r["final"]["positions"]["ronic"]["source"] != "P6"
    else:
        assert d["accepted"] and r["final"]["positions"]["ronic"]["percentile"] == 30 and r["final"]["positions"]["ronic"]["source"] == "P6"


def test_a_p6_that_never_parses_leaves_every_pass1_position(tmp_path, realistic_price):
    r = run(tmp_path, fx.ScriptedMuse(hooks={"P6": lambda u, a, req: "garbage"}), price=realistic_price)
    assert r["status"] == "ok" and all(p["source"] != "P6" for p in r["final"]["positions"].values())
    assert r["calls"][-1]["call"] == "P6" and r["calls"][-1]["ok"] is False


def test_without_a_price_the_run_stops_after_the_price_free_pass(tmp_path):
    c = fx.ScriptedMuse()
    r = run(tmp_path, c, price=None)
    assert r["status"] == "pass1_only" and kinds(c) == ["P1", "P2", "P3", "P4", "P5"] and "reverse" not in r and r["pass1"]["iv_per_share"]["p50"] > 0


def test_a_transport_failure_stops_the_run_and_makes_no_values(tmp_path):
    class Down:
        def chat(self, req):
            raise MuseTransportError("no server")
    r = run(tmp_path, Down())
    assert r["status"] == "model_unavailable" and "final" not in r and "pass1" not in r


def test_an_engine_refusal_stops_before_any_model_call(tmp_path):
    c = fx.ScriptedMuse()
    r = run(tmp_path, c, pit=fx.make_pit(drop=("capex",)))
    assert r["status"] == "engine_refused" and "maintenance" in json.dumps(r["reason"]) and c.requests == []
    r = run(tmp_path / "b", c, pit=fx.make_pit(years=1))                       # no prior year: the discount rate cannot be built
    assert r["status"] == "refused" and c.requests == []


def test_a_family_not_built_is_not_valued_and_no_model_is_called(tmp_path):
    c = fx.ScriptedMuse()
    r = run(tmp_path, c, pit=fx.make_pit(sic="6798"))
    assert r["status"] == "not_valued" and "family not built" in r["reason"] and c.requests == []


def test_every_request_is_saved_and_the_leakage_audit_of_the_run_is_clean(tmp_path, realistic_price):
    r = run(tmp_path, fx.ScriptedMuse(), price=realistic_price)
    files = sorted(p.name for p in (tmp_path / "run").iterdir())
    assert sum(f.endswith("_request.json") for f in files) == 6 == sum(f.endswith("_response.json") for f in files)
    rep = la.audit_run_dir(tmp_path / "run")
    assert rep["violations"] == 0, rep["findings"]

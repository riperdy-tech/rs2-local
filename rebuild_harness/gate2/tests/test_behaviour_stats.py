"""behaviour_stats: format, anchoring and red-team counts from saved run folders (mock model; Addendum AC 4)."""
import json

from rebuild_harness.gate2 import behaviour_stats as bs
from valuation.muse.pipeline import run_company
from valuation.muse.tests import fixtures as fx


def make_run(state, key, client, price=None):
    run_dir = state / "runs" / "2025-10-31" / key / "a01"
    run_company(pit=fx.make_pit(), identity=fx.IDENTITY, priors=fx.LabeledPlaceholderPriors(), disc_factory=fx.disc_factory, client=client, run_dir=run_dir, price_info=price,
                documents=fx.docs(), quarters=fx.quarters(), n_draws=200, seed=11, industry_context=fx.INDUSTRY_CONTEXT)
    return run_dir


def test_a_clean_run_has_every_call_parsing_and_passing_on_the_first_attempt(tmp_path):
    probe = make_run(tmp_path / "probe", "2025-10-31_0000000001", fx.ScriptedMuse())
    p = json.loads((probe / "result.json").read_text(encoding="utf-8"))["pass1"]["iv_per_share"]["p50"]
    make_run(tmp_path, "2025-10-31_0000000002", fx.ScriptedMuse(p6={"g1": dict(percentile=75, named_error=True)}), {"price": p, "market_cap": p * 100.0, "currency": "USD"})
    rep = bs.behaviour(tmp_path)
    assert rep["n_company_dates_with_muse_calls"] == 1
    assert rep["json_parse_first_attempt"] == 1.0 and rep["clean_first_attempt"] == 1.0 and rep["format_clean_first_attempt"] == 1.0
    assert rep["unanchored_share"] == 0.0 and rep["p5_success"] == 1.0 and rep["p5_runs"] == 1
    assert rep["red_team"] == {"inputs_with_a_proposal": 1, "proposals_accepted": 1}
    assert all(rep["gate"][k] for k in ("first_attempt_parse", "format_clean_first_attempt", "unanchored", "p5"))


def test_unparseable_and_misplaced_answers_are_counted_as_format_failures(tmp_path):
    def nested(user, attempt, req):
        ans = fx.ScriptedMuse().answer("P1", user)
        return {"inputs": dict(ans["inputs"], bull_case=ans.pop("bull_case"), bear_case=ans.pop("bear_case"))}
    make_run(tmp_path, "2025-10-31_0000000003", fx.ScriptedMuse(hooks={"P1": nested, "P2": lambda u, a, r: "not json", "P5": lambda u, a, r: "not json"}))
    rep = bs.behaviour(tmp_path)
    assert rep["by_call"]["P1"] == {"calls": 1, "json_first": 1, "clean_first": 0}                 # valid JSON, wrong shape: retried
    assert rep["by_call"]["P5"]["json_first"] == 0
    assert rep["format_clean_first_attempt"] < 1.0 and rep["p5_success"] == 0.0
    assert rep["unanchored_by_input"]["margin_target"] == "1 of 1" and rep["unanchored_by_input"]["g1"] == "0 of 1" and rep["gate"]["unanchored"] is False and rep["gate"]["p5"] is False
    assert any("unexpected input" in m for m, _n in rep["retry_reasons_top"])
    assert "percentile" not in json.dumps(rep) and "iv_per_share" not in json.dumps(rep)           # behaviour only: no value is reported

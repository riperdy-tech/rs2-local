"""G1-G6 scoring on SYNTHETIC data only, the outcome extraction on a fake layer, the integrity re-check on mock runs, and the freeze contents."""
import json
from pathlib import Path

import numpy as np
import pytest

from rebuild_harness.gate2 import config, freeze_content, integrity, outcome_extract as oe, scoring as sc
from rebuild_harness.gate2 import runner as rn
from rebuild_harness.gate2 import sample as sample_mod
from rebuild_harness.gate2.tests import fakes
from valuation.muse.tests import fixtures as fx


# ---- synthetic rows ---------------------------------------------------------------------------------------------------------------------

def make_world(n_companies=60, dates=("2025-10-31", "2025-12-31", "2026-02-27"), muse_better=True, signal=True, seed=0):
    """Rows and outcomes where the truth is known: MUSE's forecasts are closer to the outcome (or farther) than CODE's, and MUSE's IV/price carries (or lacks) information."""
    rng = np.random.default_rng(seed)
    rows, outcomes = [], {}
    for c in range(n_companies):
        fam = "financial" if c % 5 == 0 else "operating"
        for d in dates:
            key = f"{d}_{c:010d}"
            y_g, y_m = rng.normal(0.05, 0.05), rng.normal(0.12, 0.04)
            noise_c = rng.normal(0, 0.05, 2)
            noise_m = noise_c * (0.4 if muse_better else 1.8)
            ex = rng.normal(0, 0.1)
            code_ratio = 1.0 + rng.normal(0, 0.3)
            muse_ratio = (1.0 + ex * 2.0 + rng.normal(0, 0.1)) if signal else 1.0 + rng.normal(0, 0.3)
            price = 10.0
            fc = lambda y, n: {"p10": y + n - 0.06, "p50": y + n, "p90": y + n + 0.06}
            rows.append({"key": key, "date": d, "cik": f"{c:010d}", "family": fam, "price": price,
                         "code": {"iv": code_ratio * price, "iv_p50": code_ratio * price, "growth": None if fam == "financial" else fc(y_g, noise_c[0]), "margin": fc(y_m, noise_c[1]),
                                  "margin_base": 0.0},
                         "muse": {"iv": muse_ratio * price, "iv_p50": muse_ratio * price, "growth": None if fam == "financial" else fc(y_g, noise_m[0]), "margin": fc(y_m, noise_m[1]),
                                  "margin_base": 0.0},
                         "decisions": [], "positions": {}, "masked": False})
            q = {"revenue_growth": y_g, "operating_margin_change": y_m, "rote_change_annualised_on_tbv_at_T": y_m}    # base 0: the change equals the level
            outcomes[key] = {"key": key, "quarters": {"q1": q, "q2": q}, "returns": {"3": {"bounds": {b: ex for b in sc.BOUNDS}}}}
    return rows, outcomes


def test_g1_passes_when_muse_forecasts_better_and_fails_when_it_forecasts_worse():
    rows, outs = make_world(muse_better=True)
    r = sc.g1(rows, outs, draws=300)
    assert r["passes"] is True and r["growth_q1"]["median_d"] < 0 and r["growth_q1"]["upper90"] < 0 and r["margin_q1"]["upper90"] < 0
    assert r["growth_q1"]["n"] == 48 * 3                                              # financials have no growth forecast (stated)
    assert r["margin_q1"]["n"] == 60 * 3 and set(r["margin_q1"]["by_family"]) == {"financial", "operating"}
    rows, outs = make_world(muse_better=False)
    r = sc.g1(rows, outs, draws=300)
    assert r["passes"] is False and r["growth_q1"]["median_d"] > 0


def test_g1_needs_both_measures_and_counts_what_it_cannot_pair():
    rows, outs = make_world(muse_better=True)
    for r in rows:                                   # MUSE is worse on the margin only
        for p in ("p10", "p50", "p90"):
            r["muse"]["margin"][p] += 0.2
    assert sc.g1(rows, outs, draws=200)["passes"] is False
    rows, outs = make_world(n_companies=10)
    outs[next(r["key"] for r in rows if r["family"] == "operating")]["quarters"]["q1"] = None
    g = sc.g1_measure(rows, outs, "growth", draws=100)
    assert g["exclusions"]["no_outcome_elapsed_or_first_report"] >= 1
    assert sc.g1([], {}, draws=10)["passes"] is None                                    # no observation: not decided, never a pass


def test_the_cluster_bootstrap_resamples_whole_companies():
    vals, cl = [1.0, 1.0, 1.0, -5.0], ["a", "a", "a", "b"]
    b = sc.cluster_bootstrap_median(vals, cl, draws=400, seed=1)
    assert set(np.unique(b)) <= {-5.0, 1.0, -2.0, 0.0 + 1.0, -2.0}                      # medians of whole-company resamples only
    assert b.min() <= -2.0 and b.max() >= 1.0


def test_spearman_handles_ties_and_constants():
    assert sc.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert sc.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert sc.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
    assert sc.spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833, rel=1e-5)


def test_g2_direction_under_the_three_bounds_pass_fail_and_not_decided():
    rows, outs = make_world(signal=True)
    r = sc.g2(rows, outs, draws=100)
    assert r["verdict"] == "pass" and all(r["horizon_3m"][b]["delta_ic"] > 0 for b in sc.BOUNDS) and r["horizon_3m"]["excluded"]["interval90"][0] <= r["horizon_3m"]["excluded"]["delta_ic"]
    rows, outs = make_world(signal=False, seed=3)
    for r_ in rows:                                                                      # CODE carries the information instead
        ex = outs[r_["key"]]["returns"]["3"]["bounds"]["excluded"]
        r_["code"]["iv"] = r_["code"]["iv_p50"] = (1.0 + 3 * ex) * 10.0
    assert sc.g2(rows, outs, draws=100)["verdict"] == "fail"
    rows, outs = make_world(signal=True, seed=5)
    for k, o in outs.items():                                                            # under the minus-100% bound the order is destroyed: the bar straddles the bounds
        o["returns"]["3"]["bounds"]["minus100"] = -o["returns"]["3"]["bounds"]["excluded"]
    r = sc.g2(rows, outs, draws=100)
    assert r["horizon_3m"]["excluded"]["direction_positive"] is True and r["horizon_3m"]["minus100"]["direction_positive"] is False and r["verdict"] == "not_decided"
    rows, outs = make_world(n_companies=3)
    assert sc.g2(rows, outs, draws=10)["verdict"] is None                                # below 10 per date: nothing to say


def test_g2_drops_unobservable_returns_only_under_the_excluded_bound():
    rows, outs = make_world(n_companies=20)
    k = rows[0]["key"]
    outs[k]["returns"]["3"]["bounds"] = {"excluded": None, "minus100": -1.1, "last_close": -0.3}
    n_ex = len(sc.ic_rows(rows, outs, "3", "excluded")[0])
    assert n_ex == len(rows) - 1 and len(sc.ic_rows(rows, outs, "3", "minus100")[0]) == len(rows)


def test_g3_coverage_is_reported_for_both_arms():
    rows, outs = make_world(n_companies=30)
    g = sc.g3(rows, outs)
    assert set(g) == {"growth_muse", "growth_code", "margin_muse", "margin_code"} and 0.0 <= g["margin_muse"]["coverage_p10_p90"] <= 1.0 and g["margin_muse"]["n"] == 90


def decision(proposed=True, toward=True, new_quote=False, named=False, accepted=False):
    return {"input": "g1", "proposed": proposed, "accepted": accepted, "toward_price": toward, "new_quote": new_quote, "named_error": named}


def test_g4_share_of_revisions_toward_the_price_without_evidence():
    rows = [{"decisions": [decision(new_quote=True)] * 9 + [decision()]}]                # 1 of 10: 10% holds
    assert sc.g4(rows)["passes"] is True and sc.g4(rows)["share"] == pytest.approx(0.1)
    rows = [{"decisions": [decision(new_quote=True)] * 8 + [decision()] * 2}]            # 20%
    assert sc.g4(rows)["passes"] is False
    rows = [{"decisions": [decision(named=True)] * 5}]                                    # a named error is evidence under the revision rule
    g = sc.g4(rows)
    assert g["passes"] is True and g["share"] == 0.0 and g["share_without_new_quote"] == 1.0
    rows = [{"decisions": [decision(new_quote=True)] * 99 + [decision(accepted=True)]}]  # 1%, but the code ACCEPTED one: the refusal does not work
    assert sc.g4(rows)["passes"] is False
    assert sc.g4([{"decisions": [decision(proposed=False, toward=None)]}])["vacuous"] is True


def test_g6_mean_absolute_shift_of_placed_percentiles():
    pos = lambda **kw: {n: {"percentile": v, "status": "anchored"} for n, v in kw.items()}
    un = [{"key": "d_1", "positions": pos(g1=50, margin_target=60)}, {"key": "d_2", "positions": pos(g1=30)}]
    mk = [{"key": "M_d_1", "positions": pos(g1=40, margin_target=60)}, {"key": "M_d_2", "positions": {"g1": {"percentile": 20, "status": "unanchored"}}}]
    g = sc.g6(un, mk)
    assert g["n_company_dates"] == 2 and g["n_inputs_compared"] == 2 and g["mean_abs_shift_percentile_points"] == 5.0 and g["n_inputs_not_anchored_in_both"] == 1


def test_the_verdict_is_the_registration_section_5_mechanically():
    ok = {"passes": True}
    g2 = lambda v: {"verdict": v}
    assert sc.verdict(ok, g2("pass"), ok, ok)["verdict"] == "PASS"
    assert sc.verdict({"passes": False}, g2("pass"), ok, ok)["verdict"] == "FAIL"
    assert sc.verdict(ok, g2("fail"), ok, ok)["verdict"] == "FAIL"
    assert sc.verdict(ok, g2("not_decided"), ok, ok)["verdict"] == "NOT DECIDED"
    assert sc.verdict(ok, g2("not_decided"), {"passes": False}, ok)["verdict"] == "FAIL"           # a failed hard bar outranks a straddle
    assert sc.verdict({"passes": None}, g2("pass"), ok, ok)["verdict"] == "NOT DECIDED"


# ---- outcomes ---------------------------------------------------------------------------------------------------------------------------

class FakePit:
    def __init__(self, rows):
        self.rows, self.args = rows, None

    def quarterly_rows(self, cik, asof, fields, max_quarters, mode):
        self.args = (cik, asof, mode)
        return self.rows


def qrow(pe, filed, rev, rev0, oi, ni=10.0):
    return {"period_end": pe, "filed": filed, "accession": "A" + pe, "values": {"revenue": rev, "operating_income": oi, "net_income": ni}, "prior_year": {"revenue": rev0}}


def test_quarter_outcomes_are_the_first_two_quarters_first_reported_after_T():
    rows = [qrow("2025-06-30", "2025-08-05", 100, 90, 10), qrow("2025-09-30", "2025-11-05", 110, 100, 15), qrow("2025-12-31", "2026-02-10", 120, 105, 12),
            qrow("2026-06-30", "2026-08-10", 130, 110, 20)]
    pit = FakePit(rows)
    o = oe.quarter_outcomes(pit, "1", "2025-10-31", "operating")
    assert pit.args == ("1", None, "first_filed")                                           # the first-reported values, no date cutoff
    assert o["q1"]["period_end"] == "2025-09-30" and o["q1"]["revenue_growth"] == pytest.approx(0.10) and o["q1"]["operating_margin"] == pytest.approx(15 / 110)
    assert o["q2"]["period_end"] == "2025-12-31" and o["q2"]["revenue_growth"] == pytest.approx(120 / 105 - 1)
    o2 = oe.quarter_outcomes(pit, "1", "2026-03-01", "operating")
    assert o2["q1"]["period_end"] == "2026-06-30" and o2["q2"] is None                      # nothing after it: not invented
    gap = oe.quarter_outcomes(FakePit([rows[1], rows[3]]), "1", "2025-10-31", "operating")
    assert gap["q1"]["period_end"] == "2025-09-30" and gap["q2"] is None                    # a gap is never bridged
    assert oe.quarter_outcomes(FakePit(rows[:2]), "1", "2026-01-01", "operating") == {"q1": None, "q2": None}


def test_financial_rote_is_the_stated_approximation_and_zero_is_a_value():
    rows = [qrow("2025-09-30", "2025-11-05", 110, 100, 0.0, ni=5.0)]
    o = oe.quarter_outcomes(FakePit(rows), "1", "2025-10-31", "financial", tbv=100.0)
    assert o["q1"]["rote_annualised_on_tbv_at_T"] == pytest.approx(0.2) and o["q1"]["operating_margin"] == 0.0
    assert oe.quarter_outcomes(FakePit(rows), "1", "2025-10-31", "operating", tbv=100.0)["q1"]["rote_annualised_on_tbv_at_T"] is None


def test_only_elapsed_horizons_are_scored_and_the_outcome_file_is_written_once(tmp_path):
    assert oe.months_after("2025-10-31", 3).isoformat() == "2026-01-01" and oe.months_after("2025-12-31", 12).isoformat() == "2026-12-01"
    class Pit(FakePit):
        price_source = None
    import rebuild_harness.outcomes as oc
    calls = []
    orig = oc.horizon_outcome
    oc.horizon_outcome = lambda pit, key, asof, h, *a, **k: calls.append(h) or {"status": "observed", "excess": 0.01, "ret": 0.02, "bounds": {b: 0.01 for b in sc.BOUNDS}, "flags": []}
    try:
        r = oe.return_outcomes(Pit([]), "AAA", "2026-02-27", "2026-06-30")
        assert sorted(r) == ["3"] and calls == [3]                                           # 6 months end 2026-09-01: not elapsed
        r = oe.return_outcomes(Pit([]), "AAA", "2025-10-31", "2026-06-30")
        assert sorted(r) == ["3", "6"]
    finally:
        oc.horizon_outcome = orig
    job = {"cik": "1", "date": "2025-10-31", "ticker": None, "family": "operating"}
    p = oe.build(FakePit([]), [job], "2026-06-30", tmp_path)
    assert json.loads(p.read_text().splitlines()[0])["returns"]["3"]["status"] == "OUTCOME_UNOBSERVABLE"
    with pytest.raises(FileExistsError):
        oe.build(FakePit([]), [job], "2026-06-30", tmp_path)


def test_returns_are_measured_on_the_resolved_common_share_not_the_sample_ticker(monkeypatch):
    import rebuild_harness.outcomes as oc
    seen = []
    monkeypatch.setattr(oc, "horizon_outcome", lambda pit, key, asof, h, *a, **k: seen.append(key) or {"status": "observed", "excess": 0.0, "ret": 0.0,
                                                                                                        "bounds": {b: 0.0 for b in sc.BOUNDS}, "flags": []})
    job = {"cik": "1000", "date": "2025-10-31", "ticker": "BRKRP", "family": "operating"}
    o = oe.company_outcomes(FakePit([]), job, "2026-06-30", ticker_of=lambda j: "BRKR")
    assert o["ticker"] == "BRKR" and o["sample_ticker"] == "BRKRP" and set(seen) == {"BRKR"}       # Addendum AD.10: the security priced at T
    seen.clear()
    assert oe.company_outcomes(FakePit([]), job, "2026-06-30")["ticker"] == "BRKRP" and set(seen) == {"BRKRP"}


# ---- the integrity re-check and the loader on real mock runs ---------------------------------------------------------------------------------

def run_mock(tmp_path, client=None, n=2):
    smp = fakes.make_sample(n_per_date=n)
    r = rn.Gate2Runner(state_dir=tmp_path, sample=smp, env=fakes.FakeEnv(), server=fakes.FakeServer(), probe=fakes.FakeProbe(), client=client or fx.ScriptedMuse(),
                       clock=fakes.Clock(), sleep=lambda s: None, poll=0, n_draws=100, out=lambda *a, **k: None)
    assert r.run(sample_mod.jobs(smp)) == 0
    return smp


def test_integrity_passes_on_clean_mock_runs_and_catches_a_citation_that_is_not_in_the_prompt(tmp_path):
    run_mock(tmp_path)
    runs = sorted(p.parent for p in (config.state_paths(tmp_path)["runs"]).rglob("result.json"))
    assert runs
    for rd in runs:
        v = integrity.verify_run_dir(rd)
        assert v["n_citations"] >= 6 and v["n_citations_failed"] == 0 and v["json_rule_violation"] is False and v["transport_violation"] is False
    # tamper with one saved final response: a quote that the model was never shown
    rd = runs[0]
    resp = sorted(rd.glob("*_P5_a1_response.json"))[0]          # the final positions come from the synthesis, so its citations are the accepted ones
    doc = json.loads(resp.read_text(encoding="utf-8"))
    obj = json.loads(doc["choices"][0]["message"]["content"])
    first = next(iter(obj["inputs"].values()))
    first["citations"][0]["quote"] = "a sentence that no filing contains at all"
    doc["choices"][0]["message"]["content"] = json.dumps(obj)
    resp.write_text(json.dumps(doc), encoding="utf-8")
    v = integrity.verify_run_dir(rd)
    assert v["n_citations_failed"] >= 1 and "not found verbatim" in v["failed"][0]["why"]


def test_a_failed_call_with_no_recorded_fallback_is_a_violation_a_recorded_one_is_not(tmp_path):
    bad = lambda user, attempt, req: "not json at all"
    run_mock(tmp_path, client=fx.ScriptedMuse(hooks={"P2": bad, "P5": bad}), n=1)
    rd = sorted(p.parent for p in config.state_paths(tmp_path)["runs"].rglob("result.json"))[0]
    v = integrity.verify_run_dir(rd)
    assert v["n_calls_not_ok"] >= 1 and v["fallback_recorded"] is True and v["json_rule_violation"] is False
    res = json.loads((rd / "result.json").read_text(encoding="utf-8"))
    for scope in ("final", "pass1"):                                                       # remove the record of the fallback
        for p in res[scope]["positions"].values():
            p["status"], p["stamps"] = "anchored", []
    (rd / "result.json").write_text(json.dumps(res), encoding="utf-8")
    assert integrity.verify_run_dir(rd)["json_rule_violation"] is True


def test_the_loader_reads_the_runs_and_the_whole_scoring_runs_end_to_end_on_mock_runs(tmp_path):
    smp = run_mock(tmp_path, n=3)
    from rebuild_harness.gate2 import stage2_layer as sl
    sl.write_pfail({sl.job_key(j["date"], j["cik"]): {"status": "ok", "p_fail": 0.05} for j in sample_mod.jobs(smp)}, "m", "s", tmp_path)
    rows, statuses, excl = sc.load_rows(tmp_path)
    assert len(rows) == 6 and statuses == {"ok": 6} and all(r["price"] == fx.PRICE_SENTINEL and r["code"]["iv_p50"] > 0 and r["muse"]["iv_p50"] > 0 and r["code"]["iv"] > 0 and r["muse"]["iv"] > 0 for r in rows)
    assert any(r["family"] == "financial" and r["code"]["growth"] is None and r["code"]["margin"] is not None for r in rows)
    outs = {}
    for r in rows:
        q = {"revenue_growth": 0.05, "operating_margin_change": 0.01, "rote_change_annualised_on_tbv_at_T": 0.01}
        outs[r["key"]] = {"key": r["key"], "quarters": {"q1": q, "q2": q}, "returns": {"3": {"bounds": {b: 0.0 for b in sc.BOUNDS}}}}
    p = tmp_path / "o.jsonl"
    p.write_text("\n".join(json.dumps(v) for v in outs.values()), encoding="utf-8")
    rep = sc.score(tmp_path, p, draws=50)
    assert rep["n_paired"] == 6 and rep["G5"]["passes"] is True and rep["G5"]["leakage_violations"] == 0 and rep["G4"]["passes"] is True
    assert rep["verdict"]["verdict"] in ("PASS", "FAIL", "NOT DECIDED")
    md = sc.render_markdown(rep)
    assert "G1 forecast accuracy" in md and "G5 integrity" in md and "Verdict" in md


# ---- the freeze contents --------------------------------------------------------------------------------------------------------------------

def test_the_freeze_is_written_only_on_confirmation_and_once_and_verify_reports_every_drift(tmp_path):
    assert freeze_content.verify(tmp_path)[0].startswith("no freeze file")
    with pytest.raises(RuntimeError, match="coordinator says so"):
        freeze_content.write(tmp_path, confirm=False)
    assert freeze_content._walk_diff({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "c": 3}, "d": 4}) == ["a.c: frozen '2', now '3'", "d: missing in the freeze"] or \
        freeze_content._walk_diff({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "c": 3}, "d": 4})[0].startswith("a.c")


def test_the_freeze_lifecycle_write_once_verify_and_every_drift_is_named(tmp_path, monkeypatch):
    from rebuild_harness.gate2 import server
    fake_inputs = {"fingerprint": {"store": {"n_files": 1}}, "full": {"store": {"tree_sha256": "x"}}}
    monkeypatch.setattr(freeze_content, "inputs_section", lambda full=False, gate1b_freeze=None: fake_inputs if full else {"fingerprint": fake_inputs["fingerprint"]})
    fake_stage2 = {"layers": {"V1": "mean"}, "survival_models": {"sha256": "m"}, "survival_pfail": {"sha256": "p"}}
    monkeypatch.setattr(freeze_content, "stage2_section", lambda state_dir=None: fake_stage2)
    from rebuild_harness.gate2.tests.test_sample_gpu_server import fake_cfg
    cfg, line = fake_cfg(tmp_path)
    server.record_pins(cfg, tmp_path)
    with pytest.raises(RuntimeError, match="no sample file"):
        freeze_content.write(tmp_path, confirm=True, cfg=cfg, hash_model=False, build_cmd=line)
    monkeypatch.setattr(freeze_content, "stage2_section", lambda state_dir=None: {"survival_models": None, "survival_pfail": None})
    sample_mod.write_once(sample_mod.sample_path(tmp_path), {"dates": ["d"], "entries": {"d": []}, "seed": config.SEED})
    with pytest.raises(RuntimeError, match="no Stage 2 survival"):
        freeze_content.write(tmp_path, confirm=True, cfg=cfg, hash_model=False, build_cmd=line)
    monkeypatch.setattr(freeze_content, "stage2_section", lambda state_dir=None: fake_stage2)
    (sample_mod.sample_path(tmp_path)).unlink()
    (sample_mod.sample_path(tmp_path).with_name("sample.json.sha256")).unlink()
    sample_mod.write_once(sample_mod.sample_path(tmp_path), {"dates": ["d"], "entries": {"d": []}, "seed": config.SEED})
    doc = freeze_content.write(tmp_path, confirm=True, cfg=cfg, hash_model=False, build_cmd=line)
    for k in ("engine", "muse", "code", "stage2", "inputs", "seeds", "sample", "packages"):
        assert k in doc
    m = doc["muse"]
    assert m["context"] == 32768 and m["server"]["window"] == 32768 and m["server"]["pinned_window"] == 98304 and m["reasoning_prefix"] == "Reasoning strength: xhigh\n"
    assert len(m["system_message_sha256"]) == 64 and "prompt_set" in m["prompt_template_hashes"] and m["model"]["sha256"] == cfg["model_sha256"] and m["drafter"]["sha256"] == cfg["drafter_sha256"]
    assert m["llama_cpp"]["build"] == "b11272" and m["request_fields"] == ["model", "messages", "stream", "max_tokens", "seed", "response_format"]   # Addendum AD R4
    with pytest.raises(RuntimeError, match="written once"):
        freeze_content.write(tmp_path, confirm=True, cfg=cfg, hash_model=False, build_cmd=line)
    assert freeze_content.verify(tmp_path, cfg=cfg, build_cmd=line) == []
    monkeypatch.setattr(config, "MAX_TOKENS", 8192)                                       # a change of what the run does after the freeze is named
    probs = freeze_content.verify(tmp_path, cfg=cfg, build_cmd=line)
    assert any("muse.max_tokens_cap" in p for p in probs)
    monkeypatch.setattr(config, "MAX_TOKENS", 16384)
    fake_stage2["survival_pfail"] = {"sha256": "changed"}                                  # a Stage 2 probability file that changed after the freeze is named
    assert any(p.startswith("stage2.survival_pfail.sha256") for p in freeze_content.verify(tmp_path, cfg=cfg, build_cmd=line))
    fake_stage2["survival_pfail"] = {"sha256": "p"}
    fake_inputs["fingerprint"]["store"]["n_files"] = 2                                       # an input tree that grew is named
    assert any(p.startswith("inputs.fingerprint.store.n_files") for p in freeze_content.verify(tmp_path, cfg=cfg, build_cmd=line))
    fake_inputs["fingerprint"]["store"]["n_files"] = 1
    monkeypatch.setattr(freeze_content, "CODE_GLOBS", freeze_content.CODE_GLOBS + ("README.md",))
    assert any(p.startswith("code.README.md") for p in freeze_content.verify(tmp_path, cfg=cfg, build_cmd=line))


def test_the_engine_section_proves_the_engine_files_equal_the_frozen_commit():
    s = freeze_content.engine_section()
    assert s["commit"].startswith("c7d7a4f") and set(s["files_sha256"]) >= {"valuation/gate1.py", "valuation/engine_operating.py", "valuation/common.py"}
    assert s["every_file_equals_the_file_at_the_commit"] is True and s["files_that_differ"] == []


def test_the_code_and_seed_sections_name_what_the_registration_freezes():
    code = freeze_content.code_section()
    assert any(k.startswith("valuation/muse/prompts/") for k in code) and "rebuild_harness/gate2/runner.py" in code
    seeds = freeze_content.seeds_section()
    assert seeds["sample_seed"] == 20261007 and "seed_for" in seeds["engine_draw_seed_rule"] and seeds["per_date"] == 120


def test_g1_scores_the_margin_and_rote_as_year_on_year_changes_addendum_o2():
    """Coordinator audit (Addendum AD): the margin forecast enters as (year-1 P50 - base-year margin), the outcome as (quarter margin - same quarter a year earlier)."""
    row = {"value": None}
    pi = {"key": "k", "family": "operating", "cik": "1",
          "muse": {"margin": {"p10": 0.10, "p50": 0.13, "p90": 0.16}, "margin_base": 0.12, "growth": None},
          "code": {"margin": {"p10": 0.09, "p50": 0.12, "p90": 0.15}, "margin_base": 0.12, "growth": None}}
    outs = {"k": {"quarters": {"q1": {"operating_margin": 0.30, "operating_margin_change": 0.01}}}}
    pairs, _ = sc.paired_errors([pi], outs, "margin")
    assert pairs[0]["muse_err"] == pytest.approx(0.0) and pairs[0]["code_err"] == pytest.approx(0.01)   # levels (0.13 vs 0.30) would mislead
    assert sc._fc(dict(pi["muse"], margin_base=None), "margin") is None                                # no base, no margin forecast
    v = {"revenue": 110.0, "operating_income": 15.0, "net_income": 6.0}
    q = oe.quarter_measures({"period_end": "2025-09-30", "filed": "2025-11-05", "values": v,
                             "prior_year": {"revenue": 100.0, "operating_income": 12.0, "net_income": 5.0}}, "financial", 100.0)
    assert q["operating_margin_change"] == pytest.approx(15 / 110 - 0.12) and q["rote_change_annualised_on_tbv_at_T"] == pytest.approx(0.04)


# ---- Addendum AH: the fiscal-year-1 outcome ---------------------------------------------------------------------------------------------------

class AnnualPit:
    """annual_reports filed strictly before asof, as the engines' CompanyPIT holds them."""
    def __init__(self, reports, asof):
        self.annual_reports = [a for a in reports if a[1] < asof]


def annual_world(reports, states):
    """states: {base period: build_state dict}; build reads the latest report the pit holds."""
    pit_at = lambda cik, d: AnnualPit(reports, d)
    build = lambda p: states.get(max((a[0] for a in p.annual_reports), default=None), {})
    return pit_at, build


REPORTS = [("2024-12-31", "2025-02-20", "A1", "10-K"), ("2025-12-31", "2026-02-19", "A2", "10-K"), ("2025-12-31", "2026-05-01", "A3", "10-K/A")]
STATES = {"2024-12-31": {"base_period": "2024-12-31", "revenue": 100.0, "op_margin": 0.10, "rote_latest": 0.12},
          "2025-12-31": {"base_period": "2025-12-31", "revenue": 112.0, "op_margin": 0.10, "rote_latest": 0.0}}


def test_the_annual_outcome_is_year_one_against_the_base_year_known_at_T_first_filed():
    pit_at, build = annual_world(REPORTS, STATES)
    a = oe.annual_outcomes(pit_at, build, "1", "2025-10-31", "2026-06-30")
    assert a["status"] == "ok" and a["base_period"] == "2024-12-31" and a["year1_period"] == "2025-12-31" and a["year1_filed"] == "2026-02-19"
    assert a["revenue_growth"] == pytest.approx(0.12) and a["operating_margin_change"] == 0.0 and a["rote_change"] == pytest.approx(-0.12)   # 0.0 is a value
    seen = []
    oe.annual_outcomes(lambda c, d: seen.append(d) or AnnualPit(REPORTS, d), build, "1", "2025-10-31", "2026-06-30")
    assert "2026-02-20" in seen                                                         # the day after the first filing, before the 10-K/A


def test_a_year_one_not_filed_or_a_fiscal_year_change_has_no_outcome_and_says_why():
    pit_at, build = annual_world(REPORTS, STATES)
    assert oe.annual_outcomes(pit_at, build, "1", "2025-10-31", "2026-02-01")["status"] == "year1_not_filed_by_scoring_date"
    assert oe.annual_outcomes(pit_at, build, "1", "2025-01-15", "2026-06-30")["status"] == "no_base_year_at_T"
    short = [REPORTS[0], ("2025-06-30", "2025-09-01", "B", "10-KT")]
    pa, bd = annual_world(short, {"2024-12-31": STATES["2024-12-31"], "2025-06-30": {"base_period": "2025-06-30"}})
    a = oe.annual_outcomes(pa, bd, "1", "2025-03-31", "2026-06-30")
    assert a["status"] == "fiscal_year_change" and a["revenue_growth"] is None


def test_company_outcomes_records_the_annual_outcome_and_an_error_as_itself():
    job = {"cik": "1", "date": "2025-10-31", "ticker": "AAA", "family": "operating"}
    o = oe.company_outcomes(FakePit([]), job, "2025-11-01", annual_of=lambda j: {"status": "ok", "revenue_growth": 0.1})
    assert o["annual"]["revenue_growth"] == 0.1
    o = oe.company_outcomes(FakePit([]), job, "2025-11-01", annual_of=lambda j: 1 / 0)
    assert o["annual"]["status"].startswith("error: ZeroDivisionError")
    assert "annual" not in oe.company_outcomes(FakePit([]), job, "2025-11-01")


def test_addendum_aj3_a_failed_pass1_call_is_handled_by_the_designed_paths_and_an_unhandled_one_is_not():
    pos = lambda **kw: {"pass1": {"positions": {n: {"status": s, "source": src} for n, (s, src) in kw.items()}}}
    extras_only = dict(pos(g1=("anchored", "P1")), calls=[{"call": "P2", "ok": False, "issues": [{"code": "quote", "input": None}]}])
    reanchored = dict(pos(g1=("anchored", "P5")), calls=[{"call": "P1", "ok": False, "issues": [{"code": "quote", "input": "g1"}]}])
    unanchored = dict(pos(g1=("unanchored", "P1")), calls=[{"call": "P1", "ok": False, "issues": [{"code": "quote", "input": "g1"}]}])
    kept_bad = dict(pos(g1=("anchored", "P1")), calls=[{"call": "P1", "ok": False, "issues": [{"code": "quote", "input": "g1"}]}])
    assert integrity.fallback_recorded(extras_only) and integrity.fallback_recorded(reanchored) and integrity.fallback_recorded(unanchored)
    assert not integrity.fallback_recorded(kept_bad)                         # a failed entry that still stands as the call's own position: a violation


def test_addendum_aj5_a_quote_verbatim_in_another_part_is_a_part_label_error_and_a_quote_found_nowhere_still_fails():
    from valuation.muse.checkers import Evidence
    d = "[D1] 10-K item 1, filed 2026-02-20\nWe write insurance.\n[D3] 8-K Item 2.02 earnings release, filed 2026-02-04\nIn Personal Lines, retention is strong.\n"
    ev = Evidence({"D": d})
    assert integrity._other_part({"section": "D1", "quote": "In Personal Lines, retention is strong."}, ev) == "D3"
    assert integrity._other_part({"section": "D1", "quote": "A sentence in no filing."}, ev) is None
    assert integrity._other_part({"section": "D", "quote": "In Personal Lines, retention is strong."}, ev) is None

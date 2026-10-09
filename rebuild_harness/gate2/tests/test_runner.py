"""The gate-2 runner with a mock model: checkpoint and resume, the pause switch, the GPU wait, transport failures, the terminal statuses, the masked control, the pilot report and seal.
No GPU, no model, no server and no network."""
import json
from pathlib import Path

import pytest

from rebuild_harness.gate2 import config, guard, runner as rn
from rebuild_harness.gate2 import sample as sample_mod
from rebuild_harness.gate2.tests import fakes
from valuation.muse.runner import MuseTransportError
from valuation.muse.tests import fixtures as fx


def make(tmp_path, *, client=None, env=None, probe=None, server=None, sleep=None, pause_also=(), freeze=lambda: [], retry_errors=False, **kw):
    smp = fakes.make_sample(**kw)
    srv = server or fakes.FakeServer()
    sleeps = []
    r = rn.Gate2Runner(state_dir=tmp_path, sample=smp, env=env or fakes.FakeEnv(), server=srv, probe=probe or fakes.FakeProbe(), client=client or fx.ScriptedMuse(),
                       pause_files=pause_also, clock=fakes.Clock(), sleep=sleep or (lambda s: sleeps.append(s)), poll=0, n_draws=100, freeze_problems=freeze,
                       retry_errors=retry_errors, out=lambda *_a, **_k: None)
    r._sleeps = sleeps
    return r, smp, srv


def events(tmp_path):
    p = config.state_paths(tmp_path)["events"]
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def progress(tmp_path):
    p = config.state_paths(tmp_path)["progress"]
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_a_full_run_checkpoints_every_company_and_writes_every_request_and_response(tmp_path):
    r, smp, srv = make(tmp_path)
    jobs = sample_mod.jobs(smp)
    assert r.run(jobs) == 0
    prog = progress(tmp_path)
    assert [p["key"] for p in prog] == [rn.job_key(j) for j in jobs] and all(p["status"] == "ok" for p in prog)
    for p in prog:
        d = config.state_paths(tmp_path)["root"] / p["run_dir"]
        assert d.name == "a01" and (d / "result.json").exists() and (d / "job.json").exists() and (d / "calls.jsonl").exists() and (d / "pack.json").exists()
        reqs, resps = sorted(d.glob("*_request.json")), sorted(d.glob("*_response.json"))
        assert len(reqs) == len(resps) >= 5                       # P1-P4 (P3 for non-financials), P5, P6: a request and a response each
        job = json.loads((d / "job.json").read_text(encoding="utf-8"))
        assert job["wall_seconds"] > 0 and job["timing"]["n_calls"] >= 5 and job["price_info"]["price"] == fx.PRICE_SENTINEL
        assert p["wall_seconds"] > 0 and p["n_calls"] >= 5 and p["integrity"]["n_citations_failed"] == 0
    assert srv.starts == 1 and srv.stops == 1                     # started when the card was free, stopped when the run ended


def test_the_code_arm_and_the_muse_arm_come_from_the_same_run_on_the_same_engine(tmp_path):
    r, smp, _ = make(tmp_path, n_per_date=1)
    r.run(sample_mod.jobs(smp))
    p = progress(tmp_path)[0]
    res = json.loads((config.state_paths(tmp_path)["root"] / p["run_dir"] / "result.json").read_text(encoding="utf-8"))
    assert res["code_only"]["iv_per_share"]["p50"] > 0 and res["final"]["iv_per_share"]["p50"] > 0
    assert res["final"]["iv_per_share"]["p50"] == pytest.approx(res["code_only"]["iv_per_share"]["p50"], rel=1e-9)     # an all-P50 mock model reproduces the prior


def test_resume_skips_what_is_done_and_a_crash_leaves_the_earlier_companies_checkpointed(tmp_path):
    class Crash(BaseException):
        pass

    class Dies(fx.ScriptedMuse):
        def chat(self, request):
            if len(self.requests) >= 8:                           # the first company needs about 6 calls: the second dies in its first calls
                raise Crash()
            return super().chat(request)
    r, smp, _ = make(tmp_path, client=Dies())
    jobs = sample_mod.jobs(smp)
    with pytest.raises(Crash):
        r.run(jobs)
    prog = progress(tmp_path)
    assert len(prog) == 1 and prog[0]["key"] == rn.job_key(jobs[0])                 # checkpointed after the first company
    r2, _, _ = make(tmp_path, client=fx.ScriptedMuse())
    assert r2.run(jobs) == 0
    prog = progress(tmp_path)
    assert [p["key"] for p in prog] == [rn.job_key(j) for j in jobs]                # the rest ran, the first did not run again
    second = [p for p in prog if p["key"] == rn.job_key(jobs[1])][0]
    assert second["attempt"] == 2                                                     # the partial folder stays; the new attempt has its own
    root = config.state_paths(tmp_path)["runs"] / jobs[1]["date"] / rn.job_key(jobs[1])
    assert sorted(x.name for x in root.iterdir()) == ["a01", "a02"] and any(root.joinpath("a01").glob("*_request.json"))


def test_a_second_runner_exits_at_once_while_the_first_holds_the_lock(tmp_path):
    h = rn.acquire_lock(config.state_paths(tmp_path)["lock"])
    assert h is not None
    r, smp, _ = make(tmp_path)
    assert r.run(sample_mod.jobs(smp)) == 0 and progress(tmp_path) == []
    h.close()


def test_the_pause_switch_stops_the_run_between_companies_and_the_server_is_stopped(tmp_path):
    pause = config.state_paths(tmp_path)["pause"]
    state = {"jobs_seen": 0}

    class Env2(fakes.FakeEnv):
        def company_inputs(self, job):
            state["jobs_seen"] += 1
            if state["jobs_seen"] == 1:
                pause.parent.mkdir(parents=True, exist_ok=True)
                pause.write_text("pause")                         # the operator pauses while company 1 is running
            return super().company_inputs(job)
    waits = []

    def sleep(s):
        waits.append(state["jobs_seen"])
        if len(waits) == 3:
            pause.replace(pause.with_name("PAUSE.removed"))      # the operator resumes (moved, not deleted)
    r, smp, srv = make(tmp_path, env=Env2(), sleep=sleep)
    jobs = sample_mod.jobs(smp)
    assert r.run(jobs) == 0
    prog = progress(tmp_path)
    assert len(prog) == len(jobs)                                                       # nothing skipped
    assert waits and all(w == 1 for w in waits)                                         # while paused, company 2 had not started
    assert srv.stops >= 2 and srv.starts >= 2                                           # stopped for the pause, restarted after it
    assert any(e["event"] == "waiting" and "paused" in e["why"] for e in events(tmp_path))


def test_a_second_pause_file_is_honoured_when_named_and_never_touched(tmp_path):
    other = tmp_path / "elsewhere" / "DEPTH_PAUSED"
    other.parent.mkdir()
    other.write_text("x")
    polls = []

    def sleep(s):
        polls.append(1)
        if len(polls) == 2:
            other.replace(other.with_name("DEPTH_PAUSED.moved"))
    r, smp, _ = make(tmp_path, sleep=sleep, pause_also=[other], n_per_date=1)
    assert r.run(sample_mod.jobs(smp)) == 0 and len(polls) >= 2 and len(progress(tmp_path)) == 2


def test_it_waits_and_never_skips_while_another_program_uses_the_gpu(tmp_path):
    calls = {"n": 0}

    def scenario(n):                                           # the first four looks: a game; then free
        return "app" if n <= 4 else None
    probe = fakes.FakeProbe(scenario)
    r, smp, srv = make(tmp_path, probe=probe, n_per_date=1)
    jobs = sample_mod.jobs(smp)
    assert r.run(jobs) == 0
    assert len(progress(tmp_path)) == len(jobs) and srv.starts >= 1
    assert any(e["event"] == "waiting" and "another process is using the GPU" in e["why"] for e in events(tmp_path))
    assert len(r._sleeps) >= 3


@pytest.mark.parametrize("mode,text", [("ollama", "Ollama has a model loaded"), ("vram", "VRAM in use with nothing of ours loaded")])
def test_foreign_ollama_models_and_gaming_memory_make_it_wait(tmp_path, mode, text):
    probe = fakes.FakeProbe(lambda n: mode if n <= 2 else None)
    r, smp, _ = make(tmp_path, probe=probe, n_per_date=1)
    assert r.run(sample_mod.jobs(smp)) == 0
    assert any(e["event"] == "waiting" and text in e["why"] for e in events(tmp_path))


def test_a_game_that_starts_while_our_server_runs_stops_the_server_and_the_run_resumes_later(tmp_path):
    state = {"first_done": False}

    class Env2(fakes.FakeEnv):
        def company_inputs(self, job):
            if self.calls:
                state["first_done"] = True
            return super().company_inputs(job)

    def scenario(n):
        # call numbers: each ensure_ready/check looks once or twice; make the card busy right after the first company finished
        return "vram" if (state["first_done"] and n % 7 in (1, 2, 3)) and not state.get("freed") else None
    probe = fakes.FakeProbe(scenario)

    def sleep(s):
        state["freed"] = True
    r, smp, srv = make(tmp_path, env=Env2(), probe=probe, sleep=sleep, n_per_date=2)
    jobs = sample_mod.jobs(smp)
    assert r.run(jobs) == 0
    assert len(progress(tmp_path)) == len(jobs)


def test_a_transport_failure_is_never_a_fallback_the_same_company_runs_again_in_a_new_attempt(tmp_path):
    client = fakes.Flaky(fx.ScriptedMuse(), fail_on={2})          # the second request of the first company cannot reach the server
    r, smp, srv = make(tmp_path, client=client, n_per_date=1)
    jobs = sample_mod.jobs(smp)
    assert r.run(jobs) == 0
    prog = progress(tmp_path)
    assert [p["key"] for p in prog] == [rn.job_key(j) for j in jobs]
    first = prog[0]
    assert first["status"] == "ok" and first["attempt"] == 2 and first["transport_retries_before"] == 1
    res = json.loads((config.state_paths(tmp_path)["root"] / first["run_dir"] / "result.json").read_text(encoding="utf-8"))
    assert res["final"]["unanchored_inputs"] == []                # a clean run, not prior values standing in for a lost answer
    assert srv.stops >= 2                                         # stopped for the failure and at the end
    ev = [e["event"] for e in events(tmp_path)]
    assert "transport_failure" in ev
    stale = config.state_paths(tmp_path)["runs"] / jobs[0]["date"] / rn.job_key(jobs[0]) / "a01"
    assert (stale / "result.json").exists() and json.loads((stale / "result.json").read_text(encoding="utf-8"))["status"] == "model_unavailable"


def test_three_transport_failures_in_a_row_halt_the_run_with_exit_3_and_record_nothing(tmp_path):
    client = fakes.Flaky(fx.ScriptedMuse(), fail_on=set(range(1, 100)))
    r, smp, srv = make(tmp_path, client=client, n_per_date=1)
    assert r.run(sample_mod.jobs(smp)) == 3
    assert progress(tmp_path) == []                               # not recorded: a fresh process retries it
    assert sum(1 for e in events(tmp_path) if e["event"] == "transport_failure") == config.MAX_CONSECUTIVE_TRANSPORT_FAILURES
    assert any(e["event"] == "halt" and e["code"] == 3 for e in events(tmp_path))
    # a fresh process retries the same company and finishes it
    r2, _, _ = make(tmp_path, client=fx.ScriptedMuse(), n_per_date=1)
    assert r2.run(sample_mod.jobs(r2.sample)) == 0 and len(progress(tmp_path)) == 2
    assert progress(tmp_path)[0]["attempt"] == config.MAX_CONSECUTIVE_TRANSPORT_FAILURES + 1


def test_a_prompt_with_no_room_for_an_answer_is_a_final_recorded_context_overflow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONTEXT", 2000)
    monkeypatch.setattr(guard, "config", config)

    class Tiny(guard.ContextGuardClient):
        def __init__(self, inner, **kw):
            super().__init__(inner, window=2000, **kw)
    monkeypatch.setattr(guard, "ContextGuardClient", Tiny)
    r, smp, _ = make(tmp_path, n_per_date=1)
    assert r.run(sample_mod.jobs(smp)) == 0
    prog = progress(tmp_path)
    assert prog and all(p["status"] == "context_overflow" for p in prog)                # final, not retried
    assert not any(e["event"] == "transport_failure" for e in events(tmp_path))


def test_an_http_4xx_is_a_final_recorded_request_rejected(tmp_path):
    client = fakes.Flaky(fx.ScriptedMuse(), fail_on={1}, exc=MuseTransportError("HTTP 400 from http://127.0.0.1:8080: b'exceed_context_size_error'"))
    r, smp, _ = make(tmp_path, client=client, n_per_date=1)
    assert r.run(sample_mod.jobs(smp)) == 0
    assert progress(tmp_path)[0]["status"] == "request_rejected"


def test_a_refusal_and_an_exception_are_recorded_and_the_run_goes_on(tmp_path):
    env = fakes.FakeEnv(refuse={"0000000001"}, boom={"0000000002"})
    r, smp, _ = make(tmp_path, env=env, n_per_date=3)
    jobs = sample_mod.jobs(smp)
    assert r.run(jobs) == 0
    by = {p["key"]: p for p in progress(tmp_path)}
    assert by[rn.job_key(jobs[0])]["status"] == "refused" and by[rn.job_key(jobs[1])]["status"] == "error" and by[rn.job_key(jobs[2])]["status"] == "ok"
    err = json.loads((config.state_paths(tmp_path)["root"] / by[rn.job_key(jobs[1])]["run_dir"] / "job.json").read_text(encoding="utf-8"))
    assert "synthetic failure" in err["error"]["message"] and "Traceback" in err["error"]["trace"]
    r2, _, _ = make(tmp_path, n_per_date=3)
    r2.run(jobs)
    assert len(progress(tmp_path)) == len(jobs)                                          # the error is final unless asked
    r3, _, _ = make(tmp_path, n_per_date=3, retry_errors=True)
    r3.run(jobs)
    assert [p["status"] for p in progress(tmp_path) if p["key"] == rn.job_key(jobs[1])] == ["error", "ok"]


def test_an_unfrozen_run_is_refused_before_anything_runs(tmp_path):
    r, smp, srv = make(tmp_path, freeze=lambda: ["no freeze file at x"])
    assert r.run(sample_mod.jobs(smp)) == 5
    assert progress(tmp_path) == [] and srv.starts == 0


def test_a_server_that_cannot_start_for_a_permanent_reason_halts_the_run(tmp_path):
    srv = fakes.FakeServer()
    srv.refuse_start = "the pins record is missing"
    r, smp, _ = make(tmp_path, server=srv)
    assert r.run(sample_mod.jobs(smp)) == 6 and progress(tmp_path) == []


def test_the_masked_control_hides_the_name_and_ticker_and_has_its_own_folder_and_keys(tmp_path):
    client = fx.ScriptedMuse()
    r, smp, _ = make(tmp_path, client=client, n_per_date=1)
    jobs = sample_mod.jobs(smp)[:1]
    assert r.run(jobs, masked=True) == 0
    p = progress(tmp_path)[0]
    assert p["masked"] is True and p["key"].startswith("M_") and "runs_masked" in p["run_dir"]
    text = json.dumps(client.requests)
    assert "Synthetic Co" not in text and "(T1)" not in text and "Company X" in text
    r2, _, _ = make(tmp_path, n_per_date=1)
    assert r2.run(jobs) == 0 and len(progress(tmp_path)) == 2                              # the unmasked run of the same company-date is still to do


def test_the_pilot_report_is_times_and_counts_only_and_the_outputs_are_sealed(tmp_path):
    smp = fakes.make_sample(n_per_date=12, dates=("2025-10-31", "2026-04-30"))
    sd = sample_mod.sample_path(tmp_path)
    sample_mod.write_once(sd, dict(smp, rule="test", universe_counts={}, allocation={}))
    pilot = sample_mod.pilot_jobs(smp)
    assert len(pilot) == 10 and {j["date"] for j in pilot} == {"2025-10-31"}
    # run the pilot companies on a date the fixtures' filings precede
    class Env2(fakes.FakeEnv):
        def company_inputs(self, job):
            return super().company_inputs(dict(job, date="2026-04-30"))
    r, _, _ = make(tmp_path, env=Env2(), n_per_date=12, dates=("2025-10-31", "2026-04-30"))
    assert r.run(pilot, label="pilot") == 0
    rep = rn.pilot_report(tmp_path)
    assert rep["n_finished"] == 10 and rep["mean_seconds"] > 0 and rep["estimated_gpu_days_for_the_sample"] is not None
    assert set(rep) >= {"mean_seconds", "median_seconds", "p90_seconds", "mean_calls", "max_prompt_tokens", "n_length_cut", "technical_outcomes"}
    text = json.dumps(rep)
    assert "iv_per_share" not in text and "percentile" not in text                        # no output is summarised
    seal = rn.seal_pilot(tmp_path)
    doc = json.loads(seal.read_text(encoding="utf-8"))
    assert doc["n_files"] > 10 * 12 and len(doc["manifest_sha256"]) == 64
    assert rn.seal_pilot(tmp_path) == seal                                                  # sealed once


def test_the_repeat_control_changes_only_the_model_seed(tmp_path):
    """Addendum AD R8: the second model seed reaches every request; the engine draws keep their seed (11 in the fakes)."""
    c1, c2 = fx.ScriptedMuse(), fx.ScriptedMuse()
    r1, smp, _ = make(tmp_path / "a", client=c1, n_per_date=1)
    jobs = sample_mod.jobs(smp)[:1]
    assert r1.run(jobs) == 0
    r2, _, _ = make(tmp_path / "b", client=c2, n_per_date=1)
    r2.llm_seed_offset = config.REPEAT_LLM_SEED_OFFSET
    assert r2.run(jobs) == 0
    assert {q.get("seed") for q in c1.requests} == {11} and {q.get("seed") for q in c2.requests} == {12}
    j2 = json.loads(next((tmp_path / "b").rglob("job.json")).read_text(encoding="utf-8"))
    assert j2["seed"] == 11 and j2["llm_seed"] == 12


def test_repeat_mode_and_scored_modes_refuse_each_others_state_folder(tmp_path):
    assert rn.main(["--mode", "repeat", "--state-dir", str(tmp_path)]) == 2            # no marker: a scored folder
    (tmp_path / config.REPEAT_MARKER).write_text("R8", encoding="utf-8")
    for mode in ("full", "pilot", "masked"):
        assert rn.main(["--mode", mode, "--state-dir", str(tmp_path)]) == 2

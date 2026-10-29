"""M-ERR and M-REC: the runner against a stub Ollama server on an ephemeral local port (no GPU, no Ollama, no model).

The stub answers POST /api/generate per task (the task is read from the rendered prompt's "TASK <id>." line) from a script of actions;
when a task's script is used up it answers a valid reply for that task."""
import hashlib
import json
import re
import shutil
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from qwen_c import contract, runner, tasks

import ollama_raw  # noqa: E402  (on sys.path through qwen_c.runner)
import ops  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures_b"
THINKING = "THINKING-TEXT-MUST-NOT-REACH-ANALYSIS"
TASK_RE = re.compile(r"TASK (\w+)\. ")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def valid_reply(task):
    claim = {"claim": "Revenue rose to $1,200 million in 2025.", "fact_ids": ["P1"], "quotes": ["Revenue rose to $1,200 million in 2025"],
             "numbers": ["$1,200 million", "2025"], "confidence_basis": "stated in P1"}
    claim.update({"risks": {"risk_type": "other"}, "thesis_change": {"point": "G1", "change_type": "unchanged"},
                  "unresolved_questions": {"settled_by": "the next 10-Q"}}.get(task, {}))
    bad = {"claim": "Margin was 99.9%.", "fact_ids": ["P1"], "quotes": [], "numbers": ["99.9%"], "confidence_basis": "inferred"}
    bad.update({k: v for k, v in claim.items() if k not in bad})
    return {"task": task, "claims": [claim, bad], "unknowns": ["nothing on segments"]}


def completion(obj):
    return f"{THINKING}\n</think>\n\nHere it is.\n```json\n{json.dumps(obj)}\n```"


SHOW = {"parameters": "temperature                    0.6\ntop_p                          0.95\ntop_k                          20",
        "details": {"family": "qwen3"}, "modified_at": "2026-10-17T00:00:00Z"}


class Stub(BaseHTTPRequestHandler):
    script = {}
    posts = []
    loaded = []                       # what /api/ps lists; None answers 500
    show = SHOW                       # what /api/show answers; None answers 404
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def do_GET(self):
        if self.path.endswith("/api/ps"):
            if Stub.loaded is None:
                self._send(500, {"error": "ps failed"})
            else:
                self._send(200, {"models": [{"name": n, "model": n} for n in Stub.loaded]})
            return
        self._send(200, {"version": "0.40.3"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/api/show"):
            with Stub.lock:
                Stub.posts.append({"task": "_show", "req": req})
            self._send(*((200, Stub.show) if Stub.show is not None else (404, {"error": "model not found"})))
            return
        m = TASK_RE.search(req.get("prompt", ""))
        task = m.group(1) if m else None
        with Stub.lock:
            Stub.posts.append({"task": task, "req": req})
            todo = Stub.script.get(task) or []
            action = todo.pop(0) if todo else "valid"
        ok = {"model": req["model"], "done": True, "done_reason": "stop", "prompt_eval_count": 900, "eval_count": 100}
        if action == "valid":
            self._send(200, {**ok, "response": completion(valid_reply(task))})
        elif action == "no_json":
            self._send(200, {**ok, "response": f"{THINKING}\n</think>\n\nI cannot answer in JSON."})
        elif action == "bad_shape":
            r = valid_reply(task)
            del r["claims"][0]["confidence_basis"]
            self._send(200, {**ok, "response": completion(r)})
        elif action == "two_blocks":
            self._send(200, {**ok, "response": completion(valid_reply(task)) + "\n```json\n{}\n```"})
        elif action == "bare_json":
            self._send(200, {**ok, "response": f"{THINKING}\n</think>\n\n" + json.dumps(valid_reply(task))})
        elif action == "500":
            self._send(500, {"error": "llama runner process has terminated: cudaMalloc failed: out of memory"})
        elif action == "404":
            self._send(404, {"error": "model not found"})
        elif action == "drop":
            self.close_connection = True
            self.connection.close()
        elif action == "sleep":
            time.sleep(1.5)
            self._send(200, {**ok, "response": completion(valid_reply(task))})
        elif action == "overflow":
            self._send(200, {**ok, "prompt_eval_count": req["options"]["num_ctx"], "eval_count": 1,
                             "response": completion(valid_reply(task))})
        elif action == "at_the_wall":                          # used == num_ctx - 1: ollama_raw's guard (> num_ctx) does not see it
            self._send(200, {**ok, "prompt_eval_count": req["options"]["num_ctx"] - 2, "eval_count": 1,
                             "response": completion(valid_reply(task))})
        elif action == "no_counts":
            self._send(200, {k: v for k, v in ok.items() if k != "prompt_eval_count"} | {"response": completion(valid_reply(task))})
        elif action == "error_200":
            self._send(200, {"model": req["model"], "error": "llama runner process has terminated", "response": "", "done": False})
        elif action == "empty_200":
            self._send(200, {"model": req["model"], "response": "", "done": False})
        elif action == "cut_at_length":
            self._send(200, {**ok, "done_reason": "length", "response": f"{THINKING}\n</think>\n\n```json\n{{\"task\": \"{task}\", "})
        elif action == "empty_reply":
            self._send(200, {**ok, "response": completion({"task": task, "claims": [], "unknowns": []})})
        elif action == "fake_point":
            r = valid_reply(task)
            r["claims"][0]["point"] = "FAKE99"
            self._send(200, {**ok, "response": completion(r)})
        else:
            raise AssertionError(action)


@pytest.fixture
def env(monkeypatch, tmp_path):
    Stub.script, Stub.posts, Stub.loaded, Stub.show = {}, [], [], SHOW
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/api/chat"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # the suite's autouse fixture blocks urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: opener.open(req, timeout=timeout))
    monkeypatch.setattr(ollama_raw, "_VERSIONS", {})
    monkeypatch.setattr(runner, "M3M_DIR", tmp_path / "m3m")
    monkeypatch.setattr(runner, "git_state", lambda: ("a" * 40, False))
    unloads = []
    monkeypatch.setattr(ops, "wait_unloaded", lambda endpoint, model, **k: (unloads.append((endpoint, model)) or (True, "stub: unloaded")))
    models = tmp_path / "ollama_models"
    man = models / "manifests" / "registry.ollama.ai" / "library" / runner.MODEL / "latest"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"layers": [{"mediaType": "application/vnd.ollama.image.system", "digest": "sha256:" + "9" * 64}]}))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    pk = tmp_path / "packet.json"
    shutil.copyfile(FIX / "packet_acme.json", pk)
    yield {"url": url, "stub": Stub, "unloads": unloads, "packet": pk, "tmp": tmp_path, "model_manifest": man}
    srv.shutdown()
    srv.server_close()


def run(env, **kw):
    return runner.run(env["packet"], url=env["url"], **kw)


def manifest(res):
    return json.loads((Path(res["run_dir"]) / "manifest.json").read_text(encoding="utf-8"))


def analysis(res):
    return json.loads((Path(res["run_dir"]) / "analysis.json").read_text(encoding="utf-8"))


def posts_of(task):
    return [p["req"] for p in Stub.posts if p["task"] == task]


def generate_posts():
    return [p for p in Stub.posts if p["task"] != "_show"]


SENT = [t for t in tasks.TASKS if t != "thesis_change"]


# ---------------------------------------------------------------- the happy path and M-REC

def test_a_clean_run_is_complete_and_every_record_recomputes(env):
    res = run(env)
    assert res["status"] == "complete" and res["incomplete_tasks"] == {}
    d = Path(res["run_dir"])
    man, an = manifest(res), analysis(res)
    assert res["run_id"] == f"ACME_20261029T130000Z_{man['packet']['packet_sha256'][:12]}_1" == d.name
    # packet.json is a byte copy; its canonical sha recomputes
    pk = (d / "packet.json").read_bytes()
    assert sha(pk) == man["packet"]["file_sha256"] == sha(env["packet"].read_bytes())
    assert sha(runner.canonical_bytes(json.loads(pk))) == man["packet"]["packet_sha256"] == an["packet_sha256"]
    # prompts: one per sent task, sha in the manifest, and the very prompt that was POSTed (turn_log's prompt_sha256)
    assert sorted(man["prompts"]) == sorted(f"{t}.txt" for t in SENT)
    for name, h in man["prompts"].items():
        assert sha((d / "prompts" / name).read_bytes()) == h
    for t in SENT:
        (req,) = posts_of(t)
        assert sha(req["prompt"].encode("utf-8")) == man["prompts"][f"{t}.txt"]
        turn = json.loads((d / "turns" / f"{t}_1.json").read_text(encoding="utf-8"))
        assert turn["prompt_sha256"] == man["prompts"][f"{t}.txt"] and turn["system_sha256"] == man["system_sha256"]
        assert turn["template_sha256"] == man["template_sha256"] == ollama_raw.TEMPLATE_SHA256
    # raw records and turn records recompute
    for t, rec in man["tasks"].items():
        for a in rec["attempts"]:
            assert sha((d / a["raw_file"]).read_bytes()) == a["raw_sha256"]
    assert man["turns"] and all(sha((d / p).read_bytes()) == h for p, h in man["turns"].items())
    assert (d / "turns" / "run_hashes.json").exists()
    # analysis and manifest and ledger
    assert sha((d / "analysis.json").read_bytes()) == man["analysis_sha256"]
    (line,) = runner._read_jsonl(runner.M3M_DIR / "ledger.jsonl")
    summary = {"claims": 12, "supported": 6, "unsupported": 6}            # ruling 4.1: six tasks sent, one good and one bad claim each
    assert line == {"run_id": res["run_id"], "ticker": "ACME", "T": "2026-10-29T13:00:00Z", "packet_sha256": man["packet"]["packet_sha256"],
                    "status": "complete", "support_summary": summary, "manifest_sha256": sha((d / "manifest.json").read_bytes())}
    assert an["support_summary"] == res["support_summary"] == summary and res["ledger_appended"] is True
    # rulings 6.3 and 6.4: the server preflights are recorded
    assert man["gpu_preflight"] == {"loaded": []} and man["model"]["show"]["parameters"] == SHOW["parameters"]
    assert man["model"]["show"]["details"] == {"family": "qwen3"} and len(man["model"]["show"]["show_sha256"]) == 64
    assert posts_of("_show") == [{"model": runner.MODEL}]
    # the model serving record recomputes from the Ollama manifest file
    assert man["model"]["manifest_sha256"] == sha(env["model_manifest"].read_bytes())
    assert man["model"]["system_layer_digest"] == "sha256:" + "9" * 64 and man["model"]["tag"] == runner.MODEL
    # the manifest's fixed fields
    assert man["contract"] == "m3m.analysis.v1" and man["prompt_version"] == "m3m.prompt.v2" and man["builder_version"] == "fixture_b.1"
    assert man["ollama_version"] == "0.40.3" and man["kis_halt"] == "not_resolvable_in_rs2"
    assert man["qwen_c"] == {"git_commit": "a" * 40, "dirty": False}
    assert man["options"]["num_ctx"] == 98304 and man["options"]["num_predict"] == 12288 and man["options"]["think"] == "medium"
    assert man["options"]["seeds"] == {t: 1000 + i for i, t in enumerate(tasks.TASKS)} and man["options"]["differs_from_defaults"] == []
    assert man["started_at"] and man["finished_at"] and man["status"] == "complete"
    assert man["tasks"]["thesis_change"]["status"] == "not_applicable_no_prior" and posts_of("thesis_change") == []


def test_the_requests_carry_the_fixed_options_our_system_and_think(env):
    run(env)
    for i, t in enumerate(tasks.TASKS):
        if t == "thesis_change":
            continue
        (req,) = posts_of(t)
        assert req["raw"] is True and req["model"] == runner.MODEL
        assert req["options"] == {"num_ctx": 98304, "num_predict": 12288, "seed": 1000 + i}      # sampling is the Modelfile's
        msgs = tasks.messages(t, json.loads(env["packet"].read_text(encoding="utf-8")))
        assert req["prompt"] == ollama_raw.render_prompt(msgs, None, "medium")
        assert req["prompt"] != ollama_raw.render_prompt(msgs, None, "high") and tasks.SYSTEM in req["prompt"]
        assert "Reasoning effort is set to" not in req["prompt"]          # the pinned template prints no effort line for medium
    first = [p["req"]["prompt"] for p in generate_posts()]
    head = tasks.render_packet(json.loads(env["packet"].read_text(encoding="utf-8")))
    cut = [p.index(head) + len(head) for p in first]
    assert len({p[:c] for p, c in zip(first, cut)}) == 1          # the shared prefix: system and packet are identical for every task


def test_thinking_stays_in_raw_and_never_reaches_analysis(env):
    res = run(env)
    d = Path(res["run_dir"])
    assert THINKING not in (d / "analysis.json").read_text(encoding="utf-8")
    raw = json.loads((d / "raw" / "business_model_1.json").read_text(encoding="utf-8"))
    assert raw["response"]["message"]["thinking"] == THINKING
    assert raw["response"]["eval_count"] == 100 and raw["response"]["done_reason"] == "stop"


def test_the_analysis_carries_the_checks_beside_unedited_claims(env):
    an = analysis(run(env))
    bm = an["tasks"]["business_model"]
    assert bm["status"] == "ok" and [c["support"] for c in bm["claims"]] == ["supported", "number_not_found"]
    assert bm["claims"][1]["claim"] == "Margin was 99.9%." and bm["support_counts"] == {"supported": 1, "number_not_found": 1}
    assert an["contract"] == contract.CONTRACT and "not a verified value" in an["note"]


def test_a_re_run_never_overwrites(env):
    a, b = run(env), run(env)
    assert a["run_id"].endswith("_1") and b["run_id"].endswith("_2") and Path(a["run_dir"]).exists()
    assert len(runner._read_jsonl(runner.M3M_DIR / "ledger.jsonl")) == 2


# ---------------------------------------------------------------- M-ERR

def test_malformed_then_valid_retries_once_with_the_seed_offset_and_the_line(env):
    Stub.script = {"financial_health": ["no_json"]}
    res = run(env)
    assert res["status"] == "complete"
    first, second = posts_of("financial_health")
    assert first["options"]["seed"] == 1001 and second["options"]["seed"] == 1001 + 50000
    assert tasks.RETRY_LINE not in first["prompt"] and tasks.RETRY_LINE in second["prompt"]
    man = manifest(res)
    rec = man["tasks"]["financial_health"]
    assert rec["status"] == "ok" and [a["outcome"] for a in rec["attempts"]] == ["malformed", "ok"]
    assert sha((Path(res["run_dir"]) / "prompts" / "financial_health_retry.txt").read_bytes()) == man["prompts"]["financial_health_retry.txt"]
    assert sha(second["prompt"].encode()) == man["prompts"]["financial_health_retry.txt"]


def test_malformed_twice_is_malformed(env):
    Stub.script = {"risks": ["bad_shape", "two_blocks"]}
    res = run(env)
    assert res["status"] == "analysis_incomplete" and res["incomplete_tasks"] == {"risks": "malformed"}
    rec = analysis(res)["tasks"]["risks"]
    assert rec["status"] == "malformed" and rec["attempts"] == 2 and rec["claims"] == [] and "fenced json blocks" in rec["cause"]
    assert len(posts_of("risks")) == 2


def test_a_bare_json_reply_is_accepted(env):
    Stub.script = {"growth_thesis": ["bare_json"]}
    assert run(env)["status"] == "complete" and len(posts_of("growth_thesis")) == 1


def test_timeout_is_not_retried(env, monkeypatch):
    monkeypatch.setattr(runner, "TASK_TIMEOUT_S", 0.5)
    Stub.script = {"competitive_position": ["sleep"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"competitive_position": "timeout"}
    assert len(posts_of("competitive_position")) == 1 and env["unloads"] == []
    assert manifest(res)["tasks"]["competitive_position"]["attempts"][0]["outcome"] == "timeout"


def test_500_then_valid_waits_for_the_unload_and_retries(env):
    Stub.script = {"business_model": ["500"]}
    res = run(env)
    assert res["status"] == "complete" and env["unloads"] == [(env["url"], runner.MODEL)]
    a1, a2 = posts_of("business_model")
    assert a1["options"]["seed"] == a2["options"]["seed"] == 1000 and a1["prompt"] == a2["prompt"]
    att = manifest(res)["tasks"]["business_model"]["attempts"]
    assert att[0]["outcome"] == "infra_retry" and "cudaMalloc" in att[0]["detail"] and att[0]["wait_unloaded"]["ok"] is True


def test_500_twice_is_infra_error_with_the_cause(env):
    Stub.script = {"business_model": ["500", "500"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"business_model": "infra_error"} and len(env["unloads"]) == 1
    assert "HTTP 500" in analysis(res)["tasks"]["business_model"]["cause"]


def test_a_dropped_connection_is_an_infra_retry(env):
    Stub.script = {"unresolved_questions": ["drop"]}
    res = run(env)
    assert res["status"] == "complete" and len(env["unloads"]) == 1 and len(posts_of("unresolved_questions")) == 2


def test_no_retry_when_the_unload_is_not_confirmed(env, monkeypatch):
    monkeypatch.setattr(ops, "wait_unloaded", lambda endpoint, model, **k: (False, "TIMEOUT after 180s"))
    Stub.script = {"business_model": ["500"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"business_model": "infra_error"} and len(posts_of("business_model")) == 1
    assert "wait_unloaded did not confirm" in analysis(res)["tasks"]["business_model"]["cause"]


def test_a_4xx_is_infra_error_without_retry(env):
    Stub.script = {"business_model": ["404"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"business_model": "infra_error"} and len(posts_of("business_model")) == 1 and env["unloads"] == []


def test_context_overflow_is_not_retried(env):
    Stub.script = {"risks": ["overflow"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"risks": "context_overflow"} and len(posts_of("risks")) == 1
    assert "context_overflow" in analysis(res)["tasks"]["risks"]["cause"]
    assert (Path(res["run_dir"]) / "turns" / "risks_1.json").exists()          # the turn is logged before the guard refuses it


def test_no_task_ok_is_failed_and_still_ledgered(env):
    Stub.script = {t: ["no_json", "no_json"] for t in tasks.TASKS}
    res = run(env)
    assert res["status"] == "failed" and set(res["incomplete_tasks"]) == set(SENT)
    assert runner.read_ledger()[0]["status"] == "failed"


def test_a_crash_mid_run_reads_as_crashed(env, monkeypatch):
    calls, real = [], contract.check_task

    def boom(task, obj, packet, *point_ids):
        calls.append(task)
        if len(calls) == 2:
            raise KeyboardInterrupt                                  # stands in for the process dying mid-run
        return real(task, obj, packet, *point_ids)

    monkeypatch.setattr(contract, "check_task", boom)
    with pytest.raises(KeyboardInterrupt):
        run(env)
    (row,) = runner.read_ledger()
    assert row["status"] == "crashed" and row["ticker"] == "ACME"
    run_dir = runner.M3M_DIR / "runs" / row["run_id"]
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert man["status"] == "running" and "finished_at" not in man
    assert not (runner.M3M_DIR / "ledger.jsonl").exists()


def test_an_unexpected_error_inside_a_task_is_a_status_not_a_raise(env, monkeypatch):
    monkeypatch.setattr(tasks, "RETRY_LINE", None)                   # the retry message cannot be built: a TypeError in the runner
    Stub.script = {"business_model": ["no_json"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"business_model": "infra_error"}
    assert "runner exception: TypeError" in analysis(res)["tasks"]["business_model"]["cause"]


# ---------------------------------------------------------------- refusals and the CLI

def test_a_wrong_packet_is_refused_and_nothing_is_written(env):
    bad = env["tmp"] / "bad.json"
    bad.write_text(json.dumps({"contract": "m3m.packet.v0"}))
    with pytest.raises(runner.RunRefused):
        runner.run(bad, url=env["url"])
    with pytest.raises(runner.RunRefused):
        run(env, think="extreme")
    pk = json.loads(env["packet"].read_text(encoding="utf-8"))
    pk["evidence"].append(dict(pk["evidence"][0]))
    bad.write_text(json.dumps(pk))
    with pytest.raises(runner.RunRefused):
        runner.run(bad, url=env["url"])
    assert not runner.M3M_DIR.exists()


def test_the_cli(env, capsys):
    assert runner.main([str(env["packet"]), "--url", env["url"], "--num-predict", "8192", "--think", "low"]) == 0
    res = json.loads(capsys.readouterr().out)
    man = manifest(res)
    assert man["options"]["num_predict"] == 8192 and man["options"]["think"] == "low"
    assert man["options"]["differs_from_defaults"] == ["num_predict", "think"]
    assert "Reasoning effort is set to low" in generate_posts()[0]["req"]["prompt"]
    bad = env["tmp"] / "bad.json"
    bad.write_text("{")
    assert runner.main([str(bad), "--url", env["url"]]) == 2


def test_git_state_reads_this_worktree():
    commit, dirty = runner.git_state()
    assert commit is None or (re.fullmatch(r"[0-9a-f]{40}", commit) and isinstance(dirty, bool))


# ---------------------------------------------------------------- thesis_change and the prior run

def _packet_at(env, T, name):
    pk = json.loads(env["packet"].read_text(encoding="utf-8"))
    pk["decision_time_utc"] = T
    p = env["tmp"] / name
    p.write_bytes(runner.canonical_bytes(pk))
    return p


def test_thesis_change_is_sent_against_the_newest_prior_run(env):
    early = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    assert early["status"] == "complete"
    Stub.posts.clear()
    late = run(env)
    assert late["status"] == "complete", manifest(late)["tasks"]["thesis_change"]
    (req,) = posts_of("thesis_change")
    assert "as of 2026-05-01T13:00:00Z" in req["prompt"] and "effective after 2026-05-01T13:00:00Z: P2." in req["prompt"]
    assert "G1: Revenue rose to $1,200 million in 2025. (cited P1; code check: supported)" in req["prompt"]
    assert "R1: Revenue rose to $1,200 million in 2025. (cited P1; code check: supported)" in req["prompt"]
    # ruling 3.4: the unsupported prior claims are not points, and their count is stated
    assert "Margin was 99.9%" not in req["prompt"] and "G2:" not in req["prompt"] and "R2:" not in req["prompt"]
    assert "2 that did not pass it are left out" in req["prompt"] and "did not finish" not in req["prompt"]
    man = manifest(late)
    assert man["prior_run"]["run_id"] == early["run_id"] and man["prior_run"]["tasks_used"] == ["growth_thesis", "risks"]
    assert man["prior_run"]["point_ids"] == ["G1", "R1"] and man["prior_run"]["points_left_out"] == 2
    assert man["prior_run"]["tasks_missing"] == {} and man["prior_run"]["ledger_missing"] is False
    assert man["tasks"]["thesis_change"]["seed"] == 1005
    tc = analysis(late)["tasks"]["thesis_change"]
    assert tc["status"] == "ok" and tc["claims"][0]["point"] == "G1" and tc["claims"][0]["change_type"] == "unchanged"
    # ruling 4.3: both reply claims name G1, so R1 is recorded as not addressed (in the analysis and the manifest)
    assert tc["points_not_addressed"] == ["R1"] and man["tasks"]["thesis_change"]["points_not_addressed"] == ["R1"]


def test_a_thesis_change_claim_naming_a_point_that_is_not_listed_is_malformed(env):
    runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    Stub.script = {"thesis_change": ["fake_point", "fake_point"]}
    late = run(env)
    assert late["incomplete_tasks"] == {"thesis_change": "malformed"} and len(posts_of("thesis_change")) == 2
    assert "claims[0].point 'FAKE99' is not one of the earlier points (G1, R1)" in analysis(late)["tasks"]["thesis_change"]["cause"]


def test_a_prior_with_one_task_not_ok_names_it_in_the_instruction_and_the_manifest(env):
    Stub.script = {"risks": ["no_json", "no_json"]}
    early = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    assert early["status"] == "analysis_incomplete"
    late = run(env)
    (req,) = posts_of("thesis_change")
    assert "The earlier risks task did not finish, so no points come from it. " in req["prompt"]
    man = manifest(late)
    assert man["prior_run"]["tasks_used"] == ["growth_thesis"] and man["prior_run"]["tasks_missing"] == {"risks": "malformed"}
    assert man["prior_run"]["point_ids"] == ["G1"] and late["status"] == "complete"


def test_a_run_at_the_same_t_is_not_a_prior(env):
    run(env)
    assert manifest(run(env))["tasks"]["thesis_change"]["status"] == "not_applicable_no_prior"


def test_a_prior_whose_records_do_not_recompute_is_infra_error(env):
    early = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    a = Path(early["run_dir"]) / "analysis.json"
    a.write_bytes(a.read_bytes() + b" ")
    late = run(env)
    assert late["incomplete_tasks"] == {"thesis_change": "infra_error"}
    assert "does not match its manifest sha256" in analysis(late)["tasks"]["thesis_change"]["cause"]
    assert posts_of("thesis_change") == []


def test_a_prior_without_ok_growth_or_risks_is_prior_unusable(env):
    # ruling 4.4 (the reply's failing input): the run is analysis_incomplete, not complete
    Stub.script = {"growth_thesis": ["no_json", "no_json"], "risks": ["no_json", "no_json"]}
    early = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    assert early["status"] == "analysis_incomplete"
    late = run(env)
    tc = manifest(late)["tasks"]["thesis_change"]
    assert tc["status"] == "prior_unusable" and "neither growth_thesis nor risks is ok" in tc["cause"]
    assert late["status"] == "analysis_incomplete" and late["incomplete_tasks"] == {"thesis_change": "prior_unusable"}
    assert posts_of("thesis_change") == [] and "prior_unusable" in runner.STATUSES


def test_a_prior_with_no_supported_claim_is_prior_unusable(env, monkeypatch):
    real = contract.check_claim
    monkeypatch.setattr(contract, "check_claim", lambda c, items, ticker=None, statements=(): {**real(c, items, ticker, statements), "support": "number_not_found"})
    runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    monkeypatch.setattr(contract, "check_claim", real)
    late = run(env)
    tc = manifest(late)["tasks"]["thesis_change"]
    assert tc["status"] == "prior_unusable" and "no supported growth_thesis or risks claim" in tc["cause"]
    assert manifest(late)["prior_run"]["point_ids"] == [] and manifest(late)["prior_run"]["points_left_out"] == 4
    assert late["status"] == "analysis_incomplete" and posts_of("thesis_change") == []


def test_a_finished_run_missing_from_the_ledger_is_still_the_prior(env):
    # ruling 4.5 A: a crash between manifest.json and the ledger append must not let an older run be used
    runner.run(_packet_at(env, "2026-04-01T13:00:00Z", "older.json"), url=env["url"])
    newer = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "newer.json"), url=env["url"])
    ledger = runner.M3M_DIR / "ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
    ledger.write_text(lines[0], encoding="utf-8")              # the newer run's line never landed
    rows = runner.read_ledger()
    assert [r.get("ledger_missing", False) for r in rows] == [False, True] and rows[1]["status"] == "complete"
    late = run(env)
    man = manifest(late)
    assert man["prior_run"]["run_id"] == newer["run_id"] and man["prior_run"]["ledger_missing"] is True
    assert man["prior_run"]["manifest_sha256"] == sha((Path(newer["run_dir"]) / "manifest.json").read_bytes())
    assert "as of 2026-05-01T13:00:00Z" in posts_of("thesis_change")[-1]["prompt"]               # the late run's (newer's own is first)


def test_a_torn_last_ledger_line_is_skipped_and_reported_and_not_appended_after(env):
    # ruling 4.5 B
    early = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    ledger = runner.M3M_DIR / "ledger.jsonl"
    with open(ledger, "a", encoding="utf-8") as f:
        f.write('{"run_id": "ACME_2026')
    rows = runner.read_ledger()
    assert rows[0]["run_id"] == early["run_id"] and rows[1]["status"] == "torn_ledger_line" and rows[1]["line"] == 2
    before = ledger.read_bytes()
    late = run(env)
    assert late["status"] == "complete" and late["ledger_appended"] is False and ledger.read_bytes() == before
    assert "torn" in manifest(late)["ledger_not_appended"]
    assert manifest(late)["prior_run"]["run_id"] == early["run_id"]                # the prior is still found
    assert [r["run_id"] for r in runner.read_ledger() if r.get("ledger_missing")] == [late["run_id"]]


def test_a_torn_middle_ledger_line_still_raises(env):
    early = runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    ledger = runner.M3M_DIR / "ledger.jsonl"
    good = ledger.read_text(encoding="utf-8")
    ledger.write_text('{"run_id": "torn\n' + good, encoding="utf-8")
    with pytest.raises(ValueError, match="line 1 of 2 is torn"):
        runner.read_ledger()
    late = run(env)
    assert late["status"] == "failed" and "line 1 of 2 is torn" in manifest(late)["cause"]


def test_a_whole_last_line_without_a_newline_gets_one_before_the_append(env):
    runner.run(_packet_at(env, "2026-05-01T13:00:00Z", "early.json"), url=env["url"])
    ledger = runner.M3M_DIR / "ledger.jsonl"
    ledger.write_bytes(ledger.read_bytes().rstrip(b"\n"))
    late = run(env)
    assert late["ledger_appended"] is True and len(runner._read_jsonl(ledger)) == 2 and ledger.read_bytes().endswith(b"\n")


# ---------------------------------------------------------------- WO_M4: the reply, the context window and the server

def test_an_empty_reply_is_malformed_and_retried(env):
    Stub.script = {"business_model": ["empty_reply", "empty_reply"], "risks": ["empty_reply"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"business_model": "malformed"} and len(posts_of("risks")) == 2
    assert "the reply has no claims and no unknowns" in analysis(res)["tasks"]["business_model"]["cause"]


@pytest.mark.parametrize("action,detail", [("error_200", "HTTP 200 with an error: llama runner"),
                                           ("empty_200", "HTTP 200 with an empty response and done False")])
def test_an_http_200_error_or_empty_response_is_an_infra_retry(env, action, detail):
    Stub.script = {"business_model": [action]}
    res = run(env)
    assert res["status"] == "complete" and env["unloads"] == [(env["url"], runner.MODEL)] and len(posts_of("business_model")) == 2
    att = manifest(res)["tasks"]["business_model"]["attempts"]
    assert att[0]["outcome"] == "infra_retry" and detail in att[0]["detail"]
    Stub.script = {"business_model": [action, action]}
    res = run(env)
    assert res["incomplete_tasks"] == {"business_model": "infra_error"} and detail in analysis(res)["tasks"]["business_model"]["cause"]


def test_a_reply_cut_at_num_predict_names_done_reason_length(env):
    Stub.script = {"risks": ["cut_at_length", "cut_at_length"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"risks": "malformed"}
    assert "done_reason is length: the reply was cut at num_predict 12288" in analysis(res)["tasks"]["risks"]["cause"]


def test_the_post_check_catches_a_reply_at_the_context_wall(env):
    Stub.script = {"risks": ["at_the_wall"], "growth_thesis": ["no_counts"]}
    res = run(env)
    assert res["incomplete_tasks"] == {"risks": "context_overflow", "growth_thesis": "context_overflow"}
    assert len(posts_of("risks")) == 1 and len(posts_of("growth_thesis")) == 1
    an = analysis(res)["tasks"]
    assert "post-check: prompt_eval_count 98302 + eval_count 1 = 98303 >= num_ctx - 1 = 98303" in an["risks"]["cause"]
    assert "no prompt_eval_count" in an["growth_thesis"]["cause"]


def test_the_preflight_refuses_a_prompt_that_cannot_fit(env):
    res = run(env, num_ctx=12288 + 500)              # the rendered prompt is over 1,250 characters, so no task fits
    assert set(res["incomplete_tasks"]) == set(SENT) and res["status"] == "failed"
    assert [p for p in generate_posts()] == []
    rec = manifest(res)["tasks"]["business_model"]
    assert rec["status"] == "context_overflow" and rec["cause"].startswith("preflight: ") and rec["cause"].endswith("not sent")
    assert rec["attempts"][0]["seconds"] == 0.0 and manifest(res)["options"]["chars_per_token"] == 2.5


def test_another_resident_model_refuses_the_run_and_writes_nothing(env):
    Stub.loaded = ["rs2-research:latest", runner.MODEL + ":latest"]
    with pytest.raises(runner.RunRefused, match=r"^gpu_busy: another model is loaded on the Ollama server: rs2-research:latest$"):
        run(env)
    Stub.loaded = None
    with pytest.raises(runner.RunRefused, match="^gpu_state_unreadable"):
        run(env)
    assert not runner.M3M_DIR.exists() and generate_posts() == []
    Stub.loaded = [runner.MODEL + ":latest"]                                     # our own model may be resident
    assert run(env)["status"] == "complete"


@pytest.mark.parametrize("show", [None, {"details": {}}, {"parameters": "  "}])
def test_no_model_parameters_refuses_the_run(env, show):
    Stub.show = show
    with pytest.raises(runner.RunRefused, match="^model_show_failed"):
        run(env)
    assert not runner.M3M_DIR.exists() and generate_posts() == []


# ---------------------------------------------------------------- the parser

@pytest.mark.parametrize("content,ok", [
    ('```json\n{"a": 1}\n```', True),
    ('text\n```JSON\n{"a": 1}\n```\nmore', True),
    ('{"a": 1}', True),
    ('```json\n{"a": 1}\n```\n```json\n{"a": 2}\n```', False),
    ('```json\n{"a": \n```', False),
    ('```\n{"a": 1}\n```', False),
    ('{"a": NaN}', False),
    ('', False),
    (None, False),
])
def test_parse_reply(content, ok):
    obj, err = runner.parse_reply(content)
    assert (obj is not None) is ok and (err is None) is ok

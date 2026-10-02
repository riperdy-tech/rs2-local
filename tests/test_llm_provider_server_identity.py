"""Muse integration, M2.3 "Server identity" and the upstream wait: the provider reads cache/llamacpp/engine.json before each
request and refuses with HTTP 500 `engine_not_ready` when the file is missing, its PID is not alive, its pins differ from the
config, or GET /health does not answer 200 within 5 s. The refusal comes before any generation: the fake llama-server must
have received no request. Also: the upstream wait is min(caller timeout, upstream_timeout_s)."""
import json
import os
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llamacpp_fakes import chat_body, completion, engine_record, fake_llama, muse_env  # noqa: E402,F401
import llm_provider as prov  # noqa: E402
import rs2_data  # noqa: E402


def refused(env, why_contains):
    code, out = env.post(chat_body())
    assert code == 500 and out["cause"] == "engine_not_ready", out
    assert out["error"].startswith("engine_not_ready") and why_contains in out["error"], out
    assert env.fake.requests == [], "the refusal must come before any generation"
    return out


# ------------------------------------------------------------------ the engine file

def test_a_live_pinned_healthy_server_is_served_and_health_is_checked_before_every_request(muse_env):
    muse_env.fake.script = [("json", 200, completion("a")), ("json", 200, completion("b"))]
    assert muse_env.post(chat_body())[0] == 200 and muse_env.post(chat_body())[0] == 200
    assert muse_env.fake.health_calls == 2 and len(muse_env.fake.requests) == 2


def test_a_missing_engine_file_refuses(muse_env):
    muse_env.engine_file.unlink()
    refused(muse_env, "does not exist")


@pytest.mark.parametrize("content,why", [("{not json", "unreadable"), ("[1, 2]", "not a JSON object"), ("", "unreadable")])
def test_an_unreadable_engine_file_refuses(muse_env, content, why):
    muse_env.engine_file.write_text(content, encoding="utf-8")
    refused(muse_env, why)


def test_a_dead_pid_refuses(muse_env):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    muse_env.write_engine(pid=p.pid)
    refused(muse_env, "is not alive")


@pytest.mark.parametrize("pid", [None, 0, -5, "123", True, 1.5])
def test_a_missing_or_malformed_pid_refuses(muse_env, pid):
    muse_env.write_engine(pid=pid)
    refused(muse_env, "is not alive")


def test_pid_alive_is_true_for_a_running_process_and_false_for_a_finished_one():
    assert prov.pid_alive(os.getpid()) is True
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert prov.pid_alive(p.pid) is True
        assert prov.pid_alive(p.pid) is True        # asking never terminates it (os.kill(pid, 0) would on Windows)
    finally:
        p.kill()
        p.wait()
    assert prov.pid_alive(p.pid) is False


@pytest.mark.parametrize("key,wrong", [
    ("build", "b99999"), ("build_manifest_sha256", "0" * 64), ("model_sha256", "0" * 64), ("drafter_sha256", "0" * 64),
    ("server_cmdline_sha256", "0" * 64), ("system_sha256", "0" * 64), ("provider_sha256", "0" * 64),
    ("spec", {"type": "draft-dflash", "n_max": 6, "ngld": 99}), ("spec", {"type": "none"}),
    ("reasoning_format", "none"), ("endpoint", "http://127.0.0.1:9"), ("build_manifest_sha256", None), ("model_sha256", None)])
def test_a_pin_that_differs_from_the_config_refuses_and_names_it(muse_env, key, wrong):
    muse_env.write_engine(**{key: wrong})
    refused(muse_env, key)


def test_a_pin_missing_from_the_engine_file_refuses(muse_env):
    rec = json.loads(muse_env.engine_file.read_text(encoding="utf-8"))
    del rec["drafter_sha256"]
    muse_env.engine_file.write_text(json.dumps(rec), encoding="utf-8")
    refused(muse_env, "drafter_sha256")


def test_a_config_pin_that_moved_after_the_server_started_refuses(muse_env):
    muse_env.fake.script = [("json", 200, completion("a"))]
    assert muse_env.post(chat_body())[0] == 200
    muse_env.cfg["model_sha256"] = "1" * 64            # the config now pins another model than the running server's
    muse_env.fake.requests.clear()
    refused(muse_env, "model_sha256")


def test_the_system_file_must_hash_to_the_pinned_sha(muse_env, tmp_path):
    other = tmp_path / "other_system.txt"
    other.write_bytes(b"not the charter")
    muse_env.cfg["system_file"] = str(other)           # config still pins the real SYSTEM's sha256
    refused(muse_env, "hashes to")


def test_a_missing_system_file_refuses(muse_env, tmp_path):
    muse_env.cfg["system_file"] = str(tmp_path / "nope.txt")
    refused(muse_env, "system_file")


def test_depth_model_must_equal_the_model_tag(muse_env, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_model", "rs2-analyst-deep-mtp5-v33")
    out = refused(muse_env, "depth_model")
    assert "rs2-analyst-deep-mtp5-v33" in out["error"] and muse_env.cfg["model_tag"] in out["error"]


def test_a_config_without_the_llamacpp_block_refuses(muse_env, monkeypatch):
    monkeypatch.delitem(rs2_data.CONFIG, "llamacpp")
    refused(muse_env, "no llamacpp block")


# ------------------------------------------------------------------ /health

def test_health_must_answer_200(muse_env):
    muse_env.fake.health = (503, {"error": {"message": "Loading model"}})
    refused(muse_env, "/health")


def test_health_that_does_not_answer_in_time_refuses(muse_env, monkeypatch):
    monkeypatch.setattr(prov, "HEALTH_TIMEOUT_S", 0.3)
    muse_env.fake.health_delay = 1.5
    t0 = time.time()
    refused(muse_env, "/health")
    assert time.time() - t0 < 1.4


def test_the_health_wait_is_five_seconds():
    assert prov.HEALTH_TIMEOUT_S == 5


def test_a_server_that_is_down_refuses_before_any_request(muse_env):
    muse_env.fake.close()
    code, out = muse_env.post(chat_body())
    assert code == 500 and out["cause"] == "engine_not_ready"


def test_the_response_carries_the_engine_record_that_was_checked(muse_env):
    muse_env.fake.script = [("json", 200, completion("a"))]
    code, out = muse_env.post(chat_body())
    assert code == 200 and out["engine"] == json.loads(muse_env.engine_file.read_text(encoding="utf-8"))
    assert out["engine"]["provider_sha256"] == prov.provider_sha256()


# ------------------------------------------------------------------ the provider setting

def test_an_unknown_provider_is_a_configuration_error_not_a_fallback(monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "vllm")
    with pytest.raises(ValueError, match="depth_provider"):
        prov.chat(chat_body(), 10)


def test_the_provider_defaults_to_ollama_when_the_key_is_absent(monkeypatch):
    monkeypatch.delitem(rs2_data.CONFIG, "depth_provider", raising=False)
    assert prov.provider_name() == "ollama"


# ------------------------------------------------------------------ the 500 the callers see

def test_the_raised_error_is_an_http_error_500_with_the_adapters_json_body(muse_env):
    muse_env.fake.script = [("json", 400, {"error": {"type": "exceed_context_size_error", "message": "m",
                                                     "n_prompt_tokens": 9, "n_ctx": 4}})]
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat(chat_body(), 30)
    assert e.value.code == 500 and e.value.cause == "context_overflow"
    body = json.loads(e.value.read())
    assert set(body) == {"error", "cause"} and body["cause"] == "context_overflow"
    assert body["error"] == 'context_overflow m {"n_prompt_tokens": 9, "n_ctx": 4}'


# ------------------------------------------------------------------ the upstream wait: min(caller timeout, upstream_timeout_s)

def test_a_caller_timeout_below_the_upstream_timeout_raises_the_timeout_urllib_raises_at_the_caller(muse_env):
    muse_env.cfg["upstream_timeout_s"] = 3600
    muse_env.fake.script = [("sleep", 3, completion("late"))]
    t0 = time.time()
    with pytest.raises(TimeoutError):
        prov.chat(chat_body(), 0.5)
    assert time.time() - t0 < 2.5


def test_an_upstream_timeout_below_the_caller_timeout_is_a_named_500(muse_env):
    muse_env.cfg["upstream_timeout_s"] = 0.5
    muse_env.fake.script = [("sleep", 3, completion("late"))]
    t0 = time.time()
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat(chat_body(), 1800)
    assert e.value.code == 500 and e.value.cause == "upstream_timeout" and time.time() - t0 < 2.5
    assert "0.5s" in json.loads(e.value.read())["error"]


def test_equal_timeouts_are_the_upstream_timeout(muse_env):
    muse_env.cfg["upstream_timeout_s"] = 0.5
    muse_env.fake.script = [("sleep", 3, completion("late"))]
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat(chat_body(), 0.5)
    assert e.value.cause == "upstream_timeout"


def test_the_harness_timeouts_sit_where_the_adapter_topology_put_them():
    """Tools path 14,400 s and no-tools path 7,200 s sit above the adapter's 3,600 s (the upstream timeout fires first, as a
    named 500); continue_report and discovery 1,800 s and _llm_fix_json 900 s sit below it (the caller's timeout fires first,
    as a TimeoutError)."""
    up = rs2_data.CONFIG["llamacpp"]["upstream_timeout_s"]
    assert 14400 > up and 7200 > up and 1800 < up and 900 < up


# ------------------------------------------------------------------ C4: each request names the pinned model

@pytest.mark.parametrize("model", ["rs2-analyst-deep-mtp5-v33", "m", "", None])
def test_a_request_for_another_model_is_refused_before_anything_is_sent(muse_env, model):
    body = chat_body()
    if model is None:
        del body["model"]
    else:
        body["model"] = model
    code, out = muse_env.post(body)
    assert code == 500 and out["cause"] == "engine_not_ready" and "is not llamacpp.model_tag" in out["error"]
    assert muse_env.fake.requests == []


def test_a_request_for_the_pinned_model_is_served(muse_env):
    muse_env.fake.script = [("json", 200, completion("a"))]
    assert muse_env.post(chat_body(model=muse_env.cfg["model_tag"]))[0] == 200

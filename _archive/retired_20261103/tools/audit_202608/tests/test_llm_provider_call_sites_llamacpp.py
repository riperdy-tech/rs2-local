"""Muse integration, M2.4 and M4.2 under depth_provider "llamacpp": every analyst-model call site of the depth path goes
through the provider, reaches the (fake) llama-server's OpenAI endpoint with the pinned SYSTEM text injected, and never
reaches Ollama. The harness itself never sends a system message.

The fake is an in-process OpenAI-compatible HTTP server (tests/llamacpp_fakes.py); no GPU, no model, no network beyond 127.0.0.1."""
import json
import sys
import urllib.request
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
REPO = AUDIT_DIR.parents[1]
for p in (str(AUDIT_DIR), str(REPO), str(REPO / "tests"), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import analyst_tools as at  # noqa: E402
import catalyst_research as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import llm_provider as prov  # noqa: E402
import pack_facts  # noqa: E402
from llamacpp_fakes import REAL_SYSTEM_FILE, chat_body, completion, fake_llama, muse_env, tool_call  # noqa: E402,F401
from test_consensus_anchor_gate import _DUMMY_PACK, _SAMPLE_MEMO  # noqa: E402

_REAL_LLM_FIX_JSON = cr._llm_fix_json
REPORT = "y" * 6000
SYSTEM = REAL_SYSTEM_FILE.read_bytes().decode("utf-8")


@pytest.fixture
def urls(muse_env, monkeypatch):
    """Record every URL urlopen is asked for; the loopback opener (installed by muse_env) still serves them."""
    seen = []
    real = urllib.request.urlopen

    def recording(req, *a, **k):
        seen.append(req if isinstance(req, str) else req.full_url)
        return real(req, *a, **k)
    monkeypatch.setattr(urllib.request, "urlopen", recording)
    return seen


def assert_llamacpp_only(urls, env):
    assert urls and all(u.startswith(f"http://127.0.0.1:{env.cfg['port']}/") for u in urls), urls
    assert not any(":11434" in u for u in urls)


def first_is_the_pinned_system(request):
    m = request["messages"]
    assert m[0] == {"role": "system", "content": SYSTEM}
    assert [x["role"] for x in m].count("system") == 1


def test_the_tools_path_goes_through_the_provider(muse_env, urls, tmp_path):
    muse_env.fake.script = [("json", 200, completion(REPORT))]
    rep, think, meta = at.chat_with_tools(muse_env.cfg["model_tag"], "PACK", tmp_path / "s", think="high", verbose=False,
                                          max_model_calls=0, seed=1001, num_predict=4096)
    assert rep == REPORT and meta["failure"] is None
    assert_llamacpp_only(urls, muse_env)
    req = muse_env.fake.requests[0]
    first_is_the_pinned_system(req)
    assert req["messages"][1] == {"role": "user", "content": "PACK"} and req["seed"] == 1001 and req["max_tokens"] == 4096
    assert "tools" in req and "temperature" not in req and "presence_penalty" not in req and "repeat_penalty" not in req


def test_the_harness_never_sends_a_system_message(muse_env, monkeypatch, tmp_path):
    bodies = []
    real_chat = prov.chat
    monkeypatch.setattr(prov, "chat", lambda body, timeout: (bodies.append(json.loads(json.dumps(body))), real_chat(body, timeout))[1])
    muse_env.fake.script = [("json", 200, completion("", finish="tool_calls", tool_calls=[tool_call()])),
                            ("json", 200, completion(REPORT))]
    monkeypatch.setattr(at, "search_web", lambda *a, **k: {"results": [], "n_results": 0, "query": "q"})
    at.chat_with_tools(muse_env.cfg["model_tag"], "PACK", tmp_path / "s", think="high", verbose=False, max_model_calls=0)
    assert len(bodies) == 2
    assert all(m["role"] != "system" for b in bodies for m in b["messages"])
    # and the provider added exactly one to each request it sent
    for r in muse_env.fake.requests:
        first_is_the_pinned_system(r)


def test_the_discovery_json_fix_goes_through_the_provider(muse_env, urls, monkeypatch):
    monkeypatch.setattr(cr, "_llm_fix_json", _REAL_LLM_FIX_JSON)
    muse_env.fake.script = [("json", 200, completion("```json\n{\"a\": 1}\n```"))]
    assert cr._llm_fix_json(muse_env.cfg["model_tag"], "{bad", "err") == '{"a": 1}'
    assert_llamacpp_only(urls, muse_env)
    first_is_the_pinned_system(muse_env.fake.requests[0])


def test_continue_report_goes_through_the_provider(muse_env, urls):
    muse_env.fake.script = [("json", 200, completion("continued", reasoning="t", usage=(900, 7)))]
    out = cv.continue_report(model=muse_env.cfg["model_tag"], pack="PACK", partial_report="partial " * 50, ctx=98304,
                             seed=1101, think="high")
    assert out == ("continued", "t", {"done_reason": "stop", "generated_tokens": 7})
    assert_llamacpp_only(urls, muse_env)
    req = muse_env.fake.requests[0]
    first_is_the_pinned_system(req)
    assert req["seed"] == 1101 and req["max_tokens"] == 32768


def test_continue_report_reports_a_server_refusal_as_before(muse_env):
    muse_env.engine_file.unlink()
    out = cv.continue_report(model=muse_env.cfg["model_tag"], pack="PACK", partial_report="p" * 300, ctx=98304)
    assert out == ("", "", {"done_reason": "error", "error": "HTTP Error 500: Internal Server Error"})
    assert muse_env.fake.requests == []


def test_the_no_tools_path_and_its_retry_go_through_the_provider(muse_env, urls, monkeypatch, tmp_path, capsys,
                                                                 screener_data_stub):
    muse_env.fake.script = [("json", 200, completion("")), ("json", 200, completion(_SAMPLE_MEMO, usage=(100, 500)))]
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    pack_file = frozen / "_pack.md"
    pack_file.write_text(_DUMMY_PACK, encoding="utf-8")
    facts = pack_facts.from_text(_DUMMY_PACK)
    facts["source"] = "build"
    facts["consensus_data_status"] = "enrich_missing"
    pack_facts.write_sidecar(frozen, facts)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--model", muse_env.cfg["model_tag"], "--ctx", "98304",
                                      "--price", "100", "--samples", "1", "--no-early-stop", "--pack-file", str(pack_file),
                                      "--out-dir", str(out_dir)])
    cv.main()
    capsys.readouterr()
    assert_llamacpp_only(urls, muse_env)
    first, retry = muse_env.fake.requests
    for r in (first, retry):
        first_is_the_pinned_system(r)
        assert r["messages"][1] == {"role": "user", "content": _DUMMY_PACK}
        assert r["max_tokens"] == cv.NUM_PREDICT
        for k in ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repeat_penalty", "cache_prompt"):
            assert k not in r
    assert (first["seed"], retry["seed"]) == (1001, 51001)                  # the empty-report retry's perturbed seed, as today


def test_the_pinned_system_text_is_the_charters_file_decoded_without_newline_translation(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    code, out = muse_env.post(chat_body())
    sent = muse_env.fake.requests[0]["messages"][0]["content"]
    assert code == 200 and out["system_injected"] is True
    assert sent.encode("utf-8") == REAL_SYSTEM_FILE.read_bytes() and "\r" not in sent
    assert sent.startswith("Reasoning strength: xhigh\n")


def test_a_requests_own_system_message_is_left_alone_with_the_real_file(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    code, out = muse_env.post(chat_body(messages=[{"role": "system", "content": "mine"}, {"role": "user", "content": "u"}]))
    assert out["system_injected"] is False
    assert muse_env.fake.requests[0]["messages"][0] == {"role": "system", "content": "mine"}

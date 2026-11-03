"""Muse integration, M3.3 (where the lifecycle is called) and M8 item 4: under depth_provider "llamacpp" the depth path stops
the server before research, makes sure it runs after research and before discovery, stops it after each child, and the status
dashboard reports it; under "ollama" every one of those places behaves exactly as before and never touches the server module.

Every GPU, subprocess and model seam is stubbed: llamacpp_server.stop / ensure_ready are recorders here (their own behaviour is
tests/test_llamacpp_server.py), ops.wait_unloaded is a recorder, the children are fake processes."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# orchestrate_depth re-wraps sys.stdout at import; keep the wrapper alive and restore ours (see tests/test_depth_queue.py)
_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
import depth_ondemand as dod  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT

import catalyst_research as cr  # noqa: E402
import depth_pipeline as dp  # noqa: E402
import llamacpp_server  # noqa: E402
import rs2_data  # noqa: E402
import status as st  # noqa: E402


@pytest.fixture
def provider(monkeypatch):
    """Switch the provider, and record every call into the server module: ("stop",), ("ensure_ready",)."""
    calls = []
    state = {"stop": (True, "stopped"), "ensure": None}

    def stop(cfg=None):
        calls.append(("stop",))
        return state["stop"]

    def ensure_ready(cfg=None, hasher=None):
        calls.append(("ensure_ready",))
        if state["ensure"] is not None:
            raise state["ensure"]
        return {"pid": 1}
    monkeypatch.setattr(llamacpp_server, "stop", stop)
    monkeypatch.setattr(llamacpp_server, "ensure_ready", ensure_ready)

    def select(name):
        monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", name)
    select.calls, select.state = calls, state
    select("llamacpp")
    return select


# ------------------------------------------------------------------ depth_pipeline.run_research: stop, then the same poll

@pytest.fixture
def research(monkeypatch, tmp_path):
    """run_research with everything but the unload barrier stubbed."""
    rv = tmp_path / "python.exe"
    rv.write_text("x")
    monkeypatch.setitem(dp.CONFIG, "research_venv_python", str(rv))
    events = []
    monkeypatch.setattr(dp.ops, "wait_unloaded", lambda endpoint, model, need_free_mb=20000, timeout_s=180, poll_s=2.0:
                        (events.append(("wait_unloaded", endpoint, model, need_free_mb, timeout_s)), (True, "free"))[1])
    monkeypatch.setattr(dp.rs2_data, "resolve_name", lambda t: "Test Co")
    monkeypatch.setattr(dp, "_research_brief_provenance", lambda t: (None, None))
    monkeypatch.setattr(dp, "check_research_brief", lambda t: (True, "ok"))
    monkeypatch.setattr(dp, "_invoke_deep_research", lambda t, name, rv, force=False: events.append(("deep_research", t)))
    return events


def test_research_under_llamacpp_stops_the_server_then_runs_the_same_free_memory_poll(provider, research):
    assert dp.run_research("TEST") is True
    events = [("stop",) if e == ("stop",) else e for e in research]
    assert provider.calls == [("stop",)]
    first_poll = research[0]
    assert first_poll[0] == "wait_unloaded" and first_poll[2] == dp.MODEL and first_poll[3] == 11000
    assert first_poll[1] == dp.CONFIG["ollama_endpoint"]
    assert first_poll[4] == int(dp.CONFIG.get("vram_unload_timeout_s", 180))
    assert research[1] == ("deep_research", "TEST")


def test_stop_comes_before_the_poll_and_before_research(provider, research, monkeypatch):
    order = []
    monkeypatch.setattr(llamacpp_server, "stop", lambda cfg=None: (order.append("stop"), (True, "x"))[1])
    monkeypatch.setattr(dp.ops, "wait_unloaded", lambda *a, **k: (order.append("poll"), (True, "x"))[1])
    monkeypatch.setattr(dp, "_invoke_deep_research", lambda *a, **k: order.append("research"))
    dp.run_research("TEST")
    assert order[:3] == ["stop", "poll", "research"]


def test_a_stop_that_does_not_complete_exits_7_and_research_does_not_run(provider, research):
    provider.state["stop"] = (False, "TIMEOUT after 180s - pid 1 gone=False gpu_used=22000MiB")
    with pytest.raises(SystemExit) as e:
        dp.run_research("TEST")
    assert e.value.code == 7
    assert research == [] and provider.calls == [("stop",)]


def test_research_under_ollama_is_unchanged_and_never_touches_the_server(provider, research):
    provider("ollama")
    assert dp.run_research("TEST") is True
    assert provider.calls == []
    assert research[0] == ("wait_unloaded", dp.CONFIG["ollama_endpoint"], dp.MODEL, 11000,
                           int(dp.CONFIG.get("vram_unload_timeout_s", 180)))
    assert research[1] == ("deep_research", "TEST")


# ------------------------------------------------------------------ depth_pipeline.main: ensure_ready after research

@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """depth_pipeline.main() with its seams stubbed, recording the order of research, ensure_ready, discovery and consensus."""
    order = []
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path / "research"))
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))
    monkeypatch.setattr(dp.price_now, "quote", lambda t: {"price": 100.0, "asof": "2026-10-02", "source": "yfinance"})
    monkeypatch.setattr(dp, "run_research", lambda t: (order.append("research"), True)[1])
    monkeypatch.setattr(dp, "audit_verdict", lambda t, ledger: None)
    monkeypatch.setattr(dp.ops, "notify_telegram", lambda msg: None)
    monkeypatch.setattr(dp, "LEDGER", tmp_path / "depth_ledger.jsonl")
    monkeypatch.setattr(dp, "TEST_LEDGER", tmp_path / "depth_test_ledger.jsonl")
    monkeypatch.setattr(dp, "OD_LEDGER", tmp_path / "depth_ondemand_ledger.jsonl")
    cdir = tmp_path / "TEST_20261002_120000"
    cdir.mkdir()
    monkeypatch.setattr(dp, "run_consensus", lambda *a, **k: (order.append("consensus"), (cdir, {"ticker": "TEST", "price": 100.0}))[1])
    monkeypatch.setattr(dp, "band_verdict", lambda doc: {"ticker": "TEST", "price": 100.0, "date": "2026-10-02", "direction": "hold"})
    monkeypatch.setattr(cr, "run", lambda t: (order.append("discovery"), {"ticker": t})[1])

    def go(*flags):
        monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "TEST", *flags])
        dp.main()
    go.order = order
    return go


def test_ensure_ready_runs_after_research_and_before_discovery_and_consensus(provider, pipeline, monkeypatch):
    monkeypatch.setattr(llamacpp_server, "ensure_ready", lambda cfg=None, hasher=None: pipeline.order.append("ensure_ready"))
    pipeline()
    assert pipeline.order == ["research", "ensure_ready", "discovery", "consensus"]


def test_ensure_ready_runs_even_when_discovery_is_skipped(provider, pipeline, monkeypatch):
    monkeypatch.setattr(llamacpp_server, "ensure_ready", lambda cfg=None, hasher=None: pipeline.order.append("ensure_ready"))
    pipeline("--no-discovery")
    assert pipeline.order == ["research", "ensure_ready", "consensus"]


def test_ensure_ready_runs_when_research_is_skipped(provider, pipeline, monkeypatch):
    monkeypatch.setattr(llamacpp_server, "ensure_ready", lambda cfg=None, hasher=None: pipeline.order.append("ensure_ready"))
    pipeline("--no-research", "--no-discovery")
    assert pipeline.order == ["ensure_ready", "consensus"]


def test_a_server_that_cannot_be_made_ready_exits_7_before_discovery_and_consensus(provider, pipeline, capsys):
    provider.state["ensure"] = llamacpp_server.ServerRefusal("Ollama has a model loaded: ['rs2-research']")
    with pytest.raises(SystemExit) as e:
        pipeline()
    assert e.value.code == 7
    assert pipeline.order == ["research"]
    assert "::VRAM:: llama-server not ready" in capsys.readouterr().out


def test_main_under_ollama_never_calls_ensure_ready(provider, pipeline):
    provider("ollama")
    pipeline()
    assert pipeline.order == ["research", "discovery", "consensus"] and provider.calls == []


IMPORTS_LIFECYCLE = re.compile(r"^\s*(import|from)\s+llamacpp_server", re.M)


def test_the_consensus_subprocess_never_starts_or_stops_the_server():
    """It reaches the server only through the provider: neither the harness modules nor the provider import the lifecycle."""
    for rel in ("tools/audit_202608/consensus_valuation.py", "tools/audit_202608/analyst_tools.py",
                "tools/audit_202608/llm_provider.py", "catalyst_research.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not IMPORTS_LIFECYCLE.search(text), rel
    for rel in ("depth_pipeline.py", "orchestrate_depth.py", "depth_ondemand.py", "status.py"):   # the control: the regex does match
        assert IMPORTS_LIFECYCLE.search((ROOT / rel).read_text(encoding="utf-8")), rel


# ------------------------------------------------------------------ after each child: orchestrate_depth and depth_ondemand

class FakeProc:
    def __init__(self, rc=0, hang=False):
        self.rc, self.hang, self.pid = rc, hang, 4242

    def wait(self, timeout=None):
        if self.hang:
            raise subprocess.TimeoutExpired("depth_pipeline", timeout)
        return self.rc


@pytest.fixture
def children(monkeypatch):
    """Both runners with a fake child, a recording of ops.wait_unloaded, and a fake taskkill."""
    unloads = []
    logs = []
    for mod in (od.ops,):
        monkeypatch.setattr(mod, "wait_unloaded", lambda endpoint, model, need_free_mb=20000, timeout_s=180, poll_s=2.0:
                            (unloads.append((model, need_free_mb, timeout_s)), (True, "free"))[1])
    monkeypatch.setattr(od, "log", lambda msg: logs.append(msg))
    monkeypatch.setattr(dod, "_log", lambda msg: logs.append(msg))
    monkeypatch.setattr(od, "_kill_tree", lambda pid: None)
    monkeypatch.setattr(od, "SAMPLE_TIMEOUT_MIN", 0)
    monkeypatch.setattr(dod, "TIMEOUT_MIN", 0)
    monkeypatch.setattr(dod.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setitem(rs2_data.CONFIG, "depth_model", "rs2-analyst-deep-mtp5")
    monkeypatch.setitem(rs2_data.CONFIG, "research_model", "rs2-research")

    def use(proc):
        monkeypatch.setattr(od.subprocess, "Popen", lambda *a, **k: proc)
        monkeypatch.setattr(dod.subprocess, "Popen", lambda *a, **k: proc)
    use.unloads, use.logs = unloads, logs
    return use


RUNNERS = [pytest.param(lambda: od.run_one("TEST"), id="orchestrate_depth.run_one"),
           pytest.param(lambda: dod._run_one("TEST"), id="depth_ondemand._run_one")]


@pytest.mark.parametrize("run", RUNNERS)
@pytest.mark.parametrize("rc,why", [(0, "ok"), (5, "consensus_failed"), (7, "vram")])
def test_a_finished_child_under_llamacpp_is_followed_by_stop_and_no_ollama_unload(provider, children, run, rc, why):
    children(FakeProc(rc))
    assert run() == (rc == 0, why)
    assert provider.calls == [("stop",)]
    assert children.unloads == []


@pytest.mark.parametrize("run", RUNNERS)
def test_a_watchdog_kill_under_llamacpp_stops_the_server_and_unloads_only_the_research_model(provider, children, run):
    children(FakeProc(hang=True))
    assert run() == (False, "watchdog_timeout")
    assert provider.calls == [("stop",)]
    assert children.unloads == [("rs2-research", 0, 120)]


@pytest.mark.parametrize("run", RUNNERS)
def test_a_stop_that_fails_after_a_child_is_logged_not_raised(provider, children, run):
    provider.state["stop"] = (False, "TIMEOUT after 180s")
    children(FakeProc(0))
    assert run() == (True, "ok")
    assert any("llama-server not released" in m and "TIMEOUT after 180s" in m for m in children.logs)


@pytest.mark.parametrize("run", RUNNERS)
def test_under_ollama_a_finished_child_changes_nothing(provider, children, run):
    provider("ollama")
    children(FakeProc(0))
    assert run() == (True, "ok")
    assert provider.calls == [] and children.unloads == []


@pytest.mark.parametrize("run", RUNNERS)
def test_under_ollama_a_watchdog_kill_unloads_both_models_as_before(provider, children, run):
    provider("ollama")
    children(FakeProc(hang=True))
    assert run() == (False, "watchdog_timeout")
    assert provider.calls == []
    assert children.unloads == [("rs2-analyst-deep-mtp5", 0, 120), ("rs2-research", 0, 120)]


# ------------------------------------------------------------------ status.py

@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "LEDGER", tmp_path / "depth_ledger.jsonl")
    monkeypatch.setattr(st, "DEPTH_STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(st, "DEPTH_PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(st, "DEPTH_LOCK", tmp_path / "orchestrate_depth.lock")
    monkeypatch.setattr(st, "DEPTH_PAUSE", tmp_path / "DEPTH_PAUSED")
    monkeypatch.setattr(st, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(st, "_task_info", lambda: (None, None, None))
    monkeypatch.setitem(st._LLAMACPP_CACHE, "v", None)
    st._LLAMACPP_CACHE.update(t=0.0, v=None)


def _status(**over):
    base = {"provider": "llamacpp", "model_tag": "muse-tag", "engine_file": True, "pid": 4242, "pid_alive": True, "health": True,
            "gpu_used_mib": 21937, "ready": True, "problem": None}
    base.update(over)
    return base


def test_the_dashboard_reports_the_servers_status_under_llamacpp(provider, dashboard, monkeypatch):
    monkeypatch.setattr(llamacpp_server, "status", lambda cfg=None: _status())
    out = st.depth_snapshot()
    assert "llama-server: READY | PID 4242 | health ok | GPU 21937 MiB | muse-tag" in out


def test_the_dashboard_says_down_and_why_when_the_server_is_not_ready(provider, dashboard, monkeypatch):
    monkeypatch.setattr(llamacpp_server, "status", lambda cfg=None: _status(ready=False, pid_alive=False, health=False,
                                                                           problem="llama-server PID 4242 from engine.json is not alive"))
    out = st.depth_snapshot()
    assert "llama-server: DOWN | PID 4242 | health — | GPU 21937 MiB" in out and "is not alive" in out


def test_the_dashboards_server_line_is_cached_for_30_seconds(provider, dashboard, monkeypatch):
    n = []
    monkeypatch.setattr(llamacpp_server, "status", lambda cfg=None: (n.append(1), _status())[1])
    st._llamacpp_line()
    st._llamacpp_line()
    assert len(n) == 1


def test_the_dashboard_under_ollama_never_asks_the_server_module(provider, dashboard, monkeypatch):
    provider("ollama")
    monkeypatch.setattr(llamacpp_server, "status", lambda cfg=None: pytest.fail("status() called under ollama"))
    out = st.depth_snapshot()
    assert "llama-server" not in out and st._llamacpp_line() is None


def _unload_spy(monkeypatch):
    posts = []

    class R:
        def read(self):
            return b""

    def urlopen(req, timeout=None):
        posts.append(json.loads(req.data))
        return R()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return posts


def test_unload_models_under_llamacpp_stops_the_server_and_unloads_only_the_research_model(provider, monkeypatch):
    posts = _unload_spy(monkeypatch)
    st._unload_models()
    assert provider.calls == [("stop",)]
    assert posts == [{"model": st.RESEARCH_MODEL, "keep_alive": 0}]


def test_unload_models_under_ollama_unloads_both_as_before(provider, monkeypatch):
    provider("ollama")
    posts = _unload_spy(monkeypatch)
    st._unload_models()
    assert provider.calls == []
    assert posts == [{"model": st.DEPTH_MODEL, "keep_alive": 0}, {"model": st.RESEARCH_MODEL, "keep_alive": 0}]

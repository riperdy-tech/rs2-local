"""2026-10-21: the Wi-Fi dropped for 1-40 minutes about hourly. Research must stop as an infra failure while the network is down (never declare a
topic NOT RESEARCHED), and a stage-1 research call waits for the network instead of handing the model an empty search."""
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "tools" / "audit_202608")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ops  # noqa: E402


def test_internet_up_is_true_when_a_probe_connects_and_false_when_none_does(monkeypatch):
    import importlib
    fresh = importlib.reload(ops)          # the real probe (the conftest stub is restored at teardown)
    seen = []

    class _C:
        def close(self):
            pass

    def ok(addr, timeout=None):
        seen.append(addr)
        return _C()

    def fail(addr, timeout=None):
        seen.append(addr)
        raise OSError("unreachable")

    monkeypatch.setattr(socket, "create_connection", ok)
    assert fresh.internet_up() is True and seen == [("1.1.1.1", 443)]
    seen.clear()
    monkeypatch.setattr(socket, "create_connection", fail)
    assert fresh.internet_up() is False and seen == [("1.1.1.1", 443), ("8.8.8.8", 53)]


def test_wait_for_internet_returns_when_the_network_comes_back(monkeypatch):
    states = iter([False, False, True])
    monkeypatch.setattr(ops, "internet_up", lambda timeout_s=3.0: next(states))
    monkeypatch.setattr(ops.time, "sleep", lambda s: None)
    back, waited = ops.wait_for_internet(60, poll_s=1)
    assert back is True


def test_wait_for_internet_gives_up_after_the_bound(monkeypatch):
    clock = iter(range(0, 1000, 30))
    monkeypatch.setattr(ops, "internet_up", lambda timeout_s=3.0: False)
    monkeypatch.setattr(ops.time, "time", lambda: next(clock))
    monkeypatch.setattr(ops.time, "sleep", lambda s: None)
    back, waited = ops.wait_for_internet(90, poll_s=1)
    assert back is False and waited >= 90


def test_a_research_topic_that_comes_back_empty_while_the_network_is_down_is_an_infra_failure(monkeypatch):
    import deep_research as dr
    import types
    monkeypatch.setattr(dr, "tool_chain", lambda: ["searxng", "tavily"])
    monkeypatch.setattr(dr, "ldr_overrides", lambda tool: {})
    calls = []
    fake = types.ModuleType("local_deep_research.api")
    fake.quick_summary = lambda q, settings_override=None: calls.append(q) or {"summary": "", "sources": [], "formatted_findings": ""}
    monkeypatch.setitem(sys.modules, "local_deep_research.api", fake)
    monkeypatch.setattr(ops, "internet_up", lambda timeout_s=3.0: False)
    with pytest.raises(dr.ResearchInfraError, match="network down"):
        dr.run_topic("q")
    assert len(calls) == 1                     # the keyed provider is not spent while the network is down


def test_a_stage1_research_call_waits_for_the_network_and_records_the_wait(monkeypatch):
    import r26_stages as st
    states = iter([False, True, True])
    monkeypatch.setattr(ops, "internet_up", lambda timeout_s=3.0: next(states))
    monkeypatch.setattr(ops, "wait_for_internet", lambda max_wait_s, poll_s=15.0: (True, 120.0))
    monkeypatch.setattr(st.analyst_tools, "dispatch_tool", lambda name, args, **kw: {"results": [{"url": "u"}]})
    rec = {}
    assert st._dispatch_net("search_web", {"query": "x"}, rec) == {"results": [{"url": "u"}]}
    assert rec["network_wait_s"] == 120.0


def test_a_stage1_research_call_stops_when_the_network_stays_down(monkeypatch):
    import r26_stages as st
    monkeypatch.setattr(ops, "internet_up", lambda timeout_s=3.0: False)
    monkeypatch.setattr(ops, "wait_for_internet", lambda max_wait_s, poll_s=15.0: (False, max_wait_s))
    with pytest.raises(st.NetworkDown):
        st._dispatch_net("fetch_page", {"url": "u"}, {})


def test_a_call_that_failed_as_the_network_dropped_is_retried_once(monkeypatch):
    import r26_stages as st
    states = iter([True, False, True])            # up before the call, down after it failed, up again before the retry
    monkeypatch.setattr(ops, "internet_up", lambda timeout_s=3.0: next(states))
    out = iter([{"error": "search failed: getaddrinfo"}, {"results": []}])
    monkeypatch.setattr(st.analyst_tools, "dispatch_tool", lambda name, args, **kw: next(out))
    assert st._dispatch_net("search_web", {"query": "x"}, {}) == {"results": []}

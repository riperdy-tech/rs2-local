"""Muse integration, C6: a production sweep under depth_provider "llamacpp" takes the full model and drafter hashes at its start
(llamacpp_server.begin_run); a mismatch refuses the sweep. Under "ollama" nothing changes. Mocks only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gate_no_publish import _isolate, od  # noqa: E402,F401
import llamacpp_server  # noqa: E402
import rs2_data  # noqa: E402


def _run(monkeypatch, tmp_path, *flags):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od, "publish_overlay", lambda: None)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--ignore-factor-guard", "--tickers", "FAKE1", *flags])
    return od.main()


def test_the_sweep_takes_the_full_hashes_once_before_the_first_name(monkeypatch, tmp_path):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "llamacpp")
    order = []
    monkeypatch.setattr(llamacpp_server, "begin_run", lambda cfg=None, hasher=None: order.append("begin_run"))
    monkeypatch.setattr(llamacpp_server, "stop", lambda cfg=None: (True, "x"))
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od, "run_one", lambda t, ondemand=False: (order.append(f"run_one {t}"), (True, ""))[1])
    monkeypatch.setattr(od, "publish_overlay", lambda: None)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--ignore-factor-guard", "--tickers", "FAKE1"])
    assert od.main() == 0
    assert order == ["begin_run", "run_one FAKE1"]


def test_a_model_that_is_not_the_pinned_one_refuses_the_sweep(monkeypatch, tmp_path):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "llamacpp")

    def bad(cfg=None, hasher=None):
        raise llamacpp_server.ServerRefusal("model sha256 deadbeef is not the pinned cafe")
    monkeypatch.setattr(llamacpp_server, "begin_run", bad)
    ran = []
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od, "run_one", lambda t, ondemand=False: (ran.append(t), (True, ""))[1])
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--ignore-factor-guard", "--tickers", "FAKE1"])
    assert od.main() == 1
    assert ran == [] and not od.LOCK.exists()


def test_a_dry_run_takes_no_hashes(monkeypatch, tmp_path):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "llamacpp")
    monkeypatch.setattr(llamacpp_server, "begin_run", lambda cfg=None, hasher=None: pytest.fail("begin_run on a dry run"))
    assert _run(monkeypatch, tmp_path, "--dry-run") == 0


def test_under_ollama_the_sweep_never_touches_the_server_module(monkeypatch, tmp_path):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama")
    monkeypatch.setattr(llamacpp_server, "begin_run", lambda cfg=None, hasher=None: pytest.fail("begin_run under ollama"))
    assert _run(monkeypatch, tmp_path) == 0

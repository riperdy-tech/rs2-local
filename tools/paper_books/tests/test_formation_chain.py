"""formation_chain.py: what is due in a pass, and that a failed step stops the chain with a flag."""
import json
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

import formation_chain as C

FILL = "2026-12-01T14:30:00Z"


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def a_map(*states):
    return {"fill_open_utc": FILL, "fill_session": "2026-12-01", "names": {f"N{i}": {"state": s} for i, s in enumerate(states)}}


@pytest.mark.parametrize("m, frozen, now, marked, published, want", [
    (None, False, "2026-12-01T00:00", False, False, ["decide"]),
    (a_map("to_build", "operator_excluded"), False, "2026-12-01T00:00", False, False, ["packets", "read"]),
    (a_map("to_run", "complete"), False, "2026-12-01T00:00", False, False, ["read"]),
    (a_map("pending", "complete"), False, "2026-12-01T13:30", False, False, ["freeze", "read"]),      # an hour before the open: frozen as it stands, then read on
    (a_map("complete", "analysis_incomplete"), False, "2026-12-01T00:00", False, False, ["freeze"]),
    (a_map("to_run"), False, "2026-12-01T14:30", False, False, ["late"]),                              # never frozen after the open
    (a_map("complete"), True, "2026-12-02T00:00", False, False, []),
    (a_map("complete"), True, "2026-12-02T00:00", True, False, ["publish"]),
    (a_map("complete"), True, "2026-12-02T00:00", True, True, []),
    (a_map("to_run"), True, "2026-12-01T15:00", False, False, ["read"]),                               # the read goes on after the freeze
])
def test_what_is_due(m, frozen, now, marked, published, want):
    assert C.next_steps(m, frozen, at(now), marked, published) == want


@pytest.fixture
def chain(tmp_path, monkeypatch):
    books = tmp_path / "books"
    (books / "m3o" / "inputs").mkdir(parents=True)
    monkeypatch.setattr(C.book_paths, "books", lambda: books)
    monkeypatch.setattr(C.book_paths, "screener_repo", lambda: tmp_path)
    monkeypatch.setattr(C, "STATE", tmp_path / "state")
    monkeypatch.setattr(C, "LOG", tmp_path / "state" / "chain.log")
    (tmp_path / "state").mkdir()
    told = []
    monkeypatch.setattr(C, "tell", told.append)

    @contextmanager
    def lock(wait_s=0):
        yield True
    monkeypatch.setattr(C, "_main_module", lambda name: type("M", (), {"rs2_state_lock": staticmethod(lock)}))
    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: None)
    return tmp_path, books, told


def test_no_decision_yet_is_not_a_failure(chain, monkeypatch):
    tmp, books, told = chain
    calls = []
    monkeypatch.setattr(C, "run", lambda script, *a, **k: (calls.append(script), (1, "STOP: no verified run") if script == "formation_decide.py" else (0, ""))[1])
    assert C.one_pass("2026-11-30", now=at("2026-12-01T00:00")) == 0
    assert calls == ["check_new_runs.py", "formation_decide.py"] and not told and not list((tmp / "state").glob("chain_STOP_*"))


def test_a_failed_step_stops_the_chain_until_the_flag_is_removed(chain, monkeypatch):
    tmp, books, told = chain
    (books / "m3o" / "inputs" / "formation_2026-11-30.json").write_text(json.dumps(a_map("to_build")), encoding="utf-8")
    calls = []
    monkeypatch.setattr(C, "run", lambda script, *a, **k: (calls.append(script), (2, "STOP: builder changed"))[1])
    assert C.one_pass("2026-11-30", now=at("2026-12-01T00:00")) == 1
    assert calls == ["formation_packets.py"] and len(told) == 1 and "builder changed" in told[0]
    assert C.one_pass("2026-11-30", now=at("2026-12-01T00:10")) == 1 and calls == ["formation_packets.py"]        # idle: nothing is run again


def test_late_is_a_stop_and_nothing_is_frozen(chain, monkeypatch):
    tmp, books, told = chain
    (books / "m3o" / "inputs" / "formation_2026-11-30.json").write_text(json.dumps(a_map("to_run")), encoding="utf-8")
    monkeypatch.setattr(C, "run", lambda *a, **k: pytest.fail("no step may run"))
    assert C.one_pass("2026-11-30", now=at("2026-12-01T15:00")) == 1 and "fill open has passed" in told[0]


def test_the_read_goes_in_chunks_until_no_name_is_left_then_freezes(chain, monkeypatch):
    tmp, books, told = chain
    path = books / "m3o" / "inputs" / "formation_2026-11-30.json"
    path.write_text(json.dumps(a_map(*["to_run"] * 7)), encoding="utf-8")
    monkeypatch.setattr(C, "worker_free", lambda: True)
    monkeypatch.setattr(C.G, "SITE", tmp / "site")
    calls = []

    def run(script, *a, **k):
        calls.append(script)
        m = json.loads(path.read_text(encoding="utf-8"))
        if script == "formation_run_cloud.py":
            assert a[-2:] == ("--limit", str(C.READ_CHUNK)) and (tmp / "site" / "formation.hold").exists()
            for n in [n for n in m["names"].values() if n["state"] == "to_run"][:C.READ_CHUNK]:
                n["state"] = "complete"
            path.write_text(json.dumps(m), encoding="utf-8")
        if script == "formation_freeze.py":
            path.with_name("formation_2026-11-30.frozen.json").write_text("{}")
        return 0, "witness line"
    monkeypatch.setattr(C, "run", run)
    assert C.one_pass("2026-11-30", now=at("2026-12-01T00:00")) == 0
    assert calls == ["formation_run_cloud.py", "formation_run_cloud.py", "formation_freeze.py"]
    assert "witness line" in told[0] and not (tmp / "site" / "formation.hold").exists()

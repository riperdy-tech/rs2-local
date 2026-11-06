"""The monthly formation steps (formation_decide / _packets / _run / _freeze): synthetic maps in a temp folder, a fake subprocess, no network,
no GPU, no model. Run from the repo root:  python -m pytest tools/paper_books/tests -q"""
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import book_paths  # noqa: E402
import forward_ledger as FL  # noqa: E402
import formation_decide as D  # noqa: E402
import formation_freeze as Z  # noqa: E402
import formation_packets as P  # noqa: E402
import formation_run as R  # noqa: E402

T = "2026-10-30"
COMMIT = "abcdef0123456789abcdef0123456789abcdef01"
EXCL = sorted(FL.OPERATOR_EXCLUDED)[0]                                    # the conftest's synthetic OPXA


def write_map(inputs, states, **over):
    m = {"formation_T": T, "fill_session": "2026-11-02", "fill_open_utc": "2026-11-02T14:30:00Z",
         "decision_time_utc": "2026-10-30T21:00:00Z", "run_id": "111", "output_commit": COMMIT,
         "verified_record": "rec.json", "builder_version": None, "book": sorted(states), "flags": {},
         "names": {t: {"packet": None, "run_dir": None, "attempts": 0, "state": s} for t, s in states.items()}}
    m.update(over)
    inputs.mkdir(parents=True, exist_ok=True)
    p = inputs / f"formation_{T}.json"
    p.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    return p


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- decide

@pytest.fixture
def decide(tmp_path, monkeypatch):
    inputs, checks = tmp_path / "inputs", tmp_path / "checks"
    checks.mkdir()
    (checks / "check_20261031T000000Z.json").write_text(
        json.dumps([{"verdict": "PASS", "pair": "PASS", "output_commit": COMMIT[:12]}]), encoding="utf-8")
    state = {"res": {"run_id": "111", "output_commit": COMMIT, "decision_time_utc": "2026-10-30T21:00:00Z"}}
    monkeypatch.setattr(D, "INPUTS", inputs)
    monkeypatch.setattr(D, "CHECKS", checks)
    monkeypatch.setattr(FL, "scoring_runs", lambda: [])
    monkeypatch.setattr(FL, "decision_for", lambda t, runs: (state["res"], date(2026, 11, 2), None))
    monkeypatch.setattr(FL, "book", lambda res: (["AAA", "BBB", EXCL], {"AAA": ["x"]}))
    monkeypatch.setattr(sys, "argv", ["formation_decide.py", T])
    return SimpleNamespace(inputs=inputs, checks=checks, state=state, path=inputs / f"formation_{T}.json")


def test_decide_writes_the_map_under_the_books_dir(decide, capsys):
    assert D.main() == 0
    m = load(decide.path)
    assert (m["run_id"], m["output_commit"], m["book"]) == ("111", COMMIT, ["AAA", "BBB", EXCL])
    assert m["fill_open_utc"] == "2026-11-02T14:30:00Z" and m["builder_version"] is None
    assert m["verified_record"] == str(decide.checks / "check_20261031T000000Z.json")
    assert {t: n["state"] for t, n in m["names"].items()} == {"AAA": "to_build", "BBB": "to_build", EXCL: "operator_excluded"}
    assert all(n["packet"] is None and n["run_dir"] is None and n["attempts"] == 0 for n in m["names"].values())
    assert "wrote" in capsys.readouterr().out


def test_decide_is_default_pointed_at_the_books_inputs_folder():
    assert D.INPUTS.parts[-3:] == ("paper_books", "m3o", "inputs")
    assert D.CHECKS.parts[-3:] == ("paper_books", "m3l_verifier", "out")


def test_decide_same_decision_is_unchanged_and_touches_nothing(decide, capsys):
    D.main()
    decide.path.write_text(decide.path.read_text(encoding="utf-8").replace('"to_build"', '"complete"', 1), encoding="utf-8")
    before = decide.path.read_bytes()
    capsys.readouterr()
    assert D.main() == 0
    assert "unchanged" in capsys.readouterr().out
    assert decide.path.read_bytes() == before


def test_decide_refuses_to_overwrite_a_different_decision(decide):
    D.main()
    before = decide.path.read_bytes()
    decide.state["res"] = {"run_id": "222", "output_commit": COMMIT, "decision_time_utc": "2026-10-31T21:00:00Z"}
    with pytest.raises(SystemExit) as e:
        D.main()
    assert "decision changed" in str(e.value)
    assert decide.path.read_bytes() == before


def test_decide_stops_without_a_verifier_record_and_writes_nothing(decide):
    for p in decide.checks.glob("check_*.json"):
        p.unlink()
    with pytest.raises(SystemExit) as e:
        D.main()
    assert "no check_new_runs record" in str(e.value)
    assert not decide.path.exists()


def test_decide_stops_when_the_ledger_has_no_decision(decide, monkeypatch):
    monkeypatch.setattr(FL, "decision_for", lambda t, runs: (None, None, "no verified run"))
    with pytest.raises(SystemExit) as e:
        D.main()
    assert "STOP: no verified run" in str(e.value)


# ---------------------------------------------------------------- packets

def fake_packet_run(tmp_path, calls, refuse=(), version="m3m.packet.builder.v7"):
    def run(argv, **kw):
        t = argv[argv.index("--ticker") + 1]
        calls.append((argv, kw))
        if t in refuse:
            return SimpleNamespace(stdout="", stderr="PacketError: no filing", returncode=1)
        pk = tmp_path / f"{t}.packet.json"
        pk.write_text(json.dumps({"builder_version": version}), encoding="utf-8")
        out = {"packet": str(pk), "packet_sha256": "sha_" + t, "annotations": ["trimmed x", "gc_passages_omitted 2"]}
        return SimpleNamespace(stdout="log line\n" + json.dumps(out), stderr="", returncode=0)
    return run


def test_packets_build_to_build_names_only_and_resume(tmp_path, monkeypatch):
    path = write_map(tmp_path / "inputs", {"AAA": "to_build", "BBB": "to_build", "CCC": "to_run", EXCL: "operator_excluded"})
    monkeypatch.setattr(P, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(book_paths, "screener_repo", lambda: tmp_path / "screener")
    calls = []
    monkeypatch.setattr(subprocess, "run", fake_packet_run(tmp_path, calls, refuse={"BBB"}))
    monkeypatch.setattr(sys, "argv", ["formation_packets.py", T])
    assert P.main() == 0
    m = load(path)
    a, b = m["names"]["AAA"], m["names"]["BBB"]
    assert (a["state"], a["packet_sha256"], a["trimmed"], a["gc_omitted"]) == ("to_run", "sha_AAA", 1, 1)
    assert (b["state"], b["reason"]) == ("analysis_incomplete", "packet_refused") and "no filing" in b["detail"]
    assert m["names"]["CCC"]["state"] == "to_run" and m["names"][EXCL]["state"] == "operator_excluded"
    assert m["builder_version"] == "m3m.packet.builder.v7"
    assert [c[0][c[0].index("--ticker") + 1] for c in calls] == ["AAA", "BBB"]
    argv, kw = calls[0]
    assert argv[:3] == [sys.executable, "-m", "qwen_c.packet"] and kw["cwd"] == P.ROOT == Path(P.__file__).resolve().parents[2]
    assert argv[argv.index("--screener-repo") + 1] == str(tmp_path / "screener") and "--online" in argv
    assert argv[argv.index("--commit") + 1] == COMMIT and argv[argv.index("--T") + 1] == "2026-10-30T21:00:00Z"
    calls.clear()                                                         # a rerun finds nothing to_build: no subprocess at all
    assert P.main() == 0 and calls == []


def test_packets_stop_on_a_builder_version_change(tmp_path, monkeypatch):
    write_map(tmp_path / "inputs", {"AAA": "to_build"}, builder_version="m3m.packet.builder.v6")
    monkeypatch.setattr(P, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(book_paths, "screener_repo", lambda: tmp_path / "screener")
    monkeypatch.setattr(subprocess, "run", fake_packet_run(tmp_path, []))
    monkeypatch.setattr(sys, "argv", ["formation_packets.py", T])
    with pytest.raises(SystemExit) as e:
        P.main()
    assert "built with m3m.packet.builder.v7" in str(e.value)


# ---------------------------------------------------------------- run

@pytest.fixture
def runner(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(R, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(R, "STATE", state)
    monkeypatch.setattr(R, "LOCK", state / "runner.lock")
    monkeypatch.setattr(R, "ollama_up", lambda: True)
    monkeypatch.setattr(sys, "argv", ["formation_run.py", T])
    yield SimpleNamespace(inputs=tmp_path / "inputs", state=state)
    R.release_lock()


def fake_runner(results, calls):
    def run(argv, **kw):
        calls.append((argv, kw))
        t = Path(argv[argv.index("-m") + 2]).stem.split(".")[0]
        res = results[t].pop(0)
        if res == "gpu_busy":
            return SimpleNamespace(stdout="", stderr="refused: gpu_busy", returncode=3)
        return SimpleNamespace(stdout="noise\n" + json.dumps(res, indent=1), stderr="", returncode=0)
    return run


def packet_map(runner, states):
    path = write_map(runner.inputs, states)
    m = load(path)
    for t, n in m["names"].items():
        n["packet"] = f"{t}.packet.json"
    path.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    return path


def test_run_complete_partial_retry_and_finished_flag(runner, monkeypatch):
    path = packet_map(runner, {"AAA": "to_run", "BBB": "to_run", "CCC": "pending", "DDD": "complete", EXCL: "operator_excluded"})
    calls = []
    results = {
        "AAA": [{"status": "complete", "run_id": "r1", "run_dir": "d1"}],
        "BBB": [{"status": "analysis_incomplete", "run_id": "r2", "run_dir": "d2", "incomplete_tasks": {"valuation": "x"}}],
        "CCC": [{"status": "analysis_incomplete", "run_id": "r3", "run_dir": "d3", "incomplete_tasks": {"material_events": "x"}}],
    }
    monkeypatch.setattr(subprocess, "run", fake_runner(results, calls))
    assert R.main() == 0
    R.release_lock()
    m = load(path)["names"]
    assert (m["AAA"]["state"], m["AAA"]["run_dir"]) == ("complete", "d1")
    assert m["BBB"]["state"] == "complete" and m["BBB"]["partial_analysis"] is True        # material_events ok: SPEC_m3o A1S
    assert (m["CCC"]["state"], m["CCC"]["attempts"]) == ("pending", 1)                      # first failure: retried
    assert m["DDD"]["state"] == "complete" and m[EXCL]["state"] == "operator_excluded"
    assert [c[0][0] for c in calls] == [sys.executable] * 3 and all(c[1]["cwd"] == R.ROOT for c in calls)
    assert calls[0][0][1:3] == ["-m", "qwen_c.runner"] and calls[0][0][-2:] == ["--seed-base", "1000"]
    assert not (runner.state / f"finished_{T}.flag").exists()
    results["CCC"].append({"status": "analysis_incomplete", "run_id": "r4", "run_dir": "d4", "incomplete_tasks": {"material_events": "x"}})
    calls.clear()
    assert R.main() == 0                                                                    # resumes: only CCC is left
    m = load(path)["names"]
    assert [c[0][3] for c in calls] == ["CCC.packet.json"]
    assert (m["CCC"]["state"], m["CCC"]["reason"], m["CCC"]["attempts"]) == ("analysis_incomplete", "runner_attempts", 2)
    assert (runner.state / f"finished_{T}.flag").read_text() == "done"


def test_run_gpu_busy_stops_without_counting_an_attempt(runner, monkeypatch):
    path = packet_map(runner, {"AAA": "to_run"})
    monkeypatch.setattr(subprocess, "run", fake_runner({"AAA": ["gpu_busy"]}, []))
    assert R.main() == 3
    n = load(path)["names"]["AAA"]
    assert (n["state"], n["attempts"]) == ("to_run", 0)
    assert not (runner.state / f"finished_{T}.flag").exists()


def test_run_does_nothing_while_another_live_process_holds_the_lock(runner, monkeypatch):
    path = packet_map(runner, {"AAA": "to_run"})
    runner.state.mkdir(parents=True)
    R.LOCK.write_text(str(R.os.getpid()))                                                   # a live pid (this one)
    calls = []
    monkeypatch.setattr(subprocess, "run", fake_runner({"AAA": []}, calls))
    assert R.main() == 0 and calls == []
    assert load(path)["names"]["AAA"]["state"] == "to_run"
    R.LOCK.unlink()


def test_run_state_folder_is_the_gitignored_cache():
    assert R.STATE == Path(R.__file__).resolve().parents[2] / "cache" / "paper_books" / "formation"


# ---------------------------------------------------------------- freeze

def test_freeze_copies_the_map_writes_the_witness_and_refuses_a_second_freeze(tmp_path, monkeypatch, capsys):
    inputs, witness = tmp_path / "inputs", tmp_path / "witness"
    path = write_map(inputs, {"AAA": "complete", "BBB": "to_run", "CCC": "analysis_incomplete", EXCL: "operator_excluded"})
    monkeypatch.setattr(Z, "INPUTS", inputs)
    monkeypatch.setattr(Z, "WITNESS", witness)
    monkeypatch.setattr(sys, "argv", ["formation_freeze.py", T])
    assert Z.main() == 0
    frozen = inputs / f"formation_{T}.frozen.json"
    assert frozen.read_bytes() == path.read_bytes()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    line = (witness / f"formation_{T}.txt").read_text(encoding="utf-8")
    assert line.endswith("\n") and line == capsys.readouterr().out
    assert line.startswith(f"formation {T} map_sha256 {sha} run 111 T 2026-10-30T21:00:00Z complete 1 pending 1 incomplete 1 operator_excluded 1 frozen_at ")
    path.write_text(path.read_text(encoding="utf-8").replace('"to_run"', '"complete"'), encoding="utf-8")   # the runner kept working
    with pytest.raises(SystemExit) as e:
        Z.main()
    assert "exists" in str(e.value)
    assert frozen.read_bytes() != path.read_bytes() and (witness / f"formation_{T}.txt").read_text(encoding="utf-8") == line


def test_freeze_default_witness_folder_is_in_the_books():
    assert Z.WITNESS.parts[-3:] == ("paper_books", "m3o", "witness")


def test_a_frozen_formation_with_names_left_to_run_does_not_hold_the_gpu(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    path = write_map(inputs, {"AAA": "complete", "BBB": "to_run"})
    monkeypatch.setattr(R, "INPUTS", inputs)
    monkeypatch.setattr(R, "STATE", tmp_path / "state")
    assert R.formation_waiting()
    (inputs / f"formation_{T}.frozen.json").write_bytes(path.read_bytes())   # frozen at its fill: BBB is cash for good
    assert not R.formation_waiting()

"""formation_run_cloud.py and publish_books.py: synthetic maps in a temp folder, a stub reader (no network, no Gemini, no Claude, no Ollama, no git
remote). Run from the repo root:  python -m pytest tools/paper_books/tests -q"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formation_run as FR  # noqa: E402
import formation_run_cloud as CR  # noqa: E402
import m3o_engine as E  # noqa: E402
import publish_books as PB  # noqa: E402
import qwen_site  # noqa: E402
from test_formation import EXCL, T, load, write_map  # noqa: E402

G, runner = CR.G, CR.runner
GEM, SON = G.ARMS["gemini"]["model"], G.ARMS["sonnet"]["model"]


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    state, site = tmp_path / "state", tmp_path / "site"
    monkeypatch.setattr(FR, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(FR, "STATE", state)
    monkeypatch.setattr(CR, "RUNS", tmp_path / "m3m_formation")
    monkeypatch.setattr(G, "SITE", site)
    monkeypatch.setattr(G, "LOCK", site / "worker.lock")
    monkeypatch.setattr(G, "log", lambda msg: None)
    swaps = []
    monkeypatch.setattr(G, "swap", lambda: swaps.append(G.ARM))
    left = {"gemini": 0.5, "sonnet": 0.5}
    monkeypatch.setattr(G, "meter", lambda: {k: (left[G.ARM], None) for k in G.FLOORS})
    calls = []
    results = {}

    def run(packet, *, seed, task_ids):
        t = Path(packet).name.split(".")[0]
        calls.append({"ticker": t, "seed": seed, "task_ids": task_ids, "root": runner.M3M_DIR, "arm": G.ARM})
        res = results[t].pop(0)
        if isinstance(res, BaseException):
            raise res
        return res

    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(runner, "M3M_DIR", runner.M3M_DIR)                  # restored at teardown whatever the code assigns
    monkeypatch.setattr(sys, "argv", ["formation_run_cloud.py"])
    yield SimpleNamespace(inputs=tmp_path / "inputs", state=state, site=site, left=left, calls=calls, results=results, swaps=swaps, tmp=tmp_path)
    G.set_arm("gemini")


def packet_map(c, states):
    path = write_map(c.inputs, states)
    m = load(path)
    for t, n in m["names"].items():
        n["packet"] = f"{t}.packet.json"
    path.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    return path


def ok(t):
    return {"status": "complete", "run_id": f"r_{t}", "run_dir": f"d_{t}", "incomplete_tasks": {}}


def failed(t):
    return {"status": "failed", "run_id": f"f_{t}", "run_dir": f"fd_{t}", "incomplete_tasks": {"material_events": "malformed"}}


def test_a_read_ok_is_complete_with_its_reader_and_only_the_book_task_is_read(cloud):
    path = packet_map(cloud, {"AAA": "to_run", "BBB": "complete", EXCL: "operator_excluded"})
    cloud.results["AAA"] = [ok("AAA")]
    assert CR.main([]) == 0
    m = load(path)["names"]
    assert (m["AAA"]["state"], m["AAA"]["run_dir"], m["AAA"]["reader"], m["AAA"].get("partial_analysis")) == ("complete", "d_AAA", GEM, None)
    assert m["AAA"]["runs"][-1]["reader"] == GEM and m["AAA"]["attempts"] == 1
    assert m["BBB"]["state"] == "complete" and m[EXCL]["state"] == "operator_excluded"
    assert cloud.calls == [{"ticker": "AAA", "seed": 1000, "task_ids": ["material_events"], "root": cloud.tmp / "m3m_formation", "arm": "gemini"}]
    assert cloud.swaps == ["gemini"]                                         # the model call is swapped before the read, per name


def test_a_name_goes_to_sonnet_when_gemini_is_under_its_floor_and_the_reader_says_so(cloud):
    path = packet_map(cloud, {"AAA": "to_run", "BBB": "to_run"})
    cloud.left["gemini"] = 0.0
    cloud.results.update(AAA=[ok("AAA")], BBB=[ok("BBB")])
    assert CR.main([]) == 0
    m = load(path)["names"]
    assert (m["AAA"]["reader"], m["BBB"]["reader"]) == (SON, SON)
    assert [c["arm"] for c in cloud.calls] == ["sonnet", "sonnet"] and cloud.swaps == ["sonnet", "sonnet"]
    assert not (cloud.site / "worker.lock").exists()


def test_a_failed_read_counts_an_attempt_and_after_the_limit_the_name_is_analysis_incomplete(cloud):
    path = packet_map(cloud, {"AAA": "to_run"})
    cloud.results["AAA"] = [failed("AAA"), failed("AAA")]
    assert CR.main([]) == 0
    n = load(path)["names"]["AAA"]
    assert (n["state"], n["attempts"]) == ("pending", 1) and not (cloud.state / f"finished_{T}.flag").exists()
    assert CR.main([]) == 0
    n = load(path)["names"]["AAA"]
    assert (n["state"], n["reason"], n["attempts"], n["reader"]) == ("analysis_incomplete", "runner_attempts", 2, GEM)
    assert (cloud.state / f"finished_{T}.flag").read_text() == "done"


def test_a_refused_packet_is_a_failed_attempt_with_its_cause(cloud):
    path = packet_map(cloud, {"AAA": "to_run"})
    cloud.results["AAA"] = [runner.RunRefused("packet unreadable: x")]
    assert CR.main([]) == 0
    n = load(path)["names"]["AAA"]
    assert (n["state"], n["attempts"], n["runs"][-1]["run_id"]) == ("pending", 1, None) and "RunRefused: packet unreadable" in n["runs"][-1]["stderr_tail"]


def test_a_finished_name_is_not_read_again_and_the_flag_waits_for_the_last_name(cloud):
    path = packet_map(cloud, {"AAA": "to_run", "BBB": "to_run", "CCC": "to_run"})
    cloud.results.update(AAA=[ok("AAA")], BBB=[ok("BBB")], CCC=[ok("CCC")])
    assert CR.main(["--limit", "1"]) == 0
    assert [c["ticker"] for c in cloud.calls] == ["AAA"] and not (cloud.state / f"finished_{T}.flag").exists()
    assert CR.main(["--limit", "1"]) == 0
    assert [c["ticker"] for c in cloud.calls] == ["AAA", "BBB"] and not (cloud.state / f"finished_{T}.flag").exists()   # a limited pass never writes it
    assert CR.main([]) == 0
    assert [c["ticker"] for c in cloud.calls] == ["AAA", "BBB", "CCC"]                                                 # AAA and BBB were not read again
    assert (cloud.state / f"finished_{T}.flag").read_text() == "done"
    assert {n["state"] for n in load(path)["names"].values()} == {"complete"}


def test_an_allowance_under_the_floor_stops_before_a_name_and_leaves_the_map_as_it_was(cloud):
    path = packet_map(cloud, {"AAA": "to_run", "BBB": "to_run"})
    before = path.read_text(encoding="utf-8")
    cloud.left.update(gemini=0.0, sonnet=0.0)
    assert CR.main([]) == 3
    assert path.read_text(encoding="utf-8") == before and cloud.calls == []
    assert not (cloud.site / "worker.lock").exists() and not (cloud.state / f"finished_{T}.flag").exists()


def test_an_allowance_stop_in_the_middle_of_a_read_leaves_that_name_and_the_unread_ones_unchanged(cloud):
    path = packet_map(cloud, {"AAA": "to_run", "BBB": "to_run", "CCC": "pending"})
    cloud.results.update(AAA=[ok("AAA")], BBB=[CR.AllowanceStop("under the floor")], CCC=[ok("CCC")])
    assert CR.main([]) == 3
    m = load(path)["names"]
    assert m["AAA"]["state"] == "complete"
    assert (m["BBB"]["state"], m["BBB"]["attempts"], "runs" in m["BBB"]) == ("to_run", 0, False)
    assert (m["CCC"]["state"], m["CCC"]["attempts"], "runs" in m["CCC"]) == ("pending", 0, False)
    assert [c["ticker"] for c in cloud.calls] == ["AAA", "BBB"] and not (cloud.state / f"finished_{T}.flag").exists()
    assert not (cloud.site / "worker.lock").exists() and G.wait_for_quota is not CR.stop_at_floor


def test_the_swapped_wait_for_quota_stops_the_read_only_when_an_allowance_is_low(cloud):
    CR.stop_at_floor()
    cloud.left["gemini"] = 0.0
    with pytest.raises(CR.AllowanceStop):
        CR.stop_at_floor()
    assert not isinstance(CR.AllowanceStop(), Exception)                     # the runner's `except Exception` must not turn it into a task status


def test_the_worker_lock_is_shared_and_released(cloud):
    path = packet_map(cloud, {"AAA": "to_run"})
    cloud.site.mkdir(parents=True)
    (cloud.site / "worker.lock").write_text(str(os.getpid()))                # a live holder: the site worker
    assert CR.main([]) == 0
    assert cloud.calls == [] and load(path)["names"]["AAA"]["state"] == "to_run"
    assert (cloud.site / "worker.lock").read_text() == str(os.getpid())      # not taken over, not removed
    (cloud.site / "worker.lock").write_text("999999999")                     # a dead pid: taken over, then released
    cloud.results["AAA"] = [ok("AAA")]
    assert CR.main([]) == 0 and len(cloud.calls) == 1 and not (cloud.site / "worker.lock").exists()


def test_dry_run_lists_the_names_and_reads_nothing(cloud, capsys):
    path = packet_map(cloud, {"AAA": "to_run", "BBB": "pending", "CCC": "complete"})
    before = path.read_text(encoding="utf-8")
    assert CR.main(["--dry-run", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 name(s)" in out and "AAA" in out and "BBB" not in out
    assert path.read_text(encoding="utf-8") == before and cloud.calls == [] and not cloud.state.exists() and not cloud.site.exists()


def test_the_default_map_is_the_newest_live_one(cloud):
    cloud.inputs.mkdir()
    for name, extra in (("formation_2026-10-30.json", {}), ("formation_2026-11-30.json", {}), ("formation_2026-12-31.json", {"label": "retrospective"}),
                        ("formation_2027-01-29.json", {})):
        (cloud.inputs / name).write_text(json.dumps(dict(names={}, **extra)), encoding="utf-8")
    (cloud.inputs / "formation_2027-01-29.frozen.json").write_text("{}", encoding="utf-8")
    (cloud.inputs / "formation_2026-11-30_superseded_9.json").write_text("{}", encoding="utf-8")
    assert CR.newest_map().name == "formation_2026-11-30.json"


# ---------------------------------------------------------------- the engine reads what the cloud path writes

def test_the_engine_accepts_a_run_written_by_the_cloud_path(cloud, monkeypatch):
    packet = cloud.tmp / "AAA.packet.json"
    packet.write_text(json.dumps({"contract": "m3m.packet.v1", "ticker": "AAA", "decision_time_utc": "2026-10-30T21:00:00Z",
                                  "evidence": [{"fact_id": "F1", "text": "x"}]}), encoding="utf-8")
    path = packet_map(cloud, {"AAA": "to_run"})
    m = load(path)
    m["names"]["AAA"]["packet"] = str(packet)
    path.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    monkeypatch.undo()                                                      # the real runner.run, with only its server and task calls stubbed
    monkeypatch.setattr(FR, "INPUTS", cloud.inputs)
    monkeypatch.setattr(FR, "STATE", cloud.state)
    monkeypatch.setattr(CR, "RUNS", cloud.tmp / "m3m_formation")
    monkeypatch.setattr(G, "SITE", cloud.site)
    monkeypatch.setattr(G, "LOCK", cloud.site / "worker.lock")
    monkeypatch.setattr(G, "log", lambda msg: None)
    monkeypatch.setattr(G, "meter", lambda: {k: (0.5, None) for k in G.FLOORS})
    monkeypatch.setattr(G, "swap", lambda: None)
    monkeypatch.setattr(runner, "M3M_DIR", cloud.tmp / "wrong")
    monkeypatch.setattr(runner, "MODEL", f"{GEM} via agy")
    monkeypatch.setattr(runner, "gpu_preflight", lambda url: [])
    monkeypatch.setattr(runner, "model_show", lambda url: {"swapped_for": "stub"})
    monkeypatch.setattr(runner.ollama_raw, "ollama_version", lambda base: "not used")
    monkeypatch.setattr(runner, "git_state", lambda: ("c" * 40, False))
    monkeypatch.setattr(runner, "_run_task", lambda task, idx, *a, **k: ({"status": "ok", "attempts": 1, "claims": [], "unknowns": []},
                                                                           {"status": "ok", "seed": 1000 + idx, "seconds": 0.0, "attempts": []}))
    assert CR.main([]) == 0
    n = load(path)["names"]["AAA"]
    assert n["state"] == "complete" and n["reader"] == GEM and Path(n["run_dir"]).parent == cloud.tmp / "m3m_formation" / "runs"
    info = E.read_run("AAA", n, "2026-10-30T21:00:00Z")                      # ticker and decision time match, analysis.json hashes to the manifest's
    assert info["me_status"] == "ok" and info["finished"] is not None and info["analysis_sha"] == info["manifest"]["analysis_sha256"]
    assert info["manifest"]["tasks_requested"] == ["material_events"] and info["manifest"]["model"]["tag"] == f"{GEM} via agy"
    with pytest.raises(E.Stop):
        E.read_run("AAA", n, "2026-10-31T21:00:00Z")


# ---------------------------------------------------------------- publish_books

BOOKS = {"schema": "m3o_books_v1", "formation": T, "decision_time_utc": "2026-10-30T21:00:00Z", "slots": 2, "generated_at": "2026-10-30T21:00:00Z",
         "note": "n", "books": {"code_book": {"AAA": 50.0, "BBB": 50.0}, "qwen_book": {"AAA": 50.0}}}
OLD = {**BOOKS, "formation": "2026-09-30", "books": {"code_book": {"AAA": 100.0}, "qwen_book": {"AAA": 100.0}}, "slots": 1}


@pytest.fixture
def publish(tmp_path, monkeypatch):
    repo, out = tmp_path / "screener", tmp_path / "site"
    (repo / "public" / "data").mkdir(parents=True)
    git = []

    def run(argv, **kw):
        a = argv[3:]
        git.append(a)
        if a[:2] == ["remote", "get-url"]:
            return SimpleNamespace(stdout="https://example.test/org/stock-screener.git\n", stderr="", returncode=0)
        if a[0] == "show":
            return SimpleNamespace(stdout=json.dumps(OLD), stderr="", returncode=0)
        if a[:3] == ["diff", "--cached", "--quiet"]:
            return SimpleNamespace(stdout="", stderr="", returncode=1)       # something is staged
        return SimpleNamespace(stdout="abc1234\n" if a[0] == "rev-parse" else "", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(PB.book_paths, "screener_repo", lambda: repo)
    monkeypatch.setattr(PB.qwen_site, "books", lambda t: BOOKS)
    monkeypatch.setattr(PB.qwen_site, "OUT", out)
    monkeypatch.setattr(PB.qwen_site, "LOCK", out / "unused.lock")
    monkeypatch.setattr(PB.G, "_main_checkout", lambda: tmp_path)
    (tmp_path / "cache").mkdir()
    return SimpleNamespace(repo=repo, out=out, git=git, tmp=tmp_path)


def test_publish_dry_run_writes_only_the_one_file_and_changes_nothing_in_the_clone(publish, capsys):
    assert PB.main([T, "--dry-run"]) == 0
    assert sorted(p.name for p in publish.out.iterdir()) == ["m3o_books.json"]
    assert json.loads((publish.out / "m3o_books.json").read_text(encoding="utf-8")) == BOOKS
    said = capsys.readouterr().out
    assert "formation 2026-09-30 -> " + T in said and "code_book: 1 -> 2 names, added 1, removed 0, weight changed 1" in said
    assert [a[0] for a in publish.git] == ["remote", "fetch", "show"]       # nothing staged, committed, reset or pushed
    assert not (publish.repo / "public" / "data" / "m3o_books.json").exists() and not (publish.tmp / "cache" / "screener_publish.lock").exists()


def test_publish_commits_the_one_file_by_pathspec_and_pushes(publish):
    assert PB.main([T]) == 0
    assert (publish.repo / PB.REL).read_text(encoding="utf-8") == (publish.out / "m3o_books.json").read_text(encoding="utf-8")
    cmds = [" ".join(a) for a in publish.git]
    assert f"status --porcelain -- :!{PB.REL}" in cmds and f"add -- {PB.REL}" in cmds
    assert any(c.startswith("-c commit.gpgsign=false commit -m") and c.endswith(f"-- {PB.REL}") for c in cmds)
    assert "push origin main" in cmds and not any("qwen_overlay" in c or "qwen_reports" in c for c in cmds)
    assert sorted(p.name for p in publish.out.iterdir()) == ["m3o_books.json"]


def test_publish_refuses_a_clone_with_other_changes(publish, monkeypatch):
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout=" M public/data/qwen_overlay.json\n", stderr="", returncode=0)
                        if argv[3] == "status" else real(argv, **kw))
    with pytest.raises(SystemExit) as e:
        PB.main([T])
    assert "unexpected local changes" in str(e.value)
    assert not any(a[0] in ("add", "commit", "push") for a in publish.git)

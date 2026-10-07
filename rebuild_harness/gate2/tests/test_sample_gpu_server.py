"""The sample drawer, the GPU wait, the guard and the server lifecycle (all machine seams faked: no GPU, no server, no nvidia-smi)."""
import hashlib
import json
from pathlib import Path

import pytest

from rebuild_harness.gate2 import config, gpu, guard, server
from rebuild_harness.gate2 import sample as sm
from rebuild_harness.gate2.tests import fakes
from valuation.muse.runner import MuseTransportError


# ---- the sample -------------------------------------------------------------------------------------------------------------------------

def universe(n_op=700, n_fin=200, n_com=100):
    out = []
    for i in range(n_op):
        out.append({"cik": f"{i + 1:010d}", "ticker": f"O{i}", "family": "operating"})
    for i in range(n_fin):
        out.append({"cik": f"{10000 + i:010d}", "ticker": f"F{i}", "family": "financial"})
    for i in range(n_com):
        out.append({"cik": f"{20000 + i:010d}", "ticker": f"C{i}", "family": "commodity"})
    return out


def test_allocate_is_proportional_whole_and_sums_to_the_total():
    a = sm.allocate({"operating": 700, "financial": 200, "commodity": 100}, 120)
    assert a == {"operating": 84, "financial": 24, "commodity": 12} and sum(a.values()) == 120
    b = sm.allocate({"operating": 3, "financial": 1}, 120)
    assert b == {"operating": 3, "financial": 1}                       # never more than a family has
    c = sm.allocate({"a": 1, "b": 1, "c": 1}, 2)
    assert sum(c.values()) == 2 and c == {"a": 1, "b": 1, "c": 0}      # ties go to the name that sorts first
    assert sm.allocate({"x": 0}, 5) == {"x": 0}


def test_the_draw_is_stratified_random_deterministic_and_without_duplicates():
    u = universe()
    r1, r2 = sm.draw_date(u, "2025-10-31"), sm.draw_date(list(reversed(u)), "2025-10-31")
    assert r1 == r2                                                    # does not depend on the order the universe was listed in
    ents = r1["entries"]
    assert len(ents) == 120 and len({e["cik"] for e in ents}) == 120
    from collections import Counter
    assert Counter(e["family"] for e in ents) == {"operating": 84, "financial": 24, "commodity": 12}
    assert [e["cik"] for e in ents] != sorted(e["cik"] for e in ents)  # shuffled, not sorted
    other = sm.draw_date(u, "2025-12-31")
    assert {e["cik"] for e in other["entries"]} != {e["cik"] for e in ents}      # a different date draws differently
    assert sm.draw_date(u, "2025-10-31", seed=1)["entries"] != ents                 # the seed matters


def test_a_universe_with_an_unbuilt_family_or_a_duplicate_is_refused():
    with pytest.raises(sm.SampleError):
        sm.draw_date([{"cik": "1", "family": "reit"}], "d")
    with pytest.raises(sm.SampleError):
        sm.draw_date([{"cik": "1", "family": "operating"}, {"cik": "0000000001", "family": "operating"}], "d")


def test_the_sample_is_written_once_with_its_sha256_and_never_redrawn(tmp_path):
    uni = {d: universe() for d in config.DATES}
    s = sm.draw(uni)
    assert set(s["entries"]) == set(config.DATES) and all(len(v) == 120 for v in s["entries"].values()) and s["seed"] == 20261007
    path = sm.sample_path(tmp_path)
    sha = sm.write_once(path, s)
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest() and json.loads(path.with_name("sample.json.sha256").read_text())["sha256"] == sha
    before = path.read_bytes()
    with pytest.raises(sm.SampleExists):
        sm.write_once(path, sm.draw(uni, seed=1))
    assert path.read_bytes() == before                                   # nothing was overwritten
    assert sm.load_verified(path)["entries"] == json.loads(json.dumps(s["entries"]))
    path.write_bytes(before.replace(b"20261007", b"20261008"))           # a tampered sample is refused
    with pytest.raises(sm.SampleError):
        sm.load_verified(path)


def test_the_cli_refuses_to_redraw(tmp_path):
    ctx = config.state_paths(tmp_path)["ctx"]
    ctx.mkdir(parents=True)
    for d in config.DATES:
        (ctx / f"universe_{d}.json").write_text(json.dumps({"companies": universe()}))
    assert sm.main(["draw", "--state-dir", str(tmp_path)]) == 0
    assert sm.main(["draw", "--state-dir", str(tmp_path)]) == 5
    assert sm.main(["verify", "--state-dir", str(tmp_path)]) == 0


def test_pilot_is_ten_from_the_first_date_the_control_is_thirty_and_both_are_in_the_sample():
    s = sm.draw({d: universe() for d in config.DATES})
    pil = sm.pilot_jobs(s)
    allj = sm.jobs(s)
    assert len(pil) == 10 and {j["date"] for j in pil} == {"2025-10-31"} and pil == allj[:10]
    ctl = sm.masked_control(s)
    assert len(ctl) == 30 and all(j in allj for j in ctl) and ctl == sm.masked_control(s)
    assert [j["date"] for j in allj] == sorted(j["date"] for j in allj)


# ---- the GPU wait -----------------------------------------------------------------------------------------------------------------------

class P(gpu.Probe):
    def __init__(self, loaded=(), apps=(), used=300, alive=False):
        self._l, self._a, self._u, self._alive = list(loaded), list(apps), used, alive

    def ollama_loaded(self):
        return self._l

    def compute_apps(self):
        return self._a

    def used_mib(self):
        return self._u

    def pid_alive(self, pid):
        return self._alive


def test_other_gpu_use_names_each_reason(tmp_path):
    nolock = tmp_path / "none.lock"
    assert gpu.other_gpu_use(P(), lock_path=nolock) is None
    assert "Ollama has a model loaded" in gpu.other_gpu_use(P(loaded=["rs2-analyst"]), lock_path=nolock)
    assert "another process" in gpu.other_gpu_use(P(apps=[(77, "game.exe")]), lock_path=nolock)
    assert gpu.other_gpu_use(P(apps=[(55, "ollama.exe")]), lock_path=nolock) is None            # an ollama process alone: its models are checked by the rule above
    assert gpu.other_gpu_use(P(apps=[(99, "llama-server.exe")]), ours_pids=[99], ours_loaded=True, our_mib=300, lock_path=nolock) is None
    assert "another process" in gpu.other_gpu_use(P(apps=[(98, "llama-server.exe")]), ours_pids=[99], ours_loaded=True, lock_path=nolock)
    assert "VRAM in use with nothing of ours loaded" in gpu.other_gpu_use(P(used=5000), lock_path=nolock)
    assert gpu.other_gpu_use(P(used=22000), ours_loaded=True, our_mib=21800, lock_path=nolock) is None      # ours
    assert "more than our server took" in gpu.other_gpu_use(P(used=26000), ours_loaded=True, our_mib=21800, lock_path=nolock)
    class Unreadable(P):
        def used_mib(self):
            return None
    assert "not known to be idle" in gpu.other_gpu_use(Unreadable(), lock_path=nolock)
    class NoApps(P):
        def compute_apps(self):
            return None
    assert "cannot list" in gpu.other_gpu_use(NoApps(), lock_path=nolock)
    lock = tmp_path / "gpu_tests.lock"
    lock.write_text("1234")
    assert "GPU-test lock" in gpu.other_gpu_use(P(alive=True), lock_path=lock)
    assert gpu.other_gpu_use(P(alive=False), lock_path=lock) is None                              # a dead holder does not block


def test_wait_until_free_polls_reports_changes_once_and_never_gives_up():
    seq = iter(["a", "a", "b", None])
    seen, slept = [], []
    n = gpu.wait_until_free(lambda: next(seq), sleep=lambda s: slept.append(s), poll=5, on_change=seen.append)
    assert n == 3 and seen == ["a", "b"] and slept == [5, 5, 5]
    with pytest.raises(TimeoutError):
        gpu.wait_until_free(lambda: "busy", sleep=lambda s: None, max_polls=4)


# ---- the guard ----------------------------------------------------------------------------------------------------------------------------

class Echo:
    def __init__(self):
        self.seen = []

    def chat(self, req):
        self.seen.append(req)
        return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_the_guard_lowers_the_cap_to_fit_the_window_and_refuses_when_there_is_no_room(tmp_path):
    inner = Echo()
    g = guard.ContextGuardClient(inner, window=10000, margin=500, floor=1000, chars_per_token=3.0, log_path=tmp_path / "g.jsonl")
    g.chat({"messages": [{"role": "user", "content": "x" * 3000}], "max_tokens": 4000})
    assert inner.seen[-1]["max_tokens"] == 4000                        # room: 10000 - 1001 - 500
    g.chat({"messages": [{"role": "user", "content": "x" * 24000}], "max_tokens": 4000})
    assert inner.seen[-1]["max_tokens"] == 10000 - 8001 - 500          # lowered to what is left
    with pytest.raises(guard.ContextOverflow) as e:
        g.chat({"messages": [{"role": "user", "content": "x" * 27000}], "max_tokens": 4000})
    assert str(e.value).startswith(guard.OVERFLOW_PREFIX) and isinstance(e.value, MuseTransportError) and len(inner.seen) == 2
    log = [json.loads(x) for x in (tmp_path / "g.jsonl").read_text().splitlines()]
    assert [x.get("lowered") for x in log[:2]] == [False, True] and log[2]["refused"] == "context_overflow"


def test_the_timer_adds_up_seconds_and_tokens():
    t = guard.TimedClient(Echo(), clock=fakes.Clock())
    t.chat({"messages": []})
    t.chat({"messages": []})
    s = t.summary()
    assert s["n_calls"] == 2 and s["prompt_tokens"] == 20 and s["completion_tokens"] == 10 and s["model_seconds"] > 0 and s["max_prompt_tokens"] == 10


# ---- the server ---------------------------------------------------------------------------------------------------------------------------

def fake_cfg(tmp_path):
    b = tmp_path / "build"
    b.mkdir()
    (b / "llama-server.exe").write_bytes(b"exe")
    (b / "ggml.dll").write_bytes(b"dll")
    m, d = tmp_path / "model.gguf", tmp_path / "drafter.gguf"
    m.write_bytes(b"M" * 2048)
    d.write_bytes(b"D" * 512)
    h = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    _e, msha = server.build_manifest(b, h)
    cfg = {"build": "b11272", "server_exe": str(b / "llama-server.exe"), "build_manifest_sha256": msha, "model_path": str(m), "model_sha256": h(m), "drafter_path": str(d),
           "drafter_sha256": h(d), "host": "127.0.0.1", "port": 8080, "load_timeout_s": 5}
    line = lambda c: f'"{c["server_exe"]}" -m "{c["model_path"]}" --port {c["port"]} -np 1 -ngl 99 -c 98304 -fa on --temp 1.0 -md "{c["drafter_path"]}" --spec-draft-n-max 15'
    cfg["server_cmdline_sha256"] = hashlib.sha256(line(cfg).encode()).hexdigest()
    return cfg, line


def test_the_gate2_line_differs_from_the_pinned_one_in_the_window_only(tmp_path):
    cfg, line = fake_cfg(tmp_path)
    wd = server.window_difference(cfg, line)
    assert " -c 32768 " in wd["gate2_cmdline"] and " -c 98304 " in wd["pinned_cmdline"]
    assert wd["pinned_line_matches_config_pin"] and wd["equal_after_the_window_is_equalised"]
    assert wd["gate2_cmdline"].replace("-c 32768", "-c 98304") == wd["pinned_cmdline"]
    with pytest.raises(server.ServerRefusal):
        server.gate2_cmdline(cfg, lambda c: "llama-server -c 4096 -x")


class FakeProc:
    pid = 4321
    returncode = None

    def poll(self):
        return None


def make_server(tmp_path, cfg, line, *, log_text=None, used=None, health=True, alive=None):
    state = {"alive": alive if alive is not None else set(), "killed": [], "used": used or [300, 22300], "i": 0}

    def spawn(cmd, log_path):
        state["cmd"] = cmd
        Path(log_path).write_text(log_text if log_text is not None else "n_ctx_slot = 32768\nspec n_max=15\nload_tensors: offloaded 49/49 layers to GPU\n")
        state["alive"].add(4321)
        return FakeProc()

    def gpu_used():
        if state["killed"]:
            return 300                                       # the memory is released once the server is killed
        v = state["used"][min(state["i"], len(state["used"]) - 1)]
        state["i"] += 1
        return v

    def kill(pid):
        state["killed"].append(pid)
        state["alive"].discard(pid)
    s = server.Gate2Server(cfg, tmp_path, spawn=spawn, health=lambda url, timeout=2.0: health, gpu_used=gpu_used, port_free=lambda h, p: True, kill=kill,
                           pid_alive=lambda pid: pid in state["alive"], image_name=lambda pid: "llama-server.exe", sleep=lambda x: None, build_cmd=line)
    return s, state


def test_start_refuses_without_pins_then_starts_records_and_stops_only_our_server(tmp_path):
    cfg, line = fake_cfg(tmp_path)
    s, st = make_server(tmp_path, cfg, line)
    with pytest.raises(server.ServerRefusal, match="no pins record"):
        s.start()
    server.record_pins(cfg, tmp_path)
    assert server.pins_problems(cfg, tmp_path) == []
    rec = s.start()
    assert st["cmd"] == server.gate2_cmdline(cfg, line) and rec["window"] == 32768 and rec["vram_baseline_mib"] == 300 and rec["vram_loaded_mib"] == 22300
    assert s.is_up() and s.our_pids() == [4321] and s.our_vram_mib() == 22300
    ok, detail = s.stop()
    assert ok and st["killed"] == [4321] and not s.is_up() and s.read_engine() is None
    assert list(config.state_paths(tmp_path)["server"].glob("engine_stopped_*.json"))              # moved aside, not deleted


def test_start_refuses_a_busy_card_a_wrong_window_a_partial_offload_and_a_changed_model(tmp_path):
    cfg, line = fake_cfg(tmp_path)
    server.record_pins(cfg, tmp_path)
    s, st = make_server(tmp_path, cfg, line, used=[5000])
    with pytest.raises(server.ServerRefusal, match="not free"):
        s.start()
    s, st = make_server(tmp_path, cfg, line, log_text="n_ctx_slot = 98304\nn_max=15\n")
    with pytest.raises(server.ServerRefusal, match="n_ctx_slot = 32768"):
        s.start()
    assert st["killed"] == [4321]                                           # a failed start leaves no server
    s, st = make_server(tmp_path, cfg, line, log_text="n_ctx_slot = 32768\nn_max=15\nload_tensors: offloaded 30/49 layers to GPU\n")
    with pytest.raises(server.ServerRefusal, match="offloaded"):
        s.start()
    Path(cfg["model_path"]).write_bytes(b"changed" * 400)
    assert any("changed since the pins were recorded" in p for p in server.pins_problems(cfg, tmp_path))
    s, st = make_server(tmp_path, cfg, line)
    with pytest.raises(server.ServerRefusal, match="changed since"):
        s.start()


def test_record_pins_refuses_a_file_that_is_not_the_pinned_one(tmp_path):
    cfg, line = fake_cfg(tmp_path)
    cfg = dict(cfg, model_sha256="0" * 64)
    with pytest.raises(server.ServerRefusal, match="not the pinned"):
        server.record_pins(cfg, tmp_path)


def test_stop_never_kills_a_process_that_is_not_the_pinned_server(tmp_path):
    cfg, line = fake_cfg(tmp_path)
    server.record_pins(cfg, tmp_path)
    s, st = make_server(tmp_path, cfg, line)
    s.start()
    s.image_name = lambda pid: "game.exe"                                  # the pid now belongs to another program
    ok, _ = s.stop(timeout=0.0)
    assert st["killed"] == []

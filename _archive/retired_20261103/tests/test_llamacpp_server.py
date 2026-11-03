"""Muse integration, M3 and M8 item 4: the lifecycle of llama-server, against a mock server PROCESS (a real process that can be
killed and can leave a child behind: tests/fixtures/mock_llama_server_process.py) with nvidia-smi and Ollama's /api/ps mocked.
No GPU, no model, no llama-server: the launch is replaced by the mock, and every pin is computed from small temporary files.

Covered: every start() refusal; the health wait; the readiness checks (log, GPU band); stop() killing the tree and waiting for
the memory; engine.json written atomically and removed; the provider's engine_not_ready refusal; a server killed mid-request
and restored; the command line and the manifest format against P7's and the reviewer's pins."""
import copy
import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llamacpp_server as S  # noqa: E402
import llm_provider as prov  # noqa: E402
import ops  # noqa: E402
import rs2_data  # noqa: E402
from llamacpp_fakes import chat_body, loopback_urlopen  # noqa: E402

MOCK = ROOT / "tests" / "fixtures" / "mock_llama_server_process.py"
MANIFEST_FIXTURE = ROOT / "tests" / "fixtures" / "b11272_manifest.json"
P7_LINE3 = ('"C:\\Users\\riper\\models\\llamacpp\\b11272\\llama-server.exe" -m '
            '"C:\\Users\\riper\\models\\muse\\Muse-Glimmer-30B-UD-Q5_K_M.gguf" --host 127.0.0.1 --port 8080 -np 1 -ngl 99 '
            '-c 98304 -fa on -ctk q8_0 -ctv q8_0 --jinja --temp 1.0 --top-p 0.95 --top-k 64 --min-p 0 --reasoning-format deepseek '
            '-md "C:\\Users\\riper\\models\\dflash\\Muse-Glimmer-30B-DFlash2-Q8_0.gguf" --spec-type draft-dflash '
            '--spec-draft-n-max 15 -ngld 99')
P7_LINE3_SHA = "87f5b5780514d2e516f7f69c5c78c280ac563991ca32efd4404fb7c98dd0f1a7"
P7_LINE3_BYTES = 406
BUILD_MANIFEST_SHA = "79472cf31743b42fa5056bf89025ee284b7835a05e56e49e3fcb34381416f02c"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Srv:
    """The fixture's handle: the config, the spawn log, the mock's arguments and the fake machine state."""

    def __init__(self):
        self.cfg = None
        self.spawns = []
        self.procs = []
        self.mock_args = []
        self.gpu = None
        self.ollama = []
        self.tmp = None

    @property
    def engine_file(self):
        return prov.engine_path()

    def alive(self):
        return any(p.poll() is None for p in self.procs)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    s = Srv()
    s.tmp = tmp_path
    build = tmp_path / "build"
    build.mkdir()
    (build / "llama-server.exe").write_bytes(b"exe bytes")
    (build / "ggml-base.dll").write_bytes(b"base dll")
    (build / "CUDA-Runtime.dll").write_bytes(b"cuda dll")
    models = tmp_path / "models"
    models.mkdir()
    (models / "muse.gguf").write_bytes(b"the model bytes" * 100)
    (models / "drafter.gguf").write_bytes(b"the drafter bytes" * 50)
    cfg = copy.deepcopy(rs2_data.CONFIG["llamacpp"])
    cfg.update(server_exe=str(build / "llama-server.exe"), model_path=str(models / "muse.gguf"),
               drafter_path=str(models / "drafter.gguf"), port=free_port(), load_timeout_s=10, vram_loaded_mib_band=None,
               model_sha256=sha((models / "muse.gguf").read_bytes()), drafter_sha256=sha((models / "drafter.gguf").read_bytes()),
               build_manifest_sha256=S.manifest_sha256(S.manifest_entries(build)))
    cfg["server_cmdline_sha256"] = S.cmdline_sha256(cfg)
    s.cfg = cfg
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "llamacpp")
    monkeypatch.setitem(rs2_data.CONFIG, "depth_model", cfg["model_tag"])
    monkeypatch.setitem(rs2_data.CONFIG, "llamacpp", cfg)
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 3)
    monkeypatch.setattr(prov, "ENGINE_DIR", tmp_path / "cache_llamacpp")
    monkeypatch.setattr(urllib.request, "urlopen", loopback_urlopen)     # the suite blocks urlopen; the mock is on loopback
    monkeypatch.setattr(S, "POLL_S", 0.05)

    def fake_spawn(cmdline, log_path):
        s.spawns.append(cmdline)
        log = open(log_path, "ab")
        p = subprocess.Popen([sys.executable, str(MOCK), "--port", str(cfg["port"]), *s.mock_args], stdout=log,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        log.close()
        s.procs.append(p)
        return p
    monkeypatch.setattr(S, "_spawn", fake_spawn)
    s.gpu = lambda: 21937 if s.alive() else 40
    monkeypatch.setattr(S, "gpu_used_mib", lambda: s.gpu())
    monkeypatch.setattr(ops, "ollama_loaded", lambda endpoint: list(s.ollama))
    monkeypatch.setattr(S, "process_image_path", lambda pid: cfg["server_exe"])
    # the committed provider is whatever this tree holds (M7's own tests below replace this)
    monkeypatch.setattr(S, "committed_provider_sha256", lambda repo=S.HERE, path=S.PROVIDER_FILE: prov.provider_sha256())
    yield s
    for p in s.procs:
        if p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            p.wait()


@pytest.fixture
def short_wait(monkeypatch):
    """The wait on a busy card is vram_unload_timeout_s (3 s in this fixture); the tests of a refusal need not sit through it."""
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 0.3)


def refused(srv, why):
    with pytest.raises(S.ServerRefusal) as e:
        S.start()
    assert why in str(e.value), str(e.value)
    assert srv.spawns == [], "a refusal must come before the launch"
    assert not srv.engine_file.exists()
    return str(e.value)


# ------------------------------------------------------------------ the command line and the manifest

def test_the_command_line_is_p7s_line_3_byte_for_byte():
    cfg = rs2_data.CONFIG["llamacpp"]
    got = S.build_cmdline(cfg)
    assert got == P7_LINE3
    assert len(got.encode("utf-8")) == P7_LINE3_BYTES and sha(got.encode("utf-8")) == P7_LINE3_SHA == cfg["server_cmdline_sha256"]
    assert S.cmdline_sha256(cfg) == P7_LINE3_SHA


def test_the_command_line_is_built_from_the_configs_keys_in_one_fixed_order():
    cfg = copy.deepcopy(rs2_data.CONFIG["llamacpp"])
    cfg.update(server_exe="X:\\a b\\llama-server.exe", model_path="X:\\m.gguf", drafter_path="X:\\d.gguf", host="127.0.0.2", port=9)
    assert S.build_cmdline(cfg) == ('"X:\\a b\\llama-server.exe" -m "X:\\m.gguf" --host 127.0.0.2 --port 9 -np 1 -ngl 99 -c 98304 '
                                    '-fa on -ctk q8_0 -ctv q8_0 --jinja --temp 1.0 --top-p 0.95 --top-k 64 --min-p 0 '
                                    '--reasoning-format deepseek -md "X:\\d.gguf" --spec-type draft-dflash '
                                    '--spec-draft-n-max 15 -ngld 99')


def test_the_manifest_hash_is_the_reviewers_over_the_sorted_compact_json():
    raw = MANIFEST_FIXTURE.read_bytes()
    assert sha(raw) == BUILD_MANIFEST_SHA == rs2_data.CONFIG["llamacpp"]["build_manifest_sha256"]
    entries = json.loads(raw)
    assert len(entries) == 55 and all(set(e) == {"path", "sha256", "size"} for e in entries)
    assert S.manifest_sha256(entries) == BUILD_MANIFEST_SHA


def test_the_manifest_lists_a_folder_case_insensitively_sorted_with_sizes_and_hashes(tmp_path):
    entries = json.loads(MANIFEST_FIXTURE.read_bytes())
    for e in entries:
        (tmp_path / e["path"]).write_bytes(b"x")
    got = S.manifest_entries(tmp_path, hasher=lambda p: {e["path"]: e["sha256"] for e in entries}[p.name])
    assert [e["path"] for e in got] == [e["path"] for e in entries]
    assert [e["sha256"] for e in got] == [e["sha256"] for e in entries] and all(e["size"] == 1 for e in got)
    sizes_replaced = [dict(g, size=e["size"]) for g, e in zip(got, entries)]
    assert S.manifest_sha256(sizes_replaced) == BUILD_MANIFEST_SHA        # the serialisation reproduces the pinned hash


def test_the_manifest_changes_when_any_file_changes(srv):
    folder = Path(srv.cfg["server_exe"]).parent
    before = S.manifest_sha256(S.manifest_entries(folder))
    (folder / "ggml-base.dll").write_bytes(b"base dlL")
    assert S.manifest_sha256(S.manifest_entries(folder)) != before
    (folder / "ggml-base.dll").write_bytes(b"base dll")
    (folder / "new.dll").write_bytes(b"x")
    assert S.manifest_sha256(S.manifest_entries(folder)) != before


# ------------------------------------------------------------------ start(): the happy path and engine.json

def test_start_launches_the_pinned_command_line_and_writes_engine_json(srv):
    rec = S.start()
    assert srv.spawns == [S.build_cmdline(srv.cfg)] and sha(srv.spawns[0].encode()) == srv.cfg["server_cmdline_sha256"]
    on_disk = json.loads(srv.engine_file.read_text(encoding="utf-8"))
    assert on_disk == rec
    assert list(rec) == ["pid", "endpoint", "build", "build_manifest_sha256", "model_sha256", "drafter_sha256", "spec",
                         "server_cmdline_sha256", "system_sha256", "provider_sha256", "reasoning_format", "vram_loaded_mib",
                         "started_at"]
    assert rec["pid"] == srv.procs[0].pid and prov.pid_alive(rec["pid"])
    assert rec["endpoint"] == f"http://127.0.0.1:{srv.cfg['port']}" and rec["build"] == "b11272"
    for k in ("build_manifest_sha256", "model_sha256", "drafter_sha256", "server_cmdline_sha256", "system_sha256"):
        assert rec[k] == srv.cfg[k]
    assert rec["spec"] == {"type": "draft-dflash", "n_max": 15, "ngld": 99} and rec["reasoning_format"] == "deepseek"
    assert rec["provider_sha256"] == prov.provider_sha256() and rec["vram_loaded_mib"] == 21937
    assert len(rec["started_at"]) == 19
    assert not list(srv.engine_file.parent.glob("*.tmp"))                       # written atomically, no temp file left


def test_the_log_is_cache_llamacpp_server_timestamp_log(srv):
    S.start()
    logs = list(srv.engine_file.parent.glob("server_*.log"))
    assert len(logs) == 1 and len(logs[0].stem) == len("server_20261002_130000")
    assert "n_ctx_slot = 98304" in logs[0].read_text(encoding="utf-8") and "n_max=15" in logs[0].read_text(encoding="utf-8")


def test_the_provider_serves_through_the_started_server_end_to_end(srv):
    """M2 and M3 together: engine.json as start() writes it passes the provider's checks and a request completes."""
    S.start()
    out = prov.chat(chat_body(), 30)
    assert out["message"]["content"] == "ok" and out["draft_n"] == 4 and out["engine"]["pid"] == srv.procs[0].pid
    assert out["system_injected"] is True


def test_the_health_wait_polls_until_the_server_answers(srv):
    srv.mock_args = ["--ready-after", "1.0"]
    t0 = time.time()
    S.start()
    assert 0.8 < time.time() - t0 < 8


# ------------------------------------------------------------------ start(): every refusal

def test_refuses_when_the_build_folder_differs_from_the_manifest(srv):
    (Path(srv.cfg["server_exe"]).parent / "ggml-base.dll").write_bytes(b"tampered")
    refused(srv, "hashes to manifest")


def test_refuses_when_a_file_is_added_to_the_build_folder(srv):
    (Path(srv.cfg["server_exe"]).parent / "extra.dll").write_bytes(b"x")
    refused(srv, "hashes to manifest")


def test_refuses_when_the_model_does_not_match_its_sha256(srv):
    srv.cfg["model_sha256"] = "0" * 64
    msg = refused(srv, "model sha256")
    assert "is not the pinned" in msg


def test_refuses_when_the_drafter_does_not_match_its_sha256(srv):
    srv.cfg["drafter_sha256"] = "0" * 64
    refused(srv, "drafter sha256")


def test_a_model_changed_since_the_run_start_is_caught_by_size_and_modification_time(srv):
    S.begin_run()                                                           # the run start: full hashes recorded
    Path(srv.cfg["model_path"]).write_bytes(Path(srv.cfg["model_path"]).read_bytes() + b"!")
    refused(srv, "changed since the run start")


def test_the_same_size_but_a_later_modification_time_is_caught(srv):
    import os
    S.begin_run()
    p = Path(srv.cfg["drafter_path"])
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    refused(srv, "changed since the run start")


def test_start_compares_with_the_record_and_does_not_hash_the_model_again(srv, monkeypatch):
    S.begin_run()
    hashed = []
    real = S.sha256_file
    monkeypatch.setattr(S, "sha256_file", lambda p, chunk=16 * 1024 * 1024: (hashed.append(Path(p).name), real(p, chunk))[1])
    S.start(hasher=S.sha256_file)
    assert "muse.gguf" not in hashed and "drafter.gguf" not in hashed
    assert "llama-server.exe" in hashed                                      # the build folder is hashed at every start


def test_a_start_with_no_run_start_record_takes_the_full_hashes_first(srv):
    assert not S.run_start_path().exists()
    S.start()
    rec = json.loads(S.run_start_path().read_text(encoding="utf-8"))
    assert rec["model"]["sha256"] == srv.cfg["model_sha256"] and rec["drafter"]["sha256"] == srv.cfg["drafter_sha256"]
    assert rec["model"]["size"] == Path(srv.cfg["model_path"]).stat().st_size


def test_begin_run_refuses_a_model_that_is_not_the_pinned_one_and_records_nothing(srv):
    srv.cfg["model_sha256"] = "1" * 64
    with pytest.raises(S.ServerRefusal, match="model sha256"):
        S.begin_run()
    assert not S.run_start_path().exists()


def test_a_run_start_record_for_other_pins_is_refused(srv):
    S.begin_run()
    srv.cfg["model_sha256"] = "2" * 64
    refused(srv, "run-start record has sha256")


def test_refuses_when_the_command_line_does_not_hash_to_its_pin(srv):
    srv.cfg["host"] = "127.0.0.2"                                            # the line built from the config changes; the pin does not
    refused(srv, "the command line built from the config hashes to")


def test_refuses_when_the_system_file_does_not_hash_to_its_pin(srv):
    srv.cfg["system_sha256"] = "3" * 64
    refused(srv, "system_file")


def test_refuses_when_the_port_is_not_free(srv):
    s = socket.socket()
    s.bind(("127.0.0.1", srv.cfg["port"]))
    s.listen(1)
    try:
        refused(srv, "is not free")
    finally:
        s.close()


@pytest.mark.parametrize("used,ok", [(0, True), (199, True), (200, False), (201, False), (21937, False)])
def test_the_card_must_be_idle_under_200_mib(srv, used, ok, short_wait):
    srv.gpu = lambda: used if not srv.alive() else 21937
    if ok:
        S.start()
    else:
        refused(srv, "the card is not idle")


def test_refuses_when_gpu_memory_cannot_be_read(srv, short_wait):
    srv.gpu = lambda: None
    refused(srv, "cannot be read (nvidia-smi)")


def test_refuses_when_ollama_has_a_model_loaded(srv, short_wait):
    srv.ollama = ["rs2-research:latest"]
    refused(srv, "Ollama has a model loaded")


def test_refuses_when_ollama_cannot_say_what_is_loaded(srv, monkeypatch, short_wait):
    monkeypatch.setattr(ops, "ollama_loaded", lambda endpoint: None)
    refused(srv, "Ollama /api/ps cannot be read")


def test_every_reason_is_reported_together(srv, short_wait):
    srv.cfg["model_sha256"] = "0" * 64
    srv.ollama = ["x"]
    srv.gpu = lambda: 5000
    with pytest.raises(S.ServerRefusal) as e:
        S.start()
    for part in ("model sha256", "Ollama has a model loaded", "the card is not idle"):
        assert part in str(e.value)


def test_a_missing_llamacpp_block_refuses(srv, monkeypatch):
    monkeypatch.delitem(rs2_data.CONFIG, "llamacpp")
    with pytest.raises(S.ServerRefusal, match="no llamacpp block"):
        S.start()


# ------------------------------------------------------------------ start(): after the launch

def test_a_server_that_exits_before_it_is_ready_is_a_refusal(srv):
    srv.mock_args = ["--exit-code", "3"]
    with pytest.raises(S.ServerRefusal, match="exited with code 3"):
        S.start()
    assert not srv.engine_file.exists()


def test_a_server_that_never_answers_health_is_stopped_and_refused(srv):
    srv.cfg["load_timeout_s"] = 1
    srv.mock_args = ["--ready-after", "999"]
    t0 = time.time()
    with pytest.raises(S.ServerRefusal, match="did not answer /health 200 within load_timeout_s=1"):
        S.start()
    assert time.time() - t0 < 10
    assert not srv.engine_file.exists() and srv.procs[0].wait(10) is not None and not prov.pid_alive(srv.procs[0].pid)


@pytest.mark.parametrize("mock_args,why", [(["--n-ctx", "49152"], "n_ctx_slot = 98304"), (["--n-ctx", "983040"], "n_ctx_slot = 98304"),
                                           (["--n-max", "6"], "n_max=15"), (["--n-max", "150"], "n_max=15")])
def test_the_log_checks_are_each_a_refusal_and_the_server_is_stopped(srv, mock_args, why):
    srv.mock_args = mock_args
    with pytest.raises(S.ServerRefusal, match=why):
        S.start()
    assert not srv.engine_file.exists()
    srv.procs[0].wait(10)
    assert not prov.pid_alive(srv.procs[0].pid), "the refused server must be stopped"


@pytest.mark.parametrize("used,ok", [(21499, False), (21500, True), (21937, True), (22300, True), (22301, False), (None, False)])
def test_while_the_band_is_null_the_m9_range_21500_to_22300_applies_and_the_value_is_recorded(srv, used, ok):
    assert srv.cfg["vram_loaded_mib_band"] is None
    srv.gpu = lambda: (used if srv.alive() else 40)
    if ok:
        assert S.start()["vram_loaded_mib"] == used
    else:
        with pytest.raises(S.ServerRefusal, match="outside the band"):
            S.start()
        assert not srv.engine_file.exists()


@pytest.mark.parametrize("used,ok", [(21680, False), (21681, True), (21937, True), (22193, True), (22194, False)])
def test_a_pinned_band_is_inclusive_and_replaces_the_m9_range(srv, used, ok):
    srv.cfg["vram_loaded_mib_band"] = [21681, 22193]                         # 21,937 plus or minus 256
    srv.gpu = lambda: (used if srv.alive() else 40)
    if ok:
        assert S.start()["vram_loaded_mib"] == used
    else:
        with pytest.raises(S.ServerRefusal, match=r"outside the band \[21681, 22193\]"):
            S.start()


def test_a_partial_offload_falls_outside_the_band(srv):
    """A layer of this model is about 400 MB; llama.cpp's memory fitting would offload fewer layers and use less memory."""
    srv.cfg["vram_loaded_mib_band"] = [21681, 22193]
    srv.gpu = lambda: (21937 - 400 if srv.alive() else 40)
    with pytest.raises(S.ServerRefusal, match="outside the band"):
        S.start()


def test_a_stale_engine_file_with_a_dead_pid_is_replaced(srv):
    srv.engine_file.parent.mkdir(parents=True, exist_ok=True)
    srv.engine_file.write_text(json.dumps({"pid": 999999999, "build": "old"}), encoding="utf-8")
    rec = S.start()
    assert json.loads(srv.engine_file.read_text(encoding="utf-8"))["pid"] == rec["pid"] != 999999999


# ------------------------------------------------------------------ stop()

def test_stop_kills_the_whole_tree_waits_for_the_memory_and_removes_engine_json(srv):
    pidfile = srv.tmp / "child.pid"
    srv.mock_args = ["--child-pid-file", str(pidfile)]
    rec = S.start()
    child = int(pidfile.read_text())
    assert prov.pid_alive(rec["pid"]) and prov.pid_alive(child)
    ok, detail = S.stop()
    assert ok and "stopped" in detail
    assert not prov.pid_alive(rec["pid"]) and not prov.pid_alive(child), "taskkill /T must take the child down too"
    assert not srv.engine_file.exists()


def test_stop_waits_until_less_than_200_mib_is_in_use(srv):
    S.start()
    reads = []

    def gpu():
        reads.append(1)
        return 5000 if len(reads) < 6 else 120            # the memory drains over a few polls after the process is gone
    srv.gpu = gpu
    t0 = time.time()
    ok, detail = S.stop()
    assert ok and len(reads) >= 6 and "gpu_used=120MiB" in detail
    assert not srv.engine_file.exists()


def test_a_stop_that_times_out_is_a_hard_failure_and_keeps_the_record(srv):
    S.start()
    srv.gpu = lambda: 5000
    t0 = time.time()
    ok, detail = S.stop()                                  # vram_unload_timeout_s is 3 in this fixture
    assert ok is False and detail.startswith("TIMEOUT after 3s") and 3 <= time.time() - t0 < 10
    assert srv.engine_file.exists()


def test_a_stop_that_cannot_read_the_gpu_is_a_failure_not_a_success(srv):
    S.start()
    srv.gpu = lambda: None
    ok, detail = S.stop()
    assert ok is False and "TIMEOUT" in detail


def test_stop_without_a_record_is_a_no_op(srv):
    assert S.stop() == (True, "no engine record: no server to stop")


def test_stop_never_kills_a_process_that_is_not_the_server(srv, monkeypatch):
    """A record left by a crash names a PID that another program may hold now."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        srv.engine_file.parent.mkdir(parents=True, exist_ok=True)
        srv.engine_file.write_text(json.dumps({"pid": other.pid}), encoding="utf-8")
        monkeypatch.setattr(S, "process_image_path", lambda pid: "C:\\Windows\\System32\\notepad.exe")
        srv.gpu = lambda: 40
        ok, detail = S.stop()
        assert ok and other.poll() is None, "the other program must still be running"
        assert not srv.engine_file.exists()
    finally:
        other.kill()
        other.wait()


def test_the_process_image_of_a_running_process_can_be_read():
    import os
    img = S.process_image_path(os.getpid())
    assert img is not None and Path(img).name.lower().startswith("python")


# ------------------------------------------------------------------ status() and ensure_ready()

def test_status_reports_pid_health_and_memory(srv):
    s0 = S.status()
    assert s0["engine_file"] is False and s0["ready"] is False and s0["pid"] is None and s0["gpu_used_mib"] == 40
    S.start()
    s1 = S.status()
    assert s1["ready"] is True and s1["pid_alive"] is True and s1["health"] is True and s1["gpu_used_mib"] == 21937
    S.stop()
    assert S.status()["engine_file"] is False


def test_status_of_a_killed_server_says_so(srv):
    rec = S.start()
    S._kill_tree(rec["pid"])
    srv.procs[0].wait(10)
    s = S.status()
    assert s["engine_file"] is True and s["pid_alive"] is False and s["health"] is False and s["ready"] is False
    assert "is not alive" in s["problem"]


def test_ensure_ready_starts_a_server_when_none_runs_and_leaves_a_running_one_alone(srv):
    rec = S.ensure_ready()
    assert len(srv.spawns) == 1
    again = S.ensure_ready()
    assert len(srv.spawns) == 1 and again["pid"] == rec["pid"]               # verified, not restarted


def test_ensure_ready_refuses_a_running_server_whose_pins_differ_and_does_not_kill_it(srv):
    rec = S.ensure_ready()
    srv.cfg["model_sha256"] = "0" * 64
    with pytest.raises(S.ServerRefusal, match="model_sha256"):
        S.ensure_ready()
    assert prov.pid_alive(rec["pid"]) and len(srv.spawns) == 1


def test_ensure_ready_refuses_a_running_server_that_is_not_healthy(srv, monkeypatch):
    S.ensure_ready()
    monkeypatch.setattr(prov, "health_ok", lambda cfg, timeout=None: False)
    with pytest.raises(S.ServerRefusal, match="/health"):
        S.ensure_ready()


def test_ensure_ready_restarts_after_the_server_died(srv):
    rec = S.ensure_ready()
    S._kill_tree(rec["pid"])
    srv.procs[0].wait(10)
    new = S.ensure_ready()
    assert len(srv.spawns) == 2 and new["pid"] != rec["pid"] and prov.pid_alive(new["pid"])
    assert json.loads(srv.engine_file.read_text(encoding="utf-8"))["pid"] == new["pid"]


def test_ensure_ready_propagates_a_start_refusal(srv):
    srv.ollama = ["rs2-analyst-deep-mtp5:latest"]
    with pytest.raises(S.ServerRefusal, match="Ollama has a model loaded"):
        S.ensure_ready()


# ------------------------------------------------------------------ the provider after stop(), and a kill mid-request (M9 d)

def test_after_stop_the_provider_refuses_with_engine_not_ready(srv):
    S.start()
    assert prov.chat(chat_body(), 30)["message"]["content"] == "ok"
    S.stop()
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat(chat_body(), 30)
    assert e.value.code == 500 and e.value.cause == "engine_not_ready"


def test_a_server_killed_mid_request_fails_the_request_fast_and_a_restart_restores_service(srv):
    srv.mock_args = ["--delay", "30"]
    rec = S.start()
    box = {}

    def call():
        try:
            prov.chat(chat_body(), 120)
        except Exception as e:                      # noqa: BLE001
            box["err"] = e
    th = threading.Thread(target=call)
    t0 = time.time()
    th.start()
    time.sleep(1.0)                                  # the request is in flight at the mock
    S._kill_tree(rec["pid"])
    th.join(60)
    assert not th.is_alive() and time.time() - t0 < 60
    assert isinstance(box["err"], urllib.error.HTTPError) and box["err"].code == 500
    assert box["err"].cause in ("connection_reset", "connection_refused")
    srv.procs[0].wait(10)
    srv.mock_args = []
    new = S.ensure_ready()                           # the lifecycle restores the server
    assert new["pid"] != rec["pid"]
    assert prov.chat(chat_body(), 30)["message"]["content"] == "ok"          # and the next request completes


# ------------------------------------------------------------------ the command line interface

def test_the_cli_status_start_stop_and_exit_codes(srv, capsys):
    assert S.main(["status"]) == 0 and json.loads(capsys.readouterr().out)["ready"] is False
    assert S.main(["start"]) == 0 and json.loads(capsys.readouterr().out)["pid"] == srv.procs[0].pid
    assert S.main(["ensure"]) == 0 and len(srv.spawns) == 1
    capsys.readouterr()
    assert S.main(["stop"]) == 0 and capsys.readouterr().out.startswith("ok: stopped")
    assert S.main(["bogus"]) == 2
    srv.ollama = ["x"]
    assert S.main(["start"]) == 7 and "::VRAM:: llama-server: " in capsys.readouterr().out


def test_the_cli_stop_that_times_out_exits_7(srv, capsys):
    S.start()
    srv.gpu = lambda: 5000
    assert S.main(["stop"]) == 7 and capsys.readouterr().out.startswith("FAILED: TIMEOUT")


def test_the_cli_begin_run_records_the_full_hashes(srv, capsys):
    assert S.main(["begin-run"]) == 0
    assert json.loads(capsys.readouterr().out)["model"]["sha256"] == srv.cfg["model_sha256"]


def test_is_enabled_follows_depth_provider(srv, monkeypatch):
    assert S.is_enabled() is True
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama")
    assert S.is_enabled() is False


# ------------------------------------------------------------------ M7: the pins checked before anything runs

def test_check_pins_is_empty_when_every_pin_holds(srv):
    assert S.check_pins() == []


def test_check_pins_reports_every_m3_refusal_without_launching(srv):
    srv.cfg["model_sha256"] = "0" * 64
    srv.ollama = ["x"]
    srv.gpu = lambda: 5000
    srv.cfg["system_sha256"] = "3" * 64
    bad = S.check_pins()
    for part in ("model sha256", "Ollama has a model loaded", "the card is not idle", "system_file"):
        assert any(part in b for b in bad), (part, bad)
    assert srv.spawns == []


def test_depth_model_must_equal_the_model_tag(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_model", "rs2-analyst-deep-mtp5-v33")
    refused(srv, "depth_model 'rs2-analyst-deep-mtp5-v33' is not llamacpp.model_tag")
    assert any("depth_model" in b for b in S.check_pins())


def test_the_window_must_be_the_servers(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_ctx", 81920)
    refused(srv, "depth_ctx 81920 is not the server's window 98304")


@pytest.mark.parametrize("name,why", [("ollama", "not 'llamacpp'"), ("vllm", "depth_provider must be one of")])
def test_the_provider_must_be_llamacpp(srv, monkeypatch, name, why):
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", name)
    refused(srv, why)


def test_a_provider_module_that_is_not_the_committed_file_refuses(srv, monkeypatch):
    monkeypatch.setattr(S, "committed_provider_sha256", lambda repo=S.HERE, path=S.PROVIDER_FILE: "9" * 64)
    msg = refused(srv, "llm_provider.py hashes to")
    assert prov.provider_sha256() in msg and "the committed file to " + "9" * 64 in msg


def test_a_committed_provider_that_cannot_be_read_refuses(srv, monkeypatch):
    monkeypatch.setattr(S, "committed_provider_sha256", lambda repo=S.HERE, path=S.PROVIDER_FILE: None)
    refused(srv, "the committed llm_provider.py cannot be read")


def test_the_registrations_pin_replaces_the_committed_file_as_the_reference(srv, monkeypatch):
    monkeypatch.setattr(S, "committed_provider_sha256", lambda repo=S.HERE, path=S.PROVIDER_FILE: "9" * 64)
    assert S.check_pins(expected_provider_sha256=prov.provider_sha256()) == []
    bad = S.check_pins(expected_provider_sha256="8" * 64)
    assert len(bad) == 1 and "the pinned file to " + "8" * 64 in bad[0]


def test_the_committed_file_is_read_with_git_show_head(tmp_path):
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    repo = tmp_path / "repo"
    (repo / "tools" / "audit_202608").mkdir(parents=True)
    f = repo / "tools" / "audit_202608" / "llm_provider.py"
    content = b"first" + bytes([13, 10]) + b"second" + bytes([10])        # CRLF inside: the bytes are hashed as they are
    f.write_bytes(content)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, env={**os.environ, **env}, check=True)
    run("init", "-q")
    run("config", "core.autocrlf", "false")
    run("add", ".")
    run("commit", "-q", "-m", "x")
    committed = sha(content)
    assert S.committed_provider_sha256(repo) == committed
    f.write_bytes(b"edited after the commit")                       # a working-tree edit does not change what is committed
    assert S.committed_provider_sha256(repo) == committed
    assert S.committed_provider_sha256(tmp_path / "not_a_repo") is None


def test_the_provider_file_is_kept_byte_exact_by_git(tmp_path):
    """The pin is the sha256 of the file's bytes; with autocrlf a text file is checked out as CRLF and the pin would differ
    between trees. .gitattributes marks it -text."""
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    out = subprocess.run(["git", "check-attr", "text", "--", S.PROVIDER_FILE], cwd=ROOT, capture_output=True, text=True).stdout
    assert out.strip().endswith("text: unset"), out


def test_the_real_committed_provider_is_this_trees_when_the_file_is_clean():
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", S.PROVIDER_FILE], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip():
        pytest.skip("llm_provider.py has uncommitted changes in this tree")
    assert S.committed_provider_sha256() == prov.provider_sha256()


def test_the_cli_check_pins_exit_codes(srv, capsys):
    assert S.main(["check-pins"]) == 0 and capsys.readouterr().out.strip() == "ok: every pin holds"
    assert S.main(["check-pins", "--provider-sha256", "7" * 64]) == 7
    assert "the pinned file to " + "7" * 64 in capsys.readouterr().out
    srv.ollama = ["x"]
    assert S.main(["check-pins"]) == 7 and "Ollama has a model loaded" in capsys.readouterr().out


def test_the_runs_pins_are_the_registrations_list(srv):
    """registration 3.2: build manifest, model, drafter, command line, SYSTEM, provider, residency band: each is a key the
    refusals above read; none has a default."""
    for k in ("build_manifest_sha256", "model_sha256", "drafter_sha256", "server_cmdline_sha256", "system_sha256"):
        assert k in rs2_data.CONFIG["llamacpp"] and len(rs2_data.CONFIG["llamacpp"][k]) == 64
    assert "vram_loaded_mib_band" in rs2_data.CONFIG["llamacpp"]


def test_ensure_ready_checks_the_config_pins_and_the_provider_for_a_running_server_too(srv, monkeypatch):
    S.ensure_ready()
    monkeypatch.setitem(rs2_data.CONFIG, "depth_ctx", 81920)
    with pytest.raises(S.ServerRefusal, match="depth_ctx 81920"):
        S.ensure_ready()
    monkeypatch.setitem(rs2_data.CONFIG, "depth_ctx", 98304)
    monkeypatch.setattr(S, "committed_provider_sha256", lambda repo=S.HERE, path=S.PROVIDER_FILE: "9" * 64)
    with pytest.raises(S.ServerRefusal, match="llm_provider.py hashes to"):
        S.ensure_ready()
    assert len(srv.spawns) == 1                      # refused, not restarted


# ------------------------------------------------------------------ B-2: a card that is not yet idle is waited on

def _busy_then_idle(srv, busy_checks, busy_mib=5000):
    """gpu_used_mib reads `busy_mib` for the first `busy_checks` readings taken before the launch, then idle."""
    reads = []

    def gpu():
        if srv.alive():
            return 21937
        reads.append(1)
        return busy_mib if len(reads) <= busy_checks else 40
    srv.gpu = gpu
    return reads


def test_a_card_that_falls_idle_on_the_third_check_starts(srv):
    reads = _busy_then_idle(srv, 2)
    t0 = time.time()
    rec = S.start()
    assert len(reads) == 3 and len(srv.spawns) == 1 and rec["pid"] == srv.procs[0].pid
    assert time.time() - t0 < 3


def test_ollama_releasing_its_model_on_the_third_check_starts(srv, monkeypatch):
    states = iter([["rs2-research:latest"], ["rs2-research:latest"], []])
    seen = []
    monkeypatch.setattr(ops, "ollama_loaded", lambda endpoint: (seen.append(1), next(states, []))[1])
    S.start()
    assert len(seen) == 3 and len(srv.spawns) == 1


def test_the_two_conditions_are_both_rechecked_each_round(srv, monkeypatch):
    gpu_reads, ps_reads = [], []
    srv.gpu = lambda: (21937 if srv.alive() else (gpu_reads.append(1), 5000 if len(gpu_reads) < 3 else 40)[1])
    monkeypatch.setattr(ops, "ollama_loaded", lambda endpoint: (ps_reads.append(1), [] if len(ps_reads) >= 3 else ["x"])[1])
    S.start()
    assert len(gpu_reads) == 3 and len(ps_reads) == 3


def test_a_card_that_never_falls_idle_is_refused_after_the_wait_with_nothing_launched(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 1)
    srv.gpu = lambda: 5000
    t0 = time.time()
    with pytest.raises(S.ServerRefusal) as e:
        S.start()
    assert 1 <= time.time() - t0 < 6
    assert "the card is not idle: 5000 MiB in use" in str(e.value) and "still so after waiting 1s" in str(e.value)
    assert srv.spawns == [] and not srv.engine_file.exists()


def test_a_model_in_ollama_that_never_leaves_is_refused_after_the_wait(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 1)
    srv.ollama = ["rs2-research:latest"]
    with pytest.raises(S.ServerRefusal, match="Ollama has a model loaded.*still so after waiting 1s"):
        S.start()
    assert srv.spawns == []


def test_pin_and_file_refusals_stay_immediate_on_a_busy_card(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 30)
    srv.gpu = lambda: 5000
    srv.cfg["model_sha256"] = "0" * 64
    t0 = time.time()
    with pytest.raises(S.ServerRefusal) as e:
        S.start()
    assert time.time() - t0 < 5, "a pin refusal must not wait on the card"
    assert "model sha256" in str(e.value) and "the card is not idle" in str(e.value)       # reported together, from one look
    assert srv.spawns == []


def test_a_port_in_use_stays_immediate_too(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 30)
    srv.gpu = lambda: 5000
    s = socket.socket()
    s.bind(("127.0.0.1", srv.cfg["port"]))
    s.listen(1)
    try:
        t0 = time.time()
        with pytest.raises(S.ServerRefusal, match="is not free"):
            S.start()
        assert time.time() - t0 < 5
    finally:
        s.close()


def test_check_pins_looks_once_and_does_not_wait(srv, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "vram_unload_timeout_s", 30)
    srv.gpu = lambda: 5000
    t0 = time.time()
    assert any("the card is not idle" in b for b in S.check_pins())
    assert time.time() - t0 < 5


def test_ensure_ready_waits_on_a_busy_card_through_start(srv):
    reads = _busy_then_idle(srv, 2)
    rec = S.ensure_ready()
    assert len(reads) == 3 and rec["pid"] == srv.procs[0].pid

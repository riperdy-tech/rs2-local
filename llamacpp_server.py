#!/usr/bin/env python3
"""llamacpp_server.py - the lifecycle of the llama-server process behind depth_provider "llamacpp"
(brief_muse_integration.md M3). The provider (tools/audit_202608/llm_provider.py) only talks to the server; this module
owns starting it, checking what it is, stopping it, and the engine record the provider reads before every request.

    start()         refuses unless every pin holds, the port is free and the card is idle; launches the pinned command line
                    (subprocess.Popen, no shell), waits for /health, checks the log and the GPU memory it settled at, then
                    writes cache/llamacpp/engine.json. Any failure after the launch stops the server and refuses.
    stop()          taskkill /PID <pid> /T /F, waits until the PID is gone and less than 200 MiB is in use, removes engine.json.
                    Returns (ok, detail); not ok is a hard failure (the callers exit 7, as for Ollama).
    status()        PID alive, /health, GPU memory in use.
    ensure_ready()  start() when no server runs; otherwise verifies engine.json against the config and /health.
    begin_run()     the full sha256 of the model and drafter, recorded in cache/llamacpp/run_start.json. start() compares
                    name, size and modification time with that record; a start with no record takes the hashes first.

    python llamacpp_server.py start | stop | status | ensure | begin-run

The consensus subprocess never starts or stops the server: it reaches it only through the provider.
Exit codes of the command line: 0 done, 7 refused or failed (the VRAM exit code of the depth pipeline).
Nothing here loads a model except the llama-server it launches; the tests replace the launch, nvidia-smi and Ollama's /api/ps.
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_AUDIT_DIR = str(HERE / "tools" / "audit_202608")
if _AUDIT_DIR not in sys.path:
    sys.path.append(_AUDIT_DIR)

import ops  # noqa: E402
import rs2_data  # noqa: E402
import llm_provider as prov  # noqa: E402

IDLE_MIB = 200                  # "the card is idle": less than this in use (as the run tooling checks today)
WINDOW = 98304                  # -c, equal to depth_ctx
N_MAX = 15                      # --spec-draft-n-max
NGLD = 99                       # -ngld
VRAM_TOLERANCE_MIB = 256        # the pinned band is the M9 measurement plus or minus this
M9_VRAM_RANGE_MIB = (21500, 22300)   # M9 (a)'s fixed range, applied while vram_loaded_mib_band is null
POLL_S = 1.0
RUN_START_FILE = "run_start.json"


class ServerRefusal(RuntimeError):
    """start() / ensure_ready() will not (or could not) provide a pinned, healthy server. The depth pipeline exits 7."""


def _config():
    return rs2_data.CONFIG


def is_enabled():
    """True when depth_provider is "llamacpp"."""
    return prov.provider_name() == "llamacpp"


def settings():
    cfg = _config().get("llamacpp")
    if not isinstance(cfg, dict):
        raise ServerRefusal("config.json has no llamacpp block")
    return cfg


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path, chunk=16 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- the pinned command line

def build_cmdline(cfg):
    """The command line of P7's launch_dflash_n15.cmd (line 3), built from the config's keys in one fixed order. Its sha256
    must equal cfg["server_cmdline_sha256"]."""
    def q(p):
        return f'"{p}"'
    return (f'{q(cfg["server_exe"])} -m {q(cfg["model_path"])} --host {cfg["host"]} --port {cfg["port"]} -np 1 -ngl 99 '
            f'-c {WINDOW} -fa on -ctk q8_0 -ctv q8_0 --jinja --temp 1.0 --top-p 0.95 --top-k 64 --min-p 0 '
            f'--reasoning-format deepseek -md {q(cfg["drafter_path"])} --spec-type draft-dflash '
            f'--spec-draft-n-max {N_MAX} -ngld {NGLD}')


def cmdline_sha256(cfg):
    return sha256_bytes(build_cmdline(cfg).encode("utf-8"))


# ---------------------------------------------------------------- the build folder and the model files

def manifest_entries(folder, hasher=sha256_file):
    """[{path, sha256, size}] of every file under `folder`, paths relative with "/", sorted case-insensitively."""
    root = Path(folder)
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = Path(dirpath) / name
            out.append({"path": p.relative_to(root).as_posix(), "sha256": hasher(p), "size": p.stat().st_size})
    return sorted(out, key=lambda e: e["path"].lower())


def manifest_sha256(entries):
    """sha256 of the sorted, compact JSON of the entries: the reviewer's `build_manifest_sha256`."""
    return sha256_bytes(json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _stat_record(path, hasher):
    p = Path(path)
    st = p.stat()
    return {"path": str(p), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": hasher(p)}


def run_start_path():
    return Path(prov.ENGINE_DIR) / RUN_START_FILE


def begin_run(cfg=None, hasher=sha256_file):
    """Full sha256 of the model and the drafter, compared with the pins and recorded in run_start.json. Called at the start
    (and the end) of every run; start() then only compares name, size and modification time with this record."""
    cfg = cfg or settings()
    rec = {"model": _stat_record(cfg["model_path"], hasher), "drafter": _stat_record(cfg["drafter_path"], hasher),
           "taken_at": datetime.now().isoformat(timespec="seconds")}
    bad = [f"{k} sha256 {rec[k]['sha256']} is not the pinned {cfg[k + '_sha256']}" for k in ("model", "drafter")
           if rec[k]["sha256"] != cfg[k + "_sha256"]]
    if bad:
        raise ServerRefusal("; ".join(bad))
    p = run_start_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def _artifact_problems(cfg, hasher):
    """Why the build folder, model or drafter is not the pinned one (empty: they are)."""
    bad = []
    folder = Path(cfg["server_exe"]).parent
    try:
        got = manifest_sha256(manifest_entries(folder, hasher))
    except OSError as e:
        return [f"build folder {folder} cannot be read: {type(e).__name__}: {e}"]
    if got != cfg["build_manifest_sha256"]:
        bad.append(f"build folder {folder} hashes to manifest {got}, pinned {cfg['build_manifest_sha256']}")
    rp = run_start_path()
    try:
        rec = json.loads(rp.read_text(encoding="utf-8"))
    except FileNotFoundError:
        try:
            rec = begin_run(cfg, hasher)                 # no run-start record: this start is the start of the run
        except (ServerRefusal, OSError) as e:
            return bad + [str(e)]
    except (OSError, ValueError) as e:
        return bad + [f"run-start record {rp} is unreadable: {type(e).__name__}: {e}"]
    for key, path_key in (("model", "model_path"), ("drafter", "drafter_path")):
        r = rec.get(key) or {}
        try:
            st = Path(cfg[path_key]).stat()
        except OSError as e:
            bad.append(f"{key} {cfg[path_key]} cannot be read: {type(e).__name__}: {e}")
            continue
        if r.get("path") != str(Path(cfg[path_key])):
            bad.append(f"{key}: the run-start record is for {r.get('path')!r}, config says {cfg[path_key]!r}")
        elif (r.get("size"), r.get("mtime_ns")) != (st.st_size, st.st_mtime_ns):
            bad.append(f"{key} {cfg[path_key]} changed since the run start (size or modification time differs from the record)")
        if r.get("sha256") != cfg[key + "_sha256"]:
            bad.append(f"{key}: the run-start record has sha256 {r.get('sha256')}, pinned {cfg[key + '_sha256']}")
    return bad


# ---------------------------------------------------------------- what the machine says

def gpu_used_mib():
    """GPU memory in use per nvidia-smi, in MiB, or None when it cannot be read ("unknown", never "idle")."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        return int(r.stdout.strip().splitlines()[0].strip())
    except Exception:
        return None


def port_free(host, port):
    """Nothing listens on host:port and it can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)                 # a listener accepts at once; Windows takes seconds to refuse a closed local port
        if s.connect_ex((host, int(port))) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, int(port)))
        except OSError:
            return False
    return True


def _kill_tree(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
    except Exception:
        pass


def _spawn(cmdline, log_path):
    """Launch the pinned command line: Popen, no shell, stdout and stderr to the log."""
    log = open(log_path, "ab")
    try:
        return subprocess.Popen(cmdline, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, shell=False)
    finally:
        log.close()


# ---------------------------------------------------------------- refusals

def refusals(cfg=None, hasher=sha256_file):
    """Every reason the server may not be started now, as readable lines (empty: it may). Nothing is launched."""
    cfg = cfg or settings()
    bad = []
    got = cmdline_sha256(cfg)
    if got != cfg["server_cmdline_sha256"]:
        bad.append(f"the command line built from the config hashes to {got}, pinned {cfg['server_cmdline_sha256']}")
    sysf = prov.HERE / cfg["system_file"]
    try:
        sysh = sha256_file(sysf)
        if sysh != cfg["system_sha256"]:
            bad.append(f"system_file {sysf} hashes to {sysh}, pinned {cfg['system_sha256']}")
    except OSError as e:
        bad.append(f"system_file {sysf} cannot be read: {type(e).__name__}: {e}")
    if not port_free(cfg["host"], cfg["port"]):
        bad.append(f"port {cfg['host']}:{cfg['port']} is not free")
    used = gpu_used_mib()
    if used is None:
        bad.append("GPU memory in use cannot be read (nvidia-smi): the card is not known to be idle")
    elif used >= IDLE_MIB:
        bad.append(f"the card is not idle: {used} MiB in use, the limit is {IDLE_MIB}")
    loaded = ops.ollama_loaded(_config()["ollama_endpoint"])
    if loaded is None:
        bad.append("Ollama /api/ps cannot be read: whether a model is loaded is not known")
    elif loaded:
        bad.append(f"Ollama has a model loaded: {loaded}")
    return bad + _artifact_problems(cfg, hasher)


# ---------------------------------------------------------------- start

def _read_log(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _vram_band(cfg):
    band = cfg.get("vram_loaded_mib_band")
    if band is None:
        return M9_VRAM_RANGE_MIB
    lo, hi = band
    return lo, hi


def _wait_ready(proc, cfg):
    deadline = time.time() + cfg["load_timeout_s"]
    while True:
        if proc.poll() is not None:
            raise ServerRefusal(f"llama-server exited with code {proc.returncode} before /health answered 200")
        if prov.health_ok(cfg, timeout=2):
            return
        if time.time() >= deadline:
            raise ServerRefusal(f"llama-server did not answer /health 200 within load_timeout_s={cfg['load_timeout_s']}")
        time.sleep(POLL_S)


def _write_engine(rec):
    p = prov.engine_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _stale_engine_removed():
    """An engine.json whose PID is gone describes no server; it is removed before a new start."""
    try:
        eng = prov.read_engine()
    except prov.ProviderError:
        return
    if not prov.pid_alive(eng.get("pid")):
        prov.engine_path().unlink(missing_ok=True)


def start(cfg=None, hasher=sha256_file):
    """Start the pinned llama-server and write engine.json, or raise ServerRefusal (and leave no server running)."""
    cfg = cfg or settings()
    bad = refusals(cfg, hasher)
    if bad:
        raise ServerRefusal("; ".join(bad))
    _stale_engine_removed()
    cmdline = build_cmdline(cfg)
    log_dir = Path(prov.ENGINE_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"server_{datetime.now():%Y%m%d_%H%M%S}.log"
    proc = _spawn(cmdline, log_path)
    try:
        _wait_ready(proc, cfg)
        log = _read_log(log_path)
        if not re.search(rf"n_ctx_slot = {WINDOW}\b", log):
            raise ServerRefusal(f"the server log does not carry n_ctx_slot = {WINDOW} ({log_path})")
        if not re.search(rf"n_max={N_MAX}\b", log):
            raise ServerRefusal(f"the server log does not carry n_max={N_MAX} ({log_path})")
        used = gpu_used_mib()
        lo, hi = _vram_band(cfg)
        if used is None or not lo <= used <= hi:
            raise ServerRefusal(f"GPU memory in use after load is {used} MiB, outside the band [{lo}, {hi}] MiB "
                                "(a partial offload by llama.cpp's memory fitting falls outside it)")
        rec = {"pid": proc.pid, "endpoint": prov.endpoint(cfg), "build": cfg["build"],
               "build_manifest_sha256": cfg["build_manifest_sha256"], "model_sha256": cfg["model_sha256"],
               "drafter_sha256": cfg["drafter_sha256"],
               "spec": {"type": "draft-dflash", "n_max": N_MAX, "ngld": NGLD},
               "server_cmdline_sha256": cmdline_sha256(cfg), "system_sha256": cfg["system_sha256"],
               "provider_sha256": prov.provider_sha256(), "reasoning_format": prov.REASONING_FORMAT,
               "vram_loaded_mib": used, "started_at": datetime.now().isoformat(timespec="seconds")}
        _write_engine(rec)
        return rec
    except BaseException:
        _kill_tree(proc.pid)
        raise


# ---------------------------------------------------------------- stop, status, ensure_ready

def process_image_path(pid):
    """The executable path of a running process (Windows), or None when it cannot be told."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = wintypes.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return None
        return buf.value
    finally:
        k32.CloseHandle(h)


def _is_our_server(pid, cfg):
    """False only when the PID is alive and demonstrably another program's: a record left by a crash must never make stop()
    kill whatever process was given that PID since."""
    if not (isinstance(pid, int) and prov.pid_alive(pid)):
        return False
    img = process_image_path(pid) if cfg else None
    return img is None or Path(img).name.lower() == Path(cfg["server_exe"]).name.lower()


def stop(cfg=None):
    """Stop the recorded server. Returns (ok, detail); ok False (the PID or the memory did not go within
    vram_unload_timeout_s) is a hard failure the callers exit 7 on. No engine.json: nothing was started here, (True, ...)."""
    try:
        pid = prov.read_engine().get("pid")
    except prov.ProviderError:
        return True, "no engine record: no server to stop"
    try:
        cfg = cfg or settings()
    except ServerRefusal:
        cfg = None
    timeout = int(_config().get("vram_unload_timeout_s", 180))
    if _is_our_server(pid, cfg):
        _kill_tree(pid)
    t0 = time.time()
    while True:
        gone = not _is_our_server(pid, cfg)
        used = gpu_used_mib()
        if gone and used is not None and used < IDLE_MIB:
            prov.engine_path().unlink(missing_ok=True)
            return True, f"stopped in {time.time() - t0:.0f}s (gpu_used={used}MiB)"
        if time.time() - t0 >= timeout:
            return False, (f"TIMEOUT after {timeout}s - pid {pid} gone={gone} gpu_used={used}MiB (limit {IDLE_MIB}MiB); "
                           "engine.json kept")
        time.sleep(POLL_S)


def status(cfg=None):
    cfg = cfg or settings()
    out = {"provider": "llamacpp", "model_tag": cfg.get("model_tag"), "engine_file": prov.engine_path().exists(),
           "pid": None, "pid_alive": False, "health": False, "gpu_used_mib": gpu_used_mib(), "ready": False, "problem": None}
    try:
        eng = prov.read_engine()
        out["pid"] = eng.get("pid")
        out["pid_alive"] = prov.pid_alive(eng.get("pid"))
        out["health"] = prov.health_ok(cfg) if out["pid_alive"] else False
        prov.check_engine_ready(cfg)
        out["ready"] = True
    except prov.ProviderError as e:
        out["problem"] = str(e)
    return out


def ensure_ready(cfg=None, hasher=sha256_file):
    """The engine record of a running, pinned, healthy server; starts one when none runs. ServerRefusal otherwise."""
    cfg = cfg or settings()
    try:
        eng = prov.read_engine()
    except prov.ProviderError:
        return start(cfg, hasher)
    if not prov.pid_alive(eng.get("pid")):
        return start(cfg, hasher)                    # a stale record: start() clears it
    try:
        return prov.check_engine_ready(cfg)
    except prov.ProviderError as e:
        raise ServerRefusal(str(e)) from e


# ---------------------------------------------------------------- command line

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""
    try:
        if cmd == "start":
            print(json.dumps(start(), indent=2))
        elif cmd == "ensure":
            print(json.dumps(ensure_ready(), indent=2))
        elif cmd == "stop":
            ok, detail = stop()
            print(("ok: " if ok else "FAILED: ") + detail)
            return 0 if ok else 7
        elif cmd == "status":
            print(json.dumps(status(), indent=2))
        elif cmd == "begin-run":
            print(json.dumps(begin_run(), indent=2))
        else:
            print(__doc__)
            return 2
    except ServerRefusal as e:
        print(f"::VRAM:: llama-server: {e}", flush=True)
        return 7
    return 0


if __name__ == "__main__":
    sys.exit(main())

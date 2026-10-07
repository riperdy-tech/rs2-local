"""server.py - the lifecycle of the Muse llama-server for gate 2 (registration section 1: Muse Glimmer 30B GGUF and drafter, llama.cpp build b11272, context 32k, the
server's pinned sampling).

    python -m rebuild_harness.gate2.server pins      [--state-dir DIR]     record the sha256 of the model, the drafter and the build folder (disk only; no GPU, no server)
    python -m rebuild_harness.gate2.server cmdline                         print the gate-2 command line and how it differs from the pinned one
    python -m rebuild_harness.gate2.server status    [--state-dir DIR]

THE COMMAND LINE is the pinned production line (`llamacpp_server.build_cmdline(cfg)` over the `llamacpp` block of config.json) with ONE difference: `-c 32768` where the
pinned line has `-c 98304` (the registered gate-2 context; the production window is 98304).  Every other flag (-np 1 -ngl 99 -fa on -ctk q8_0 -ctv q8_0 --jinja --temp 1.0
--top-p 0.95 --top-k 64 --min-p 0 --reasoning-format deepseek -md <drafter> --spec-type draft-dflash --spec-draft-n-max 15 -ngld 99) is the pinned one.  `window_difference`
proves it: the production line must hash to the config's pinned `server_cmdline_sha256`, and the two lines must be equal once the `-c` value is made equal.

WHAT THIS DOES NOT TOUCH.  `llamacpp_server.start()` writes the production engine record under rs2-local's cache and checks the 98304 window and the depth config; none of that
applies to a replay, and the production provider reads that record.  This module therefore launches the same command itself and keeps its own record under the gate-2 state
folder (`server/engine.json`, `server/pins.json`, the server logs).  It imports `llamacpp_server` only for its pure helpers (the command-line builder and the hashing helpers).

STARTING.  `start()` refuses unless the pins record exists and holds (model, drafter and build folder as recorded: size and modification time compared, the sha256 taken once by
`record_pins`) and the port is free; it never decides whether the GPU is free (the runner's GPU wait does, and the runner only calls start() when it is).  It launches the
command (Popen, no shell, output to a log), waits for /health, requires `n_ctx_slot = 32768` and `n_max=15` in the log and the weights on the GPU, records the VRAM it settled at,
and writes engine.json.  Any failure after the launch kills the server and refuses.  `stop()` kills only a process whose image is the pinned llama-server.exe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import config

IDLE_MIB = 200
HEALTH_POLL_S = 1.0


class ServerRefusal(RuntimeError):
    pass


# ---- the pinned configuration and the gate-2 line -----------------------------------------------------------------------------------------

def load_cfg(path: Optional[Path] = None) -> dict:
    """The `llamacpp` block of config.json: RS2_CONFIG_PATH when set, else this repository's config.json."""
    p = Path(path) if path is not None else Path(os.environ.get("RS2_CONFIG_PATH") or (config.REPO / "config.json"))
    cfg = json.loads(p.read_text(encoding="utf-8")).get("llamacpp")
    if not isinstance(cfg, dict):
        raise ServerRefusal(f"{p} has no llamacpp block")
    return cfg


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pinned_cmdline(cfg: dict, build: Optional[Callable] = None) -> str:
    if build is None:
        import llamacpp_server
        build = llamacpp_server.build_cmdline
    return build(cfg)


def gate2_cmdline(cfg: dict, build: Optional[Callable] = None) -> str:
    """The pinned production command line with `-c 98304` replaced by `-c 32768`; refuses when the pinned line does not carry the 98304 window exactly once."""
    base = pinned_cmdline(cfg, build)
    needle = f" -c {config.PINNED_WINDOW} "
    if base.count(needle) != 1:
        raise ServerRefusal(f"the pinned command line does not carry {needle.strip()!r} exactly once: {base}")
    return base.replace(needle, f" -c {config.CONTEXT} ")


def window_difference(cfg: dict, build: Optional[Callable] = None) -> dict:
    """The proof that the gate-2 line differs from the pinned one in the context only."""
    base = pinned_cmdline(cfg, build)
    g2 = gate2_cmdline(cfg, build)
    same_after = g2.replace(f" -c {config.CONTEXT} ", f" -c {config.PINNED_WINDOW} ") == base
    return {"pinned_cmdline": base, "pinned_cmdline_sha256": _sha(base.encode("utf-8")), "config_pins_sha256": cfg.get("server_cmdline_sha256"),
            "pinned_line_matches_config_pin": _sha(base.encode("utf-8")) == cfg.get("server_cmdline_sha256"), "gate2_cmdline": g2,
            "gate2_cmdline_sha256": _sha(g2.encode("utf-8")), "pinned_window": config.PINNED_WINDOW, "gate2_window": config.CONTEXT,
            "equal_after_the_window_is_equalised": same_after}


# ---- the pins record --------------------------------------------------------------------------------------------------------------------

def sha256_file(path, chunk=16 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _stat(p) -> dict:
    st = Path(p).stat()
    return {"path": str(Path(p)), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def build_files(folder) -> List[dict]:
    root = Path(folder)
    out = []
    for dirpath, _d, files in os.walk(root):
        for n in files:
            p = Path(dirpath) / n
            st = p.stat()
            out.append({"path": p.relative_to(root).as_posix(), "size": st.st_size, "mtime_ns": st.st_mtime_ns})
    return sorted(out, key=lambda e: e["path"].lower())


def build_manifest(folder, hasher: Callable = sha256_file) -> Tuple[List[dict], str]:
    """([{path, sha256, size}], manifest sha256): the same manifest llamacpp_server pins (`build_manifest_sha256`)."""
    root = Path(folder)
    entries = []
    for dirpath, _d, files in os.walk(root):
        for n in files:
            p = Path(dirpath) / n
            entries.append({"path": p.relative_to(root).as_posix(), "sha256": hasher(p), "size": p.stat().st_size})
    entries = sorted(entries, key=lambda e: e["path"].lower())
    return entries, _sha(json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def pins_path(state_dir=None) -> Path:
    return config.state_paths(state_dir)["server"] / "pins.json"


def record_pins(cfg: dict, state_dir=None, hasher: Callable = sha256_file) -> dict:
    """The full sha256 of the model, the drafter and the build folder, compared with the config's pins and written to `server/pins.json`.  Refuses on any difference."""
    rec = {"taken_at": datetime.now().isoformat(timespec="seconds"), "build": cfg.get("build")}
    bad = []
    for key, path_key in (("model", "model_path"), ("drafter", "drafter_path")):
        r = _stat(cfg[path_key])
        r["sha256"] = hasher(cfg[path_key])
        rec[key] = r
        if r["sha256"] != cfg[key + "_sha256"]:
            bad.append(f"{key} sha256 {r['sha256']} is not the pinned {cfg[key + '_sha256']}")
    folder = Path(cfg["server_exe"]).parent
    _entries, msha = build_manifest(folder, hasher)
    rec["build_folder"] = {"folder": str(folder), "manifest_sha256": msha, "files": build_files(folder)}
    if msha != cfg["build_manifest_sha256"]:
        bad.append(f"build folder {folder} hashes to manifest {msha}, pinned {cfg['build_manifest_sha256']}")
    if bad:
        raise ServerRefusal("; ".join(bad))
    p = pins_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def pins_problems(cfg: dict, state_dir=None) -> List[str]:
    """Why the recorded pins no longer describe the files on disk (empty: they do)."""
    p = pins_path(state_dir)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"no pins record at {p}: run `python -m rebuild_harness.gate2.server pins` first (it hashes the model, the drafter and the build folder)"]
    except (OSError, ValueError) as e:
        return [f"the pins record {p} is unreadable: {e}"]
    bad = []
    for key, path_key in (("model", "model_path"), ("drafter", "drafter_path")):
        r = rec.get(key) or {}
        try:
            now = _stat(cfg[path_key])
        except OSError as e:
            bad.append(f"{key} {cfg[path_key]} cannot be read: {e}")
            continue
        if r.get("path") != now["path"]:
            bad.append(f"{key}: the pins record is for {r.get('path')!r}, the config says {now['path']!r}")
        elif (r.get("size"), r.get("mtime_ns")) != (now["size"], now["mtime_ns"]):
            bad.append(f"{key} {now['path']} changed since the pins were recorded (size or modification time)")
        if r.get("sha256") != cfg[key + "_sha256"]:
            bad.append(f"{key}: the pins record has sha256 {r.get('sha256')}, pinned {cfg[key + '_sha256']}")
    bf = rec.get("build_folder") or {}
    if bf.get("manifest_sha256") != cfg["build_manifest_sha256"]:
        bad.append("the pins record's build manifest is not the pinned one")
    try:
        if build_files(bf.get("folder") or Path(cfg["server_exe"]).parent) != bf.get("files"):
            bad.append("the build folder's files changed since the pins were recorded (a name, size or modification time differs)")
    except OSError as e:
        bad.append(f"the build folder cannot be read: {e}")
    return bad


# ---- the machine seams ----------------------------------------------------------------------------------------------------------------

def _spawn(cmdline: str, log_path: Path):
    log = open(log_path, "ab")
    try:
        return subprocess.Popen(cmdline, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        log.close()


def _health(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _gpu_used() -> Optional[int]:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30)
        return int(r.stdout.strip().splitlines()[0].strip()) if r.returncode == 0 else None
    except Exception:
        return None


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex((host, int(port))) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, int(port)))
        except OSError:
            return False
    return True


def _kill_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
    except Exception:
        pass


def _pid_alive(pid) -> bool:
    if not isinstance(pid, int):
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return True
    return str(pid) in out


def _image_name(pid: int) -> Optional[str]:
    try:
        import llamacpp_server
        p = llamacpp_server.process_image_path(pid)
    except Exception:
        return None
    return None if p is None else Path(p).name.lower()


class Gate2Server:
    """The Muse server of one gate-2 job.  Every machine seam is a constructor argument, so the tests start nothing."""

    def __init__(self, cfg: dict, state_dir=None, *, spawn=_spawn, health=_health, gpu_used=_gpu_used, port_free=_port_free, kill=_kill_tree, pid_alive=_pid_alive,
                 image_name=_image_name, sleep=time.sleep, clock=time.time, build_cmd: Optional[Callable] = None):
        self.cfg = cfg
        self.paths = config.state_paths(state_dir)
        self.dir = self.paths["server"]
        self.state_dir = state_dir
        self.spawn, self.health, self.gpu_used, self.port_free, self.kill, self.pid_alive = spawn, health, gpu_used, port_free, kill, pid_alive
        self.image_name, self.sleep, self.clock, self.build_cmd = image_name, sleep, clock, build_cmd

    # -- records --
    @property
    def endpoint(self) -> str:
        return f"http://{self.cfg['host']}:{self.cfg['port']}"

    @property
    def engine_file(self) -> Path:
        return self.dir / "engine.json"

    def read_engine(self) -> Optional[dict]:
        try:
            return json.loads(self.engine_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def our_pids(self) -> List[int]:
        e = self.read_engine()
        return [e["pid"]] if e and self.pid_alive(e.get("pid")) else []

    def our_vram_mib(self) -> Optional[int]:
        e = self.read_engine()
        return None if not e else e.get("vram_loaded_mib")

    def is_up(self) -> bool:
        e = self.read_engine()
        return bool(e) and self.pid_alive(e.get("pid")) and self.health(self.endpoint)

    # -- refusals --
    def refusals(self) -> List[str]:
        bad = []
        try:
            wd = window_difference(self.cfg, self.build_cmd)
            if not wd["pinned_line_matches_config_pin"]:
                bad.append(f"the pinned command line hashes to {wd['pinned_cmdline_sha256']}, the config pins {wd['config_pins_sha256']}")
            if not wd["equal_after_the_window_is_equalised"]:
                bad.append("the gate-2 command line differs from the pinned one in more than the context window")
        except ServerRefusal as e:
            bad.append(str(e))
        bad += pins_problems(self.cfg, self.state_dir)
        if not self.port_free(self.cfg["host"], self.cfg["port"]):
            bad.append(f"port {self.cfg['host']}:{self.cfg['port']} is not free")
        return bad

    # -- start --
    def start(self) -> dict:
        eng = self.read_engine()
        if eng is not None and not self.pid_alive(eng.get("pid")):
            self.engine_file.replace(self.dir / f"engine_stale_{datetime.now():%Y%m%d_%H%M%S}.json")     # the record of a dead server describes nothing: moved aside, never deleted
        bad = self.refusals()
        if bad:
            raise ServerRefusal("; ".join(bad))
        baseline = self.gpu_used()
        if baseline is None or baseline > config.BUSY_MIB:
            raise ServerRefusal(f"GPU memory in use is {baseline} MiB (limit {config.BUSY_MIB} before the load): the card is not free")
        cmd = gate2_cmdline(self.cfg, self.build_cmd)
        self.dir.mkdir(parents=True, exist_ok=True)
        log_path = self.dir / f"server_{datetime.now():%Y%m%d_%H%M%S}.log"
        proc = self.spawn(cmd, log_path)
        try:
            deadline = self.clock() + float(self.cfg["load_timeout_s"])
            while True:
                if proc.poll() is not None:
                    raise ServerRefusal(f"llama-server exited with code {proc.returncode} before /health answered 200")
                if self.health(self.endpoint):
                    break
                if self.clock() >= deadline:
                    raise ServerRefusal(f"llama-server did not answer /health 200 within load_timeout_s={self.cfg['load_timeout_s']}")
                self.sleep(HEALTH_POLL_S)
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            if not re.search(rf"n_ctx_slot = {config.CONTEXT}\b", log):
                raise ServerRefusal(f"the server log does not carry n_ctx_slot = {config.CONTEXT} ({log_path})")
            if not re.search(r"n_max=15\b", log):
                raise ServerRefusal(f"the server log does not carry n_max=15 ({log_path})")
            m = re.search(r"offloaded (\d+)/(\d+) layers to GPU", log)
            if m and m.group(1) != m.group(2):
                raise ServerRefusal(f"only {m.group(1)} of {m.group(2)} layers were offloaded to the GPU (log {log_path})")
            used = self.gpu_used()
            model_mib = Path(self.cfg["model_path"]).stat().st_size / 2 ** 20 if Path(self.cfg["model_path"]).exists() else 0
            if used is None or (model_mib and used - baseline < 0.8 * model_mib):
                raise ServerRefusal(f"GPU memory in use after the load is {used} MiB (before: {baseline}); the weights ({model_mib:.0f} MiB) are not on the GPU")
            wd = window_difference(self.cfg, self.build_cmd)
            rec = {"pid": proc.pid, "endpoint": self.endpoint, "build": self.cfg.get("build"), "build_manifest_sha256": self.cfg["build_manifest_sha256"],
                   "model_sha256": self.cfg["model_sha256"], "drafter_sha256": self.cfg["drafter_sha256"], "cmdline": cmd, "cmdline_sha256": wd["gate2_cmdline_sha256"],
                   "pinned_cmdline_sha256": wd["pinned_cmdline_sha256"], "window": config.CONTEXT, "vram_baseline_mib": baseline, "vram_loaded_mib": used,
                   "log": str(log_path), "started_at": datetime.now().isoformat(timespec="seconds")}
            tmp = self.engine_file.with_name("engine.json.tmp")
            tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            os.replace(tmp, self.engine_file)
            return rec
        except BaseException:
            self.kill(proc.pid)
            raise

    # -- stop --
    def stop(self, timeout: float = 180.0) -> Tuple[bool, str]:
        """Stop OUR server (the pid of engine.json, and only while its image is the pinned llama-server.exe).  (ok, detail); ok False when the process did not go."""
        e = self.read_engine()
        if e is None:
            return True, "no engine record: no server of ours to stop"
        pid = e.get("pid")
        want = Path(self.cfg["server_exe"]).name.lower()

        def ours() -> bool:
            if not self.pid_alive(pid):
                return False
            img = self.image_name(pid)
            return img is None or img == want
        if ours():
            self.kill(pid)
        t0 = self.clock()
        while True:
            if not ours():
                used = self.gpu_used()
                base = e.get("vram_baseline_mib")
                if used is None or base is None or used <= base + 1024 or used < IDLE_MIB:
                    self.engine_file.with_name("engine.json").replace(self.dir / f"engine_stopped_{datetime.now():%Y%m%d_%H%M%S}.json")
                    return True, f"stopped in {self.clock() - t0:.0f}s (gpu_used={used} MiB)"
            if self.clock() - t0 >= timeout:
                return False, f"TIMEOUT after {timeout:.0f}s: pid {pid} alive={self.pid_alive(pid)} gpu_used={self.gpu_used()}"
            self.sleep(1.0)

    def ensure_up(self) -> dict:
        """The engine record of a running healthy server; starts one when none runs (the caller has checked that the GPU is free)."""
        if self.is_up():
            return self.read_engine()
        e = self.read_engine()
        if e is not None and self.pid_alive(e.get("pid")):        # alive but not healthy: ours, stopped before a fresh start
            ok, detail = self.stop()
            if not ok:
                raise ServerRefusal(f"an unhealthy server of ours could not be stopped: {detail}")
        return self.start()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["pins", "cmdline", "status"])
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--config", type=Path)
    a = ap.parse_args(argv)
    cfg = load_cfg(a.config)
    try:
        if a.cmd == "cmdline":
            print(json.dumps(window_difference(cfg), indent=2))
        elif a.cmd == "pins":
            r = record_pins(cfg, a.state_dir)
            print(json.dumps({k: (v if k != "build_folder" else {"manifest_sha256": v["manifest_sha256"], "n_files": len(v["files"])}) for k, v in r.items()}, indent=2))
        else:
            s = Gate2Server(cfg, a.state_dir)
            print(json.dumps({"up": s.is_up(), "engine": s.read_engine(), "pins_problems": pins_problems(cfg, a.state_dir)}, indent=2))
    except ServerRefusal as e:
        print(f"REFUSED: {e}")
        return 7
    return 0


if __name__ == "__main__":
    sys.exit(main())

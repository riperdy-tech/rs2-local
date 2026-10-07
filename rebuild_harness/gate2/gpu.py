"""gpu.py - who else is using the GPU, and the wait that never skips (registration section 2: "the run goes through a scheduled task"; memory: the operator games on this card).

The logic is the baseline runner's (scratch/baseline-2026-10/baseline_runner.py `other_gpu_use`), adapted to a job that owns the WHOLE card (the Muse server takes about
22 of 24 GiB, so no Ollama model of any kind can be resident beside it):

  * a model loaded in Ollama (any: this job owns no Ollama model);
  * a CUDA compute process other than our own llama-server (an `ollama` process is not counted here: its models are, through the previous rule, and a lingering process
    without a model is caught by the memory rule);
  * VRAM in use that is not ours: more than BUSY_MIB while nothing of ours is loaded (a game or another program), or more than BUSY_MIB above what our server took when
    it is loaded;
  * another session's GPU-test lock (`scratch/gpu_tests.lock`, holding a live PID), as the baseline honours it;
  * an unreadable card ("unknown" is never "idle").

`other_gpu_use` returns the reason as text or None.  `wait_until_free` polls and never skips.  The probes are injectable (`Probe`), so the tests run no nvidia-smi and
no Ollama.  Nothing here loads or unloads a model; the runner stops OUR server when this says the card is not free.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from . import config


class Probe:
    """The machine as seen by nvidia-smi, Ollama's /api/ps and the task list.  Every method may be replaced in a test."""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url.rstrip("/")

    def ollama_loaded(self) -> Optional[List[str]]:
        """Names of the models Ollama has loaded; [] when its server does not answer (no server, no model); None never (an unreadable answer is a wait)."""
        try:
            with urllib.request.urlopen(self.ollama_url + "/api/ps", timeout=20) as r:
                return [str(m.get("name", "")).split(":")[0] for m in (json.loads(r.read().decode()).get("models") or [])]
        except urllib.error.URLError:
            return []
        except (OSError, ValueError):
            return None

    def compute_apps(self) -> Optional[List[Tuple[int, str]]]:
        try:
            r = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        out = []
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            pid, _, name = line.partition(",")
            try:
                out.append((int(pid.strip()), name.strip()))
            except ValueError:
                out.append((-1, line.strip()))
        return out

    def used_mib(self) -> Optional[int]:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=60)
            return int(r.stdout.strip().splitlines()[0].strip()) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    def pid_alive(self, pid: int) -> bool:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            return True                      # cannot tell: the lock is honoured
        return str(pid) in out


def test_lock_path() -> Path:
    """Another session's GPU-test lock: `<workspace>/scratch/gpu_tests.lock` (the baseline runner's convention)."""
    return config.WORKSPACE / "scratch" / "gpu_tests.lock"


def test_lock_holder(probe: Probe, path: Optional[Path] = None) -> Optional[int]:
    p = Path(path) if path is not None else test_lock_path()
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if probe.pid_alive(pid) else None


def other_gpu_use(probe: Probe, *, ours_pids: Iterable[int] = (), ours_loaded: bool = False, our_mib: Optional[int] = None, busy_mib: int = config.BUSY_MIB,
                  lock_path: Optional[Path] = None) -> Optional[str]:
    """Why the card is not ours alone right now, or None.  `ours_loaded`: our llama-server is running, with `our_mib` of VRAM recorded when it settled."""
    ours = set(ours_pids)
    holder = test_lock_holder(probe, lock_path)
    if holder is not None:
        return f"another session holds the GPU-test lock (pid {holder})"
    loaded = probe.ollama_loaded()
    if loaded is None:
        return "Ollama's /api/ps cannot be read: whether a model is loaded is not known"
    if loaded:
        return f"Ollama has a model loaded: {loaded}"
    apps = probe.compute_apps()
    if apps is None:
        return "nvidia-smi cannot list the compute processes: the card is not known to be idle"
    others = [f"{pid}:{name}" for pid, name in apps if pid not in ours and "ollama" not in name.lower()]
    if others:
        return f"another process is using the GPU: {others}"
    used = probe.used_mib()
    if used is None:
        return "GPU memory in use cannot be read: the card is not known to be idle"
    if not ours_loaded:
        if used > busy_mib:
            return f"{used} MiB of VRAM in use with nothing of ours loaded (a game or another program)"
    elif our_mib is not None and used - our_mib > busy_mib:
        return f"{used} MiB of VRAM in use, {used - our_mib} MiB more than our server took (a game or another program started)"
    return None


def wait_until_free(check: Callable[[], Optional[str]], *, sleep: Callable[[float], None] = time.sleep, poll: float = config.POLL_SECONDS,
                    on_change: Optional[Callable[[Optional[str]], None]] = None, max_polls: Optional[int] = None) -> int:
    """Poll `check()` (a reason, or None when free) until it says free; never skips.  `on_change(reason)` is called whenever the reason changes.  Returns the number of polls
    that waited.  `max_polls` exists for the tests only (a loop that must end)."""
    said: object = object()                # nothing said yet: the first reason is always reported
    waited = 0
    while True:
        why = check()
        if why is None:
            return waited
        if why != said:
            if on_change is not None:
                on_change(why)
            said = why
        waited += 1
        if max_polls is not None and waited >= max_polls:
            raise TimeoutError(f"still not free after {waited} polls: {why}")
        sleep(poll)

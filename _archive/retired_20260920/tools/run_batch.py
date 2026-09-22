#!/usr/bin/env python3
"""run_batch.py — the ONLY sanctioned way to launch an orchestrate batch.

Written 2026-08-12 after both failure modes bit repeatedly in one session and made several
hours of test results uninterpretable:

  1. LOCK COLLISION. orchestrate exits immediately when another instance holds
     cache/orchestrate.lock. That is correct behaviour, but the launcher then reported
     "0 clean / 5" — indistinguishable from a real failure. Two separate diagnoses were
     built on runs that never executed a single ticker.
  2. MID-FLIGHT EDITS. Engine files were edited while a batch was running. Every ticker is
     a fresh subprocess, so later names silently ran DIFFERENT code from earlier ones and
     the batch could not be read as one experiment.

This wrapper makes both impossible to miss:
  * refuses to start while a live lock exists (and says whose PID holds it);
  * records the git SHA + dirty state at launch, re-checks at exit, and marks the batch
    CONTAMINATED in its own log if the working tree changed while it ran;
  * writes a machine-readable receipt next to the log so result-mining can assert the run
    actually happened on stable code before believing its numbers.

Usage:
    python tools/run_batch.py --tickers "A,B,C" --log reports/_x.log [--limit N] [--pause-after]
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
LOCK = HERE / "cache" / "orchestrate.lock"
PAUSE = HERE / "cache" / "PAUSED"
ENGINE_FILES = ("run_rs2.py", "rs2_data.py", "valuation_backbone.py", "orchestrate.py",
                "RS2-Analyst.Modelfile", "config.json", "outcome_feedback.py")


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=str(HERE), capture_output=True,
                              text=True, encoding="utf-8").stdout.strip()
    except Exception:
        return ""


def engine_fingerprint():
    """SHA of HEAD plus a hash of the engine files' current bytes — catches uncommitted
    edits, which are what actually reach a running subprocess."""
    import hashlib
    h = hashlib.sha256()
    for f in ENGINE_FILES:
        p = HERE / f
        if p.exists():
            h.update(p.read_bytes())
    return _git("rev-parse", "--short", "HEAD"), h.hexdigest()[:12]


def lock_holder():
    if not LOCK.exists():
        return None
    try:
        return LOCK.read_text(encoding="utf-8-sig").split()[0]
    except Exception:
        return "unreadable"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pause-after", action="store_true",
                    help="re-create cache/PAUSED when the batch finishes")
    ap.add_argument("--wait-lock", type=int, default=0,
                    help="seconds to wait for an existing lock to clear (0 = fail immediately)")
    a = ap.parse_args()

    waited = 0
    while (holder := lock_holder()) and waited < a.wait_lock:
        time.sleep(15)
        waited += 15
    if holder := lock_holder():
        print(f"REFUSING TO LAUNCH: cache/orchestrate.lock held by pid {holder}. "
              f"A batch is already running — wait for it, or the results of BOTH runs are "
              f"uninterpretable.", file=sys.stderr)
        return 2

    n = len([x for x in a.tickers.split(",") if x.strip()])
    sha0, fp0 = engine_fingerprint()
    started = datetime.now()
    print(f"[run_batch] {n} tickers | engine {sha0}/{fp0} | log {a.log}")
    PAUSE.unlink(missing_ok=True)

    cmd = [sys.executable, str(HERE / "orchestrate.py"), "--unanchored",
           "--tickers", a.tickers, "--no-push"]
    if a.limit:
        cmd += ["--limit", str(a.limit)]
    with open(HERE / a.log, "w", encoding="utf-8", errors="replace") as fh:
        rc = subprocess.run(cmd, cwd=str(HERE), stdout=fh, stderr=subprocess.STDOUT).returncode

    sha1, fp1 = engine_fingerprint()
    clean = (sha0, fp0) == (sha1, fp1)
    if a.pause_after:
        PAUSE.write_text(f"paused by run_batch at {datetime.now():%H:%M:%S}", encoding="utf-8")
    receipt = {
        "tickers": a.tickers, "n": n, "log": a.log, "returncode": rc,
        "started": started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine_at_start": f"{sha0}/{fp0}", "engine_at_end": f"{sha1}/{fp1}",
        "code_stable": clean,
        "verdict": "CLEAN" if (clean and rc == 0) else
                   ("CONTAMINATED — engine files changed mid-run" if not clean else
                    f"orchestrate exited {rc}"),
    }
    rp = HERE / (a.log + ".receipt.json")
    rp.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"[run_batch] {receipt['verdict']} | receipt {rp.name}")
    return 0 if (clean and rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())

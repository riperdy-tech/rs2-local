"""Backtest registration section 3, "load each arm's modules in its own process": one arm, one process.

  python -m backtest_phase2.arm_worker --arm baseline|candidate --tree <rs2 tree> --job <job.json> --out <result.json>

The tree's `tools/` directory is put on sys.path (the baseline tree at rs2-local fee17cf, the candidate tree at ac68e25) and
the revision's own consensus_reference (and, for the candidate, throughcycle_record) is imported from it.  The two revisions
therefore never share a process.  The worker blocks every socket, never writes bytecode into a revision's tree, records which
files it actually loaded, and refuses to run if the loaded module is not under the tree it was given.

Job types are in jobs.py; each returns a JSON-able dict.
"""
import argparse
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

sys.dont_write_bytecode = True


class _Blocked(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("Socket access blocked in this step")


def _no_net(*a, **k):
    raise RuntimeError("Network access blocked in this step")


socket.socket = _Blocked
socket.getaddrinfo = _no_net
socket.create_connection = _no_net


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_arm(arm, tree):
    """Import the arm's revision from `tree`.  Returns (cref, tcr or None, identity dict)."""
    tree = Path(tree).resolve()
    tools = tree / "tools"
    sys.path.insert(0, str(tools))
    import consensus_reference as cref
    tcr = None
    if arm == "candidate":
        import throughcycle_record as tcr
    cref_path = Path(cref.__file__).resolve()
    if tools not in cref_path.parents:
        raise RuntimeError(f"consensus_reference loaded from {cref_path}, not from {tools}")
    if arm == "baseline" and ("throughcycle_record" in sys.modules or hasattr(cref, "long_run_value")):
        raise RuntimeError("the baseline process holds revision 17 code")
    if arm == "candidate" and not hasattr(cref, "long_run_value"):
        raise RuntimeError("the candidate process holds revision 16 code")
    ident = {"arm": arm, "tree": str(tree), "consensus_reference": str(cref_path), "consensus_reference_sha256": sha256_file(cref_path),
             "has_long_run_value": hasattr(cref, "long_run_value"),
             "throughcycle_record": str(Path(tcr.__file__).resolve()) if tcr is not None else None,
             "throughcycle_record_sha256": sha256_file(tcr.__file__) if tcr is not None else None,
             "throughcycle_record_loaded": "throughcycle_record" in sys.modules}
    return cref, tcr, ident


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["baseline", "candidate"])
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--job", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    harness_root = Path(__file__).resolve().parents[1]
    cref, tcr, ident = load_arm(a.arm, a.tree)
    if str(harness_root) not in sys.path:
        sys.path.append(str(harness_root))                 # after the revision's tools: the harness package name is unique
    from backtest_phase2 import jobs
    job = json.loads(a.job.read_text(encoding="utf-8"))
    if tcr is not None and job.get("calibration"):
        tcr.CALIBRATION_FILE = Path(job["calibration"])
        tcr.calibration.cache_clear()
        ident["calibration_file"] = job["calibration"]
        ident["calibration_sha256"] = sha256_file(job["calibration"])
    result = jobs.run(a.arm, cref, tcr, job)
    result["identity"] = ident
    result["modules_loaded"] = sorted(m for m in ("consensus_reference", "throughcycle_record") if m in sys.modules)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result), encoding="utf-8")
    print("worker done", a.arm, a.job.name)


if __name__ == "__main__":
    main()

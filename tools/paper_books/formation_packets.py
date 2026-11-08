"""formation_packets.py - WO_O2 step 2: one builder-v6 packet per book name of a formation map, regime verified, online (SEC).

    python tools/paper_books/formation_packets.py 2026-10-30

Names in state `to_build` are built through the qwen_c packet CLI (python -m qwen_c.packet, run from this repository's root); a refusal sets state `analysis_incomplete` with its reason. The map
is rewritten after each name (tmp + replace), so the script resumes. Excluded names are never built.
The map's "candidates" (paper book FD) are built the same way after the book names: state built, or packet_refused with its reason.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402

ROOT = HERE.parents[1]                                                    # the rs2-local repo root: qwen_c runs from here
PY = sys.executable
INPUTS = book_paths.books() / "m3o" / "inputs"


def screener():
    """The screener clone whose git objects hold the output commits: paths.py screener_publish_repo (the clone the verifier fetches)."""
    return str(book_paths.screener_repo())


def save(path, m):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def build(t, m):
    return subprocess.run([PY, "-m", "qwen_c.packet", "--ticker", t, "--T", m["decision_time_utc"], "--commit", m["output_commit"],
                           "--verified-record", m["verified_record"], "--screener-repo", screener(), "--online"],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def build_candidates(path, m):
    for c in m.get("candidates") or []:
        if c["state"] != "to_build":
            continue
        r = build(c["ticker"], m)
        try:
            out = json.loads(r.stdout[r.stdout.index("{"):])
            pk = json.loads(Path(out["packet"]).read_text(encoding="utf-8"))
            if m["builder_version"] not in (None, pk["builder_version"]):
                sys.exit(f"STOP: candidate {c['ticker']} built with {pk['builder_version']}, the map holds {m['builder_version']}")
            c.update(packet=out["packet"], packet_sha256=out["packet_sha256"], state="built", annotations=out["annotations"])
        except (ValueError, KeyError, OSError):
            c.update(state="packet_refused", detail=(r.stderr or r.stdout)[-600:])
        save(path, m)
        print("candidate", c["ticker"], c["state"], flush=True)


def main():
    path = INPUTS / f"formation_{sys.argv[1]}.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    for t, n in sorted(m["names"].items()):
        if n["state"] != "to_build":
            continue
        r = build(t, m)
        try:
            out = json.loads(r.stdout[r.stdout.index("{"):])
            pk = json.loads(Path(out["packet"]).read_text(encoding="utf-8"))
            n.update(packet=out["packet"], packet_sha256=out["packet_sha256"], state="to_run",
                     annotations=out["annotations"], trimmed=sum(a.startswith("trimmed") for a in out["annotations"]),
                     gc_omitted=sum(a.startswith("gc_passages_omitted") for a in out["annotations"]))
            if m["builder_version"] not in (None, pk["builder_version"]):
                sys.exit(f"STOP: {t} built with {pk['builder_version']}, the map holds {m['builder_version']}")
            m["builder_version"] = pk["builder_version"]
        except (ValueError, KeyError, OSError):
            n.update(state="analysis_incomplete", reason="packet_refused", detail=(r.stderr or r.stdout)[-600:])
        save(path, m)
        print(t, n["state"], n.get("packet_sha256", n.get("detail", "")[-120:]), flush=True)
    build_candidates(path, m)
    return 0


if __name__ == "__main__":
    sys.exit(main())

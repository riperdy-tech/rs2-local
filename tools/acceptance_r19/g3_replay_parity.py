"""Revision 19, G3 (brief_rev19.md section 8): frozen-replay parity on built packs. OFFLINE: sockets are blocked, nothing but a temporary folder is written.

  python g3_replay_parity.py --tree <rs2 tree> --root <data root: enrich/ cache/ research/> --sd <screener data dir> --mri <MRI anchors dir>
         --date YYYY-MM-DD --closure <artifact> --names <file, one development name per line> [--json]

For each name: the pack is built fresh (tools/acceptance_r18/build_day.build_rows), its facts are written as the run's sidecar (_pack_facts.json)
and read back as a `--pack-file` replay reads them, and the desk context each gives (consensus_valuation.build_desk_context, the one function main
uses) is compared key for key and value for value. This is what lets the registration's attribution arms value exactly what the production run valued.
Development names only; the output lists names and the keys that differ (none when the replay is faithful).
"""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "acceptance_r18"))
import accept_common as ac  # noqa: E402


def differences(a, b, path=""):
    """The paths at which two values differ, key for key and value for value (a nan equals a nan; the types must agree too)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            out += [f"{path}/{k}"] if (k not in a or k not in b) else differences(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return [f"{path}[len]"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return []
    return [] if (a == b and type(a) is type(b)) else [path]


def parity_for(ns, rows):
    """{name: {"keys": the number of keys of the fresh context, "differences": [paths]}} for the built rows."""
    import consensus_valuation as cv
    pack_facts = ns.pack_facts
    out = {}
    for t, r in sorted(rows.items()):
        if r.get("error") is not None:
            out[t] = {"error": str(r["error"])[:120]}
            continue
        facts = r["facts"]
        price = facts.get("price_implied_price")
        price = price if isinstance(price, (int, float)) else (r.get("price") or 1.0)
        fresh = cv.build_desk_context(facts, price, t, t)
        with tempfile.TemporaryDirectory() as d:
            pack_facts.write_sidecar(d, facts)
            replay = cv.build_desk_context(pack_facts.read_sidecar(d), price, t, t)
        out[t] = {"keys": len(fresh), "differences": differences(fresh, replay)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("tree", "root", "sd", "mri", "names"):
        ap.add_argument("--" + name, required=True, type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--closure", default=None, type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ns = ac.bootstrap(a.tree, a.sd, a.mri, a.root, a.date, closure=a.closure)
    import build_day
    names = [l.strip() for l in a.names.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows, _meta = build_day.build_rows(ns, names, progress=False, enrich_label="book")
    result = parity_for(ns, rows)
    print(json.dumps(result, indent=None if a.json else 1))
    return 0 if result and all("differences" in v and not v["differences"] for v in result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

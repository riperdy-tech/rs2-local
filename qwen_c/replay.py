"""replay.py - the M-P4 pack replay gate of qwen_c (SPEC_m3m_qwen_pipeline.md §7).

`replay(packet_path)` rebuilds a stored packet offline from exactly its `raw_inputs` (sec_store.get_pinned: the url and the sha256 it
pinned, nothing else) and the screener git blobs at its commit, and compares the canonical bytes with the stored file. A document the
rebuild asks for that the packet did not pin raises NotInStore; stored bytes that no longer hash to their name raise StoreCorrupt.

The verified-record check is a build-time precondition: replay re-runs every other refusal (excluded ticker, ticker and CIK in the
screener blobs, commit dated after T, and the run-time check of the packet's pinned `verified_row` against T) and carries that row
through unchanged.

CLI: `python -m qwen_c.replay [--dir cache/m3m/packets]` replays every packet there, prints one JSON line each, and exits 0 only when
there is at least one packet and every one is identical.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from qwen_c import packet, sec_store


def _short(v):
    s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 200 else s[:200] + "..."


def first_diff(a, b, path="$"):
    """The first place (in sorted-key, index order) where the stored value `a` and the rebuilt value `b` differ, or None."""
    if type(a) is not type(b):
        return {"path": path, "stored": _short(a), "rebuilt": _short(b)}
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return {"path": f"{path}.{k}", "stored": _short(a.get(k)) if k in a else "<absent>",
                        "rebuilt": _short(b.get(k)) if k in b else "<absent>"}
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        for i in range(max(len(a), len(b))):
            if i >= len(a) or i >= len(b):
                return {"path": f"{path}[{i}]", "stored": _short(a[i]) if i < len(a) else "<absent>",
                        "rebuilt": _short(b[i]) if i < len(b) else "<absent>"}
            d = first_diff(a[i], b[i], f"{path}[{i}]")
            if d:
                return d
        return None
    if a != b:
        return {"path": path, "stored": _short(a), "rebuilt": _short(b)}
    return None


def replay(packet_path, *, store_root=None, screener_repo_path=None):
    """{"identical", "first_diff", "stored_sha256", "rebuilt_sha256"} of one stored packet, rebuilt from its pinned inputs."""
    stored = Path(packet_path).read_bytes()
    pk = json.loads(stored.decode("utf-8"))
    pinned = {}
    for ri in pk["raw_inputs"]:
        if pinned.get(ri["url"], ri["sha256"]) != ri["sha256"]:
            raise packet.PacketError(f"{ri['url']} is pinned to two sha256 values")
        pinned[ri["url"]] = ri["sha256"]

    def get(url):
        if url not in pinned:
            raise sec_store.NotInStore(f"{url} is not a raw input of {Path(packet_path).name}")
        return sec_store.get_pinned(url, pinned[url], root=store_root)

    ticker = packet._check_ticker(pk["ticker"])
    repo = Path(screener_repo_path) if screener_repo_path is not None else packet.screener_repo()
    rebuilt = packet._core(ticker, packet.parse_T(pk["decision_time_utc"]), pk["screener"]["commit"], repo, packet._Inputs(get),
                           pk["screener"].get("verified_row"))
    new = packet.canonical_bytes(rebuilt)
    identical = new == stored
    diff = None
    if not identical:
        diff = first_diff(pk, rebuilt)
        if diff is None:
            k = next((i for i, (x, y) in enumerate(zip(stored, new)) if x != y), min(len(stored), len(new)))
            diff = {"path": None, "reason": "the stored file is not in canonical byte form", "byte_offset": k}
    return {"identical": identical, "first_diff": diff, "stored_sha256": hashlib.sha256(stored).hexdigest(),
            "rebuilt_sha256": hashlib.sha256(new).hexdigest()}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay every stored m3m packet offline and compare bytes (gate M-P4)")
    ap.add_argument("--dir", default=str(packet.PACKETS_DIR))
    a = ap.parse_args(argv)
    paths = sorted(Path(a.dir).glob("*.json"))
    if not paths:
        print(json.dumps({"error": f"no packets in {a.dir}"}))
        return 1
    ok = True
    for p in paths:
        try:
            res = replay(p)
        except Exception as e:                     # one packet's failure is reported and fails the gate; the others still run
            res = {"identical": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        ok = ok and res["identical"]
        print(json.dumps({"packet": p.name, **res}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

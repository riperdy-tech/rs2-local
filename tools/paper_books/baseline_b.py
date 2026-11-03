"""baseline_b.py - the deterministic baseline B of 3N (SPEC_m3n_event_validation.md section 6.5; PREREG_m3n.json "baseline_B").

The rules are PREREG's regular expressions, matched case-insensitively with DOTALL on each evidence item's text separately; nothing
else is read. A hit is (class, fact_id, accession of the item, the pattern that matched, the matched text up to 200 characters). The
screener row (S0) is never matched. The patterns are read from PREREG_m3n.json, and its sha256 is checked against PREREG_SHA256 so a
changed PREREG cannot be used silently.

    python baseline_b.py <packet.json> [...]      prints one JSON line per packet: {"packet", "packet_sha256", "hits": [...]}
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths  # noqa: E402

PREREG = book_paths.prereg("PREREG_m3n.json")      # a frozen copy in rs2-state (it names tickers); its sha256 is checked below
PREREG_SHA256 = "eafda74379c4c7bf1009fc86ff4a72e768b5f54bc83521e580cd1d227889070c"
_ACC = re.compile(r"(\d{10}-\d{2}-\d{6})")


def rules():
    raw = PREREG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PREREG_SHA256:
        raise SystemExit(f"{PREREG} does not hash to the frozen PREREG sha256")
    b = json.loads(raw)["baseline_B"]
    return {c: [re.compile(p, re.I | re.S) for p in pats] for c, pats in b.items() if re.fullmatch(r"C\d", c)}


def item_accession(e):
    """The SEC accession of an evidence item (its source's `accession`, else read from its URL), or None."""
    src = e.get("source") or {}
    if src.get("accession"):
        return src["accession"]
    m = _ACC.search(src.get("url") or "")
    if m:
        return m.group(1)
    m = re.search(r"/(\d{10})(\d{2})(\d{6})/", src.get("url") or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def hits(packet, compiled=None):
    compiled = compiled or rules()
    out = []
    for e in packet.get("evidence") or []:
        if e.get("kind") == "screener_row":
            continue
        text = e.get("text") or ""
        for cls, pats in compiled.items():
            for p in pats:
                m = p.search(text)
                if m:
                    out.append({"class": cls, "fact_id": e["fact_id"], "accession": item_accession(e), "pattern": p.pattern,
                                "match": m.group(0)[:200]})
                    break                               # one hit per (class, item) is enough
    return out


def main(argv):
    compiled = rules()
    for path in argv:
        raw = Path(path).read_bytes()
        pk = json.loads(raw)
        print(json.dumps({"packet": str(path), "packet_sha256": hashlib.sha256(raw).hexdigest(), "hits": hits(pk, compiled)},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

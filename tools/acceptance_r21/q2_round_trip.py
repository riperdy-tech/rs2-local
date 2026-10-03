"""Revision 21, Q2: the round trip of the PRIMARY SOURCES. Offline, no model, no network.

For every item of a built pack, every sentence of at least 40 characters (and every table row of that length) is cited as `PRIMARY P#` and as the item's URL, and
the crux check's own classification (crux_check.classify_citations, the one owner) must say the citation is company evidence (`pack_company`) whose quote is found:
100% of them. A failure is a defect of the normalisation (crux_check.normalise), never of the test.

  python q2_round_trip.py --packs <dir of packs, one <NAME>.md each>        counts only; a failure prints the item id and the start of the quote

`round_trip(pack_text)` returns (citations tried, failures) for one pack.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "tools" / "audit_202608"))

MIN_LEN = 40


def sentences(text, min_len=MIN_LEN):
    """The sentences of an item's text (its lines joined, split after . ! ?) and its lines, each of at least `min_len` characters."""
    flat = re.sub(r"\s+", " ", text)
    out = [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if len(s.strip()) >= min_len]
    return out + [l for l in text.split("\n") if len(l) >= min_len]


def round_trip(pack_text):
    """(n, failures): n citations tried over every item of the pack; failures [(item id, source form, start of the quote)]."""
    import crux_check
    items = crux_check.primary_items(pack_text)
    sources = crux_check.pack_sources(pack_text)
    n, bad = 0, []
    for it in items:
        for q in sentences(it["text"]):
            for src, form in ((f"PRIMARY {it['id']}", "PRIMARY P#"), (it["url"], "url")):
                n += 1
                rec = crux_check.classify_citations([{"source": src, "date": it["filed"], "quote": q}], sources, {}, None, None, items)[0]
                if not (rec["class"] == "pack_company" and rec["quote_found"] is True):
                    bad.append((it["id"], form, q[:60]))
    return n, bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    a = ap.parse_args(argv)
    packs = sorted(Path(a.packs).glob("*.md"))
    tried = failed = packs_with_items = items_n = 0
    import crux_check
    for p in packs:
        text = p.read_text(encoding="utf-8")
        k = len(crux_check.primary_items(text))
        items_n += k
        packs_with_items += 1 if k else 0
        n, bad = round_trip(text)
        tried += n
        failed += len(bad)
        for b in bad[:5]:
            print(f"FAIL {b[0]} {b[1]}: {b[2]!r}")
    ok = failed == 0 and tried > 0
    print(f"{'PASS' if ok else 'FAIL'}  Q2 round trip: {tried} citations over {items_n} items of {packs_with_items} of {len(packs)} packs; {failed} not found")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

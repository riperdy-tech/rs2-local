"""Round 2's re-check of the Addendum E 5 extraction (Addendum H8): `documents.py`'s Item 1 / Item 7 extraction on the SAME (name, date) pairs as round 1's check,
read from round 1's `muse_checks_summary.json`, against the same cached annual reports.  No network: a report that round 1 did not fetch is recorded as such.

    python -m rebuild_harness.gate1_extraction_recheck MUSE_CHECKS_DIR --out-dir OUT

For each pair it runs the production path (`AcceptanceBoundedDocuments.items`: the cached submissions with their acceptance timestamps, the 16:00 ET rule, the latest
annual report accepted before the date, `item_span` on its text) with the round-1 cache as the annual-report source, and writes round 1's result beside round 2's.
Descriptive only; the flags are `gate1_muse_checks.extraction_flags`.
"""
import argparse
import gzip
import json
from pathlib import Path

from valuation.muse import documents as docs
from .gate1_muse_checks import LIVE_SUBS, extraction_flags


def _cached_annual(cache_dir):
    cache_dir = Path(cache_dir)

    def fetch(cik, accession):
        p = cache_dir / f"{str(cik).zfill(10)}_{accession}.annual.json.gz"
        if not p.exists():
            return None
        return json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))["raw"]
    return fetch


def recheck(muse_dir):
    muse_dir = Path(muse_dir)
    summ = json.loads((muse_dir / "muse_checks_summary.json").read_text(encoding="utf-8"))
    src = docs.AcceptanceBoundedDocuments(LIVE_SUBS, fetch_8k=lambda c, a: None, fetch_periodic=lambda c, a: None, fetch_annual=_cached_annual(muse_dir / "sec_annual_cache"))
    rows = []
    for r in summ["extraction"]:
        e = r.get("extraction") or {}
        items, notes = src.items(r["cik"], r["date"])
        by = {i.kind: i for i in items}
        row = {"ticker": r["ticker"], "cik": r["cik"], "date": r["date"], "family": r["family"], "notes": [n for n in notes if "annual" in n or "business" in n or "management" in n]}
        for kind, label in (("annual_business", "item_1_business"), ("annual_mdna_outlook", "item_7_mdna")):
            old = e.get(label) or {}
            it = by.get(kind)
            row[label] = {"round1_found": bool(old.get("found")), "round1_chars": old.get("chars"), "round2_found": it is not None,
                          "round2_chars": None if it is None else len(it.text), "round2_flags": [] if it is None else extraction_flags(it.text, kind),
                          "accession": None if it is None else it.accession, "head": None if it is None else it.text[:160]}
        rows.append(row)
    return rows


def summarize(rows):
    out = {"pairs": len(rows)}
    for label in ("item_1_business", "item_7_mdna"):
        out[label] = {"round1_found": sum(1 for r in rows if r[label]["round1_found"]), "round2_found": sum(1 for r in rows if r[label]["round2_found"]),
                      "newly_found": sum(1 for r in rows if r[label]["round2_found"] and not r[label]["round1_found"]),
                      "lost": sum(1 for r in rows if r[label]["round1_found"] and not r[label]["round2_found"]),
                      "changed_length": sum(1 for r in rows if r[label]["round1_found"] and r[label]["round2_found"] and r[label]["round1_chars"] != r[label]["round2_chars"])}
    out["still_missing"] = [(r["ticker"], r["date"], lab, "; ".join(r["notes"])[:120]) for r in rows for lab in ("item_1_business", "item_7_mdna") if not r[lab]["round2_found"]]
    return out


def render(rows, summ):
    L = ["# Extraction re-check (Addendum H8): Item 1 and Item 7 on round 1's 40 (name, date) pairs", "",
         f"pairs: {summ['pairs']}", ""]
    for label in ("item_1_business", "item_7_mdna"):
        s = summ[label]
        L.append(f"- {label}: found in round 1 {s['round1_found']} of {summ['pairs']}, round 2 {s['round2_found']}; newly found {s['newly_found']}; lost {s['lost']}; "
                 f"found in both with a different length {s['changed_length']}")
    L += ["", "| date | ticker | family | Item 1 round 1 -> round 2 (chars) [flags] | Item 7 round 1 -> round 2 (chars) [flags] | notes |", "|---|---|---|---|---|---|"]
    for r in rows:
        def c(label):
            x = r[label]
            a = x["round1_chars"] if x["round1_found"] else "NOT FOUND"
            b = x["round2_chars"] if x["round2_found"] else "NOT FOUND"
            return f"{a} -> {b} {x['round2_flags'] if x['round2_flags'] else ''}"
        L.append(f"| {r['date']} | {r['ticker']} | {r['family']} | {c('item_1_business')} | {c('item_7_mdna')} | {'; '.join(r['notes'])[:100]} |")
    L += ["", "Still missing after the fix:"] + [f"- {t} {d} {lab}: {n}" for t, d, lab, n in summ["still_missing"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("muse_dir", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    rows = recheck(a.muse_dir)
    summ = summarize(rows)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "extraction_recheck.json").write_text(json.dumps({"summary": summ, "rows": rows}, indent=1), encoding="utf-8")
    (a.out_dir / "extraction_recheck.md").write_text(render(rows, summ), encoding="utf-8")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()

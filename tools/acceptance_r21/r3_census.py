"""Revision 21, R3: the refusal census. Offline, no model, no network, nothing written outside the paths given.

Applies the R2 rules (sec_primary.refuse_search) to every `search_web` query of AT10b's stage 1 (the `sample1_research` and `sample2_research` snapshots of
each name's consensus run), against the PRIMARY SOURCES of the pack built for that name under revision 21 (a pack file `<TICKER>.md` in --packs, as
build_day.py --dump-dir writes them). The census is reported, not a bar: the coordinator reads the lists, and an over-refusal of a genuinely new
angle is a rule defect, fixed by a rule stated in words, never per query.

  python r3_census.py --consensus-dir <gpu_r19/tree/ab_reports/consensus> --packs <dir> --private <lists_private.json> --public <counts.json>

--private holds tickers and every refused and every allowed query (name it with `_private`); --public holds counts only, the names as n1, n2, ... Existing
files are never overwritten.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "tools" / "audit_202608"))
sys.path.insert(0, str(HERE.parent / "acceptance_r18"))


def stage1_queries(consensus_dir):
    """{ticker: [{"sample": n, "query": str, "dedup": bool}]}: the search_web calls of `<TICKER>_*/sample{1,2}_research/_research_snapshot.json`, in call
    order. A directory with more than one run of a name is an error (a census over two runs would count a query twice)."""
    out, seen = {}, {}
    for d in sorted(Path(consensus_dir).iterdir()):
        if not d.is_dir():
            continue
        t = d.name.split("_", 1)[0]
        if t in seen:
            raise SystemExit(f"two runs of one name in {consensus_dir}: {seen[t]} and {d.name}")
        seen[t] = d.name
        for n in (1, 2):
            f = d / f"sample{n}_research" / "_research_snapshot.json"
            if not f.exists():
                continue
            calls = json.loads(f.read_text(encoding="utf-8")).get("calls") or []
            for c in calls:
                if isinstance(c, dict) and c.get("tool") == "search_web" and isinstance(c.get("query"), str) and c["query"].strip():
                    out.setdefault(t, []).append({"sample": n, "query": c["query"], "dedup": bool(c.get("dedup") or c.get("deduplicated_from"))})
    return out


def _flags(query, items, ticker):
    """What a query that is allowed holds, for the reader of the allowed list: whether it names a document word, a period, or a figure token no
    item prints."""
    import sec_primary as sp
    return {"document_word": any(rx.search(query) for rx, _ in sp._DOC_RES), "period": bool(sp.query_periods(query)),
            "figure_not_in_items": [t for t in sp.figure_tokens(query, ticker)]}


def census(queries, packs_dir):
    """(private, public): the lists and the counts. `queries` is `stage1_queries`'s; each name's items are parsed from its pack file."""
    import sec_primary as sp
    private = {"names": {}, "totals": {}}
    pub = {"queries": 0, "refused": 0, "allowed": 0, "by_rule": {"figure": 0, "document": 0, "figure+document": 0}, "unique_queries": 0,
           "names": {}, "names_without_primary_items": 0}
    uniq = set()
    for k, t in enumerate(sorted(queries), 1):
        p = Path(packs_dir) / f"{t}.md"
        items = sp.parse_pack(p.read_text(encoding="utf-8")) if p.exists() else []
        refused, allowed = [], []
        for q in queries[t]:
            got = sp.refuse_search(q["query"], items, t)
            if got is None:
                allowed.append(dict(q, **_flags(q["query"], items, t)))
            else:
                res, rule = got
                refused.append(dict(q, rule=rule, items=res["served_from_primary"],
                                    figure_tokens=[x for x in sp.figure_tokens(q["query"], t) if any(x in sp.item_figures(i["text"]) for i in items)]))
            uniq.add((t, q["query"]))
        private["names"][t] = {"pack_found": p.exists(), "items": [{"id": i["id"], "type": i["type"], "chars": len(i["text"])} for i in items],
                               "refused": refused, "allowed": allowed}
        label = f"n{k}"
        by = {"figure": 0, "document": 0, "figure+document": 0}
        for r in refused:
            by[r["rule"]] += 1
            pub["by_rule"][r["rule"]] += 1
        pub["names"][label] = {"queries": len(queries[t]), "refused": len(refused), "by_rule": by, "primary_items": len(items)}
        pub["names_without_primary_items"] += 0 if items else 1
        pub["queries"] += len(queries[t])
        pub["refused"] += len(refused)
        pub["allowed"] += len(allowed)
    pub["unique_queries"] = len(uniq)
    private["totals"] = {k: v for k, v in pub.items() if k != "names"}
    return private, pub


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus-dir", required=True)
    ap.add_argument("--packs", required=True)
    ap.add_argument("--private", required=True)
    ap.add_argument("--public", required=True)
    a = ap.parse_args(argv)
    if "_private" not in Path(a.private).name:
        sys.exit("the lists hold tickers: the file name must carry `_private`")
    private, pub = census(stage1_queries(a.consensus_dir), a.packs)
    for path, doc in ((a.private, private), (a.public, pub)):
        with open(path, "x", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=1, ensure_ascii=False))
    print(json.dumps(pub, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Revision 21: the SEC prefetch of the PRIMARY SOURCES section, and the census of what it builds (brief_rev21.md, "SEC network" and "Report").

This is the ONE script of revision 21 that reaches the network, and only sec.gov and data.sec.gov, through sec_primary (sec_guidance's User-Agent,
one request at a time, THROTTLE_S after each: under 10 requests per second; each accession fetched once and cached forever). Every other script
builds the pack offline from the cache this one fills.

  python prefetch_sec.py --names FILE --cik-map <screener data dir>/cik_map.json --asof 2026-10-03 --cache-dir DIR --out RESULT_private.json

  --names      one ticker per line ('#' lines and blanks ignored)
  --cik-map    the screener's cik_map.json ({"map": {ticker: cik}})
  --asof       the as-of date of every build (the filings dated after it are not used)
  --cache-dir  the directory the per-accession cache and the submissions copies go to (default: the tree's cache/sec_primary and cache/sec_submissions)
  --out        the per-name result (it holds tickers: name it with `_private`); an existing file is never overwritten

stdout and the census carry counts only: coverage per item type, the size distribution and the failure reasons counted. Never a ticker.
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "tools" / "audit_202608"))
sys.path.insert(0, str(HERE.parent / "acceptance_r18"))

TYPES = ("earnings_release", "other_exhibit", "segment_table", "other_8k")


def normalise_reason(text):
    """A reason or annotation with the dates, accession numbers, file names and counts taken out, so equal causes count together."""
    s = re.sub(r"\b\d{10}-\d{2}-\d{6}\b", "<accession>", str(text))
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", s)
    s = re.sub(r"\b[\w.-]+\.(?:pdf|htm|html|txt|xml)\b", "<file>", s)
    s = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", "<n>", s)
    return re.sub(r"\s+", " ", s).strip()


def census(results):
    """Counts over per-name results [{"items": [{"type", "chars"}], "annotations": [...], "reason": ...}] (no names): the number of names; names
    with at least one item, and with none; per item type the names that hold one and the character sizes; the distribution of the section's total
    characters; the failure reasons (a name with no item) and the annotations counted by cause."""
    def dist(xs):
        xs = sorted(xs)
        if not xs:
            return None
        q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
        return {"n": len(xs), "min": xs[0], "p25": q(0.25), "median": statistics.median(xs), "p75": q(0.75), "p90": q(0.90), "max": xs[-1],
                "mean": round(statistics.mean(xs), 1)}
    out = {"names": len(results), "with_items": 0, "without_items": 0, "by_type": {t: {"names": 0, "chars": []} for t in TYPES},
           "total_chars": [], "item_counts": {}, "reasons": {}, "annotations": {}}
    for r in results:
        its = r.get("items") or []
        if its:
            out["with_items"] += 1
            out["total_chars"].append(sum(i["chars"] for i in its))
        else:
            out["without_items"] += 1
            k = normalise_reason(r.get("reason") or "no reason recorded")
            out["reasons"][k] = out["reasons"].get(k, 0) + 1
        out["item_counts"][str(len(its))] = out["item_counts"].get(str(len(its)), 0) + 1
        for t in TYPES:
            of = [i for i in its if i["type"] == t]
            if of:
                out["by_type"][t]["names"] += 1
                out["by_type"][t]["chars"] += [i["chars"] for i in of]
        for a in r.get("annotations") or []:
            k = normalise_reason(a)
            out["annotations"][k] = out["annotations"].get(k, 0) + 1
    out["by_type"] = {t: {"names": v["names"], "share": round(v["names"] / len(results), 4) if results else None, "chars": dist(v["chars"])}
                      for t, v in out["by_type"].items()}
    out["total_chars"] = dist(out["total_chars"])
    return out


def run(names, cik_map, asof, cache_dir=None, log=print):
    """Builds the section of every name (online: the cache fills) and returns [{"ticker", "cik", "items": [{"id", "type", "form", "filed", "period",
    "chars"}], "annotations", "reason"}]. A ticker with no CIK is a result with the reason `no CIK`."""
    import sec_guidance
    import sec_primary
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        sec_primary.CACHE = cache_dir / "sec_primary"
        sec_guidance.SUB_CACHE = cache_dir / "sec_submissions"
    out = []
    t0 = time.time()
    for n, t in enumerate(names, 1):
        raw = cik_map.get(t) or cik_map.get(t.upper())
        cik = str(raw).zfill(10) if raw else None
        res = sec_primary.build(cik, asof=asof)
        out.append({"ticker": t, "cik": cik, "reason": res["reason"], "annotations": res["annotations"],
                    "items": [{"id": i["id"], "type": i["type"], "form": i["form"], "filed": i["filed"], "period": i["period"],
                               "chars": len(i["text"])} for i in res["items"]]})
        if n % 25 == 0:
            log(f"  {n}/{len(names)} names, {time.time() - t0:.0f}s")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", required=True)
    ap.add_argument("--cik-map", required=True)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--cache-dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if "_private" not in Path(a.out).name:
        sys.exit("the per-name result holds tickers: its file name must carry `_private`")
    import accept_common
    names = accept_common.load_names(a.names)
    cm = json.loads(Path(a.cik_map).read_text(encoding="utf-8"))
    cm = cm.get("map") if isinstance(cm.get("map"), dict) else cm
    res = run(names, cm, a.asof, a.cache_dir)
    accept_common.write_result(a.out, {"asof": a.asof, "results": res})
    c = census(res)
    print(json.dumps(c, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

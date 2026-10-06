"""Why `documents.item_span` found no Item 1 / Item 7 (or Item 4 / Item 5 of a 20-F) in some real annual reports: reads the muse checks' summary and the annual-report text
the run fetched, and classifies each miss.  Descriptive only; nothing here changes the extraction.

    python -m rebuild_harness.gate1_extraction_diagnosis MUSE_CHECKS_DIR [--out file.txt]

Classes: no filing listed in the cached submissions before T (the document source cannot see the report); report listed but its text not fetched; the heading exists only
as a TABLE ROW (the selector reads paragraph blocks only); a paragraph heading matched but the span is empty; the heading text sits inside a longer paragraph; no
heading at all in the fetched text (cut at the raw limit, or another layout).
"""
import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path

import sec_primary as sp
from valuation.muse import documents as docs
from .gate1_muse_checks import LIVE_SUBS

PATTERNS = (("item_1_business", r"item\s*(1|4)\b[\s\.\:\-–—]*(description of )?(the )?(business|information on)"),
            ("item_7_mdna", r"item\s*(7|5)\b[\s\.\:\-–—]*(management|operating and financial)"))


def diagnose(muse_dir):
    muse_dir = Path(muse_dir)
    s = json.loads((muse_dir / "muse_checks_summary.json").read_text(encoding="utf-8"))
    cat, detail, total = collections.Counter(), [], collections.Counter()
    for r in s["extraction"]:
        e = r.get("extraction")
        if not e:
            continue
        for lab, pat in PATTERNS:
            total[lab] += 1
            if e[lab].get("found"):
                continue
            cik, d = r["cik"], r["date"]
            anns = sorted([x for x in docs.read_submissions(LIVE_SUBS, cik) if x["form"] in docs.ANNUAL_ORIGINAL and x["filed"] < d], key=lambda x: x["filed"])
            if not anns:
                cat[(lab, "no annual report listed in the cached submissions before T")] += 1
                detail.append((r["ticker"], d, lab, "no_filing_listed"))
                continue
            ann = anns[-1]
            f = list((muse_dir / "sec_annual_cache").glob(f"{cik}_{ann['accession']}.annual.json.gz"))
            if not f:
                cat[(lab, "annual report listed, text not fetched")] += 1
                detail.append((r["ticker"], d, lab, "not_fetched"))
                continue
            raw = json.loads(gzip.decompress(f[0].read_bytes()).decode())["raw"]
            blocks = sp.blocks_of(raw)
            hp = [c[:70] for k, c in blocks if k == "p" and len(c) <= 220 and re.match(r"^\s*" + pat, c, re.I)]
            ht = [row[:70] for k, c in blocks if k == "t" for row in c if len(row) <= 220 and re.match(r"^\s*" + pat, row.replace(" | ", " "), re.I)]
            anywhere = [c[:70] for k, c in blocks if k == "p" and re.search(pat, c[:300], re.I)]
            if ht and not hp:
                key = "heading present only as a TABLE ROW (item_span reads paragraph blocks only)"
            elif hp:
                key = "paragraph heading matched but the span is empty"
            elif anywhere:
                key = "heading text inside a longer paragraph, not a short heading block"
            else:
                key = "no heading found in the fetched text (cut at the raw limit, or another layout)"
            cat[(lab, key)] += 1
            detail.append((r["ticker"], d, lab, key[:44], len(raw), (ht or hp or anywhere or [""])[0]))
    return total, cat, detail


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("muse_dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    total, cat, detail = diagnose(a.muse_dir)
    lines = [f"{lab}: {n} (name, date) pairs checked" for lab, n in sorted(total.items())] + [f"{v}  {k[0]}: {k[1]}" for k, v in sorted(cat.items())] + [str(d) for d in detail]
    text = "\n".join(lines) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()

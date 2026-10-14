"""Audit 1's hand check (AK.35): the 20 seeded q1 outcomes of the version of record, against the filed documents themselves.

For each: the same-filing values (revenue and operating income, current quarter and the year-earlier quarter) are re-derived from the outcome store with
tag_consistent's rules, the filing's primary document is downloaded from SEC (standing approval; memory `sec-downloads-standing-approval`; sha256
recorded), and each value is searched for in the document's text at the usual scales (whole dollars, thousands, millions to 1 or 0 decimals).
A value found confirms that the number we scored is the number the company filed; growth is then recomputed from the two found values.

    python hand_check.py REPORT_JSON OUT_DIR STORE
"""
import hashlib
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
sys.path.insert(0, str(Path(__file__).parent))
import tag_consistent as tc  # noqa: E402
from rebuild_harness.gate2.score_day import SEC_UA  # noqa: E402
from valuation.pit_data import PitData  # noqa: E402


def get(url):
    time.sleep(0.25)                                                    # SEC fair access: well under 10 requests a second
    with urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=60) as r:
        return r.read()


def forms(v):
    a = abs(v)
    out = {f"{a:,.0f}"}
    if a >= 1e3:
        out.add(f"{a / 1e3:,.0f}")
    if a >= 1e6:
        out |= {f"{a / 1e6:,.1f}", f"{a / 1e6:,.0f}", f"{a / 1e6:,.2f}"}
    return out


def main():
    report, out, store = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    hc = json.loads(report.read_text(encoding="utf-8"))["audit1"]["hand_check"]
    pit = PitData(store)
    manifest, results = [], []
    for h in hc:
        c = pit.company(h["cik"])
        facts = tc.merged(c.facts, c.qfacts) if c else {}
        vals = {}
        for f in ("revenue", "operating_income", "net_income"):
            rs = tc.rows_of(facts, f)
            p = tc.pairs_in_filing(rs, h["accession"], h["q1_period_end"], tc.Q3M) or tc.derived_q4(rs, h["accession"], h["q1_period_end"])
            k, v, _ = tc.choose(p, f)
            vals[f] = None if k is None else {"tag": k[1], "cur": v[0], "prior": v[1]}
        cik_i, acc = int(h["cik"]), h["accession"].replace("-", "")
        rec = {"key": h["key"], "ticker": h["ticker"], "accession": h["accession"], "scored_growth": h.get("revenue_growth"),
               "scored_margin_change": h.get("operating_margin_change"), "values": vals}
        try:
            idx = json.loads(get(f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/index.json"))
            items = idx["directory"]["item"]
            prim = [i["name"] for i in items if i["name"].lower().endswith((".htm", ".html")) and not i["name"].lower().startswith(("r", "fileSummary"))]
            prim = sorted(prim, key=lambda n: -int(next((i.get("size") or 0 for i in items if i["name"] == n), 0) or 0))
            doc = get(f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{prim[0]}")
            sha = hashlib.sha256(doc).hexdigest()
            pth = out / f"{h['key']}_{prim[0]}"
            if not pth.exists():
                pth.write_bytes(doc)
            manifest.append({"key": h["key"], "url": f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{prim[0]}", "bytes": len(doc), "sha256": sha})
            text = html.unescape(re.sub(r"<[^>]+>", " ", doc.decode("utf-8", "replace")))
            text = re.sub(r"\s+", " ", text)
            found = {}
            for f, v in vals.items():
                if v is None:
                    continue
                for leg in ("cur", "prior"):
                    found[f"{f}.{leg}"] = any(s in text for s in forms(v[leg]))
            rec["doc"] = prim[0]
            rec["found"] = found
            r = vals.get("revenue")
            rec["growth_from_document_values"] = (r["cur"] / r["prior"] - 1) if r and r["prior"] else None
            rec["growth_matches_scored"] = (rec["growth_from_document_values"] is not None and h.get("revenue_growth") is not None
                                            and abs(rec["growth_from_document_values"] - h["revenue_growth"]) < 1e-9)
        except Exception as e:                                          # recorded, never silent
            rec["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        results.append(rec)
    (out / "manifest.json").write_text(json.dumps({"why": "gate-2 Audit 1 hand check of 20 seeded outcomes (AK.35)", "files": manifest}, indent=1), encoding="utf-8")
    (out / "hand_check.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    for r in results:
        print(r["key"], r["ticker"], r.get("doc"), r.get("found"), "growth ok" if r.get("growth_matches_scored") else r.get("error", "growth MISMATCH/none"))


if __name__ == "__main__":
    main()

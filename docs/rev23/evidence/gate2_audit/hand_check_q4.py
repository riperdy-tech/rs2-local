"""Hand check of derived-Q4 outcomes (AK.36): both legs against the filed documents.  The fiscal-year pair in the 10-K text, the nine-month pair in the
third-quarter 10-Q text (downloaded, sha256 recorded).   python hand_check_q4.py OUT_DIR STORE KEY:FIELD ..."""
import hashlib
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import hand_check as hc  # noqa: E402
import tag_consistent as tc  # noqa: E402
from valuation.pit_data import PitData  # noqa: E402

out, store = Path(sys.argv[1]), Path(sys.argv[2])
pit = PitData(store)
rep = json.loads((Path(__file__).parent / "tag_consistent/2026-10-06_v2/scored/report.json").read_text(encoding="utf-8"))
hcl = {h["key"]: h for h in rep["audit1"]["hand_check"]}
man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
res = []


def text_of(cik_i, accn):
    acc = accn.replace("-", "")
    idx = json.loads(hc.get(f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/index.json"))["directory"]["item"]
    prim = sorted((i for i in idx if i["name"].lower().endswith((".htm", ".html")) and not i["name"].lower().startswith("r")),
                  key=lambda i: -int(i.get("size") or 0))[0]["name"]
    doc = hc.get(f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{prim}")
    p = out / f"q4leg_{accn}_{prim}"
    if not p.exists():
        p.write_bytes(doc)
    man["files"].append({"key": f"q4 leg {accn}", "url": f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{prim}", "bytes": len(doc),
                         "sha256": hashlib.sha256(doc).hexdigest()})
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", doc.decode("utf-8", "replace"))))


for arg in sys.argv[3:]:
    key, field = arg.split(":")
    h = hcl[key]
    c = pit.company(h["cik"])
    rows = tc.rows_of(tc.merged(c.facts, c.qfacts), field)
    fy = tc.pairs_in_filing(rows, h["accession"], h["q1_period_end"], tc.QFY)
    k, (fc, fp), _ = tc.choose(fy, field)
    end9 = next(r["end"] for r in rows if r["form"].startswith("10-Q") and tc._cls(r, tc.Q9M) and 80 <= tc._days(r["end"], h["q1_period_end"]) <= 100)
    acc9 = sorted({r["accn"] for r in rows if r["end"] == end9 and tc._cls(r, tc.Q9M) and r["form"].startswith("10-Q")
                   and (r["taxo"], r["tag"], r["unit"]) == k})[0]
    nc, np_ = tc.pairs_in_filing(rows, acc9, end9, tc.Q9M)[k]
    t10k = text_of(int(h["cik"]), h["accession"])
    t10q = text_of(int(h["cik"]), acc9)
    f = {"fy.cur": any(s in t10k for s in hc.forms(fc)), "fy.prior": any(s in t10k for s in hc.forms(fp)),
         "9m.cur": any(s in t10q for s in hc.forms(nc)), "9m.prior": any(s in t10q for s in hc.forms(np_))}
    q4c, q4p = fc - nc, fp - np_
    res.append({"key": key, "field": field, "tag": k[1], "fy": [fc, fp], "nine_months": [nc, np_], "q4": [q4c, q4p], "q3_10q": acc9, "found": f,
                "q4_growth": (q4c / q4p - 1) if field == "revenue" and q4p else None, "scored_growth": h.get("revenue_growth")})
    print(key, field, f, "q4", q4c, q4p, "growth", res[-1]["q4_growth"], "scored", h.get("revenue_growth"))
(out / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
(out / "hand_check_q4.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

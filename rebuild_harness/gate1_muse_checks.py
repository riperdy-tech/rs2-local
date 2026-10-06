"""The Muse-side checks of the T-integrate brief (no GPU, no model, no server):

  (1) the LEAKAGE AUDIT (`valuation/muse/leakage_audit.py`) on pack v2 for 20 names at each of two development dates, with the shared layer's quarterly source
      (`PitQuarterSource`, Addendum G 12) and real documents; and
  (2) the Addendum E 5 EXTRACTION CHECK: `documents.py`'s Item 1 (business) and Item 7 (MD&A) extraction on real annual reports, for at least 20 names across the
      three built families.

    python -m rebuild_harness.gate1_muse_checks --run-dir RUN --out-dir OUT [--dates 2019-12-31 2022-06-30] [--per-family 8 6 6] [--no-network]

NETWORK: none except SEC filings through the repository's own helpers (`sec_primary`: sec.gov and data.sec.gov only, the repository's User-Agent, 0.15 s after
every request, each accession cached).  The annual reports, the earnings-release exhibits and the segment pages that a name's section D needs are the only things
fetched.  `--no-network` runs on what the caches already hold and records what could not be read.  The names are the ones whose SEC submissions are already cached
by the live tree (read only): they list each filing with its acceptance timestamp, so the 16:00 ET rule runs on real timestamps for these names.

IDENTITY.  The company name as of T comes from the submissions' former-name history (stamped `as_of_T` only when the history covers T); the ticker and the Damodaran
industry are today's records and are stamped `current_record`: the audit flags them (no header history exists in this build, so identity as of T cannot be
certified).  That is a finding of the audit, not something to repair here.

THE PACKS. Pass-1 requests (P1-P4) are rendered from the real pack and saved in the run-directory format the audit reads; P5 and P6 need a model's answers and are
not rendered here (the mock-model run of the muse tests covers their wording).  The price is never passed to the pack builder.
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from valuation import classification as cls_mod
from valuation import pit_adapter
from valuation import pit_data as pdm
from valuation.common import build_state
from valuation.muse import documents as docs
from valuation.muse import leakage_audit as la
from valuation.muse import pack_v2, prompting
from valuation.muse.runner import MuseRunner
from valuation.muse.schema import BUILT_FAMILIES, PASS1_PROMPTS
from valuation.priors import PopulationPriors

STOCKS = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks"))
LIVE_SUBS = STOCKS / "rs2-local" / "cache" / "sec_submissions"
WORKSPACE = STOCKS / "stocks-workspace"
SMOKE = WORKSPACE / "scratch" / "rev23" / "harness_smoke"
INPUTS = WORKSPACE / "data" / "priors" / "_inputs"


def name_asof(subs: dict, asof) -> tuple:
    """(name, source): the company name in force at `asof` from the submissions' former-name history; the current name when T is after the latest change."""
    asof_d = pdm.to_date(asof)
    cur = subs.get("name")
    best = None
    for fn in subs.get("formerNames") or []:
        f, t = str(fn.get("from") or "")[:10], str(fn.get("to") or "")[:10]
        if f and t and f <= asof_d.isoformat() <= t:
            best = fn.get("name")
    if best is not None:
        return best, "as_of_T"
    last_to = max([str(fn.get("to") or "")[:10] for fn in subs.get("formerNames") or []] or [""])
    if last_to and last_to < asof_d.isoformat():
        return cur, "as_of_T"
    if not (subs.get("formerNames") or []):
        return cur, "as_of_T"            # no name change on record: the current name is the name at T
    return cur, "current_record"


def candidates(run_dir, d):
    """[(cik, ticker, family)] of the run's records on date `d` with a built family and cached submissions, ordered by cik."""
    out = []
    with gzip.open(Path(run_dir) / f"records_{d}.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("family") in BUILT_FAMILIES and r.get("ticker") and (LIVE_SUBS / f"CIK{r['cik']}.json").exists() and not any(
                    x.startswith("no_annual_report") for x in r.get("reasons", [])):
                out.append((r["cik"], r["ticker"], r["family"], r["status"]))
    return sorted(out)


def select(run_dir, d, per_family):
    cands = candidates(run_dir, d)
    want = dict(zip(("operating", "financial", "commodity"), per_family))
    chosen, count = [], Counter()
    for cik, tk, fam, status in sorted(cands, key=lambda x: (x[3] != "valued", x[0])):      # prefer names the engines valued
        if count[fam] < want[fam]:
            chosen.append((cik, tk, fam, status))
            count[fam] += 1
    return sorted(chosen)


def extraction_row(items, notes):
    by = {i.kind: i for i in items}
    row = {"notes": [n for n in notes]}
    for kind, label in (("annual_business", "item_1_business"), ("annual_mdna_outlook", "item_7_mdna")):
        it = by.get(kind)
        if it is None:
            row[label] = {"found": False}
            continue
        t = it.text
        row[label] = {"found": True, "chars": len(t), "accession": it.accession, "filed": it.filed, "accepted_at": it.accepted_at, "head": t[:240], "tail": t[-200:],
                      "form": it.form, "flags": extraction_flags(t, kind)}
    return row


_HEADFRAG = re.compile(r"^[A-Z][A-Z0-9 ,&'\-]{2,60}\s+[A-Z][a-z]")
_NEXT_ITEM = re.compile(r"\bItem\s+(?:1A|1B|2|3|7A|8)\b", re.I)


def extraction_flags(text: str, kind: str) -> list:
    """Mechanical, descriptive flags for the coordinator's reading (nothing here gates): short text, a table-of-contents marker, a head that looks like the tail of a
    wrapped heading, the next Item's heading inside the last 400 characters (an overrun), omission markers."""
    f = []
    if len(text) < (1500 if kind == "annual_business" else 1000):
        f.append("short")
    if re.search(r"table of contents", text[:600], re.I):
        f.append("table_of_contents_marker_in_head")
    if _HEADFRAG.match(text.strip()):
        f.append("head_looks_like_a_wrapped_heading_fragment")
    if _NEXT_ITEM.search(text[-400:]):
        f.append("next_item_heading_in_tail")
    n = text.count("characters omitted")
    if n:
        f.append(f"omission_markers:{n}")
    return f


def run(run_dir, out_dir, dates, per_family, network):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    idm = json.loads((SMOKE / "sample_id_map.json").read_text(encoding="utf-8"))
    sic = pit_adapter.CurrentSicFile(INPUTS / "sic_by_cik.json")
    pit = pdm.PitData(SMOKE / "store_all", id_map=idm, sic_source=sic, acceptance_source=pdm.SubmissionsAcceptance(LIVE_SUBS))
    priors = PopulationPriors()
    quarters = docs.layer_quarters(pit)
    sec_cache = out_dir / "sec_annual_cache"
    if network:
        import sec_primary as sp
        sp.CACHE = out_dir / "sec_primary_cache"          # the fetchers' own cache, inside this run's folder
    fetch_note = "network: SEC filings through sec_primary" if network else "no network: caches only"
    doc_src = docs.AcceptanceBoundedDocuments(LIVE_SUBS, annual_cache_dir=sec_cache, **({} if network else {
        "fetch_8k": lambda cik, accn: None, "fetch_periodic": lambda cik, accn: None,
        "fetch_annual": (lambda c, a, base=docs.default_fetch_annual(sec_cache): None)}))
    summary = {"fetch": fetch_note, "dates": {}, "extraction": []}
    t0 = time.time()
    for d in dates:
        names = select(run_dir, d, per_family)
        summary["dates"][d] = {"names": [(c, t, f, s) for c, t, f, s in names]}
        for cik, tk, fam, status in names:
            rd = out_dir / "audit_runs" / f"{tk}_{d}"
            row = {"cik": cik, "ticker": tk, "date": d, "family": fam, "engine_status": status}
            try:
                ad = pit_adapter.adapt(pit, cik, d, ticker=tk)
                row["adapter_refusals"] = ad.refusals
                if not ad.ok:
                    summary["extraction"].append(row)
                    continue
                pc = ad.company
                st = build_state(pc)
                cl = cls_mod.classification(tk, d, pc)
                family = cl["family"]
                row["family_at_T"] = family
                if family not in BUILT_FAMILIES:
                    row["skipped"] = f"family {family}"
                    summary["extraction"].append(row)
                    continue
                subs = json.loads((LIVE_SUBS / f"CIK{cik}.json").read_text(encoding="utf-8"))
                nm, nm_src = name_asof(subs, d)
                identity = {"name": nm, "ticker": tk, "industry": ad.industry, "name_source": nm_src, "ticker_source": "current_record",
                            "industry_source": "current_record"}
                ps = priors.for_company(family, st, pc.asof)
                items, notes = doc_src.items(cik, d)
                row["extraction"] = extraction_row(items, notes)
                pack = pack_v2.build_pack(pc, family, identity, ps, state=st, documents=_Fixed(items, notes), quarters=quarters, cik=cik)
                rd.mkdir(parents=True, exist_ok=True)
                (rd / "pack.json").write_text(json.dumps({"header": pack.header, "sections": pack.sections, "r": pack.r, "manifest": pack.manifest,
                                                          "provenance": pack.provenance}, indent=1, default=str), encoding="utf-8")
                runner = MuseRunner(None, rd)
                runner.write_manifest({"ticker": tk, "asof": d, "family": family, "pack_manifest": pack.manifest})
                for prompt in PASS1_PROMPTS:
                    r1 = prompting.render_pass1(prompt, pack, family)
                    if r1 is None:
                        continue
                    runner.seq += 1
                    runner._save(f"{runner.seq:02d}_{prompt}_a1_request.json", runner._request([{"role": "system", "content": runner.system_message},
                                                                                              {"role": "user", "content": r1.user}]))
                row["pack_sections"] = {k: len(v) for k, v in pack.sections.items()}
                row["quarters_source"] = pack.manifest["quarters"]["source"]
                row["quarters_used"] = len(pack.manifest["quarters"]["used"])
                row["stamps"] = pack.manifest["stamps"]
            except Exception as e:            # a failure is a result, never a crash
                import traceback
                row["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                row["trace"] = traceback.format_exc()[-600:]
            summary["extraction"].append(row)
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", d, tk, fam, row.get("error") or "ok", flush=True)
    rep = la.audit(out_dir / "audit_runs")
    (out_dir / "leakage_audit.md").write_text(la.render_markdown(rep, limit=60), encoding="utf-8")
    (out_dir / "leakage_audit.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    summary["audit"] = {"violations": rep["violations"], "reviews": rep["reviews"], "runs": len(rep["runs"]),
                        "violations_by_kind": dict(Counter(f["kind"] + ":" + f["match"][:40] for r in rep["runs"] for f in r["findings"] if f["severity"] == "violation").most_common(40)),
                        "templates_clean": not rep["templates"]}
    (out_dir / "muse_checks_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (out_dir / "extraction_report.md").write_text(render_extraction(summary), encoding="utf-8")
    return summary


class _Fixed(docs.DocumentSource):
    def __init__(self, items, notes):
        self._i, self._n = items, notes

    def items(self, cik, asof):
        return list(self._i), list(self._n)


def render_extraction(summary):
    rows = [r for r in summary["extraction"] if r.get("extraction")]
    L = ["# Extraction check: Item 1 and Item 7 on real annual reports", "", f"({summary['fetch']})", "",
         "| date | ticker | family | Item 1 chars [flags] | Item 7 chars [flags] | notes |", "|---|---|---|---|---|---|"]
    for r in rows:
        e = r["extraction"]
        L.append(f"| {r['date']} | {r['ticker']} | {r.get('family_at_T')} | {e['item_1_business'].get('chars', 'NOT FOUND')} {e['item_1_business'].get('flags', '')} | {e['item_7_mdna'].get('chars', 'NOT FOUND')} {e['item_7_mdna'].get('flags', '')} | {'; '.join(e['notes'])[:140]} |")
    L += ["", "## Heads and tails (for the coordinator to read)", ""]
    for r in rows:
        for lab in ("item_1_business", "item_7_mdna"):
            x = r["extraction"][lab]
            if x.get("found"):
                L += [f"### {r['ticker']} {r['date']} {lab} ({x['chars']} chars, {x['form']} {x['accession']} filed {x['filed']})", "", "head: " + x["head"].replace("\n", " "), "",
                      "tail: " + x["tail"].replace("\n", " "), ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="+", default=["2019-12-31", "2022-06-30"])
    ap.add_argument("--per-family", nargs=3, type=int, default=[8, 6, 6])
    ap.add_argument("--no-network", action="store_true")
    a = ap.parse_args(argv)
    s = run(a.run_dir, a.out_dir, a.dates, a.per_family, not a.no_network)
    print(json.dumps(s["audit"], indent=1))


if __name__ == "__main__":
    main()

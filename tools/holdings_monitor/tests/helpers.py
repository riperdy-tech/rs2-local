"""Builders shared by the tests: submissions feeds, price series, and fake qwen_c run directories (manifest, analysis, packet with real shas)."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import monitor as M

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
AAA = {"ticker": "AAA", "cik": 1, "company": "Alphatest Corp"}
BBB = {"ticker": "BBB", "cik": 2, "company": "Betatest Inc"}


def feed(cik, rows):
    """A submissions JSON. rows: dicts with accession, form, accepted (ISO), items (str), doc."""
    cols = {"accessionNumber": [], "form": [], "filingDate": [], "acceptanceDateTime": [], "primaryDocument": [], "items": [], "reportDate": []}
    for r in rows:
        cols["accessionNumber"].append(r["accession"])
        cols["form"].append(r["form"])
        cols["filingDate"].append(r["accepted"][:10])
        cols["acceptanceDateTime"].append(r["accepted"])
        cols["primaryDocument"].append(r.get("doc", "x.htm"))
        cols["items"].append(r.get("items", ""))
        cols["reportDate"].append("")
    return {"cik": str(cik).zfill(10), "filings": {"recent": cols}}


def filing(acc, form, accepted, items=""):
    return {"accession": acc, "form": form, "accepted": accepted, "items": items}


QUIET = "ALPHATEST CORP (Exact name of registrant) routine report. Alphatest Corp has nothing unusual to say."


def sources(rows=None, texts=None, prices=None, news=None, cik=1, sub=None):
    """Sources over fixed data. texts: {accession: text}; the default text is quiet and names the issuer."""
    texts = texts or {}
    return M.Sources(submissions=lambda c: sub if sub is not None else feed(cik, rows or []),
                     filing_text=lambda c, acc, doc, form: texts.get(acc, QUIET),
                     prices=prices, news=news)


def closes_series(n, start=100.0, a=0.01, last_r=None, first=date(2026, 1, 1)):
    """n closes: from the second one log returns alternate +a / -a (mean 0, so the sample sd of 60 returns is a*sqrt(60/59)); if last_r is
    given the final close is the previous one times exp(last_r). Returns [{"date", "close"}]."""
    out, c = [], start
    for i in range(n):
        if i:
            c = c * math.exp(a if i % 2 else -a)
        out.append(c)
    if last_r is not None:
        out[-1] = out[-2] * math.exp(last_r)
    return [{"date": (first + timedelta(days=i)).isoformat(), "close": v} for i, v in enumerate(out)]


def price_source(rows):
    return lambda t: {"source": "fixture", "quote_date": rows[-1]["date"], "closes": rows}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_run(base, ticker="AAA", run_no=1, T="2026-10-30T01:00:00Z", status="complete", finished="2026-10-30T02:00:00Z", me_claims=None,
             tc_claims=None, tc_status="ok", prior="PRIOR_RUN", point_ids=("p1", "p2"), tamper=None, evidence=None, built="v6",
             packet_sha=None):
    """A qwen_c-shaped run directory with a valid manifest/analysis/packet. tamper: 'analysis' or 'packet' changes that file afterwards."""
    run_id = f"{ticker}_{run_no}"
    d = Path(base) / run_id
    d.mkdir(parents=True)
    ev = evidence if evidence is not None else [
        {"fact_id": "F1", "kind": "filing", "name": "8-K", "text": "On June 30, 2026 Alphatest Corp received a delisting notice. Item 3.01.",
         "source": {"accession": "0000000001-26-000001"}, "accepted_raw": "2026-06-30T20:00:00.000Z", "effective_at": "2026-06-30T20:00:00Z"},
        {"fact_id": "F2", "kind": "filing", "name": "10-Q", "text": "The quarter ended on 2026-09-30.",
         "source": {"accession": "0000000001-26-000002"}, "accepted_raw": "2026-10-20T20:00:00.000Z", "effective_at": "2026-10-20T20:00:00Z"}]
    packet = {"ticker": ticker, "evidence": ev}
    pb = json.dumps(packet).encode("utf-8")
    tasks = {"material_events": {"status": "ok", "claims": me_claims or [], "unknowns": []}}
    if tc_claims is not None or tc_status != "ok":
        tasks["thesis_change"] = {"status": tc_status, "claims": tc_claims or [], "unknowns": [],
                                  "points_not_addressed": [p for p in point_ids if p not in {c["point"] for c in tc_claims or []}]}
    analysis = {"contract": "m3m.analysis.v2", "run_id": run_id, "ticker": ticker, "tasks": tasks, "status": status}
    ab = json.dumps(analysis).encode("utf-8")
    man = {"contract": "m3m.analysis.v2", "prompt_version": "m3m.prompt.v3", "builder_version": built, "run_id": run_id, "ticker": ticker,
           "decision_time_utc": T, "packet": {"file": "packet.json", "file_sha256": sha(pb), "packet_sha256": packet_sha or sha(b"canon" + pb)},
           "status": status, "prior_run": {"run_id": prior, "decision_time_utc": "2026-09-30T18:00:00Z", "point_ids": list(point_ids)} if prior else None,
           "incomplete_tasks": {} if status == "complete" else {"risks": "malformed"}, "analysis_sha256": sha(ab)}
    if finished:
        man["finished_at"] = finished
    (d / "packet.json").write_bytes(pb)
    (d / "analysis.json").write_bytes(ab)
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    if tamper == "analysis":
        (d / "analysis.json").write_bytes(ab + b" ")
    if tamper == "packet":
        (d / "packet.json").write_bytes(pb + b" ")
    return d


def claim(event_type="delisting_notice", status="occurred", occurred_on="June 30, 2026", support="supported", fact_ids=("F1",)):
    return {"claim": "x", "event_type": event_type, "status": status, "occurred_on": occurred_on, "support": support, "fact_ids": list(fact_ids)}


def tc(point, change_type, support="supported"):
    return {"point": point, "change_type": change_type, "support": support, "claim": "x", "fact_ids": ["F2"]}


def trig(tid, priority, time, kind="sec_filing"):
    return {"id": tid, "kind": kind, "priority": priority, "time": time, "reasons": [], "annotations": []}

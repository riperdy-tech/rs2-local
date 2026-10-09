"""behaviour.py - Muse's BEHAVIOUR in a gate-2 state folder, and the behaviour gate of SPEC_rebuild Addendum AD.4. Never an outcome.

    python -m rebuild_harness.gate2.behaviour <state dir> [--reference <run-1 state dir>] [--json OUT]

WHAT IS READ.  For every company-date, the latest attempt folder (`runs/<date>/<key>/aNN`): the saved responses (`NN_<call>_aK_response.json`), `result.json`'s
call records (`calls`), positions (`pass1`, `final`) and red-team decisions, `job.json`'s integrity facts, and `progress.jsonl`'s statuses.  Nothing here reads an
outcome file, a return or a realised fundamental, and nothing compares a value with the price.

WHAT IS MEASURED (denominators exclude company-dates the engine refused before any model call):
  first-attempt parse     the first attempt's content is one JSON object (a ``` fence tolerated, the checker's own `parse_json`) and was not cut at the length
                          limit, per call type and overall;
  first-attempt checks    the call passed every check without the retry (result.json: ok and not retried);
  final ok                the call passed after at most one retry;
  unanchored inputs       final positions (and pass-1 positions) with status `unanchored`;
  identical to the code   final positions that are unanchored, or at P50 with width `normal` (the code arm's placement);
  P5 success              P5 final ok among companies that ran P5;
  quotes verified         job.json integrity: accepted citations that pass the re-check;
  length cut-offs         attempts with finish_reason `length`;
  reasoning length        characters of `reasoning_content` per first attempt, per (company, call) so a reference run can be paired;
  technical statuses      error, context_overflow, request_rejected, model_unavailable;
  leakage                 `valuation.muse.leakage_audit.audit` violations over the runs folder;
  red team                proposed revisions, toward the price, with a new quote, with a named error (behaviour, G4's inputs).

THE GATE (Addendum AD.4).  PASS needs all three: first-attempt parse >= 90% of calls; unanchored <= 5% of final inputs; P5 success >= 90%.  STOP triggers (any one stops
the run for review): median paired reasoning ratio against the reference < 0.6 for a call type; identical-to-code > 30% of final inputs; quotes verified < 90%;
any leakage violation; any technical status; length cut-offs > 5% of attempts.  A trigger that cannot be evaluated (no reference, no data) is reported as such,
never as passed.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from valuation.muse.checkers import parse_json

TECHNICAL = ("error", "context_overflow", "request_rejected", "model_unavailable")
GATE = {"first_parse_min": 0.90, "unanchored_max": 0.05, "p5_min": 0.90}
STOP = {"reasoning_ratio_min": 0.6, "identical_max": 0.30, "quotes_min": 0.90, "length_cut_max": 0.05}
_RESP = re.compile(r"^(\d+)_(.+)_a(\d+)_response\.json$")


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def latest_attempts(state_dir) -> Dict[str, Path]:
    """{company-date key: its latest attempt folder} under <state>/runs."""
    out: Dict[str, Path] = {}
    runs = Path(state_dir) / "runs"
    if not runs.exists():
        return out
    for key_dir in sorted(p for d in runs.iterdir() if d.is_dir() for p in d.iterdir() if p.is_dir()):
        atts = sorted(a for a in key_dir.iterdir() if a.is_dir() and re.fullmatch(r"a\d+", a.name))
        if atts:
            out[key_dir.name] = atts[-1]
    return out


def statuses(state_dir) -> Dict[str, str]:
    """{key: the status of its latest progress line}."""
    p = Path(state_dir) / "progress.jsonl"
    out: Dict[str, str] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[r["key"]] = r.get("status")
    return out


def call_attempts(run_dir: Path) -> List[dict]:
    """[{call, attempt, content, reasoning_chars, finish}] for every saved response, in file order."""
    out = []
    for f in sorted(run_dir.glob("*_response.json")):
        m = _RESP.match(f.name)
        if not m:
            continue
        r = _load(f)
        try:
            ch = r["choices"][0]
            msg = ch["message"]
        except (KeyError, IndexError, TypeError):
            out.append({"call": m.group(2), "attempt": int(m.group(3)), "content": None, "reasoning_chars": None, "finish": None})
            continue
        rc = msg.get("reasoning_content")
        out.append({"call": m.group(2), "attempt": int(m.group(3)), "content": msg.get("content"), "reasoning_chars": None if rc is None else len(rc),
                    "finish": ch.get("finish_reason")})
    return out


def company_record(run_dir: Path) -> dict:
    """The behaviour facts of one company-date."""
    res = _load(run_dir / "result.json") if (run_dir / "result.json").exists() else {}
    job = _load(run_dir / "job.json") if (run_dir / "job.json").exists() else {}
    atts = call_attempts(run_dir)
    first = {}
    for a in atts:
        if a["attempt"] == 1 and a["call"] not in first:
            obj, err = parse_json(a["content"])
            first[a["call"]] = {"parsed": err is None and a["finish"] != "length", "reasoning_chars": a["reasoning_chars"]}
    calls = {c["call"]: c for c in res.get("calls") or []}
    final_pos = (res.get("final") or {}).get("positions") or {}
    pass1_pos = (res.get("pass1") or {}).get("positions") or {}
    integ = job.get("integrity") or {}
    return {"status": res.get("status"), "first": first, "calls": {k: {"ok": bool(v.get("ok")), "retried": bool(v.get("retried"))} for k, v in calls.items()},
            "n_attempts": len(atts), "n_length": sum(1 for a in atts if a["finish"] == "length"),
            "final": {n: {"status": p.get("status"), "percentile": p.get("percentile"), "width": p.get("width")} for n, p in final_pos.items()},
            "pass1": {n: {"status": p.get("status")} for n, p in pass1_pos.items()},
            "citations": integ.get("n_citations"), "citations_failed": integ.get("n_citations_failed"),
            "decisions": [{k: d.get(k) for k in ("proposed", "accepted", "toward_price", "new_quote", "named_error")}
                          for d in (res.get("redteam") or {}).get("decisions") or []]}


def identical_to_code(p: dict) -> bool:
    if p.get("status") == "unanchored":
        return True
    pct = p.get("percentile")
    return pct is not None and abs(float(pct) - 50.0) < 1e-9 and p.get("width") == "normal"


def _share(a: int, b: int) -> Optional[float]:
    return None if b == 0 else a / b


def measure(state_dir, *, leakage: bool = True) -> dict:
    recs = {k: company_record(d) for k, d in latest_attempts(state_dir).items()}
    st = statuses(state_dir)
    modelled = {k: r for k, r in recs.items() if r["first"]}
    first_n, first_ok = Counter(), Counter()
    checks_ok, final_ok = Counter(), Counter()
    reasoning: Dict[Tuple[str, str], int] = {}
    for k, r in modelled.items():
        for call, f in r["first"].items():
            first_n[call] += 1
            first_ok[call] += f["parsed"]
            if f["reasoning_chars"] is not None:
                reasoning[(k, call)] = f["reasoning_chars"]
        for call, c in r["calls"].items():
            checks_ok[call] += c["ok"] and not c["retried"]
            final_ok[call] += c["ok"]
    fin = [p for r in modelled.values() for p in r["final"].values()]
    p1 = [p for r in modelled.values() for p in r["pass1"].values()]
    p5 = [r["calls"]["P5"]["ok"] for r in modelled.values() if "P5" in r["calls"]]
    cits = sum(r["citations"] or 0 for r in modelled.values())
    cits_bad = sum(r["citations_failed"] or 0 for r in modelled.values())
    atts = sum(r["n_attempts"] for r in modelled.values())
    lengths = sum(r["n_length"] for r in modelled.values())
    dec = [d for r in modelled.values() for d in r["decisions"] if d.get("proposed")]
    out = {"n_company_dates": len(recs), "n_with_model_calls": len(modelled),
           "statuses": dict(Counter(st.get(k) or recs[k]["status"] for k in recs)),
           "technical": sorted(k for k in recs if (st.get(k) or recs[k]["status"]) in TECHNICAL),
           "first_parse": {c: {"n": first_n[c], "ok": first_ok[c], "share": _share(first_ok[c], first_n[c])} for c in sorted(first_n)},
           "first_parse_all": _share(sum(first_ok.values()), sum(first_n.values())),
           "first_checks_ok": {c: checks_ok[c] for c in sorted(checks_ok)}, "final_ok": {c: final_ok[c] for c in sorted(final_ok)},
           "unanchored_final": _share(sum(1 for p in fin if p.get("status") == "unanchored"), len(fin)), "n_final_inputs": len(fin),
           "unanchored_pass1": _share(sum(1 for p in p1 if p.get("status") == "unanchored"), len(p1)),
           "identical_to_code": _share(sum(1 for p in fin if identical_to_code(p)), len(fin)),
           "p5_success": _share(sum(p5), len(p5)), "n_p5": len(p5),
           "quotes_verified": _share(cits - cits_bad, cits), "n_citations": cits,
           "length_cut_share": _share(lengths, atts), "n_attempts": atts,
           "redteam": {"proposed": len(dec), "toward_price": sum(1 for d in dec if d.get("toward_price")),
                       "toward_without_new_quote": sum(1 for d in dec if d.get("toward_price") and not d.get("new_quote")),
                       "with_named_error": sum(1 for d in dec if d.get("named_error")), "accepted": sum(1 for d in dec if d.get("accepted"))},
           "reasoning_chars": {f"{k}|{c}": v for (k, c), v in sorted(reasoning.items())}}
    if leakage:
        from valuation.muse import leakage_audit
        runs = Path(state_dir) / "runs"
        out["leakage_violations"] = leakage_audit.audit(runs)["violations"] if runs.exists() else 0
    return out


def reasoning_ratios(m: dict, ref: dict) -> Dict[str, Optional[float]]:
    """Per call type: the median of (this run's reasoning chars / the reference's) over (company, call) pairs present in both."""
    by: Dict[str, List[float]] = defaultdict(list)
    for kc, v in m["reasoning_chars"].items():
        r = ref["reasoning_chars"].get(kc)
        if r:
            by[kc.split("|", 1)[1]].append(v / r)
    return {c: (statistics.median(xs) if xs else None) for c, xs in sorted(by.items())}


def gate(m: dict, ref: Optional[dict] = None) -> dict:
    """The Addendum AD.4 gate. A check whose input is missing is 'not evaluated', never passed."""
    def ge(x, t):
        return None if x is None else x >= t

    def le(x, t):
        return None if x is None else x <= t
    passes = {"first_parse": ge(m["first_parse_all"], GATE["first_parse_min"]), "unanchored": le(m["unanchored_final"], GATE["unanchored_max"]),
              "p5": ge(m["p5_success"], GATE["p5_min"])}
    ratios = reasoning_ratios(m, ref) if ref is not None else None
    stops = {"reasoning": None if not ratios else any(r is not None and r < STOP["reasoning_ratio_min"] for r in ratios.values()),
             "identical_to_code": None if m["identical_to_code"] is None else m["identical_to_code"] > STOP["identical_max"],
             "quotes": None if m["quotes_verified"] is None else m["quotes_verified"] < STOP["quotes_min"],
             "leakage": None if "leakage_violations" not in m else m["leakage_violations"] > 0,
             "technical": bool(m["technical"]),
             "length_cuts": None if m["length_cut_share"] is None else m["length_cut_share"] > STOP["length_cut_max"]}
    ok = all(v is True for v in passes.values()) and all(v is False for v in stops.values())
    return {"passes": passes, "stops": stops, "reasoning_ratios": ratios, "verdict": "PASS" if ok else "STOP",
            "not_evaluated": sorted([k for k, v in passes.items() if v is None] + [k for k, v in stops.items() if v is None])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("state_dir", type=Path)
    ap.add_argument("--reference", type=Path, help="the run-1 state folder, for the paired reasoning ratio")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    m = measure(a.state_dir)
    ref = measure(a.reference, leakage=False) if a.reference else None
    g = gate(m, ref)
    rep = {"measure": {k: v for k, v in m.items() if k != "reasoning_chars"}, "gate": g}
    print(json.dumps(rep, indent=1, default=str))
    if a.json:
        a.json.write_text(json.dumps({"measure": m, "gate": g}, indent=1, default=str), encoding="utf-8")
    return 0 if g["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

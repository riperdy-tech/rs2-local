"""integrity.py - the per-run integrity facts behind registration G5, read back from what the runner SAVED (not from what the pipeline believed).

G5: "the leakage audit is clean on every pack; the quote check passes on 100% of accepted citations; no run fails the transport or JSON rules more than once without the
fallback being recorded."

`verify_run_dir(run_dir)` re-derives, for one company-date, from `pack`-bearing request files and the final responses:

  QUOTES.  Every citation behind an ACCEPTED position (anchored; produced by P1-P4, by the P5 synthesis, or by an accepted P6 revision, plus an accepted revision's new_quote) is
           looked up with the pipeline's own rule (`checkers.check_citation`: the normalisation and the length bounds of the revision-21 `crux_check` rule, the section named,
           the quote found verbatim) in the sections the run's prompts SHOWED.  A section P5 or P6 did not show is looked up in the union of the sections every earlier prompt of
           the run showed: the quote has to be filing text the model was given.  A citation that does not pass is counted and listed.
  JSON/FALLBACK.  A call whose final answer failed the code checks (`ok` False in result.json) must leave a recorded fallback: an unanchored position, a synthesis stamp, or a P6
           decision that says the pass-1 position stands.  A not-ok call with no recorded fallback is a violation.
  TRANSPORT.  A company-date that ends `model_unavailable` (never completed) is a violation of the rule; the retries of one that completed are counted by the runner.

Nothing here calls a model or reads a price.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from valuation.muse import checkers, leakage_audit
from valuation.muse.checkers import Evidence


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _calls(run_dir: Path) -> Dict[str, dict]:
    """{call id: the LAST attempt's {request, response}} from the saved files (file stems NN_<call>_a<attempt>)."""
    best: Dict[str, tuple] = {}
    for rq in run_dir.glob("*_request.json"):
        m = re.match(r"(\d+)_(.+)_a(\d+)_request\.json$", rq.name)
        if not m:
            continue
        seq, call, att = int(m.group(1)), m.group(2), int(m.group(3))
        rp = rq.with_name(rq.name.replace("_request.json", "_response.json"))
        if not rp.exists():
            continue
        if call not in best or (att, seq) > best[call][0]:
            best[call] = ((att, seq), rq, rp)
    return {c: {"request": _load(rq), "response": _load(rp)} for c, (_k, rq, rp) in best.items()}


def _first_requests(run_dir: Path) -> List[dict]:
    out = []
    for rq in sorted(run_dir.glob("*_a1_request.json")):
        out.append(_load(rq))
    return out


def _content(resp: dict) -> Optional[str]:
    try:
        return resp["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def _shown_sections(requests: List[dict]) -> Dict[str, str]:
    """{section letter: all the text of that section any prompt showed} (R is kept apart: it is never evidence)."""
    shown: Dict[str, List[str]] = {}
    for rq in requests:
        msgs = rq.get("messages") or []
        if len(msgs) < 2:
            continue
        for letter, text in leakage_audit.split_user_text(msgs[1]["content"]):
            if letter is not None:
                shown.setdefault(letter, []).append(text)
    return {k: "\n\n".join(dict.fromkeys(v)) for k, v in shown.items()}


def accepted_citations(result: dict, calls: Dict[str, dict]) -> List[dict]:
    """[{input, source, section, quote}] behind every accepted position, from the final responses."""
    objs: Dict[str, Optional[dict]] = {}
    for c, d in calls.items():
        obj, _err = checkers.parse_json(_content(d["response"]))
        objs[c] = obj
    pos = (result.get("final") or {}).get("positions") or (result.get("pass1") or {}).get("positions") or {}
    prompt_of = {}
    fam = result.get("family")
    if fam:
        from valuation.muse.schema import PROMPT_INPUTS
        for p, names in PROMPT_INPUTS[fam].items():
            for n in names:
                prompt_of[n] = p
    out = []
    for name, p in pos.items():
        if p.get("status") != "anchored":
            continue
        src = p.get("source")
        call = {"P5": "P5", "P6": "P6_round2" if "P6_round2" in objs else "P6"}.get(src, prompt_of.get(name, src))
        obj = objs.get(call)
        e = ((obj or {}).get("inputs") or {}).get(name) if isinstance((obj or {}).get("inputs"), dict) else None
        if not isinstance(e, dict):
            out.append({"input": name, "source": src, "section": None, "quote": None, "missing_entry": True})
            continue
        cits = list(e.get("citations") or [])
        nq = e.get("new_quote")
        if src == "P6" and isinstance(nq, dict):
            cits.append(nq)
        for c in cits:
            if isinstance(c, dict):
                out.append({"input": name, "source": src, "section": c.get("section"), "quote": c.get("quote")})
    return out


def fallback_recorded(result: dict) -> bool:
    for scope in ("final", "pass1"):
        for p in ((result.get(scope) or {}).get("positions") or {}).values():
            if p.get("status") == "unanchored" or any("synthesis_failed" in s or "synthesis_check_failed" in s for s in p.get("stamps", [])):
                return True
    for d in (result.get("redteam") or {}).get("decisions", []):
        if not d.get("accepted") and ("no usable P6 answer" in str(d.get("reason")) or str(d.get("reason", "")).startswith("refused")):
            return True
    return False


def verify_run_dir(run_dir) -> dict:
    run_dir = Path(run_dir)
    rp = run_dir / "result.json"
    out = {"run_dir": str(run_dir), "status": None, "n_citations": 0, "n_citations_failed": 0, "failed": [], "n_calls": 0, "n_calls_not_ok": 0, "fallback_recorded": None,
           "json_rule_violation": False, "transport_violation": False}
    if not rp.exists():
        out["status"] = "no_result"
        return out
    result = _load(rp)
    out["status"] = result.get("status")
    if result.get("status") == "model_unavailable":
        out["transport_violation"] = True
    calls = _calls(run_dir)
    ev_sections = _shown_sections(_first_requests(run_dir))
    ev = Evidence(ev_sections)
    for c in accepted_citations(result, calls):
        out["n_citations"] += 1
        if c.get("missing_entry"):
            out["n_citations_failed"] += 1
            out["failed"].append({**c, "why": "the accepted position has no entry in the final response of its call"})
            continue
        issue = checkers.check_citation({"section": c["section"], "quote": c["quote"]}, ev, "verify", c["input"])
        if issue is not None:
            out["n_citations_failed"] += 1
            if len(out["failed"]) < 10:
                out["failed"].append({**c, "why": issue.message[:200]})
    rc = result.get("calls") or []
    out["n_calls"] = len(rc)
    out["n_calls_not_ok"] = sum(1 for c in rc if not c.get("ok"))
    out["fallback_recorded"] = fallback_recorded(result)
    out["json_rule_violation"] = out["n_calls_not_ok"] > 0 and not out["fallback_recorded"]
    return out

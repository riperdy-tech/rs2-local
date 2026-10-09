"""behaviour_stats.py - how Muse BEHAVED in a gate-2 state folder (Addendum AC 4): format, anchoring and the red team.  Behaviour only.

    python -m rebuild_harness.gate2.behaviour_stats [--state-dir DIR] [--keys KEY ...]

READS: for each finished company-date the saved `calls.jsonl`, the `_response.json` content of each call's FIRST attempt (only to ask whether it is one JSON object), the retry
request's list of failed checks, and the statuses of `result.json` (calls ok / retried, the position status of every input, the red-team decisions' proposed / accepted flags).
DOES NOT READ OR PRINT: any value (percentile, value per share, price, probability), any outcome, any return.  The gate of Addendum AC 4 is on these numbers:

    first-attempt parse         >= 90%   share of Muse calls whose first answer is one JSON object (`json_parse_first_attempt`); `clean_first_attempt` (no retry was needed: the answer
                                          also passed every code check) is reported beside it, and `format_clean_first_attempt` (no not_json / schema / section issue)
    unanchored inputs           <=  5%   share of the Muse inputs of the final assembly whose position is the prior's P50 because the checks failed twice
    P5 synthesis                >= 90%   share of the P5 calls that passed the checks (after the one retry)
    red team                    counts   inputs for which P6 proposed a revision / the revision was accepted (reported, not gated: it is a model behaviour measured by G4)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from valuation.muse.checkers import parse_json

from . import config

GATE = {"first_attempt_parse": 0.90, "unanchored_max": 0.05, "p5_success": 0.90}
FORMAT_CODES = ("not JSON", "not valid JSON", "empty", "one JSON object", "unexpected input", "must be an object", "must be a list", "is missing from", "cut off")


def _jl(p: Path) -> List[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _content(resp_path: Path) -> Optional[str]:
    try:
        return json.loads(resp_path.read_text(encoding="utf-8"))["choices"][0]["message"].get("content")
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _retry_messages(run_dir: Path, stem_a2: str) -> List[str]:
    """The failed checks the retry request listed (the last user message), one string per line."""
    try:
        msgs = json.loads((run_dir / (stem_a2 + "_request.json")).read_text(encoding="utf-8"))["messages"]
    except (OSError, ValueError, KeyError):
        return []
    last = msgs[-1]["content"] if msgs else ""
    return [ln[2:].strip() for ln in last.splitlines() if ln.startswith("- ")]


def run_dirs(state_dir=None, keys=None) -> List[Path]:
    """The LATEST attempt folder of each finished company-date that has a result and made at least one Muse call."""
    paths = config.state_paths(state_dir)
    out = []
    root = paths["runs"]
    if not root.exists():
        return out
    for date_dir in sorted(root.iterdir()):
        for key_dir in sorted(date_dir.iterdir()) if date_dir.is_dir() else []:
            if keys and key_dir.name not in keys:
                continue
            attempts = sorted(d for d in key_dir.iterdir() if d.is_dir() and re.fullmatch(r"a\d+", d.name))
            if attempts and (attempts[-1] / "calls.jsonl").exists() and (attempts[-1] / "result.json").exists():
                out.append(attempts[-1])
    return out


def _share(n: int, d: int) -> Optional[float]:
    return None if d == 0 else round(n / d, 4)


def behaviour(state_dir=None, keys=None) -> dict:
    n_calls = n_json1 = n_clean1 = n_fmt1 = n_final_ok = 0
    by_call: Dict[str, Counter] = {}
    retry_msgs: Counter = Counter()
    n_inputs = n_unanchored = 0
    unanchored_by_input: Counter = Counter()
    inputs_by_name: Counter = Counter()
    p5_run = p5_ok = 0
    proposed = accepted = 0
    statuses: Counter = Counter()
    dirs = run_dirs(state_dir, keys)
    for d in dirs:
        res = json.loads((d / "result.json").read_text(encoding="utf-8"))
        statuses[res.get("status")] += 1
        calls = _jl(d / "calls.jsonl")
        by_stem = {(c["call"], c["attempt"]): c for c in calls}
        for ids in sorted({c["call"] for c in calls}):
            a1 = by_stem[(ids, 1)]
            obj, _err = parse_json(_content(d / (a1["file_stem"] + "_response.json")))
            retried = (ids, 2) in by_stem
            msgs = _retry_messages(d, by_stem[(ids, 2)]["file_stem"]) if retried else []
            fmt_bad = obj is None or any(any(k in m for k in FORMAT_CODES) for m in msgs)
            n_calls += 1
            n_json1 += obj is not None
            n_clean1 += not retried
            n_fmt1 += not fmt_bad
            c = by_call.setdefault(ids, Counter())
            c["calls"] += 1
            c["json_first"] += obj is not None
            c["clean_first"] += not retried
            for m in msgs:
                retry_msgs[re.sub(r"\b\d+\b", "#", m)[:90]] += 1
        for rc in res.get("calls") or []:
            n_final_ok += bool(rc.get("ok"))
            if rc.get("call") == "P5":
                p5_run += 1
                p5_ok += bool(rc.get("ok"))
        pos = (res.get("final") or {}).get("positions") or (res.get("pass1") or {}).get("positions") or {}
        for name, p in pos.items():
            n_inputs += 1
            inputs_by_name[name] += 1
            if p.get("status") != "anchored":
                n_unanchored += 1
                unanchored_by_input[name] += 1
        for dec in (res.get("redteam") or {}).get("decisions") or []:
            proposed += bool(dec.get("proposed"))
            accepted += bool(dec.get("accepted"))
    rep = {"n_company_dates_with_muse_calls": len(dirs), "result_statuses": dict(statuses), "n_calls": n_calls,
           "json_parse_first_attempt": _share(n_json1, n_calls), "format_clean_first_attempt": _share(n_fmt1, n_calls), "clean_first_attempt": _share(n_clean1, n_calls),
           "final_ok": _share(n_final_ok, n_calls), "by_call": {k: {"calls": v["calls"], "json_first": v["json_first"], "clean_first": v["clean_first"]} for k, v in sorted(by_call.items())},
           "n_inputs": n_inputs, "n_unanchored": n_unanchored, "unanchored_share": _share(n_unanchored, n_inputs),
           "unanchored_by_input": {k: f"{unanchored_by_input[k]} of {inputs_by_name[k]}" for k in sorted(inputs_by_name)},
           "p5_runs": p5_run, "p5_ok": p5_ok, "p5_success": _share(p5_ok, p5_run),
           "red_team": {"inputs_with_a_proposal": proposed, "proposals_accepted": accepted},
           "retry_reasons_top": retry_msgs.most_common(12)}
    j = rep["json_parse_first_attempt"]
    rep["gate"] = {"thresholds": GATE,
                   "first_attempt_parse": None if j is None else j >= GATE["first_attempt_parse"],
                   "format_clean_first_attempt": None if rep["format_clean_first_attempt"] is None else rep["format_clean_first_attempt"] >= GATE["first_attempt_parse"],
                   "unanchored": None if rep["unanchored_share"] is None else rep["unanchored_share"] <= GATE["unanchored_max"],
                   "p5": None if rep["p5_success"] is None else rep["p5_success"] >= GATE["p5_success"]}
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--keys", nargs="*")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(behaviour(a.state_dir, a.keys), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

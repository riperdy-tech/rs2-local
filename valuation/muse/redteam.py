"""redteam.py - pass 2's checks and the revision rule (SPEC_muse_passes section 3), and the anchoring metric.

THE REVISION RULE. For every input P6 answers keep or revise. A revision that changes the pass-1 percentile or width needs ONE of
  (a) a NEW QUOTE: a valid citation (found verbatim in a section P6 was shown) that is not one of the quotes cited anywhere in pass 1 (equal to, contained
      in, or containing a pass-1 quote does not count as new), or
  (b) a NAMED ERROR: {"reason_index": n, "why_wrong": text} where n is the number of one of that input's pass-1 reasons and the text is at least
      NAMED_ERROR_MIN_CHARS characters.
  Addendum AE.1: a revision that moves TOWARD the price is accepted only under (a), with the new quote from a filing section (F, Q or D); (b) alone is
  refused for it. A revision away from the price, or a width-only change, keeps (a) or (b).
Neither: the revision is REFUSED and the pass-1 position stands (stamped). The hard-evidence rule of pass 1 applies to the revised position (outside
P10..P90), and also to a revised position within NEAR_EXTRAORDINARY_POINTS percentile points of an extraordinary price requirement (schema.py): the side
relying on an extraordinary assumption carries the burden. Failures of schema, quotes or the hard-evidence rule inside the answer are check failures (one
retry, runner.py); a refusal under (a)/(b) is a decision, not a retry.

A requirement the reverse valuation could not locate ("not reachable") is treated as sitting at the nearest edge of P1..P99, clamped to P5..P95.

THE ANCHORING METRIC is measured in the replay and is never a gate inside a run. Over PROPOSED revisions (before the refusal rule) it reports the share that
move toward the price and, among those, the share without new evidence (no new quote; and separately no new quote and no named error). Over ACCEPTED
revisions the share that move toward the price. A pass 2 that only moves inputs toward the price without new evidence is the failure the design exists to
prevent; the coordinator reads this per replay date.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .checkers import (Evidence, Issue, NAMED_ERROR_MIN_CHARS, base_section, check_citation, check_entry, entry_has_hard_evidence, hard_evidence,
                       normalise)

FILING_SECTIONS = ("F", "Q", "D")       # Addendum AE.1: the sections a toward-price revision's new quote must come from
from .mapping import Position
from .schema import NEAR_EXTRAORDINARY_POINTS, PCT_MAX, PCT_MIN

MARKET_CASE_MIN = 20


def pass1_quote_set(entries: Iterable[Optional[Mapping]]) -> List[str]:
    """The normalised quotes cited anywhere in pass 1 (P1-P5 entries and their extra citations)."""
    out = []
    for e in entries:
        for c in (e or {}).get("citations") or []:
            if isinstance(c, dict) and isinstance(c.get("quote"), str):
                out.append(normalise(c["quote"]))
    return out


def is_new_quote(quote: str, seen: Sequence[str]) -> bool:
    q = normalise(quote)
    return not any(q == s or q in s or s in q for s in seen)


def validate_p6(obj: dict, inputs: Sequence[str], ev: Evidence, pass1_entries: Mapping[str, Optional[Mapping]]) -> List[Issue]:
    """Schema, quote and hard-evidence checks of a P6 answer (the retry's checks). The revision rule is NOT applied here."""
    block = obj.get("inputs")
    if not isinstance(block, dict):
        return [Issue("schema", "the answer needs an object \"inputs\" with one entry per input")]
    out: List[Issue] = []
    for n in inputs:
        e = block.get(n)
        if not isinstance(e, dict):
            out.append(Issue("schema", f"input {n} is missing from \"inputs\"", n))
            continue
        if not isinstance(e.get("market_case"), str) or len(e["market_case"].strip()) < MARKET_CASE_MIN:
            out.append(Issue("schema", f"input {n}: market_case must be a text of at least {MARKET_CASE_MIN} characters", n))
        if e.get("decision") not in ("keep", "revise"):
            out.append(Issue("schema", f"input {n}: decision must be \"keep\" or \"revise\"", n))
            continue
        nq, ne = e.get("new_quote"), e.get("named_error")
        if nq is not None:
            iss = check_citation(nq, ev, f"input {n}, new_quote", n)
            if iss is not None:
                out.append(iss)
        if ne is not None:
            reasons = (pass1_entries.get(n) or {}).get("reasons") or []
            idx = ne.get("reason_index") if isinstance(ne, dict) else None
            if (not isinstance(ne, dict) or not isinstance(idx, int) or isinstance(idx, bool) or not 1 <= idx <= max(len(reasons), 0)
                    or not isinstance(ne.get("why_wrong"), str) or len(ne["why_wrong"].strip()) < NAMED_ERROR_MIN_CHARS):
                out.append(Issue("schema", f"input {n}: named_error must be {{\"reason_index\": 1..{len(reasons)}, \"why_wrong\": text of at least "
                                           f"{NAMED_ERROR_MIN_CHARS} characters}}", n))
        if e["decision"] == "revise":
            out += check_entry(n, e, ev, f"input {n} (revised)")
    for n in block:
        if n not in inputs:
            out.append(Issue("schema", f"unexpected input {n!r}"))
    return out


def decide(name: str, pass1: Position, pass1_entry: Optional[Mapping], p6_entry: Optional[Mapping], requirement: Optional[Mapping], ev: Evidence,
           seen_quotes: Sequence[str]) -> dict:
    """The outcome for one input: {"input", "proposed", "accepted", "reason", "toward_price", "new_quote", "named_error", "position"}."""
    rec = {"input": name, "proposed": False, "accepted": False, "reason": "kept", "toward_price": None, "new_quote": False, "named_error": False,
           "pass1": pass1.as_dict(), "position": pass1}
    if not p6_entry or p6_entry.get("decision") != "revise":
        return rec
    pct, width = float(p6_entry["percentile"]), p6_entry["width"]
    if abs(pct - pass1.percentile) < 1e-9 and width == pass1.width:
        rec["reason"] = "revise with the pass-1 percentile and width: kept"
        return rec
    rec["proposed"] = True
    req_pct = None
    if requirement:
        if requirement.get("status") == "ok":
            req_pct = requirement["required_percentile"]
        elif requirement.get("status") == "not_reachable" and requirement.get("nearest_percentile") is not None:
            req_pct = requirement["nearest_percentile"]
    if req_pct is not None and abs(pct - pass1.percentile) > 1e-9:
        rec["toward_price"] = (pct - pass1.percentile) * (req_pct - pass1.percentile) > 0
    elif req_pct is not None:
        rec["toward_price"] = False                       # a width-only change moves no percentile
    nq = p6_entry.get("new_quote")
    rec["new_quote"] = bool(isinstance(nq, dict) and isinstance(nq.get("quote"), str) and is_new_quote(nq["quote"], seen_quotes))
    ne = p6_entry.get("named_error")
    rec["named_error"] = bool(isinstance(ne, dict))
    if not rec["new_quote"] and not rec["named_error"]:
        rec["reason"] = "refused: a revision needs a quote not cited in pass 1 or a named error in a pass-1 reason; the pass-1 position stands"
        return rec
    # Addendum AE.1 (both reviewers of cross-checks 6 and 7): a move TOWARD the price needs a NEW QUOTE from the filings (F, Q or D); a named error alone
    # no longer suffices, because run 1 (11 of 13) and rehearsal r2 (4 of 4) moved toward the price on named errors without new evidence.
    rec["new_quote_from_filing"] = bool(rec["new_quote"] and base_section(nq.get("section")) in FILING_SECTIONS)
    if rec["toward_price"] and not rec["new_quote_from_filing"]:
        rec["reason"] = ("refused (Addendum AE.1): a revision toward the price needs a new quote from the filings (sections F, Q or D) that was not cited "
                         "in pass 1; a named error alone is not enough; the pass-1 position stands")
        return rec
    extraordinary = bool(requirement and requirement.get("extraordinary"))
    stamps = ["revised_by_P6", "revision_evidence: " + ("new_quote" if rec["new_quote"] else "named_error")]
    hard = entry_has_hard_evidence(p6_entry, ev)
    if extraordinary and req_pct is not None:
        edge = min(max(req_pct, PCT_MIN), PCT_MAX)
        if abs(pct - edge) <= NEAR_EXTRAORDINARY_POINTS and not hard_evidence(p6_entry.get("citations"), ev):
            rec["reason"] = ("refused: the revised position is within %g percentile points of an extraordinary price requirement and has no hard "
                             "evidence; the pass-1 position stands" % NEAR_EXTRAORDINARY_POINTS)
            return rec
    rec["accepted"] = True
    rec["reason"] = "accepted"
    rec["position"] = Position(pct, width, "anchored", "P6", stamps, hard_evidence=hard)
    return rec


def anchoring_metric(decisions: Iterable[Mapping]) -> dict:
    """The anchoring metric over a collection of `decide` records (one replay date, or any grouping)."""
    ds = list(decisions)
    prop = [d for d in ds if d["proposed"]]
    acc = [d for d in ds if d["accepted"]]
    toward = [d for d in prop if d["toward_price"]]
    toward_acc = [d for d in acc if d["toward_price"]]
    no_quote = [d for d in toward if not d["new_quote"]]
    neither = [d for d in toward if not d["new_quote"] and not d["named_error"]]

    def share(a, b):
        return None if b == 0 else a / b
    return {"n_inputs": len(ds), "n_proposed": len(prop), "n_accepted": len(acc), "n_refused": len(prop) - len(acc),
            "n_toward_price": len(toward), "share_toward_price_of_proposed": share(len(toward), len(prop)),
            "n_toward_price_without_new_quote": len(no_quote), "share_without_new_quote_among_toward": share(len(no_quote), len(toward)),
            "n_toward_price_without_new_quote_or_named_error": len(neither),
            "share_without_new_quote_or_named_error_among_toward": share(len(neither), len(toward)),
            "n_accepted_toward_price": len(toward_acc), "share_toward_price_of_accepted": share(len(toward_acc), len(acc))}


def anchoring_by_date(records: Iterable[Mapping]) -> Dict[str, dict]:
    """{asof: metric} from decision records that carry an "asof" key."""
    by: Dict[str, list] = {}
    for r in records:
        by.setdefault(r["asof"], []).append(r)
    return {k: anchoring_metric(v) for k, v in sorted(by.items())}

"""found.py - checks v18 (SPEC_prompt_v13): the reply's `found` list, every sentence Qwen finds that guides year 1's revenue, whether or
not it chose the option `guidance`.

Annotation only: a `found` entry never moves a number and never fails a reply. A malformed list or entry is annotated and skipped. Each
well-formed entry is read exactly as rev_growth.y1's chosen guidance would be (menu.read_guidance: the sentence, date, figure and period
rules), so the PREREG_cohorts_nextq selection reading (S1) compares Qwen's choice with code's read of every guidance sentence it found.
"""
from qwen_c.value import menu

KEY = "rev_growth.y1"
FIELDS = ("evidence", "metric", "period", "sign", "ordinal")


def read(reply, base, ids, m, fy0, fy_of):
    """([{entry fields, index, number, why, period_of_evidence}], index of the entry naming the chosen year-1 sentence or None,
    annotations). `fy_of(period)` is the fiscal year of a period (checks.fiscal_year_of over the facts' fiscal-year ends)."""
    out, notes, found = [], [], reply.get("found")
    if found is None:
        return out, None, notes
    if not isinstance(found, list):
        return out, None, ["found_malformed: not a list"]
    for i, e in enumerate(found):
        if not menu.guidance_entry_ok(e, KEY, ids):
            notes.append(f"found_malformed: {i}")
            continue
        x, why = menu.read_guidance(e, KEY, ids, None, m, fy0, fy_of)
        out.append(dict({f: e.get(f) for f in FIELDS}, index=i, number=x, why=why, period_of_evidence=ids[e["evidence"]].get("period")))
    chosen_entry = (reply.get("guidance") or {}).get(KEY) if menu.option(base, KEY) == "guidance" else None
    if not isinstance(chosen_entry, dict):
        return out, None, notes
    chosen = next((r["index"] for r in out if r["evidence"] == chosen_entry.get("evidence")), None)
    return out, chosen, notes + (["found_missing_chosen"] if chosen is None else [])

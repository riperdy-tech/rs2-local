"""why_losses.py - WO_NC5: the cloud read says WHY a thin profit record is thin, before the name is valued (operator 2026-11-18).

Asked once per name, only when the valuation base carries `tax_fallback` (no tax rate could be measured), and only by the cloud arms
(gemini_ondemand.analyze). The model picks a cause from MENU and quotes the evidence; code maps the cause to an outcome (valued with a
label, or no call) and checks every quote against the cited evidence item. Nothing under qwen_c/ changes: Qwen's prompts are not touched.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from qwen_c import contract, runner, tasks  # noqa: E402

WHY_LOSSES_VERSION = "why_losses.v1 2026-11-18 WO_NC5"
UNEXPLAINED = "loss_record_unexplained"
# cause id: (label shown with a valued name, reason of the no call or None when the name is valued)
MENU = {"divested_business": ("the losses came from a business since sold, closed or reported as discontinued", None),
        "one_off_charges": ("the losses came from write-downs, restructuring or other charges that do not recur", None),
        "financing_burden": ("the operations earn a profit before interest; interest or other financing cost made the loss", None),
        "operating_losses": ("the continuing operations themselves lose money", "loss_record_operating"),
        "cannot_tell": ("the filings in the packet do not say", UNEXPLAINED)}

SYSTEM = ("You read one company's filings to find out why its profit record is thin. Answer only from the evidence given in this "
          "conversation. What the evidence does not say is not known.")
QUESTION = """QUESTION. Using only the evidence above, say why the profit record is thin. Choose exactly one cause:
- divested_business: the losses came from a business since sold, closed or reported as discontinued.
- one_off_charges: write-downs, restructuring or other charges that do not recur.
- financing_burden: the operations earn a profit before interest; interest or other financing cost made the loss.
- operating_losses: the continuing operations themselves lose money.
- cannot_tell: the evidence does not say.

Answer only from the evidence given. Quote verbatim: every quote must be copied exactly, character for character, from the item it cites. If the evidence does not say which cause applies, choose cannot_tell; do not guess.

Reply with one JSON object and nothing else: {"cause": "<one id above>", "explanation": "<one or two plain sentences>", "quotes": [{"id": "<evidence item id, for example F2>", "quote": "<exact text copied from that item>"}]}. Give at least one quote."""


def pretax_lines(f):
    """The filed pretax income by fiscal year, in the filing's currency, oldest first."""
    vals = sorted(((v["end"], v["value"]) for v in (f.get("pretax_income") or {}).get("values", [])))
    return "FILED PRETAX INCOME BY FISCAL YEAR (the filing's currency):\n" + "\n".join(f"- fiscal year ended {e}: {x:,.0f}" for e, x in vals)


def messages(packet, f, problem=None):
    user = tasks.render_packet(packet) + "\n\n" + pretax_lines(f) + "\n\n" + QUESTION
    if problem:
        user += f"\n\nYour last reply was not accepted: {problem}. Reply again."
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def check(obj, texts):
    """(answer, None) or (None, what was wrong). answer = {"cause", "explanation", "quotes": only the verified ones}."""
    if not isinstance(obj, dict):
        return None, "the reply is not a JSON object"
    cause, why = obj.get("cause"), obj.get("explanation")
    if cause not in MENU:
        return None, f"cause {cause!r} is not one of {', '.join(MENU)}"
    if not isinstance(why, str) or not why.strip():
        return None, "explanation is missing"
    kept, bad = [], []
    for q in obj.get("quotes") if isinstance(obj.get("quotes"), list) else []:
        i, s = (q.get("id"), q.get("quote")) if isinstance(q, dict) else (None, None)
        if isinstance(i, str) and isinstance(s, str) and i in texts and contract.quote_found(s, [texts[i]]):
            kept.append({"id": i, "quote": s})
        else:
            bad.append(str(s)[:80])
    if not kept:
        return None, "no quote was found word for word in the item it cites" + (f" (not found: {'; '.join(bad)})" if bad else " (no quote given)")
    return {"cause": cause, "explanation": why.strip(), "quotes": kept}, None


def ask(packet, f, raw_dir):
    """(loss_record, no-call reason or None). One call, one retry when the reply is not a valid answer; still not valid is `unexplained`
    with the failure recorded. A call that gets no reply raises: that is not an answer (the worker's failure path takes it)."""
    texts, problem, failure = contract.evidence_texts(packet), None, None
    raw_dir.mkdir(parents=True, exist_ok=True)
    for n in (1, 2):
        msgs = messages(packet, f, problem)
        kind, resp, detail = runner.call({"model": runner.MODEL, "stream": False, "messages": msgs}, runner.llm_provider.OLLAMA_URL, runner.TASK_TIMEOUT_S)
        if kind != "reply":
            raise RuntimeError(f"why_losses call failed: {kind}: {detail}")
        content = ((resp or {}).get("message") or {}).get("content")
        obj, perr = runner.parse_reply(content)
        ans, problem = (None, f"not valid JSON: {perr}") if perr else check(obj, texts)
        (raw_dir / f"attempt_{n}.json").write_text(json.dumps({"messages": msgs, "response": content, "problem": problem}, indent=1), encoding="utf-8")
        if ans:
            label, reason = MENU[ans["cause"]]
            return {**ans, "label": label, "version": WHY_LOSSES_VERSION}, reason
        failure = problem
    return {"cause": None, "label": None, "explanation": None, "quotes": [], "version": WHY_LOSSES_VERSION, "failure": failure}, UNEXPLAINED

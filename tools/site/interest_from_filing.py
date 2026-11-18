"""interest_from_filing.py - WO_NC8: where the tagged interest expense gives a cost of debt outside the band, the cloud read states the interest on
borrowings from the filing (operator 2026-11-18).

Asked once per name, only when run.prepare refuses with kd_out_of_band, and only by the cloud arms (gemini_ondemand.analyze), before the valuation
runs. The model quotes the line that carries the figure; code checks the quote against the cited item and the digits of the figure against the quote,
and the valuation is then recomputed with inputs.base(interest_override=...). The band is not touched: it still applies to the new rate. A figure the
read cannot ground leaves the refusal as it is. Nothing under qwen_c/ changes for Qwen: its prompts are not touched.
"""
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from qwen_c import contract, runner, tasks  # noqa: E402
from qwen_c.value import task as vtask  # noqa: E402

INTEREST_FROM_FILING_VERSION = "interest_from_filing.v1 2026-11-18 WO_NC8"
FOUND = "interest_on_borrowings"
CANNOT = "cannot_tell"
SCALES = {"units": Decimal(1), "thousands": Decimal(10) ** 3, "millions": Decimal(10) ** 6, "billions": Decimal(10) ** 9}
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")        # a number as printed: with thousands separators or without

SYSTEM = ("You read one company's filings to find the interest it paid on its borrowings. Answer only from the evidence given in this "
          "conversation. What the evidence does not say is not known.")
QUESTION = """QUESTION. Using only the evidence above, find the interest expense on the company's debt and borrowings for the fiscal year ended {fy0}, and for that fiscal year only. If the filing shows interest both before and after capitalised interest is deducted, give the figure before the deduction. Leave out exchange differences, fees, accretion on items that are not debt, and lease interest where the filing shows it apart. If the evidence above does not show this figure, answer cannot_tell; do not estimate it and do not add figures up.

Quote verbatim: every quote must be copied exactly, character for character, from the item it cites, and the quote must contain the number you give.

Reply with one JSON object and nothing else: {{"found": "interest_on_borrowings" or "cannot_tell", "value": <the number exactly as printed in the filing, digits only>, "scale": "units" or "thousands" or "millions" or "billions" (the unit the filing states for that line), "what": "<the filing's own name for the line>", "why_tagged_figure_differs": "<one sentence>", "quotes": [{{"id": "<evidence item id, for example F2>", "quote": "<exact text copied from that item>"}}]}}. With cannot_tell, give only found and why_tagged_figure_differs."""


def figures_text(fg):
    """What code used: the tagged interest figure, the two year-end debt totals and the rate they give (in the filing's currency)."""
    extra = f" (the interest figure code divided by debt, {fg['kd_interest']:,.0f}, adds the interest of a financing arm that the tag leaves out)" if fg["kd_interest"] != fg["interest"] else ""
    return (f"WHAT CODE USED. For the fiscal year ended {fg['fy0']} the filed data tags the interest expense as {fg['tag']}: {fg['interest']:,.0f} (the filing's currency). "
            f"Debt at that year end was {fg['debt0']:,.0f} and at the year end before {fg['debt_prev']:,.0f}. Interest divided by the average of the two is "
            f"{fg['kd']:.2%}, which code cannot accept as the cost of debt{extra}. The tagged figure may not be the interest on borrowings.")


def messages(packet, fg, problem=None):
    user = tasks.render_packet(vtask.mask_price(packet)) + "\n\n" + figures_text(fg) + "\n\n" + QUESTION.format(fy0=fg["fy0"])
    if problem:
        user += f"\n\nYour last reply was not accepted: {problem}. Reply again."
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _printed(value):
    """The Decimal of the number as printed (a JSON number, or text with thousands separators, brackets and spaces), or None."""
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return Decimal(repr(value))
        s = re.sub(r"[,\s()\[\]]", "", str(value))
        return Decimal(s) if re.fullmatch(r"-?\d+(?:\.\d+)?", s) else None
    except InvalidOperation:
        return None


def digits_in_quote(v, quotes):
    """True when a number printed in one of the quotes equals the Decimal `v` (thousands separators ignored, so 90,827 is 90827 and 90.80 is 90.8)."""
    return any(Decimal(t.replace(",", "")) == v for q in quotes for t in _NUM.findall(q))


def check(obj, texts):
    """(answer, None) or (None, what was wrong). answer = {"found", "why", "value" (in units), "printed", "scale", "what", "quotes": the verified ones}."""
    if not isinstance(obj, dict):
        return None, "the reply is not a JSON object"
    found, why = obj.get("found"), obj.get("why_tagged_figure_differs")
    if found not in (FOUND, CANNOT):
        return None, f"found {found!r} is not one of {FOUND}, {CANNOT}"
    why = why.strip() if isinstance(why, str) else ""
    if found == CANNOT:
        return {"found": CANNOT, "why": why}, None
    if not why:
        return None, "why_tagged_figure_differs is missing"
    scale, what = obj.get("scale"), obj.get("what")
    if scale not in SCALES:
        return None, f"scale {scale!r} is not one of {', '.join(SCALES)}"
    if not isinstance(what, str) or not what.strip():
        return None, "what is missing"
    v = _printed(obj.get("value"))
    if v is None or not v.is_finite() or not v > 0:
        return None, f"value {obj.get('value')!r} is not a number above 0"
    kept, bad = [], []
    for q in obj.get("quotes") if isinstance(obj.get("quotes"), list) else []:
        i, s = (q.get("id"), q.get("quote")) if isinstance(q, dict) else (None, None)
        if isinstance(i, str) and isinstance(s, str) and i in texts and contract.quote_found(s, [texts[i]]):
            kept.append({"id": i, "quote": s})
        else:
            bad.append(str(s)[:80])
    if not kept:
        return None, "no quote was found word for word in the item it cites" + (f" (not found: {'; '.join(bad)})" if bad else " (no quote given)")
    carrying = [k for k in kept if digits_in_quote(v, [k["quote"]])]
    if not carrying:
        return None, f"the number {obj.get('value')!r} does not appear in any quote that was found word for word"
    return {"found": FOUND, "why": why, "value": float(v * SCALES[scale]), "printed": obj.get("value"), "scale": scale, "what": what.strip(),
            "quotes": carrying + [k for k in kept if k not in carrying]}, None      # the first quote is one that carries the number


def ask(packet, fg, raw_dir):
    """(record, override): override is the interest in the filing's currency to value with, or None when the refusal stands. `fg` is the
    kd_out_of_band refusal's .figures. One call, one retry when the reply fails a check; a reply of cannot_tell is an answer and is not retried.
    A call that gets no reply raises (the worker's failure path takes it)."""
    texts, problem, failure = contract.evidence_texts(vtask.mask_price(packet)), None, None
    base = {"version": INTEREST_FROM_FILING_VERSION, "tagged_value": fg["interest"], "kd_tagged": fg["kd"], "fy0": fg["fy0"]}
    raw_dir.mkdir(parents=True, exist_ok=True)
    for n in (1, 2):
        msgs = messages(packet, fg, problem)
        kind, resp, detail = runner.call({"model": runner.MODEL, "stream": False, "messages": msgs}, runner.llm_provider.OLLAMA_URL, runner.TASK_TIMEOUT_S)
        if kind != "reply":
            raise RuntimeError(f"interest_from_filing call failed: {kind}: {detail}")
        content = ((resp or {}).get("message") or {}).get("content")
        obj, perr = runner.parse_reply(content)
        ans, problem = (None, f"not valid JSON: {perr}") if perr else check(obj, texts)
        (raw_dir / f"attempt_{n}.json").write_text(json.dumps({"messages": msgs, "response": content, "problem": problem}, indent=1), encoding="utf-8")
        if ans and ans["found"] == CANNOT:
            return {**base, "status": CANNOT, "why": ans["why"]}, None
        if ans:
            return {**base, "status": "used", "value": ans["value"], "printed": ans["printed"], "scale": ans["scale"], "what": ans["what"], "why": ans["why"],
                    "quote": ans["quotes"][0]["quote"], "quotes": ans["quotes"], "kd_used": None}, ans["value"]
        failure = problem
    return {**base, "status": "unverified", "failure": failure}, None

"""tasks.py - what the model is told (SPEC_m3m_qwen_pipeline.md section 4).

Every task is sent as the same layout, so Ollama reuses the prompt prefix:
    1. the system message: SYSTEM (one text for every task);
    2. the user message: the packet rendered as [S0] ..., [F1] ..., [P1] ... blocks (render_packet), then the task instruction last.

Changing any text here changes what the model is told: bump PROMPT_VERSION and re-pin the hashes in tests/test_tasks.py.
"""
from datetime import datetime

PROMPT_VERSION = "m3m.prompt.v1"
TASKS = ("business_model", "financial_health", "competitive_position", "growth_thesis", "risks", "thesis_change",
         "unresolved_questions")

SYSTEM = """You analyse one company using only the evidence given in this conversation.

EVIDENCE. The user message holds numbered evidence items. [S0] is a data row from a stock screener. [F1], [F2] and so on are financial statements from SEC filings. [P1], [P2] and so on are passages from SEC filings and company releases. Each item states its form, its period and the time it became public. Text shown as "[… 1,234 characters omitted …]" was cut and is not evidence.

CUTOFF. The decision time T is stated at the top of the user message. Use nothing you know from training, from memory or from events after T, even when you believe it is true. What the items do not say is not known.

CLAIMS. Each claim is one short statement drawn from the evidence. Every claim lists in "fact_ids" the ids of the items it rests on, for example ["F2", "P1"]. A statement that no item supports does not belong in "claims".

QUOTATIONS. "quotes" holds extracts copied exactly, character for character, from the cited items, each one sentence or shorter. Do not shorten, join, translate or correct a quotation. If you cannot copy it exactly, leave it out.

FIGURES. Every number written in a claim must also be listed in that claim's "numbers", written exactly as a cited item prints it, with the currency sign, the unit word (thousand, million, billion) or the % only when the item prints it next to the number. When a table gives its scale only in its heading, such as "$ in Millions", write the number in the claim and in "numbers" exactly as printed, for example "1,234", and name the scale apart from it, for example "(table in millions)". Do not round, convert, add up or compute new figures.

UNKNOWNS. When the evidence cannot answer part of the task, say so in "unknowns" in a short sentence. Do not guess.

SCOPE. Describe and explain what the evidence shows. Do not value the company, forecast its share price or recommend any action.

OUTPUT. Reply with JSON only, inside one fenced block that opens with ```json and closes with ```. Write nothing outside the block. Use exactly the shape the task gives; every field shown is required unless the task says it is optional."""

_CLAIM_FIELDS = '''"claim": "one short statement", "fact_ids": ["F1"], "quotes": ["an exact extract from a cited item"], "numbers": ["each figure in the claim, as printed"], "mechanism": "optional: how it works", "horizon": "optional: over what period", "counter": "optional: what argues against it", "confidence_basis": "stated in the cited item, or inferred, and from what"'''


def _shape(task, extra=""):
    lead = f"{extra}, " if extra else ""
    return ('```json\n{"task": "' + task + '", "claims": [{' + lead + _CLAIM_FIELDS + '}], "unknowns": ["what the evidence cannot answer"]}\n```')


INSTRUCTIONS = {
    "business_model": (
        "TASK business_model. Explain how the company makes money: what it sells and to whom, its reporting segments, and the "
        "drivers that move its revenue and its costs. One claim per point.\n"
        "Reply in this shape:\n" + _shape("business_model")),
    "financial_health": (
        "TASK financial_health. Describe the company's liquidity, its leverage, how much cash it generates and the quality of "
        "that cash generation, and its refinancing needs: debt that falls due, and how it can be met. One claim per point.\n"
        "Reply in this shape:\n" + _shape("financial_health")),
    "competitive_position": (
        "TASK competitive_position. Describe the company's competitive position, the evidence for it, and the threats to it "
        "named in the evidence. One claim per point.\n"
        "Reply in this shape:\n" + _shape("competitive_position")),
    "growth_thesis": (
        "TASK growth_thesis. Name the drivers of the company's growth that the evidence shows, and for each, what must be true "
        "for it to continue. One claim per driver or condition.\n"
        "Reply in this shape:\n" + _shape("growth_thesis")),
    "risks": (
        "TASK risks. List the risks the evidence supports, and the counterarguments. For each risk give its mechanism (how it "
        "would hurt the company), its horizon (when it could happen, as the evidence states it, or \"not stated\"), and in "
        "\"counter\" a competing explanation or the evidence against it. \"risk_type\" is one of: guidance_withdrawal, "
        "bankruptcy, delisting, restatement, liquidity_rupture, contract_rupture, regulatory_action, thesis_break, other. "
        "One claim per risk.\n"
        "Reply in this shape:\n" + _shape("risks", '"risk_type": "one of the risk types above"')),
    "unresolved_questions": (
        "TASK unresolved_questions. List the questions about this company that the evidence raises but cannot settle. In each "
        "claim, \"claim\" is the question, \"fact_ids\" are the items that raise it, and \"settled_by\" names the document "
        "that would settle it (for example a specific filing, exhibit or disclosure). One claim per question.\n"
        "Reply in this shape:\n" + _shape("unresolved_questions", '"settled_by": "the document that would settle it"')),
}

THESIS_CHANGE_INSTRUCTION = (
    "TASK thesis_change. An earlier analysis of this company, as of {prior_t}, made the points listed below. Compare each "
    "point with the evidence items that became effective after {prior_t}: {after_ids}. For each point give one claim with "
    "\"point\" set to its id and \"change_type\" set to one of: unchanged (the newer evidence leaves the point as it was), "
    "changed (the newer evidence alters it), unknown (the newer evidence does not address it), unsupported (the evidence does "
    "not support the point at all). Cite the items you rely on.\n"
    "EARLIER POINTS:\n{points}\n"
    "Reply in this shape:\n" + _shape("thesis_change", '"point": "G1", "change_type": "one of the four change types"'))

RETRY_LINE = "Your last reply was not valid JSON for this shape; reply again."


# ---------------------------------------------------------------- the packet as the user message

def _v(x):
    return "not stated" if x is None or x == "" else str(x)


def _source(src):
    if not isinstance(src, dict):
        return "not stated"
    if src.get("accession") or src.get("url"):
        return f"SEC accession {_v(src.get('accession'))}, {_v(src.get('url'))}"
    if src.get("git_commit") or src.get("path"):
        return f"screener git {_v(src.get('git_commit'))}:{_v(src.get('path'))}"
    return "not stated"


def render_item(e):
    head = (f"[{e['fact_id']}] kind: {_v(e.get('kind'))} | form: {_v(e.get('form'))} | period: {_v(e.get('period'))} | "
            f"effective: {_v(e.get('effective_at'))} | source: {_source(e.get('source'))}")
    return head + "\n" + (e.get("text") or "")


def render_packet(packet):
    """The packet as the opening of the user message. Annotations and `excluded` are not shown: `excluded` names filings that became
    effective after T."""
    ev = packet.get("evidence") or []
    lines = [f"DECISION TIME T: {_v(packet.get('decision_time_utc'))}",
             f"COMPANY: ticker {_v(packet.get('ticker'))}, SEC CIK {_v(packet.get('cik'))}",
             f"EVIDENCE ITEMS: {len(ev)}", ""]
    return "\n".join(lines) + "\n" + "\n\n".join(render_item(e) for e in ev)


def _parse_t(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def effective_after(packet, prior_t):
    """The fact ids of the items whose effective_at is after prior_t. An item whose time cannot be read is not counted as after."""
    pt = _parse_t(prior_t)
    out = []
    for e in packet.get("evidence") or []:
        et = _parse_t(e.get("effective_at"))
        if pt is not None and et is not None and et.tzinfo is not None and pt.tzinfo is not None and et > pt:
            out.append(e["fact_id"])
    return out


def prior_points(prior):
    """[(point id, claim dict)] of a prior run: G1.. from its growth_thesis claims, R1.. from its risks claims."""
    out = []
    for prefix, task in (("G", "growth_thesis"), ("R", "risks")):
        for i, c in enumerate(prior.get(task) or [], 1):
            out.append((f"{prefix}{i}", c))
    return out


def thesis_change_instruction(packet, prior):
    """`prior` is {"decision_time_utc", "growth_thesis": [claims], "risks": [claims]} of the prior run (claims as stored, with support)."""
    pts = prior_points(prior)
    after = effective_after(packet, prior["decision_time_utc"])
    points = "\n".join(f"{pid}: {c.get('claim')} (cited {', '.join(c.get('fact_ids') or []) or 'nothing'}; code check: "
                       f"{c.get('support')})" for pid, c in pts) or "none"
    # str.replace, not str.format: the JSON shape holds braces; the model-written points go in last so nothing in them is replaced
    return (THESIS_CHANGE_INSTRUCTION.replace("{prior_t}", str(prior["decision_time_utc"]))
            .replace("{after_ids}", ", ".join(after) or "none").replace("{points}", points))


def instruction(task, packet, prior=None):
    if task == "thesis_change":
        if prior is None:
            raise ValueError("thesis_change needs a prior run")
        return thesis_change_instruction(packet, prior)
    return INSTRUCTIONS[task]


def messages(task, packet, prior=None, retry=False):
    """The /api/chat messages of one task: [system, user]. A malformed-retry appends RETRY_LINE to the user message."""
    user = render_packet(packet) + "\n\n" + instruction(task, packet, prior)
    if retry:
        user += "\n\n" + RETRY_LINE
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]

"""What the model is told (SPEC_m3m_qwen_pipeline.md section 4). The hashes are pinned per PROMPT_VERSION: any change to a text the model
reads fails here until PROMPT_VERSION is bumped and a new pin set is added (a versioned decision, non-negotiable 7)."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from qwen_c import contract, tasks

FIX = Path(__file__).resolve().parent / "fixtures_b"
PACKET = json.loads((FIX / "packet_acme.json").read_text(encoding="utf-8"))

PINS = {
    "m3m.prompt.v1": {
        "SYSTEM": "2b9d6a8a29a237bfa2ae255823d7ae97bd4a75dda0da1f49eb7ab74526a0cd6e",
        "business_model": "428f45d0ba1e79b7e21c4e0ddfa4c1def70a7e29ecf045ab686447b7594ab692",
        "financial_health": "608cb7d45015652566443a382456fd0af335288c0a36574f824519de02b6c004",
        "competitive_position": "a7704a274a6e9b48c990c6464b86d5d1e6938d13d253f17b9ad7dd6c50b25be4",
        "growth_thesis": "d40fb8b51c9b3f38c979827c3ddf7c63a95c5dc07133fd883601d64ac20ccd60",
        "risks": "0b35f6a7ededdd8afcb11153145352b04f70f1ca0e4b1a2ace6a3c8cc45383fd",
        # re-pinned under WO_M4 (rulings 3.4, 4.4, 6.1a, 6.1c): no run has used m3m.prompt.v1 yet, so it stays v1 (CROSS_CHECK_M_RULINGS)
        "thesis_change": "2bef986503b497d7d0ff42af2fdb7a5c1538642d5c9949fe4919c5507fb209fc",
        "LEFT_OUT_LINE": "a83e279e9e9f3a1dbd33b7c1ac0d754c17558ed34d66d7cc9c99a9e40682b486",
        "MISSING_LINE": "d7c0c3712d8caefada183363178426420ce134a605ae3a98fd1066e8151189d8",
        "unresolved_questions": "e765b84fc9b8440e9f35f8047bafcb8902b6d370fa63740fade45dca6ba29592",
        "RETRY_LINE": "3eeee83f99a03448e76e788cb45399bb29d709a3ab286c28939dc1ccf8e1c82e",
        "render_packet(packet_acme)": "e6e68066bd678022adbe96f2992914f0a3d4f232ec9b1532898dd81062fee2dd",
    },
}


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def current():
    out = {"SYSTEM": h(tasks.SYSTEM), "RETRY_LINE": h(tasks.RETRY_LINE), "thesis_change": h(tasks.THESIS_CHANGE_INSTRUCTION),
           "LEFT_OUT_LINE": h(tasks.LEFT_OUT_LINE), "MISSING_LINE": h(tasks.MISSING_LINE),
           "render_packet(packet_acme)": h(tasks.render_packet(PACKET))}
    out.update({k: h(v) for k, v in tasks.INSTRUCTIONS.items()})
    return out


def test_prompt_version_and_pinned_hashes():
    assert tasks.PROMPT_VERSION == "m3m.prompt.v1"
    assert tasks.PROMPT_VERSION in PINS, "a new PROMPT_VERSION needs its own pin set"
    assert current() == PINS[tasks.PROMPT_VERSION], "what the model is told changed: bump PROMPT_VERSION and add a pin set"


def test_the_system_text_is_at_most_400_words_and_covers_the_spec_points():
    assert len(tasks.SYSTEM.split()) <= 400
    for word in ("CUTOFF", "after T", "fact_ids", "copied exactly", "numbers", "unknowns", "```json"):
        assert word in tasks.SYSTEM


BANNED = re.compile(r"\b(buy|sell|selling|buying|valuation|intrinsic|dcf|price target|target price|investment committee|underwrit\w*|"
                    r"overweight|underweight|conviction|upside|downside|undervalued|overvalued)\b", re.I)


@pytest.mark.parametrize("name", ["SYSTEM", *tasks.INSTRUCTIONS, "thesis_change", "LEFT_OUT_LINE", "MISSING_LINE"])
def test_no_valuation_or_trading_vocabulary(name):
    text = {"SYSTEM": tasks.SYSTEM, "thesis_change": tasks.THESIS_CHANGE_INSTRUCTION, "LEFT_OUT_LINE": tasks.LEFT_OUT_LINE,
            "MISSING_LINE": tasks.MISSING_LINE}.get(name) or tasks.INSTRUCTIONS[name]
    assert not BANNED.search(text), BANNED.search(text)


def _shape_of(text):
    (block,) = re.findall(r"```json\n(.*?)\n```", text, re.S)
    return json.loads(block)


@pytest.mark.parametrize("task", [t for t in tasks.TASKS])
def test_each_instruction_states_the_exact_shape_the_contract_owns(task):
    text = tasks.THESIS_CHANGE_INSTRUCTION if task == "thesis_change" else tasks.INSTRUCTIONS[task]
    assert text.startswith(f"TASK {task}. ")
    shape = _shape_of(text)
    assert set(shape) == set(contract.TASK_FIELDS) and shape["task"] == task
    (claim,) = shape["claims"]
    want = set(contract.CLAIM_REQUIRED) | set(contract.CLAIM_OPTIONAL) | set(contract.TASK_EXTRA.get(task, {}))
    assert set(claim) == want
    for f in contract.CLAIM_OPTIONAL:
        assert claim[f].startswith("optional")


def test_the_task_list_is_the_contracts():
    assert tasks.TASKS == contract.TASK_IDS
    assert set(tasks.INSTRUCTIONS) == set(tasks.TASKS) - {"thesis_change"}


def test_the_risk_types_in_the_instruction_are_the_contracts():
    listed = re.search(r'"risk_type" is one of: ([a-z_, ]+)\.', tasks.INSTRUCTIONS["risks"]).group(1)
    assert tuple(x.strip() for x in listed.split(",")) == contract.RISK_TYPES


def test_the_message_layout_is_system_then_packet_then_instruction():
    m = tasks.messages("risks", PACKET)
    assert [x["role"] for x in m] == ["system", "user"] and m[0]["content"] == tasks.SYSTEM
    user = m[1]["content"]
    assert user.startswith(tasks.render_packet(PACKET)) and user.endswith(tasks.INSTRUCTIONS["risks"])
    r = tasks.messages("risks", PACKET, retry=True)[1]["content"]
    assert r == user + "\n\n" + tasks.RETRY_LINE
    prefixes = {tasks.messages(t, PACKET)[1]["content"][:len(tasks.render_packet(PACKET))] for t in tasks.INSTRUCTIONS}
    assert len(prefixes) == 1


def test_the_packet_rendering():
    text = tasks.render_packet(PACKET)
    assert text.startswith("DECISION TIME T: 2026-10-29T13:00:00Z\nCOMPANY: ticker ACME, SEC CIK 0000123456\nEVIDENCE ITEMS: 4\n"
                           "NOT IN THIS PACKET (looked for in the filings and not found):\n"
                           "- section_not_found: risk_factors 0000123456-26-000010\n\n[S0] ")
    assert ("[S0] kind: screener_row | title: not stated | form: not stated | period: not stated | effective: not stated | "
            "source: screener git ") in text
    assert "revenue_growth_yoy: 0" in text                                   # a zero stays a value
    assert ("[F1] kind: statement | title: not stated | form: 10-K | period: 2025-12-31 | effective: 2026-02-20T14:30:00Z | "
            "source: SEC accession 0000123456-26-000010, https://www.sec.gov/") in text
    for e in PACKET["evidence"]:
        assert e["text"] in text                                             # verbatim
    assert "0000123456-26-000044" not in text and "excluded" not in text     # excluded is never shown


def test_not_in_this_packet_lists_only_the_missing_kinds_and_never_excluded():
    pk = {**PACKET, "annotations": ["no_eligible_filing: quarterly (10-Q after the annual report in the recent submissions)",
                                    "statement_not_found: cash_flows 0000123456-26-000010", "release_stale: 0000123456-26-000031",
                                    "section_not_found: mdna 0000123456-26-000010", "something_else: x"]}
    text = tasks.render_packet(pk)
    head = text.split("\n[S0] ")[0]
    assert ("NOT IN THIS PACKET (looked for in the filings and not found):\n"
            "- no_eligible_filing: quarterly (10-Q after the annual report in the recent submissions)\n"
            "- statement_not_found: cash_flows 0000123456-26-000010\n- release_stale: 0000123456-26-000031\n"
            "- section_not_found: mdna 0000123456-26-000010\n") in head               # audit 2026-10-29: release_stale is shown
    assert "something_else" not in text and "0000123456-26-000044" not in text
    assert "NOT IN THIS PACKET (looked for in the filings and not found): none\n" in tasks.render_packet({**PACKET, "annotations": []})


def test_the_item_header_carries_the_title():
    e = {"fact_id": "P4", "kind": "other_8k", "title": "8-K Items 1.01, 1.02, 2.03, 9.01", "form": "8-K", "period": None,
         "effective_at": "2026-08-01T13:30:00Z", "source": {"accession": "0000950157-26-000888", "url": "u"}, "text": "body"}
    assert tasks.render_item(e).startswith("[P4] kind: other_8k | title: 8-K Items 1.01, 1.02, 2.03, 9.01 | form: 8-K | ")


def test_thesis_change_instruction_lists_the_prior_points_and_the_newer_items():
    prior = {"decision_time_utc": "2026-05-01T13:00:00Z", "tasks_used": ["growth_thesis", "risks"],
             "growth_thesis": [{"claim": "Backlog {grows}.", "fact_ids": ["P1"], "support": "supported"}],
             "risks": [{"claim": "Losses.", "fact_ids": [], "support": "no_citation"},
                       {"claim": "Debt {n}.", "fact_ids": ["F1"], "support": "supported"}]}
    text = tasks.instruction("thesis_change", PACKET, prior)
    assert "as of 2026-05-01T13:00:00Z" in text and "effective after 2026-05-01T13:00:00Z: P2." in text
    # ruling 3.4: only supported earlier claims are points (an id keeps its stored position), and the count left out is stated
    assert "EARLIER POINTS:\nG1: Backlog {grows}. (cited P1; code check: supported)\nR2: Debt {n}. (cited F1; code check: supported)\n" in text
    assert "Losses." not in text and "R1:" not in text and "did not finish" not in text
    assert ("made the points listed below. Only its points that passed the code check are listed; 1 that did not pass it are left "
            "out. Compare each point") in text
    assert [p for p, _ in tasks.prior_points(prior)] == ["G1", "R2"] and tasks.prior_left_out(prior) == 1
    # ruling 4.4: an earlier task that is not ok is named in the instruction
    text = tasks.instruction("thesis_change", PACKET, {**prior, "tasks_used": ["growth_thesis"], "risks": []})
    assert "The earlier risks task did not finish, so no points come from it. Only its points" in text and "; 0 that did not" in text
    assert _shape_of(text)["task"] == "thesis_change"
    assert tasks.effective_after(PACKET, "2026-10-01T00:00:00Z") == []
    assert tasks.effective_after(PACKET, "not a time") == []
    with pytest.raises(ValueError):
        tasks.instruction("thesis_change", PACKET, None)

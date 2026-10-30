"""Financial GPU smoke (CTBI, 2026-10-31): S1 a year written as the prompt now asks passes the contract, a bare-adjective year does
not; S2 a failing reason's why names the failing figure."""
from qwen_c import contract
from qwen_c.value import checks, task

Y = "Filed annual record, fiscal year ended 2025-12-31 (10-K, accession 0000000000-26-000001): return on opening equity 12.9%."


def claim(text):
    return {"claim": text, "fact_ids": ["Y"], "quotes": ["return on opening equity 12.9%"], "numbers": ["12.9%"]}


def test_S1_a_year_after_a_year_word_passes_and_a_bare_one_does_not():
    assert contract.check_claim(claim("In fiscal 2025 the filed return on opening equity was 12.9%."), {"Y": Y}, "T", set())["support"] \
        == contract.SUPPORTED
    assert contract.check_claim(claim("The 2025 filed return on opening equity was 12.9%."), {"Y": Y}, "T", set())["support"] \
        == "number_not_listed"


def test_S1_both_prompts_say_how_to_write_a_year():
    assert task.VALUATION_PROMPT_VERSION == "m3q.prompt.v7" and task.VALUATION_PROMPT_FIN_VERSION == "m3q.prompt.fin.v5"
    src = open(task.__file__, encoding="utf-8").read()
    assert src.count("never as a bare adjective") == 2


def test_S2_why_names_the_failing_figure():
    out = {"reasons": [{"input": "base.roe", "claim": "The 2025 filed return on opening equity was 12.9%.", "fact_ids": ["Y"],
                        "quotes": ["return on opening equity 12.9%"], "numbers": ["12.9%"]}]}
    items = {"Y": {"fact_id": "Y", "kind": "filed_record", "period": "2025-12-31", "text": Y}}
    got = checks.reasons_by_input(out, items, "T", set(), route="financial")
    assert got[("base", "roe")][0]["why"] .startswith("contract: number_not_listed (2025): list it")

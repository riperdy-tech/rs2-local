"""Financial GPU smoke (CTBI, 2026-10-31): S1 the contract still reads a year written after a year word (contract.py stays for the
formation tasks); on prompt v8 / fin.v6 the model writes no figures, so neither prompt carries the year-writing rule any more; S2 a
reply error names what it fails."""
from qwen_c import contract
from qwen_c.value import checks, task
from qwen_c.tests import test_value_fin as FIN

Y = "Filed annual record, fiscal year ended 2025-12-31 (10-K, accession 0000000000-26-000001): return on opening equity 12.9%."


def claim(text):
    return {"claim": text, "fact_ids": ["Y"], "quotes": ["return on opening equity 12.9%"], "numbers": ["12.9%"]}


def test_S1_the_contract_still_reads_a_year_after_a_year_word():
    assert contract.check_claim(claim("In fiscal 2025 the filed return on opening equity was 12.9%."), {"Y": Y}, "T", set())["support"] \
        == contract.SUPPORTED
    assert contract.check_claim(claim("The 2025 filed return on opening equity was 12.9%."), {"Y": Y}, "T", set())["support"] \
        == "number_not_listed"


def test_S1_neither_prompt_asks_for_written_figures():
    assert task.VALUATION_PROMPT_VERSION == "m3q.prompt.v10" and task.VALUATION_PROMPT_FIN_VERSION == "m3q.prompt.fin.v7"
    src = open(task.__file__, encoding="utf-8").read()
    assert "never as a bare adjective" not in src and "single quote" not in src


def test_S2_a_reply_error_names_what_it_fails():
    b, bar, ids = FIN.ctx_of()
    out = FIN.depart(FIN.clean(), "roe.y1", "last", "record_persistence", ["Y2025-12-31", "X1.s9"])
    errors = checks.check(out, ids, b, bar, FIN.R, FIN.ENDS, route="financial")["errors"]
    assert errors == {"roe.y1": ["evidence IDs that do not exist: ['X1.s9']"]}

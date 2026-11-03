"""SPEC_m3q §2 / WO_Q5b / F_SPEC_valuation_menu §1-§2 (F2): what the model is told for valuation_inputs (prompt v8). The formation tasks'
texts must not move."""
import hashlib
import json
import re

from qwen_c import tasks
from qwen_c.value import checks, menu, task
from qwen_c.tests import test_value_checks as OP

PINNED = "553705b3b86ececed67c589d20168bf7cdf3529c3aab269811dc84a3dbc12918"   # m3q.prompt.v9
V7_INSTRUCTION_CHARS = 4065                                                     # m3q.prompt.v7's INSTRUCTION, shape included


def _base_args():
    b, bar, _ = OP.ctx_of()
    prov = {"rf": 0.0505, "g_anchor": 0.03, "loading_adjusted": 1.25, "closure_erp": 0.0417}
    return b, bar, OP.R, prov


def test_system_is_the_shared_text_and_the_formation_tasks_are_untouched():
    assert "valuation_inputs" not in tasks.TASKS
    assert tasks.PROMPT_VERSION == "m3m.prompt.v3"
    msgs = task.messages({"evidence": []}, [], *_base_args())
    assert msgs[0]["content"] is tasks.SYSTEM


def test_the_instruction_is_at_most_half_of_v7_and_names_no_figure_rules():
    assert task.VALUATION_PROMPT_VERSION == "m3q.prompt.v9" and len(task.INSTRUCTION) <= V7_INSTRUCTION_CHARS / 2
    for gone in ("quote", "bare adjective", "figures a cited item prints", "prob"):
        assert gone not in task.INSTRUCTION


def test_the_example_shape_in_the_prompt_passes_the_reply_rules():
    example = json.loads(re.search(r"```json\n(.*)\n```", task.INSTRUCTION, re.S).group(1))
    b, bar, ids = OP.ctx_of()
    ids = dict(ids, **{"P4.s17": {"fact_id": "P4", "kind": "release", "period": "2026-02-01", "text": "Revenue grows 5%.", "sentence": True}})
    res = checks.check(example, ids, b, bar, OP.R, OP.ENDS)
    assert res["status"] == "ok" and res["numbers"]["rev_growth.y1"] == 0.05, res.get("errors")


def test_user_message_carries_markers_the_record_and_the_menu_then_the_task_last():
    rec = [{"fact_id": "Y2025-12-31", "text": "Filed annual record, fiscal year ended 2025-12-31: revenue $100.0 million."}]
    pk = {"evidence": [{"fact_id": "P4", "kind": "release", "text": "Revenue rose. Margins held."},
                       {"fact_id": "F1", "kind": "statement", "text": "Revenue | 100"}]}
    msg = task.messages(pk, rec, *_base_args())[1]["content"]
    assert "<1> Revenue rose. <2> Margins held." in msg and "Revenue | 100" in msg and "<1> Revenue | 100" not in msg
    assert "[Y2025-12-31] Filed annual record" in msg and "[V0] Measured by code" in msg and "Cost of equity 0.0900" in msg
    assert "terminal_ronic (return on new capital in the long run): no_growth_value 0.0790; quarter" in msg
    assert "terminal_g: anchor 0.0300; half_anchor 0.0150; zero 0.0000; decline not available" in msg
    assert msg.rstrip().endswith("```") and msg.index("MENU") < msg.index("TASK valuation_inputs")


def test_every_option_of_the_menu_is_printed():
    b, bar, r, prov = _base_args()
    text = task.render_base(b, bar, r, prov)
    m = menu.menus(b, bar, r, "operating")
    for kind in ("growth", "margin", "ronic", "terminal_g", "capex"):
        for k in m[kind]:
            assert f" {k} " in text, (kind, k)
    assert ", ".join(menu.DRIVERS) in text and ", ".join(menu.KEYS["operating"]) in text


def _fixed_message():
    pk = {"ticker": "T", "decision_time_utc": "2026-10-30T13:00:00Z", "cik": "1",
          "evidence": [{"fact_id": "S0", "kind": "screener_row",
                        "text": "\n".join(["symbol: T", "price: 12.5", "marketCap: 1000", "price as-of (Last_Updated, zone not stated): x",
                                           "sector: Tech"])},
                       {"fact_id": "P1", "kind": "annual_section", "period": "2025-12-31", "text": "We sell widgets. Demand grew 4%."}]}
    rec = [{"fact_id": "Y2025-12-31", "text": "Filed annual record, fiscal year ended 2025-12-31: revenue $100.0 million."}]
    return task.user_message(pk, rec, *_base_args())


def test_price_blind_masks_the_screener_row():
    msg = _fixed_message()
    assert "price:" not in msg and "marketCap" not in msg and "price as-of" not in msg and "sector: Tech" in msg


def test_the_whole_user_message_template_is_pinned():
    h = hashlib.sha256("\n".join([task.VALUATION_PROMPT_VERSION, tasks.SYSTEM, _fixed_message()]).encode("utf-8")).hexdigest()
    assert h == PINNED, f"the valuation prompt changed: bump VALUATION_PROMPT_VERSION and re-pin ({h})"


def test_repair_turn_lists_every_reply_error_by_key():
    text = task.compact_failures({"op_margin.y1": ["departs (0.1600 against the neutral 0.1556) and needs a departures entry"],
                                  "uncertain": ["1 to 3 distinct departure keys"]})
    assert text.splitlines() == ["- op_margin.y1: departs (0.1600 against the neutral 0.1556) and needs a departures entry",
                                 "- uncertain: 1 to 3 distinct departure keys"]

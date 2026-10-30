"""SPEC_m3q §2 / WO_Q5b: what the model is told for valuation_inputs. The formation tasks' texts must not move."""
import hashlib
import json
import re

from qwen_c import tasks
from qwen_c.value import checks, task

PINNED = "0bd27bb0d4bd431adfd313f5f15685df1639faa008cca3ef1b5327283273175f"   # m3q.prompt.v6


def test_system_is_the_shared_text_and_the_formation_tasks_are_untouched():
    assert "valuation_inputs" not in tasks.TASKS
    assert tasks.PROMPT_VERSION == "m3m.prompt.v3"
    msgs = task.messages({"evidence": []}, [], *_base_args())
    assert msgs[0]["content"] is tasks.SYSTEM


def _base_args():
    b = {"fy0": "2025-12-31", "R0": 100.0, "tau": 0.2, "ronic0": 0.18, "c_ratio": 0.06, "d_ratio": 0.04}
    bar = {"min": 0.15, "p25": 0.152, "median": 0.155, "p75": 0.158, "max": 0.16, "last": 0.16}
    prov = {"rf": 0.0505, "g_anchor": 0.0375, "loading_adjusted": 1.25, "closure_erp": 0.0417}
    return b, bar, 0.1027, prov


def test_the_example_shape_in_the_prompt_is_itself_valid():
    example = json.loads(re.search(r"```json\n(.*)\n```", task.INSTRUCTION, re.S).group(1))
    assert checks.shape(example, 0.1027) == []


def test_user_message_carries_the_record_and_the_base_then_the_task_last():
    rec = [{"fact_id": "Y2025-12-31", "text": "Filed annual record, fiscal year ended 2025-12-31: revenue $100.0 million."}]
    msg = task.messages({"evidence": []}, rec, *_base_args())[1]["content"]
    assert "[Y2025-12-31] Filed annual record" in msg and "[V0] Measured by code" in msg and "Cost of equity 0.1027" in msg
    assert msg.rstrip().endswith("```")


def _fixed_message():
    pk = {"ticker": "T", "decision_time_utc": "2026-10-30T13:00:00Z", "cik": "1",
          "evidence": [{"fact_id": "S0", "kind": "screener_row",
                        "text": "\n".join(["symbol: T", "price: 12.5", "marketCap: 1000", "price as-of (Last_Updated, zone not stated): x",
                                           "sector: Tech"])}]}
    rec = [{"fact_id": "Y2025-12-31", "text": "Filed annual record, fiscal year ended 2025-12-31: revenue $100.0 million."}]
    return task.user_message(pk, rec, *_base_args())


def test_price_blind_masks_the_screener_row():
    msg = _fixed_message()
    assert "price:" not in msg and "marketCap" not in msg and "price as-of" not in msg and "sector: Tech" in msg


def test_the_whole_user_message_template_is_pinned():
    h = hashlib.sha256("\n".join([task.VALUATION_PROMPT_VERSION, tasks.SYSTEM, _fixed_message()]).encode("utf-8")).hexdigest()
    assert h == PINNED, f"the valuation prompt changed: bump VALUATION_PROMPT_VERSION and re-pin ({h})"

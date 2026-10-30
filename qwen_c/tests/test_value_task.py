"""SPEC_m3q §2 / WO_Q5b: what the model is told for valuation_inputs. The formation tasks' texts must not move."""
import hashlib
import json
import re

from qwen_c import tasks
from qwen_c.value import checks, task

PINNED = "f1fdce12f3e9e9fb2ffa462fdb079d706c0e063043c7ddad2a72013ce0b5c6b5"


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


def test_prompt_text_is_pinned():
    h = hashlib.sha256((task.VALUATION_PROMPT_VERSION + task.INSTRUCTION).encode("utf-8")).hexdigest()
    assert h == PINNED, "the valuation prompt changed: bump VALUATION_PROMPT_VERSION and re-pin"

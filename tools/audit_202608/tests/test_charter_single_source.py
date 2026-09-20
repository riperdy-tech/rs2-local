"""Single-source guard on the underwriting framework prompt.

The cloud arm (`api_llm/api_chat.py`) and the local depth model
(`rs2-analyst-deep-mtp5`, built from `RS2-Analyst-Deep-MTP5.Modelfile`) must send the SAME
framework text. They are two halves of one tier: both write verdicts into
`cache/depth_ledger.jsonl`, differing only in the `arm` field.

Found on 2026-09-20: `api_chat` was sending `RS2.txt` — the retired v2.0 "Integrated Investment
Analysis Engine" — while the local model had already been rebuilt on the v3.0 "Institutional
Equity Underwriting Charter". So for as long as that lasted, local and cloud verdicts in the same
ledger were produced under different definitions of MoS, Kelly, sizing and the memo structure.

The fix is a single source file (`prompts/charter_v3.0.md`). This test is what keeps it single.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[3]          # repo root
sys.path.insert(0, str(HERE / "api_llm"))


def _modelfile_system():
    """The SYSTEM block the live local model was built from, normalized the same way."""
    text = (HERE / "RS2-Analyst-Deep-MTP5.Modelfile").read_text(encoding="utf-8-sig")
    body = text.split('SYSTEM """', 1)[1]
    return body.split('"""', 1)[0].replace("\r\n", "\n").strip("\n")


def test_cloud_arm_sends_the_same_charter_as_the_local_model():
    import api_chat

    assert api_chat._system_prompt().strip() == _modelfile_system()


def test_cloud_arm_carries_v3_and_not_the_retired_v2_framework():
    import api_chat

    prompt = api_chat._system_prompt()
    assert "INSTITUTIONAL EQUITY UNDERWRITING CHARTER v3.0" in prompt
    # The v2.0 engine's header. If this ever reappears, the cloud arm has been pointed back at
    # RS2.txt and the two halves of the tier disagree again.
    assert "INTEGRATED INVESTMENT ANALYSIS ENGINE" not in prompt


def test_cloud_deep_arm_reads_the_charter_not_a_retired_modelfile():
    """The deep API arm is the other half of the cloud tier, and it was missed.

    `deep_api_run.py` extracted the framework from `RS2-Analyst-Deep.Modelfile`'s SYSTEM block.
    That file was archived on 2026-09-20, so `_rs2_framework()` - called on every request at
    :191, and reached in production through `cloud_backstop.py:197` - raised FileNotFoundError.
    Nothing caught it: no test imported this module, and the census that cleared the archival
    only inspected .py imports. A DATA PATH IS NOT AN IMPORT.
    """
    import deep_api_run

    assert deep_api_run.CHARTER == HERE / "prompts" / "charter_v3.0.md"
    assert deep_api_run.CHARTER.exists(), (
        "prompts/charter_v3.0.md is missing - the cloud deep arm cannot run without it.")


def test_cloud_deep_arm_sends_the_same_charter_as_the_local_model():
    import deep_api_run

    assert deep_api_run._rs2_framework().strip() == _modelfile_system()


def test_cloud_deep_arm_carries_v3_and_not_the_retired_v2_framework():
    import deep_api_run

    prompt = deep_api_run._rs2_framework()
    assert "INSTITUTIONAL EQUITY UNDERWRITING CHARTER v3.0" in prompt
    assert "INTEGRATED INVESTMENT ANALYSIS ENGINE" not in prompt


def test_cloud_arm_reads_the_single_source_file_not_rs2_txt():
    """Pin the SOURCE rather than scanning the file text.

    A text scan is the wrong instrument here: the module docstring legitimately names RS2.txt to
    record why it was replaced, so `"RS2.txt" not in source` fails on the explanation rather than
    on the behaviour. Asserting the resolved path is precise and still catches a revert.
    """
    import api_chat

    assert api_chat.CHARTER == HERE / "prompts" / "charter_v3.0.md"
    assert api_chat.CHARTER.exists(), (
        "prompts/charter_v3.0.md is missing — regenerate it with scratch/extract_charter.py. "
        "Without it _system_prompt() raises at the first cloud call.")

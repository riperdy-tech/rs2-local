"""2026-09-27: the analyst's processing batch comes from config depth_num_batch (window option A), and
the research helper thinks (operator ruling: "place thinking ON on the research 14B helper")."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_ORIG_STDOUT = sys.stdout
import depth_pipeline as dp  # noqa: E402
import deep_research  # noqa: E402
sys.stdout = _ORIG_STDOUT

ROOT = Path(__file__).resolve().parents[1]


def test_config_pins_the_batch_and_the_research_window():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert cfg["depth_num_batch"] == 256 and cfg["depth_ctx"] == 98304
    assert cfg["research_ctx"] == 32768


def test_run_consensus_passes_the_batch(monkeypatch):
    seen = {}

    class _Stop(Exception):
        pass

    def fake_run(cmd, *a, **k):
        seen["cmd"] = cmd
        raise _Stop

    monkeypatch.setattr(dp.subprocess, "run", fake_run)
    monkeypatch.setattr(dp, "NUM_BATCH", 256)
    try:
        dp.run_consensus("TEST", samples=2)
    except _Stop:
        pass
    cmd = seen["cmd"]
    assert cmd[cmd.index("--num-batch") + 1] == "256"


def test_the_research_helper_thinks():
    o = deep_research.ldr_overrides("searxng")
    assert o["llm.ollama.enable_thinking"] is True
    assert o["llm.local_context_window_size"] == 32768

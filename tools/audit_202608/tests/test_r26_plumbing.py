"""Brief R26-A1: the arm r26 is reached from consensus_valuation.main() when the pack's facts say pilot_arm == "r26"; every other arm still goes to chat_with_tools."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import r26_stages  # noqa: E402


def _frozen_pack(tmp_path, monkeypatch, arm):
    pack = tmp_path / "frozen_pack.md"
    pack.write_text(str(cv.cap.build_pack("GEV")) + "\n\n---\n\nYou are underwriting this company for real money. TASK.\n", encoding="utf-8")
    real = cv.pack_facts.from_text

    def with_arm(text):
        f = dict(real(text))
        f["pilot_arm"] = arm
        return f

    monkeypatch.setattr(cv.pack_facts, "from_text", with_arm)
    return pack


def test_pilot_arm_r26_runs_the_staged_analyst_not_chat_with_tools(monkeypatch, tmp_path, screener_data_stub):
    pack = _frozen_pack(tmp_path, monkeypatch, "r26")
    seen = {}

    def run_sample(model, pack_text, run_dir, **kw):
        seen.update(model=model, pack=pack_text, run_dir=Path(run_dir), **kw)
        return "", "", {}

    def boom(*a, **k):
        raise AssertionError("chat_with_tools must not run for arm r26")

    monkeypatch.setattr(r26_stages, "run_sample", run_sample)
    monkeypatch.setattr(at, "chat_with_tools", boom)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--price", "100", "--samples", "1", "--no-early-stop", "--tools",
                                      "--pack-file", str(pack), "--out-dir", str(out), "--seed-base", "40"])
    cv.main()
    (d,) = list(out.glob("GEV_*"))
    assert seen["run_dir"] == d / "sample1_research" and seen["seed"] == 41 and seen["ticker"] == "GEV" and seen["think"] == "high"
    assert seen["pack"] == pack.read_text(encoding="utf-8")
    # stages 2-4 (brief R26-A2) are handed the code-owned inputs: the pack facts, the harness price and the desk context
    assert seen["price"] == 100.0 and seen["facts"]["pilot_arm"] == "r26" and "long_run" in seen["facts"] and seen["desk_context"]["price"] == 100.0


def test_arm_r26_without_tools_is_refused(monkeypatch, tmp_path, screener_data_stub):
    pack = _frozen_pack(tmp_path, monkeypatch, "r26")
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--price", "100", "--samples", "1", "--pack-file", str(pack), "--out-dir", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as e:
        cv.main()
    assert e.value.code == 2

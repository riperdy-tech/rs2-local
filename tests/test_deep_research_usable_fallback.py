"""run_topic falls back to the next backend when the first one leaves no USABLE sources (2026-10-21: all-low-trust or
uncited SearXNG answers ended the chain and the keyed providers were never tried)."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deep_research as dr  # noqa: E402


def _run(monkeypatch, answers):
    calls = []
    ldr = types.ModuleType("local_deep_research")
    api = types.ModuleType("local_deep_research.api")

    def quick_summary(query, settings_override=None):
        tool = next(t for t in answers if settings_override and settings_override.get("_tool") == t)
        calls.append(tool)
        return answers[tool]
    api.quick_summary = quick_summary
    ldr.api = api
    monkeypatch.setitem(sys.modules, "local_deep_research", ldr)
    monkeypatch.setitem(sys.modules, "local_deep_research.api", api)
    monkeypatch.setattr(dr, "tool_chain", lambda: list(answers))
    monkeypatch.setattr(dr, "ldr_overrides", lambda tool: {"_tool": tool})
    monkeypatch.setattr(dr.quota, "bump", lambda *a, **k: None)
    monkeypatch.setattr(dr, "drop_low_trust", lambda urls: ([u for u in urls if "lowtrust" not in u], [u for u in urls if "lowtrust" in u]))
    monkeypatch.setattr(dr, "numbered_sources", lambda res: [])
    return dr.run_topic("q"), calls


def test_low_trust_only_answer_falls_back_to_the_keyed_provider(monkeypatch):
    answers = {"searxng": {"summary": "prose", "sources": [{"url": "https://lowtrust.example/a"}]},
               "tavily": {"summary": "prose", "sources": [{"url": "https://reuters.com/x"}]}}
    (tool, res, urls), calls = _run(monkeypatch, answers)
    assert calls == ["searxng", "tavily"] and tool == "tavily" and urls == ["https://reuters.com/x"]


def test_a_usable_first_answer_does_not_spend_the_keyed_provider(monkeypatch):
    answers = {"searxng": {"summary": "prose", "sources": [{"url": "https://reuters.com/x"}]},
               "tavily": {"summary": "prose", "sources": [{"url": "https://ft.com/y"}]}}
    (tool, res, urls), calls = _run(monkeypatch, answers)
    assert calls == ["searxng"] and tool == "searxng"

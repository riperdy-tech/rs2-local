"""deep_research must resolve its output directory through paths.load_config().

Regression for 2026-09-24: the module read config.json raw, where out_research_dir has been null
since the 2026-09-22 path reorganisation, so every brief build crashed at Path(None).
"""
import deep_research


def test_out_research_dir_is_resolved():
    assert deep_research.CONFIG.get("out_research_dir")
    assert str(deep_research.CONFIG["out_research_dir"]).endswith("research")

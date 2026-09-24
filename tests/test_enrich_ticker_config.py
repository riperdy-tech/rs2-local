"""enrich_ticker must resolve its output directory through paths.load_config().

Regression for 2026-09-24: the module read config.json raw, where out_enrich_dir has been null
since the 2026-09-22 path reorganisation, so every CLI run crashed at Path(None).
"""
import enrich_ticker


def test_out_enrich_dir_is_resolved():
    assert enrich_ticker.CONFIG.get("out_enrich_dir")
    assert str(enrich_ticker.CONFIG["out_enrich_dir"]).endswith("enrich")

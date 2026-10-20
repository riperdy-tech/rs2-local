"""The stage-1 fact checks hold memory proportional to the page they read, never more (the 2026-10-20 LPG stop: a MemoryError on a run whose process was reported at 23 GB).
The replay of the recorded LPG, HNRG and PTCT sessions through run_stage1 stays under 45 MB; this test pins the per-fact step on a large synthetic page."""
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import r26_stages as rs  # noqa: E402

PAGE_CHARS = 200_000
PEAK_BOUND = 64 * 2 ** 20           # 64 MB for a 200 K character page (measured about 7 MB; 1.5 M characters, the fetch cap, measured 50 MB)
ROW = "| Operating income | 12.5 | 13.1 | 14.0 |\n"


def _ledger():
    page = "| Item | 2024 | 2025 | 2026 |\n|---|---|---|---|\n" + ROW * (PAGE_CHARS // len(ROW))
    url = "http://example.test/10k"
    ev = rs.Evidence("# pack\n", {url: {"url": url, "full_text": page, "text": page[:9000]}})
    ev.fetched[url] = url
    return rs.Ledger(ev, "Acme Corp", "ACME"), url


def _fact(i, url, quote):
    return {"fact_id": f"F{i}", "source": f"page:{url}", "quote": quote, "entity": "Acme", "metric": "operating income", "period": "2025", "value": 12.5, "unit": "USD m",
            "basis": "filed_gaap", "duration_years": None}


def test_registering_facts_against_a_large_page_holds_memory_proportional_to_the_page():
    led, url = _ledger()
    tracemalloc.start()
    try:
        led.register({"facts": [_fact(1, url, ROW.strip()), _fact(2, url, "Operating income | 12.5"), _fact(3, url, "no such quote anywhere in the page")]})
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [f["quote_status"] for f in (x["statuses"] for x in led.facts)] == ["quote_verified", "quote_verified", "quote_not_found"]
    assert peak < PEAK_BOUND, f"peak {peak / 2 ** 20:.0f} MB for a {PAGE_CHARS}-character page"

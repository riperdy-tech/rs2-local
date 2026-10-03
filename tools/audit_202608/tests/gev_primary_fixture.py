"""Revision 21: GEV's real filings for the tests that build the GEV fixture pack byte for byte.

fixture_data/sec_primary holds the per-accession cache (sec_primary's own format) of the three GEV filings the PRIMARY SOURCES section reads at the frozen date
2026-09-27 (the 8-K Item 2.02 of 2026-07-22 with its exhibits, the 10-Q of the same day with its segment report, the 8-K Item 5.02 of 2026-08-27) and the
submissions list. `install` points sec_primary at them: no request is made and nothing is written."""
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fixture_data" / "sec_primary"


def install(monkeypatch):
    import sec_primary
    monkeypatch.setattr(sec_primary, "CACHE", DIR)
    monkeypatch.setattr(sec_primary, "_subs", lambda cik: json.loads((DIR / "GEV_submissions.json").read_text(encoding="utf-8")))

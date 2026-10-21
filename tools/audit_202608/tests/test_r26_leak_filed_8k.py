"""Revision 26, P5 leak audit, coordinator rulings of 2026-10-21 (DAR, VSNT): (1) a number in the company's own 8-K Item 2.02 earnings release of the trailing year,
fetched from EDGAR, is filed support, so company guidance that the consensus follows is a listed exception, not a leak; (2) a removed fact that is a dollar amount is
never matched as a percent or a multiple."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE), str(HERE.parent.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import r26_blind as rb  # noqa: E402
import sec_guidance  # noqa: E402

RELEASE = "2026 Financial Outlook The Company raised its full-year 2026 outlook: Total Revenue of $6.2 billion to $6.45 billion"


def _audit(blind, removed_lines=(), facts=None, filed_8k=None):
    n = len(blind.split("\n"))
    f = dict(facts or {})
    f["r26_blind_source"] = {"removed_lines": [{"cls": "consensus", "section": "DATA 8 - CONSENSUS & MULTIPLES", "text": t} for t in removed_lines],
                             "spans": [{"start": 0, "end": n, "cls": "narrative", "section": "CATALYST BRIEF"}]}
    if filed_8k is not None:
        f["r26_blind_source"]["filed_8k"] = filed_8k
    return rb.r26_leak_audit(blind, f)


BLIND = "# t\n- FY26 guidance raised to revenue $6.2-6.45B"
CONSENSUS = ["| Revenue next FY | $6.249B |"]
CONS_FACTS = {"x_margin_consensus_y1y2": {"y2": {"revenue_b": 6.249}}}


def test_guidance_equal_to_consensus_is_a_leak_without_the_release():
    a = _audit(BLIND, CONSENSUS, CONS_FACTS)
    assert not a["pass"] and a["leaks"][0]["form"] == "6.2"


def test_guidance_in_the_companys_8k_is_a_listed_exception():
    a = _audit(BLIND, CONSENSUS, CONS_FACTS, filed_8k=[{"accession": "0002067876-26-000038", "filing_date": "2026-08-06", "url": "u", "text": RELEASE}])
    assert a["pass"], a["leaks"]
    assert [e["filed_source"] for e in a["exceptions"]] == ["SEC 8-K 0002067876-26-000038 filed 2026-08-06"]


def test_a_consensus_number_absent_from_the_release_still_leaks():
    a = _audit("# t\n- revenue next year near $6.3B", ["| Revenue next FY | $6.31B |"],
               filed_8k=[{"accession": "a", "filing_date": "2026-08-06", "url": "u", "text": RELEASE}])
    assert not a["pass"] and a["leaks"][0]["form"] == "6.3"


def test_a_percent_does_not_match_a_dollar_amount_fact():
    facts = {"long_run": {"oe_path": [1.22, 1.10, 1.14, 1.18, 1.22]}}
    a = _audit("# t\n- Institutional ownership: 107.76%   |   insider: 1.18%", facts=facts)
    assert a["pass"], a["leaks"]


def test_a_dollar_amount_fact_still_matches_a_dollar_amount():
    facts = {"long_run": {"oe_path": [1.22, 1.10, 1.14, 1.18, 1.22]}}
    a = _audit("# t\n- owner earnings reach $1.18B in year 4", facts=facts)
    assert not a["pass"] and a["leaks"][0]["matches"] == ["fact:long_run.oe_path[3]"]


def test_a_margin_fact_still_matches_as_a_percent():
    a = _audit("# t\n- the margin settles near 15.5%", facts={"long_run": {"m5": 0.155387}})
    assert not a["pass"]


def test_earnings_releases_walks_back_through_the_trailing_year(monkeypatch):
    filings = {"2026-08-06": "a3", "2026-05-07": "a2", "2026-02-20": "a1", "2025-08-01": "a0"}

    def fake(cik, asof=None):
        cands = sorted((d for d in filings if d <= asof), reverse=True)
        return {"accession": filings[cands[0]], "filing_date": cands[0], "url": "u", "text": "t"} if cands else None

    monkeypatch.setattr(sec_guidance, "latest_earnings_release", fake)
    got = sec_guidance.earnings_releases("1", asof="2026-10-21")
    assert [r["filing_date"] for r in got] == ["2026-08-06", "2026-05-07", "2026-02-20"]
    assert [r["filing_date"] for r in sec_guidance.earnings_releases("1", asof="2026-10-21", limit=2)] == ["2026-08-06", "2026-05-07"]

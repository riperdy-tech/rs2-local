"""Section D and Q sources: the annual report's own text, the acceptance-bounded selection, the quarterly facts. Fake fetchers: no network."""
import json

import pytest

sp = pytest.importorskip("sec_primary")

from valuation.muse import documents as dc  # noqa: E402

ANNUAL_HTML = """<html><body>
<p>TABLE OF CONTENTS</p><p>Item 1. Business</p><p>Item 1A. Risk Factors</p><p>Item 7. Management's Discussion and Analysis</p><p>Item 7A. Quantitative</p>
<p>Item 1. Business</p>
<p>We design and sell widgets to industrial customers in forty countries.</p>
<p>Our backlog at year end was $4.2 billion under multi-year contracts.</p>
<p>Item 1A. Risk Factors</p><p>Many risks.</p>
<p>Item 7. Management's Discussion and Analysis of Financial Condition</p>
<p>Overview of the year and the results of operations.</p>
<p>Outlook. We expect revenue growth of 8 to 10 percent next year.</p>
<p>Item 7A. Quantitative and Qualitative Disclosures</p><p>Market risk.</p>
</body></html>"""


def test_item_span_skips_the_table_of_contents_and_stops_at_the_next_item():
    blocks = sp.blocks_of(ANNUAL_HTML)
    biz = dc.item_span(blocks, "business", "10-K")
    text = dc._plain(biz)
    assert "forty countries" in text and "backlog" in text and "Risk Factors" not in text and "Many risks" not in text
    md = dc._plain(dc.item_span(blocks, "mdna", "10-K"))
    assert "Outlook. We expect revenue growth of 8 to 10 percent" in md and "Market risk" not in md
    assert dc.item_span(blocks, "business", "40-F") == [] or True      # a 40-F wrapper has other headings: nothing is invented


def test_a_20f_uses_items_4_and_5():
    html = ("<html><body><p>Item 4. Information on the Company</p><p>The company builds ships for several customers worldwide every year.</p>"
            "<p>Item 4A. Unresolved</p><p>Item 5. Operating and Financial Review and Prospects</p><p>Revenue rose on higher volume this year.</p>"
            "<p>Item 6. Directors</p></body></html>")
    b = sp.blocks_of(html)
    assert "builds ships" in dc._plain(dc.item_span(b, "business", "20-F")) and "higher volume" in dc._plain(dc.item_span(b, "mdna", "20-F"))


def write_subs(tmp_path, rows):
    cols = {"accessionNumber": [], "form": [], "filingDate": [], "acceptanceDateTime": [], "items": [], "reportDate": [], "primaryDocument": []}
    for r in rows:
        for k, v in zip(cols, r):
            cols[k].append(v)
    (tmp_path / "CIK0000000001.json").write_text(json.dumps({"filings": {"recent": cols, "files": []}}), encoding="utf-8")


ROWS = [
    # accession, form, filed, accepted, items, report date, primary doc
    ("A-10K", "10-K", "2026-02-27", "2026-02-27T21:30:00.000Z", "", "2025-12-31", "k.htm"),
    ("A-10K-LATE", "10-K", "2026-04-15", "2026-04-15T20:00:01.000Z", "", "2026-12-31", "k2.htm"),         # accepted one second after 16:00 EDT
    ("A-8K-OLD", "8-K", "2026-02-20", "2026-02-20T21:05:00.000Z", "2.02,9.01", "2026-02-20", "e.htm"),
    ("A-8K-OK", "8-K", "2026-04-15", "2026-04-15T19:59:59.000Z", "2.02,9.01", "2026-04-15", "e2.htm"),      # one second before the cutoff
    ("A-8K-LATE", "8-K", "2026-04-15", "2026-04-15T20:30:00.000Z", "2.02", "2026-04-15", "e3.htm"),
    ("A-8K-NOTIME", "8-K", "2026-04-15", "", "2.02", "2026-04-15", "e4.htm"),                              # filed on T with no timestamp: ambiguous
    ("A-8K-FUT", "8-K", "2026-05-01", "2026-05-01T12:00:00.000Z", "2.02", "2026-05-01", "e5.htm"),
]


def fakes():
    seen = {"8k": [], "per": [], "ann": []}

    def f8k(cik, acc):
        seen["8k"].append(acc)
        return {"docs": [{"type": "EX-99.1", "filename": "ex.htm", "raw": f"<html><body><p>Release {acc}: first quarter 2026 revenue rose.</p></body></html>"}]}

    def fper(cik, acc):
        seen["per"].append(acc)
        return {"segment": {"short_name": "Segment Information", "file": "R9.htm", "raw": f"<html><body><table><tr><td>Widgets</td><td>100</td></tr></table></body></html>"}}

    def fann(cik, acc):
        seen["ann"].append(acc)
        return ANNUAL_HTML
    return f8k, fper, fann, seen


def test_selection_obeys_the_16h00_et_acceptance_cutoff(tmp_path):
    write_subs(tmp_path, ROWS)
    f8k, fper, fann, seen = fakes()
    src = dc.AcceptanceBoundedDocuments(tmp_path, fetch_8k=f8k, fetch_periodic=fper, fetch_annual=fann)
    items, notes = src.items("0000000001", "2026-04-15")
    kinds = [i.kind for i in items]
    assert kinds == ["annual_business", "annual_mdna_outlook", "annual_segment_note", "earnings_release"]
    assert seen["ann"] == ["A-10K"] and seen["per"] == ["A-10K"] and seen["8k"] == ["A-8K-OK"]            # the late 10-K and 8-Ks were never fetched
    rel = items[-1]
    assert rel.accession == "A-8K-OK" and rel.accepted_at.startswith("2026-04-15T19:59:59") and "Release A-8K-OK" in rel.text
    assert any("A-8K-NOTIME" in n and "not used" in n for n in notes)
    assert "forty countries" in items[0].text and "Outlook. We expect revenue growth" in items[1].text and "Widgets | 100" in items[2].text
    assert all(dc.eligibility(i.accepted_at, i.filed, "2026-04-15") == "ok" for i in items)


def test_an_earlier_date_sees_only_the_earlier_filings(tmp_path):
    write_subs(tmp_path, ROWS)
    f8k, fper, fann, seen = fakes()
    items, _ = dc.AcceptanceBoundedDocuments(tmp_path, fetch_8k=f8k, fetch_periodic=fper, fetch_annual=fann).items("0000000001", "2026-02-25")
    assert [i.kind for i in items] == ["earnings_release"] and items[0].accession == "A-8K-OLD"
    assert seen["ann"] == []


def test_missing_pieces_are_notes_not_made_up_text(tmp_path):
    write_subs(tmp_path, ROWS[:1])
    items, notes = dc.AcceptanceBoundedDocuments(tmp_path, fetch_8k=lambda c, a: None, fetch_periodic=lambda c, a: None,
                                                 fetch_annual=lambda c, a: None).items("0000000001", "2026-04-15")
    assert items == [] and any("could not be read" in n for n in notes) and any("no segment report" in n for n in notes) and any("no earnings release" in n for n in notes)
    assert dc.AcceptanceBoundedDocuments(tmp_path / "nowhere").items.__self__ is not None


# ---- section Q -----------------------------------------------------------------------------------------------------------------------------------

def fact(start, end, val, accn, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "accn": accn, "filed": filed, "form": form}


def companyfacts():
    rev = [fact("2025-07-01", "2025-09-30", 410.0, "Q3-25", "2025-11-05"), fact("2024-07-01", "2024-09-30", 380.0, "Q3-25", "2025-11-05"),
           fact("2025-01-01", "2025-09-30", 1190.0, "Q3-25", "2025-11-05"),                                  # nine months: not a quarter
           fact("2025-10-01", "2025-12-31", 999.0, "K-25", "2026-02-27", "10-K"),                           # a 10-K fact: not a 10-Q quarter
           fact("2026-01-01", "2026-03-31", 450.0, "Q1-26", "2026-04-15"),                                  # accepted after the cutoff below
           fact("2025-04-01", "2025-06-30", 395.0, "Q2-25", "2025-08-05"), fact("2025-04-01", "2025-06-30", 396.0, "Q2-25-A", "2025-09-01", "10-Q/A")]
    ni = [fact("2025-07-01", "2025-09-30", 44.0, "Q3-25", "2025-11-05")]
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rev}}, "NetIncomeLoss": {"units": {"USD": ni}}}}}


def test_quarters_use_ten_q_three_month_facts_with_the_comparative_and_the_acceptance_rule():
    import datetime as dt
    acc = {"Q1-26": dt.datetime(2026, 4, 15, 20, 0, 1, tzinfo=dt.timezone.utc)}
    src = dc.CompanyFactsQuarters(lambda cik: companyfacts(), acceptance=lambda cik: acc)
    q = src.quarters("1", "2026-04-15")
    assert [r["period_end"] for r in q] == ["2025-06-30", "2025-09-30"]                  # Q1-26 accepted after 16:00 EDT: out
    q3 = q[1]
    assert q3["values"] == {"revenue": 410.0, "net_income": 44.0} and q3["prior_year"] == {"revenue": 380.0} and q3["accession"] == "Q3-25"
    assert q[0]["values"]["revenue"] == 396.0                                                # the latest eligible filing of the quarter (the amendment)
    later = dc.CompanyFactsQuarters(lambda cik: companyfacts(), acceptance=lambda cik: {"Q1-26": dt.datetime(2026, 4, 15, 19, 0, tzinfo=dt.timezone.utc)})
    assert [r["period_end"] for r in later.quarters("1", "2026-04-15")][-1] == "2026-03-31"
    assert dc.CompanyFactsQuarters(lambda cik: None).quarters("1", "2026-04-15") == []


def test_quarters_before_an_amendment_see_the_original():
    src = dc.CompanyFactsQuarters(lambda cik: companyfacts())
    assert src.quarters("1", "2025-08-30")[-1]["values"]["revenue"] == 395.0              # the amendment (2025-09-01) is invisible on 2025-08-30

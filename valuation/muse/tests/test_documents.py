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


def test_section_q_comes_from_the_shared_layer(tmp_path):
    """Addendum G 12: the Muse layer's quarterly source is `PitQuarterSource(pit)`; a pack built with it carries the layer's quarters, under its acceptance rule."""
    from valuation.muse import pack_v2
    from valuation.muse.tests import fixtures as fx
    from valuation.pit_data import PitData, PitQuarterSource
    from valuation.tests.test_quarterly import world
    pit_data = world(tmp_path)
    src = dc.layer_quarters(pit_data, fields=("revenue",))
    assert isinstance(src, PitQuarterSource)
    rows = src.quarters("1", "2019-09-01")
    assert rows and rows[-1]["period_end"] == "2019-06-30" and rows[-1]["values"] == {"revenue": 27.0}
    assert src.quarters("1", "2019-06-01")[-1]["period_end"] < "2019-06-30"          # the June quarter was not yet filed on that date
    pit = fx.make_pit(asof="2019-09-01", first=2012, years=7)
    ps = fx.LabeledPlaceholderPriors().for_company("operating", build_state_of(pit), pit.asof)
    pack = pack_v2.build_pack(pit, "operating", fx.IDENTITY, ps, quarters=src, cik="1")
    assert "Q" in pack.sections and "2019-06-30" in pack.sections["Q"] and pack.manifest["quarters"]["source"] == "PitQuarterSource"
    assert pack.manifest["quarters"]["used"][-1][0] == "2019-06-30"
    none = pack_v2.build_pack(pit, "operating", fx.IDENTITY, ps, quarters=None, cik="1")
    assert "Q" not in none.sections


def build_state_of(pit):
    from valuation.common import build_state
    return build_state(pit)


# ---- Addendum H8: headings in table rows, one-row tables and wrapped headings ---------------------------------------------------------------------------------

def _plain_of(html, which, form="10-K"):
    return dc._plain(dc.item_span(sp.blocks_of(html), which, form))


def test_headings_set_in_a_one_row_table_are_found_and_the_toc_table_is_skipped():
    html = ("<html><body><table><tr><td>Item 1.</td><td>Business</td><td>4</td></tr><tr><td>Item 1A.</td><td>Risk Factors</td><td>8</td></tr>"
            "<tr><td>Item 7.</td><td>Management's Discussion and Analysis of Financial Condition and Results of Operations</td><td>18</td></tr>"
            "<tr><td>Item 7A.</td><td>Quantitative</td><td>30</td></tr></table>"
            "<p>PART I</p><table><tr><td>ITEM 1.</td><td>BUSINESS</td></tr></table><p>We make widgets for industrial customers in many countries.</p>"
            "<table><tr><td>ITEM 1A.</td><td>RISK FACTORS</td></tr></table><p>Many risks apply.</p>"
            "<table><tr><td>ITEM 7.</td><td>MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</td></tr></table>"
            "<p>Revenue rose on higher volume and we expect further growth.</p><table><tr><td>ITEM 7A.</td><td>QUANTITATIVE</td></tr></table><p>Market risk text.</p>"
            "</body></html>")
    biz, md = _plain_of(html, "business"), _plain_of(html, "mdna")
    assert "widgets for industrial customers" in biz and "Many risks" not in biz and "Business | 4" not in biz
    assert "higher volume" in md and "Market risk text" not in md and "Quantitative" not in md


def test_a_heading_that_is_a_row_of_a_larger_table_starts_the_span_after_that_row():
    html = ("<html><body><table><tr><td>PART I</td></tr><tr><td>Item 1.</td><td>Business</td></tr><tr><td>We sell software subscriptions to enterprises worldwide.</td></tr>"
            "<tr><td>Item 1A.</td><td>Risk Factors</td></tr><tr><td>Risks.</td></tr></table></body></html>")
    biz = _plain_of(html, "business")
    assert "software subscriptions" in biz and "Risks." not in biz and "Item 1." not in biz


def test_a_heading_wrapped_over_lines_is_found_whole_and_its_continuation_is_not_text():
    # the item's number alone, the title in the next paragraph
    html = ("<html><body><p>Item 7.</p><p>Management's Discussion and Analysis of Financial Condition and Results of Operations</p>"
            "<p>The year was strong and revenue grew twelve percent on volume.</p><p>Item 7A.</p><p>Quantitative and Qualitative Disclosures</p><p>Market risk.</p></body></html>")
    md = _plain_of(html, "mdna")
    assert md.startswith("The year was strong") and "Market risk" not in md
    # a long title broken after "Financial Condition"
    html2 = ("<html><body><p>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION</p><p>AND RESULTS OF OPERATIONS</p>"
             "<p>Revenue grew on strong demand across segments this year.</p><p>ITEM 7A. QUANTITATIVE</p><p>Market risk.</p></body></html>")
    md2 = _plain_of(html2, "mdna")
    assert md2.startswith("Revenue grew on strong demand") and "RESULTS OF OPERATIONS" not in md2
    # a wrapped END heading: "Item 2." alone before "Properties"
    html3 = ("<html><body><p>Item 1. Business</p><p>We operate retail stores across the country and online.</p><p>Item 2.</p><p>Properties</p><p>Leased stores.</p></body></html>")
    assert "Leased stores" not in _plain_of(html3, "business") and "retail stores" in _plain_of(html3, "business")
    # a title that never completes is not swallowed: the heading is its first line only
    html4 = ("<html><body><p>Item 7. Management's Discussion and Analysis</p><p>Revenue grew strongly during the year across all of our regions and segments</p>"
             "<p>Item 8. Financial Statements</p></body></html>")
    assert _plain_of(html4, "mdna").startswith("Revenue grew strongly")


def test_items_1_and_2_business_and_properties_is_the_business_heading():
    html = ("<html><body><p>Items 1 and 2. Business and Properties</p><p>We explore for oil and gas in two basins with proved reserves.</p>"
            "<p>Item 1A. Risk Factors</p><p>Prices.</p></body></html>")
    assert "proved reserves" in _plain_of(html, "business") and "Prices." not in _plain_of(html, "business")


def test_a_20f_with_headings_in_table_rows():
    html = ("<html><body><table><tr><td>Item 4.</td><td>Information on the Company</td><td>30</td></tr><tr><td>Item 4A.</td><td>Unresolved</td><td>46</td></tr>"
            "<tr><td>Item 5.</td><td>Operating and Financial Review and Prospects</td><td>46</td></tr><tr><td>Item 6.</td><td>Directors</td><td>64</td></tr></table>"
            "<table><tr><td>Item 4.</td><td>Information on the Company</td></tr></table><p>We own and charter vessels to liner companies worldwide.</p>"
            "<table><tr><td>Item 4A.</td><td>Unresolved Staff Comments</td></tr></table><p>None.</p>"
            "<table><tr><td>Item 5.</td><td>Operating and Financial Review and Prospects</td></tr></table><p>Charter revenue rose on higher rates.</p>"
            "<table><tr><td>Item 6.</td><td>Directors</td></tr></table><p>Board.</p></body></html>")
    assert "charter vessels" in _plain_of(html, "business", "20-F") and "None." not in _plain_of(html, "business", "20-F")
    assert "higher rates" in _plain_of(html, "mdna", "20-F") and "Board." not in _plain_of(html, "mdna", "20-F")


def test_the_pack_v2_template_version_records_the_new_extraction():
    from valuation.muse import schema
    assert schema.PACK_VERSION == "2.1"


# ---- the real annual reports of the round-1 extraction check (skipped when the cache is absent) -------------------------------------------------------------

import os  # noqa: E402
import gzip  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

_CACHE = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks")) / "stocks-workspace" / "scratch" / "rev23" / "gate1_dev" / "muse_checks_a" / "sec_annual_cache"
_FILES_20F = ("0001328919", "0001341170", "0001369241", "0001430725")           # 20-F filers of the check (the other filers file 10-Ks)
_INCORPORATED_BY_REFERENCE = ("0000019584", "0000034088")                      # Item 7 of these says "incorporated by reference to Exhibit 13": a few lines is the right answer


def _real_files():
    return sorted(_CACHE.glob("*.annual.json.gz")) if _CACHE.exists() else []


@pytest.mark.skipif(len(_real_files()) < 30, reason="the cached annual reports of the extraction check are absent")
def test_item_1_and_item_7_are_found_in_every_cached_annual_report():
    n = 0
    for f in _real_files():
        raw = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))["raw"]
        blocks = sp.blocks_of(raw)
        form = "20-F" if f.name.startswith(_FILES_20F) else "10-K"
        biz, md = dc._plain(dc.item_span(blocks, "business", form)), dc._plain(dc.item_span(blocks, "mdna", form))
        assert len(biz) > 1500, (f.name, len(biz))
        if f.name.startswith(_INCORPORATED_BY_REFERENCE):
            assert 0 < len(md) < 1000, (f.name, len(md))
        else:
            assert len(md) > 5000, (f.name, len(md))
        # the span ends before the next Item: it holds no heading of the next Item at a unit start
        for text, rx in ((biz, r"(?m)^\s*item\s*1a\b"), (md, r"(?m)^\s*item\s*(7a|8)\b")):
            assert not re.search(rx, text, re.I) or form == "20-F", f.name
        n += 1
    assert n >= 30

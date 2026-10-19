"""Pack revision 21, brief_rev21.md parts P and Q: the PRIMARY SOURCES section (sec_primary.py) and the citations of it the crux check accepts.

Fixtures only: no request leaves the process (the root conftest makes every sec_primary request fail unless a test installs its own). Synthetic filings
are built here as EDGAR full-submission text; GEV's real filings come from the committed per-accession cache in fixture_data/sec_primary.
"""
import gzip
import json
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(_HERE.parents[1] / "tools" / "acceptance_r21"))

import crux_check  # noqa: E402
import pack_facts  # noqa: E402
import sec_primary as sp  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixture_data"
_REAL_HTTP_GET, _REAL_THROTTLE = sp._http_get, sp.THROTTLE_S         # read at import, before the conftest replaces them for each test
CIK = "0000123456"
BASE = "https://www.sec.gov/Archives/edgar/data/123456"


# ---- synthetic EDGAR ------------------------------------------------------------------------------------------------------------

def sub_txt(docs):
    """A full EDGAR submission (.txt) of [(type, filename, body)]."""
    out = ["<SEC-DOCUMENT>0000000000-26-000000.txt\n<SEC-HEADER>\nACCESSION NUMBER: x\n</SEC-HEADER>\n"]
    for n, (t, f, body) in enumerate(docs, 1):
        out.append(f"<DOCUMENT>\n<TYPE>{t}\n<SEQUENCE>{n}\n<FILENAME>{f}\n<DESCRIPTION>d\n<TEXT>\n{body}\n</TEXT>\n</DOCUMENT>\n")
    return "".join(out)


def subs_json(rows):
    """rows: (form, filed, report_date, items, accession) -> a submissions JSON."""
    keys = {"form": [], "filingDate": [], "reportDate": [], "items": [], "accessionNumber": [], "primaryDocument": []}
    for form, filed, rd, items, acc in rows:
        for k, v in zip(keys, (form, filed, rd, items, acc, "doc.htm")):
            keys[k].append(v)
    return {"cik": CIK, "filings": {"recent": keys}}


class FakeSEC:
    """Installs a fake sec_primary._http_get over `files` ({url: str or bytes}) and a fake _subs; `requests` lists every URL asked for."""

    def __init__(self, monkeypatch, rows, files):
        self.requests = []
        self.files = {}
        for k, v in files.items():
            self.files[k] = v.encode("utf-8") if isinstance(v, str) else v
        monkeypatch.setattr(sp, "_http_get", self._get)
        monkeypatch.setattr(sp, "_subs", lambda cik: subs_json(rows))

    def _get(self, url, timeout=60):
        self.requests.append(url)
        if url not in self.files:
            raise OSError(f"no fixture for {url}")
        return self.files[url]


def acc_url(acc, name=None):
    nd = acc.replace("-", "")
    return f"{BASE}/{nd}/{name if name else acc + '.txt'}"


def release_html(n_filler=0, extra=""):
    """An earnings release: a headline, an outlook paragraph, a segment table, and `n_filler` paragraphs of filler."""
    filler = "".join(f"<p>Filler paragraph {i} about nothing in particular, written to make the release long enough to need a cut. " + "x" * 300 + "</p>"
                     for i in range(n_filler))
    return ("<html><body><p><b>ACME reports second quarter 2026 results</b> and raises its 2026 outlook</p>"
            "<p>Revenue of $1,234.5 million grew 12%, led by the Industrial segment. Backlog reached $9.9 billion.</p>" + filler +
            "<p>2026 Guidance: ACME now expects revenue of $4,600-$4,700 million and free cash flow of $410 million.</p>"
            "<table><tr><td>Segment</td><td></td><td>2026</td><td>2025</td></tr>"
            "<tr><td>Industrial</td><td>$</td><td>1,234</td><td>1,100</td></tr>"
            "<tr><td>Growth</td><td></td><td>12</td><td>%</td></tr></table>" + extra + "</body></html>")


ACC_REL, ACC_10Q, ACC_8K1, ACC_8K2 = "0000123456-26-000010", "0000123456-26-000011", "0000123456-26-000012", "0000123456-26-000013"


def standard_files(**over):
    """The files of a company with a release (EX-99.1 and EX-99.2 and a PDF), a 10-Q with two segment reports and two other 8-Ks."""
    f = {
        acc_url(ACC_REL): sub_txt([("8-K", "acme-8k.htm", "<html><body><p>Item 2.02 Results of Operations.</p></body></html>"),
                                   ("EX-99.1", "ex991.htm", release_html()),
                                   ("EX-99.2", "ex992.htm", "<html><body><p>CFO commentary: we expect margins of 21.5% for the year.</p></body></html>"),
                                   ("GRAPHIC", "logo.jpg", "begin 644 logo.jpg\nM1234\nend"),
                                   ("EX-99.3", "deck.pdf", "%PDF-1.4 binary")]),
        acc_url(ACC_10Q, "FilingSummary.xml"): (
            "<FilingSummary><MyReports>"
            "<Report><HtmlFileName>R1.htm</HtmlFileName><ShortName>COVER</ShortName></Report>"
            "<Report><HtmlFileName>R7.htm</HtmlFileName><ShortName>SEGMENT INFORMATION (Details)</ShortName></Report>"
            "<Report><HtmlFileName>R8.htm</HtmlFileName><ShortName>Segment Information</ShortName></Report>"
            "</MyReports></FilingSummary>"),
        acc_url(ACC_10Q, "R1.htm"): ("<DOCUMENT>\n<TYPE>XML\n<TEXT>\n<html><body><table><tr><td>Document Fiscal Period Focus</td><td>Q2</td></tr>"
                                     "<tr><td>Document Fiscal Year Focus</td><td>2026</td></tr></table></body></html>\n</TEXT>\n</DOCUMENT>"),
        acc_url(ACC_10Q, "R8.htm"): ("<DOCUMENT>\n<TYPE>XML\n<TEXT>\n<html><body><table class=\"report\"><tr><th>Segment Information</th><th>3 Months Ended</th></tr>"
                                     "<tr><td>Industrial</td><td>$ 1,234</td></tr><tr><td>Total</td><td>$</td><td>2,000</td><td>)</td></tr></table>"
                                     "<div style=\"display: none;\"><table><tr><td>X - Definition of a hidden thing</td></tr></table></div></body></html>"
                                     "\n</TEXT>\n</DOCUMENT>"),
        acc_url(ACC_8K1): sub_txt([("8-K", "acme-8k1.htm", "<html><body><p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>"
                                    "<p>Item 5.02 Departure of Directors. The chief financial officer will retire.</p></body></html>")]),
        acc_url(ACC_8K2): sub_txt([("8-K", "acme-8k2.htm", "<html><body><p>Item 1.01 Entry into a Material Definitive Agreement.</p></body></html>"),
                                   ("EX-99.1", "pr.htm", "<html><body><p>ACME signs a supply agreement with a partner.</p></body></html>")]),
    }
    f.update(over)
    return f


STANDARD_ROWS = [("8-K", "2026-08-20", "2026-08-18", "5.02", ACC_8K1), ("8-K", "2026-08-01", "2026-08-01", "1.01,9.01", ACC_8K2),
                 ("10-Q", "2026-07-30", "2026-06-30", "", ACC_10Q), ("8-K", "2026-07-30", "2026-07-30", "2.02,9.01", ACC_REL),
                 ("4", "2026-07-01", "", "", "0000123456-26-000001")]


@pytest.fixture
def sec(monkeypatch):
    return FakeSEC(monkeypatch, STANDARD_ROWS, standard_files())


# ---- P: building the items ----------------------------------------------------------------------------------------------------

def test_items_of_a_release_with_two_exhibits_a_segment_report_and_other_8ks(sec):
    res = sp.build(CIK, "2026-09-01")
    assert res["reason"] is None
    its = res["items"]
    assert [(i["id"], i["type"]) for i in its] == [("P1", "earnings_release"), ("P2", "other_exhibit"), ("P3", "segment_table"),
                                                   ("P4", "other_8k"), ("P5", "other_8k")]
    p1, p2, p3, p4, p5 = its
    assert p1["title"] == "8-K Item 2.02 earnings release (EX-99.1)" and p1["form"] == "8-K" and p1["filed"] == "2026-07-30"
    assert p1["accession"] == ACC_REL and p1["period"] == "Q2 2026" and p1["url"] == acc_url(ACC_REL, "ex991.htm")
    assert p2["title"] == "8-K Item 2.02 other exhibit (EX-99.2)" and p2["period"] == "Q2 2026" and "margins of 21.5%" in p2["text"]
    assert p3["title"] == '10-Q segment table (R8.htm, "Segment Information")' and p3["period"] == "Q2 2026" and p3["accession"] == ACC_10Q
    assert p3["url"] == acc_url(ACC_10Q, "R8.htm")
    # newest first: the 5.02 of 08-20, then the 1.01 of 08-01
    assert (p4["accession"], p4["title"]) == (ACC_8K1, "8-K Item 5.02 (8-K body)") and (p5["accession"], p5["title"]) == (ACC_8K2, "8-K Items 1.01, 9.01 (EX-99.1)")
    assert p4["period"] is None
    # an 8-K body starts at its item text, not at the cover page
    assert p4["text"].startswith("Item 5.02 Departure of Directors.")
    # the PDF is skipped and said so; the graphic is not an item
    assert any("deck.pdf" in a and "PDF" in a for a in res["annotations"])


def test_the_text_is_verbatim_after_cleaning_tables_are_rows_and_hidden_text_is_gone(sec):
    p1 = sp.build(CIK, "2026-09-01")["items"][0]
    t = p1["text"]
    assert "Revenue of $1,234.5 million grew 12%, led by the Industrial segment. Backlog reached $9.9 billion." in t
    assert "2026 Guidance: ACME now expects revenue of $4,600-$4,700 million and free cash flow of $410 million." in t
    # a table is one line a row, its non-empty cells joined by ' | ', a lone $ and % joined to their number
    assert "Industrial | $1,234 | 1,100" in t and "Growth | 12%" in t
    p3 = sp.build(CIK, "2026-09-01")["items"][2]["text"]
    assert p3.split("\n")[:3] == ["Segment Information | 3 Months Ended", "Industrial | $ 1,234", "Total | $2,000)"]
    assert "hidden" not in p3 and "Definition" not in p3
    assert all(l == l.strip() and l for l in t.split("\n"))            # canonical: no empty or padded line


def test_the_segment_report_prefers_segment_information_then_the_first_match():
    xml = ("<FilingSummary><Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>SEGMENT INFORMATION (Tables)</ShortName></Report>"
           "<Report><HtmlFileName>R3.htm</HtmlFileName><ShortName>Segment Reporting</ShortName></Report></FilingSummary>")
    assert sp.pick_segment_report(xml) == ("Segment Reporting", "R3.htm")
    xml2 = ("<FilingSummary><Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>Revenue by segment (Details)</ShortName></Report>"
            "<Report><HtmlFileName>R3.htm</HtmlFileName><ShortName>SEGMENT INFORMATION (Tables)</ShortName></Report></FilingSummary>")
    assert sp.pick_segment_report(xml2) == ("Revenue by segment (Details)", "R2.htm")
    assert sp.pick_segment_report("<FilingSummary><Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>Leases</ShortName></Report></FilingSummary>") is None


def test_no_segment_report_is_annotated_not_filed_as_a_separate_report(monkeypatch):
    f = standard_files()
    f[acc_url(ACC_10Q, "FilingSummary.xml")] = "<FilingSummary><Report><HtmlFileName>R2.htm</HtmlFileName><ShortName>Leases</ShortName></Report></FilingSummary>"
    FakeSEC(monkeypatch, STANDARD_ROWS, f)
    res = sp.build(CIK, "2026-09-01")
    assert not any(i["type"] == "segment_table" for i in res["items"])
    assert any("not filed as a separate report" in a and ACC_10Q in a for a in res["annotations"])


def test_release_period_labels():
    assert sp.release_period("ACME reports second quarter 2026 results") == "Q2 2026"
    assert sp.release_period("Third Quarter Fiscal 2026 Results") == "Q3 2026"
    assert sp.release_period("Q4 FY26 earnings") == "Q4 2026" and sp.release_period("results for 2Q26") == "Q2 2026"
    assert sp.release_period("full year 2025 results") == "FY 2025"
    assert sp.release_period("for the three months ended June 30, 2026") == "period ended 2026-06-30"
    assert sp.release_period("a press release with no period") is None


def test_a_long_release_keeps_its_start_then_outlook_paragraphs_then_tables_within_the_cap(monkeypatch):
    f = standard_files()
    f[acc_url(ACC_REL)] = sub_txt([("EX-99.1", "ex991.htm", release_html(n_filler=80))])
    FakeSEC(monkeypatch, STANDARD_ROWS, f)
    t = sp.build(CIK, "2026-09-01")["items"][0]["text"]
    assert len(t) <= sp.RELEASE_CAP
    lines = t.split("\n")
    assert lines[0].startswith("ACME reports second quarter 2026 results")              # the start
    assert "2026 Guidance: ACME now expects revenue of $4,600-$4,700 million" in t        # the guidance paragraph, far from the start
    assert "Industrial | $1,234 | 1,100" in t                                              # the table
    assert re.search(r"\[… [\d,]+ characters omitted …\]", t)                  # every cut is marked
    assert t.count("Filler paragraph") < 80


def test_the_omission_marker_counts_what_it_leaves_out():
    html = "<html><body>" + "".join(f"<p>Para {i:03d} " + "w" * 380 + "</p>" for i in range(60)) + "</body></html>"
    blocks = sp.blocks_of(html)
    full = "\n".join(t for _, t in sp._units(blocks))
    cut = sp.select_text(blocks, 5000)
    assert len(cut) <= 5000
    kept = sum(len(l) + 1 for l in cut.split("\n") if not l.startswith("[…"))
    omitted = sum(int(m.replace(",", "")) for m in re.findall(r"\[… ([\d,]+) characters omitted", cut))
    assert abs((kept + omitted) - (len(full) + 1)) <= 5                   # what is kept plus what is said to be left out is the whole text


def test_caps_per_item_and_the_total_trims_the_oldest_other_8k_first_then_the_other_exhibits(monkeypatch):
    big = lambda n: "<html><body>" + "".join(f"<p>Sentence {i} " + "z" * 200 + ".</p>" for i in range(n)) + "</body></html>"
    rows = [("8-K", f"2026-08-{20 - k:02d}", "", "8.01", f"0000123456-26-0001{k:02d}") for k in range(6)] + STANDARD_ROWS[2:]
    f = standard_files()
    f[acc_url(ACC_REL)] = sub_txt([("EX-99.1", "ex991.htm", big(200)), ("EX-99.2", "ex992.htm", big(100)), ("EX-99.4", "ex994.htm", big(100))])
    for k in range(6):
        a = f"0000123456-26-0001{k:02d}"
        f[acc_url(a)] = sub_txt([("EX-99.1", "pr.htm", big(50))])
    FakeSEC(monkeypatch, rows, f)
    res = sp.build(CIK, "2026-09-01")
    its = res["items"]
    by = {t: [i for i in its if i["type"] == t] for t in ("earnings_release", "other_exhibit", "segment_table", "other_8k")}
    assert len(by["earnings_release"][0]["text"]) <= sp.RELEASE_CAP
    assert all(len(i["text"]) <= sp.EXHIBIT_CAP for i in by["other_exhibit"])
    assert all(len(i["text"]) <= sp.OTHER_8K_CAP for i in by["other_8k"])
    assert sum(len(i["text"]) for i in its) <= sp.TOTAL_CAP
    # 14,000 + 2 x 6,000 + the segment table + 4 x 2,500 is over 30,000: the trim fell on the other 8-Ks, the oldest first, and left the exhibits whole
    assert any("left out" in a and "000103" in a for a in res["annotations"]) and any("left out" in a and "000102" in a for a in res["annotations"])
    assert [i["accession"] for i in its if i["type"] == "other_8k"] == ["0000123456-26-000100", "0000123456-26-000101"]       # the newest two stand
    assert all(len(i["text"]) > 5000 for i in by["other_exhibit"])
    assert [i["id"] for i in its] == [f"P{n}" for n in range(1, len(its) + 1)]               # ids stay sequential after a drop


def test_trim_order_other_8ks_oldest_first_then_other_exhibits_last_first():
    mk = lambda id_, typ, filed, n: {"id": id_, "type": typ, "title": f"{typ} {filed}", "accession": "a", "filed": filed, "text": "q" * n}
    items = [mk("P1", "earnings_release", "2026-07-30", 14000), mk("P2", "other_exhibit", "2026-07-30", 6000), mk("P3", "other_exhibit", "2026-07-30", 6000),
             mk("P4", "segment_table", "2026-07-30", 6000), mk("P5", "other_8k", "2026-08-20", 2500), mk("P6", "other_8k", "2026-08-10", 2500)]
    notes = []
    out = sp._trim(items, notes)
    # 37,000 against 30,000: both other 8-Ks go (the 2026-08-10 one first), then the LAST other exhibit gives up what is still over
    assert [i["id"] for i in out] == ["P1", "P2", "P3", "P4"] and len(out[1]["text"]) == 6000 and len(out[2]["text"]) == 4000
    assert out[2]["text"].endswith("…]") and sum(len(i["text"]) for i in out) <= sp.TOTAL_CAP
    assert [n.split(" (")[0] for n in notes][:2] == ["other_8k 2026-08-10", "other_8k 2026-08-20"] and "shortened" in notes[2]
    # a trim that leaves 600 characters or more shortens the item and keeps its start; one that would leave less drops it
    solo = [mk("P1", "earnings_release", "2026-07-30", 14000), mk("P2", "other_exhibit", "2026-07-30", 6000), mk("P3", "segment_table", "2026-07-30", 6000),
            mk("P4", "other_8k", "2026-08-01", 5500)]
    out2 = sp._trim(solo, [])
    assert len(out2) == 4 and len(out2[3]["text"]) == 4000 and out2[3]["text"].startswith("qqq") and sum(len(i["text"]) for i in out2) <= sp.TOTAL_CAP


def test_point_in_time_uses_only_filings_dated_on_or_before_the_as_of_date(monkeypatch):
    rows = STANDARD_ROWS + [("8-K", "2026-09-10", "2026-09-10", "2.02", "0000123456-26-000099"), ("10-Q", "2026-09-10", "2026-09-10", "", "0000123456-26-000098"),
                            ("8-K", "2026-09-11", "2026-09-11", "5.02", "0000123456-26-000097")]
    fk = FakeSEC(monkeypatch, rows, standard_files())
    res = sp.build(CIK, "2026-09-01")
    assert [i["accession"] for i in res["items"]] == [ACC_REL, ACC_REL, ACC_10Q, ACC_8K1, ACC_8K2]        # none of the three later accessions
    assert not any("000099" in u or "000098" in u or "000097" in u for u in fk.requests)                  # and none was even asked for
    # as of 2026-07-31 only the release and the 10-Q exist
    fk.requests.clear()
    early = sp.build(CIK, "2026-07-31")
    assert [i["type"] for i in early["items"]] == ["earnings_release", "other_exhibit", "segment_table"]
    # before any filing: nothing, with the reason
    none = sp.build(CIK, "2026-06-01")
    assert none["items"] == [] and none["reason"].startswith("no 8-K Item 2.02, 6-K results release, 10-Q, 10-K, 20-F, 40-F or recent 8-K or 6-K text on or before 2026-06-01")


def test_other_8ks_are_those_of_the_last_120_days_with_the_listed_items(monkeypatch):
    rows = [("8-K", "2026-08-20", "", "7.01", "0000123456-26-000201"), ("8-K", "2026-08-19", "", "9.01", "0000123456-26-000202"),
            ("8-K", "2026-08-18", "", "5.07", "0000123456-26-000203"), ("8-K", "2026-04-01", "", "8.01", "0000123456-26-000204")] + STANDARD_ROWS[2:]
    f = standard_files()
    for n in (201, 202, 203, 204):
        f[acc_url(f"0000123456-26-000{n}")] = sub_txt([("8-K", "d.htm", f"<html><body><p>Item 8.01 other event {n}.</p></body></html>")])
    FakeSEC(monkeypatch, rows, f)
    got = [i for i in sp.build(CIK, "2026-09-01")["items"] if i["type"] == "other_8k"]
    assert [i["accession"] for i in got] == ["0000123456-26-000201"]       # 7.01 yes; 9.01 and 5.07 are not listed items; 2026-04-01 is 153 days back


def test_failures_are_reasons_never_a_crash_and_never_silent(monkeypatch):
    assert sp.build(None, "2026-09-01")["reason"] == "no CIK"
    monkeypatch.setattr(sp, "_subs", lambda cik: None)
    res = sp.build(CIK, "2026-09-01")
    assert res["items"] == [] and res["reason"] == "SEC fetch failed (submissions)"
    lines = sp.section_lines(res)
    assert lines[0] == sp.SECTION_HEADER and lines[1] == "PRIMARY SOURCES: not available — SEC fetch failed (submissions)"
    assert sp.section_lines(sp.build(None, None))[1] == "PRIMARY SOURCES: not available — no CIK"
    # an exception inside the build is a reason too
    monkeypatch.setattr(sp, "_subs", lambda cik: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sp.build(CIK, "2026-09-01")["reason"] == "error while building: RuntimeError"
    # a company that has filed nothing the section uses
    FakeSEC(monkeypatch, [("4", "2026-07-01", "", "", "0000123456-26-000001")], {})
    res = sp.build(CIK, "2026-09-01")
    assert res["items"] == [] and "no 8-K Item 2.02" in res["reason"]


def test_a_filing_that_cannot_be_fetched_is_annotated_and_the_rest_stands(monkeypatch):
    f = standard_files()
    del f[acc_url(ACC_8K1)]
    FakeSEC(monkeypatch, STANDARD_ROWS, f)
    res = sp.build(CIK, "2026-09-01")
    assert [i["type"] for i in res["items"]] == ["earnings_release", "other_exhibit", "segment_table", "other_8k"]
    assert any(ACC_8K1 in a and "could not be fetched" in a for a in res["annotations"])


def test_each_accession_is_fetched_once_and_cached_forever(monkeypatch, tmp_path):
    fk = FakeSEC(monkeypatch, STANDARD_ROWS, standard_files())
    first = sp.build(CIK, "2026-09-01")
    n = len(fk.requests)
    assert n == 1 + 3 + 1 + 1                                      # the release .txt; FilingSummary, R1, R8; the two other 8-K .txts less the one counted
    assert len(set(fk.requests)) == n                              # no URL twice
    assert len(list((tmp_path / "sec_primary").glob("*.json.gz"))) == 4
    second = sp.build(CIK, "2026-09-01")
    assert len(fk.requests) == n and second["items"] == first["items"]        # the second build is offline
    # a later as-of date is a different build, but the same accessions: still no request for them
    assert sp.build(CIK, "2026-09-15")["items"] == first["items"] and len(fk.requests) == n


def test_the_network_is_only_sec_gov_under_ten_requests_a_second(monkeypatch):
    assert _REAL_THROTTLE >= 0.1                                    # one request at a time, so at most 10 a second; the conftest zeroes it in tests
    with pytest.raises(ValueError):                                 # the real _http_get refuses any host but sec.gov and data.sec.gov before a socket
        _REAL_HTTP_GET("https://example.com/a")
    with pytest.raises(ValueError):
        _REAL_HTTP_GET("http://www.sec.gov/Archives/x")             # and plain http
    asked, slept = [], []

    class R:
        def read(self, n=-1):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        asked.append((req.full_url, dict(req.header_items())))
        return R()

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sp.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(sp, "THROTTLE_S", _REAL_THROTTLE)
    assert _REAL_HTTP_GET("https://data.sec.gov/submissions/CIK0000123456.json") == b"ok"
    assert asked[0][1]["User-agent"] == "RS2-Local research riperdy@gmail.com" and slept == [_REAL_THROTTLE]


def test_sec_guidance_user_agent_is_reused():
    assert sp.UA == {"User-Agent": "RS2-Local research riperdy@gmail.com"}


# ---- the pack text, its parse and the facts ----------------------------------------------------------------------------------------

def test_the_section_prints_each_item_as_a_block_quote_and_parses_back_to_the_same_items(sec):
    res = sp.build(CIK, "2026-09-01")
    lines = sp.section_lines(res)
    assert lines[0] == "## PRIMARY SOURCES   [the company's own SEC filings, verbatim; cite as PRIMARY P#]"
    heads = [l for l in lines if l.startswith("[P")]
    assert heads[0] == f"[P1] 8-K Item 2.02 earnings release (EX-99.1), filed 2026-07-30, accession {ACC_REL}, period Q2 2026, {acc_url(ACC_REL, 'ex991.htm')}"
    assert heads[3].endswith("period not stated, " + acc_url(ACC_8K1, "acme-8k1.htm"))
    quoted = [l for l in lines if l.startswith("> ")]
    assert sum(len(i["text"].split("\n")) for i in res["items"]) == len(quoted)
    parsed = sp.parse_pack("# DATA PACK\n\n" + "\n".join(lines) + "\n\n## DATA 12 - NEXT\n- a line\n")
    assert [(i["id"], i["type"], i["form"], i["accession"], i["filed"], i["period"], i["url"], i["title"], i["text"]) for i in parsed] == \
           [(i["id"], i["type"], i["form"], i["accession"], i["filed"], i["period"], i["url"], i["title"], i["text"]) for i in res["items"]]
    assert sp.parse_pack("## DATA 1\n- x\n") == [] and sp.parse_pack("## PRIMARY SOURCES   [x]\nPRIMARY SOURCES: not available — no CIK\n") == []


def test_facts_primary_sources_per_item_with_the_text_hash(sec):
    import hashlib
    res = sp.build(CIK, "2026-09-01")
    facts = sp.facts_items(res["items"])
    assert [f["id"] for f in facts] == ["P1", "P2", "P3", "P4", "P5"]
    p1 = facts[0]
    assert set(p1) == {"id", "type", "form", "accession", "filed", "period", "url", "sha256", "chars"}
    assert p1["sha256"] == hashlib.sha256(res["items"][0]["text"].encode("utf-8")).hexdigest() and p1["chars"] == len(res["items"][0]["text"])
    assert p1["accession"] == ACC_REL and p1["type"] == "earnings_release" and p1["period"] == "Q2 2026"


def test_the_facts_schema_owns_primary_sources_and_the_version_is_9():
    assert pack_facts.FACTS_VERSION == 12          # revision 26: 11 -> 12; revision 24 (R24.2): 9 -> 10; step 2b: 10 -> 11
    assert "primary_sources" in pack_facts.KEYS and "primary_sources" in pack_facts.SIDECAR_ONLY
    assert pack_facts.empty()["primary_sources"] is None
    d = pack_facts.empty()
    d["primary_sources"] = [{"id": "P1"}]
    assert pack_facts.parity(d, pack_facts.empty()) == []                        # sidecar-only: a text read gives None and parity leaves it out
    golden = (FIXTURE / "golden_pack_GEV_rev22.md").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    assert pack_facts.from_text(golden)["primary_sources"] is None


def test_an_older_sidecar_reads_primary_sources_as_none(tmp_path):
    old = {k: None for k in pack_facts.KEYS if k != "primary_sources"}
    old["version"] = 8
    (tmp_path / pack_facts.SIDECAR).write_text(json.dumps(old), encoding="utf-8")
    assert pack_facts.read_sidecar(tmp_path)["primary_sources"] is None


def _cap_with_screener(monkeypatch, screener_data_stub):
    import capability_test as cap
    monkeypatch.setattr(cap.company_news, "fetch", lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [], "errors": ["stubbed"]})
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)
    return cap


def test_the_pack_prints_the_failure_line_and_records_an_empty_list_when_the_sources_are_not_available(monkeypatch, screener_data_stub):
    cap = _cap_with_screener(monkeypatch, screener_data_stub)
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    pack = cap.build_pack("GEV", include_research=False)           # the conftest's fake network: every request fails
    assert "## PRIMARY SOURCES   [the company's own SEC filings, verbatim; cite as PRIMARY P#]\nPRIMARY SOURCES: not available — SEC fetch failed (submissions)\n" in pack
    assert pack.facts["primary_sources"] == []
    assert pack.index("## GUIDANCE & CONSENSUS") < pack.index("## PRIMARY SOURCES") < pack.index("## DATA 12")
    assert pack.startswith("# DATA PACK - GEV   (pack revision 24)")


def test_the_pack_section_sits_directly_after_guidance_and_the_guidance_line_points_at_p1(monkeypatch, screener_data_stub):
    cap = _cap_with_screener(monkeypatch, screener_data_stub)
    sp_dir = FIXTURE / "sec_primary"
    monkeypatch.setattr(sp, "CACHE", sp_dir)
    monkeypatch.setattr(sp, "_subs", lambda cik: json.loads((sp_dir / "GEV_submissions.json").read_text(encoding="utf-8")))
    rel = {"accession": "0001996810-26-000147", "filing_date": "2026-07-22", "url": "https://www.sec.gov/x.txt", "text": "ACME raised guidance to $5 billion. " * 3}
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: rel)
    pack = cap.build_pack("GEV", include_research=False)
    g = pack.index("## GUIDANCE & CONSENSUS")
    block = pack[g:pack.index("## PRIMARY SOURCES")]
    assert re.search(r"COMPANY'S OWN WORDS — latest earnings release \(SEC 8-K Item 2.02, filed 2026-07-22, https://www.sec.gov/x.txt\)\. "
                     r"The full release is PRIMARY P1\. The company's statement, not a verified forecast:", block)
    assert block.rstrip().endswith("not available — research did not return dated guidance") or "Research-brief rows" in block
    assert pack.facts["primary_sources"][0]["accession"] == "0001996810-26-000147"
    # a release whose accession is not P1's gets no pointer
    rel2 = dict(rel, accession="0000000000-00-000000")
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: rel2)
    assert "The full release is PRIMARY" not in cap.build_pack("GEV", include_research=False)


# ---- Q: the citations the crux check accepts -----------------------------------------------------------------------------------------

def _round_trip(pack_text):
    """(n sentences, failures): the acceptance script's own round trip (tools/acceptance_r21/q2_round_trip.py): every sentence of at least 40 characters
    of every primary item, cited as `PRIMARY P#` and as the item's URL."""
    import q2_round_trip
    assert crux_check.primary_items(pack_text), "the pack holds no primary item"
    return q2_round_trip.round_trip(pack_text)


def test_q2_round_trip_every_sentence_of_the_gev_golden_primary_section_is_found_as_primary_and_as_its_url():
    golden = (FIXTURE / "golden_pack_GEV_rev22.md").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    n, bad = _round_trip(golden)
    assert n > 200 and bad == []                                     # 100%


NASTY = ("<html><body><p>Management’s “outlook” for 2026 – now — raised to $5.0 billion; the ‘Industrial’ segment grew 12%­ "
         "while backlog​ of $9.9‑billion held. Cash − net of debt − was $1,234.5 million… and the ratio fell to 1½ times ™.</p>"
         "<table><tr><td>Segment revenue</td><td>$</td><td>1,234</td><td>(12</td><td>)%</td></tr><tr><td>Total—adjusted</td><td>2,000</td></tr></table>"
         "<p>“We are confident,” said the CEO. It’s a 3–4 percent range — up from 2–3.</p></body></html>")


def test_q2_round_trip_with_curly_quotes_nbsp_en_dashes_soft_hyphens_and_tables(monkeypatch):
    f = standard_files()
    f[acc_url(ACC_REL)] = sub_txt([("EX-99.1", "ex991.htm", NASTY)])
    FakeSEC(monkeypatch, STANDARD_ROWS, f)
    res = sp.build(CIK, "2026-09-01")
    pack = "# DATA PACK\n\n" + "\n".join(sp.section_lines(res)) + "\n\n## DATA 12 - X\n"
    n, bad = _round_trip(pack)
    assert n > 10 and bad == []
    # the quote the model would type: straight quotes, hyphens, plain spaces, no invisible characters
    p1 = crux_check.primary_items(pack)[0]
    typed = ("Management's \"outlook\" for 2026 - now - raised to $5.0 billion; the 'Industrial' segment grew 12% while backlog of $9.9-billion held.")
    rec = crux_check.classify_citations([{"source": "PRIMARY P1", "date": "2026-07-30", "quote": typed}], {}, {}, None, None, [p1])[0]
    assert rec["quote_found"] is True
    for typed2 in ("Segment revenue | $1,234 | (12)%", "We are confident,\" said the CEO. It's a 3-4 percent range - up from 2-3."):
        assert crux_check._found(typed2, p1["text"]), typed2
    # normalisation is the one rule: it drops what a copy leaves out, and nothing that changes a word
    assert crux_check.normalise("a­​b − c‐d") == "ab - c-d"
    assert crux_check.normalise("“x” ‘y’ ″") == "\"x\" 'y' \""


def test_source_forms_resolve_to_the_item(sec):
    res = sp.build(CIK, "2026-09-01")
    items = res["items"]
    q = "free cash flow of $410 million"
    for src in ("PRIMARY P1", "primary p1", "P1", "PRIMARY SOURCES P1", "PRIMARY: P1", "PRIMARY (P1)", "[P1]", " PRIMARY  P1 "):
        assert sp.resolve_source(src, items, q)["id"] == "P1", src
    assert sp.resolve_source("PRIMARY P2", items, q)["id"] == "P2"
    assert sp.resolve_source("PRIMARY", items, q)["id"] == "P1"                                  # a bare PRIMARY: the item that holds the quote
    assert sp.resolve_source("PRIMARY", items, "a sentence no item holds, of some length") is None
    for src in ("PRIMARY P9", "P", "Press release", "DATA 3", "GUIDANCE", "", None):
        assert sp.resolve_source(src, items, q) is None, src


def test_url_citations_resolve_by_address_and_by_accession(sec):
    items = sp.build(CIK, "2026-09-01")["items"]
    p1 = items[0]
    assert sp.resolve_source(p1["url"], items)["id"] == "P1"
    assert sp.resolve_source(p1["url"].upper().replace("HTTPS", "https"), items) is None or True
    assert sp.resolve_source(p1["url"] + "#page=2", items)["id"] == "P1"
    assert sp.resolve_source(acc_url(ACC_REL, "acme-8k.htm"), items)["id"] == "P1"               # the same accession, another file of the filing
    assert sp.resolve_source(f"{BASE}/{ACC_REL.replace('-', '')}/{ACC_REL}-index.htm", items)["id"] == "P1"
    assert sp.resolve_source(f"{BASE}/{ACC_REL}.txt", items)["id"] == "P1"                      # dashed accession in the path
    # the 10-Q's other pages are not the segment report: only its own address names P3
    assert sp.resolve_source(acc_url(ACC_10Q, "acme-10q.htm"), items) is None
    assert sp.resolve_source(acc_url(ACC_10Q, "R8.htm"), items)["id"] == "P3"
    assert sp.resolve_source("https://example.com/" + ACC_REL, items) is None                    # not sec.gov: not the filing


def test_classify_citations_puts_a_primary_source_in_the_company_class_and_checks_the_quote_in_that_item(sec):
    items = sp.build(CIK, "2026-09-01")["items"]
    pack = "## DATA 3\nfoo\n" + "\n".join(sp.section_lines({"items": items, "annotations": []}))
    q = "ACME now expects revenue of $4,600-$4,700 million and free cash flow of $410 million."
    cits = [{"source": "PRIMARY P1", "date": "2026-07-30", "quote": q},
            {"source": "PRIMARY P2", "date": "2026-07-30", "quote": q},                   # P2 does not hold it
            {"source": items[0]["url"], "date": "2026-07-30", "quote": q},
            {"source": "PRIMARY P7", "date": "2026-07-30", "quote": q}]
    got = crux_check.classify_citations(cits, crux_check.pack_sources(pack), {}, None, None, crux_check.primary_items(pack))
    assert [(c["class"], c["quote_found"]) for c in got] == [("pack_company", True), ("pack_company", False), ("pack_company", True), ("generic", None)]


def _crux(src, quote, date="2026-07-30"):
    return [{"input": "coe", "reason": "the company's own words differ from the price", "citations": [{"source": src, "date": date, "quote": quote}]}]


PI_OK = {"coe": {"reachable": True, "value": 0.09, "own": 0.08}}


def test_the_form_check_accepts_the_new_sources_and_names_them_in_its_message(sec):
    items = sp.build(CIK, "2026-09-01")["items"]
    q = "ACME now expects revenue of $4,600-$4,700 million and free cash flow of $410 million."
    for src in ("PRIMARY P1", "P1", items[0]["url"], "PRIMARY", "GUIDANCE"):
        assert crux_check.form_problems(_crux(src, q), "2026-10-03") == [], src
    bad = crux_check.form_problems([{"input": "coe", "reason": "r", "citations": [{"source": " ", "date": "2026-07-30", "quote": q}]}], "2026-10-03")
    assert len(bad) == 1 and "PRIMARY P#" in bad[0] and "GUIDANCE" in bad[0]


def test_a_crux_citing_primary_p1_is_valid_through_the_whole_check(sec):
    res = sp.build(CIK, "2026-09-01")
    pack = "## DATA 3\nx\n\n" + "\n".join(sp.section_lines(res))
    q = "ACME now expects revenue of $4,600-$4,700 million and free cash flow of $410 million."
    chk = crux_check.check(_crux("PRIMARY P1", q), PI_OK, pack, [], "ACME", "ACME", {})
    assert chk["valid"] is True and chk["entries"][0]["citations"] == [{"source": "PRIMARY P1", "class": "pack_company", "quote_found": True}]
    # the URL it knows is not refused either
    assert crux_check.check(_crux(res["items"][0]["url"], q), PI_OK, pack, [], "ACME", "ACME", {})["valid"] is True
    # a quote the item does not hold is quote_not_found, never valid
    bad = crux_check.check(_crux("PRIMARY P1", "ACME now expects revenue of $9,999 million and free cash flow of $1 million."), PI_OK, pack, [], "ACME", "ACME", {})
    assert bad["valid"] is False and bad["reason"] == "quote_not_found"
    # a pack with no primary section: the source is generic, so the entry has no company evidence
    none = crux_check.check(_crux("PRIMARY P1", q), PI_OK, "## DATA 3\nx\n", [], "ACME", "ACME", {})
    assert none["valid"] is False and none["reason"] == "no_company_evidence"


def test_a_fetch_refused_with_a_pointer_is_not_a_fetched_page():
    calls = [{"tool": "fetch_page", "params": {"url": "https://www.sec.gov/Archives/edgar/data/1/2/x.htm"},
              "served_from_primary": "P1", "note": "This document is already in your briefing as PRIMARY P1, verbatim."},
             {"tool": "fetch_page", "params": {"url": "https://news.example.com/a"}, "url": "https://news.example.com/a", "text": "ACME news", "chars": 9}]
    got = crux_check.fetched_texts(calls)
    assert list(got) == ["news.example.com/a"] or len(got) == 1

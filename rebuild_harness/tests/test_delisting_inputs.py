"""D1 + D3 through the strict readers (Addendum L4): the HTML is read as text, an event becomes a price event only when a strict reader resolves it, a missing document leaves it
unresolved and counted, and a resolved event reaches the outcome."""
import csv
import gzip
import json

import pytest

from rebuild_harness import daily_prices as dp, delisting_inputs as di, outcomes
from rebuild_harness.tests.test_daily_prices import run, write
from valuation.common import DataNotPresent
from valuation.pit_data import PitData

CASH_8K = "<html><body><p>At the Effective Time each share of common stock was converted into the right to receive <b>$45.00</b> in cash, without interest.</p></body></html>"
STOCK_8K = "<html><body>Each share was converted into the right to receive $10.00 in cash and 0.5 shares of the Parent common stock (the exchange ratio).</body></html>"
BK_8K = "<html><body>Under the plan, all existing common stock will be cancelled and holders of common stock will not receive any distribution.</body></html>"
TABLE_8K = "<html><body><table><tr><td>Cash consideration:</td><td>$</td><td>12.50</td><td>per share in cash</td></tr></table> receive</body></html>"


def ev(cik, cls, date, accession, items, form="8-K"):
    return {"cik": cik, "date": date, "class": cls, "name": "X", "evidence": [{"form": "25", "date": date, "items": [], "accession": "0-25"},
                                                                                {"form": form, "date": date, "items": items, "accession": accession}]}


def build(tmp_path, events, docs, extra_manifest=()):
    """A D1 folder (events.json, event_8k.csv.gz) and a D3 folder (documents and _manifest.jsonl).  docs: {(cik, accession): html or None (listed, not downloaded)}."""
    d1, d3 = tmp_path / "d1", tmp_path / "d3"
    d1.mkdir()
    d3.mkdir()
    (d1 / "events.json").write_text(json.dumps(events), encoding="utf-8")
    rows = []
    with open(d3 / "_manifest.jsonl", "w", encoding="utf-8") as m:
        for (cik, acc), html in docs.items():
            rows.append({"cik": cik, "event_class": "x", "event_date": "2023-06-01", "accession": acc, "form": "8-K", "filed": "2023-06-01", "accepted": "", "items": "2.01", "primary_doc": "d8k.htm"})
            if html is None:
                continue                                       # listed in D1, not in the D3 manifest: a download in progress
            (d3 / cik / acc).mkdir(parents=True)
            (d3 / cik / acc / "d8k.htm").write_text(html, encoding="utf-8")
            (d3 / cik / acc / "dex99.htm").write_text("<p>$1.00 per share in cash $2.00 per share</p>", encoding="utf-8")      # an exhibit that would make the reader refuse: not read
            m.write(json.dumps({"cik": cik, "accession": acc, "form": "8-K", "status": "ok", "files": [{"name": "d8k.htm", "status": "ok", "bytes": 1}, {"name": "dex99.htm", "status": "ok", "bytes": 1}]}) + "\n")
        for x in extra_manifest:
            m.write(json.dumps(x) + "\n")
    with gzip.open(d1 / "event_8k.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cik", "event_class", "event_date", "accession", "form", "filed", "accepted", "items", "primary_doc"])
        w.writeheader()
        w.writerows(rows)
    return di.EventIndex(d1), di.DelistingDocs(d3)


def test_html_becomes_visible_text():
    t = di.html_to_text(b"<html><head><style>p{color:red}</style><script>var x='$9 per share in cash';</script></head><body><p>Pay&nbsp;<b>$45.00</b> in&#160;cash &amp; more</p></body></html>")
    assert t == "Pay $45.00 in cash & more"
    assert "$ 12.50" in di.html_to_text(TABLE_8K.encode())


def test_events_resolve_only_through_the_strict_readers_and_only_from_the_item_8k_primary_document(tmp_path):
    events = [ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01", "3.01"]),
              ev("0000000002", "acquisition_completed", "2023-06-01", "A-2", ["2.01"]),
              ev("0000000003", "bankruptcy", "2023-06-01", "A-3", ["1.03"]),
              ev("0000000004", "delisted_other", "2023-06-01", "A-4", []),
              ev("0000000005", "acquisition_completed", "2023-06-01", "A-5", ["2.01"])]
    idx, docs = build(tmp_path, events, {("0000000001", "A-1"): CASH_8K, ("0000000002", "A-2"): STOCK_8K, ("0000000003", "A-3"): BK_8K, ("0000000005", "A-5"): None})
    tk = {"0000000001": ["AAA"], "0000000002": ["BBB"], "0000000003": ["CCC"], "0000000004": ["DDD"], "0000000005": ["EEE", "EEEW"]}
    pe, rep = di.build_price_events(idx, docs, lambda c: tk.get(c, []), since="2023-01-01")
    assert pe["AAA"]["type"] == "acquisition" and pe["AAA"]["cash_per_share"] == 45.0         # the exhibit's $1.00 / $2.00 are not read
    assert pe["BBB"]["type"] == "unresolved_acquisition_completed"                              # stock words: the strict reader declines
    assert pe["CCC"]["type"] == "bankruptcy"
    assert pe["DDD"]["type"] == "unresolved_delisted_other"                                     # no reader for this class
    assert pe["EEE"]["type"] == "unresolved_acquisition_completed" and pe["EEEW"] is pe["EEE"]  # document not downloaded: unresolved, never "no cash"
    assert rep["resolved"] == {"acquisition_completed": 1, "bankruptcy": 1} and rep["missing_documents"] == 1
    assert rep["events"] == {"acquisition_completed": 3, "bankruptcy": 1, "delisted_other": 1}
    assert rep["unresolved_reason"]["class_has_no_reader"] == 1 and sum(rep["unresolved_reason"].values()) == 3


def test_a_partial_text_is_never_read_and_an_event_with_no_matching_8k_is_unresolved(tmp_path):
    e = ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01"])
    e["evidence"].append({"form": "8-K", "date": "2023-06-02", "items": ["2.01"], "accession": "A-1b"})          # a second 2.01 8-K whose document is missing
    idx, docs = build(tmp_path, [e], {("0000000001", "A-1"): CASH_8K, ("0000000001", "A-1b"): None})
    text, why = di.event_text(e, idx, docs)
    assert text is None and why == "accession_not_in_d3_manifest"
    e2 = ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["3.01"])                                    # no Item 2.01 8-K among the evidence
    assert di.event_text(e2, idx, docs) == (None, "no_item_2.01_8k_in_the_evidence")
    assert di.event_text(ev("0000000001", "delisted_other", "2023-06-01", "A-1", ["2.01"]), idx, docs) == (None, "class_has_no_reader")
    # the same 8-K listed twice in the evidence is read once
    e3 = ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01"])
    e3["evidence"].append(dict(e3["evidence"][1]))
    assert di.event_text(e3, idx, docs)[0].count("$45.00") == 1


def test_without_a_documents_folder_every_event_is_unresolved(tmp_path):
    idx, _docs = build(tmp_path, [ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01"])], {("0000000001", "A-1"): CASH_8K})
    pe, rep = di.build_price_events(idx, None, lambda c: ["AAA"], since="2023-01-01")
    assert pe["AAA"]["type"] == "unresolved_acquisition_completed" and rep["resolved"] == {}


def test_the_window_of_events(tmp_path):
    events = [ev("0000000001", "acquisition_completed", "2019-06-01", "A-1", ["2.01"]), ev("0000000002", "acquisition_completed", "2023-06-01", "A-2", ["2.01"])]
    idx, docs = build(tmp_path, events, {("0000000001", "A-1"): CASH_8K, ("0000000002", "A-2"): CASH_8K})
    pe, _ = di.build_price_events(idx, docs, lambda c: {"0000000001": ["OLD"], "0000000002": ["NEW"]}[c], since="2023-01-01")
    assert set(pe) == {"NEW"}
    pe, _ = di.build_price_events(idx, docs, lambda c: {"0000000001": ["OLD"], "0000000002": ["NEW"]}[c], since="2019-01-01", until="2020-12-31")
    assert set(pe) == {"OLD"}


def test_completeness_says_whether_d3_holds_what_d1_asks_for(tmp_path):
    e = [ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01"]), ev("0000000002", "acquisition_completed", "2023-06-01", "A-2", ["2.01"])]
    idx, docs = build(tmp_path, e, {("0000000001", "A-1"): CASH_8K, ("0000000002", "A-2"): None})
    c = di.completeness(idx, docs, since="2023-01-01")
    assert c["accessions_wanted"] == 2 and c["with_document"] == 1 and c["not_downloaded"] == 1 and c["complete"] is False and c["first_missing"][0][1] == "A-2"
    # a fetch that failed for good (the filing has no document) is recorded, not "missing": the set is complete
    (tmp_path / "d3" / "_manifest.jsonl").write_text((tmp_path / "d3" / "_manifest.jsonl").read_text(encoding="utf-8") +
                                                       json.dumps({"cik": "0000000002", "accession": "A-2", "form": "8-K", "status": "http_404", "files": []}) + "\n", encoding="utf-8")
    c = di.completeness(idx, di.DelistingDocs(tmp_path / "d3"), since="2023-01-01")
    assert c["complete"] is True and c["fetch_failed"] == 1 and c["with_document"] == 1
    assert di.completeness(idx, docs, since="2024-01-01")["accessions_wanted"] == 0                       # event dates before `since` are not asked for


def test_the_inputs_must_exist(tmp_path):
    with pytest.raises(DataNotPresent, match="D1 event index"):
        di.EventIndex(tmp_path)
    (tmp_path / "events.json").write_text(json.dumps([{"cik": "1"}]), encoding="utf-8")
    with pytest.raises(DataNotPresent, match="lack cik/date/class/evidence"):
        di.EventIndex(tmp_path)
    with pytest.raises(DataNotPresent, match="D3 manifest"):
        di.DelistingDocs(tmp_path)


def _world(tmp_path, price_events, name="d5"):
    d5 = tmp_path / name
    d5.mkdir()
    a = run("2023-01-02", 60, 100.0, 1.0)                    # last bar 2023-03-02; entry 2023-01-11 for a decision on 2023-01-10
    write(d5, "AAA", a)
    write(d5, "SPY", run("2023-01-02", 400, 300.0, 0.0))
    return PitData("unused", price_source=dp.LazyDailyPriceSource(d5, delistings=price_events))


def test_a_resolved_event_reaches_the_outcome_and_an_unresolved_one_gets_three_bounds(tmp_path):
    cash = {"AAA": {"date": "2023-03-03", "type": "acquisition", "cash_per_share": 200.0}}
    o = outcomes.horizon_outcome(_world(tmp_path, cash), "AAA", "2023-01-10", 3)
    # entry: the open of 2023-01-11 = 109 - 0.5; the last bar (day 59, close 100 + 59 = 159) scaled by 200 / 159: 200 / 108.5
    assert o["status"] == "delisted_acquisition" and o["ret"] == pytest.approx(200.0 / 108.5 - 1.0) and o["bounds"]["minus100"] == o["bounds"]["excluded"] == o["excess"]
    un = {"AAA": {"date": "2023-03-03", "type": "unresolved_acquisition_completed"}}
    o = outcomes.horizon_outcome(_world(tmp_path, un, "d5b"), "AAA", "2023-01-10", 3)
    bench = 300.0 / 299.5 - 1.0                                # the benchmark enters at the next session's open (300 - 0.5) and is read at the close (300)
    assert o["status"] == "OUTCOME_UNOBSERVABLE" and o["bounds"]["excluded"] is None and o["bounds"]["minus100"] == pytest.approx(-1.0 - bench) and o["bounds"]["last_close"] == pytest.approx(159.0 / 108.5 - 1.0 - bench)


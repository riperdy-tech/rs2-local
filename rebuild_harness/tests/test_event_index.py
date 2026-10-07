"""The all-events D1 index (Addendum P4): every exit event of each company, built from a submissions archive into a new folder next to D1's first-event files."""
import csv
import gzip
import json
import zipfile

import pytest

from rebuild_harness import delisting_inputs as di, delistings as D, event_index as ei
from valuation.common import DataNotPresent


def sub(forms, name="X"):
    return {"name": name, "filings": {"recent": {"form": [f[0] for f in forms], "filingDate": [f[1] for f in forms], "items": [f[2] if len(f) > 2 else "" for f in forms],
                                                  "accessionNumber": [f"{name}-{i}" for i in range(len(forms))], "acceptanceDateTime": [f[1] + "T12:00:00.000Z" for f in forms],
                                                  "primaryDocument": [f"doc{i}.htm" for i in range(len(forms))]}}}


COMPANIES = {
    # 1: a Form 25 for notes (the company kept reporting), then the common stock bought for cash
    "0000000001": sub([("10-K", "2019-03-01"), ("25", "2020-01-02"), ("10-K", "2021-03-01"), ("8-K", "2022-02-10", "2.01,3.01"), ("25", "2022-03-01"), ("15-12B", "2022-03-08")], "A"),
    # 2: one event only
    "0000000002": sub([("10-K", "2019-03-01"), ("25", "2020-06-02")], "B"),
    # 3: Item 1.03 and no exit record
    "0000000003": sub([("8-K", "2019-01-15", "1.03")], "C"),
    # 4: no event at all (not in D1)
    "0000000004": sub([("10-K", "2019-03-01")], "D"),
}


def make_zip(tmp_path):
    z = tmp_path / "subs.zip"
    with zipfile.ZipFile(z, "w") as zz:
        for cik, doc in COMPANIES.items():
            zz.writestr(f"CIK{cik}.json", json.dumps(doc))
    return z


def make_d1(tmp_path):
    """D1 as built before P4: the first event per company and the 8-K rows of those events."""
    d1 = tmp_path / "d1"
    d1.mkdir()
    events, rows = [], []
    for cik, doc in COMPANIES.items():
        filings = D.filings_of([doc])
        e = D.classify_company(cik, filings)
        if e:
            e["name"] = doc["name"]
            events.append(e)
            r = list(ei._rows_of([doc]))
            rows += [dict(zip(ei.COLUMNS, x)) for x in ei.eight_k_rows(sorted(r, key=lambda x: x[2]), e)]
    (d1 / "events.json").write_text(json.dumps(events), encoding="utf-8")
    with gzip.open(d1 / "event_8k.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ei.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return d1


def test_the_index_holds_every_exit_event_keeps_d1_first_events_unchanged_and_adds_the_8k_rows_of_the_new_events(tmp_path):
    d1 = make_d1(tmp_path)
    out = tmp_path / "idx"
    man = ei.build_all_events_index(make_zip(tmp_path), d1, out, workers=1)
    assert (out / "events.json").read_bytes() == (d1 / "events.json").read_bytes()                                          # D1's first events: byte for byte
    idx = di.EventIndex(out)
    assert idx.has_all_events and len(idx.events) == 3 and len(idx.all_events) == 4
    got = [(e["cik"], e["date"], e["class"]) for e in idx.all_events]
    assert got == [("0000000001", "2020-01-02", "exit_record_still_reporting"), ("0000000001", "2022-03-01", "acquisition_completed"),
                   ("0000000002", "2020-06-02", "delisted_other"), ("0000000003", "2019-01-15", "bankruptcy_no_exit_record")]
    assert all(e["name"] for e in idx.all_events)
    # D1 held company 1's first event (the notes): the 2.01/3.01 8-K of 2022 is outside that event's window and so not in D1's rows; the all-events index adds it
    d1_idx = di.EventIndex(d1)
    assert ("0000000001", "A-3") not in d1_idx.eight_k and ("0000000001", "A-3") in idx.eight_k and idx.primary_doc[("0000000001", "A-3")] == "doc3.htm"
    assert idx.eight_k[("0000000001", "A-3")]["event_class"] == "acquisition_completed" and idx.eight_k[("0000000001", "A-3")]["event_date"] == "2022-03-01"
    assert man["added_event_8k_rows"] == 1 and man["all_events"] == 4 and man["d1_companies"] == 3 and man["d1_first_event_reproduced_with_identical_evidence"] == 3
    assert man["d1_first_event_differs"] == 0 and man["events_per_company"] == {"1": 2, "2": 1}
    assert idx.info()["all_events"] == 4 and idx.info()["all_events_sha256"] == idx.all_events_sha256
    # an index folder with only D1's files falls back to D1's events
    assert di.EventIndex(d1).has_all_events is False and di.EventIndex(d1).all_events == di.EventIndex(d1).events


def test_an_existing_non_empty_output_folder_is_refused_and_nothing_is_overwritten(tmp_path):
    d1 = make_d1(tmp_path)
    out = tmp_path / "idx"
    out.mkdir()
    (out / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(DataNotPresent, match="new folder"):
        ei.build_all_events_index(make_zip(tmp_path), d1, out, workers=1)
    assert (out / "keep.txt").read_text(encoding="utf-8") == "keep" and sorted(p.name for p in out.iterdir()) == ["keep.txt"]


def test_a_company_of_d1_that_the_archive_lacks_is_refused(tmp_path):
    d1 = make_d1(tmp_path)
    z = tmp_path / "short.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("CIK0000000001.json", json.dumps(COMPANIES["0000000001"]))
    with pytest.raises(DataNotPresent, match="not in"):
        ei.build_all_events_index(z, d1, tmp_path / "idx2", workers=1)


def test_older_submission_pages_are_merged_with_the_main_file_first(tmp_path):
    z = tmp_path / "paged.zip"
    main = sub([("25", "2022-03-01"), ("15-12B", "2022-03-05")], "P")
    main["filings"]["files"] = [{"name": "CIK0000000001-submissions-001.json"}]
    older = {"form": ["25", "10-K"], "filingDate": ["2019-01-10", "2018-11-01"], "items": ["", ""], "accessionNumber": ["old25", "oldk"], "acceptanceDateTime": ["", ""], "primaryDocument": ["", ""]}
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("CIK0000000001.json", json.dumps(main))
        zz.writestr("CIK0000000001-submissions-001.json", json.dumps(older))
    d1 = tmp_path / "d1"
    d1.mkdir()
    first = D.classify_company("0000000001", D.filings_of([main, older]))
    first["name"] = "P"
    (d1 / "events.json").write_text(json.dumps([first]), encoding="utf-8")
    with gzip.open(d1 / "event_8k.csv.gz", "wt", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=ei.COLUMNS).writeheader()
    ei.build_all_events_index(z, d1, tmp_path / "out", workers=1)
    idx = di.EventIndex(tmp_path / "out")
    assert [(e["date"], e["class"]) for e in idx.all_events] == [("2019-01-10", "delisted_other"), ("2022-03-01", "delisted_other")]       # the older page's record is an event of its own (nothing periodic follows it here)

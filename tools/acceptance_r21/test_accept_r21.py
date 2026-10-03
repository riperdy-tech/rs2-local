"""Proves revision 21's acceptance tooling on synthetic data: the SEC prefetch and its census, the R3 refusal census and the Q2 round trip. Nothing here is
an acceptance run, nothing here touches the network.

Run (from the repository root):  python -m pytest tools/acceptance_r21/test_accept_r21.py -q -p no:cacheprovider --confcutdir tools/acceptance_r21
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
for p in (str(TREE), str(TREE / "tools" / "audit_202608"), str(TREE / "tools" / "acceptance_r18"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import prefetch_sec  # noqa: E402
import q2_round_trip  # noqa: E402
import r3_census  # noqa: E402
import sec_primary as sp  # noqa: E402

A1 = "0000123456-26-000010"
URL1 = "https://www.sec.gov/Archives/edgar/data/123456/000012345626000010/ex991.htm"
ITEM = {"id": "P1", "type": "earnings_release", "form": "8-K", "accession": A1, "filed": "2026-07-30", "period": "Q2 2026", "title": "8-K Item 2.02 earnings release (EX-99.1)",
        "url": URL1, "text": "ACME reports second quarter 2026 results. Revenue of $1,234.5 million grew 12%, led by the Industrial segment of the company.\n"
                              "Industrial | $1,234 | 1,100 | and a table row of some length to cite whole"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "CACHE", tmp_path / "sec_primary")
    monkeypatch.setattr(sp, "THROTTLE_S", 0.0)
    monkeypatch.setattr(sp, "_http_get", lambda url, timeout=60: (_ for _ in ()).throw(OSError("offline")))


def pack(items):
    return "# DATA PACK - ACME   (pack revision 21)\n\n" + "\n".join(sp.section_lines({"items": items, "annotations": []})) + "\n\n## DATA 12 - X\n- y\n"


# ---- the prefetch and its census ----------------------------------------------------------------------------------------------------------

def test_census_counts_coverage_sizes_and_reasons_without_names():
    res = [{"ticker": "AAA", "items": [{"type": "earnings_release", "chars": 13000}, {"type": "segment_table", "chars": 4000}], "annotations": [
               "The 10-Q filed 2026-08-01 (accession 0000000001-26-000001): the segment table is not filed as a separate report."], "reason": None},
           {"ticker": "BBB", "items": [{"type": "earnings_release", "chars": 9000}, {"type": "other_8k", "chars": 2500}, {"type": "other_8k", "chars": 2400}],
            "annotations": ["x.pdf (a PDF exhibit of the same 8-K, accession 0000000001-26-000002) is a PDF and is not included."], "reason": None},
           {"ticker": "CCC", "items": [], "annotations": ["No 8-K Item 2.02 earnings release on or before 2026-10-03."], "reason": "no 8-K Item 2.02, 10-Q, 10-K or recent 8-K text on or before 2026-10-03"},
           {"ticker": "DDD", "items": [], "annotations": [], "reason": "no CIK"}]
    c = prefetch_sec.census(res)
    assert c["names"] == 4 and c["with_items"] == 2 and c["without_items"] == 2 and c["item_counts"] == {"2": 1, "3": 1, "0": 2}
    assert c["by_type"]["earnings_release"]["names"] == 2 and c["by_type"]["earnings_release"]["share"] == 0.5
    assert c["by_type"]["other_8k"] == {"names": 1, "share": 0.25, "chars": c["by_type"]["other_8k"]["chars"]} and c["by_type"]["other_8k"]["chars"]["n"] == 2
    assert c["by_type"]["other_exhibit"]["chars"] is None and c["total_chars"]["n"] == 2 and c["total_chars"]["max"] == 17000 and c["total_chars"]["min"] == 13900
    assert c["reasons"] == {"no 8-K Item 2.02, 10-Q, 10-K or recent 8-K text on or before <date>": 1, "no CIK": 1}
    assert "the segment table is not filed as a separate report." in " ".join(c["annotations"]) and sum(c["annotations"].values()) == 3
    assert not any(t in json.dumps(c) for t in ("AAA", "BBB", "CCC", "DDD"))                # counts only, never a ticker


def test_the_prefetch_builds_every_name_and_returns_rows_with_no_network(monkeypatch, tmp_path):
    files = {f"https://www.sec.gov/Archives/edgar/data/123456/000012345626000010/{A1}.txt":
             "<DOCUMENT>\n<TYPE>EX-99.1\n<FILENAME>ex991.htm\n<TEXT>\n<html><body><p>ACME reports second quarter 2026 results.</p></body></html>\n</TEXT>\n</DOCUMENT>"}
    monkeypatch.setattr(sp, "_http_get", lambda url, timeout=60: files[url].encode())
    monkeypatch.setattr(sp, "_subs", lambda cik: {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-07-30"], "reportDate": [""], "items": ["2.02"],
                                                                         "accessionNumber": [A1], "primaryDocument": ["x.htm"]}}})
    rows = prefetch_sec.run(["ACME", "NOPE"], {"ACME": "123456"}, "2026-10-03", cache_dir=None, log=lambda *_: None)
    assert [r["ticker"] for r in rows] == ["ACME", "NOPE"] and rows[1]["reason"] == "no CIK" and rows[1]["items"] == []
    assert rows[0]["cik"] == "0000123456" and [(i["id"], i["type"], i["period"]) for i in rows[0]["items"]] == [("P1", "earnings_release", "Q2 2026")]


def test_the_prefetch_output_must_be_named_private_and_is_never_overwritten(tmp_path, monkeypatch):
    names = tmp_path / "names.txt"
    names.write_text("ACME\n", encoding="utf-8")
    cm = tmp_path / "cik_map.json"
    cm.write_text(json.dumps({"map": {"ACME": "123456"}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        prefetch_sec.main(["--names", str(names), "--cik-map", str(cm), "--asof", "2026-10-03", "--out", str(tmp_path / "result.json")])
    monkeypatch.setattr(sp, "_subs", lambda cik: None)
    out = tmp_path / "result_private.json"
    assert prefetch_sec.main(["--names", str(names), "--cik-map", str(cm), "--asof", "2026-10-03", "--out", str(out), "--cache-dir", str(tmp_path / "c")]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["results"][0]["reason"] == "SEC fetch failed (submissions)"
    with pytest.raises(FileExistsError):
        prefetch_sec.main(["--names", str(names), "--cik-map", str(cm), "--asof", "2026-10-03", "--out", str(out), "--cache-dir", str(tmp_path / "c")])


# ---- R3 --------------------------------------------------------------------------------------------------------------------------------

def _snapshot(d, name, sample, queries):
    f = d / name / f"sample{sample}_research"
    f.mkdir(parents=True)
    calls = [{"tool": "search_web", "query": q} for q in queries] + [{"tool": "fetch_page", "params": {"url": "u"}}]
    (f / "_research_snapshot.json").write_text(json.dumps({"calls": calls}), encoding="utf-8")


def test_r3_census_counts_by_rule_and_keeps_the_lists_private(tmp_path):
    cons = tmp_path / "consensus"
    _snapshot(cons, "ACME_20261003_080000", 1, ["Acme Q2 2026 earnings release", "Acme revenue $1,234.5 million", "Acme city council vote", "Acme Q2 2026 revenue $1,234.5 million results"])
    _snapshot(cons, "ACME_20261003_080000", 2, ["Acme partner announcement"])
    _snapshot(cons, "ZZZZ_20261003_090000", 1, ["Zzzz earnings release Q2 2026"])
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "ACME.md").write_text(pack([ITEM]), encoding="utf-8")                       # ZZZZ has no pack: its queries are all allowed, and it is counted
    qs = r3_census.stage1_queries(cons)
    assert {t: len(v) for t, v in qs.items()} == {"ACME": 5, "ZZZZ": 1}
    private, pub = r3_census.census(qs, packs)
    assert pub["queries"] == 6 and pub["refused"] == 3 and pub["allowed"] == 3 and pub["by_rule"] == {"figure": 1, "document": 1, "figure+document": 1}
    assert pub["names"] == {"n1": {"queries": 5, "refused": 3, "by_rule": {"figure": 1, "document": 1, "figure+document": 1}, "primary_items": 1},
                            "n2": {"queries": 1, "refused": 0, "by_rule": {"figure": 0, "document": 0, "figure+document": 0}, "primary_items": 0}}
    assert pub["names_without_primary_items"] == 1 and pub["unique_queries"] == 6
    assert "ACME" not in json.dumps(pub) and "ZZZZ" not in json.dumps(pub)
    acme = private["names"]["ACME"]
    assert [r["query"] for r in acme["refused"]] == ["Acme Q2 2026 earnings release", "Acme revenue $1,234.5 million", "Acme Q2 2026 revenue $1,234.5 million results"]
    assert acme["refused"][1]["figure_tokens"] == ["1234.5"] and acme["refused"][0]["items"] == ["P1"]
    assert [r["query"] for r in acme["allowed"]] == ["Acme city council vote", "Acme partner announcement"]
    assert acme["allowed"][0] == {"sample": 1, "query": "Acme city council vote", "dedup": False, "document_word": False, "period": False, "figure_not_in_items": []}
    # the script: the lists file must say `_private`, and an existing file is never overwritten
    args = ["--consensus-dir", str(cons), "--packs", str(packs), "--private", str(tmp_path / "lists_private.json"), "--public", str(tmp_path / "counts.json")]
    assert r3_census.main(args) == 0
    with pytest.raises(FileExistsError):
        r3_census.main(args)
    with pytest.raises(SystemExit):
        r3_census.main(["--consensus-dir", str(cons), "--packs", str(packs), "--private", str(tmp_path / "lists.json"), "--public", str(tmp_path / "c2.json")])


def test_r3_refuses_a_directory_holding_two_runs_of_one_name(tmp_path):
    _snapshot(tmp_path, "ACME_20261003_080000", 1, ["q"])
    _snapshot(tmp_path, "ACME_20261003_090000", 1, ["q"])
    with pytest.raises(SystemExit):
        r3_census.stage1_queries(tmp_path)


# ---- Q2 --------------------------------------------------------------------------------------------------------------------------------

def test_the_round_trip_passes_on_a_pack_and_names_the_failing_item_otherwise(monkeypatch, tmp_path, capsys):
    n, bad = q2_round_trip.round_trip(pack([ITEM]))
    assert n > 4 and bad == []
    (tmp_path / "ACME.md").write_text(pack([ITEM]), encoding="utf-8")
    assert q2_round_trip.main(["--packs", str(tmp_path)]) == 0 and "PASS  Q2 round trip" in capsys.readouterr().out
    import crux_check
    monkeypatch.setattr(crux_check, "_found", lambda quote, text: False)
    n, bad = q2_round_trip.round_trip(pack([ITEM]))
    assert bad and bad[0][0] == "P1" and bad[0][1] == "PRIMARY P#"
    assert q2_round_trip.main(["--packs", str(tmp_path)]) == 1
    assert q2_round_trip.main(["--packs", str(tmp_path / "empty")]) == 1                    # no pack at all is not a pass

"""packet: the input contract m3m.packet.v1 (SPEC §3, gate M-P4 negatives). Offline: a synthetic store and a throwaway git repository
in tmp_path; the FilingSummary and the balance-sheet R report are trimmed real bytes of AMD's 10-Q 0000002488-26-000123."""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sec_primary
from qwen_c import packet, sec_store
from sec_guidance import UA

FIX = Path(__file__).resolve().parent / "fixtures"
CIK = "0000000123"
T = "2026-10-28T20:00:00Z"
COMMIT_DATE = "2026-10-01T00:00:00+00:00"

A10K = "0000000123-26-000010"
AQ = "0000000123-26-000050"
AREL = "0000000123-26-000051"
A502 = "0000000123-26-000060"
A801 = "0000000123-26-000070"
A701 = "0000000123-26-000072"
ANEW = "0000000123-26-000080"
AOLD = "0000000123-26-000030"


def base(acc):
    return f"https://www.sec.gov/Archives/edgar/data/123/{acc.replace('-', '')}"


SUBS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"


def filler(tag, n):
    """About n characters of distinct sentences, so a section's length is under the test's control."""
    out, i = [], 0
    while sum(len(s) + 1 for s in out) < n:
        out.append(f"{tag} sentence {i} describes the business in plain words and states a figure of {i}.{i % 10} million.")
        i += 1
    return " ".join(out)


def paras(tag, n, size=400):
    return "".join(f"<p>{filler(f'{tag}-{k}', size)}</p>" for k in range(max(1, n // size)))


def tenk_html():
    toc = ("<table>"
           "<tr><td>Item 1.</td><td>Business</td><td>3</td></tr>"
           "<tr><td>Item 1A.</td><td>Risk Factors</td><td>9</td></tr>"
           "<tr><td>Item 1B.</td><td>Unresolved Staff Comments</td><td>20</td></tr>"
           "<tr><td>Item 7.</td><td>Management’s Discussion and Analysis</td><td>25</td></tr>"
           "<tr><td>Item 7A.</td><td>Quantitative and Qualitative Disclosures About Market Risk</td><td>30</td></tr>"
           "<tr><td>Item 8.</td><td>Financial Statements</td><td>31</td></tr></table>")
    body = ("<p>PART I</p>"
            "<p><b>Item 1. Business</b></p><p>BUSINESS_START the company sells widgets.</p>" + paras("biz", 3000) +
            "<p>Item 1A. Risk Factors</p>" + paras("risk", 2400) +
            "<p>Item 1A. Risk Factors (continued)</p>" + paras("risk2", 1200) + "<p>RISK_TAIL the last risk.</p>"
            "<p>Item 1B. Unresolved Staff Comments</p><p>None.</p>"
            "<p>PART II</p>"
            "<p>Item 7.</p><p>Management’s Discussion and Analysis of Financial Condition and Results of Operations</p>"
            + paras("mdna", 3000) +
            "<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p><p>Rates.</p>"
            "<p>Item 8. Financial Statements</p><p>See the statements.</p>")
    return ("<html><body><p>FORM 10-K</p>" + toc + body + "</body></html>").encode("cp1252")


def tenq_html():
    toc = ("<table><tr><td>Part I</td></tr>"
           "<tr><td>Item 2 | Management's Discussion and Analysis</td><td>12</td></tr>"
           "<tr><td>Item 3</td><td>Quantitative and Qualitative Disclosures</td><td>18</td></tr>"
           "<tr><td>Item 1A</td><td>Risk Factors</td><td>20</td></tr>"
           "<tr><td>Item 2</td><td>Unregistered Sales</td><td>21</td></tr></table>")
    body = ("<p>PART I. FINANCIAL INFORMATION</p><p>ITEM 1. FINANCIAL STATEMENTS</p>" + paras("fs", 2000) +
            "<p>ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</p>"
            "<p>QMDNA_START quarterly review.</p>" + paras("qmdna", 2500) +
            "<p>ITEM 3. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK</p><p>Rates.</p>"
            "<p>PART II. OTHER INFORMATION</p><p>ITEM 1. LEGAL PROCEEDINGS</p><p>None.</p>"
            "<p>ITEM 1A. RISK FACTORS</p><p>There have been no material changes to our risk factors.</p>"
            "<p>ITEM 2. UNREGISTERED SALES OF EQUITY SECURITIES</p><p>None.</p><p>ITEM 6. EXHIBITS</p>")
    return ("<html><body>" + toc + body + "</body></html>").encode("utf-8")


def eightk_txt(acc, docs):
    """An EDGAR full submission .txt: [(type, filename, html)]."""
    parts = [f"<SEC-DOCUMENT>{acc}.txt\n<SEC-HEADER>\nACCESSION NUMBER: {acc}\n</SEC-HEADER>\n"]
    for n, (t, f, h) in enumerate(docs, 1):
        parts.append(f"<DOCUMENT>\n<TYPE>{t}\n<SEQUENCE>{n}\n<FILENAME>{f}\n<DESCRIPTION>{t}\n<TEXT>\n{h}\n</TEXT>\n</DOCUMENT>\n")
    parts.append("</SEC-DOCUMENT>\n")
    return "".join(parts).encode("utf-8")


def r_table(title, rows):
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table class=\"report\"><tr><th>{title}</th><th>Jun. 27, 2026</th></tr>{trs}</table></body></html>".encode()


def submissions(extra=()):
    rows = [  # newest first, as SEC lists them
        (ANEW, "8-K", "2026-10-28", "2026-10-28T12:00:00.000Z", "", "2.02,9.01", "anew.htm"),
        (A801, "8-K", "2026-10-20", "2026-10-20T14:00:00.000Z", "2026-10-20", "8.01,9.01", "e801.htm"),
        (A701, "8-K", "2026-10-01", "2026-10-01T14:00:00.000Z", "2026-10-01", "7.01,9.01", "e701.htm"),
        (A502, "8-K", "2026-09-15", "2026-09-15T14:00:00.000Z", "2026-09-14", "5.02", "e502.htm"),
        (AREL, "8-K", "2026-08-05", "2026-08-05T20:01:00.000Z", "2026-08-05", "2.02,9.01", "rel.htm"),
        (AQ, "10-Q", "2026-08-05", "2026-08-05T20:00:00.000Z", "2026-06-30", "", "tq-20260630.htm"),
        (AOLD, "8-K", "2026-05-01", "2026-05-01T14:00:00.000Z", "2026-05-01", "1.01", "old.htm"),
        (A10K, "10-K", "2026-02-20", "2026-02-20T21:00:00.000Z", "2025-12-31", "", "tk-20251231.htm"),
    ] + list(extra)
    keys = ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "reportDate", "items", "primaryDocument")
    recent = {k: [r[i] for r in rows] for i, k in enumerate(keys)}
    return json.dumps({"cik": "123", "name": "Test Co", "filings": {"recent": recent, "files": []}}).encode()


def documents():
    q = base(AQ)
    rel = ("<html><body><p>Test Co Reports Second Quarter 2026 Results</p><p>RELEASE_START revenue was $1,234.5 million.</p>"
           + paras("rel", 3000) + "<p>Outlook: the company expects revenue of $1.3 billion.</p></body></html>")
    return {
        SUBS_URL: submissions(),
        f"{q}/FilingSummary.xml": (FIX / "amd_10q_FilingSummary_trimmed.xml").read_bytes(),
        f"{q}/R4.htm": (FIX / "amd_10q_R4.htm").read_bytes(),
        f"{q}/R2.htm": r_table("Condensed Consolidated Statements of Operations", [["Net revenue", "$ 7,685"], ["Net income", "872"]]),
        f"{q}/R6.htm": r_table("Condensed Consolidated Statements of Cash Flows", [["Net cash from operations", "1,500"]]),
        f"{base(A10K)}/tk-20251231.htm": tenk_html(),
        f"{q}/tq-20260630.htm": tenq_html(),
        f"{base(AREL)}/{AREL}.txt": eightk_txt(AREL, [("8-K", "f8k.htm", "<p>Item 2.02 Results.</p>"), ("EX-99.1", "ex991.htm", rel)]),
        f"{base(A502)}/{A502}.txt": eightk_txt(A502, [("8-K", "f502.htm", "<p>UNITED STATES</p><p>FORM 8-K</p><p>Item 5.02 Departure of "
                                                     "Directors.</p><p>E502_TEXT " + filler("e502", 1400) + "</p>")]),
        f"{base(A801)}/{A801}.txt": eightk_txt(A801, [("8-K", "f801.htm", "<p>Item 8.01 Other Events.</p>"),
                                                     ("EX-99.1", "ex801.htm", "<p>E801_TEXT " + filler("e801", 1500) + "</p>")]),
    }


def make_store(root, docs=None):
    for url, data in (docs if docs is not None else documents()).items():
        sec_store._store(Path(root), url, data, 200, UA["User-Agent"])
    return Path(root)


def git(repo, *args, date=COMMIT_DATE):
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                          check=True, capture_output=True, env=env).stdout.decode().strip()


def make_repo(root, date=COMMIT_DATE):
    repo = Path(root)
    (repo / "public" / "data").mkdir(parents=True)
    stocks = [{"symbol": "TEST", "name": "Test Co", "price": 12.5, "peRatio": 0, "metrics": {"netIncome": 0.0, "roic": 0.125, "dilution": 0,
               "mScore": None, "quarterlyEps": [0.0, 0.1]}, "reasons": ["ok"]},
              {"symbol": "NOCIK", "name": "No Cik Inc"}, {"symbol": "NOPROF", "name": "No Profile Inc"}, {"symbol": "MOV", "name": "Movado"}]
    factor = {"generated_at": "2026-09-30T00:00:00Z",
              "profiles": {"TEST": {"ticker": "TEST", "z_value": 0.0, "score_door1": 1.5, "nominated_doors": ["DOOR_1_COMPOUNDER"]},
                           "NOCIK": {"ticker": "NOCIK"}, "MOV": {"ticker": "MOV"}}}
    cmap = {"fetched_at": "2026-06-10T00:00:00Z", "map": {"TEST": "0000000123", "NOPROF": "0000000789", "MOV": "0000000456"}}
    (repo / packet.STOCKS_PATH).write_text(json.dumps(stocks), encoding="utf-8")
    (repo / packet.FACTOR_PATH).write_text(json.dumps(factor), encoding="utf-8")
    (repo / packet.CIK_MAP_PATH).write_text(json.dumps(cmap), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    git(repo, "add", "-A", date=date)
    git(repo, "commit", "-q", "-m", "screener output", date=date)
    return repo, git(repo, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path):
    repo, commit = make_repo(tmp_path / "repo")
    store = make_store(tmp_path / "store")
    record = [{"run_id": "r-fail", "verdict": "PASS", "pair": "FAIL", "output_commit": commit},
              {"run_id": "r-ok", "verdict": "PASS", "pair": "PASS", "output_commit": commit}]
    return {"repo": repo, "commit": commit, "store": store, "record": record, "tmp": tmp_path}


def build(w, ticker="TEST", T=T, commit=None, record=None, store=None):
    return packet.build(ticker, T, commit or w["commit"], online=False, verified_record=w["record"] if record is None else record,
                        screener_repo_path=w["repo"], store_root=store or w["store"])


# ---- the acceptance rule (ported from m3l_sec_pit_asof's tests, plus the boundaries) ---------------------------------------------

def eff(raw):
    return packet._z(packet.effective_at(packet.accepted_at(raw)))


def test_after_close_acceptance_requires_next_nyse_open():
    assert eff("2024-11-04T16:15:00") == "2024-11-05T14:30:00Z"


def test_z_clock_uses_the_later_of_the_utc_and_eastern_wall_readings():
    assert packet._z(packet.accepted_at("2024-11-04T16:15:00Z")) == "2024-11-04T21:15:00Z"      # Eastern-wall reading is later
    assert packet._z(packet.accepted_at("2024-11-04T21:15:00Z")) == "2024-11-05T02:15:00Z"
    assert eff("2024-11-04T21:15:00Z") == "2024-11-06T14:30:00Z"      # 21:15 read as Eastern wall is after 17:30: one more session
    assert eff("2025-02-18T22:29:00.000Z") == "2025-02-20T14:30:00Z"  # the UTC reading (17:29 ET) would be one session earlier


def test_1730_et_boundary():
    assert eff("2025-02-18T17:29:59") == "2025-02-19T14:30:00Z"
    assert eff("2025-02-18T17:30:00") == "2025-02-20T14:30:00Z"
    assert eff("2025-02-18T17:31:00") == "2025-02-20T14:30:00Z"
    assert eff("2025-02-18T17:30:00.000Z") == "2025-02-20T14:30:00Z"  # Z: Eastern-wall 17:30 is the later reading


def test_weekend_and_holidays_are_not_sessions():
    assert eff("2026-10-23T16:15:00") == "2026-10-26T13:30:00Z"       # Friday after the close -> Monday
    assert eff("2026-10-23T18:00:00") == "2026-10-27T13:30:00Z"       # Friday after 17:30 -> Tuesday
    assert eff("2026-10-24T11:00:00") == "2026-10-26T13:30:00Z"       # Saturday -> Monday
    assert eff("2026-04-02T16:15:00") == "2026-04-06T13:30:00Z"       # Good Friday 2026-04-03 is a holiday
    assert eff("2026-11-25T10:00:00") == "2026-11-27T14:30:00Z"       # Thanksgiving 2026-11-26; the early-close Friday is a session


def test_acceptance_missing_raises():
    with pytest.raises(ValueError):
        packet.accepted_at("")


# ---- the build ---------------------------------------------------------------------------------------------------------------------

def test_full_build_order_kinds_and_sections(world):
    pk = build(world)
    ev = pk["evidence"]
    assert [(e["fact_id"], e["kind"], e["name"]) for e in ev] == [
        ("S0", "screener_row", "screener_row"),
        ("F1", "statement", "balance_sheet"), ("F2", "statement", "income_statement"), ("F3", "statement", "cash_flows"),
        ("P1", "annual_section", "business"), ("P2", "annual_section", "risk_factors"), ("P3", "annual_section", "mdna"),
        ("P4", "quarterly_section", "quarterly_mdna"), ("P5", "release", "earnings_release"),
        ("P6", "other_8k", "other_8k"), ("P7", "other_8k", "other_8k")]
    by = {e["fact_id"]: e for e in ev}
    assert pk["contract"] == "m3m.packet.v1" and pk["cik"] == CIK and pk["decision_time_utc"] == T
    assert pk["sec_policy"] == "sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1"
    assert pk["screener"]["commit"] == world["commit"] and pk["screener"]["verified_run_id"] == "r-ok"
    assert pk["screener"]["stocks_blob_sha"] == git(world["repo"], "rev-parse", f"HEAD:{packet.STOCKS_PATH}")
    assert pk["screener"]["factor_blob_sha"] == git(world["repo"], "rev-parse", f"HEAD:{packet.FACTOR_PATH}")
    assert "Total assets | 84,464 | 76,926" in by["F1"]["text"]                       # the real R4 report, flattened
    assert by["F1"]["source"] == {"accession": AQ, "url": f"{base(AQ)}/R4.htm"}
    assert by["F2"]["source"]["url"].endswith("/R2.htm") and by["F3"]["source"]["url"].endswith("/R6.htm")
    assert by["P1"]["text"].startswith("Item 1. Business\nBUSINESS_START")              # the real heading, not the contents row
    assert "RISK_TAIL" in by["P2"]["text"]                                               # a running header does not end the section
    assert "Unresolved Staff Comments" not in by["P2"]["text"]
    assert by["P3"]["text"].startswith("Item 7.\nManagement’s Discussion")          # split heading; cp1252 bytes decoded
    assert by["P4"]["text"].startswith("ITEM 2. MANAGEMENT'S DISCUSSION") and "QMDNA_START" in by["P4"]["text"]
    assert by["P5"]["source"]["accession"] == AREL and "RELEASE_START" in by["P5"]["text"]
    assert [by["P6"]["source"]["accession"], by["P7"]["source"]["accession"]] == [A801, A502]    # newest first; 7.01 and >120 d out
    assert by["P6"]["text"].startswith("E801_TEXT") and by["P7"]["text"].startswith("Item 5.02")   # exhibit; 8-K body from its item
    assert by["P1"]["effective_at"] == "2026-02-24T14:30:00Z"            # Fri 21:00 ET (later reading) -> Mon, +1 for after 17:30 -> Tue
    assert by["P1"]["accepted_raw"] == "2026-02-20T21:00:00.000Z" and by["P1"]["period"] == "2025-12-31" and by["P1"]["form"] == "10-K"
    raw = documents()[f"{base(A10K)}/tk-20251231.htm"]
    assert by["P1"]["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert pk["raw_inputs"][0] == {"url": SUBS_URL, "sha256": hashlib.sha256(submissions()).hexdigest()}
    assert {r["url"] for r in pk["raw_inputs"]} == set(documents())                    # every input used, nothing more
    assert f"section_not_found: quarterly_risk_factors {AQ}" in pk["annotations"]      # a short section is not guessed
    assert pk["excluded"] == [{"slot": "release", "accession": ANEW, "form": "8-K", "accepted_raw": "2026-10-28T12:00:00.000Z",
                               "effective_at": "2026-10-29T13:30:00Z"}]


def test_s0_prints_zero_as_zero_and_keeps_both_records(world):
    s0 = build(world)["evidence"][0]
    lines = s0["text"].split("\n")
    for want in ("peRatio: 0", "metrics.netIncome: 0", "metrics.dilution: 0", "metrics.mScore: null", "metrics.roic: 0.125",
                 "metrics.quarterlyEps: [0, 0.1]", "z_value: 0", "score_door1: 1.5", "nominated_doors: [DOOR_1_COMPOUNDER]"):
        assert want in lines
    assert s0["source"]["git_commit"] == world["commit"] and s0["source"]["path"] == [packet.STOCKS_PATH, packet.FACTOR_PATH]
    assert "NOCIK" not in s0["text"]


def test_build_is_deterministic_and_saved_bytes_are_canonical(world):
    a, b = build(world), build(world)
    assert packet.canonical_bytes(a) == packet.canonical_bytes(b)
    out = world["tmp"] / "packets"
    p = packet.save(a, out)
    assert p.name == "TEST_20261028T200000Z.json"
    assert p.read_bytes() == json.dumps(a, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert packet.packet_sha256(a) == hashlib.sha256(p.read_bytes()).hexdigest()
    assert packet.save(b, out) == p                                                    # the same bytes: a no-op
    a["annotations"].append("changed")
    with pytest.raises(packet.PacketError):
        packet.save(a, out)                                                            # never overwritten


def test_a_filing_effective_exactly_at_T_is_eligible(world):
    docs = documents()
    docs[f"{base(ANEW)}/{ANEW}.txt"] = eightk_txt(ANEW, [("EX-99.1", "new.htm", "<p>NEW_RELEASE third quarter results.</p>")])
    store = make_store(world["tmp"] / "store2", docs)
    pk = build(world, T="2026-10-29T13:30:00Z", store=store)
    rel = [e for e in pk["evidence"] if e["kind"] == "release"][0]
    assert rel["source"]["accession"] == ANEW and pk["excluded"] == []
    pk2 = build(world, T="2026-10-29T13:29:59Z", store=store)
    assert [x["accession"] for x in pk2["excluded"]] == [ANEW]


def test_a_missing_raw_input_raises_not_in_store(world):
    docs = documents()
    del docs[f"{base(A801)}/{A801}.txt"]
    with pytest.raises(sec_store.NotInStore):
        build(world, store=make_store(world["tmp"] / "partial", docs))


def test_tampered_stored_bytes_raise_store_corrupt(world):
    sha = hashlib.sha256(tenk_html()).hexdigest()
    (world["store"] / sha).write_bytes(b"tampered")
    with pytest.raises(sec_store.StoreCorrupt):
        build(world)


# ---- refusals --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("t", ["SENEA", "SENEB", "MOV", "MG", "mov"])
def test_excluded_tickers_are_refused_before_anything_is_read(world, t):
    with pytest.raises(packet.PacketRefused) as e:
        packet.build(t, T, world["commit"], online=False, verified_record=world["record"], screener_repo_path=world["tmp"] / "nowhere",
                     store_root=world["tmp"] / "nowhere")
    assert e.value.code == "ticker_excluded"


@pytest.mark.parametrize("rows", [
    [],
    [{"verdict": "FAIL", "pair": "PASS", "output_commit": "<c>"}],
    [{"verdict": "PASS", "pair": "FAIL", "output_commit": "<c>"}],
    [{"verdict": "PASS", "pair": "PASS", "output_commit": "0123456789abcdef"}],
    [{"verdict": "PASS", "pair": "PASS", "output_commit": "<c9>"}],
    [{"verdict": "PASS", "output_commit": "<c>"}],
    {"verdict": "PASS", "pair": "PASS", "output_commit": "<c>"},
])
def test_an_unverified_screener_commit_is_refused(world, rows):
    c = world["commit"]
    sub = lambda v: c if v == "<c>" else (c[:9] if v == "<c9>" else v)
    rows = [{k: sub(v) for k, v in r.items()} for r in rows] if isinstance(rows, list) else {k: sub(v) for k, v in rows.items()}
    with pytest.raises(packet.PacketRefused) as e:
        build(world, record=rows)
    assert e.value.code == "screener_commit_not_verified"


def test_a_ten_hex_prefix_on_a_pass_row_verifies_and_a_short_commit_resolves(world):
    c = world["commit"]
    pk = build(world, commit=c[:12].upper(), record=[{"verdict": "PASS", "pair": "PASS", "output_commit": c[:10], "run_id": "x"}])
    assert pk["screener"]["commit"] == c and pk["screener"]["verified_run_id"] == "x"


def test_a_record_read_from_a_file_path(world):
    p = world["tmp"] / "check.json"
    p.write_text(json.dumps(world["record"]), encoding="utf-8")
    assert build(world, record=str(p))["screener"]["verified_run_id"] == "r-ok"


@pytest.mark.parametrize("ticker,code", [("ZZZZ", "ticker_not_in_stocks"), ("NOCIK", "no_cik"),
                                         ("NOPROF", "ticker_not_in_factor_profiles")])
def test_screener_refusals(world, ticker, code):
    with pytest.raises(packet.PacketRefused) as e:
        build(world, ticker=ticker)
    assert e.value.code == code


def test_a_screener_commit_dated_after_T_is_refused(world):
    with pytest.raises(packet.PacketRefused) as e:
        build(world, T="2026-09-30T23:59:59Z")
    assert e.value.code == "screener_commit_after_T"


@pytest.mark.parametrize("commit", ["abc", "zz" * 10, None])
def test_an_invalid_commit_string_is_refused(world, commit):
    with pytest.raises(packet.PacketRefused) as e:
        packet.build("TEST", T, commit, online=False, verified_record=world["record"], screener_repo_path=world["repo"],
                     store_root=world["store"])
    assert e.value.code == "screener_commit_invalid"


def test_T_must_be_aware_and_whole_seconds(world):
    for bad in ("2026-10-28T20:00:00", "2026-10-28T20:00:00.5Z", datetime(2026, 10, 28, 20)):
        with pytest.raises(ValueError):
            build(world, T=bad)
    assert build(world, T=datetime(2026, 10, 28, 20, tzinfo=timezone.utc))["decision_time_utc"] == T


# ---- the size cap ----------------------------------------------------------------------------------------------------------------

def test_size_cap_trims_in_reverse_list_order_with_annotations(world, monkeypatch):
    full = build(world)
    by = {e["fact_id"]: e for e in full["evidence"]}
    total = sum(len(e["text"]) for e in full["evidence"])

    monkeypatch.setattr(packet, "TOTAL_CAP", total - 100)          # only the oldest other 8-K is cut, by 100 characters
    pk = build(world)
    cut = [e for e in pk["evidence"] if e["source"].get("accession") == A502][0]
    assert sum(len(e["text"]) for e in pk["evidence"]) <= total - 100
    assert sec_primary.OMIT_RE.search(cut["text"])
    assert [a for a in pk["annotations"] if a.startswith("trimmed")] == [
        f"trimmed: other_8k other_8k {A502} to {len(cut['text'])} characters (packet over {total - 100} characters)"]

    cap = total - len(by["P6"]["text"]) - len(by["P7"]["text"]) - 2000     # both 8-Ks go, then the release is cut
    monkeypatch.setattr(packet, "TOTAL_CAP", cap)
    pk = build(world)
    notes = [a for a in pk["annotations"] if a.startswith("trimmed")]
    assert [n.split(" (")[0].rsplit(" to ", 1)[0] for n in notes] == [
        f"trimmed_out: other_8k other_8k {A502}", f"trimmed_out: other_8k other_8k {A801}", f"trimmed: release earnings_release {AREL}"]
    assert [e["fact_id"] for e in pk["evidence"]] == ["S0", "F1", "F2", "F3", "P1", "P2", "P3", "P4", "P5"]
    assert pk["evidence"][-1]["kind"] == "release" and sum(len(e["text"]) for e in pk["evidence"]) <= cap
    assert by["P1"]["text"] == pk["evidence"][4]["text"]                    # earlier items untouched


# ---- statement and section finding -----------------------------------------------------------------------------------------------

def test_pick_statements_on_a_real_filing_summary():
    got = packet.pick_statements((FIX / "amd_10q_FilingSummary_trimmed.xml").read_text(encoding="utf-8"))
    assert got == {"balance_sheet": ("Condensed Consolidated Balance Sheets", "R4.htm"),
                   "income_statement": ("Condensed Consolidated Statements of Operations", "R2.htm"),
                   "cash_flows": ("Condensed Consolidated Statements of Cash Flows", "R6.htm")}


def summary(*names):
    reps = "".join(f"<Report instance=\"x\"><HtmlFileName>R{i}.htm</HtmlFileName><ShortName>{n}</ShortName>"
                   f"<MenuCategory>{'Details' if 'Details' in n else 'Statements'}</MenuCategory></Report>" for i, n in enumerate(names, 2))
    return f"<FilingSummary><MyReports>{reps}</MyReports></FilingSummary>"


def test_income_statement_choice_rules():
    got = packet.pick_statements(summary("Consolidated Statements of Comprehensive Income (Loss)", "Consolidated Balance Sheets",
                                         "Consolidated Balance Sheets (Parenthetical)", "Statements of Cash Flows"))
    assert got["income_statement"][1] == "R2.htm"               # comprehensive-only filer: its single statement
    got = packet.pick_statements(summary("Consolidated Statements of Operations and Comprehensive Loss", "Consolidated Statements of Income (Details)"))
    assert got == {"income_statement": ("Consolidated Statements of Operations and Comprehensive Loss", "R2.htm")}
    got = packet.pick_statements(summary("Consolidated Statement of Other Comprehensive Earnings", "Statement of Changes in Equity",
                                         "Statement of Financial Position"))
    assert "income_statement" not in got and got["balance_sheet"][1] == "R4.htm"
    got = packet.pick_statements(summary("Consolidated Statements of Condition", "Consolidated Statements of Income and Retained Earnings"))
    assert got["balance_sheet"][1] == "R2.htm" and got["income_statement"][1] == "R3.htm"


def test_a_missing_statement_is_an_annotation(world):
    docs = documents()
    docs[f"{base(AQ)}/FilingSummary.xml"] = summary("Condensed Consolidated Balance Sheets", "Cover").replace("R2.htm", "R4.htm").encode()
    docs.pop(f"{base(AQ)}/R2.htm")
    docs.pop(f"{base(AQ)}/R6.htm")
    pk = build(world, store=make_store(world["tmp"] / "s3", docs))
    assert [e["name"] for e in pk["evidence"] if e["kind"] == "statement"] == ["balance_sheet"]
    assert f"statement_not_found: income_statement {AQ}" in pk["annotations"]
    assert f"statement_not_found: cash_flows {AQ}" in pk["annotations"]


def twentyf_lines():
    big = lambda tag: [filler(tag, 800), filler(tag + "b", 900)]
    return (["Item 3: Key Information | 1", "D. | RISK FACTORS | 1", "Item 4: Information on the Company | 28",
             "Item 4A: Unresolved Staff Comments | 46", "Item 5: Operating and Financial Review and Prospects | 47",
             "Item 6: Directors | 60", "PART I", "ITEM 3. KEY INFORMATION", "A. [Reserved]", "D.Risk Factors"] + big("risk") +
            ["See “Item 5. Operating and Financial Review” for more.", "ITEM 4. INFORMATION ON THE COMPANY"] + big("info") +
            ["ITEM 4A. UNRESOLVED STAFF COMMENTS", "None.", "ITEM 5. | OPERATING AND FINANCIAL REVIEW AND PROSPECTS"] + big("ofr") +
            ["ITEM 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES", "Board."])


def test_twenty_f_sections():
    lines = twentyf_lines()
    found = {name: packet.find_section(lines, num, own, title) for name, num, own, title, _, _ in packet.SECTIONS["20-F"]}
    assert lines[found["risk_factors"][0]] == "D.Risk Factors" and lines[found["risk_factors"][1]] == "ITEM 4. INFORMATION ON THE COMPANY"
    assert lines[found["business"][0]] == "ITEM 4. INFORMATION ON THE COMPANY" and lines[found["business"][1]].startswith("ITEM 4A.")
    assert lines[found["mdna"][0]].startswith("ITEM 5. |") and lines[found["mdna"][1]].startswith("ITEM 6.")


def test_section_rules_never_guess():
    long = [filler("x", 1600)]
    assert packet.find_section(["Item 1A. Risk Factors"] + long, r"1[Aa]", "1A", r"risk\s+factors") is None          # no end
    assert packet.find_section(["Item 1A. Risk Factors", "Short.", "Item 2. Properties"], r"1[Aa]", "1A", r"risk\s+factors") is None
    lines = ["Item 1A. Risk Factors"] + long + ["Item 1B. Unresolved"]
    assert packet.find_section(lines, r"1[Aa]", "1A", r"risk\s+factors") == (0, 2)
    assert packet.find_section(["Item 1A of Part II covers risk factors"] + long + ["Item 2. X"], r"1[Aa]", "1A", r"risk\s+factors") is None
    assert packet.find_section(["Item 10. Business"] + long + ["Item 11. X"], r"1(?:\s*(?:and|&|,)\s*2)?", "1", "business") is None
    lines = ["Items 1 and 2. Business and Properties"] + long + ["Item 1A. Risk Factors"]
    assert packet.find_section(lines, r"1(?:\s*(?:and|&|,)\s*2)?", "1", "business") == (0, 2)


def test_a_forty_f_cover_document_has_no_sections(world):
    docs = documents()
    docs[f"{base(A10K)}/tk-20251231.htm"] = b"<html><body><p>FORM 40-F</p><p>Annual Information Form: see Exhibit 99.1.</p></body></html>"
    subs = json.loads(submissions())
    r = subs["filings"]["recent"]
    i = r["accessionNumber"].index(A10K)
    r["form"][i] = "40-F"
    docs[SUBS_URL] = json.dumps(subs).encode()
    pk = build(world, store=make_store(world["tmp"] / "s40", docs))
    for name in ("business", "risk_factors", "mdna"):
        assert f"section_not_found: {name} {A10K}" in pk["annotations"]
    assert not [e for e in pk["evidence"] if e["kind"] == "annual_section"]


# ---- the bytes and the resolver ----------------------------------------------------------------------------------------------------

def test_canonical_bytes_form():
    assert packet.canonical_bytes({"b": 1, "a": "é", "c": [0.0, None]}) == '{"a":"é","b":1,"c":[0.0,null]}'.encode("utf-8")


def test_screener_repo_is_resolved_through_paths(tmp_path, monkeypatch):
    for var in ("SCREENER_PUBLISH_REPO", "MRI_OUTPUTS_DIR", "RS2_STATE_DIR"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))
    assert packet.screener_repo() == tmp_path / "screener_publish_repo"


def test_a_short_last_section_after_a_contents_entry_is_kept():
    # audit 2026-10-29: a 10-Q's one-sentence Item 1A ("no material changes") was annotated as not found
    no_change = "There have been no material changes to the risk factors disclosed in our Annual Report on Form 10-K for the fiscal year."
    toc = ["Item 1A. Risk Factors", "45", "Item 2. Unregistered Sales", "46"]
    body = ["Item 1A. Risk Factors", no_change, "Item 2. Unregistered Sales of Equity Securities"]
    rf = (r"1[Aa]", "1A", r"risk\s+factors")
    assert packet.find_section(toc + body, *rf) == (4, 6)
    assert packet.find_section(body, *rf) is None                                  # one heading only: it may be the contents entry
    assert packet.find_section(toc + ["Item 1A. Risk Factors", "None.", "Item 2. X"], *rf) is None   # under SHORT_MIN_CHARS

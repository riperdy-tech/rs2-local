"""packet: the input contract m3m.packet.v1 (SPEC §3, gate M-P4 negatives). Offline: a synthetic store and a throwaway git repository
in tmp_path; the FilingSummary and the balance-sheet R report are trimmed real bytes of AMD's 10-Q 0000002488-26-000123."""
import hashlib
import importlib.metadata
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
RUN_UPDATED = "2026-10-02T00:00:00Z"            # GitHub's end of the run that witnessed the commit (CROSS_CHECK_M 2.1)

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


def submissions(extra=(), drop=()):
    rows = [r for r in [  # newest first, as SEC lists them
        (ANEW, "8-K", "2026-10-28", "2026-10-28T12:00:00.000Z", "", "2.02,9.01", "anew.htm"),
        (A801, "8-K", "2026-10-20", "2026-10-20T14:00:00.000Z", "2026-10-20", "8.01,9.01", "e801.htm"),
        (A701, "8-K", "2026-10-01", "2026-10-01T14:00:00.000Z", "2026-10-01", "7.01,9.01", "e701.htm"),
        (A502, "8-K", "2026-09-15", "2026-09-15T14:00:00.000Z", "2026-09-14", "5.02", "e502.htm"),
        (AREL, "8-K", "2026-08-05", "2026-08-05T20:01:00.000Z", "2026-08-05", "2.02,9.01", "rel.htm"),
        (AQ, "10-Q", "2026-08-05", "2026-08-05T20:00:00.000Z", "2026-06-30", "", "tq-20260630.htm"),
        (AOLD, "8-K", "2026-05-01", "2026-05-01T14:00:00.000Z", "2026-05-01", "1.01", "old.htm"),
        (A10K, "10-K", "2026-02-20", "2026-02-20T21:00:00.000Z", "2025-12-31", "", "tk-20251231.htm"),
    ] + list(extra) if r[0] not in drop]
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
        f"{base(A701)}/{A701}.txt": eightk_txt(A701, [("8-K", "f701.htm", "<p>Item 7.01 Regulation FD Disclosure.</p><p>E701_TEXT "
                                                     + filler("e701", 900) + "</p>"),
                                                     ("EX-99.1", "ex701.htm", "<p>E701_DECK the investor presentation.</p>")]),
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
    stocks = [{"symbol": "TEST", "name": "Test Co", "sector": "Industrials", "industry": "Widgets", "price": 12.5, "marketCap": 0,
               "Last_Updated": "2026-09-30 16:47", "last_listed": "2026-09-30", "peRatio": 0,
               "metrics": {"netIncome": 0.0, "roic": 0.125, "dilution": 0, "mScore": None, "quarterlyEps": [0.0, 0.1],
                           "forwardEpsEstimate": 5.0875, "pegRatio": 1.6619115000000002},
               "reverse": {"rev_mos": 85, "rev_band": "Watchlist", "rev_rank": 821,
                           "rev_con": "G quality is shallow; v3.2 must verify capital and credit; PRICE_EXTENDED: current price 3.3x above 2yr low"},
               "description": "Test Co owns 79 containerships and 38 dry bulk vessels.", "status": "Fail", "score": 70,
               "reasons": ["ok"]},
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
    record = [{"run_id": "r-fail", "verdict": "PASS", "pair": "FAIL", "output_commit": commit, "run_updated_at": RUN_UPDATED},
              {"run_id": "r-ok", "workflow": "Post-Close Price Refresh", "run_created_at": "2026-10-01T23:30:00Z", "run_updated_at": RUN_UPDATED,
               "verdict": "PASS", "failed_checks": [], "output_commit": commit, "pair": "PASS", "pair_detail": {"stocks": 4}}]
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
        ("P6", "other_8k", "other_8k"), ("P7", "other_8k", "other_8k"), ("P8", "other_8k", "other_8k")]
    by = {e["fact_id"]: e for e in ev}
    assert pk["contract"] == "m3m.packet.v1" and pk["cik"] == CIK and pk["decision_time_utc"] == T
    assert pk["sec_policy"] == "sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1"
    assert pk["screener"]["commit"] == world["commit"]
    assert pk["screener"]["verified_row"] == {"run_id": "r-ok", "verdict": "PASS", "pair": "PASS", "output_commit": world["commit"],
                                              "run_updated_at": RUN_UPDATED}          # ruling 5.1: the row as found
    assert pk["builder_version"] == "m3m.packet.builder.v7" and pk["regime"] == "verified" and "cik_source" not in pk
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
    assert [by[f]["source"]["accession"] for f in ("P6", "P7", "P8")] == [A801, A701, A502]    # newest first; 7.01 is listed (v5); >120 d out: not
    assert by["P6"]["text"].startswith("Item 8.01 Other Events.\nE801_TEXT")      # 8-K body from its item, then EX-99.1 (ruling 6.1b)
    assert by["P7"]["text"].startswith("Item 7.01 Regulation FD Disclosure.\nE701_TEXT") and "E701_DECK" in by["P7"]["text"]
    assert by["P8"]["text"].startswith("Item 5.02 Departure of Directors.\nE502_TEXT") and "FORM 8-K" not in by["P8"]["text"]
    assert by["P6"]["title"] == "8-K Items 8.01, 9.01 (8-K body, EX-99.1)" and by["P8"]["title"] == "8-K Item 5.02 (8-K body)"
    assert by["P5"]["title"] == "8-K Item 2.02 earnings release (EX-99.1 ex991.htm)"
    assert by["P1"]["effective_at"] == "2026-02-24T14:30:00Z"            # Fri 21:00 ET (later reading) -> Mon, +1 for after 17:30 -> Tue
    assert by["P1"]["accepted_raw"] == "2026-02-20T21:00:00.000Z" and by["P1"]["period"] == "2025-12-31" and by["P1"]["form"] == "10-K"
    raw = documents()[f"{base(A10K)}/tk-20251231.htm"]
    assert by["P1"]["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert pk["raw_inputs"][0] == {"url": SUBS_URL, "sha256": hashlib.sha256(submissions()).hexdigest()}
    assert {r["url"] for r in pk["raw_inputs"]} == set(documents())                    # every input used, nothing more
    assert f"section_not_found: quarterly_risk_factors {AQ}" in pk["annotations"]      # a short section is not guessed
    assert pk["excluded"] == [{"slot": "release", "accession": ANEW, "form": "8-K", "accepted_raw": "2026-10-28T12:00:00.000Z",
                               "effective_at": "2026-10-29T13:30:00Z"}]


def test_s0_is_the_identity_and_market_whitelist_only(world):
    # CROSS_CHECK_M 3.1: the reviewer's failing input is the screener's own opinions (reverse.*, doors, ranks, bands, scores, the rev_con
    # narrative, forward consensus), placeholder zeros of derived metrics and the Yahoo description, all printed into S0
    pk = build(world)
    s0 = pk["evidence"][0]
    assert s0["text"].split("\n") == [
        f"stocks.json record ({packet.STOCKS_PATH} at {world['commit']}), identity and market fields only:",
        "symbol: TEST", "name: Test Co", "sector: Industrials", "industry: Widgets", "country: absent", "price: 12.5", "marketCap: 0",
        "price as-of (Last_Updated, zone not stated): 2026-09-30 16:47", "last_listed: 2026-09-30"]
    for banned in ("rev_", "Watchlist", "G quality", "PRICE_EXTENDED", "nominated", "DOOR_1", "score", "status", "Fail", "peRatio",
                   "netIncome", "forwardEps", "pegRatio", "roic", "containerships", "description", "z_value", "reasons"):
        assert banned not in s0["text"]
    assert s0["source"] == {"git_commit": world["commit"], "path": packet.STOCKS_PATH}
    stocks_blob = subprocess.run(["git", "-C", str(world["repo"]), "show", f"HEAD:{packet.STOCKS_PATH}"], capture_output=True).stdout
    assert s0["raw_sha256"] == hashlib.sha256(stocks_blob).hexdigest()
    assert s0["title"] == "Screener row: identity and market fields of the stocks.json record"
    assert pk["screener"]["factor_blob_sha"] == git(world["repo"], "rev-parse", f"HEAD:{packet.FACTOR_PATH}")  # pinned, for audit only
    assert "NOCIK" not in s0["text"]


def test_s0_lines_print_zero_as_zero_null_as_null_and_a_missing_field_as_absent():
    assert packet.s0_lines({"symbol": "X", "price": 0.0, "marketCap": None}) == [
        "symbol: X", "name: absent", "sector: absent", "industry: absent", "country: absent", "price: 0", "marketCap: null",
        "price as-of (Last_Updated, zone not stated): absent", "last_listed: absent"]


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
    pk = build(world, commit=c[:12].upper(), record=[{"verdict": "PASS", "pair": "PASS", "output_commit": c[:10], "run_id": "x",
                                                     "run_updated_at": RUN_UPDATED}])
    assert pk["screener"]["commit"] == c and pk["screener"]["verified_row"]["run_id"] == "x"


def test_a_record_read_from_a_file_path(world):
    p = world["tmp"] / "check.json"
    p.write_text(json.dumps(world["record"]), encoding="utf-8")
    assert build(world, record=str(p))["screener"]["verified_row"]["run_id"] == "r-ok"


@pytest.mark.parametrize("ticker,code", [("ZZZZ", "ticker_not_in_stocks"), ("NOCIK", "no_cik"),
                                         ("NOPROF", "ticker_not_in_factor_profiles")])
def test_screener_refusals(world, ticker, code):
    with pytest.raises(packet.PacketRefused) as e:
        build(world, ticker=ticker)
    assert e.value.code == code


def test_a_screener_commit_dated_after_T_is_refused(world):
    record = [dict(world["record"][1], run_updated_at="2026-09-30T00:00:00Z")]     # the run-time check passes; the commit date does not
    with pytest.raises(packet.PacketRefused) as e:
        build(world, T="2026-09-30T23:59:59Z", record=record)
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

    cap = total - len(by["P6"]["text"]) - len(by["P7"]["text"]) - len(by["P8"]["text"]) - 2000     # all three 8-Ks go, then the release is cut
    monkeypatch.setattr(packet, "TOTAL_CAP", cap)
    pk = build(world)
    notes = [a for a in pk["annotations"] if a.startswith("trimmed")]
    assert [n.split(" (")[0].rsplit(" to ", 1)[0] for n in notes] == [
        f"trimmed_out: other_8k other_8k {A502}", f"trimmed_out: other_8k other_8k {A701}", f"trimmed_out: other_8k other_8k {A801}",
        f"trimmed: release earnings_release {AREL}"]
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


# ---- CROSS_CHECK_M rulings (WO_M4, builder A2) -------------------------------------------------------------------------------------

def with_docs(w, name, extra_rows=(), drop=(), docs_extra=None):
    """A store of documents() plus extra submissions rows and documents, minus dropped rows."""
    docs = documents()
    docs[SUBS_URL] = submissions(extra=extra_rows, drop=drop)
    docs.update(docs_extra or {})
    return make_store(w["tmp"] / name, docs)


# 2.1: the run-time check against GitHub's run_updated_at

@pytest.mark.parametrize("value,code", [
    ("<absent>", "verified_run_time_missing"), (None, "verified_run_time_missing"), ("", "verified_run_time_missing"),
    ("2026-10-02T00:00:00", "verified_run_time_missing"),            # no zone: not readable as a time
    ("not a time", "verified_run_time_missing"),
    ("2026-10-28T20:00:01Z", "verified_run_after_T"),                 # one second after T
])
def test_a_verified_row_without_a_run_end_by_T_is_refused(world, value, code):
    row = dict(world["record"][1])
    if value == "<absent>":
        row.pop("run_updated_at")
    else:
        row["run_updated_at"] = value
    with pytest.raises(packet.PacketRefused) as e:
        build(world, record=[row])
    assert e.value.code == code


def test_a_run_that_ended_exactly_at_T_is_accepted(world):
    pk = build(world, record=[dict(world["record"][1], run_updated_at=T)])
    assert pk["screener"]["verified_row"]["run_updated_at"] == T


# 5.1: the verified row, as found, is pinned in the header (the reviewer's input: two records for one commit with other run ids)

def test_the_real_check_new_runs_row_shape_is_pinned_and_other_runs_are_visible(world):
    real = {"run_id": "40796224964", "workflow": "Post-Close Price Refresh", "runner": "github_hosted",
            "run_created_at": "2026-10-01T00:46:21Z", "run_updated_at": "2026-10-01T01:13:38Z", "verdict": "PASS", "failed_checks": [],
            "output_commit": world["commit"], "candidates": {"PIT_PROSPECTIVE": 160}, "momentum": ["PIT_VALID"], "input_issues": [],
            "pair": "PASS", "pair_detail": {"stocks": 7012, "reverse": 7012, "exact_pairs": 7012}}
    a = build(world, record=[real])
    b = build(world, record=[dict(real, run_id="40799999999")])
    assert a["screener"]["verified_row"] == {"run_id": "40796224964", "verdict": "PASS", "pair": "PASS", "output_commit": world["commit"],
                                             "run_updated_at": "2026-10-01T01:13:38Z"}
    assert b["screener"]["verified_row"]["run_id"] == "40799999999" and a["evidence"] == b["evidence"]
    assert packet.packet_sha256(a) != packet.packet_sha256(b)


# 2.3: T older than the oldest filings.recent row

@pytest.fixture
def early_world(tmp_path):
    repo, commit = make_repo(tmp_path / "repo", date="2026-01-01T00:00:00+00:00")
    record = [{"run_id": "r", "verdict": "PASS", "pair": "PASS", "output_commit": commit, "run_updated_at": "2026-01-02T00:00:00Z"}]
    return {"repo": repo, "commit": commit, "store": make_store(tmp_path / "store"), "record": record, "tmp": tmp_path}


def test_T_older_than_the_oldest_filings_recent_row_is_refused(early_world):
    oldest = packet._z(packet.accepted_at("2026-02-20T21:00:00.000Z"))         # the 10-K, the oldest row: 2026-02-21T02:00:00Z
    with pytest.raises(packet.PacketRefused) as e:
        build(early_world, T="2026-02-21T01:59:59Z")
    assert e.value.code == "T_before_filings_recent" and oldest in str(e.value)
    pk = build(early_world, T=oldest)                                            # at the oldest row: built (nothing is effective yet)
    assert [e["kind"] for e in pk["evidence"]] == ["screener_row"]
    assert [(x["slot"], x["accession"]) for x in pk["excluded"]] == [("statements", A10K), ("annual", A10K)]


def test_an_empty_filings_recent_is_refused(world):
    store = with_docs(world, "empty", drop=(ANEW, A801, A701, A502, AREL, AQ, AOLD, A10K))
    with pytest.raises(packet.PacketRefused) as e:
        build(world, store=store)
    assert e.value.code == "T_before_filings_recent"


# 5.3: T outside the calendar, and the builder's code in the header

@pytest.mark.parametrize("t", ["2004-12-31T23:59:59Z", "2005-01-03T14:29:59Z",
                               "2031-12-30T23:00:00Z",          # 18:00 ET: its effective session is in 2032, past the calendar
                               "2031-12-31T15:00:00Z", "2035-06-01T00:00:00Z"])
def test_T_outside_the_calendar_is_refused(world, t):
    with pytest.raises(packet.PacketRefused) as e:
        build(world, T=t)
    assert e.value.code == "T_outside_calendar"


def test_the_calendar_bounds_that_are_inside():
    for t in ("2005-01-03T14:30:00Z", "2031-12-30T15:00:00Z", "2026-10-29T03:00:00Z"):
        packet.check_T_in_calendar(packet.parse_T(t))


def test_builder_code_pins_the_source_files_and_the_calendar_libraries(world, tmp_path, monkeypatch):
    bc = build(world)["builder_code"]
    lf = lambda p: hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert bc == {"packet.py": lf(packet.__file__), "sec_primary.py": lf(sec_primary.__file__),
                  "sec_guidance.py": lf(packet.sec_guidance.__file__),
                  "exchange_calendars": importlib.metadata.version("exchange_calendars"), "tzdata": importlib.metadata.version("tzdata")}
    crlf, lfile = tmp_path / "crlf.py", tmp_path / "lf.py"
    crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
    lfile.write_bytes(b"a = 1\nb = 2\n")
    monkeypatch.setattr(packet, "BUILDER_FILES", (("packet.py", crlf),))
    one = packet.builder_code()["packet.py"]
    monkeypatch.setattr(packet, "BUILDER_FILES", (("packet.py", lfile),))
    assert packet.builder_code()["packet.py"] == one                            # a checkout's line ends do not change the pin
    lfile.write_bytes(b"a = 1\nb = 3\n")
    assert packet.builder_code()["packet.py"] != one                            # an edit does


# 6.1b: the other-8-K text (the reviewer's input: ILMN 0000950157-26-000888, a credit agreement's cover in the slot of the 8-K body)

AILMN = "0000000123-26-000075"
ILMN_BODY = ("<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 8-K</p><p>Check the appropriate box below.</p>"
             "<table><tr><td>Item 1.01.</td><td>Entry into a Material Definitive Agreement.</td></tr></table>"
             "<p>On October 9, 2026, the Company entered into a credit agreement providing for a $750 million revolving facility maturing in "
             "2031.</p><table><tr><td>Item 2.03.</td><td>Creation of a Direct Financial Obligation.</td></tr></table>"
             "<p>The information set forth under Item 1.01 is incorporated herein by reference.</p>"
             "<p>Item 9.01. Financial Statements and Exhibits.</p><p>10.1 Credit Agreement</p>")
CONTRACTS = [("EX-10.1", "ex10-1.htm", "<p>CREDIT AGREEMENT TABLE OF CONTENTS Article I Definitions</p>"),
             ("EX-9.01", "ex101cpdealer.htm", "<p>COMMERCIAL PAPER DEALER AGREEMENT [●]</p>"),
             ("EX-4.2", "ex42.htm", "<p>INDENTURE SUPPLEMENT</p>"), ("EX-1.1", "ex11.htm", "<p>UNDERWRITING AGREEMENT</p>"),
             ("EX-3.1", "ex31.htm", "<p>AMENDED BYLAWS</p>"), ("EX-5.1", "ex51.htm", "<p>LEGAL OPINION</p>")]
ILMN_ROW = (AILMN, "8-K", "2026-10-10", "2026-10-10T14:00:00.000Z", "2026-10-09", "1.01,2.03,9.01", "form8-k.htm")


def other(pk, acc):
    return [e for e in pk["evidence"] if e["kind"] == "other_8k" and e["source"]["accession"] == acc]


def test_other_8k_is_the_body_from_its_first_listed_item_and_never_a_contract(world):
    txt = eightk_txt(AILMN, [("8-K", "form8-k.htm", ILMN_BODY)] + CONTRACTS)
    pk = build(world, store=with_docs(world, "ilmn", extra_rows=[ILMN_ROW], docs_extra={f"{base(AILMN)}/{AILMN}.txt": txt}))
    [e] = other(pk, AILMN)
    assert e["text"].startswith("Item 1.01. | Entry into a Material Definitive Agreement.\nOn October 9, 2026")
    assert "$750 million revolving facility" in e["text"] and "Item 2.03." in e["text"]
    for banned in ("UNITED STATES", "Check the appropriate", "CREDIT AGREEMENT", "DEALER", "[●]", "INDENTURE", "UNDERWRITING", "BYLAWS",
                   "LEGAL OPINION"):
        assert banned not in e["text"]
    assert e["title"] == "8-K Items 1.01, 2.03, 9.01 (8-K body)"


def test_other_8k_body_then_ex99_and_the_title_names_only_what_the_cut_text_reaches(world):
    ex99 = ("EX-99.1", "ex991.htm", "<p>EX99_TEXT the press release.</p>")
    ex992 = ("EX-99.2", "ex992.htm", "<p>EX992_TEXT the presentation.</p>")
    short = eightk_txt(AILMN, [("8-K", "form8-k.htm", ILMN_BODY), CONTRACTS[0], ex99, ex992])
    pk = build(world, store=with_docs(world, "ex99", extra_rows=[ILMN_ROW], docs_extra={f"{base(AILMN)}/{AILMN}.txt": short}))
    [e] = other(pk, AILMN)
    assert e["text"].index("Item 1.01.") < e["text"].index("EX99_TEXT") < e["text"].index("EX992_TEXT")
    assert e["title"] == "8-K Items 1.01, 2.03, 9.01 (8-K body, EX-99.1, EX-99.2)" and "CREDIT AGREEMENT" not in e["text"]
    long_body = ILMN_BODY.replace("<p>Item 9.01.", "<p>" + filler("long", 5000) + "</p><p>Item 9.01.")
    cut = eightk_txt(AILMN, [("8-K", "form8-k.htm", long_body), ("EX-99.1", "ex991.htm", "<p>EX99_TEXT " + filler("exh", 400) + "</p>")])
    pk = build(world, store=with_docs(world, "ex99cut", extra_rows=[ILMN_ROW], docs_extra={f"{base(AILMN)}/{AILMN}.txt": cut}))
    [e] = other(pk, AILMN)
    assert len(e["text"]) <= packet.OTHER_8K_CAP and sec_primary.OMIT_RE.search(e["text"]) and "EX99_TEXT" not in e["text"]
    assert e["title"] == "8-K Items 1.01, 2.03, 9.01 (8-K body)"


def test_other_8k_without_a_listed_item_heading_uses_no_cover_page(world):
    cover_only = "<p>UNITED STATES</p><p>FORM 8-K</p><p>See the exhibit.</p>"
    ex99 = ("EX-99.1", "ex991.htm", "<p>EX99_TEXT the press release.</p>")
    txt = eightk_txt(AILMN, [("8-K", "form8-k.htm", cover_only), CONTRACTS[0], ex99])
    pk = build(world, store=with_docs(world, "nohead", extra_rows=[ILMN_ROW], docs_extra={f"{base(AILMN)}/{AILMN}.txt": txt}))
    [e] = other(pk, AILMN)
    assert e["text"] == "EX99_TEXT the press release." and e["title"] == "8-K Items 1.01, 2.03, 9.01 (EX-99.1)"
    assert f"8k_item_heading_not_found: {AILMN}" in pk["annotations"]
    txt = eightk_txt(AILMN, [("8-K", "form8-k.htm", cover_only)] + CONTRACTS)
    pk = build(world, store=with_docs(world, "nothing", extra_rows=[ILMN_ROW], docs_extra={f"{base(AILMN)}/{AILMN}.txt": txt}))
    assert other(pk, AILMN) == [] and f"8k_text_not_found: {AILMN}" in pk["annotations"]


def test_eight_k_body_lines_start_at_the_first_heading_of_a_listed_item():
    lines = ["FORM 8-K", "The information in Item 7.01 is furnished.", "Item 7.01. Regulation FD Disclosure.", "Text.", "Item 8.01. Other"]
    assert packet.eight_k_body_lines(lines, ["7.01", "8.01", "9.01"]) == lines[2:]      # ECPG 0001084961-26-000052: 7.01 is listed
    assert packet.eight_k_body_lines(lines, ["8.01"]) == lines[4:]
    assert packet.eight_k_body_lines(["ITEMS 1.01 AND 2.03. Entry"], ["2.03", "1.01"]) == ["ITEMS 1.01 AND 2.03. Entry"]
    assert packet.eight_k_body_lines(["Item 1.011 x"], ["1.01"]) is None
    assert packet.eight_k_body_lines(["Item 1.01 x"], []) is None


# 6.2a: amendments

AAM1 = "0000000123-26-000020"     # a 10-K/A after the annual report (HRTG 0001193125-26-115451: explanatory note, then Item 8)
AAM2 = "0000000123-26-000058"     # a 10-Q/A with a contents table
AAM3 = "0000000123-26-000005"     # a 10-K/A before the annual report: not used
AAM4 = "0000000123-26-000040"     # a 10-Q/A with no Item heading
AAMX = "0000000123-26-000079"     # a 10-K/A not yet effective at T


def amend_html(kind):
    if kind == "hrtg":
        return ("<html><body><p>FORM 10-K/A</p><p>(Amendment No. 1)</p><p>Indicate by check mark pursuant to Item 405.</p>"
                "<p>EXPLANATORY NOTE</p><p>This Amendment No. 1 restates the auditor's report.</p><p>PART II</p>"
                "<p>Item 8. Financial Statements and Supplementary Data</p><p>AM1_START index of statements.</p>" + paras("am1", 6000)
                + "<p>Item 15. Exhibits, Financial Statements Schedules</p><p>Listed.</p></body></html>").encode()
    if kind == "toc":
        return ("<html><body><table><tr><td>Item 1.</td><td>Financial Statements</td><td>3</td></tr>"
                "<tr><td>Item 2.</td><td>Management's Discussion</td><td>10</td></tr></table>"
                "<p>Item 1. Financial Statements</p><p>AM2_START restated quarter.</p>" + paras("am2", 600)
                + "<p>Item 2. Management's Discussion</p><p>Restated.</p></body></html>").encode()
    return b"<html><body><p>FORM 10-Q/A</p><p>This amendment furnishes a corrected cover page only.</p></body></html>"


AMEND_ROWS = {AAM1: (AAM1, "10-K/A", "2026-03-19", "2026-03-19T16:00:42.000Z", "2025-12-31", "", "tka1.htm"),
              AAM2: (AAM2, "10-Q/A", "2026-09-01", "2026-09-01T14:00:00.000Z", "2026-06-30", "", "tqa2.htm"),
              AAM3: (AAM3, "10-K/A", "2026-01-10", "2026-01-10T14:00:00.000Z", "2024-12-31", "", "tka3.htm"),
              AAM4: (AAM4, "10-Q/A", "2026-05-01", "2026-05-01T14:00:00.000Z", "2026-03-31", "", "tqa4.htm"),
              AAMX: (AAMX, "10-K/A", "2026-10-28", "2026-10-28T13:00:00.000Z", "2025-12-31", "", "tkax.htm")}
AMEND_DOCS = {f"{base(AAM1)}/tka1.htm": amend_html("hrtg"), f"{base(AAM2)}/tqa2.htm": amend_html("toc"),
              f"{base(AAM3)}/tka3.htm": amend_html("hrtg"), f"{base(AAM4)}/tqa4.htm": amend_html("none")}


def test_an_amendment_after_the_annual_report_is_an_item_from_its_first_item_heading(world):
    store = with_docs(world, "am1", extra_rows=[AMEND_ROWS[AAM1], AMEND_ROWS[AAM3]], docs_extra=AMEND_DOCS)
    pk = build(world, store=store)
    kinds = [e["kind"] for e in pk["evidence"]]
    assert kinds.index("quarterly_section") < kinds.index("amendment") < kinds.index("release")
    [e] = [e for e in pk["evidence"] if e["kind"] == "amendment"]
    assert e["source"] == {"accession": AAM1, "url": f"{base(AAM1)}/tka1.htm"} and e["form"] == "10-K/A" and e["name"] == "amendment"
    assert e["text"].startswith("EXPLANATORY NOTE\n")                     # audit 2026-10-29: the note before the first Item heading
    assert "Item 8. Financial Statements and Supplementary Data\nAM1_START" in e["text"]
    assert "Item 405" not in e["text"]                                    # the cover before the note is not kept
    assert len(e["text"]) <= packet.AMENDMENT_CAP and sec_primary.OMIT_RE.search(e["text"])
    assert e["title"] == "10-K/A amendment, from its first Item heading"
    assert f"{base(AAM3)}/tka3.htm" not in {r["url"] for r in pk["raw_inputs"]}      # before the annual report: not read


def test_at_most_two_amendments_newest_first_and_a_contents_entry_is_skipped(world):
    rows = [AMEND_ROWS[a] for a in (AAM1, AAM2, AAM4, AAMX)]
    pk = build(world, store=with_docs(world, "am2", extra_rows=rows, docs_extra=AMEND_DOCS))
    am = [e for e in pk["evidence"] if e["kind"] == "amendment"]
    assert [e["source"]["accession"] for e in am] == [AAM2]                            # the two newest eligible are AAM2 and AAM4
    assert am[0]["text"].startswith("Item 1. Financial Statements\nAM2_START")           # not the contents row
    assert f"amendment_text_not_found: 10-Q/A {AAM4}" in pk["annotations"]             # AAM4 has no Item heading: annotated
    assert f"{base(AAM1)}/tka1.htm" not in {r["url"] for r in pk["raw_inputs"]}      # the third newest is not read
    assert {"slot": "amendment", "accession": AAMX, "form": "10-K/A", "accepted_raw": "2026-10-28T13:00:00.000Z",
            "effective_at": "2026-10-29T13:30:00Z"} in pk["excluded"]                  # not yet effective: listed, not used


def test_amendment_lines_rules():
    long = filler("x", 200)
    assert packet.amendment_lines(["Cover", "Item 1. | Business | 3", "Item 2. | Properties | 9", "Item 1. Business", long]) == [
        "Item 1. Business", long]                                                         # contents rows skipped; runs to the end
    assert packet.amendment_lines(["Item 15. Exhibits", "None.", "Item 16. Summary", "None."]) is None   # under SHORT_MIN_CHARS
    assert packet.amendment_lines(["EXPLANATORY NOTE", long]) is None


# 6.2c: the release staleness bound

def test_a_release_accepted_more_than_120_days_before_T_is_not_used(world):
    store = with_docs(world, "stale", drop=(ANEW,))
    accepted = packet.accepted_at("2026-08-05T20:01:00.000Z")                          # the later reading: 2026-08-06T00:01:00Z
    edge = packet._z(accepted + packet.timedelta(days=packet.RELEASE_MAX_DAYS))
    pk = build(world, T=edge, store=store)
    assert [e["source"]["accession"] for e in pk["evidence"] if e["kind"] == "release"] == [AREL]     # exactly 120 days: used
    later = packet._z(accepted + packet.timedelta(days=packet.RELEASE_MAX_DAYS, seconds=1))
    pk = build(world, T=later, store=store)
    assert not [e for e in pk["evidence"] if e["kind"] == "release"]
    assert f"release_stale: {AREL} accepted 2026-08-05T20:01:00.000Z, more than 120 days before T" in pk["annotations"]
    assert not [a for a in pk["annotations"] if a.startswith("no_eligible_filing: release")]


# ---- 3N (WO_N2): 8-K Item 1.02 and the archival regime ----------------------------------------------------------------------------------

A102 = "0000000123-26-000077"
ROW_102 = (A102, "8-K", "2026-10-10", "2026-10-10T14:00:00.000Z", "2026-10-09", "1.02,9.01", "f102.htm")
BODY_102 = ("<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 8-K</p><p>Item 1.02 Termination of a Material Definitive Agreement.</p>"
            "<p>On October 9, 2026, the Company's largest customer gave notice that it is terminating the supply agreement.</p>"
            "<p>Item 9.01 Financial Statements and Exhibits.</p>")


def test_an_item_1_02_eight_k_is_an_other_8k_item(world):
    assert "1.02" in packet.OTHER_8K_ITEMS
    txt = eightk_txt(A102, [("8-K", "f102.htm", BODY_102)])
    pk = build(world, store=with_docs(world, "i102", extra_rows=[ROW_102], docs_extra={f"{base(A102)}/{A102}.txt": txt}))
    [e] = other(pk, A102)
    assert e["text"].startswith("Item 1.02 Termination of a Material Definitive Agreement.\nOn October 9, 2026")
    assert e["title"] == "8-K Items 1.02, 9.01 (8-K body)" and "FORM 8-K" not in e["text"]


# ---- WO_N5: builder v5 ------------------------------------------------------------------------------------------------------------

A402 = "0000000123-26-000078"           # OPTU 0001702780-26-000057: Items 2.02, 4.02 and 9.01 and no EX-99
ROW_402 = (A402, "8-K", "2026-10-15", "2026-10-15T14:00:00.000Z", "2026-10-15", "2.02,4.02,9.01", "f402.htm")
BODY_402 = ("<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 8-K</p><p>Item 2.02 Results of Operations and Financial Condition.</p>"
            "<p>On October 14, 2026, the Company announced its results; they are being restated.</p>"
            "<p>Item 4.02 Non-Reliance on Previously Issued Financial Statements.</p>"
            "<p>NONRELIANCE_TEXT On October 14, 2026, the Audit Committee concluded that the financial statements for the quarter ended "
            "June 30, 2026 should no longer be relied upon.</p><p>Item 9.01 Financial Statements and Exhibits.</p>")


def store_402(w, name, docs, extra_rows=(), extra_docs=None):
    """A store whose newest eligible Item 2.02 8-K is A402 (Items 2.02, 4.02, 9.01) with the given documents [(type, filename, html)]."""
    return with_docs(w, name, extra_rows=[ROW_402, *extra_rows],
                     docs_extra={f"{base(A402)}/{A402}.txt": eightk_txt(A402, docs), **(extra_docs or {})})


def test_builder_v5_constants():
    assert "7.01" in packet.OTHER_8K_ITEMS and "2.02" not in packet.OTHER_8K_ITEMS


def test_a_release_slot_eight_k_with_no_ex99_still_yields_its_item_4_02_text(world):
    pk = build(world, store=store_402(world, "i402", [("8-K", "f402.htm", BODY_402)]))
    assert not [e for e in pk["evidence"] if e["kind"] == "release"]                    # the release exhibit is not found, unchanged
    assert f"release_exhibit_not_found: {A402}" in pk["annotations"]
    [e] = other(pk, A402)
    assert "NONRELIANCE_TEXT" in e["text"] and e["text"].startswith("Item 4.02 Non-Reliance") and "FORM 8-K" not in e["text"]
    assert "Results of Operations" not in e["text"]                       # v6: the Item 2.02 segment is not an OTHER_8K_ITEMS item's
    assert e["title"] == "8-K Items 2.02, 4.02, 9.01 (8-K body)"
    assert [x["source"]["accession"] for x in pk["evidence"] if x["kind"] == "other_8k"][:2] == [A801, A402]    # newest first, among the others


def test_a_release_slot_eight_k_with_an_ex99_yields_the_release_and_its_other_item(world):
    ex = ("EX-99.1", "ex9911.htm", "<p>RELEASE_402 results.</p>")
    pk = build(world, store=store_402(world, "i402rel", [("8-K", "f402.htm", BODY_402), ex]))
    [rel] = [e for e in pk["evidence"] if e["kind"] == "release"]
    assert rel["source"]["accession"] == A402 and rel["text"] == "RELEASE_402 results."
    [e] = other(pk, A402)
    assert e["text"].index("NONRELIANCE_TEXT") < e["text"].index("RELEASE_402") and e["title"] == "8-K Items 2.02, 4.02, 9.01 (8-K body, EX-99.1)"
    assert not [a for a in pk["annotations"] if a.startswith("release_exhibit_not_found")]


def test_a_release_slot_eight_k_with_only_items_2_02_and_9_01_yields_no_other_item(world):
    pk = build(world)
    assert [e["source"]["accession"] for e in pk["evidence"] if e["kind"] == "release"] == [AREL] and other(pk, AREL) == []


def test_the_release_slot_eight_k_counts_toward_max_other_8k(world):
    assert packet.MAX_OTHER_8K == 4
    a103 = "0000000123-26-000079"
    row = (a103, "8-K", "2026-10-12", "2026-10-12T14:00:00.000Z", "2026-10-12", "1.03", "f103.htm")
    f103 = eightk_txt(a103, [("8-K", "f103.htm", "<p>Item 1.03 Bankruptcy or Receivership.</p><p>F103_TEXT</p>")])
    pk = build(world, store=store_402(world, "max", [("8-K", "f402.htm", BODY_402)], extra_rows=[row], extra_docs={f"{base(a103)}/{a103}.txt": f103}))
    others = [e["source"]["accession"] for e in pk["evidence"] if e["kind"] == "other_8k"]
    assert others == [A801, A402, a103, A701]                              # five qualify; the oldest (A502) is the fifth and is left out


def test_a_seven_01_only_eight_k_is_an_other_8k_item(world):
    pk = build(world)
    [e] = other(pk, A701)
    assert e["text"].startswith("Item 7.01 Regulation FD Disclosure.\nE701_TEXT") and "E701_DECK" in e["text"]
    assert e["title"] == "8-K Items 7.01, 9.01 (8-K body, EX-99.1)"


def test_the_release_reads_every_ex99_exhibit_in_exhibit_order(world):
    ex1 = ("EX-99.1", "ex991.htm", "<p>FIRST_EXHIBIT the press release.</p>")
    ex2 = ("EX-99.2", "ex992.htm", "<p>SECOND_EXHIBIT the shareholder letter: we suspend forward guidance.</p>")
    ex10 = ("EX-99.10", "ex9910.htm", "<p>TENTH_EXHIBIT.</p>")
    contract = ("EX-10.1", "ex101.htm", "<p>CONTRACT_TEXT</p>")
    pk = build(world, store=store_402(world, "rel2", [("8-K", "f402.htm", BODY_402), contract, ex10, ex2, ex1]))     # file order is not exhibit order
    [rel] = [e for e in pk["evidence"] if e["kind"] == "release"]
    assert rel["text"] == "FIRST_EXHIBIT the press release.\nSECOND_EXHIBIT the shareholder letter: we suspend forward guidance.\nTENTH_EXHIBIT."
    assert rel["title"] == "8-K Item 2.02 earnings release (EX-99.1 ex991.htm, EX-99.2 ex992.htm, EX-99.10 ex9910.htm)"
    assert "CONTRACT_TEXT" not in rel["text"]


def test_the_release_exhibit_order_is_ex99_then_by_number_and_01_is_1():
    docs = [{"type": t, "raw": ""} for t in ("EX-99.2", "EX-99.01", "EX-99", "EX-10.1", "EX-99.3", "EX-99.A")]
    assert [d["type"] for d in packet._release_docs(docs)] == ["EX-99", "EX-99.01", "EX-99.2", "EX-99.3", "EX-99.A"]
    assert packet._release_docs([{"type": "EX-99.1", "filename": "x.pdf", "skipped": "pdf"}]) == []


def test_the_release_is_cut_to_release_cap_over_all_exhibits_and_the_title_names_what_it_reaches(world):
    big = "".join(f"<p>{filler(f'big-{k}', 600)}</p>" for k in range(40))                  # about 24 000 characters
    ex1 = ("EX-99.1", "ex991.htm", "<p>FIRST_EXHIBIT the press release.</p>" + big)
    ex2 = ("EX-99.2", "ex992.htm", "<p>SECOND_EXHIBIT the shareholder letter.</p><p>Outlook: we suspend forward guidance and earnings calls.</p>")
    pk = build(world, store=store_402(world, "relcut", [("8-K", "f402.htm", BODY_402), ex1, ex2]))
    [rel] = [e for e in pk["evidence"] if e["kind"] == "release"]
    assert len(rel["text"]) <= packet.RELEASE_CAP and sec_primary.OMIT_RE.search(rel["text"])
    assert "we suspend forward guidance" in rel["text"]                                   # the outlook paragraph of EX-99.2 is kept
    assert rel["title"] == "8-K Item 2.02 earnings release (EX-99.1 ex991.htm, EX-99.2 ex992.htm)"
    huge2 = ("EX-99.2", "ex992.htm", "<p>" + "word " * 8000 + "</p>")
    pk = build(world, store=store_402(world, "relcut1", [("8-K", "f402.htm", BODY_402), ex1, huge2]))
    [rel] = [e for e in pk["evidence"] if e["kind"] == "release"]
    assert len(rel["text"]) <= packet.RELEASE_CAP


ARCH = packet.REGIME_ARCHIVAL
FRAME_DATE = "2026-10-02T00:00:00+00:00"


def build_a(w, ticker="TEST", T=T, commit=None, store=None, repo=None, **kw):
    return packet.build(ticker, T, commit or w["commit"], online=False, screener_repo_path=repo or w["repo"], store_root=store or w["store"],
                        regime=ARCH, **kw)


def frame_repo(root, drop=(), cik_map=None, date=FRAME_DATE):
    """The make_repo commit and then a frame commit that drops files (paths) and/or rewrites cik_map.json (a dict, written as is)."""
    repo, _ = make_repo(root)
    for path in drop:
        git(repo, "rm", "-q", path, date=date)
    if cik_map is not None:
        (repo / packet.CIK_MAP_PATH).write_text(json.dumps(cik_map), encoding="utf-8")
        git(repo, "add", packet.CIK_MAP_PATH, date=date)
    git(repo, "commit", "-q", "-m", "frame", date=date)
    return repo, git(repo, "rev-parse", "HEAD")


def test_an_archival_packet_needs_no_verified_record_and_records_the_regime(world):
    pk = build_a(world)
    v = build(world)
    sh = pk["screener"]
    assert pk["regime"] == ARCH and v["regime"] == "verified" and pk["builder_version"] == "m3m.packet.builder.v7"
    assert pk["cik_source"] == "cik_map" and pk["cik"] == CIK
    assert sh["regime"] == ARCH and sh["screener_commit_verified"] is False and sh["verified_row"] is None
    assert sh["commit_time_utc"] == "2026-10-01T00:00:00Z" and sh["commit"] == world["commit"]
    assert {k: sh[k] for k in ("stocks_blob_sha", "factor_blob_sha", "cik_map_blob_sha")} == {
        k: v["screener"][k] for k in ("stocks_blob_sha", "factor_blob_sha", "cik_map_blob_sha")}
    assert pk["evidence"] == v["evidence"] and pk["annotations"] == v["annotations"] and pk["excluded"] == v["excluded"]
    assert pk["raw_inputs"] == v["raw_inputs"] and "regime" not in v["screener"] and "commit_time_utc" not in v["screener"]
    assert packet.canonical_bytes(build_a(world)) == packet.canonical_bytes(pk)                 # deterministic, as the verified regime


def test_an_archival_commit_is_not_checked_against_any_verified_record(world):
    # the verified regime refuses a commit that is on no PASS row; the archival regime has no record to check
    with pytest.raises(packet.PacketRefused) as e:
        build(world, record=[])
    assert e.value.code == "screener_commit_not_verified"
    assert build_a(world)["screener"]["verified_row"] is None


def test_each_regime_refuses_the_argument_that_belongs_to_the_other(world):
    with pytest.raises(packet.PacketRefused) as e:
        build_a(world, verified_record=world["record"])
    assert e.value.code == "argument_not_for_regime"
    with pytest.raises(packet.PacketRefused) as e:
        packet.build("TEST", T, world["commit"], online=False, verified_record=world["record"], screener_repo_path=world["repo"],
                     store_root=world["store"], cik=CIK)
    assert e.value.code == "argument_not_for_regime"
    with pytest.raises(packet.PacketRefused) as e:                                             # verified with no record: refused as before
        packet.build("TEST", T, world["commit"], online=False, screener_repo_path=world["repo"], store_root=world["store"])
    assert e.value.code == "screener_commit_not_verified"
    with pytest.raises(packet.PacketRefused) as e:
        packet.build("TEST", T, world["commit"], online=False, screener_repo_path=world["repo"], store_root=world["store"], regime="nope")
    assert e.value.code == "regime_invalid"


def test_an_archival_commit_dated_after_T_is_refused_and_one_at_T_is_not(world):
    with pytest.raises(packet.PacketRefused) as e:
        build_a(world, T="2026-09-30T23:59:59Z")                                              # the commit is dated 2026-10-01T00:00:00Z
    assert e.value.code == "frame_commit_after_T"
    assert build_a(world, T="2026-10-01T00:00:00Z")["screener"]["commit_time_utc"] == "2026-10-01T00:00:00Z"


def test_an_archival_commit_without_stocks_json_is_refused(tmp_path):
    repo = tmp_path / "bare"
    repo.mkdir()
    (repo / "README.md").write_text("no snapshot yet", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    w = {"repo": repo, "commit": git(repo, "rev-parse", "HEAD"), "store": make_store(tmp_path / "store")}
    with pytest.raises(packet.PacketRefused) as e:
        build_a(w)
    assert e.value.code == "stocks_json_absent"


def test_an_archival_commit_where_stocks_json_was_deleted_is_refused(tmp_path):
    repo, commit = frame_repo(tmp_path / "gone", drop=(packet.STOCKS_PATH,))
    with pytest.raises(packet.PacketRefused) as e:
        build_a({"repo": repo, "commit": commit, "store": make_store(tmp_path / "store")})
    assert e.value.code == "stocks_json_absent"


@pytest.mark.parametrize("ticker,code", [("ZZZZ", "ticker_not_in_stocks"), ("MOV", "ticker_excluded"), ("NOCIK", "no_cik")])
def test_archival_refusals_shared_with_the_verified_regime(world, ticker, code):
    with pytest.raises(packet.PacketRefused) as e:
        build_a(world, ticker=ticker)
    assert e.value.code == code


def test_the_cik_comes_from_the_map_or_the_argument_and_the_source_is_recorded(tmp_path):
    w = {"store": make_store(tmp_path / "store")}
    # the commit has no cik_map.json: the argument is the CIK (and the factor file is gone too: neither is required)
    repo, commit = frame_repo(tmp_path / "nomap", drop=(packet.CIK_MAP_PATH, packet.FACTOR_PATH))
    w.update(repo=repo, commit=commit)
    with pytest.raises(packet.PacketRefused) as e:
        build_a(w)
    assert e.value.code == "no_cik"
    pk = build_a(w, cik="123")
    assert pk["cik"] == CIK and pk["cik_source"] == "argument"
    assert pk["screener"]["cik_map_blob_sha"] is None and pk["screener"]["factor_blob_sha"] is None
    assert pk["screener"]["stocks_blob_sha"] == git(repo, "rev-parse", f"{commit}:{packet.STOCKS_PATH}")
    # a map that lacks the ticker
    repo, commit = frame_repo(tmp_path / "othermap", cik_map={"map": {"NOPROF": "0000000789"}})
    w.update(repo=repo, commit=commit)
    pk = build_a(w, cik=CIK)
    assert pk["cik_source"] == "argument" and pk["screener"]["cik_map_blob_sha"] == git(repo, "rev-parse", f"{commit}:{packet.CIK_MAP_PATH}")
    # a map that has the ticker: the same argument agrees (the source stays the map), another one conflicts
    repo, commit = frame_repo(tmp_path / "samemap", cik_map={"map": {"TEST": "0000000123"}})
    w.update(repo=repo, commit=commit)
    assert build_a(w)["cik_source"] == "cik_map" and build_a(w, cik=CIK)["cik_source"] == "cik_map"
    assert build_a(w, cik=123)["cik_source"] == "cik_map"
    with pytest.raises(packet.PacketRefused) as e:
        build_a(w, cik="0000000999")
    assert e.value.code == "cik_conflict" and "0000000123" in str(e.value) and "0000000999" in str(e.value)


@pytest.mark.parametrize("bad", ["", "abc", "0", "12345678901", "12 34", -5, True, 1.5])
def test_an_unreadable_cik_argument_is_refused(world, bad):
    with pytest.raises(packet.PacketRefused) as e:
        build_a(world, cik=bad)
    assert e.value.code == "cik_invalid"


def test_the_archival_cli_builds_a_packet_with_no_verified_record(world, monkeypatch, capsys):
    monkeypatch.setattr(sec_store, "RAW_DIR", world["store"])
    monkeypatch.setattr(packet, "PACKETS_DIR", world["tmp"] / "cli_packets")
    assert packet.main(["--ticker", "TEST", "--T", T, "--commit", world["commit"], "--regime", ARCH,
                        "--screener-repo", str(world["repo"])]) == 0
    out = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(out["packet"]).read_text(encoding="utf-8"))
    assert saved["regime"] == ARCH and saved["cik_source"] == "cik_map" and out["packet_sha256"] == packet.packet_sha256(saved)
    with pytest.raises(SystemExit) as e:                                     # the default regime still needs the record
        packet.main(["--ticker", "TEST", "--T", T, "--commit", world["commit"], "--screener-repo", str(world["repo"])])
    assert e.value.code == 2


def test_effective_at_before_the_calendar():
    # 3N 2026-10-29 (control HPI, a fund with 2004 filings in filings.recent): a filing accepted before the calendar's first session is
    # effective by that session's open, not a DateOutOfBounds crash
    cal = packet._calendar()
    got = packet.effective_at(datetime(2004, 12, 29, 15, 0, tzinfo=timezone.utc))
    assert got == cal.first_session_open.to_pydatetime().astimezone(timezone.utc)
    assert got < packet.effective_at(datetime(2025, 12, 22, 15, 0, tzinfo=timezone.utc))


# ---- WO_N6: builder v6 ------------------------------------------------------------------------------------------------------------
# the going-concern note (the notes to the financial statements are outside every section) and the 8-K body shared across its listed items

TENK_URL = f"{base(A10K)}/tk-20251231.htm"
TENQ_URL = f"{base(AQ)}/tq-20260630.htm"
ITEM8 = b"<p>Item 8. Financial Statements</p><p>See the statements.</p>"
GC_PARAS = ("<p>Item 8. Financial Statements</p><p>See the statements.</p>"
            "<p>Note 1. Organization</p><p>NOTE_BEFORE the company was formed in 2001.</p>"
            "<p>Going Concern</p><p>GC_NOTE_TEXT The Company has incurred recurring losses, and these conditions raise substantial doubt about "
            "the Company's ability to continue as a going concern.</p>"
            "<p>NOTE_AFTER management plans to raise capital.</p><p>Note 2. Leases</p><p>The company leases offices.</p>")


def tenk_gc_html():
    """tenk_html() with a going-concern note after Item 8 and a going-concern risk-factor paragraph that the packet shows in P2."""
    html = tenk_html().replace(ITEM8, GC_PARAS.encode("cp1252"))
    html = html.replace(b"<p>RISK_TAIL the last risk.</p>", b"<p>RISK_TAIL the last risk.</p><p>RISK_GC_MENTION a going concern risk.</p>")
    assert html.count(b"going concern") == 2 and b"RISK_GC_MENTION" in html
    return html


def tenq_gc_html():
    """tenq_html() with a going-concern note in Part I Item 1, before the MD&A the packet shows."""
    marker = b"<p>ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS"
    html = tenq_html().replace(marker, b"<p>QGC_BEFORE the notes begin.</p><p>QGC_NOTE substantial doubt exists about the Company's ability "
                                       b"to continue as a going concern.</p><p>QGC_AFTER management's plans.</p>" + marker)
    assert b"QGC_NOTE" in html
    return html


def gc_items(pk):
    return [e for e in pk["evidence"] if e["kind"] == "gc_note"]


def gc_store(w, name, tenk=None, tenq=None):
    extra = {}
    if tenk is not None:
        extra[TENK_URL] = tenk
    if tenq is not None:
        extra[TENQ_URL] = tenq
    return with_docs(w, name, docs_extra=extra)


def test_builder_v6_constants():
    assert packet.BUILDER_VERSION == "m3m.packet.builder.v7" and packet.GC_CAP == 6_000 and packet.OTHER_8K_CAP == 4_000


def test_the_going_concern_note_follows_the_sections_of_its_filing_with_a_paragraph_each_side(world):
    pk = build(world, store=gc_store(world, "gc10k", tenk=tenk_gc_html()))
    assert [(e["fact_id"], e["kind"]) for e in pk["evidence"]][4:10] == [
        ("P1", "annual_section"), ("P2", "annual_section"), ("P3", "annual_section"), ("P4", "gc_note"), ("P5", "quarterly_section"),
        ("P6", "release")]
    [g] = gc_items(pk)
    assert g["name"] == "gc_note" and g["title"] == "10-K going concern and liquidity passages" and g["source"]["accession"] == A10K
    assert g["source"]["url"] == TENK_URL and g["form"] == "10-K" and g["period"] == "2025-12-31"
    assert g["raw_sha256"] == hashlib.sha256(tenk_gc_html()).hexdigest()
    lines = g["text"].split("\n")
    i = next(n for n, l in enumerate(lines) if "GC_NOTE_TEXT" in l)
    assert lines[i - 1] == "Going Concern" and "NOTE_AFTER" in lines[i + 1]                  # the paragraph before and the one after
    assert "RISK_GC_MENTION" in next(e for e in pk["evidence"] if e["name"] == "risk_factors")["text"]
    assert "RISK_GC_MENTION" not in g["text"]                                              # a line the packet already shows is not repeated
    assert f"gc_text_not_found: {AQ}" in pk["annotations"] and f"gc_text_not_found: {A10K}" not in pk["annotations"]


def test_a_ten_k_with_no_going_concern_paragraph_has_no_note_and_says_so(world):
    pk = build(world)
    assert gc_items(pk) == []
    assert f"gc_text_not_found: {A10K}" in pk["annotations"] and f"gc_text_not_found: {AQ}" in pk["annotations"]
    assert [e["fact_id"] for e in pk["evidence"]] == ["S0", "F1", "F2", "F3", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]


def test_the_ten_q_has_its_own_going_concern_note_after_its_sections(world):
    pk = build(world, store=gc_store(world, "gcq", tenk=tenk_gc_html(), tenq=tenq_gc_html()))
    assert [(e["kind"], e["source"].get("accession")) for e in pk["evidence"]][6:11] == [
        ("annual_section", A10K), ("gc_note", A10K), ("quarterly_section", AQ), ("gc_note", AQ), ("release", AREL)]
    q = gc_items(pk)[1]
    assert q["title"] == "10-Q going concern and liquidity passages"
    assert all(s in q["text"] for s in ("QGC_NOTE", "QGC_BEFORE", "QGC_AFTER"))
    assert not [a for a in pk["annotations"] if a.startswith("gc_text_not_found")]


def test_gc_passages_merge_overlaps_keep_document_order_mark_gaps_and_skip_shown_lines():
    L = [f"line {n}" for n in range(30)]
    L[5] = "the going concern assumption"
    L[7] = "SUBSTANTIAL  DOUBT exists"                                                     # line 6 is shared by the two windows: one passage
    L[20] = "also a Going Concern matter"
    text, found, kept = packet.gc_passages(L)
    assert (found, kept) == (2, 2)
    assert text.split("\n") == L[4:9] + [sec_primary.OMIT.format(n=sum(len(x) + 1 for x in L[9:19]))] + L[19:22]
    assert packet.gc_passages(L, shown={L[20]})[0] == "\n".join(L[4:9]) and packet.gc_passages(L, shown={L[5]})[1:] == (2, 2)
    assert packet.gc_passages(L, shown={L[5], L[7]})[0] == "\n".join(L[19:22])
    assert packet.gc_passages(["a", "going concern", "b"])[0] == "a\ngoing concern\nb"      # the document edges
    assert packet.gc_passages(["going concern"]) == ("going concern", 1, 1)
    assert packet.gc_passages(["nothing here", "concern", "going on"]) == ("", 0, 0)


def test_over_gc_cap_passages_with_substantial_doubt_go_first_then_the_later_ones_and_the_text_stays_in_document_order():
    big = "x" * 1_000
    L = []
    for n in range(8):                                                                    # eight passages of about 1,000 characters
        L += ["filler a", f"{big} {'substantial doubt' if n in (2, 5) else 'going concern'} {n}", "filler b", "gap 1", "gap 2"]
    text, found, kept = packet.gc_passages(L, cap=3_500)
    assert found == 8 and kept == 3
    assert [int(l.rsplit(" ", 1)[1]) for l in text.split("\n") if l.startswith("x")] == [2, 5, 7]       # both `substantial doubt`, then the latest other
    assert len(sec_primary.OMIT_RE.findall(text)) == 2                                    # a marker over each of the two gaps
    assert packet.gc_passages(L, cap=100_000)[1:] == (8, 8)                               # under the cap, every passage
    one = packet.gc_passages(["a", big * 5 + " going concern", "b"], cap=500)
    assert one[1:] == (1, 1) and one[0].startswith("a\nxxx")                              # a lone passage over the cap is kept (the caller cuts it)


def test_the_going_concern_note_is_capped_and_omitted_passages_are_annotated(world):
    para = "<p>{} " + "pad " * 250 + "going concern.</p>"
    notes = "".join(para.format(f"PASSAGE_{n}") + "<p>gap</p>" * 3 for n in range(12))
    tenk = tenk_html().replace(ITEM8, notes.encode())
    pk = build(world, store=gc_store(world, "gccap", tenk=tenk))
    [g] = gc_items(pk)
    assert len(g["text"]) <= packet.GC_CAP and g["text"].count("PASSAGE_") < 12 and "PASSAGE_11" in g["text"]
    [a] = [a for a in pk["annotations"] if a.startswith("gc_passages_omitted")]
    assert a.startswith(f"gc_passages_omitted: {A10K} kept ") and a.endswith(f" of 12 (over {packet.GC_CAP} characters)")


def test_size_cap_trimming_never_counts_or_cuts_the_going_concern_notes(world, monkeypatch):
    # v7 (CROSS_CHECK_O 6a): in v6 the notes counted against TOTAL_CAP and pushed out the event 8-Ks (PTHS 4.02, EONR 3.01)
    store = gc_store(world, "gctrim", tenk=tenk_gc_html(), tenq=tenq_gc_html())
    full = build(world, store=store)
    notes = [e for e in full["evidence"] if e["kind"] == "gc_note"]
    assert len(notes) == 2
    rest = sum(len(e["text"]) for e in full["evidence"] if e["kind"] != "gc_note")
    monkeypatch.setattr(packet, "TOTAL_CAP", rest)                        # the notes alone take the packet over: nothing is cut
    pk = build(world, store=store)
    assert pk["evidence"] == full["evidence"] and not [a for a in pk["annotations"] if a.startswith("trimmed")]
    by = {(e["kind"], e["source"].get("accession")): e for e in full["evidence"] if e["kind"] != "other_8k"}
    gone = sum(len(e["text"]) for e in full["evidence"] if e["kind"] == "other_8k") + len(by["release", AREL]["text"])
    monkeypatch.setattr(packet, "TOTAL_CAP", rest - gone - 50)            # the 8-Ks and the release go; the 10-Q's sections are cut by 50
    pk = build(world, store=store)
    assert [a.split(" (")[0].rsplit(" to ", 1)[0] for a in pk["annotations"] if a.startswith("trimmed")] == [
        f"trimmed_out: other_8k other_8k {A502}", f"trimmed_out: other_8k other_8k {A701}", f"trimmed_out: other_8k other_8k {A801}",
        f"trimmed_out: release earnings_release {AREL}", f"trimmed: quarterly_section quarterly_mdna {AQ}"]
    assert [e["text"] for e in pk["evidence"] if e["kind"] == "gc_note"] == [e["text"] for e in notes]      # both notes whole
    assert sum(len(e["text"]) for e in pk["evidence"] if e["kind"] != "gc_note") <= packet.TOTAL_CAP


# 8-K body shared across its listed items

A204 = "0000000123-26-000081"           # C8-1053-QVCGA 0001104659-26-044521: Items 1.01, 1.03, 2.04, 7.01, 9.01; a long 1.01 first
ROW_204 = (A204, "8-K", "2026-10-14", "2026-10-14T14:00:00.000Z", "2026-10-13", "1.01,1.03,2.04,7.01,9.01", "f204.htm")
DEFAULT_SENTENCE = "The filing of the Chapter 11 Cases described above in Item 1.03 constitutes an event of default that accelerated the Company's obligations."
BODY_204 = ("<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 8-K</p>"
            "<p>Item 1.01 Entry into a Material Definitive Agreement.</p><p>Restructuring Support Agreement</p>" + paras("rsa", 6000, 600) +
            "<p>Item 1.03 Bankruptcy or Receivership.</p><p>BK_TEXT The Company commenced the Chapter 11 Cases.</p>"
            "<p>Item 2.04 Triggering Events that Accelerate or Increase a Direct Financial Obligation.</p>"
            f"<p>DEFAULT_TEXT {DEFAULT_SENTENCE}</p>"
            "<p>Item 7.01 Regulation FD Disclosure.</p><p>FD_TEXT Commencement of the Solicitation.</p>"
            "<p>Item 9.01 Financial Statements and Exhibits.</p><p>EXHIBIT_LIST 99.1 Press release.</p>")


def row_204(items):
    return (A204, "8-K", "2026-10-14", "2026-10-14T14:00:00.000Z", "2026-10-13", items, "f204.htm")


def store_204(w, name, body=BODY_204, exhibits=(), items="1.01,1.03,2.04,7.01,9.01"):
    return with_docs(w, name, extra_rows=[row_204(items)],
                     docs_extra={f"{base(A204)}/{A204}.txt": eightk_txt(A204, [("8-K", "f204.htm", body), *exhibits])})


def test_a_long_item_1_01_no_longer_cuts_off_the_item_2_04_after_it(world):
    pk = build(world, store=store_204(world, "i204"))
    [e] = other(pk, A204)
    assert DEFAULT_SENTENCE in e["text"] and len(e["text"]) <= packet.OTHER_8K_CAP
    for marker in ("Item 1.01", "Item 1.03", "BK_TEXT", "Item 2.04", "Item 7.01", "FD_TEXT"):       # every listed item has its own segment
        assert marker in e["text"]
    assert "rsa-0 sentence 0" in e["text"] and sec_primary.OMIT_RE.search(e["text"])             # the long one is cut, and marked
    assert "EXHIBIT_LIST" not in e["text"] and "FORM 8-K" not in e["text"]                       # Item 9.01 is no OTHER_8K_ITEMS item
    assert e["title"] == "8-K Items 1.01, 1.03, 2.04, 7.01, 9.01 (8-K body)"
    body = packet.eight_k_body_lines(packet.doc_lines(BODY_204), ["1.01", "1.03", "2.04", "7.01", "9.01"])      # the v5 text: from 1.01 to the cap
    v5 = packet.canonical(sec_primary.prefix_text(packet.canonical("\n".join(body)), packet.OTHER_8K_CAP))
    assert DEFAULT_SENTENCE not in v5                                                             # v5 lost it


def test_space_a_short_segment_leaves_unused_passes_to_the_long_one_and_the_exhibits_fill_the_rest(world):
    body = ("<p>Item 1.01 Entry.</p><p>SHORT_ONE the agreement.</p><p>Item 8.01 Other Events.</p>" + paras("lg", 9000, 900) +
            "<p>Item 9.01 Exhibits.</p><p>list</p>")
    pk = build(world, store=store_204(world, "share2", body=body, items="1.01,8.01,9.01"))
    [e] = other(pk, A204)
    assert "SHORT_ONE the agreement." in e["text"]
    assert packet.OTHER_8K_CAP - 60 < len(e["text"]) <= packet.OTHER_8K_CAP                       # the long item got all but the short one's size
    ex = ("EX-99.1", "ex991.htm", "<p>EX99_TEXT the press release.</p>")
    short = "<p>Item 1.01 Entry.</p><p>SHORT_ONE the agreement.</p><p>Item 8.01 Other Events.</p><p>SHORT_TWO.</p><p>Item 9.01 Exhibits.</p>"
    pk = build(world, store=store_204(world, "share3", body=short, exhibits=[ex], items="1.01,8.01,9.01"))
    [e] = other(pk, A204)
    assert e["text"].index("SHORT_TWO") < e["text"].index("EX99_TEXT") and e["title"] == "8-K Items 1.01, 8.01, 9.01 (8-K body, EX-99.1)"
    assert "Item 9.01" not in e["text"]


def test_a_body_with_no_heading_of_a_qualifying_item_is_read_from_its_first_listed_heading_as_before(world):
    body = "<p>FORM 8-K</p><p>Item 9.01 Financial Statements and Exhibits.</p><p>FALLBACK_TEXT the notice.</p>"
    pk = build(world, store=store_204(world, "fb", body=body, items="8.01,9.01"))
    [e] = other(pk, A204)
    assert e["text"] == "Item 9.01 Financial Statements and Exhibits.\nFALLBACK_TEXT the notice." and "FORM 8-K" not in e["text"]


def test_eight_k_item_segments_split_at_each_listed_heading_and_read_a_combined_heading():
    lines = ["FORM 8-K", "Item 1.01 | Entry", "text a", "Items 2.03 and 2.04. Obligations", "text b", "Item 5.07 Votes", "text c", "Item 9.01 Exhibits", "d"]
    segs = packet.eight_k_item_segments(lines, ["1.01", "2.03", "2.04", "9.01"])
    assert segs == [(["1.01"], lines[1:3]), (["2.03", "2.04"], lines[3:7]), (["9.01"], lines[7:])]      # 5.07 is not listed: no heading of its own
    assert packet.eight_k_item_segments(lines, []) == [] and packet.eight_k_item_segments(["FORM 8-K"], ["1.01"]) == []
    assert packet.eight_k_item_segments(["Item 1.011 x"], ["1.01"]) == []


def test_share_gives_the_short_texts_what_they_need_and_the_long_ones_equal_parts_of_the_rest():
    out = packet._share(["a" * 100, "b" * 5_000, "c" * 5_000], 4_000)
    assert out[0] == "a" * 100 and abs(len(out[1]) - len(out[2])) <= 1
    assert 3_900 < sum(len(t) for t in out) + 2 <= 4_000
    assert all(sec_primary.OMIT_RE.search(t) for t in out[1:]) and not sec_primary.OMIT_RE.search(out[0])
    assert packet._share(["x" * 10, "y" * 20], 4_000) == ["x" * 10, "y" * 20] and packet._share(["z" * 9_000], 4_000)[0].startswith("zzz")


# an amendment is read for going-concern passages too (C2-1122-AMS: the 10-Q/A restates the balance sheet; its going-concern sentence is past
# the amendment item's AMENDMENT_CAP, and the 10-Q before it has none)

def amend_gc_html():
    return ("<html><body><p>FORM 10-Q/A</p><p>EXPLANATORY NOTE</p><p>This amendment restates the classification of debt.</p>" + paras("amgc", 5000)
            + "<p>AMGC_BEFORE the company is in default.</p><p>AMGC_TEXT As a result, these conditions raise substantial doubt about the "
              "Company's ability to continue as a going concern.</p><p>AMGC_AFTER management's plans.</p>"
            + "<p>Item 1. Financial Statements</p><p>AM2_START restated quarter.</p>" + paras("am2", 600)
            + "<p>Item 2. Management's Discussion</p><p>Restated.</p></body></html>").encode()


def test_an_amendment_has_its_own_going_concern_note_right_after_it(world):
    docs = {**AMEND_DOCS, f"{base(AAM2)}/tqa2.htm": amend_gc_html()}
    pk = build(world, store=with_docs(world, "amgc", extra_rows=[AMEND_ROWS[AAM2], AMEND_ROWS[AAM4]], docs_extra=docs))
    seq = [(e["kind"], e["source"].get("accession")) for e in pk["evidence"]]
    assert seq[seq.index(("amendment", AAM2)):][:2] == [("amendment", AAM2), ("gc_note", AAM2)] and seq.index(("gc_note", AAM2)) < seq.index(("release", AREL))
    am = [e for e in pk["evidence"] if e["kind"] == "amendment"][0]
    [g] = [e for e in gc_items(pk) if e["source"]["accession"] == AAM2]
    assert "AMGC_TEXT" not in am["text"] and all(s in g["text"] for s in ("AMGC_BEFORE", "AMGC_TEXT", "AMGC_AFTER"))     # past the amendment's cap
    assert g["title"] == "10-Q/A going concern and liquidity passages" and g["form"] == "10-Q/A" and g["source"]["url"] == f"{base(AAM2)}/tqa2.htm"
    assert f"gc_text_not_found: {AAM4}" in pk["annotations"]                              # AAM4: no amendment text and no going-concern passage, both said
    assert f"amendment_text_not_found: 10-Q/A {AAM4}" in pk["annotations"]

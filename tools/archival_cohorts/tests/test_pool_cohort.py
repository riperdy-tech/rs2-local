"""tools/archival_cohorts: the survivor-free universe, the ticker, the dates, the book's cells and quotas, the walk and the census of a
drawn name, on synthetic data (no network, no store, no ticker of any real company)."""
import hashlib
from datetime import datetime, timezone

import pool_cohort as C
import pool_k2

IDX = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Last Data Received:    Sep 30, 2025

Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
10-K        ZED ALPHA INC                                                 1001        2025-03-15  edgar/data/1001/0000001001-25-000001.txt
10-K/A      ZED ALPHA INC                                                 1001        2025-04-01  edgar/data/1001/0000001001-25-000002.txt
10-Q        ZED BETA  CORP                                                1002        2025-08-10  edgar/data/1002/0000001002-25-000001.txt
10-Q        ZED BETA CORP NEW                                             1002        2025-09-30  edgar/data/1002/0000001002-25-000002.txt
6-K         ZED GAMMA PLC                                                 1003        2025-06-01  edgar/data/1003/0000001003-25-000001.txt
20-F        ZED DELTA SA                                                  1004        2025-05-01  edgar/data/1004/0000001004-25-000001.txt
10-Q        ZED DELTA SA                                                  1004        2025-08-01  edgar/data/1004/0000001004-25-000002.txt
10-Q        ZED EPSILON LTD                                               1005        2025-03-14  edgar/data/1005/0000001005-25-000001.txt
10-Q        ZED ZETA INC                                                  1006        2025-10-01  edgar/data/1006/0000001006-25-000001.txt
10-Q        ZED ETA INC                                                   1007        2025-10-02  edgar/data/1007/0000001007-25-000001.txt
SC 13G      ZED THETA INC                                                 1008        2025-05-05  edgar/data/1008/0000001008-25-000001.txt
8-K         ZED IOTA INC                                                  1009        2025-05-05  edgar/data/1009/0000001009-25-000001.txt
"""


# ---- U1 ------------------------------------------------------------------------------------------------------------------------------

def test_form_idx_keeps_the_pool_forms_only_and_reads_columns_from_the_right():
    rows = C.parse_form_idx(IDX)
    assert {r[0] for r in rows} == {"10-K", "10-Q", "6-K", "20-F"}
    assert ("10-Q", "ZED BETA CORP", "0000001002", "2025-08-10") in rows        # the company's double space is not a column break
    assert all(len(r[2]) == 10 for r in rows)


def test_universe_window_is_200_days_to_T_inclusive_originals_only_and_foreign_tagged_not_dropped():
    u = C.universe(C.parse_form_idx(IDX), "2025-10-01")
    assert sorted(u) == ["0000001001", "0000001002", "0000001003", "0000001004", "0000001006"]
    assert u["0000001001"]["forms"] == ["10-K"]                                 # 2025-03-15 is T - 200 days: in; the 10-K/A is not read
    assert u["0000001003"]["segment"] == "foreign"                              # a 6-K filer stays, tagged
    assert u["0000001004"]["segment"] == "primary" and u["0000001004"]["forms"] == ["10-Q", "20-F"]
    assert u["0000001002"]["name"] == "ZED BETA CORP NEW"                       # the latest filing's name
    assert "0000001005" not in u and "0000001007" not in u                      # T - 201 days and T + 1 day: out


def test_quarters_touch_the_window():
    from datetime import date
    assert C.quarters(date(2025, 3, 15), date(2025, 10, 1)) == [(2025, 1), (2025, 2), (2025, 3), (2025, 4)]
    assert C.quarters(date(2025, 12, 31), date(2026, 1, 1)) == [(2025, 4), (2026, 1)]


# ---- the ticker ----------------------------------------------------------------------------------------------------------------------

def test_ticker_company_tickers_first_then_submissions_else_null():
    tickers = C.by_cik({"ZB": ("0000000001", "One"), "ZA": ("0000000001", "One"), "ZC": ("0000000002", "Two")})
    assert tickers == {"0000000001": "ZA", "0000000002": "ZC"}
    asked = []

    def subs_of(cik):
        asked.append(cik)
        return {"0000000003": {"tickers": ["zy", "ZX"]}, "0000000004": {"tickers": []}}.get(cik, {})
    assert C.ticker_of("0000000001", tickers, subs_of) == ("ZA", "company_tickers") and asked == []
    assert C.ticker_of("0000000003", tickers, subs_of) == ("ZX", "submissions")
    assert C.ticker_of("0000000004", tickers, subs_of) == (None, "submissions")
    assert C.ticker_of("0000000005", tickers, subs_of) == (None, "submissions")


# ---- the dates -----------------------------------------------------------------------------------------------------------------------

def test_fy0_window_is_k2s_rule_shifted():
    assert C.fy0_window("2025-10-01") == pool_k2.FY0_WINDOW == ("2024-10-02", "2025-06-30")
    assert C.fy0_window("2026-01-01") == ("2025-01-02", "2025-09-30")
    assert C.fy0_window("2026-04-01") == ("2025-04-02", "2025-12-31")
    assert C.fy0_window("2026-07-01") == ("2025-07-02", "2026-03-31")


def test_frame_quarter_is_k2s_at_k2s_T_and_ends_45_days_before_T():
    assert C.frame_quarter("2025-10-01") == (2025, 2)                           # K2's CY2025Q2I
    assert C.frame_quarter("2026-01-01") == (2025, 3)
    assert C.frame_quarter("2026-04-01") == (2025, 4)
    assert C.frame_quarter("2026-07-01") == (2026, 1)


def test_session_and_T():
    assert C.session_at("2025-10-01") == pool_k2.SESSION
    assert C.session_at("2026-01-01") == "2025-12-31"                           # a holiday: the session before
    assert C.at("2025-10-01") == (pool_k2.T, pool_k2.T_STR)


# ---- the book's cells, quotas, the draw order ----------------------------------------------------------------------------------------

def test_book_cells_terciles_by_rank_and_quotas_sum_to_target():
    book = {f"Z{i}": {"sector": "A" if i % 2 else "B", "market_cap": (i + 1) * 1e9, "family": "operating" if i % 3 else "commodity"}
            for i in range(9)}
    unrouted = {"ZF": {"sector": "A", "market_cap": 1e12, "family": "financial"}, "ZN": {"sector": "C", "market_cap": 1e6,
                                                                                          "family": "family_not_built"}}
    cut, cells = C.book_cells(dict(book, **unrouted))           # a family outside the valued routes gets no quota and moves no cutoff
    assert cut == (3e9, 6e9)
    assert [C.tercile(x, cut) for x in (3e9, 3.0001e9, 6e9, 6.1e9)] == [1, 2, 2, 3]
    assert sum(cells.values()) == 9 and cells == {"B|T1": 2, "A|T1": 1, "A|T2": 2, "B|T2": 1, "B|T3": 2, "A|T3": 1}
    for target in (1, 5, 20, 125):
        q = C.quotas(cells, target)
        assert sum(q.values()) == target and set(q) == set(cells)
    assert C.quotas(cells, 3) == {"A|T2": 1, "B|T1": 1, "B|T3": 1, "A|T1": 0, "A|T3": 0, "B|T2": 0}   # equal fractions: by cell name


def test_draw_key_is_sha256_of_ticker_or_cik_and_the_date():
    assert C.draw_key({"ticker": "ZA", "cik": "0000000001"}, "2025-10-01") == hashlib.sha256(b"ZA|2025-10-01").hexdigest()
    assert C.draw_key({"ticker": None, "cik": "0000000001"}, "2025-10-01") == hashlib.sha256(b"0000000001|2025-10-01").hexdigest()


# ---- the walk ------------------------------------------------------------------------------------------------------------------------

def test_walk_records_every_name_and_fills_only_with_primary_passes():
    cut = (1e9, 5e9)
    quota = {"A|T1": 1, "B|T2": 1, "C|T1": 0}
    sec = {"n3": "A", "n4": "A", "n5": "D", "n6": None, "n7": "A", "n9": "B", "n10": "B"}
    cands = [{"ticker": "n1", "segment": "primary", "cap_prefilter": None}, {"ticker": "n2", "segment": "primary", "cap_prefilter": None},
             {"ticker": "n3", "segment": "foreign", "cap_prefilter": 5e8}, {"ticker": "n4", "segment": "primary", "cap_prefilter": 5e8},
             {"ticker": "n5", "segment": "primary", "cap_prefilter": 5e8}, {"ticker": "n6", "segment": "primary", "cap_prefilter": 5e8},
             {"ticker": "n7", "segment": "primary", "cap_prefilter": 5e8}, {"ticker": "n8", "segment": "primary", "cap_prefilter": 6e8},
             {"ticker": "n9", "segment": "primary", "cap_prefilter": 2e9}, {"ticker": "n10", "segment": "primary", "cap_prefilter": 3e9}]
    caps = {"n1": (None, "none filed"), "n2": (2e8, None)}
    asked = []

    def sector_of(r):
        asked.append(r["ticker"])
        return sec[r["ticker"]], "x", "sector_screener_at_T"

    def census(r):
        return dict(r, stage="december" if r["ticker"] == "n4" else None)
    names, fill = C.walk(cands, quota, cut, lambda r: caps[r["ticker"]], sector_of, census)
    got = {n["ticker"]: (n["stage"], n.get("reason")) for n in names}
    assert len(names) == len(cands)
    assert got == {"n1": ("no_cap_at_T", "no_shares_filed_by_T"), "n2": ("below_min_cap", "below_min_cap"),
                   "n3": (None, None), "n4": ("december", None), "n5": ("not_drawn", "cell_quota_zero"),
                   "n6": ("no_sector", "no_sector"), "n7": (None, None), "n8": ("not_drawn", "cell_full"),
                   "n9": (None, None), "n10": ("not_drawn", "draw_complete")}
    assert fill == {"A|T1": 1, "B|T2": 1, "C|T1": 0}                           # the foreign pass (n3) fills nothing
    assert "n8" not in asked                                                   # a full tercile asks for no sector
    n2 = next(n for n in names if n["ticker"] == "n2")
    assert n2["cap_source"] == "companyfacts" and n2["cap_prefilter"] == 2e8
    assert next(n for n in names if n["ticker"] == "n7")["cell"] == "A|T1"


# ---- the census of a drawn name ------------------------------------------------------------------------------------------------------

def _cf(val, filed):
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"val": val, "end": filed, "filed": filed, "accn": "a1"}]}}}}}


def test_census_s0_row_cap_at_T_and_j2_one_called_with_the_window(monkeypatch):
    T = datetime(2025, 10, 1, 21, tzinfo=timezone.utc)
    calls = []
    monkeypatch.setattr(C.P, "get_doc", lambda url, store, offline: b"{}")
    docs = {"0000000001": _cf(10_000_000, "2025-08-01"), "0000000002": _cf(10_000_000, "2025-10-02")}
    monkeypatch.setattr(C.facts, "fetch", lambda cik, T, online, root: (docs[cik], {"name": "Zed One"}, {}))

    def one(company, store, offline, window):
        calls.append((company, window))
        return dict(company, stage=None, reason=None)
    monkeypatch.setattr(C.P, "one", one)
    rec = {"cik": "0000000001", "ticker": "ZA", "name": "ZED ONE", "close": 50.0, "split_factor": 2.0, "sector": "A", "industry": "x",
           "sector_source": "sector_from_screener_today", "loc": "US-ZZ", "segment": "primary"}
    out = C.census(rec, None, True, T, "2025-10-01", ("2024-10-02", "2025-06-30"))
    assert out["stage"] is None and calls[0][1] == ("2024-10-02", "2025-06-30") and calls[0][0]["market_cap"] == 5e8
    assert out["s0_row"] == {"symbol": "ZA", "name": "Zed One", "sector": "A", "industry": "x", "country": "US-ZZ", "price": 50.0,
                             "marketCap": 500000000, "Last_Updated": "2025-10-01"}
    assert out["s0_stamps"] == ["sector_not_point_in_time", "sector_from_screener_today", "price_split_unadjusted_x2"]
    late = C.census(dict(rec, cik="0000000002"), None, True, T, "2025-10-01", ("2024-10-02", "2025-06-30"))
    assert (late["stage"], late["reason"]) == ("cap_at_T", "no_shares_filed_by_T") and len(calls) == 1   # shares filed after T: none

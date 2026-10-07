"""The lazy loader of the D5 daily raw closes (Addendum L4): the traded close from the split-adjusted Close and the exact split ex-dates, the contract of `DailyPriceSource`, the next
session's OPEN as the entry, a bounded memory, and the refusals."""
import gzip
from datetime import date, timedelta

import pytest

from rebuild_harness import daily_prices as dp, outcomes
from valuation.common import DataNotPresent
from valuation.pit_data import DailyPriceSource, PitData

HDR = "Date,Open,High,Low,Close,Adj Close,Volume,Dividends,Stock Splits"


def write(folder, ticker, bars):
    """bars: [(iso, open, close, adj, split)] -> <ticker>.csv.gz (high/low/volume filled)."""
    lines = [HDR] + [f"{d},{o},{c},{c},{c},{a},1000,0,{s}" for d, o, c, a, s in bars]
    with gzip.open(folder / f"{ticker}.csv.gz", "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run(start, n, c0, step, adj_factor=1.0, skip_weekends=False):
    out, d, i = [], date.fromisoformat(start), 0
    while len(out) < n:
        if not (skip_weekends and d.weekday() >= 5):
            c = c0 + step * i
            out.append((d.isoformat(), c - 0.5, c, c * adj_factor, 0))
            i += 1
        d += timedelta(days=1)
    return out


def test_the_traded_close_is_close_times_the_splits_after_the_session_and_the_ex_date_is_exact(tmp_path):
    bars = [("2020-08-27", 125.0, 125.0, 120.0, 0), ("2020-08-28", 124.0, 124.8, 120.9, 0), ("2020-08-31", 127.5, 129.04, 125.06, 4.0), ("2020-09-01", 130.0, 134.18, 130.0, 0)]
    write(tmp_path, "AAA", bars)
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.has_key("AAA") and not s.has_key("NOPE")
    assert s.close_unadjusted("AAA", "2020-08-28").price == pytest.approx(124.8 * 4.0)        # the traded close before the 4-for-1
    assert s.close_unadjusted("AAA", "2020-08-31").price == pytest.approx(129.04)             # the ex-date's close is already post-split
    assert s.close_unadjusted("AAA", "2020-09-01").price == pytest.approx(134.18)
    assert s.splits("AAA") == [("2020-08-31", 4.0)] and s.last_date("AAA") == "2020-09-01"
    assert s.close_unadjusted("AAA", "2020-08-28").quality == "verified" and s.close_unadjusted("AAA", "2020-08-28").flags == ()
    assert s.adj_close("AAA", "2020-08-28").price == pytest.approx(120.9)


def test_two_splits_and_a_reverse_split_compose(tmp_path):
    write(tmp_path, "B", [("2020-01-02", 1, 10.0, 10.0, 0), ("2020-02-03", 1, 11.0, 11.0, 2.0), ("2020-03-02", 1, 12.0, 12.0, 0), ("2020-04-01", 1, 13.0, 13.0, 0.1), ("2020-05-01", 1, 14.0, 14.0, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.close_unadjusted("B", "2020-01-02").price == pytest.approx(10.0 * 2.0 * 0.1)
    assert s.close_unadjusted("B", "2020-03-02").price == pytest.approx(12.0 * 0.1)
    assert s.close_unadjusted("B", "2020-04-01").price == pytest.approx(13.0)


def test_it_serves_the_same_values_as_the_in_memory_daily_source_including_the_gap_rule(tmp_path):
    bars = run("2020-01-01", 120, 50.0, 0.5, adj_factor=0.9, skip_weekends=True)
    write(tmp_path, "C", bars)
    mem = DailyPriceSource({"C": {d: {"close": c, "adj": a} for d, o, c, a, s in bars}}, splits={"C": []})
    lazy = dp.LazyDailyPriceSource(tmp_path, entry_field="adj_close")
    for q in ("2020-01-01", "2020-01-04", "2020-01-05", "2020-01-06", "2020-03-15", "2020-05-25", "2020-06-30", "2019-12-31"):
        a, b = lazy.close_unadjusted("C", q), mem.close_unadjusted("C", q)
        assert (a is None) == (b is None) and (a is None or (a.price == pytest.approx(b.price) and a.bar == b.bar and a.flags == b.flags and a.quality == b.quality)), q
        a, b = lazy.adj_close("C", q), mem.adj_close("C", q)
        assert (a is None) == (b is None) and (a is None or (a.price == pytest.approx(b.price) and a.bar == b.bar)), q
        a, b = lazy.entry_point("C", q), mem.entry_point("C", q)
        assert (a is None) == (b is None) and (a is None or (a.price == pytest.approx(b.price) and a.bar == b.bar)), q


def test_a_stale_bar_is_flagged_and_a_bar_beyond_the_gap_is_none(tmp_path):
    write(tmp_path, "D", [("2020-01-02", 1, 10.0, 10.0, 0), ("2020-01-03", 1, 11.0, 11.0, 0), ("2020-02-03", 1, 12.0, 12.0, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    p = s.close_unadjusted("D", "2020-01-06")                    # three days after the last bar: stale, unverified
    assert p.price == 11.0 and "stale_bar" in p.flags and p.quality == "unverified"
    assert s.close_unadjusted("D", "2020-01-08") is not None and s.close_unadjusted("D", "2020-01-09") is None      # more than 5 days after the bar: none
    assert s.close_unadjusted("D", "2019-12-31") is None


def test_the_entry_is_the_next_sessions_adjusted_open_not_the_decision_close(tmp_path):
    # the next session (2020-02-03) opens at 100 with a close of 110 and an adjusted close of 99: the adjusted open is 100 x 99 / 110 = 90
    write(tmp_path, "E", [("2020-01-31", 100.0, 105.0, 94.5, 0), ("2020-02-03", 100.0, 110.0, 99.0, 0), ("2020-02-04", 111.0, 112.0, 100.8, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    e = s.entry_point("E", "2020-01-31")
    assert e.price == pytest.approx(90.0) and e.bar == "2020-02-03"
    assert s.entry_point("E", "2020-02-04") is None and s.entry_point("E", "2020-01-30").bar == "2020-01-31"      # strictly after the date; none past the last bar
    assert dp.LazyDailyPriceSource(tmp_path, entry_field="adj_close").entry_point("E", "2020-01-31").price == pytest.approx(99.0)
    with pytest.raises(ValueError):
        dp.LazyDailyPriceSource(tmp_path, entry_field="close")


def test_a_bar_with_no_positive_value_is_none_and_the_previous_bar_is_not_substituted(tmp_path):
    write(tmp_path, "F", [("2020-01-02", 1, 10.0, 10.0, 0), ("2020-01-03", 1, "nan", "nan", 0), ("2020-01-06", 0, 12.0, 12.0, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.close_unadjusted("F", "2020-01-03") is None and s.adj_close("F", "2020-01-03") is None
    assert s.entry_point("F", "2020-01-03") is None                # the next bar opens at 0: no entry, never the close
    assert s.close_unadjusted("F", "2020-01-06").price == 12.0


def test_the_cache_is_bounded_and_values_survive_eviction(tmp_path):
    for i in range(12):
        write(tmp_path, f"T{i}", [("2020-01-02", 1, 10.0 + i, 10.0 + i, 0), ("2020-01-03", 1, 11.0 + i, 11.0 + i, 0)])
    s = dp.LazyDailyPriceSource(tmp_path, max_cached=3)
    for i in range(12):
        assert s.close_unadjusted(f"T{i}", "2020-01-03").price == 11.0 + i
        assert s.cached() <= 3
    assert s.close_unadjusted("T0", "2020-01-02").price == 10.0 and s.cached() == 3
    s.drop_cache()
    assert s.cached() == 0


def test_refusals(tmp_path):
    with pytest.raises(DataNotPresent, match="does not exist"):
        dp.LazyDailyPriceSource(tmp_path / "nowhere")
    write(tmp_path, "U", [("2020-01-03", 1, 10.0, 10.0, 0), ("2020-01-02", 1, 11.0, 11.0, 0)])
    with pytest.raises(DataNotPresent, match="not strictly increasing"):
        dp.LazyDailyPriceSource(tmp_path).close_unadjusted("U", "2020-01-03")
    write(tmp_path, "V", [("2020-01-02", 1, 10.0, 10.0, 0), ("2020-01-02", 1, 11.0, 11.0, 0)])
    with pytest.raises(DataNotPresent, match="not strictly increasing"):
        dp.LazyDailyPriceSource(tmp_path).close_unadjusted("V", "2020-01-02")
    with gzip.open(tmp_path / "W.csv.gz", "wt") as f:
        f.write("Date,Close\n2020-01-02,1\n")
    with pytest.raises(DataNotPresent, match="no column"):
        dp.LazyDailyPriceSource(tmp_path).close_unadjusted("W", "2020-01-02")


def test_validate_folder_reports_what_a_loader_must_know(tmp_path):
    write(tmp_path, "A", [("2020-01-02", 1, 10.0, 10.0, 0), ("2020-01-03", 1, 11.0, 11.0, 2.0)])
    write(tmp_path, "BAD", [("2020-01-03", 1, 10.0, 10.0, 0), ("2020-01-02", 1, 11.0, 11.0, 0)])
    write(tmp_path, "Z", [("2020-01-02", 1, 0.0, 0.0, 0)])
    (tmp_path / "manifest.csv").write_text("ticker,rows,first_date,last_date,status\nA,2,x,y,ok\nZ,5,x,y,ok\nGONE,3,x,y,ok\nEMPTY,0,,,empty\n", encoding="utf-8")
    r = dp.validate_folder(tmp_path)
    assert r["files"] == 3 and [x[0] for x in r["unparseable"]] == ["BAD"] and r["splits"] == 1 and r["bars"] == 3
    assert r["rows_mismatch"] == [["Z", 5, 1]] and r["files_with_nonpositive_close"] == 1 and r["not_in_manifest"] == [] and r["manifest_ok_without_file"] == ["GONE"]


def test_outcomes_run_on_the_lazy_source_with_the_registered_entry(tmp_path):
    a = run("2020-01-01", 400, 100.0, 1.0)
    write(tmp_path, "A", a)
    write(tmp_path, "SPY", run("2020-01-01", 400, 300.0, 0.0))
    pit = PitData("unused", price_source=dp.LazyDailyPriceSource(tmp_path))
    o = outcomes.horizon_outcome(pit, "A", "2020-01-10", 3)       # entry 2020-01-11: open 110 - 0.5 = 109.5; exit 2020-04-10 close 200 (adj = close)
    assert o["status"] == "observed" and o["ret"] == pytest.approx(200.0 / 109.5 - 1.0) and "no_next_session_in_monthly_data" not in o["flags"]


def test_a_split_the_close_history_was_not_adjusted_for_is_not_applied_to_the_traded_close(tmp_path):
    # a 1-for-50 reverse split (ratio 0.02) whose earlier closes are the traded prices (0.33 -> 13.88 across the ex-date): Close is raw, so the traded close is the Close itself
    write(tmp_path, "RAW", [("2026-09-10", 0.33, 0.33, 0.33, 0), ("2026-09-11", 0.33, 0.33, 0.33, 0), ("2026-09-14", 13.88, 13.88, 13.88, 0.02), ("2026-09-15", 12.7, 12.77, 12.77, 0)])
    # the same split with the history adjusted by Yahoo (the earlier closes already x50: 16.5 -> 13.88, continuous): the traded close is Close x 0.02
    write(tmp_path, "ADJ", [("2026-09-10", 16.5, 16.5, 16.5, 0), ("2026-09-11", 16.5, 16.5, 16.5, 0), ("2026-09-14", 13.88, 13.88, 13.88, 0.02), ("2026-09-15", 12.7, 12.77, 12.77, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.close_unadjusted("RAW", "2026-09-11").price == pytest.approx(0.33) and s.raw_split_events("RAW") == [("2026-09-14", 0.02)]
    assert s.close_unadjusted("ADJ", "2026-09-11").price == pytest.approx(16.5 * 0.02) and s.raw_split_events("ADJ") == []
    assert s.splits("RAW") == [("2026-09-14", 0.02)] == s.splits("ADJ")                # the event itself (a real share-count change) is kept either way
    assert s.raw_split_events("NOPE") is None


def test_a_raw_forward_split_and_the_ambiguous_small_ratios(tmp_path):
    write(tmp_path, "FWD", [("2020-01-02", 400.0, 400.0, 400.0, 0), ("2020-01-03", 100.0, 100.0, 100.0, 4.0), ("2020-01-06", 101.0, 101.0, 101.0, 0)])      # raw: the price fell to a quarter
    write(tmp_path, "DIV", [("2020-01-02", 10.0, 10.0, 10.0, 0), ("2020-01-03", 9.6, 9.6, 9.6, 1.05), ("2020-01-06", 9.7, 9.7, 9.7, 0)])                    # ratio within 1.5-fold: taken as adjusted
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.close_unadjusted("FWD", "2020-01-02").price == pytest.approx(400.0) and s.raw_split_events("FWD") == [("2020-01-03", 4.0)]
    assert s.close_unadjusted("DIV", "2020-01-02").price == pytest.approx(10.0 * 1.05) and s.raw_split_events("DIV") == []
    r = dp.validate_folder(tmp_path)
    assert r["raw_split_events"] == 1 and r["files_with_raw_split_events"] == 1


def test_the_ex_date_bar_without_a_price_is_judged_across_the_neighbouring_priced_bars(tmp_path):
    write(tmp_path, "HALT", [("2026-09-03", 0.15, 0.15, 0.15, 0), ("2026-09-04", 0.15, 0.148, 0.148, 0), ("2026-09-08", "nan", "nan", "nan", 0.05), ("2026-09-09", 2.7, 2.74, 2.74, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.raw_split_events("HALT") == [("2026-09-08", 0.05)] and s.close_unadjusted("HALT", "2026-09-04").price == pytest.approx(0.148)


def test_a_marginal_jump_is_taken_as_adjusted_not_raw(tmp_path):
    # a 1-for-5 reverse split (ratio 0.2) with a jump of 2.5x across the ex-date: the raw reading is the closer one (log error 0.69 against 0.92) but not decisively (it is not under half the
    # adjusted reading's error): the default, adjusted, stands.  A jump of 5x is decisive (error 0 against 1.6): raw (the tests above).
    write(tmp_path, "MARG", [("2024-12-06", 6.0, 6.0, 6.0, 0), ("2024-12-09", 15.0, 15.0, 15.0, 0.2), ("2024-12-10", 14.0, 14.0, 14.0, 0)])
    s = dp.LazyDailyPriceSource(tmp_path)
    assert s.raw_split_events("MARG") == [] and s.close_unadjusted("MARG", "2024-12-06").price == pytest.approx(6.0 * 0.2)

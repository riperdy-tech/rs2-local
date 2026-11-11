"""The warning log with prices (WO_HM3a): rows for every resolved read, fills at 1, 20 and 60 sessions from SPY's bars, annotated missing prices,
the summary. Stub prices only; the network is blocked."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import monitor as M
import warning_log as W

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)            # last completed session: Wed 2026-10-28
T0 = "2026-08-03T01:00:00Z"                                         # the session before it: Fri 2026-07-31
D0 = date(2026, 7, 31)
D1 = date(2026, 8, 3)
LEDGER = lambda: {"books": {"arm_b": ["TSTA", "TSTB"], "arm_a": ["TSTA"]}, "ledger_formation_T": "2026-10-01T00:00:00Z"}


def sessions(first=date(2026, 7, 1), last=date(2026, 10, 28), drop=()):
    return [d for d in (first + timedelta(days=i) for i in range((last - first).days + 1)) if M.is_session(d) and d not in drop]


class Prices:
    """A fetch stub: {ticker: [(date, close)]}; SPY is flat at 100 on every session unless given. Records its calls; `fail` lists tickers that raise."""
    def __init__(self, data=None, drop=()):
        self.data = {"SPY": [(d, 100.0) for d in sessions(drop=drop)], **(data or {})}
        self.calls, self.fail = [], set()

    def __call__(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if ticker in self.fail:
            raise RuntimeError("boom")
        return "stub", [(d, c) for d, c in self.data.get(ticker, []) if start <= d <= end]

    def of(self, ticker):
        return [c for c in self.calls if c[0] == ticker]


def journal(root, *lines):
    M.Monitor(root)._write_journal([
        {"kind": "resolved", "event_id": "resolved:" + l["run_id"], "t": "2026-08-03T03:00:00Z", "cik": 7, "name_state": "thesis_intact", "thesis_compare": "unchanged",
         "q1": {"verdict": "none"}, "warning_kind": None, "decision_time_utc": T0, "triggers": [{"id": "x", "kind": "sec_filing", "priority": 1}], **l}
        for l in lines])


def flat(c0, c1, days=(D0, D1)):
    return [(d, c) for d, c in zip(days, (c0, c1))]


def log_lines(root):
    return [json.loads(l) for l in W.log_path(root).read_text(encoding="utf-8").splitlines() if l.strip()]


def test_warned_and_unwarned_reads_both_become_rows(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA", "warning_kind": "news_event", "name_state": "news_event", "q1": {"verdict": "news_event"}},
            {"run_id": "R2", "ticker": "TSTC"})
    rep = W.update(root, NOW, Prices(), LEDGER)
    r = {x["run_id"]: x for x in W.rows(root)}
    assert rep["rows_added"] == 2 and set(r) == {"R1", "R2"}
    assert r["R1"]["warning_kind"] == "news_event" and r["R1"]["q1_verdict"] == "news_event" and r["R2"]["warning_kind"] is None
    assert r["R1"]["held_by"] == ["arm_a", "arm_b"] and r["R2"]["held_by"] == [] and r["R1"]["ledger_formation_T"] == "2026-10-01T00:00:00Z"
    assert r["R1"]["triggers"] == [{"id": "x", "kind": "sec_filing", "priority": 1}] and r["R1"]["read_at"] == "2026-08-03T03:00:00Z"
    assert r["R1"]["decision_time_utc"] == T0 and r["R1"]["cik"] == 7 and r["R1"]["thesis_compare"] == "unchanged"


def test_an_older_resolved_line_without_triggers_logs_null(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA", "triggers": None})
    W.update(root, NOW, Prices(), LEDGER)
    assert W.rows(root)[0]["triggers"] is None


def test_a_second_update_adds_nothing(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    px = Prices({"TSTA": [(d, 50.0) for d in sessions()]})
    W.update(root, NOW, px, LEDGER)
    before = W.log_path(root).read_bytes()
    n = len(px.calls)
    rep = W.update(root, NOW, px, LEDGER)
    assert W.log_path(root).read_bytes() == before and rep["rows_added"] == 0 and rep["fills_written"] == {}
    assert len(px.calls) == n                                                 # nothing open: not even the yardstick is fetched again


def test_a_horizon_not_yet_due_writes_nothing(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA", "decision_time_utc": "2026-10-27T01:00:00Z"})       # base Mon 10-26, d1 Tue 10-27, d20 is far off
    px = Prices({"TSTA": [(d, 50.0) for d in sessions()]})
    rep = W.update(root, NOW, px, LEDGER)
    fills = W.rows(root)[0]["fills"]
    assert set(fills) == {"1"} and rep["not_yet_due"] == 2 and rep["fills_written"] == {"1": {"ok": 1}}
    assert fills["1"]["ret_from_next_close"] is None and fills["1"]["spy_ret_from_next_close"] is None     # k = 1 has no "from the next close"
    assert fills["1"]["d0"] == "2026-10-26" and fills["1"]["dk"] == "2026-10-27"
    assert len(px.of("TSTA")) == 1                                            # no fetch for a horizon that is not due


def test_all_three_closes_of_a_fill_come_from_one_fetch(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    ss = sessions()
    i = ss.index(D0)
    px = Prices({"TSTA": [(d, 100.0 + n) for n, d in enumerate(ss)]})
    W.update(root, NOW, px, LEDGER)
    f = W.rows(root)[0]["fills"]["20"]
    assert (f["d0"], f["d1"], f["dk"]) == (D0.isoformat(), ss[i + 1].isoformat(), ss[i + 20].isoformat())
    assert (f["c0"], f["c1"], f["ck"]) == (100.0 + i, 101.0 + i, 120.0 + i) and f["status"] == "ok" and f["source"] == "stub"
    assert f["ret_from_before"] == pytest.approx(f["ck"] / f["c0"] - 1) and f["ret_from_next_close"] == pytest.approx(f["ck"] / f["c1"] - 1)
    assert (f["spy_c0"], f["spy_ret_from_before"], f["spy_ret_from_next_close"]) == (100.0, 0.0, 0.0)
    assert px.of("TSTA").count(("TSTA", D0 - timedelta(days=7), ss[i + 20])) == 1 and len(px.of("TSTA")) == 3    # k = 1, 20 and 60 are all due: one fetch each, to dk
    assert len(px.of("SPY")) == 1                                              # one yardstick fetch for the whole update


def test_a_missing_bar_gives_stale_bar_with_the_used_dates(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    ss = sessions()
    dk = ss[ss.index(D0) + 20]
    px = Prices({"TSTA": [(d, 10.0 + n) for n, d in enumerate(ss) if d not in (dk, D1)]})
    W.update(root, NOW, px, LEDGER)
    f = W.rows(root)[0]["fills"]["20"]
    assert f["status"] == "stale_bar" and f["used_d0"] == D0.isoformat() and f["used_d1"] == D0.isoformat() and f["c1"] == f["c0"]
    assert f["used_dk"] == ss[ss.index(dk) - 1].isoformat() and f["d1"] == D1.isoformat() and f["dk"] == dk.isoformat()


def test_no_bars_after_the_base_date_waits_then_is_no_price(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    px = Prices({"TSTA": [(D0, 10.0)]})                                         # delisted after d0
    rep = W.update(root, datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc), px, LEDGER)      # SPY bars after d1 (08-03): 08-04 .. 08-10 is 5
    assert W.rows(root)[0]["fills"] == {} and rep["no_bars_yet"] == 1 and rep["not_yet_due"] == 2
    W.update(root, datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc), px, LEDGER)      # six: more than 5 past due
    f = W.rows(root)[0]["fills"]["1"]
    assert f["status"] == "no_price" and f["last_bar_date"] == D0.isoformat() and f["last_bar_close"] == 10.0 and f["c0"] is None
    assert f["spy_c0"] == 100.0 and f["ret_from_before"] is None


def test_no_bar_on_the_base_date_uses_the_last_bar_before_it(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})                           # halted on d0 (Fri 07-31): the close of Thu 07-30 is the close before
    px = Prices({"TSTA": [(date(2026, 7, 30), 10.0), (D1, 12.0)]})
    W.update(root, datetime(2026, 8, 5, 21, 0, tzinfo=timezone.utc), px, LEDGER)
    f = W.rows(root)[0]["fills"]["1"]
    assert f["status"] == "stale_bar" and f["used_d0"] == "2026-07-30" and f["c0"] == 10.0 and f["ret_from_before"] == pytest.approx(0.2)


def test_no_bar_at_all_on_or_before_the_base_date_is_no_price_not_stale(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    W.update(root, datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc), Prices({"TSTA": [(D1, 10.0)]}), LEDGER)
    f = W.rows(root)[0]["fills"]["1"]
    assert f["status"] == "no_price" and f["last_bar_date"] == D1.isoformat() and f["last_bar_close"] == 10.0


def test_a_raising_fetch_is_reported_and_retried(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"}, {"run_id": "R2", "ticker": "TSTB"})
    px = Prices({"TSTA": flat(10.0, 11.0), "TSTB": flat(10.0, 12.0)})
    px.fail = {"TSTA"}
    now = datetime(2026, 8, 5, 21, 0, tzinfo=timezone.utc)
    rep = W.update(root, now, px, LEDGER)
    assert list(rep["errors"]) == ["TSTA"] and "boom" in rep["errors"]["TSTA"] and rep["fills_written"] == {"1": {"ok": 1}}
    assert {r["ticker"]: set(r["fills"]) for r in W.rows(root)} == {"TSTA": set(), "TSTB": {"1"}}
    px.fail = set()
    rep = W.update(root, now, px, LEDGER)
    assert rep["errors"] == {} and rep["rows_added"] == 0 and rep["fills_written"] == {"1": {"ok": 1}}
    assert {r["ticker"]: set(r["fills"]) for r in W.rows(root)} == {"TSTA": {"1"}, "TSTB": {"1"}}
    px.fail = {"SPY"}                                                           # a failing yardstick: no fill written, reported
    journal(root, {"run_id": "R3", "ticker": "TSTC"})
    assert "SPY" in W.update(root, now, px, LEDGER)["errors"] and len(log_lines(root)) == 5     # 3 reads + 2 fills


def test_a_close_of_zero_is_a_value(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    W.update(root, datetime(2026, 8, 5, 21, 0, tzinfo=timezone.utc), Prices({"TSTA": flat(10.0, 0.0)}), LEDGER)
    f = W.rows(root)[0]["fills"]["1"]
    assert f["c1"] == 0.0 and f["ck"] == 0.0 and f["ret_from_before"] == -1.0 and f["status"] == "ok"


def test_a_nan_close_is_dropped(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    W.update(root, datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc), Prices({"TSTA": [(D0, 10.0), (D1, float("nan"))]}), LEDGER)
    f = W.rows(root)[0]["fills"]["1"]
    assert f["status"] == "no_price" and f["last_bar_date"] == D0.isoformat()          # the NaN bar does not count as a bar after d0


def test_a_yardstick_holiday_shifts_the_horizon(root):
    holiday = date(2026, 9, 22)                                                 # a Tuesday the yardstick has no bar for (not in the holiday table)
    journal(root, {"run_id": "R1", "ticker": "TSTA", "decision_time_utc": "2026-09-22T01:00:00Z"})       # base Mon 09-21
    W.update(root, NOW, Prices({"TSTA": [(d, 10.0) for d in sessions() if d != holiday]}, drop=(holiday,)), LEDGER)
    f = W.rows(root)[0]["fills"]["1"]
    assert f["d0"] == "2026-09-21" and f["d1"] == "2026-09-23" and f["status"] == "ok"


def test_held_by_is_null_when_the_ledger_cannot_be_read(root):
    def broken():
        raise M.MonitorError("no ledger")
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    rep = W.update(root, NOW, Prices(), broken)
    r = W.rows(root)[0]
    assert r["held_by"] is None and r["ledger_formation_T"] is None and "no ledger" in rep["ledger_error"]


def test_summary_counts_mean_and_median(root):
    journal(root, {"run_id": "A", "ticker": "TSTA", "warning_kind": "thesis_changed"}, {"run_id": "B", "ticker": "TSTB", "warning_kind": "thesis_changed"},
            {"run_id": "E", "ticker": "TSTE", "warning_kind": "thesis_changed"}, {"run_id": "C", "ticker": "TSTC"},
            {"run_id": "D", "ticker": "TSTD", "warning_kind": "event_found"})
    px = Prices({"TSTA": flat(100.0, 110.0), "TSTB": flat(100.0, 80.0), "TSTE": flat(100.0, 130.0), "TSTC": flat(100.0, 105.0), "TSTD": []})
    px.data["SPY"] = [(d, 102.0 if d == D1 else 100.0) for d in sessions()]       # SPY +2% on d1, so every excess is the return minus 0.02
    W.update(root, datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc), px, LEDGER)
    s = W.summary(root)
    tc, nw, ev = s["thesis_changed"]["1"], s["no_warning"]["1"], s["event_found"]["1"]
    assert (tc["rows"], tc["priced"], tc["no_price"], tc["excess_n"]) == (3, 3, 0, 3)
    assert tc["excess_mean"] == pytest.approx((0.08 - 0.22 + 0.28) / 3) and tc["excess_median"] == pytest.approx(0.08)
    assert (nw["rows"], nw["priced"]) == (1, 1) and nw["excess_mean"] == pytest.approx(0.03) and nw["excess_median"] == pytest.approx(0.03)
    assert (ev["rows"], ev["priced"], ev["no_price"], ev["excess_mean"], ev["excess_median"]) == (1, 0, 1, None, None)
    assert s["news_event"]["1"]["rows"] == 0 and s["thesis_changed"]["20"]["priced"] == 0 and s["thesis_changed"]["20"]["rows"] == 3


def test_a_torn_last_line_of_the_log_is_not_buried(root):
    journal(root, {"run_id": "R1", "ticker": "TSTA"})
    W.update(root, NOW, Prices(), LEDGER)
    with open(W.log_path(root), "ab") as f:
        f.write(b'{"kind": "read", "event_id": "read:TORN')
    journal(root, {"run_id": "R2", "ticker": "TSTC"})
    W.update(root, NOW, Prices(), LEDGER)
    raw = W.log_path(root).read_text(encoding="utf-8").splitlines()
    assert sum(1 for l in raw if "read:TORN" in l) == 1 and all(l.endswith("}") or "read:TORN" in l for l in raw)
    assert {r["run_id"] for r in W.rows(root)} == {"R1", "R2"}


def test_the_cli_summary_prints_json(root, capsys):
    assert W.main(["summary", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["no_warning"]["1"]["rows"] == 0

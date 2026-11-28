"""The daily Telegram report: which jobs are problems, the AI book's lines, one report a session. No scheduler, network or Telegram here."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_report as R  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 28, 14, 0, tzinfo=KST)          # a Saturday here: the day after a US Friday


def task(name, state="Ready", result=0, last="2026-11-28T06:00:01", nxt="2026-11-29T06:00:00"):
    return {"name": name, "state": state, "result": result, "last": last, "next": nxt}


def logs(tmp_path, news=("2026-11-28T07:12:00 gather 2026-11-27: 2 stocks", "2026-11-28T07:32:52 act: 1 stocks"), worker="2026-11-28T13:49:00 [gemini] nothing to analyse"):
    n, w = tmp_path / "news.log", tmp_path / "worker.log"
    n.write_text("\n".join(news) + "\n", encoding="utf-8")
    w.write_text(worker + "\n", encoding="utf-8")
    return {"news_log": n, "worker_log": w}


def nav(date, value, **benches):
    return {"date": date, "nav": value, "benches": benches}


def ledgers(book, written="2026-11-28T03:49:00Z"):
    return {"last_updated": written, "ledgers": {R.BOOK: book}}


BOOK = {"nav_series": [nav("2026-11-26", 100.0, SPY=100.0, AGG=50.0, QQQ=200.0, IWM=10.0, DRAM=5.0, SOXL=20.0),
                       nav("2026-11-27", 101.0, SPY=110.0, AGG=50.0, QQQ=198.0, IWM=10.0, DRAM=5.5, SOXL=22.0)],
        "state": {"cash": 1.01, "holdings": {f"S{k}": {"entry_price": 10.0} for k in range(6)}},
        "last_marks": {f"S{k}": 10.0 + k for k in range(6)},
        "trades": [{"date": "2026-11-26", "side": "buy", "ticker": "OLD"}, {"date": "2026-11-27", "side": "buy", "ticker": "S5"},
                   {"date": "2026-11-27", "side": "buy", "ticker": "S4"}, {"date": "2026-11-27", "side": "sell", "ticker": "OLD"}]}


def test_a_failed_last_run_and_an_overdue_start_are_problems_and_a_running_task_is_not():
    tasks = [task("RS2-A"), task("RS2-B", result=2), task("RS2-C", nxt="2026-11-28T13:00:00"), task("RS2-D", nxt="2026-11-28T13:50:00"),
             task("RS2-E", state="Running", result=2147946720, nxt="2026-11-28T12:00:00"), task("RS2-F", result=267011, last=None, nxt=None)]
    assert R.task_problems(tasks, NOW) == ["RS2-B: last run (2026-11-28T06:00:01) ended with error code 2", "RS2-C: did not start at 2026-11-28T13:00:00"]


def test_all_ran_is_said_only_when_the_tasks_and_the_three_results_are_in_order(tmp_path):
    text, session = R.compose(NOW, [task("RS2-A"), task("MRI-B")], ledgers(BOOK), **logs(tmp_path))
    assert text.splitlines()[:2] == ["Daily report 2026-11-28 14:00", "JOBS: all ran (2 scheduled jobs, news watch, site worker, site close run)."]
    assert session == "2026-11-27"


def test_a_job_that_ended_well_and_did_nothing_is_a_problem(tmp_path):
    quiet = logs(tmp_path, news=("2026-11-27T07:12:00 gather 2026-11-26: 2 stocks", "2026-11-28T07:12:00 gather 2026-11-27: 2 stocks"),
                 worker="2026-11-28T12:30:00 [gemini] nothing to analyse")
    text, _ = R.compose(NOW, [task("RS2-A")], ledgers(BOOK, written="2026-11-27T16:24:35Z"), **quiet)
    assert text.splitlines()[1:5] == ["JOBS: 3 PROBLEMS", "- news watch: today's log has no gather and act lines", "- site worker: no log line in the last hour",
                                      "- site: the paper ledgers were not written after today's close run (last 2026-11-27T16:24:35Z)"]


def test_the_site_run_is_not_asked_for_on_a_day_after_no_us_session_and_unreadable_sources_are_said(tmp_path):
    sunday = datetime(2026, 11, 29, 14, 0, tzinfo=KST)
    ok = logs(tmp_path, news=("2026-11-29T07:12:00 gather 2026-11-28: 2 stocks", "2026-11-29T07:32:52 act: 0 stocks"), worker="2026-11-29T13:49:00 [gemini] x")
    assert "JOBS: all ran" in R.compose(sunday, [task("RS2-A", nxt="2026-11-30T06:00:00")], ledgers(BOOK, written="2026-11-28T03:49:00Z"), **ok)[0]
    text, session = R.compose(sunday, None, None, **ok)
    assert "- the Windows scheduler could not be read" in text and "- site: the paper ledgers could not be read" in text and session is None


def test_the_book_gives_value_day_and_start_beside_the_six_lines_and_names_the_trades_of_the_session():
    out, session = R.book_lines(BOOK)
    assert session == "2026-11-27" and out[:3] == ["AI BOOK, session 2026-11-27 (day 2)", "Value 101.00: since start (2026-11-26) +1.00%; day +1.00%",
                                                   "Holds 6 stocks, cash 1.0% of value"]
    assert out[3:9] == ["  60/40: since start +6.00%; day +6.00%", "  QQQ: since start -1.00%; day -1.00%", "  SPY: since start +10.00%; day +10.00%",
                        "  IWM: since start +0.00%; day +0.00%", "  DRAM: since start +10.00%; day +10.00%", "  SOXL: since start +10.00%; day +10.00%"]
    assert out[9:11] == ["Bought (2): S4, S5", "Sold (1): OLD"]
    assert out[11:] == ["Best since entry: S5 +50.00%, S4 +40.00%, S3 +30.00%", "Worst since entry: S0 +0.00%, S1 +10.00%, S2 +20.00%"]


def test_a_first_day_has_no_day_change_and_a_missing_line_reads_n_a_and_zero_is_a_value():
    one = dict(BOOK, nav_series=[nav("2026-11-27", 100.0, SPY=110.0, QQQ=198.0)], state={"cash": 0.0, "holdings": {}})
    out, _ = R.book_lines(one)
    assert out[1] == "Value 100.00: since start (2026-11-27) +0.00%; day n/a" and out[2] == "Holds 0 stocks, cash 0.0% of value"
    assert out[3] == "  60/40: since start n/a; day n/a" and out[5] == "  SPY: since start +0.00%; day n/a" and out[8] == "  SOXL: since start n/a; day n/a"


def test_many_names_are_cut_with_a_count_and_a_session_is_reported_once_and_an_empty_book_says_so():
    many = dict(BOOK, trades=[{"date": "2026-11-27", "side": "buy", "ticker": f"T{k:02d}"} for k in range(45)])
    line = R.book_lines(many)[0][9]
    assert line.startswith("Bought (45): T00, T01") and line.endswith("T39 and 5 more")
    assert R.book_lines(BOOK, last_reported="2026-11-27") == (["AI BOOK: no new session since 2026-11-27. Value 101.00: since start (2026-11-26) +1.00%."], "2026-11-27")
    assert R.book_lines({"nav_series": [], "state": {"cash": 100.0, "holdings": {}}}) == (["AI BOOK: no row yet (it starts at the first close run after it was added)."], None)
    assert R.book_lines(None)[1] is None


def test_sixty_forty_is_set_back_every_close_and_skips_a_day_missing_a_close():
    rows = [nav("d1", 1, SPY=100.0, AGG=100.0), nav("d2", 1, SPY=110.0), nav("d3", 1, SPY=121.0, AGG=110.0)]
    assert R.sixty_forty(rows) == {"d1": 100.0, "d3": 100.0 * (1 + 0.6 * 0.21 + 0.4 * 0.10)}

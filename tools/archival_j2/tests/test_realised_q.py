"""realised_q.py (PREREG_cohorts_nextq v0.1): the first quarter after T, measured inside its own filing, on synthetic SEC JSON."""
import realised_q as Q
from test_realised import cf, fact, subs

T = "2025-10-01"
QA, QB = "0000000001-25-000010", "0000000001-25-000011"


def test_the_first_report_date_after_T_is_the_quarter_and_growth_is_inside_its_filing():
    c = cf(Revenues=[fact("2025-09-28", "2025-12-27", 110.0, QA, "2026-02-05", "10-Q", "Q1"),
                     fact("2024-09-29", "2024-12-28", 100.0, QA, "2026-02-05", "10-Q", "Q1")])
    s = subs(("10-Q", QA, "2026-02-05", "2025-12-27"), ("10-Q", QB, "2025-11-05", "2025-09-27"))
    r = Q.realised_q(c, s, T, "2026-11-10")
    assert r["status"] == "ok" and r["quarter"]["report_date"] == "2025-12-27" and abs(r["revenue_growth"] - 0.10) < 1e-12


def test_a_quarter_filed_after_by_is_not_seen():
    s = subs(("10-Q", QA, "2026-02-05", "2025-12-27"))
    assert Q.realised_q(cf(Revenues=[]), s, T, "2026-01-31")["status"] == "no_quarter_filed"


def test_a_first_quarter_ending_long_after_T_is_a_gap_not_a_forecast():
    s = subs(("10-Q", QA, "2026-05-05", "2026-03-31"))
    assert Q.realised_q(cf(Revenues=[]), s, T, "2026-11-10")["status"] == "quarter_gap"


def test_an_amendment_serves_only_where_no_original_reports_the_period():
    s = subs(("10-Q/A", QB, "2026-03-01", "2025-12-31"), ("10-Q", QA, "2026-02-05", "2025-12-31"))
    q, st = Q.next_quarter_filing(s, T, "2026-11-10")
    assert st == "ok" and q["accession"] == QA and q["stamp"] is None
    q, st = Q.next_quarter_filing(subs(("10-Q/A", QB, "2026-03-01", "2025-12-31")), T, "2026-11-10")
    assert q["accession"] == QB and q["stamp"] == "from_amendment"


def test_no_same_filing_pair_is_counted_not_imputed():
    s = subs(("10-Q", QA, "2026-02-05", "2025-12-27"))
    r = Q.realised_q(cf(Revenues=[fact("2025-09-28", "2025-12-27", 110.0, QA, "2026-02-05", "10-Q", "Q1")]), s, T, "2026-11-10")
    assert r["status"] != "ok" and r["revenue_growth"] is None

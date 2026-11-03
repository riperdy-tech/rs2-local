"""pool.py (J2-1): the prepare stage with the cost-of-equity step skipped, the release rule, the exclusions before the census, on synthetic
data (no network, no store, no ticker of any real company)."""
from datetime import datetime, timezone

import pytest

import pool as P
from qwen_c.tests import test_value_checks as C
from qwen_c.value import coe

FY0 = "2024-12-31"
K0, K1, Q3 = "0000000001-25-000001", "0000000001-26-000002", "0000000001-25-000030"


# ---- prepare: every data step runs, the cost-of-equity step is skipped ------------------------------------------------------------

def test_prepare_runs_every_data_step_and_skips_only_the_cost_of_equity(monkeypatch):
    real_coe = coe.cost_of_equity
    monkeypatch.setattr(P.run.facts, "build", lambda *a, **k: C.facts())
    status, why, b = P.prepare_at_T("0000000001", "Technology", 180e6, "operating", None)
    assert (status, why) == ("ok", None) and b["R0"] > 0 and "ytd" in b
    assert P.run.coe.cost_of_equity is real_coe and P.run.inputs.base.__name__ == "base"      # both put back


def test_prepare_refusals_leave_with_their_code(monkeypatch):
    monkeypatch.setattr(P.run.facts, "build", lambda *a, **k: C.facts())
    status, why, _ = P.prepare_at_T("0000000001", "Technology", 0, "operating", None)          # stocks.json writes 0 for an unmeasured cap
    assert status == "refused" and why.startswith("market_cap_unavailable")
    status, why, _ = P.prepare_at_T("0000000001", "Technology", 180e6, "family_not_built", None)
    assert status == "refused" and why.startswith("family_not_routed")


# ---- the release rule --------------------------------------------------------------------------------------------------------------

def subs(*rows):
    """submissions from (form, accession, filingDate, acceptanceDateTime, items, reportDate)."""
    cols = ("form", "accessionNumber", "filingDate", "acceptanceDateTime", "items", "reportDate")
    return {"filings": {"recent": {c: [r[i] for r in rows] for i, c in enumerate(cols)}}}


# SEC's Z clock is read at its LATER reading (packet.accepted_at): "10:00Z" is 10:00 ET, before 17:30, effective the next session
TENQ = ("10-Q", Q3, "2025-11-04", "2025-11-04T10:00:00.000Z", "", "2025-09-30")     # Tuesday: effective Wednesday 11-05


def rel(acc, day, hhmm="12:00"):
    return ("8-K", acc, day, f"{day}T{hhmm}:00.000Z", "2.02,9.01", "")


def test_a_release_one_session_after_the_10q_stays_and_two_sessions_excludes():
    ytd = {"accn": Q3}
    same = P.release_rule(subs(TENQ, rel("R0", "2025-11-04")), ytd)                  # same day, after the 10-Q
    assert not same["excluded"] and same["releases"][0]["sessions"] == 0
    nxt = P.release_rule(subs(TENQ, rel("R1", "2025-11-05")), ytd)                   # next day: effective 11-06, one session later
    assert not nxt["excluded"] and nxt["releases"][0]["sessions"] == 1
    two = P.release_rule(subs(TENQ, rel("R2", "2025-11-06")), ytd)                   # effective 11-07: two sessions
    assert two["excluded"] and two["releases"][0]["sessions"] == 2


def test_a_release_before_the_10q_or_effective_after_T_is_not_counted():
    ytd = {"accn": Q3}
    before = P.release_rule(subs(TENQ, rel("RB", "2025-10-28")), ytd)
    assert before["releases"] == [] and not before["excluded"]
    after = P.release_rule(subs(TENQ, rel("RA", "2025-12-31", "18:00")), ytd)        # 18:00 ET on T: effective in 2026
    assert after["releases"] == [] and not after["excluded"]
    not_202 = P.release_rule(subs(TENQ, ("8-K", "RX", "2025-11-20", "2025-11-20T12:00:00.000Z", "5.02", "")), ytd)
    assert not_202["releases"] == []


def test_the_session_count_skips_weekends_and_holidays():
    a = datetime(2025, 11, 26, 14, 30, tzinfo=timezone.utc)                        # Wednesday open
    b = datetime(2025, 12, 1, 14, 30, tzinfo=timezone.utc)                         # Monday open; Thanksgiving 11-27 closed, 11-28 open
    assert P.sessions_between(a, b) == 2


# ---- the exclusions before the census ----------------------------------------------------------------------------------------------

def fact(start, end, val, accn, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "accn": accn, "filed": filed, "form": form, "fp": "FY"}


def cf(r0_first=1000.0, r0_same=1000.0, gp=None, cost=None):
    g = {"Revenues": {"units": {"USD": [fact("2024-01-01", FY0, r0_first, K0, "2025-02-20"), fact("2025-01-01", "2025-12-31", 1100.0, K1, "2026-02-19"),
                                        fact("2024-01-01", FY0, r0_same, K1, "2026-02-19")]}},
         "OperatingIncomeLoss": {"units": {"USD": [fact("2025-01-01", "2025-12-31", 110.0, K1, "2026-02-19"),
                                                   fact("2024-01-01", FY0, 90.0, K1, "2026-02-19")]}}}
    if gp:
        g["GrossProfit"] = {"units": {"USD": [fact("2025-01-01", "2025-12-31", gp[0], K1, "2026-02-19"), fact("2024-01-01", FY0, gp[1], K1, "2026-02-19")]}}
        g["CostOfRevenue"] = {"units": {"USD": [fact("2025-01-01", "2025-12-31", cost[0], K1, "2026-02-19"), fact("2024-01-01", FY0, cost[1], K1, "2026-02-19")]}}
    return {"facts": {"us-gaap": g}}


SUBS = subs(("10-K", K0, "2025-02-20", "2025-02-20T21:00:00.000Z", "", FY0), TENQ,
            ("10-K", K1, "2026-02-19", "2026-02-19T21:00:00.000Z", "", "2025-12-31"))
YTD = {"accn": Q3, "revenue_tag": "Revenues"}


def test_a_clean_name_is_kept_and_its_record_carries_no_realised_number():
    reasons, rec = P.exclusions(cf(), SUBS, FY0, YTD)
    assert reasons == {}
    assert rec["realised_status"] == "ok" and rec["realised_margin_available"] is True and rec["base_move_evaluable"] is True
    flat = repr(rec)
    assert "1100" not in flat and "growth_same" not in flat and "margin\"" not in flat and "0.1" not in flat


def test_a_base_moved_more_than_one_growth_point_is_excluded():
    reasons, _ = P.exclusions(cf(r0_first=1100.0), SUBS, FY0, YTD)                  # 1100/1000 - 1 against 1100/1100 - 1: 10 points
    assert set(reasons) == {"base_move"} and reasons["base_move"]["growth_gap_points"] == pytest.approx(0.10)
    reasons, rec = P.exclusions(cf(r0_first=1007.0), SUBS, FY0, YTD)                # base -0.7%, 0.76 points: kept, the restatement recorded
    assert reasons == {} and rec["restated_base"] is True


def test_the_total_revenue_abstention_excludes_and_closure_keeps():
    assert P.exclusions(cf(gp=(400.0, 350.0), cost=(700.0, 650.0)), SUBS, FY0, YTD)[0] == {}
    reasons, _ = P.exclusions(cf(gp=(400.0, 350.0), cost=(300.0, 650.0)), SUBS, FY0, YTD)
    assert set(reasons) == {"revenue_scope"} and reasons["revenue_scope"]["status"] == "closure_fail"


def test_no_year1_filing_is_recorded_not_excluded_and_item_202_uses_fy0_plus_365():
    s = subs(("10-K", K0, "2025-02-20", "2025-02-20T21:00:00.000Z", "", FY0), TENQ)
    reasons, rec = P.exclusions(cf(), s, FY0, YTD)
    assert reasons == {} and rec["realised_status"] == "no_year1_annual_filing" and rec["base_move_evaluable"] is False
    assert rec["year1_end_used"] == "2025-12-31" and rec["year1_end_stamp"] == "year1_end_fy0_plus_365"


def test_item_202_public_before_T_excludes():
    # a 52-week year ending 2025-12-27 whose results 8-K is accepted 2025-12-30: public before T
    s = subs(("10-K", K0, "2025-02-20", "2025-02-20T21:00:00.000Z", "", FY0), TENQ,
             ("8-K", "E", "2025-12-30", "2025-12-30T13:00:00.000Z", "2.02", ""),
             ("10-K", K1, "2026-02-19", "2026-02-19T21:00:00.000Z", "", "2025-12-27"))
    reasons, rec = P.exclusions(cf(), s, FY0, YTD)
    assert "item_202_public" in reasons and reasons["item_202_public"]["accession"] == "E"


def test_a_tag_mismatch_is_reported_not_excluded():
    reasons, rec = P.exclusions(cf(), SUBS, FY0, dict(YTD, revenue_tag="RevenueFromContractWithCustomerExcludingAssessedTax"))
    assert reasons == {} and rec["tag_mismatch"] is True


def test_the_name_check_ignores_legal_suffixes():
    assert P.name_shared("Acme Widgets, Inc.", "ACME WIDGETS INC")
    assert not P.name_shared("Acme Holdings Inc.", "Zenith Corp")

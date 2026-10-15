"""Engine v2.2's discount rate (REGISTRATION_wacc_v22.md rev 2; SPEC_rebuild AL.54-AL.60): the rating table and spread ladder, market weights,
the refusals, the materiality exception and the minimum spread over terminal growth."""
import json
import math

import pytest

from valuation import discount_rate_v2 as D

THRESH = [[-100000.0, "D2/D"], [0.2, "C2/C"], [0.65, "Ca2/CC"], [0.8, "Caa/CCC"], [1.25, "B3/B-"], [1.5, "B2/B"], [1.75, "B1/B+"], [2.0, "Ba2/BB"],
          [2.25, "Ba1/BB+"], [2.5, "Baa2/BBB"], [3.0, "A3/A-"], [4.25, "A2/A"], [5.5, "A1/A+"], [6.5, "Aa2/AA"], [8.5, "Aaa/AAA"]]
SPREADS = {"Aaa/AAA": 0.004, "Aa2/AA": 0.0055, "A1/A+": 0.007, "A2/A": 0.0078, "A3/A-": 0.0089, "Baa2/BBB": 0.0111, "Ba1/BB+": 0.0138, "Ba2/BB": 0.0184,
           "B1/B+": 0.0275, "B2/B": 0.0321, "B3/B-": 0.0509, "Caa/CCC": 0.0885, "Ca2/CC": 0.1261, "C2/C": 0.16, "D2/D": 0.19}
RF, BU, ERP = 0.045, 1.0, 0.045


def tables(tmp_path, aaa=0.008, baa=0.018):
    (tmp_path / "ratings_v22.json").write_text(json.dumps({"thresholds": THRESH, "spreads_by_year": {"2026": SPREADS, "2025": SPREADS}}))
    (tmp_path / "anchors_v22.json").write_text(json.dumps({"AAA10Y": {"2026-07-29": aaa, "2026-07-31": 0.5}, "BAA10Y": {"2026-07-29": baa, "2026-07-31": 0.5}}))
    return D.CreditTables(tmp_path)


def providers():
    return (lambda d: (RF, "rf"), lambda d, ind: (BU, "beta", {}), lambda d: (ERP, "erp", {}))


def state(**kw):
    st = {"tax_rate": 0.21, "operating_income": 100.0, "debt": 400.0, "debt_incl_finance_leases": 400.0, "base_period": "2025-12-31"}
    st.update(kw)
    return st


def run(t, st, price=10.0, shares=100.0, gi=20.0, quarters=()):
    rfp, bp, ep = providers()
    return D.operating_discount_rate(st, "2026-07-31", industry="x", price=price, shares=shares, gross_interest=gi, gross_interest_tag="InterestExpense",
                                     quarter_records=list(quarters), rf_provider=rfp, beta_provider=bp, erp_provider=ep, tables=t)


def test_the_rating_follows_the_coverage_thresholds_and_the_anchors_are_read_strictly_before_t(tmp_path):
    t = tables(tmp_path)
    assert t.rating(10.0) == "Aaa/AAA" and t.rating(2.7) == "Baa2/BBB" and t.rating(1.0) == "Caa/CCC" and t.rating(-5.0) == "D2/D"
    assert t.anchor("AAA10Y", "2026-07-31") == (0.008, "2026-07-29")              # the 07-31 observation (0.5) is not before T
    with pytest.raises(D.DiscountRefusal):
        t.anchor("BAA10Y", "2026-07-29")


def test_the_spread_ladder_interpolates_investment_grade_adds_below_it_and_caps_distress_at_ccc(tmp_path):
    t = tables(tmp_path, aaa=0.008, baa=0.018)
    assert math.isclose(t.spread("Aaa/AAA", "2026-07-31")[0], 0.008)
    assert math.isclose(t.spread("Baa2/BBB", "2026-07-31")[0], 0.018)
    w = (0.0078 - 0.004) / (0.0111 - 0.004)
    assert math.isclose(t.spread("A2/A", "2026-07-31")[0], 0.008 + w * 0.010)
    assert math.isclose(t.spread("B2/B", "2026-07-31")[0], 0.018 + (0.0321 - 0.0111))              # additive, never multiplicative
    for r in ("Ca2/CC", "C2/C", "D2/D"):
        s, info = t.spread(r, "2026-07-31")
        assert math.isclose(s, 0.018 + (0.0885 - 0.0111)) and info["rating_used"] == "Caa/CCC"


def test_market_weights_hamada_on_market_de_and_the_rated_cost_of_debt(tmp_path):
    t = tables(tmp_path)
    r = run(t, state(), price=10.0, shares=100.0, gi=20.0)                                         # E 1000, D 400, coverage 5 -> A2/A
    assert r.de_basis == "market" and math.isclose(r.de_ratio, 0.4)
    assert math.isclose(r.beta_levered, BU * (1 + 0.79 * 0.4))
    kd = RF + t.spread("A2/A", "2026-07-31")[0]
    assert math.isclose(r.kd_pretax, kd) and r.sources["v22"]["rating"] == "A2/A"
    dv = 400 / 1400
    assert math.isclose(r.wacc, (1 - dv) * r.coe + dv * kd * 0.79)


def test_refusals_are_named_and_nothing_is_floored_silently(tmp_path):
    t = tables(tmp_path)
    with pytest.raises(D.DiscountRefusal, match="no market capitalisation"):
        run(t, state(), price=None)
    with pytest.raises(D.DiscountRefusal, match="no gross interest"):
        run(t, state(), gi=None)                                                                    # debt weight 29% > 5%
    with pytest.raises(D.DiscountRefusal, match="not positive"):
        run(t, state(), gi=-7.0)                                                                    # MAN's case: a negative interest line
    with pytest.raises(D.DiscountRefusal, match="within 2.0% of terminal growth"):
        rfp, bp, ep = providers()
        D.operating_discount_rate(state(debt=0.0, debt_incl_finance_leases=0.0), "2026-07-31", industry="x", price=10.0, shares=100.0,
                                  gross_interest=None, gross_interest_tag=None, quarter_records=[],                 # k_e = 4.6%, g_T = 3.75%
                                  rf_provider=rfp, beta_provider=lambda d, i: (0.1, "b", {}), erp_provider=lambda d: (0.01, "e", {}), tables=t)


def test_immaterial_debt_gets_the_aaa_floor_flagged_instead_of_a_refusal(tmp_path):
    t = tables(tmp_path)
    r = run(t, state(debt=40.0, debt_incl_finance_leases=40.0), gi=None)                          # D/(D+E) = 40/1040 < 5%
    assert "kd_immaterial_floor" in r.sources["v22"]["flags"] and math.isclose(r.kd_pretax, RF + 0.008)


def test_zero_debt_needs_no_cost_of_debt_and_distressed_coverage_is_flagged(tmp_path):
    t = tables(tmp_path)
    r = run(t, state(debt=0.0, debt_incl_finance_leases=0.0), gi=None)
    assert r.kd_pretax is None and math.isclose(r.wacc, r.coe)
    r = run(t, state(operating_income=-50.0), gi=20.0)
    assert "distressed_debt" in r.sources["v22"]["flags"] and r.sources["v22"]["rating"] == "D2/D"


def test_the_latest_10q_debt_replaces_the_annual_only_when_both_components_are_filed_before_t(tmp_path):
    st = state(debt=400.0, debt_incl_finance_leases=450.0)                                         # 50 of finance leases
    q = [{"field": "debt_current", "period_end": "2026-03-31", "filed": "2026-05-01", "value": 100.0},
         {"field": "debt_lt_noncurrent", "period_end": "2026-03-31", "filed": "2026-05-01", "value": 500.0},
         {"field": "debt_current", "period_end": "2026-06-30", "filed": "2026-08-05", "value": 1.0}]   # filed after T: unseen
    d, basis, flags = D.latest_balance_debt(st, q, "2026-07-31")
    assert d == 650.0 and basis == "10-Q 2026-03-31" and flags == []
    d, basis, flags = D.latest_balance_debt(st, q[:1], "2026-07-31")
    assert d == 450.0 and flags == ["debt_annual_only"]
    assert D.latest_balance_debt(st, [], "2026-07-31") == (450.0, "annual", [])


def test_gross_interest_reads_the_2024_element_and_never_the_net_one():
    class C:
        def facts_table(self, asof, tags=None):
            rows = [("InterestIncomeExpenseNet", -9.0), ("InterestExpenseNonoperating", 12.0), ("InterestExpenseDebt", 11.0)]
            return [{"tag": t, "unit": "USD", "state": D.PIT_VALID, "instant": False, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-20",
                     "accession": "a", "value": v} for t, v in rows if tags is None or t in tags]
    assert D.gross_interest_at(C(), "2025-12-31", "2026-07-31") == (12.0, "InterestExpenseNonoperating")
    assert D.gross_interest_at(None, "2025-12-31", "2026-07-31") == (None, None)


def test_the_financial_rule_is_the_same_gap_on_the_cost_of_equity():
    assert math.isclose(D.check_min_gap(0.08, 0.045, "financial"), 0.0375)
    with pytest.raises(D.DiscountRefusal, match="cost of equity"):
        D.check_min_gap(0.05, 0.045, "financial")


def test_the_built_tables_load_when_present():
    from pathlib import Path
    root = Path(r"C:\Users\riper\stocks\stocks-workspace\data\discount_v22")
    if not (root / "ratings_v22.json").exists():
        pytest.skip("built tables not present")
    t = D.CreditTables(root)
    s, info = t.spread("Baa2/BBB", "2022-06-30")
    assert info["january_table"] == 2022 and s > 0
    assert t.rating(5.0) == "A2/A"

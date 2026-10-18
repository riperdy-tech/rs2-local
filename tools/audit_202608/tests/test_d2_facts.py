"""Brief D2b2 (BRIEF_D2b2_pack_facts.md): the pack facts that produce the `d2` members, and their wiring (sidecar, context, desk switch).

1. Legacy unchanged: the new facts are sidecar-only, parity ignores them, the context only carries d2, and without `d2_enabled` the desk is today's.
2. Measurement of every member from constructed fundamentals rows: IFRS lessee, US GAAP finance lessee, no leases, net cash, a currency mismatch,
   the financial route, partial history, the schedule versus the a0 fallback, 0.0 kept as a value.
3. L3: r_tc_after_lease_interest beside r_tc.
"""
import copy
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import d2_facts as D  # noqa: E402
import pack_facts  # noqa: E402
import throughcycle_record as tcr  # noqa: E402
import consensus_reference as cr  # noqa: E402


def row(y, **kw):
    r = {"revenue": 1000.0 + 50 * (y - 2021), "capex": 80.0, "da": 70.0, "net_income": 100.0, "pretax_income": 130.0, "tax_provision": 26.0,
         "interest_expense": 20.0, "lt_debt": 300.0, "debt_lt_noncurrent": 300.0, "debt_current": 20.0, "cash": 60.0, "st_investments": 10.0,
         "equity": 500.0, "total_assets": 1200.0, "total_liabilities": 700.0, "current_assets": 400.0, "current_liabilities": 250.0,
         "amortization_intangibles": 5.0}
    r.update(kw)
    return r


def rows(**kw):
    return {str(y): row(y, **kw) for y in range(2021, 2026)}


def build(rs=None, **kw):
    args = dict(sic=3571, sector="Technology", financial_sectors=("Financial Services", "Real Estate"), price=10.0, shares=100.0,
                statement_currency="USD", quote_currency="USD", currency_source="test", valuation_date="2026-10-18", pi=1.0, unit=1.0)
    args.update(kw)
    return D.build(rs if rs is not None else rows(), 2025, **args)


# ---- 1. legacy ------------------------------------------------------------------------------------------------------------------------------

def test_the_new_keys_are_sidecar_only_and_version_12():
    assert pack_facts.FACTS_VERSION == 12
    for k in ("d2", "d2_provenance", "d2_unavailable"):
        assert k in pack_facts.KEYS and k in pack_facts.SIDECAR_ONLY
        assert pack_facts.empty()[k] is None
    assert pack_facts.parity({"d2": {"family": "operating"}}, {"d2": None}) == []
    assert "r_tc_after_lease_interest" in pack_facts.LONG_RUN_UNPRINTED
    a = pack_facts.quantize_long_run({"r_tc": 0.1, "r_tc_after_lease_interest": 0.09})
    b = pack_facts.quantize_long_run({"r_tc": 0.1})
    assert a.pop("r_tc_after_lease_interest") == 0.09 and a == b
    assert pack_facts.parity({"long_run": pack_facts.quantize_long_run({"r_tc": 0.1, "r_tc_after_lease_interest": 0.09})},
                             {"long_run": b}) == []


def test_the_context_carries_d2_and_the_desk_ignores_it_unless_enabled():
    import consensus_valuation as cv
    import financial_model_tool as fmt
    f = pack_facts.empty()
    f["shares_default"] = 1.0
    f["d2"] = {"family": "operating"}
    ctx = cv.build_desk_context(f, 10.0, "T", "Co")
    assert ctx["d2"] == {"family": "operating"} and "d2_enabled" not in ctx
    params = {"scenarios": [{"name": "Base", "base_cf": 1.0, "growth_rates": [0.05] * 5, "wacc": 0.09, "terminal_g": 0.02}]}
    c0 = {"price": 10.0, "shares_default_b": 1.0}
    r0 = fmt.execute_financial_model(copy.deepcopy(params), dict(c0))
    r1 = fmt.execute_financial_model(copy.deepcopy(params), dict(c0, d2={"family": "operating"}))
    assert r0 == r1        # d2 present but d2_enabled unset: the same result


# ---- 2. measurement -------------------------------------------------------------------------------------------------------------------------

def test_us_gaap_filer_without_leases():
    out = build()
    d2 = out["d2"]
    assert out["d2_unavailable"] is None and d2["family"] == "operating"
    nd = 320.0 - 60.0 - 10.0
    assert d2["delta"] == pytest.approx(nd / (nd + 1000.0))
    assert d2["kd"] == pytest.approx(20.0 / 320.0)
    assert d2["tau"] == pytest.approx(0.2)
    p = d2["pooled"]
    assert p["years"] == 5 and p["revenue"] == sum(1000.0 + 50 * k for k in range(5)) and p["capex"] == 400.0
    assert p["da_org"] == pytest.approx(5 * (70.0 - 5.0))          # D&A less acquired amortization, per year
    assert "lease_principal" not in p and "rou_dep" not in p
    assert "lease_principal_not_filed" in out["d2_provenance"]["stamps"]
    assert d2["valuation_date"] == "2026-10-18"
    # the debt is the one invested_capital counts
    r = rows()["2025"]
    te = tcr.tangible_equity(r)
    assert tcr.invested_capital(r) == pytest.approx(te + D.gross_debt(r)[0] - 60.0 - 10.0)


def test_us_gaap_finance_lessee_and_ifrs_lessee():
    extra = dict(lease_principal=12.0, rou_depreciation=9.0, lease_interest=3.0, finance_lease_liability=50.0)
    out = build(rows(**extra))
    p = out["d2"]["pooled"]
    assert p["lease_principal"] == 60.0 and p["rou_dep"] == 45.0
    assert p["da_org"] == pytest.approx(5 * (70.0 - 9.0 - 5.0))                      # D&A_org = D&A - ROU - amortization, per year
    assert out["d2"]["kd"] == pytest.approx((20.0 - 3.0) / 320.0)                    # lease interest comes out of the interest
    assert out["d2"]["year0"]["lease_principal"] == 12.0 and out["d2"]["year0"]["rou_dep"] == 9.0
    # IFRS: interest_on_borrowings is already without lease interest and is used as filed (no second subtraction)
    out = build(rows(**dict(extra, interest_on_borrowings=15.0)))
    assert out["d2"]["kd"] == pytest.approx(15.0 / 320.0)


def test_net_cash_delta_is_zero_and_zero_is_kept():
    out = build(rows(lt_debt=0.0, debt_lt_noncurrent=0.0, debt_current=0.0, cash=500.0))
    assert out["d2"]["delta"] == 0.0 and "net_cash_delta_zero" in out["d2_provenance"]["stamps"]
    assert "kd" not in out["d2"] and "kd_debt_zero_or_unproven" in out["d2_provenance"]["stamps"]      # zero debt: no kd, never 0.05
    # 0.0 is a value: a filed zero capex, zero lease principal and zero amortization are summed, not dropped
    out = build(rows(capex=0.0, lease_principal=0.0, rou_depreciation=0.0, amortization_intangibles=0.0))
    p = out["d2"]["pooled"]
    assert p["capex"] == 0.0 and p["lease_principal"] == 0.0 and p["rou_dep"] == 0.0 and p["years"] == 5
    assert out["d2"]["year0"]["capex"] == 0.0 and out["d2"]["year0"]["amortization"] == 0.0


def test_no_debt_filed_at_all_is_unproven_not_zero():
    out = build(rows(lt_debt=None, debt_lt_noncurrent=None, debt_current=None))
    assert out["d2"] is None and out["d2_unavailable"] == ["delta"]
    assert "delta_debt_not_filed" in out["d2_provenance"]["stamps"]


def test_currency_mismatch_leaves_delta_absent():
    out = build(statement_currency="IDR")
    assert out["d2"] is None and out["d2_unavailable"] == ["delta"]
    assert "delta_currency_unproven" in out["d2_provenance"]["stamps"]
    assert build(statement_currency=None, quote_currency=None)["d2_unavailable"] == ["delta"]


def test_financial_route_takes_no_delta():
    r = rows(insurance_reserves=600.0)                      # 600 / 1200 of assets
    out = build(r, sic=6331)
    assert out["d2"] == {"family": "financial", "valuation_date": "2026-10-18"}
    assert "delta_not_applied_financial_route" in out["d2_provenance"]["stamps"]
    assert build(sic=6211)["d2"]["family"] == "financial"
    # a credit SIC is financial only when borrowings fund >= 50% of liabilities
    assert build(rows(lt_debt=400.0, debt_lt_noncurrent=400.0), sic=6153)["d2"]["family"] == "financial"
    ops = build(sic=6153)
    assert ops["d2"]["family"] == "operating" and "family_route_unresolved" in ops["d2_provenance"]["stamps"]
    # a name no evaluated test confirms, outside the financial SIC range, is operating without the unresolved stamp
    assert "family_route_unresolved" not in build()["d2_provenance"]["stamps"]
    assert "family_route_unresolved" in build(sic=None)["d2_provenance"]["stamps"]


def test_partial_history_excludes_incomplete_years_by_name():
    rs = rows()
    rs["2022"]["capex"] = None
    del rs["2021"]
    out = build(rs)
    p = out["d2"]["pooled"]
    assert p["years"] == 3 and p["capex"] == 240.0
    st = out["d2_provenance"]["stamps"]
    assert "pooled_year_2021_excluded:no_row" in st and "pooled_year_2022_excluded:capex" in st
    # an optional component filed elsewhere in the window and missing in a year excludes that year from every sum
    rs = rows(rou_depreciation=4.0)
    rs["2023"]["rou_depreciation"] = None
    out = build(rs)
    assert out["d2"]["pooled"]["years"] == 4 and "pooled_year_2023_excluded:rou_depreciation" in out["d2_provenance"]["stamps"]
    # no complete year: pooled is a named unavailable member
    rs = rows(capex=None)
    out = build(rs)
    assert out["d2"] is None and "pooled" in out["d2_unavailable"]


def test_schedule_versus_a0_fallback_and_ppe():
    full = {f"amortization_sched_y{i}": 5.0 - i * 0.5 for i in range(1, 6)}
    r = rows()
    r["2025"].update(full, amortization_sched_thereafter=2.0, ppe_gross=900.0, ppe_net=600.0)
    r["2024"]["ppe_gross"] = 850.0
    out = build(r)
    am = out["d2"]["amortization"]
    assert am == {"schedule": [4.5, 4.0, 3.5, 3.0, 2.5], "thereafter": 2.0}
    assert out["d2"]["ppe"] == {"gross_prior": 850.0, "gross": 900.0, "net": 600.0, "da_org_0": 65.0}
    # thereafter null: absent and stamped
    r["2025"]["amortization_sched_thereafter"] = None
    out = build(r)
    assert out["d2"]["amortization"] == {"schedule": [4.5, 4.0, 3.5, 3.0, 2.5]}
    assert "amortization_thereafter_not_filed" in out["d2_provenance"]["stamps"]
    # a partial schedule falls back to A_0 and says so; no schedule at all, the same; 0.0 A_0 is a value
    r["2025"]["amortization_sched_y5"] = None
    out = build(r)
    assert out["d2"]["amortization"] == {"a0": 5.0}
    assert any(s.startswith("amortization_schedule_partial") for s in out["d2_provenance"]["stamps"])
    out = build(rows(amortization_intangibles=0.0))
    assert out["d2"]["amortization"] == {"a0": 0.0} and "ppe" not in out["d2"] and "ppe_gross_not_filed" in out["d2_provenance"]["stamps"]
    out = build(rows(amortization_intangibles=None))
    assert "amortization" not in out["d2"]


def test_year0_levels_are_scaled_by_pi_and_nwc_comes_from_the_record():
    out = build(pi=0.5)
    y0 = out["d2"]["year0"]
    assert y0["capex"] == 40.0 and y0["da_org"] == pytest.approx(32.5)
    nwc = tcr.net_working_capital(rows()["2025"])
    assert y0["dnwc"] == pytest.approx(0.5 * (nwc - tcr.net_working_capital(rows()["2024"])))
    assert y0["invested_capital"] == pytest.approx(0.5 * tcr.invested_capital(rows()["2025"]))
    assert out["d2"]["pooled"]["capex"] == 400.0          # the pooled totals stay raw


def test_tau_default_is_stamped():
    out = build(rows(pretax_income=None))
    assert out["d2"]["tau"] == 0.21 and "tax_rate_default_21pct" in out["d2_provenance"]["stamps"]


# ---- 3. L3 -------------------------------------------------------------------------------------------------------------------------------

def test_r_tc_after_lease_interest():
    hist = {y: row(y, interest_expense=30.0, lease_interest=10.0) for y in range(2014, 2026)}
    rec = tcr.analyse(hist, 0.08, base_year=2025)
    plain = tcr.analyse({y: {k: v for k, v in r.items() if k != "lease_interest"} for y, r in hist.items()}, 0.08, base_year=2025)
    assert rec["R_tc"] == plain["R_tc"]                                           # r_tc is untouched
    assert rec["R_tc_after_lease_interest"] < rec["R_tc"]                         # the lease interest stays deducted
    assert plain["R_tc_after_lease_interest"] == plain["R_tc"]                   # nothing filed: the same number
    x = tcr.adjusted_earnings(hist[2025])
    assert tcr.return_numerator_after_lease_interest(hist[2025]) == pytest.approx(x + 20.0 * (1 - tcr.tax_rate(hist[2025])))
    assert tcr.non_lease_interest({"interest_expense": 5.0, "interest_on_borrowings": 0.0}) == (0.0, "interest_on_borrowings")


def test_desk_uses_the_after_lease_ronic_start_only_when_enabled():
    import financial_model_tool as fmt
    calls = []
    real = fmt.unbundled_dcf

    def spy(**kw):
        calls.append(kw)
        return real(**kw)
    fmt.unbundled_dcf = spy
    try:
        params = {"scenarios": [{"name": "Base", "base_cf": 1.0, "growth_rates": [0.05] * 5, "wacc": 0.09, "terminal_g": 0.02}]}
        ctx = {"price": 10.0, "shares_default_b": 1.0, "d2": {"family": "operating"}, "long_run": {"r_tc": 0.12, "r_tc_after_lease_interest": 0.1}}
        fmt.execute_financial_model(copy.deepcopy(params), dict(ctx))
        assert all("d2" not in c and c["long_run"]["r_tc"] == 0.12 for c in calls)
        calls.clear()
        fmt.execute_financial_model(copy.deepcopy(params), dict(ctx, d2_enabled=True))
        # no bridge in this call: d2 is not forwarded (it needs the bridge), and the start is today's
        assert all("d2" not in c and c["long_run"]["r_tc"] == 0.12 for c in calls)
    finally:
        fmt.unbundled_dcf = real


# ---- the model-visible text does not change when the screener's eleven new keys arrive ---------------------------------------------------------

NEW_KEYS = ("da_d2", "revenue_d2", "lease_principal", "lease_interest", "rou_depreciation", "interest_on_borrowings", "ppe_gross", "amortization_sched_y1",
            "amortization_sched_y2", "amortization_sched_y3", "amortization_sched_y4", "amortization_sched_y5", "amortization_sched_thereafter",
            "capex_d2", "debt_d2_total")      # the last two: D2b3 (BRIEF_D2b3_coverage.md, Part R)


def test_the_eleven_new_keys_are_reviewed_and_the_pack_text_is_byte_identical(monkeypatch):
    import capability_test as cap
    import rs2_data
    assert set(NEW_KEYS) <= cap.REVIEWED_HISTORY_KEYS
    real = rs2_data.load_json
    hist = real(cap.SD / "fundamentals_history.json")
    if not hist or "BUD" not in (hist.get("tickers") or {}):
        pytest.skip("no stored fundamentals history for BUD")
    with_keys = copy.deepcopy(hist)
    for y, r in with_keys["tickers"]["BUD"].items():
        if isinstance(r, dict):
            r.update({k: 1.5e9 for k in NEW_KEYS})

    def build(doc):
        monkeypatch.setattr(rs2_data, "load_json", lambda p, *a, **k: doc if str(p).endswith("fundamentals_history.json") else real(p, *a, **k))
        return str(cap.build_pack("BUD", price_override=60.0, include_research=False))

    assert build(hist) == build(with_keys)


def test_levels_are_in_billions_by_default_ratios_unchanged():
    big = {y: {k: (v * 1e9 if isinstance(v, float) and k not in ("pretax_income",) else v) for k, v in r.items()} for y, r in rows().items()}
    for r in big.values():
        r["pretax_income"], r["tax_provision"] = 130.0e9, 26.0e9
    out = D.build(big, 2025, sic=3571, sector="Technology", price=10.0, shares=100.0, statement_currency="USD",
                  quote_currency="USD", valuation_date="2026-10-18", pi=1.0)
    ref = build()
    assert out["d2"]["pooled"]["capex"] == pytest.approx(ref["d2"]["pooled"]["capex"])      # 400e9 / 1e9 = 400
    assert out["d2"]["year0"]["capex"] == pytest.approx(80.0)


def test_d2_enabled_with_a_bridge_forwards_d2_and_starts_ronic_at_the_after_lease_return():
    import financial_model_tool as fmt
    from test_rev25_bridge import _call, _ctx, _run, _dcf
    d2 = build(unit=1.0)["d2"]
    d2 = dict(d2, year0={}, delta=0.0, kd=0.05)
    lr = dict(_ctx()["long_run"], r_tc=0.12, r_tc_after_lease_interest=0.10)
    base = _run(_call(), _ctx(long_run=lr, d2=d2))
    on = _run(_call(), _ctx(long_run=lr, d2=d2, d2_enabled=True))
    assert "d2" not in _dcf(base, "base")                                              # unset: the legacy desk, no d2 diagnostics
    dd = _dcf(on, "base")
    assert "desk_d2_terminal_reinvestment" in dd["stamps"] and dd["d2"]["roic_n1_roll_forward"]["r_tc"] == pytest.approx(0.10)
    on2 = _run(_call(), _ctx(long_run=dict(lr, r_tc_after_lease_interest=None), d2=d2, d2_enabled=True))
    assert _dcf(on2, "base")["d2"]["roic_n1_roll_forward"]["r_tc"] == pytest.approx(0.12)       # absent: today's r_tc


# ---- D2b3 Part R: coverage rules (kd source, capex_d2, debt_d2_total, the debt-free rule) ---------------------------------------------------

def fp(field, tag, state="primary", years=range(2021, 2026)):
    return {field: {y: {"tag": tag, "state": state} for y in years}}


def test_kd_prefers_interest_on_borrowings_and_never_subtracts_lease_interest_from_an_ifrs_rung():
    rs = rows(interest_on_borrowings=15.0, lease_interest=4.0)
    out = build(rs, field_prov=fp("interest_on_borrowings", "InterestExpenseOnBorrowings"))
    assert out["d2"]["kd"] == pytest.approx(15.0 / 320.0)
    assert out["d2_provenance"]["members"]["kd"]["source"].startswith("interest_on_borrowings:InterestExpenseOnBorrowings /")
    comp = build(rs, field_prov=fp("interest_on_borrowings", "InterestExpenseOnBonds+InterestExpenseOnBankLoansAndOverdrafts", "component_sum"))
    assert comp["d2"]["kd"] == pytest.approx(15.0 / 320.0)


def test_kd_subtracts_lease_interest_on_the_nonoperating_rung_and_on_interest_expense():
    rs = rows(interest_on_borrowings=15.0, lease_interest=4.0)
    out = build(rs, field_prov=fp("interest_on_borrowings", "InterestExpenseNonoperating"))
    assert out["d2"]["kd"] == pytest.approx(11.0 / 320.0)
    assert "less_lease_interest" in out["d2_provenance"]["members"]["kd"]["source"]
    ie = build(rows(lease_interest=4.0))
    assert ie["d2"]["kd"] == pytest.approx(16.0 / 320.0)
    # a filed 0.0 interest_on_borrowings is a value: interest_expense does not replace it (IFRS rung: nothing subtracted)
    z = build(rows(interest_on_borrowings=0.0, lease_interest=4.0), field_prov=fp("interest_on_borrowings", "InterestExpenseOnBorrowings"))
    assert z["d2"] is None and z["d2_provenance"]["kd_outside_plausible_range"]["kd"] == 0.0     # used as 0.0 (not replaced), then out of range
    assert "interest_on_borrowings:InterestExpenseOnBorrowings" in z["d2_provenance"]["members"]["kd"]["source"]
    unk = build(rs)
    assert unk["d2"]["kd"] == pytest.approx(15.0 / 320.0) and "interest_on_borrowings_tag_unknown" in unk["d2_provenance"]["members"]["kd"]["stamps"]


def test_capex_d2_fills_pooled_and_year0_only_when_capex_is_null_and_carries_its_class():
    rs = rows(capex=None, capex_d2=-90.0)
    out = build(rs, field_prov=fp("capex_d2", "PaymentsForProceedsFromProductiveAssets"))
    assert out["d2"]["pooled"]["years"] == 5 and out["d2"]["pooled"]["capex"] == pytest.approx(450.0)
    assert out["d2"]["year0"]["capex"] == pytest.approx(90.0)
    pv = out["d2_provenance"]
    assert pv["capex_d2"]["2025"]["classes"] == ["net_of_proceeds"]
    assert "capex_from_d2_year_2023:net_of_proceeds" in pv["members"]["pooled"]["stamps"]
    assert "capex_from_d2:net_of_proceeds" in pv["members"]["year0"]["stamps"]
    both = build(rows(capex=80.0, capex_d2=999.0))                    # capex filed: capex wins, capex_d2 never read
    assert both["d2"]["pooled"]["capex"] == pytest.approx(400.0) and "capex_d2" not in both["d2_provenance"]
    z = build(rows(capex=0.0, capex_d2=999.0))                        # capex 0.0 is a value
    assert z["d2"]["pooled"]["capex"] == 0.0
    none = build(rows(capex=None))                                    # neither: the years are excluded by name, as before
    assert "pooled" in (none["d2_unavailable"] or [])


def test_capex_d2_class_markers():
    c = D.capex_class
    assert c({"tag": "x", "state": "from_capex"}) == ["from_capex"]
    assert c({"tag": "PaymentsToAcquireRealEstate+PaymentsToAcquireLand", "state": "component_sum"}) == ["component_sum", "real_estate_components"]
    assert c({"tag": "PaymentsForConstructionInProcess", "state": "primary"}) == ["construction_in_process"]
    assert c({"tag": "PaymentsToAcquireOtherPropertyPlantAndEquipment", "state": "primary"}) == ["other_ppe_partial_risk"]
    assert c({"tag": "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
              "state": "primary"}) == ["includes_intangibles"]
    assert c(None) == []


NO_LADDER = dict(lt_debt=None, debt_lt_noncurrent=None, debt_current=None)


def test_debt_d2_total_replaces_an_absent_ladder_and_year0_invested_capital_uses_the_same_debt():
    rs = rows(**NO_LADDER, debt_d2_total=250.0)
    out = build(rs)
    pv = out["d2_provenance"]["members"]
    nd = 250.0 - 60.0 - 10.0
    assert out["d2"]["delta"] == pytest.approx(nd / (nd + 1000.0))
    assert out["d2"]["kd"] == pytest.approx(20.0 / 250.0)
    for m in ("delta", "kd", "year0"):
        assert "debt_from_d2_total" in pv[m]["stamps"]
    base = tcr.invested_capital(tcr.normalise_rows(rs)[2025])         # the record's own invested capital is untouched (ladder counted 0)
    assert out["d2"]["year0"]["invested_capital"] == pytest.approx(base + 250.0)


def test_the_ladder_wins_when_it_resolves_and_debt_d2_total_is_ignored():
    out = build(rows(debt_d2_total=9999.0))
    assert out["d2"]["kd"] == pytest.approx(20.0 / 320.0)
    assert "debt_from_d2_total" not in out["d2_provenance"]["stamps"]


def test_short_term_filed_without_long_term_uses_the_total_without_double_counting():
    rs = rows(lt_debt=None, debt_lt_noncurrent=None, debt_current=20.0, debt_d2_total=250.0)
    out = build(rs)
    base = tcr.invested_capital(tcr.normalise_rows(rs)[2025])         # counted the 20 of short-term debt
    assert out["d2"]["year0"]["invested_capital"] == pytest.approx(base + 250.0 - 20.0)


def test_debt_free_rule_zero_only_with_the_vendor_test():
    rs = rows(**NO_LADDER, finance_lease_liability=40.0, operating_lease_liability=60.0)
    for vendor, ok in ((0.0, True), (100.0, True), (110.0, True), (111.0, False), (5000.0, False), (None, False)):
        out = build(rs, vendor_total_debt=vendor)
        if ok:
            st = out["d2_provenance"]["members"]["delta"]["stamps"]
            assert out["d2"]["delta"] == 0.0 and "debt_zero_inferred_leases_only" in st and "delta_debt_not_filed" not in st, vendor
            assert "debt_zero_inferred_leases_only" in out["d2_provenance"]["members"]["kd"]["stamps"]
            assert out["d2"]["year0"]["invested_capital"] == pytest.approx(tcr.invested_capital(tcr.normalise_rows(rs)[2025]))
        else:
            assert "delta_debt_not_filed" in out["d2_provenance"]["members"]["delta"]["stamps"], vendor
            assert "debt_zero_inferred_leases_only" not in out["d2_provenance"]["stamps"] and "delta" in out["d2_unavailable"], vendor
    nl = rows(**NO_LADDER)                                            # no filed leases: only a vendor Total_Debt of 0 passes
    assert build(nl, vendor_total_debt=0.0)["d2"]["delta"] == 0.0
    assert build(nl, vendor_total_debt=1.0)["d2"] is None


def test_debt_free_rule_needs_every_window_year_clean_and_a_proven_currency():
    rs = rows(**NO_LADDER)
    rs["2023"]["debt_current"] = 5.0                                  # one window year files a debt tag
    assert "debt_zero_inferred_leases_only" not in build(rs, vendor_total_debt=0.0)["d2_provenance"]["stamps"]
    rs = rows(**NO_LADDER)
    rs["2022"]["debt_d2_total"] = 5.0                                 # debt_d2_total filed in an earlier year: not debt-free
    assert "debt_zero_inferred_leases_only" not in build(rs, vendor_total_debt=0.0)["d2_provenance"]["stamps"]
    cur = build(rows(**NO_LADDER), vendor_total_debt=0.0, statement_currency="EUR")
    assert "debt_zero_inferred_leases_only" not in cur["d2_provenance"]["stamps"]


# ---- coordinator additions: vendor agreement of rung-sourced values, and the kd plausible range -----------------------------------------

def test_capex_d2_rung_is_verified_against_the_vendor():
    rs = rows(capex=None, capex_d2=90.0)
    cls = fp("capex_d2", "PaymentsToAcquireOilAndGasPropertyAndEquipment")
    ok = build(rs, field_prov=cls, vendor_capex=-100.0)
    assert ok["d2"]["pooled"]["capex"] == pytest.approx(450.0) and "capex_d2_rung_vendor_agrees" in ok["d2_provenance"]["members"]["pooled"]["stamps"]
    for bad in (-300.0, -50.0):                                           # ratios 0.30 and 1.80
        out = build(rs, field_prov=cls, vendor_capex=bad)
        assert "capex_d2_vendor_disagrees" in out["d2_provenance"]["members"]["pooled"]["stamps"]
        assert out["d2"] is None and "pooled" in out["d2_unavailable"]
        assert out["d2_provenance"]["capex_d2_vendor"]["ratio"] == pytest.approx(90.0 / abs(bad))
    un = build(rs, field_prov=cls)
    assert "capex_d2_rung_unverified" in un["d2_provenance"]["members"]["pooled"]["stamps"] and un["d2"]["pooled"]["years"] == 5
    fc = build(rows(capex=None, capex_d2=90.0), field_prov=fp("capex_d2", "x", "from_capex"), vendor_capex=-1000.0)   # from_capex: not checked
    assert fc["d2"]["pooled"]["years"] == 5 and "capex_d2_vendor_disagrees" not in fc["d2_provenance"]["stamps"]


def test_debt_d2_total_rung_is_verified_against_the_vendor_less_leases():
    rs = rows(**NO_LADDER, debt_d2_total=250.0, finance_lease_liability=20.0, operating_lease_liability=30.0)
    d2 = fp("debt_d2_total", "DebtInstrumentCarryingAmount")
    ok = build(rs, field_prov=d2, vendor_total_debt=300.0)               # 250 / (300 - 50) = 1.0
    assert ok["d2"]["delta"] > 0 and "debt_d2_total_rung_vendor_agrees" in ok["d2_provenance"]["members"]["delta"]["stamps"]
    for vendor in (1000.0, 60.0):                                         # ratios 0.26 and 25
        out = build(rs, field_prov=d2, vendor_total_debt=vendor)
        assert "debt_d2_vendor_disagrees" in out["d2_provenance"]["members"]["delta"]["stamps"] and "delta" in out["d2_unavailable"]
        assert out["d2_provenance"]["debt_d2_vendor_ratio"] == pytest.approx(250.0 / (vendor - 50.0))
    un = build(rs, field_prov=d2)
    assert "debt_d2_total_rung_unverified" in un["d2_provenance"]["members"]["delta"]["stamps"] and un["d2"]["delta"] > 0
    lad = build(rs, field_prov=fp("debt_d2_total", "x", "from_ladder"), vendor_total_debt=1000.0)
    assert not any("vendor" in x for x in lad["d2_provenance"]["members"]["delta"]["stamps"]) and lad["d2"]["delta"] > 0


def test_kd_outside_the_plausible_range_is_unavailable_with_the_value_kept():
    for interest in (2.0, 90.0):                                          # kd 0.00625 and 0.28 on 320 of debt
        out = build(rows(interest_expense=interest))
        assert out["d2"] is None and "kd" in out["d2_unavailable"]
        assert out["d2_provenance"]["kd_outside_plausible_range"]["kd"] == pytest.approx(interest / 320.0)
        assert "kd_outside_plausible_range" in out["d2_provenance"]["members"]["kd"]["stamps"]
    edge = build(rows(interest_expense=3.2))                              # exactly 0.01 is inside
    assert edge["d2"]["kd"] == pytest.approx(0.01)


# ---- D2b4 Part R: da_d2 and revenue_d2 (BRIEF_D2b4_da_revenue.md) ----------------------------------------------------------------------------

def test_da_and_revenue_d2_keys_are_reviewed():
    import capability_test as cap
    assert {"da_d2", "revenue_d2"} <= cap.REVIEWED_HISTORY_KEYS


def test_da_d2_markers_by_state_and_by_tag():
    c = D.da_class
    assert c({"tag": "x", "state": "from_da"}) == []
    assert c({"tag": "x", "state": "cogs_da"}) == ["cogs_da"]
    assert c({"tag": "ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion", "state": "rung"}) == ["includes_accretion"]
    assert c({"tag": "DepreciationNonproduction", "state": "rung"}) == ["da_lone_depreciation"]
    assert c({"tag": "Weird", "state": "rung"}) == ["rung_unclassified"]
    assert D.revenue_class({"tag": "RevenueFromRenderingOfTransportServices", "state": "rung"}) == ["transport_services_revenue"]
    assert D.revenue_class({"tag": "Revenues", "state": "from_revenue"}) == []


def test_da_d2_fills_pooled_and_year0_only_when_da_is_null_and_keeps_the_da_org_arithmetic():
    rs = rows(da=None, da_d2=70.0, rou_depreciation=10.0, lease_principal=5.0)
    out = build(rs, field_prov=fp("da_d2", "CostOfGoodsAndServicesSoldDepreciationAndAmortization", "cogs_da"), vendor_da=75.0)
    pv = out["d2_provenance"]
    assert out["d2"]["pooled"]["years"] == 5 and out["d2"]["pooled"]["da_org"] == pytest.approx(5 * (70.0 - 10.0 - 5.0))
    assert out["d2"]["year0"]["da_org"] == pytest.approx(55.0)
    assert pv["da_d2"]["2025"]["classes"] == ["cogs_da"]
    assert "da_from_d2_year_2023:cogs_da" in pv["members"]["pooled"]["stamps"] and "da_from_d2:cogs_da" in pv["members"]["year0"]["stamps"]
    assert "da_d2_rung_vendor_agrees" in pv["members"]["pooled"]["stamps"] and "da_d2_rung_vendor_agrees" in pv["members"]["year0"]["stamps"]
    both = build(rows(da=70.0, da_d2=999.0))                      # da filed: da wins, da_d2 never read
    assert both["d2"]["pooled"]["da_org"] == pytest.approx(5 * 65.0) and "da_d2" not in both["d2_provenance"]
    z = build(rows(da=0.0, da_d2=999.0))                          # 0.0 is a value
    assert z["d2"]["pooled"]["da_org"] == pytest.approx(5 * -5.0)
    none = build(rows(da=None))
    assert "pooled" in (none["d2_unavailable"] or [])


def test_da_d2_lone_depreciation_subtracts_no_amortization():
    rs = rows(da=None, da_d2=70.0, amortization_intangibles=None)
    out = build(rs, field_prov=fp("da_d2", "Depreciation", "da_lone_depreciation"), vendor_da=70.0)
    assert out["d2"]["pooled"]["da_org"] == pytest.approx(350.0)
    assert "da_from_d2_year_2025:da_lone_depreciation" in out["d2_provenance"]["members"]["pooled"]["stamps"]


def test_da_d2_rung_is_verified_against_the_vendor():
    rs = rows(da=None, da_d2=70.0)
    cls = fp("da_d2", "ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion", "includes_accretion")
    for bad in (30.0, 200.0):                                      # ratios 2.33 and 0.35
        out = build(rs, field_prov=cls, vendor_da=bad)
        assert "da_d2_vendor_disagrees" in out["d2_provenance"]["members"]["pooled"]["stamps"]
        assert out["d2"] is None and "pooled" in out["d2_unavailable"]
    for vd in (None, 0.0):                                         # the absent-vendor stamp
        un = build(rs, field_prov=cls, vendor_da=vd)
        assert "da_d2_rung_unverified" in un["d2_provenance"]["members"]["pooled"]["stamps"] and un["d2"]["pooled"]["years"] == 5
    fd = build(rs, field_prov=fp("da_d2", "x", "from_da"), vendor_da=1.0)         # from_da: not checked
    assert fd["d2"]["pooled"]["years"] == 5 and "da_d2_vendor_disagrees" not in fd["d2_provenance"]["stamps"]


def test_revenue_d2_fills_pooled_revenue_and_is_checked_per_year_against_the_vendor():
    rs = rows(revenue=None, revenue_d2=1000.0)
    cls = fp("revenue_d2", "RevenueFromRenderingOfTransportServices", "transport_services_revenue")
    vend = {y: 1000.0 for y in range(2021, 2026)}
    out = build(rs, field_prov=cls, vendor_revenue=vend)
    pv = out["d2_provenance"]
    assert out["d2"]["pooled"]["revenue"] == pytest.approx(5000.0) and out["d2"]["pooled"]["years"] == 5
    assert pv["revenue_d2"]["2024"]["classes"] == ["transport_services_revenue"]
    assert "revenue_from_d2_year_2024:transport_services_revenue" in pv["members"]["pooled"]["stamps"]
    assert "revenue_d2_rung_vendor_agrees" in pv["members"]["pooled"]["stamps"]
    part = build(rs, field_prov=cls, vendor_revenue={2025: 1000.0})                # the vendor holds one year only
    assert "revenue_d2_rung_unverified" in part["d2_provenance"]["members"]["pooled"]["stamps"] and part["d2"]["pooled"]["years"] == 5
    assert "revenue_d2_rung_unverified" in build(rs, field_prov=cls)["d2_provenance"]["members"]["pooled"]["stamps"]
    bad = build(rs, field_prov=cls, vendor_revenue={**vend, 2023: 3000.0})
    assert "revenue_d2_vendor_disagrees" in bad["d2_provenance"]["members"]["pooled"]["stamps"] and bad["d2"] is None
    plain = build(rows(revenue_d2=1.0), vendor_revenue={2025: 9e9})               # revenue filed: revenue_d2 never read, never checked
    assert plain["d2"]["pooled"]["revenue"] == pytest.approx(5500.0) and "revenue_d2" not in plain["d2_provenance"]
    z = build(rows(revenue=0.0, revenue_d2=500.0))                                # 0.0 is a value
    assert z["d2"]["pooled"]["revenue"] == 0.0


def test_vendor_revenue_by_year_matches_on_the_period_end_and_refuses_unconverted_fx():
    import capability_test as cap
    fin = {"Annual_Income_Statement": [{"Date": "2025-03-31", "TotalRevenue": 7.0}, {"Date": "2024-03-30", "TotalRevenue": 6.0}]}
    pe = {"2025": "2025-03-31", "2024": "2024-03-31", "2023": "2023-03-31"}
    assert cap._vendor_revenue_by_year(fin, pe, [2023, 2024, 2025]) == {2025: 7.0, 2024: 6.0}
    assert cap._vendor_revenue_by_year(dict(fin, FX={"converted": False, "flag": "INR"}), pe, [2025]) == {}

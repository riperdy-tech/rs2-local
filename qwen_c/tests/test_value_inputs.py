"""CROSS_CHECK_Q_RULINGS batch C: qwen_c/value/inputs.py (m3q.inputs.v2) on hand-built facts."""
import pytest

from qwen_c.value import desk, inputs

ENDS = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
BILL = 0.04


def series(vals, tag="T", ends=ENDS):
    return {"values": [{"end": e, "value": v, "tag": tag, "form": "10-K"} for e, v in zip(ends[-len(vals):], vals)]}


def facts(**over):
    f = {"revenue": series([80, 85, 90, 95, 100]), "operating_income": series([12, 13, 14, 15, 16]),
         "net_income": series([8, 8.8, 9.6, 10, 10.4]), "pretax_income": series([10, 11, 12, 12.5, 13]),
         "tax_provision": series([2, 2.2, 2.4, 2.5, 2.6]), "da": series([4, 4.2, 4.5, 4.7, 5]), "capex": series([5, 5, 5.5, 6, 6]),
         "amortization": series([1, 1, 1, 1, 1]), "interest_expense": series([1, 1, 1, 1, 1]), "diluted_shares": series([10, 10, 10, 10, 10]),
         "eps_diluted": series([0.8, 0.88, 0.96, 1.0, 1.04]),
         "assets_current": series([30, 30, 30, 30, 32]), "liabilities_current": series([20, 20, 20, 20, 21]), "cash": series([5, 5, 5, 6, 7]),
         "debt_current": series([1, 1, 1, 1, 1], tag="LongTermDebtCurrent"), "debt_noncurrent": series([19, 19, 19, 19, 19]),
         "equity": series([40, 41, 42, 44, 46]), "goodwill": series([4, 4, 4, 4, 4]),
         "amort_next_1": series([1.0]), "amort_next_2": series([1.0]), "amort_next_3": series([0.8]), "amort_next_4": series([0.5]),
         "amort_next_5": series([0.5]), "amort_after_5": series([2.0]), "_absent": {}, "_stale": {}, "_latest_annual_period": "2025-12-31"}
    f.update(over)
    return f


def base(f=None, **kw):
    return inputs.base(f or facts(), market_cap=kw.get("mcap", 180.0), bill_rate=kw.get("bill", BILL))


# ---- the earnings base (rulings 6, 9, 19) ------------------------------------------------------------------------------------------

def test_x0_k0_from_pretax_and_the_bridge_returns_x0():
    b = base()
    tau = 2.6 / 13
    pt_ex = 13 - 7 * BILL                                             # cash 7 at the bill rate; no NCI filed
    assert b["tau"] == pytest.approx(tau)
    assert b["x0"] == pytest.approx((pt_ex + 1) * (1 - tau))
    assert b["k0"] == pytest.approx(16 - pt_ex)                          # non-operating items only (the v1.3 fix)
    assert inputs.bridge_x_margin(b, [0.16], [100.0], [1.0])[0] == pytest.approx(b["m0"])
    assert b["excess_cash"] == 7 and "nci_not_filed" in b["stamps"]


def test_cash_counted_once():
    # $100 more cash adds $100 / shares at face and removes its interest from X_0: never both
    b0, b1 = base(), base(facts(cash=series([5, 5, 5, 6, 107])))
    assert b1["excess_cash"] - b0["excess_cash"] == 100
    assert b0["x0"] - b1["x0"] == pytest.approx(100 * BILL * (1 - b0["tau"]))


def test_no_bill_rate_means_no_cash_added():
    b = base(bill=None)
    assert b["excess_cash"] == 0.0 and b["cash_interest_pretax"] == 0.0 and "cash_term_not_available_no_bill_rate" in b["stamps"]


def test_a_tax_anomaly_in_fy0_does_not_enter_the_base():
    b = base(facts(tax_provision=series([2, 2.2, 2.4, 2.5, 6.0]), net_income=series([8, 8.8, 9.6, 10, 7.0]),   # FY0 46%
                   eps_diluted=series([0.8, 0.88, 0.96, 1.0, 0.7])))
    tau = sorted([0.2, 0.2, 0.2, 0.2])[1]
    assert b["tau"] == pytest.approx(tau) and "tax_rate_multi_year_median" in b["stamps"]
    assert b["x0"] == pytest.approx((13 - 7 * BILL + 1) * (1 - tau))           # from pretax: NI's anomaly is not capitalised


def test_latest_in_band_rate_far_from_the_median_takes_the_median():
    b = base(facts(tax_provision=series([2.4, 2.6, 2.9, 3.0, 0.3])))           # 24%, 24%, 24%, 24%, then 2.3%
    assert "tax_rate_multi_year_median" in b["stamps"] and b["tau"] == pytest.approx(0.24, abs=0.005)


def test_amortization_basis_must_hold_in_every_pooled_year():
    f = facts(amortization={"values": [{"end": e, "value": 1, "tag": "T"} for e in ENDS[2:]]})
    b = base(f)
    assert b["amort_schedule"] == [0.0] * 5 and "amortization_basis_not_filed_every_year" in b["stamps"]
    assert b["x0"] == pytest.approx((13 - 7 * BILL) * (1 - b["tau"]))


def test_depreciation_only_tag_is_not_reduced_by_amortization():
    b = base(facts(da=series([3, 3.2, 3.5, 3.7, 4], tag="Depreciation")))
    assert b["d_ratio"] == pytest.approx(sum([3, 3.2, 3.5, 3.7, 4]) / 450)


# ---- debt, kd, delta (rulings 5, 27) -----------------------------------------------------------------------------------------------

def test_debt_components_and_kd():
    b = base()
    assert b["debt0"] == 20 and b["kd"] == pytest.approx(1 / 20)
    assert b["delta"] == pytest.approx(13 / (13 + 46)) and b["delta_market"] == pytest.approx(13 / 193)   # B12 book ratio; N10 net of cash
    assert "leverage_book_ratio_assumed" in b["stamps"]


def test_a_total_tag_is_not_added_to_current_debt():
    f = facts(debt_total=series([20, 20, 20, 20, 20], tag="DebtAndCapitalLeaseObligations"))
    assert base(f)["debt0"] == 20


def test_long_term_debt_total_adds_short_term_borrowings():
    f = facts(debt_total=series([20, 20, 20, 20, 20], tag="LongTermDebt"), debt_short=series([2, 2, 2, 2, 2]))
    assert base(f)["debt0"] == 22


def test_interest_without_any_debt_tag_is_refused_never_zero():
    f = facts()
    del f["debt_current"], f["debt_noncurrent"]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == "debt_unavailable"


def test_no_debt_and_no_interest_is_a_stamped_zero():
    f = facts()
    del f["debt_current"], f["debt_noncurrent"], f["interest_expense"]
    b = base(f)
    assert b["debt0"] == 0 and b["delta"] == 0 and b["kd"] == 0 and "no_debt_filed" in b["stamps"]


@pytest.mark.parametrize("over,code", [
    ({"interest_expense": series([1, 1, 1, 1])}, "debt_without_interest"),            # no interest for FY0
    ({"interest_expense": series([1, 1, 1, 1, 8])}, "kd_out_of_band"),               # 40%
    ({"interest_expense": series([1, 1, 1, 1, 0.1])}, "kd_out_of_band"),             # 0.5%
])
def test_kd_rules(over, code):
    f = facts(**over)
    if code == "debt_without_interest":
        f["interest_expense"]["values"] = [v for v in f["interest_expense"]["values"] if v["end"] != ENDS[-1]]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == code


# ---- returns, shares, staleness (rulings 5, 8, 21) ---------------------------------------------------------------------------------

def test_ronic0_on_tangible_capital_and_capped():
    b = base()
    tangible = 44 + 20 - 6 - 4
    assert b["ronic0"] == pytest.approx((b["x0"] + 1 * (1 - b["tau"])) / tangible)
    b = base(facts(goodwill=series([60, 60, 60, 60, 60])))                       # tangible capital negative
    assert b["ronic0"] == 1.0 and "tangible_capital_not_positive_ronic0_capped" in b["stamps"]


def test_share_scale_is_reconciled_to_eps():
    with pytest.raises(desk.DeskRefusal) as e:
        base(facts(diluted_shares=series([0.01, 0.01, 0.01, 0.01, 0.01])))
    assert e.value.code == "shares_scale_unverified"
    f = facts()
    del f["eps_diluted"]
    assert "shares_unreconciled_no_eps" in base(f)["stamps"]


def test_base_year_older_than_the_newest_annual_report_is_refused():
    with pytest.raises(desk.DeskRefusal) as e:
        base(facts(_latest_annual_period="2026-12-31"))
    assert e.value.code == "base_year_not_latest_annual"


@pytest.mark.parametrize("over,code", [
    ({"_stale": {"net_income": "2013-12-31"}}, "facts_stale"),
    ({"pretax_income": series([-8, -8, -9, -9, -12]), "tax_provision": series([0, 0, 0, 0, 0])}, "tax_unavailable"),
    ({"revenue": series([95, 100])}, "history_short"),
    ({"diluted_shares": {"values": [{"end": e, "value": 10, "tag": "T"} for e in ENDS[:-1]]}}, "shares_unavailable"),
    ({"operating_income": series([12, 13, 14, 15])}, "bridge_unavailable"),
])
def test_refusals_by_name(over, code):
    f = facts(**over)
    if code == "bridge_unavailable":
        f["operating_income"]["values"] = [v for v in f["operating_income"]["values"] if v["end"] != ENDS[-1]]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == code


def test_market_cap_required():
    with pytest.raises(desk.DeskRefusal) as e:
        base(mcap=None)
    assert e.value.code == "market_cap_unavailable"


# ---- tax rule (V8) -------------------------------------------------------------------------------------------------------------------

def test_zero_tax_is_a_measured_value():
    b = base(facts(tax_provision=series([0, 0, 0, 0, 0.0])))
    assert b["tau"] == 0.0


def test_persistent_high_rate_is_used_and_an_erratic_one_refused():
    import statistics
    b = base(facts(tax_provision=series([4.0, 4.4, 4.9, 5.0, 5.3])))       # 40-41%
    assert "tax_rate_persistent_outside_band" in b["stamps"]
    assert b["tau"] == pytest.approx(statistics.median([0.4, 0.4, 4.9 / 12, 0.4, 5.3 / 13]))
    with pytest.raises(desk.DeskRefusal) as e:
        base(facts(tax_provision=series([4.0, 6.0, 4.9, 7.0, 5.3])))
    assert e.value.code == "tax_unavailable"


# ---- financial route base ---------------------------------------------------------------------------------------------------------

def test_financial_base_uses_book_equity_and_the_identity_holds():
    b = inputs.base_financial(facts())
    roe = 10.4 / 44
    assert b["roe0"] == pytest.approx(roe) and (b["R0"], b["R1"]) == (44, 46)
    g = 0.05
    R = [b["R0"], b["R1"]] + [b["R1"] * (1 + g) ** t for t in range(1, 5)]
    v = desk.value_financial({"revenue": R, "margin": [roe] * 5, "r": 0.10, "g_T": 0.03, "F": 10, "ronic0": roe, "ronic_T": roe,
                              "m_long": roe, "shares": b["shares"], "excess_cash": 0.0, "driver": "book", "g5": g})
    assert v["flows_all"][0] == pytest.approx(R[1] * roe - (R[2] - R[1]))


def test_bridge_adds_each_years_amortization_and_none_in_the_long_run():
    # v1.3 production path (D_acquirer +12%): K_0 holds only non-operating items; A_t is added per year, so a run-off schedule does not
    # leave the base year's amortization in the long-run margin
    b = base()
    assert b["k0"] == pytest.approx(16 - (13 - 7 * BILL))
    with_a = inputs.bridge_x_margin(b, [0.16], [100.0], [1.0])[0]
    without = inputs.bridge_x_margin(b, [0.16], [100.0])[0]
    assert with_a == pytest.approx(b["m0"]) and with_a - without == pytest.approx(1.0 * (1 - b["tau"]) / 100)



def test_nci_material_is_stamped_and_dominant_refused():
    assert "nci_material" in base(facts(nci_income=series([1, 1, 1, 1, 2.0])))["stamps"]       # 15% of pretax
    with pytest.raises(desk.DeskRefusal) as e:
        base(facts(nci_income=series([1, 1, 1, 1, 4.0])))                                     # 31%
    assert e.value.code == "nci_dominant"


def test_revenue_not_positive_is_refused():
    with pytest.raises(desk.DeskRefusal) as e:
        base(facts(revenue=series([80, 0, 90, 95, 100])))
    assert e.value.code == "revenue_not_positive"


def test_eps_rounded_to_the_cent_is_accepted():
    # NI 0.104 on 10 shares is 0.0104 a share, filed as 0.01: 4% off relatively, within the cent
    f = facts(net_income=series([8, 8.8, 9.6, 10, 0.104]), eps_diluted=series([0.8, 0.88, 0.96, 1.0, 0.01]))
    assert "shares_weighted_average_diluted" in base(f)["stamps"]


def test_vintages_out_of_bounds_falls_back_to_pooled():
    # life = gross_prior / D&A_org = 200 / 4 = 50 years: outside [5, 40]
    f = facts(ppe_gross=series([200, 200, 200, 200, 200]), ppe_net=series([100, 100, 100, 100, 100]))
    b = base(f)
    assert b["ppe"] is None and b["da_rule"] == "pooled" and any(s.startswith("da_vintages_out_of_bounds") for s in b["stamps"])


def test_book_delta_is_capped_and_negative_equity_valued_at_the_cap():
    b = base(facts(equity=series([40, 41, 42, 44, 2])))                  # net debt 13 over 13 + 2: 0.87 -> capped
    assert b["delta"] == inputs.DELTA_CAP and "delta_book_capped" in b["stamps"]
    b = base(facts(equity=series([40, 41, 42, 44, -5])))
    assert b["delta"] == inputs.DELTA_CAP and "book_equity_negative_delta_at_cap" in b["stamps"]


def test_only_interest_scales_with_revenue_in_the_bridge():
    b = base()
    k_int, k_other = b["k0_interest"], b["k0"] - b["k0_interest"]
    x = inputs.bridge_x_margin(b, [0.16], [200.0], [1.0])[0]
    assert x == pytest.approx((0.16 * 200 + 1.0 - k_int * 2 - k_other) * (1 - b["tau"]) / 200)

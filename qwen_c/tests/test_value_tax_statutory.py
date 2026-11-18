"""WO_NC3: the statutory tax rate the company files, as the last rung of the tax rate, and the value shown at two rates. Synthetic facts only.
The fallback fires only after every measured rung fails, takes the filed rate as filed (a filed 0.0 is a rate), is refused outside the band or
where it is not filed for the base year, drives the value and the checks at the filed rate, and carries a second rate beside it."""
import json

import pytest

from qwen_c import runner
from qwen_c.tests import test_value_checks as C
from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_run import fake, value
from qwen_c.value import checks, desk, forecast, inputs, memo, run

STAT = "EffectiveIncomeTaxRateReconciliationAtFederalStatutoryIncomeTaxRate"
FB = "tax_rate_statutory_fallback"
E0 = ti.ENDS[-1]


def stat(vals, tag=STAT, ends=ti.ENDS):
    return ti.series(vals, tag=tag, ends=ends)


def fb_inputs(rate=0.21, **over):
    """Inputs facts whose measured rungs all fail (the latest year at 50%, two measured years only) and that file a statutory rate."""
    return ti.facts(pretax_income=ti.series([-8, -8, -9, 12, 13]), tax_provision=ti.series([0, 0, 0, 2, 6.5]),
                    statutory_tax_rate=stat([rate] * 5), **over)


# ---- tax_rate: the last rung ---------------------------------------------------------------------------------------------------------

def test_the_filed_rate_is_returned_as_filed_after_every_rung_failed():
    assert inputs.tax_rate(fb_inputs(0.23), E0) == (0.23, FB)
    assert inputs.tax_rate(fb_inputs(0.0), E0) == (0.0, FB)                           # a filed 0.0 is a rate
    assert inputs.tax_rate(fb_inputs(0.35), E0) == (0.35, FB)                         # the band's edge is in


def test_every_measured_rung_comes_first():
    s = stat([0.21] * 5)
    assert inputs.tax_rate(ti.facts(statutory_tax_rate=s), E0) == (pytest.approx(0.2), "tax_rate_measured")
    f = ti.facts(net_income=ti.series([8, 8.8, 9.6, 10, 13.0]), tax_provision={"values": []}, statutory_tax_rate=s)
    assert inputs.tax_rate(f, E0) == (0.0, "tax_zero_no_provision")                   # no provision filed, net income is pretax: the zero rung wins
    f = ti.facts(tax_provision=ti.series([0.02, 0.0759, -0.0312, -0.01625, -0.013]), statutory_tax_rate=s)
    assert inputs.tax_rate(f, E0) == (0.0, "tax_rate_median_near_zero")
    f = ti.facts(tax_provision=ti.series([4.0, 6.0, 4.9, 7.0, 5.3]), statutory_tax_rate=s)
    assert inputs.tax_rate(f, E0)[1] == "tax_rate_median_outside_band"


@pytest.mark.parametrize("rate", [0.351, 0.40, 0.50, -0.01])
def test_a_filed_rate_outside_the_band_is_not_used(rate):
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.tax_rate(fb_inputs(rate), E0)
    assert e.value.code == "tax_unavailable" and "no statutory rate in the band" in str(e.value) and "never a stamped default" not in str(e.value)


def test_no_statutory_rate_filed_is_the_refusal_as_before():
    f = fb_inputs()
    del f["statutory_tax_rate"]
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(f, market_cap=180.0, bill_rate=ti.BILL)
    assert e.value.code == "tax_unavailable"


def test_a_rate_filed_for_another_year_only_is_not_used():
    f = fb_inputs()
    f["statutory_tax_rate"] = stat([0.21] * 4, ends=ti.ENDS[:4])
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.tax_rate(f, E0)
    assert e.value.code == "tax_unavailable"


# ---- base: the stamps, the second rate, tau_override --------------------------------------------------------------------------------------

def test_the_fallback_base_carries_the_rate_the_second_rate_and_the_stamps():
    b = ti.base(fb_inputs(0.21))
    assert b["tau"] == 0.21 and FB in b["stamps"] and "tax_fallback_positive_pretax_years:2_of_5" in b["stamps"]
    tf = b["tax_fallback"]
    assert tf["rate"] == 0.21 and tf["rate_alt"] == pytest.approx(0.21 + inputs.STATUTORY_UPLIFT) and tf["source_tag"] == f"us-gaap:{STAT}"
    assert (tf["positive_pretax_years"], tf["pretax_years"]) == (2, 5)
    assert inputs.STATUTORY_UPLIFT == 0.055


def test_the_pretax_years_counted_are_those_in_the_pooled_window_with_a_filed_pretax_income():
    f = fb_inputs()
    f.update(pretax_income=ti.series([-9, 12, 13]), tax_provision=ti.series([0, 2, 6.5]), statutory_tax_rate=stat([0.25] * 5, tag="ApplicableTaxRate"))
    b = ti.base(f)
    assert "tax_fallback_positive_pretax_years:2_of_3" in b["stamps"]
    assert b["tax_fallback"]["source_tag"] == "ifrs-full:ApplicableTaxRate"


def test_a_filed_zero_rate_is_a_value_and_its_second_rate_is_the_uplift():
    b = ti.base(fb_inputs(0.0))
    assert b["tau"] == 0.0 and b["tax_fallback"]["rate"] == 0.0 and b["tax_fallback"]["rate_alt"] == inputs.STATUTORY_UPLIFT
    assert b["x0"] == pytest.approx((13 - 7 * ti.BILL + 1) * 1.0)


def test_tau_override_changes_the_base_the_return_and_the_nci_term_and_nothing_else():
    f = fb_inputs(0.21, nci_income=ti.series([1, 1, 1, 1, 1]))
    b1 = ti.base(f)
    alt = b1["tax_fallback"]["rate_alt"]
    b2 = inputs.base(f, market_cap=180.0, bill_rate=ti.BILL, tau_override=alt)
    pt_ex = lambda tau: 13 - 7 * ti.BILL - 1 / (1 - tau)                               # the NCI term is grossed up at tau
    assert b1["x0"] == pytest.approx((pt_ex(0.21) + 1) * (1 - 0.21)) and b2["x0"] == pytest.approx((pt_ex(alt) + 1) * (1 - alt))
    assert b2["tau"] == alt and b2["ronic0"] == pytest.approx((b2["x0"] + 1 * (1 - alt)) / (44 + 20 - 6 - 4))
    assert b1["k0"] == pytest.approx(16 - pt_ex(0.21)) and b2["k0"] == pytest.approx(16 - pt_ex(alt))
    assert b2["tax_fallback"] == b1["tax_fallback"] and b2["stamps"] == b1["stamps"]
    for k in ("R0", "revenue_hist", "d_ratio", "c_ratio", "w", "delta", "kd", "debt0", "shares", "excess_cash", "amort_schedule", "record", "oi0"):
        assert b2[k] == b1[k], k


def test_a_name_with_a_measured_rate_is_unchanged_by_a_filed_statutory_rate():
    plain, filed = ti.base(), ti.base(ti.facts(statutory_tax_rate=stat([0.21] * 5)))
    assert filed == plain and "tax_fallback" not in plain and not [s for s in plain["stamps"] if "statutory" in s or "tax_fallback" in s]
    assert inputs.base(ti.facts(), market_cap=180.0, bill_rate=ti.BILL, tau_override=None) == plain


def test_the_new_concept_is_auxiliary_and_never_named_stale():
    from qwen_c.value import facts
    assert "statutory_tax_rate" in facts.AUX_CONCEPTS and facts.CONCEPTS["statutory_tax_rate"][1][0][2] == "pure"
    assert facts.taxonomy_of("statutory_tax_rate", "ApplicableTaxRate") == "ifrs-full"


def test_facts_reads_the_pure_number_tags_by_fiscal_year_end():
    from qwen_c.tests.test_value_facts import T, cf, fy, subs
    from qwen_c.value import facts
    acc = "0001-26-000010"
    d = cf([fy("2025-12-31", 100.0, acc), fy("2024-12-31", 90.0, acc)])
    d["facts"]["us-gaap"][STAT] = {"units": {"pure": [fy("2025-12-31", 0.21, acc), fy("2024-12-31", 0.0, acc)]}}
    out = facts.annual_facts(d, subs(), T)
    assert [(v["end"], v["value"], v["tag"]) for v in out["statutory_tax_rate"]["values"]] == [("2024-12-31", 0.0, STAT), ("2025-12-31", 0.21, STAT)]
    assert "statutory_tax_rate" not in out["_stale"]


# ---- run.value: the second value, the first untouched -------------------------------------------------------------------------------------

def fb_facts(rate=0.21):
    f = C.facts()
    f.update(pretax_income=C.series([x * C.M for x in (-8, -8, -9, 12, 13)]), tax_provision=C.series([x * C.M for x in (0, 0, 0, 2, 6.5)]),
             statutory_tax_rate=C.series([rate] * 5, tag=STAT))
    return f


def measured_twin(tau):
    """The same company with a measured rate of exactly `tau` (every number but the rate is that of fb_facts)."""
    f = C.facts()
    f["tax_provision"] = C.series([tau * x * C.M for x in (10, 11, 12, 12.5, 13)])
    return f


def arrange(tmp_path, monkeypatch, f):
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0, g_anchor=0.03, bill_source="test")
    bar, record = forecast.record_bar(b["record"]["op_margin"]), forecast.record_items(f)
    monkeypatch.setattr(run, "prepare", lambda *a, **k: (f, b, bar, record, C.R, C.PROV, C.ENDS))
    pk = {"contract": runner.PACKET_CONTRACT, "ticker": "TEST", "decision_time_utc": "2026-10-30T13:00:00Z",
          "evidence": [{"fact_id": k, "kind": kd, "period": per, "text": t} for k, (kd, per, t) in C.ITEMS.items()]}
    p = tmp_path / "packet.json"
    p.write_text(json.dumps(pk), encoding="utf-8")
    monkeypatch.setattr(runner, "call", fake([C.clean()] * 4, []))
    return p, b


def test_the_value_at_the_second_rate_rides_beside_the_first_and_matches_a_measured_twin(tmp_path, monkeypatch):
    p, b = arrange(tmp_path, monkeypatch, fb_facts())
    res = value(p, tmp_path / "a")
    tr = res["tax_range"]
    assert res["status"] == "ok" and res["base"]["tau"] == 0.21 and FB in res["stamps"] and tr["values"] == res["values"]
    assert tr["rate"] == 0.21 and tr["rate_alt"] == pytest.approx(0.265) and tr["status_alt"] == "ok" and tr["values_alt"] != res["values"]
    assert tr["values_alt"]["base"] < res["values"]["base"]                                         # a higher rate leaves less value
    p2, _ = arrange(tmp_path, monkeypatch, measured_twin(0.21))                                       # rate one equals the measured twin at that rate
    once = value(p2, tmp_path / "b")["values"]
    assert once == {k: pytest.approx(v, rel=1e-9) for k, v in res["values"].items()}
    p3, _ = arrange(tmp_path, monkeypatch, measured_twin(0.265))                                      # rate two equals the twin at the second rate
    twin = value(p3, tmp_path / "c")
    assert twin["base"]["tau"] == pytest.approx(0.265) and "tax_range" not in twin
    for k in ("bear", "base", "bull"):
        assert tr["values_alt"][k] == pytest.approx(twin["values"][k], rel=1e-9)


def test_tax_range_is_present_only_on_a_fallback(tmp_path, monkeypatch):
    p, _ = arrange(tmp_path, monkeypatch, C.facts())
    res = value(p, tmp_path / "a")
    assert res["status"] == "ok" and "tax_range" not in res and "tax_fallback" not in res["base"]


@pytest.mark.parametrize("how", ["refusal", "defect", "no_call"])
def test_a_failing_second_check_leaves_the_first_result_intact(tmp_path, monkeypatch, how):
    p, b = arrange(tmp_path, monkeypatch, fb_facts())
    first = value(p, tmp_path / "a")
    alt_tau = b["tax_fallback"]["rate_alt"]
    real = checks.check

    def check(reply, ids, base, *a, **k):
        if base["tau"] == alt_tau:
            if how == "defect":
                raise AssertionError("V1: injected")
            if how == "no_call":
                return dict(real(reply, ids, base, *a, **k), status="no_call", reason="x", detail="y", values={})
        return real(reply, ids, base, *a, **k)
    monkeypatch.setattr(checks, "check", check)
    if how == "refusal":
        monkeypatch.setattr(run, "alt_tax_base", lambda *a: (_ for _ in ()).throw(desk.DeskRefusal("e0_not_positive", "no earnings base")))
    again = value(p, tmp_path / "b")
    tr = again["tax_range"]
    assert tr["values_alt"] is None and tr["status_alt"] and again["status"] == first["status"] == "ok"
    assert {k: again[k] for k in ("values", "checks", "inputs")} == {k: first[k] for k in ("values", "checks", "inputs")}
    assert {"refusal": "e0_not_positive", "defect": "engine_defect", "no_call": "no_call: x: y"}[how] in tr["status_alt"]


def test_the_memo_says_the_rate_is_the_filed_statutory_one_and_prints_both_values(tmp_path, monkeypatch):
    p, _ = arrange(tmp_path, monkeypatch, fb_facts())
    res = value(p, tmp_path / "a")
    text = (next((tmp_path / "a").iterdir()) / "memo.md").read_text(encoding="utf-8")
    va = res["tax_range"]["values_alt"]
    assert "statutory rate (company's filed rate), not measured" in text and "21.0%" in text and "26.5%" in text
    assert f"base {va['base']:,.2f}" in text and memo.MEMO_VERSION == "m3q.memo.v8"
    res["tax_range"] = dict(res["tax_range"], values_alt=None, status_alt="no_call: x")
    assert "not available (no_call: x)" in memo.render(res)

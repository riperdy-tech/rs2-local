"""Addendum AE.3: the pass-1 baselines from the quarters known at T."""
import pytest

from rebuild_harness.gate2 import baselines as bl


def row(pe, rev, rev0, oi, oi0, ni=None, ni0=None, filed="2025-08-01"):
    return {"period_end": pe, "filed": filed, "accepted_at": None, "values": {"revenue": rev, "operating_income": oi, "net_income": ni},
            "prior_year": {"revenue": rev0, "operating_income": oi0, "net_income": ni0}}


def test_persistence_and_trailing_four_quarters_for_an_operating_company():
    rows = [row("2024-12-31", 100, 90, 10, 9), row("2025-03-31", 110, 100, 12, 10), row("2025-06-30", 120, 100, 15, 10), row("2025-09-30", 130, 110, 13, 11),
            row("2024-09-30", 95, 95, 9, 9)]
    b = bl.company_baselines(rows, "operating", None)
    assert b["growth"]["persistence"] == pytest.approx(130 / 110 - 1) and b["growth"]["latest_quarter"] == "2025-09-30"
    g4 = [100 / 90 - 1, 110 / 100 - 1, 120 / 100 - 1, 130 / 110 - 1]
    assert b["growth"]["t4q"] == pytest.approx(sum(g4) / 4)
    assert b["margin"]["persistence"] == pytest.approx(13 / 130 - 11 / 110)


def test_missing_inputs_are_none_never_zero_and_t4q_needs_four():
    b = bl.company_baselines([row("2025-06-30", 120, None, 15, 10), row("2025-09-30", 130, 110, None, 11)], "operating", None)
    assert b["growth"]["persistence"] == pytest.approx(130 / 110 - 1) and b["growth"]["t4q"] is None and b["margin"]["persistence"] is None
    assert bl.company_baselines([], "operating", None)["growth"] == {"persistence": None, "t4q": None, "latest_quarter": None}


def test_financials_use_the_annualised_rote_change_on_tangible_book():
    b = bl.company_baselines([row("2025-09-30", 50, 48, None, None, ni=6.0, ni0=5.0)], "financial", 100.0)
    assert set(b) == {"margin"} and b["margin"]["persistence"] == pytest.approx(0.04)
    assert bl.company_baselines([row("2025-09-30", 50, 48, None, None, ni=6.0, ni0=5.0)], "financial", None)["margin"]["persistence"] is None


def test_build_applies_eligibility_skips_commodity_and_takes_medians_per_date_and_family():
    class Pit:
        def quarterly_rows(self, cik, d, fields, n):
            k = int(cik)
            return [row("2025-06-30", 100 + k, 100, 10, 10), row("2025-09-30", 100 + 2 * k, 100, 10, 10, filed="2025-11-30")]
    uni = {"2025-10-31": [{"cik": "1", "family": "operating"}, {"cik": "2", "family": "operating"}, {"cik": "3", "family": "operating"},
                          {"cik": "4", "family": "commodity"}]}
    elig = lambda acc, filed, d: "ok" if filed < d else "after"
    rep = bl.build(Pit(), uni, elig, lambda *a: None)
    assert "2025-10-31_0000000004" not in rep["companies"]                              # commodity out of scope (V3)
    c1 = rep["companies"]["2025-10-31_0000000001"]
    assert c1["n_quarters"] == 1 and c1["baselines"]["growth"]["persistence"] == pytest.approx(0.01)   # the quarter filed after T is not known at T
    assert rep["pop_median"]["2025-10-31"]["operating"]["growth"] == pytest.approx(0.02)


# ---- Addendum AH: the annual-convention run-rate ----------------------------------------------------------------------------------------------

Q4 = [row("2024-12-31", 100, 90, 10, 9, ni=3.0), row("2025-03-31", 110, 100, 12, 10, ni=3.2), row("2025-06-30", 120, 100, 15, 10, ni=3.4),
      row("2025-09-30", 130, 110, 13, 11, ni=3.6)]


def test_runrate_is_four_contiguous_quarters_against_the_build_state_base_year():
    r = bl.runrate(Q4, "operating", {"op_margin": 0.10})
    assert r["growth"] == pytest.approx(460 / 400 - 1) and r["margin"] == pytest.approx(50 / 460 - 0.10)
    assert bl.runrate(Q4[1:], "operating", {"op_margin": 0.10}) == {"growth": None, "margin": None}                 # fewer than four
    gap = Q4[:2] + [row("2025-09-30", 130, 110, 13, 11), row("2025-12-31", 140, 120, 14, 12)]
    assert bl.runrate(gap, "operating", {"op_margin": 0.10})["growth"] is None                                     # a missing quarter is never bridged
    assert bl.runrate(Q4, "operating", {})["margin"] is None and bl.runrate(Q4, "operating", None)["growth"] == pytest.approx(0.15)


def test_runrate_rote_uses_the_same_denominator_as_rote_latest_and_zero_is_a_value():
    st = {"base_period": "2024-12-31", "tbv_series": {"2023-12-31": 100.0, "2024-12-31": 120.0}, "rote_latest": 0.10}
    assert bl.runrate(Q4, "financial", st) == {"margin": pytest.approx(13.2 / 110 - 0.10)}
    zero = [dict(r, values=dict(r["values"], net_income=0.0)) for r in Q4]
    assert bl.runrate(zero, "financial", st)["margin"] == pytest.approx(-0.10)
    assert bl.runrate(Q4, "financial", dict(st, tbv_series={"2024-12-31": 120.0}))["margin"] == pytest.approx(13.2 / 120 - 0.10)   # first year: no average
    assert bl.runrate(Q4, "financial", dict(st, rote_latest=None))["margin"] is None


def test_build_records_the_runrate_and_its_population_median():
    class Pit:
        def quarterly_rows(self, cik, d, fields, n):
            k = int(cik)
            return [dict(r, values=dict(r["values"], revenue=r["values"]["revenue"] * k)) for r in Q4]
    uni = {"2025-10-31": [{"cik": "1", "family": "operating"}, {"cik": "2", "family": "operating"}, {"cik": "3", "family": "operating"}]}
    rep = bl.build(Pit(), uni, lambda acc, filed, d: "ok", lambda cik, d, t: {"op_margin": 0.10})
    gs = sorted(rep["companies"][f"2025-10-31_{c:010d}"]["runrate"]["growth"] for c in (1, 2, 3))
    assert gs == pytest.approx([460 / 400 - 1, 920 / 400 - 1, 1380 / 400 - 1])
    assert rep["pop_median_runrate"]["2025-10-31"]["operating"]["growth"] == pytest.approx(920 / 400 - 1)

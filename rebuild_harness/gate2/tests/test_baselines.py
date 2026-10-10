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

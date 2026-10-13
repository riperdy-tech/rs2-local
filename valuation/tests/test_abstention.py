"""Plan B6: every refusal path seen in gate-2 run 2 maps to a "no view" code, and a technical failure never does."""
import pytest

from valuation.abstention import abstention

# the distinct (status, reason) pairs of gate-2 run 2 at 563 company-dates (2026-10-13), each with the code it must map to
RUN2 = [
    ("engine_refused", ["not available: trailing 3-year ROIC (NOPAT / invested capital ...)"], "engine_refused"),
    ("engine_refused", ["not available: operating_income", "not available: trailing 3-year ROIC (...)"], "engine_refused"),
    ("refused", "discount rate: industry_unmapped: no Damodaran industry for the company (the current-dated industry file does not list it)", "family_not_built"),
    ("engine_refused", ["not available: revenue", "not available: trailing 3-year ROIC (...)"], "engine_refused"),
    ("engine_refused", ["not available: maintenance capex ratio (Greenwald ...)"], "engine_refused"),
    ("engine_refused", ["not available: net working capital / revenue (...)"], "engine_refused"),
    ("engine_refused", ["not available: debt (an interest charge is filed but no debt component)"], "engine_refused"),
    ("engine_refused", ["not available: tangible book value is not positive (-12.3): the excess-return method has no base"], "engine_refused"),
    ("engine_refused", ["not available: cash", "not available: trailing 3-year ROIC (...)"], "engine_refused"),
    ("engine_refused", ["not available: base-year return on tangible equity (...)"], "engine_refused"),
    ("engine_refused", ["not available: revenue is not positive", "not available: base-year operating margin (...)"], "engine_refused"),
    ("engine_refused", ["priors do not supply: ['g1', 'growth_decay']"], "family_not_built"),          # VIRT, MIAX, CBOE once corrected (AK.5, AK.14)
]


@pytest.mark.parametrize("status,reason,code", RUN2)
def test_every_run2_refusal_maps_to_its_code_with_the_reasons_copied(status, reason, code):
    a = abstention(status, reason, family="financial")
    assert a["code"] == code and a["reasons"] and a["reason"]


def test_technical_failures_are_never_a_no_view_and_valued_companies_are_not_abstentions():
    assert abstention("error", "KeyError: 'growth_decay'") is None
    assert abstention("transport_failure", None) is None
    assert abstention("ok", None, family="operating", has_value_per_share=True, has_recent_10q=True) is None


def test_unbuilt_families_foreign_issuers_and_missing_share_counts_are_named():
    assert abstention("ok", None, family="commodity")["code"] == "family_not_built"
    assert abstention("not_valued", "family 'reit': ...", family="reit")["code"] == "family_not_built"
    assert abstention("ok", None, family="operating", has_recent_10q=False)["code"] == "no_quarterly_filings"
    assert abstention("ok", None, family="operating", has_value_per_share=False, has_recent_10q=True)["code"] == "no_share_count"

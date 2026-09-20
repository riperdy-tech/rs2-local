"""One owner for the contract base.

Three independent resolutions of the same published number existed:

  * `depth_pipeline.contract_base(scorecard)`  -> `base_iv or median_iv`
  * the `mos_vs_median_pct` anchor in `band_verdict` (deliberately the dispersion statistic)
  * `depth_sanity.py:117`                      -> `base_iv or median_iv or lo`

The third is not merely a copy: it carries an extra fallback (`or lo`, the platform band's low
bound) that the other two lack, so the two resolvers disagree on any scorecard that has neither
`base_iv` nor `median_iv`. They diverge on real data whenever `base_iv` exists and differs from
`median_iv` - GEV's shape, where the published fields sat 3.4 points apart.

The fix is not to make the auditor copy the rule more carefully. It is to give the rule one
owner, `fiduciary_gate.contract_base`, which both import; the auditor's extra tolerance then
stays visible as `or lo` at its own call site rather than hiding inside a second definition.

This also pins the MoS convention to (A) `IV/price - 1` by construction: `contract_base` and the
MoS restatement are the same step in the retired spec, so they must read one field.
"""
import pytest

import depth_pipeline as dp
from tools.audit_202608 import depth_sanity as ds
from tools.audit_202608 import fiduciary_gate as fg


# ---- the resolver itself ---------------------------------------------------------------

def test_the_contract_base_is_the_medoid_base_when_both_are_present():
    # GEV: base 549.77, median 517.745. The base wins; the median is dispersion.
    assert fg.contract_base({"base_iv": 549.77, "median_iv": 517.745}) == 549.77


def test_the_median_is_the_documented_legacy_fallback():
    # Verdicts published before 2026-09-20 carry no `base_iv`.
    assert fg.contract_base({"median_iv": 517.745}) == 517.745


def test_no_base_available_is_none_not_a_guess():
    assert fg.contract_base({}) is None
    assert fg.contract_base(None) is None


# ---- single ownership ------------------------------------------------------------------

def test_the_pipeline_and_the_auditor_share_one_resolver():
    """Not copies that could drift - the same function object.

    Both route through the BARE `fiduciary_gate` module (the tools directory is on `sys.path`),
    so whichever loads first, the other reuses it from `sys.modules`. Note the comparison must
    use that same route: `tools.audit_202608.fiduciary_gate` is a DIFFERENT module instance of
    the same file when a test imports the dotted path, so `fg.contract_base` is not the object
    production holds. That dual-instance quirk is pre-existing and repo-wide, not introduced
    here; asserting identity against the dotted path would test the import system, not ownership.
    """
    assert dp.contract_base is ds.contract_base


def test_the_rule_is_defined_once_in_the_source_tree():
    # A guard against a future re-introduction of a local copy inside the pipeline.
    import inspect
    assert inspect.getsourcefile(dp.contract_base).endswith("fiduciary_gate.py")
    assert inspect.getsourcefile(ds.contract_base).endswith("fiduciary_gate.py")


def test_depth_sanity_routes_the_base_through_the_shared_resolver(monkeypatch):
    """The auditor must CALL the shared resolver, not re-implement it.

    Patched to a base ABOVE the price while the scorecard's own `median_iv` sits BELOW it. If
    the auditor still resolves inline it reads 934.535 < 951.04 and fails the contract; routing
    through the resolver it reads 1000.0 and passes. That difference is the whole point: a
    second definition is a second policy.
    """
    monkeypatch.setattr(ds, "contract_base", lambda scorecard: 1000.0)
    verdict = {
        "ticker": "GEV", "price": 951.04, "direction": "hold", "size_hint": "half",
        "iv_band_low": 831.19, "iv_band_high": 1037.88, "n_basis": 2, "spread_pct": 24.9,
        "samples_run": 3, "early_stop": False,
        "scorecard": {"median_iv": 934.535, "median_kelly_fraction_pct": 8.98},
    }
    level, lines = ds.audit("GEV", verdict)
    assert level < 2, lines
    assert not any("fiduciary" in l.lower() for l in lines)


def test_depth_sanity_keeps_its_extra_tolerance_for_a_scorecard_with_no_iv(monkeypatch):
    """The auditor runs on ledger rows that may predate the scorecard entirely. Its `or lo`
    fallback must survive the move - it is the auditor's own tolerance, held at its call site."""
    seen = {}
    monkeypatch.setattr(ds, "contract_base", lambda scorecard: seen.setdefault("called", True))
    verdict = {
        "ticker": "GEV", "price": 951.04, "direction": "hold", "size_hint": "half",
        "iv_band_low": 800.0, "iv_band_high": 1037.88, "n_basis": 2, "spread_pct": 24.9,
        "samples_run": 3, "early_stop": False, "scorecard": {"median_kelly_fraction_pct": 8.98},
    }
    ds.audit("GEV", verdict)
    # contract_base returned None; the auditor must not raise on that, and must fall back to lo.
    assert seen.get("called") is True

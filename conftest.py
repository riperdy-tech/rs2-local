"""conftest.py — suite-level guard against writing into production cache/.

B2 (Phase 1 approval review, fix list): the canonical test invocation is
`pytest tests tools/audit_202608/tests`, and this file sits at their common ancestor so it loads
for both. The review measured that tests/test_factor_guard.py's od.main() tests wrote a real
wrong-engine row into cache/depth_membership.jsonl and appended to cache/depth_orchestrate.log —
production state consumed by real capital allocation. Those tests are now isolated (redirect
LOG/STATE, stub the network- and file-scanning calls), but this fixture is the backstop for every
test, present and future: any test that leaves so much as one file under cache/ with a changed
mtime, or added/removed, fails loudly instead of corrupting production state silently.
"""
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"


def _snapshot():
    if not CACHE.exists():
        return {}
    return {str(p.relative_to(CACHE)): p.stat().st_mtime_ns
            for p in CACHE.rglob("*") if p.is_file()}


@pytest.fixture(autouse=True)
def _cache_must_stay_untouched():
    before = _snapshot()
    yield
    after = _snapshot()
    if after != before:
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(p for p in (set(after) & set(before)) if after[p] != before[p])
        pytest.fail(
            "test wrote into production cache/ — added=" + repr(added) +
            " removed=" + repr(removed) + " mtime-changed=" + repr(changed) +
            ". Redirect the module's LOG/STATE/etc. to tmp_path instead of letting it touch "
            "the real cache/ directory.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _risk_bucket_is_deterministic_in_tests(monkeypatch):
    """P4.9/C1 — depth_pipeline.band_verdict() calls risk_bucket(), which reads the MRI shock
    register LIVE off disk (CONFIG["mri_outputs_dir"]/shock_register.json) to see whether
    elevated_volatility_ahead is active right now. A test must never depend on that: today's
    real reading changes with market conditions, so an un-mocked band_verdict() test would pass
    or fail depending on the state of the world outside the test, not on the code under test.

    Every test defaults to the neutral, non-restricting reading ('full', None) — exactly as if
    the risk component were absent from the P4.9 min(). A test that wants to exercise the risk
    component itself (an active flag capping to 'half', or an unreadable register producing
    None + risk_flag_unavailable) re-applies its own `monkeypatch.setattr(dp, "risk_bucket", ...)`
    in its own body, which simply overrides this default for that one test.
    """
    import depth_pipeline as dp
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("full", None))


@pytest.fixture(autouse=True)
def _isolate_sec_guidance_in_tests(monkeypatch, tmp_path):
    """P4 D4b: Isolate sec_guidance caches from production cache/ and disable unmocked network calls in tests."""
    import urllib.error
    import sec_guidance
    import depth_triggers
    monkeypatch.setattr(sec_guidance, "SEC_8K_CACHE", tmp_path / "sec_8k")
    monkeypatch.setattr(sec_guidance, "SUB_CACHE", tmp_path / "sec_submissions")
    monkeypatch.setattr(depth_triggers, "SUB_CACHE", tmp_path / "sec_submissions")

    def _no_network_urlopen(*args, **kwargs):
        raise urllib.error.URLError("Network disabled in tests")

    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", _no_network_urlopen)


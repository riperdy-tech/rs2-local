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

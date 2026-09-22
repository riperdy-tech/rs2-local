"""Shared fixtures for the audit suite.

WHY A DATA STUB EXISTS. Several tests call `capability_test.build_pack("GEV")`, which reads the
operator's screener data directory - `config.json -> screener_data_dir`, an absolute path under
`Downloads`. Those tests therefore passed only on the machine that wrote them: redirect that path
to a non-existent directory and five of them fail. That is the same defect as a guard that only
fires for its author, which is exactly the class of bug this suite keeps finding.

`fixture_data/` holds the GEV entries copied VERBATIM from the real files by
`scratch/make_gev_fixture.py`. Real data, not a hand-authored approximation: an approximation
would encode a guess about what `build_pack` reads and then go stale silently when it changed.

Files named `<dir>__<name>.json` land at `<SD>/<dir>/<name>.json`; the rest land at `<SD>/<name>`.
"""
import shutil
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
AUDIT_DIR = TESTS.parent                  # tools/audit_202608
REPO = AUDIT_DIR.parent                   # repo root
FIXTURE = TESTS / "fixture_data"

# The test modules import both `tools.audit_202608.x` and bare `depth_pipeline` / `common`, so
# both the repo root and the audit directory must be importable regardless of invocation cwd.
for _p in (str(REPO), str(AUDIT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def screener_data_stub(tmp_path, monkeypatch):
    """Point both screener-data constants at a committed GEV slice.

    BOTH are patched on purpose: `capability_test.build_pack` reads `cap.SD`, while
    `consensus_valuation.owner_cf_by_year` reads `common.SD`. Patching one would leave the other
    resolving this machine's real directory and the test would still be machine-dependent.
    """
    import common
    import capability_test as cap

    sd = tmp_path / "data"
    (sd / "financials").mkdir(parents=True, exist_ok=True)
    for f in sorted(FIXTURE.glob("*.json")):
        if f.name.startswith("_"):
            continue
        if "__" in f.name:
            sub, leaf = f.name.split("__", 1)
            (sd / sub).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, sd / sub / leaf)
        else:
            shutil.copyfile(f, sd / f.name)

    monkeypatch.setattr(cap, "SD", sd)
    monkeypatch.setattr(common, "SD", sd)
    # `_sec_facts` memoizes per process keyed on TICKER ONLY, so a lookup made before this stub
    # applied is served from the cache afterwards - the test then reads whichever directory was
    # in effect at that moment and the redirect silently does nothing. Clearing it is also the
    # honest behaviour: the cache is keyed on a ticker, but the value depends on the directory.
    cap._SEC_CACHE.clear()
    return sd

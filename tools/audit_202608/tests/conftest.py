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
import json
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
    # Revision 18, amendment 2 (a missing provenance marker is a stated gap): the committed slice of the history predates brief A, so
    # it carries no marker for GEV. Every name of the book carries one (the extractor processed it); the copy gives GEV the marker of
    # nothing untagged, which is exactly what the code read for a missing marker before the guard, so the golden packs hold. A test
    # of the guard itself removes it (tools/audit_202608/tests/test_rev18_marker_guard.py).
    hist = sd / "fundamentals_history.json"
    if hist.exists():
        doc = json.loads(hist.read_text(encoding="utf-8"))
        doc.setdefault("provenance", {}).setdefault("untagged_fields", {}).setdefault("GEV", [])
        hist.write_text(json.dumps(doc), encoding="utf-8")

    monkeypatch.setattr(cap, "SD", sd)
    monkeypatch.setattr(common, "SD", sd)
    monkeypatch.setattr(cap, "HERE", tmp_path)
    # `_sec_facts` memoizes per process keyed on TICKER ONLY, so a lookup made before this stub
    # applied is served from the cache afterwards - the test then reads whichever directory was
    # in effect at that moment and the redirect silently does nothing. Clearing it is also the
    # honest behaviour: the cache is keyed on a ticker, but the value depends on the directory.
    cap._SEC_CACHE.clear()
    return sd


@pytest.fixture
def anchors_of_the_frozen_day(tmp_path, monkeypatch):
    """The MRI capital-market anchors as they stood on the day these tests freeze the clock (2026-09-27), written to a folder of their own.

    Tests that freeze `datetime` at 2026-09-27 used to read the anchors from the live MRI outputs folder. Once MRI republished with an
    `asof` after the frozen day, the anchor's age came out negative and `rs2_data.usable_anchor` (0 to anchor_max_age_days) rejected it, so
    the reference silently became "not_available"; and the literal rates the tests pin (the 8.98% cost of equity) are September's, not today's.
    The legs below are the ones the committed golden pack (fixture_data/golden_pack_GEV_rev22.md, "Rates:" and "COE ANCHOR" lines) printed:
    rf 5.01%, real 10y 2.68%, breakeven 2.34%, market premium 4.35%, market cost of equity 9.36%, the industrials loading 0.868, the growth
    anchor 3.75%, and the inflation trend (CPI 3.35%, PCE 3.70%, the golden pack's SECTION 1.6 line). `nominal_gdp_trend` 4.46% is the value test_rev19_text.py uses. The sector bands are left out (the bands accessor then
    returns {}, the pack's own "not available" reading). `rs2_data.CONFIG["anchors_dir"]` is the seam the code reads (`anchors_dir()`);
    the per-process anchor cache is reset so this folder is read."""
    import rs2_data

    d = tmp_path / "anchors_frozen_day"
    d.mkdir()
    cost = {"anchor_id": "cost_of_capital", "asof": "2026-09-26", "degraded": False, "erp_basis": "universe",
            "risk_free": {"nominal_10y": 0.0501, "real_10y": 0.0268, "breakeven_10y": 0.0234},
            "implied_erp": 0.0435, "implied_cost_of_equity": 0.0936, "sector_loadings": {"industrials": 0.868},
            "inflation": {"cpi_yoy": 0.0335, "pce_yoy": 0.0370}}
    growth = {"anchor_id": "long_run_growth", "asof": "2026-09-23", "degraded": False,
              "terminal_g_suggestion": 0.0375, "nominal_gdp_trend": 0.0446}
    (d / rs2_data.ANCHOR_FILES["cost_of_capital"]).write_text(json.dumps(cost), encoding="utf-8")
    (d / rs2_data.ANCHOR_FILES["long_run_growth"]).write_text(json.dumps(growth), encoding="utf-8")
    monkeypatch.setitem(rs2_data.CONFIG, "anchors_dir", str(d))
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    yield d


@pytest.fixture
def clock_of_the_frozen_day(monkeypatch):
    """The pack's clock frozen at 2026-09-27 12:00, the day the committed September fixtures (a consensus record fetched 2026-09-24, a price
    target dated the same week) were current. The 45-day staleness rules read `datetime.now()` in these modules, so a fixture that is only
    "fresh" on its own date goes stale on the real clock and the line it feeds is suppressed. The same patch, on the same modules, as
    test_pack_facts.py's `frozen_env` and test_review_b1_b4.py's `_FixedNow` (those two stay local to their files)."""
    from datetime import datetime as _real_datetime
    import capability_test as cap
    import catalyst_research
    import rs2_data
    import valuation_backbone

    fixed = _real_datetime(2026, 9, 27, 12, 0, 0)

    class _Frozen(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    for mod in (cap, rs2_data, catalyst_research, valuation_backbone):
        monkeypatch.setattr(mod, "datetime", _Frozen, raising=False)
    return fixed

"""C2: the harness call sites fed the production inputs of G's book run reproduce the revisions' reference values to the cent.

The recorded values were produced by the production pack build (wb_build.py) at fee17cf and at ac68e25 on the 291 book names; the
check replays each recorded `build` call (its estimates from the run's enrich cache) through arms.baseline_build / candidate_build in
the two revisions' own processes.  Skipped when the recorded runs are not on this machine."""
import json
import os
from pathlib import Path

import pytest

BT = Path(os.environ.get("BACKTEST_ROOT", r"C:/Users/riper/AppData/Local/Temp/claude/C--Users-riper-stocks/d3013e2d-dbcb-4c2e-be4e-49617528a6b8/scratchpad/backtest"))
C2 = BT / "out" / "c2"
pytestmark = pytest.mark.skipif(not (C2 / "b_old_fee17cf.json").exists() and (C2 / "b_new_ac68e25.json").exists(),
                                reason="the recorded book runs are not on this machine")


@pytest.mark.parametrize("arm,rows", [("baseline", "b_old_fee17cf.json"), ("candidate", "b_new_ac68e25.json")])
def test_production_reference_values_reproduce_to_the_cent(run, arm, rows):
    # calibration None: revision 17 as committed, with its own reference_calibration_v2.json (no harness override)
    r = run(arm, {"type": "c2_production", "rows": str(C2 / rows), "enrich_root": str(C2 / "root_book"), "calibration": None})
    assert r["names"] == 291
    assert r["valued_recorded"] > 200
    assert r["valued_match_to_the_cent"] == r["valued_recorded"]
    assert r["no_value_recorded_and_no_value_got"] == r["no_value_recorded"]
    assert r["max_abs_diff_valued"] < 0.005

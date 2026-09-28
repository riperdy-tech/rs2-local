"""Reviewer's tests for the S3 package C review (2026-09-28), one or more per defect fixed.

1. A point-in-time pack carries no date later than its as-of date. The share-count default (5.11)
   read today's vendor income statements, so GEV as of 2026-03-31 printed its dilution factor from
   the "quarter ended 2026-06-30", in SECTION 2 and in DEFAULTS. It also multiplied a count that is
   already the filed diluted average. A point-in-time pack now measures no factor.
2. The TASK and the desk's shares_diluted description name 5.11's default (the DEFAULTS
   shares_default), not SECTION 2's count. Since 5.11 the two differ on about 21 names, EZPW among
   them, and a call that followed the old sentence was refused by R1.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import analyst_tools  # noqa: E402
import capability_test as cap  # noqa: E402
import pack_facts  # noqa: E402
import test_consensus_anchor_gate as tcag  # noqa: E402
from test_consensus_anchor_gate import frozen_env  # noqa: E402,F401  (registers the fixture)

ASOF = "2026-03-31"


def _pit_gev(monkeypatch):
    tcag._fake_asof_price_lookup(monkeypatch, price=180.0, asof_str=ASOF)
    tcag._fake_mri_asof(monkeypatch)
    return cap.build_pack("GEV", asof=ASOF, include_research=False)


def test_point_in_time_pack_has_no_date_after_asof(screener_data_stub, frozen_env, monkeypatch):
    text = str(_pit_gev(monkeypatch))
    late = [(d, ln[:120]) for ln in text.splitlines()
            for d in re.findall(r"\b20\d\d-\d\d-\d\d\b", ln) if d > ASOF]
    assert late == []


def test_point_in_time_share_default_is_the_filed_count_without_a_factor(screener_data_stub, frozen_env,
                                                                         monkeypatch):
    pack = _pit_gev(monkeypatch)
    f = pack.facts
    assert f["shares_outstanding"] and f["shares_default"] == f["shares_outstanding"]
    assert f["shares_dilution_factor"] is None and f["shares_dilution_period"] is None
    assert f["shares_warning"] is None
    text = str(pack)
    idx2 = text.index("## DATA 2 ")
    sec2 = text[idx2:text.index("\n## ", idx2 + 5)]
    assert "- Shares dilution factor: not available (point-in-time)" in sec2
    assert "quarter ended" not in sec2
    assert pack_facts.parity(f, pack_facts.from_text(text)) == []


def test_live_pack_still_measures_the_factor(screener_data_stub, frozen_env, monkeypatch):
    # the fix is point-in-time only: the live path keeps 5.11's measured factor and its period
    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["shares_dilution_factor"] is not None
    assert "quarter ended" in (pack.facts["shares_dilution_period"] or "")


def test_task_and_tools_name_the_share_default():
    assert "use the DEFAULTS block's shares_default, the desk's default" in cap.TASK
    assert "use SECTION 2's count" not in cap.TASK
    fm = next(t for t in analyst_tools.TOOLS if t["function"]["name"] == "run_financial_model")
    desc = fm["function"]["parameters"]["properties"]["shares_diluted"]["description"]
    assert "the DEFAULTS block's shares_default" in desc and "SECTION 2's count" not in desc
    assert json.dumps(analyst_tools.TOOLS).count("SECTION 2's count") == 0

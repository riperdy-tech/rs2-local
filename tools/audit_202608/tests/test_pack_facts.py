"""tools/audit_202608/tests/test_pack_facts.py — Step 5 tests for pack facts object.

Covers:
1. GEV fixture parity and literal values
2. from_text branch coverage on hand-written minimal texts
3. build_pack branch coverage via monkeypatched inputs
4. Consumer equivalence across all 5 consumers
5. main() with --pack-file with and without sidecar
"""
import copy
from datetime import datetime as _real_datetime
import hashlib
import json
from pathlib import Path
import socket
import sys
import urllib.request

import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import catalyst_research
import capability_test as cap
import consensus_valuation as cv
import pack_facts
import rs2_data
import valuation_backbone

FIXED_LOCAL = _real_datetime(2026, 9, 27, 12, 0, 0)


class FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FIXED_LOCAL.astimezone(tz)
        return FIXED_LOCAL


@pytest.fixture
def frozen_env(monkeypatch):
    """Freeze clock and stub external services for deterministic build_pack."""
    class BlockedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")
        def connect(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")

    monkeypatch.setattr(socket, "socket", BlockedSocket)
    monkeypatch.setattr(
        cap.company_news, "fetch",
        lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [], "errors": ["stubbed"]}
    )
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    # build_pack imports the screener's industry_taxonomy through sys.path entries it appends itself
    # (capability_test.py SECTION 1). Whether the import succeeds depends on what earlier tests left
    # in sys.path and sys.modules: the SECTION 1 cluster line then reads "Unknown" or the real cluster
    # (20 characters on GEV). Blocking the import pins the fallback branch, so the bytes do not depend
    # on test order. Both branches print through the same lines.
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)

    for mod in (cap, rs2_data, catalyst_research, valuation_backbone):
        monkeypatch.setattr(mod, "datetime", FrozenDatetime, raising=False)


# ---- Case 1: GEV fixture ----------------------------------------------------

def test_gev_fixture_parity_and_literal_values(screener_data_stub, frozen_env):
    pack = cap.build_pack("GEV", include_research=False)
    assert hasattr(pack, "facts"), "PackText must have .facts attribute"

    from_text = pack_facts.from_text(str(pack))
    diffs = pack_facts.parity(pack.facts, from_text)
    assert diffs == [], f"Parity diffs between pack.facts and from_text: {diffs}"

    for k in pack_facts.KEYS:
        got = pack.facts[k]
        if k == "long_run":
            # revision 17 (brief C7): the facts also keep the record's full stamps (`stamps_full`) for the verdict, which the
            # DEFAULTS block does not print; every other member reads back equal
            # brief F1: four held years are fewer than the five an operating-margin median needs
            # revision 18: the test suite's bill rate is "not available" (conftest), so the cash term is stamped
            assert got["stamps_full"] == ["amortization_gap:2022/2023/2024/2025", "tangible_equity_partial:2022/2023/2024/2025",
                                          "margin_record_not_available", "cash_term_not_available_no_bill_rate"]
            got = {m: v for m, v in got.items() if m != "stamps_full"}
        assert got == from_text[k], f"Mismatch for key {k}: {pack.facts[k]} != {from_text[k]}"

    # Literal expected values for at least shares_outstanding, coe_anchor, terminal_g_default, owner_earnings_source
    assert pack.facts["shares_outstanding"] == 266333600.0
    assert pack.facts["coe_anchor"] == 0.0898
    assert pack.facts["terminal_g_default"] == 0.0375
    assert pack.facts["owner_earnings_source"] == "ttm_filed"
    assert pack.facts["net_debt_b"] == -7.676
    assert pack.facts["reference_status"] == "not_available"


# ---- Case 2: from_text branch coverage ---------------------------------------

def test_from_text_branches():
    # 1. Reference used
    t1 = ("CONSENSUS-IMPLIED VALUE (reference, not a forecast): $123.45 per share\n"
          "Consensus cash-flow levels: year 1 $1.200B, year 2 $2.300B")
    f1 = pack_facts.from_text(t1)
    assert f1["reference_status"] == "used"
    assert f1["consensus_implied_value"] == 123.45
    assert f1["levels"] == {"year1": 1.2, "year2": 2.3}

    # 2. Reference used with Bull and Bear levels
    t2 = ("CONSENSUS-IMPLIED VALUE (reference, not a forecast): $123.45 per share\n"
          "Consensus cash-flow levels: year 1 $1.200B, year 2 $2.300B\n"
          "Bull year 2 $3.400B and Bear year 2 $0.800B")
    f2 = pack_facts.from_text(t2)
    assert f2["reference_status"] == "used"
    assert f2["consensus_implied_value"] == 123.45
    assert f2["levels"] == {"year1": 1.2, "year2": 2.3, "bull2": 3.4, "bear2": 0.8}

    # 3. Outside fence above
    t3 = "- CONSENSUS-IMPLIED VALUE: not used — the consensus path carried forward lands above the fence (reference_status: outside_fence_above)"
    f3 = pack_facts.from_text(t3)
    assert f3["reference_status"] == "outside_fence_above"
    assert f3["consensus_implied_value"] is None

    # 4. Outside fence below
    t4 = "- CONSENSUS-IMPLIED VALUE: not used — the consensus path carried forward lands below the fence (reference_status: outside_fence_below)"
    f4 = pack_facts.from_text(t4)
    assert f4["reference_status"] == "outside_fence_below"
    assert f4["consensus_implied_value"] is None

    # 5. Not available (line A: pack_line)
    t5a = "- CONSENSUS-IMPLIED VALUE: not available — no consensus earnings path is available for this name"
    f5a = pack_facts.from_text(t5a)
    assert f5a["reference_status"] == "not_available"
    assert f5a["consensus_implied_value"] is None

    # 6. Not available (line B: _civ_na append)
    t5b = "- CONSENSUS-IMPLIED VALUE: not available — owner-earnings base missing"
    f5b = pack_facts.from_text(t5b)
    assert f5b["reference_status"] == "not_available"
    assert f5b["consensus_implied_value"] is None

    # 7. Negative value (not matched by CIV regex)
    t6 = "CONSENSUS-IMPLIED VALUE (reference, not a forecast): $-12.34 per share"
    f6 = pack_facts.from_text(t6)
    assert f6["reference_status"] is None
    assert f6["consensus_implied_value"] is None

    # 8. Base window with TTM value
    t7 = ("BASE WINDOW CHECK: base_window_gap +18%\n"
          "On the TTM window the consensus path is worth $110.50 per share, year-2 cash-flow level $1.900B")
    f7 = pack_facts.from_text(t7)
    assert f7["base_window"] == {"gap": 0.18, "ttm_value": 110.50, "ttm_year2": 1.9}

    # 9. Base window fenced
    t8 = ("BASE WINDOW CHECK: base_window_gap +22%\n"
          "On the TTM window the consensus path is outside the street fence")
    f8 = pack_facts.from_text(t8)
    assert f8["base_window"] == {"gap": 0.22, "ttm_value": None, "ttm_year2": None}

    # 10. Base window TTM not positive
    t9 = ("BASE WINDOW CHECK: base_window_gap +20%\n"
          "On the TTM window the consensus path is worth $-10.00 per share, year-2 cash-flow level $1.900B")
    f9 = pack_facts.from_text(t9)
    assert f9["base_window"] == {"gap": 0.20, "ttm_value": None, "ttm_year2": None}

    # 11. Net debt positive
    t10 = "NET DEBT (default net_debt for the firm frame): = $15.500B"
    f10 = pack_facts.from_text(t10)
    assert f10["net_debt_b"] == 15.5

    # 12. Net cash (negative net debt)
    t11 = "NET DEBT (default net_debt for the firm frame): = -$15.500B"
    f11 = pack_facts.from_text(t11)
    assert f11["net_debt_b"] == -15.5

    # 13. Net debt rounds to 0.000
    t12 = "NET DEBT (default net_debt for the firm frame): = -$0.000B"
    f12 = pack_facts.from_text(t12)
    assert f12["net_debt_b"] == 0.0

    # 14. Terminal default printed and anchor only
    t13a = ("- Long-run nominal growth anchor for terminal_g: 3.50%\n"
            "- TERMINAL-GROWTH DEFAULT for this name: 2.50% — next-FY revenue growth is below anchor")
    f13a = pack_facts.from_text(t13a)
    assert f13a["terminal_g_default"] == 0.025

    t13b = "- Long-run nominal growth anchor for terminal_g: 3.50%"
    f13b = pack_facts.from_text(t13b)
    assert f13b["terminal_g_default"] == 0.035

    # 15. Owner earnings fallback token
    t14 = "- OWNER EARNINGS (default base_cf): $1.500B (owner_earnings_source: 3y_avg_ni+3y_avg_capex)"
    f14 = pack_facts.from_text(t14)
    assert f14["owner_earnings_source"] == "3y_avg_ni+3y_avg_capex"

    # 16. Share count of 0
    t15 = "- Shares outstanding: 0"
    f15 = pack_facts.from_text(t15)
    assert f15["shares_outstanding"] == 0.0

    # 17. Each key absent
    t16 = "Plain text with no financial pack data."
    f16 = pack_facts.from_text(t16)
    expected_empty = pack_facts.empty()
    expected_empty["source"] = "text"
    assert f16 == expected_empty


# ---- Case 3: build_pack branch coverage via monkeypatches --------------------

def test_build_pack_branch_net_debt(screener_data_stub, frozen_env, monkeypatch):
    """Monkeypatch fundamentals_history so effective debt exceeds cash -> net debt branch."""
    real_load_json = rs2_data.load_json

    def fake_load_json(p):
        data = real_load_json(p)
        if isinstance(data, dict) and "fundamentals_history" in str(p):
            d = copy.deepcopy(data)
            ticker_data = d.get("tickers", {}).get("GEV", {})
            for yr in ticker_data:
                ticker_data[yr]["lt_debt"] = 50e9
                ticker_data[yr]["cash"] = 1e9
            return d
        if isinstance(data, dict) and "financials" in str(p):
            d = copy.deepcopy(data)
            d["Total_Cash"] = 1e9
            d["Total_Debt"] = 50e9
            return d
        return data

    monkeypatch.setattr(rs2_data, "load_json", fake_load_json)
    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["net_debt_b"] > 0, f"Expected positive net debt, got {pack.facts['net_debt_b']}"
    from_text = pack_facts.from_text(str(pack))
    assert pack_facts.parity(pack.facts, from_text) == []


def test_build_pack_branch_terminal_default_below_anchor(screener_data_stub, frozen_env, monkeypatch):
    """Monkeypatch terminal_default to return a value below the anchor."""
    import consensus_reference
    monkeypatch.setattr(
        consensus_reference, "revenue_growth_next_fy",
        lambda *a, **k: 0.02
    )
    monkeypatch.setattr(
        consensus_reference, "terminal_default",
        lambda anchor, be, rev_g2, med5: (0.0215, "below anchor")
    )
    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["terminal_g_default"] == 0.0215
    from_text = pack_facts.from_text(str(pack))
    assert pack_facts.parity(pack.facts, from_text) == []


def test_build_pack_branch_owner_earnings_fallback_token(screener_data_stub, frozen_env, monkeypatch):
    """Monkeypatch fundamentals_ttm to have capex=None, forcing fallback to FY capex."""
    real_load_json = rs2_data.load_json

    def fake_load_json(p):
        data = real_load_json(p)
        if isinstance(data, dict) and "fundamentals_ttm" in str(p):
            d = copy.deepcopy(data)
            ttm_gev = d.get("tickers", {}).get("GEV", {})
            if "fields" in ttm_gev and ttm_gev["fields"]:
                ttm_gev["fields"]["capex"] = None
            return d
        return data

    monkeypatch.setattr(rs2_data, "load_json", fake_load_json)
    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["owner_earnings_source"] == "ttm_ni+fy_capex"
    from_text = pack_facts.from_text(str(pack))
    assert pack_facts.parity(pack.facts, from_text) == []


def test_build_pack_branch_reference_outside_fence(screener_data_stub, frozen_env, monkeypatch):
    """Revision 18 (brief 1.5): a reference outside the street-target fence prints its number, the fence and "a level check
    only", and the facts keep the value with the status flag. The synthetic history gives a valued reference; the fence is
    forced."""
    from test_throughcycle_reference import _synthetic_pack
    monkeypatch.setattr(cap, "_reference_outside_fence", lambda v, b: ("above", (50.0, 150.0)))
    pack = _synthetic_pack(monkeypatch)
    f = pack.facts
    assert f["reference_status"] == "outside_fence_above"
    assert isinstance(f["consensus_implied_value"], float) and f["consensus_implied_value"] > 0
    line = next(l for l in str(pack).splitlines() if "CONSENSUS-IMPLIED VALUE (reference" in l)
    assert f"${f['consensus_implied_value']:,.2f} per share" in line
    assert line.endswith("| outside the street-target fence [$50.00, $150.00] (0.5\u00d7 the lowest and 2\u00d7 the highest analyst "
                         "target, each discounted by 10%) \u2014 read it as a level check only")
    assert "not used" not in line and "not a credible summary" not in str(pack)
    # the facts the reference derives are kept (the desk's default inputs equal the reference); the desk reads the status
    assert f["levels"].get("year2") and f["long_run"]["e5"] is not None and f["reference_base_b"] is not None
    from_text = pack_facts.from_text(str(pack))
    assert pack_facts.parity(f, from_text) == []
    assert from_text["reference_status"] == "outside_fence_above" and from_text["consensus_implied_value"] == f["consensus_implied_value"]


# ---- Case 4: Consumer equivalence --------------------------------------------

TEXT_1 = """## SECTION 1.5 - CAPITAL-MARKET ANCHORS
- COE ANCHOR for this name: rf 4.00% + adjusted loading 1.000× implied ERP 5.00% = 9.00%
- Long-run nominal growth anchor for terminal_g: 3.00%
- TERMINAL-GROWTH DEFAULT for this name: 2.50%

## SECTION 2 - CAPITAL STRUCTURE
- Shares outstanding: 500,000,000

## SECTION 5 - HISTORICAL OPERATING RESULTS
| Year | Revenue | Interest Expense |
| 2024 | $10.0B | $0.500B |
| 2025 | $12.0B | $0.600B |

## SECTION 6 - NET DEBT
- [Arithmetic] NET DEBT (net_debt for the firm frame): = $5.000B

## SECTION 8 - EXPECTATIONS
CONSENSUS-IMPLIED VALUE (reference, not a forecast): $120.00 per share
Consensus cash-flow levels: year 1 $1.500B, year 2 $2.000B
Bull year 2 $2.500B and Bear year 2 $1.200B
BASE WINDOW CHECK: base_window_gap +18%
On the TTM window the consensus path is worth $110.00 per share, year-2 cash-flow level $1.800B
"""

TEXT_2 = """## SECTION 1.5 - CAPITAL-MARKET ANCHORS
- COE ANCHOR for this name: rf 4.00% + adjusted loading 1.000× implied ERP 5.00% = 9.00%
- Long-run nominal growth anchor for terminal_g: 3.00%

## SECTION 2 - CAPITAL STRUCTURE
- Shares outstanding: 200,000,000

## SECTION 3 - TRAILING TWELVE MONTHS
- OWNER EARNINGS (default base_cf): $2.000B (owner_earnings_source: ttm_ni+fy_capex)

## SECTION 6 - NET DEBT
- [Arithmetic] NET DEBT (net_debt for the firm frame): = -$3.000B

## SECTION 8 - EXPECTATIONS
- CONSENSUS-IMPLIED VALUE: not used — the consensus path carried forward lands above the fence (reference_status: outside_fence_above)
"""

TEXT_3 = """## SECTION 1.5 - CAPITAL-MARKET ANCHORS
- COE ANCHOR for this name: not available
- Long-run nominal growth anchor for terminal_g: not available

## SECTION 8 - EXPECTATIONS
CONSENSUS-IMPLIED VALUE (reference, not a forecast): not available
"""


@pytest.mark.parametrize("pack_text", ["GEV_FIXTURE", TEXT_1, TEXT_2, TEXT_3])
def test_consumer_equivalence(pack_text, screener_data_stub, frozen_env):
    if pack_text == "GEV_FIXTURE":
        pack_text = str(cap.build_pack("GEV", include_research=False))

    facts = pack_facts.from_text(pack_text)

    scorecard = {
        "base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0,
        "base_cf_used": 1.5, "stage1_growth_path": [0.10, 0.10, 0.08, 0.06, 0.05],
        "coe_used": 0.09,
    }
    enrich = {"estimates": {"0y": {"eps": {"analysts": 10}}, "+1y": {"eps": {"analysts": 10}}}}
    desk_info = {"desk_calls": 1, "desk_iv_match": True, "desk_share_implausible": False}

    # 1. (reference_window left the harness in revision 17 with the nearer-window choice; consensus_ratios below
    #    reads the same fiscal-year reference and level)

    # 2. consensus_ratios
    res2_text = cv.consensus_ratios(scorecard, enrich_data=enrich, pack_text=pack_text)
    res2_facts = cv.consensus_ratios(scorecard, enrich_data=enrich, pack_text=None, facts=facts)
    assert res2_text == res2_facts

    # 3. scenario_checks
    res3_text = cv.scenario_checks(None, scorecard, enrich_data=enrich, pack_text=pack_text, price=100.0)
    res3_facts = cv.scenario_checks(None, scorecard, enrich_data=enrich, pack_text=None, price=100.0, facts=facts)
    assert res3_text == res3_facts

    # 4. check_sample_harness_rules
    res4_text = cv.check_sample_harness_rules(
        scorecard=scorecard, price=100.0, desk_info=desk_info,
        enrich_data=enrich, momentum_state={}, pack_text=pack_text
    )
    res4_facts = cv.check_sample_harness_rules(
        scorecard=scorecard, price=100.0, desk_info=desk_info,
        enrich_data=enrich, momentum_state={}, pack_text=None, facts=facts
    )
    assert res4_text == res4_facts

    # 5. extract_desk_snapshot_metrics
    res5_text = cv.extract_desk_snapshot_metrics(
        snapshot=[], base_iv=120.0, coe_used=0.09, ticker="GEV",
        scorecard=scorecard, pack=pack_text
    )
    res5_facts = cv.extract_desk_snapshot_metrics(
        snapshot=[], base_iv=120.0, coe_used=0.09, ticker="GEV",
        scorecard=scorecard, pack=None, facts=facts
    )
    assert res5_text == res5_facts


# ---- Case 5: main() with --pack-file -----------------------------------------

MEMO = (
    "SECTION 0. EXECUTIVE VERDICT\n"
    + "\n".join(f"  detail line {n} of the institutional memorandum." for n in range(400))
    + "\nSECTION 12. MACHINE CONTRACT\n"
    "```json:underwriting\n"
    '{"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0, "base_probability": 0.5, '
    '"bull_probability": 0.3, "bear_probability": 0.2, "conviction_score": 10, '
    '"business_quality_moat": 3, "kelly_fraction_pct": 2.0, '
    '"base_cf_used": 1.0, "base_cf_basis": "other"}\n'
    "```\n"
)


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False


def _ollama_payload():
    return {"message": {"content": MEMO}, "done_reason": "stop",
            "eval_count": 500, "prompt_eval_count": 100}


def test_main_pack_file_with_sidecar(monkeypatch, tmp_path, screener_data_stub):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_ollama_payload()))

    frozen_dir = tmp_path / "frozen_with_sidecar"
    frozen_dir.mkdir(parents=True)
    pack_file = frozen_dir / "_pack.md"
    pack_file.write_text(TEXT_1, encoding="utf-8")

    sidecar_facts = pack_facts.from_text(TEXT_1)
    sidecar_facts["source"] = "build"
    pack_facts.write_sidecar(frozen_dir, sidecar_facts)

    out_dir = tmp_path / "out1"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--pack-file", str(pack_file), "--out-dir", str(out_dir)
    ])
    cv.main()

    run_dirs = list(out_dir.glob("GEV_*"))
    assert len(run_dirs) == 1
    d = run_dirs[0]

    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert doc["pack_facts_source"] == "sidecar"
    assert doc["pack_facts_version"] == pack_facts.FACTS_VERSION
    assert "pack_facts_parity" not in doc, "pack_facts_parity must be stamped on build only"

    assert (d / "_pack_facts.json").exists(), "Run dir must contain _pack_facts.json"
    written_facts = json.loads((d / "_pack_facts.json").read_text(encoding="utf-8"))
    assert written_facts["source"] == "build"
    assert written_facts["shares_outstanding"] == 500000000.0


def test_main_pack_file_without_sidecar(monkeypatch, tmp_path, screener_data_stub):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_ollama_payload()))

    frozen_dir = tmp_path / "frozen_no_sidecar"
    frozen_dir.mkdir(parents=True)
    pack_file = frozen_dir / "_pack.md"
    pack_file.write_text(TEXT_1, encoding="utf-8")

    out_dir = tmp_path / "out2"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--pack-file", str(pack_file), "--out-dir", str(out_dir)
    ])
    cv.main()

    run_dirs = list(out_dir.glob("GEV_*"))
    assert len(run_dirs) == 1
    d = run_dirs[0]

    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert doc["pack_facts_source"] == "text"
    assert doc["pack_facts_version"] == pack_facts.FACTS_VERSION
    assert "pack_facts_parity" not in doc, "pack_facts_parity must be stamped on build only"

    assert (d / "_pack_facts.json").exists(), "Run dir must contain _pack_facts.json"
    written_facts = json.loads((d / "_pack_facts.json").read_text(encoding="utf-8"))
    assert written_facts["source"] == "text"
    assert written_facts["shares_outstanding"] == 500000000.0

"""Phase 4 E10 (F1 of the 2026-09-24 Fable cross-review): cash-flow growth vs consensus EARNINGS,
the consensus-implied reference value, and the harness flags built on them.

The AMD probe grew a $5.1B cash-flow base at consensus REVENUE growth (+46.9%, +73.1%): its
"consensus plays out" case reached $13.0B in year 2 against consensus next-FY net income of
$25.4B, and it valued AMD at $378.92 against a $614.61 price.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import consensus_reference as cref  # noqa: E402
import consensus_valuation as cv  # noqa: E402

AMD_EST = {
    "0y": {"revenue": {"analysts": 49, "growth": 0.4687},
           "eps": {"avg": 7.57578, "low": 7.0, "high": 8.2, "analysts": 49, "growth": 0.8167, "year_ago": 4.17}},
    "+1y": {"revenue": {"analysts": 52, "growth": 0.73120004},
            "eps": {"avg": 15.57069, "low": 9.6, "high": 20.25, "analysts": 50, "growth": 1.0553, "year_ago": 7.57578}},
}
AMD_SHARES = 1_632_475_042


def test_consensus_earnings_growth_usable_and_not():
    assert cref.consensus_earnings_growth(AMD_EST) == (0.8167, 1.0553, None)
    trough = {"0y": {"eps": {"analysts": 9, "growth": 4.0, "year_ago": 0.2}}, "+1y": {"eps": {"analysts": 9, "growth": 0.3}}}
    assert cref.consensus_earnings_growth(trough)[2].startswith("EPS growth +400% for 0y is off a trough")
    loss = {"0y": {"eps": {"analysts": 5, "growth": 0.5, "year_ago": -1.2}}, "+1y": {"eps": {"analysts": 5, "growth": 0.4}}}
    assert "not positive" in cref.consensus_earnings_growth(loss)[2]
    none = {"0y": {"eps": {"analysts": 0}}, "+1y": {"eps": {"analysts": 0}}}
    assert cref.consensus_earnings_growth(none)[2] == "no EPS estimate for 0y"
    assert cref.consensus_earnings_growth(None)[2] == "no consensus estimates"


def test_amd_reference_path_and_value():
    r = cref.build(7.578e9, AMD_EST, 0.1045, 0.0375, AMD_SHARES, 0.122)
    assert [round(g, 3) for g in r["path"]] == [0.817, 1.055, 0.528, 0.325, 0.122]
    assert abs(r["value"] - 520.02) < 0.5
    # year 2 now sits with consensus earnings ($25.4B), not at half of it
    assert 7.578 * (1 + r["c1"]) * (1 + r["c2"]) > 25.0


def test_reference_value_matches_the_closed_form():
    # no growth and no terminal growth: a perpetuity, base / coe
    assert abs(cref.reference_value(100.0, [0, 0, 0, 0, 0], 0.10, 0.0, 10.0) - 100.0) < 1e-9
    assert cref.reference_value(100.0, [0.1] * 5, 0.03, 0.03, 10.0) is None     # coe must exceed g
    assert cref.build(-5.0, AMD_EST, 0.1, 0.03, 10.0, 0.1)["reason"] == "owner-earnings base is not positive"
    assert "cost-of-equity anchor missing" in cref.build(5.0, AMD_EST, None, 0.03, 10.0, 0.1)["reason"]


def _probe_pack(civ=520.02):
    return ("## GROWTH BASE RATES\n"
            "- 5y sustained growth, this size bucket (n=1641): >=10%/yr 17.2%, median 4.3%, p90 14.0%\n"
            "- Given the growth just delivered (+34.3% YoY revenue, FY2025, bucket 25-40%): realized next-5y "
            "revenue CAGR across the corpus (n=1115) - p25 3.4%, median 12.2%, p75 21.8%, p90 30.1%\n"
            f"- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): ${civ:,.2f} per share \u2014 ...\n")


def _flags(sc, pack=None):
    return cv.check_sample_harness_rules(sc, 614.61, desk_info={"desk_per_share_ivs": [sc.get("base_iv")]},
                                         enrich_data={"estimates": AMD_EST}, pack_text=pack or _probe_pack())[2]


def test_harness_flags_the_amd_probe_shape():
    probe = {"base_iv": 378.92, "stage1_growth_path": [0.469, 0.731, 0.5, 0.35, 0.25],
             "guidance_deviation_reason": None}
    f = _flags(probe)
    assert "years12_off_consensus_earnings" in f           # 2.54x vs 3.73x over two years
    assert "base_far_from_consensus_implied" in f          # 378.92 / 520.02 = 0.73
    assert "years35_above_base_rate_p90" in f              # ~36% a year vs conditional p90 30.1%


def test_harness_is_quiet_when_the_base_follows_consensus():
    sc = {"base_iv": 540.0, "stage1_growth_path": [0.80, 1.00, 0.50, 0.30, 0.12], "guidance_deviation_reason": ""}
    f = _flags(sc)
    assert not {"years12_off_consensus_earnings", "base_far_from_consensus_implied",
                "years35_above_base_rate_p90"} & set(f)


def test_a_stated_reason_clears_the_consensus_flags_but_not_the_base_rate_note():
    sc = {"base_iv": 378.92, "stage1_growth_path": [0.469, 0.731, 0.5, 0.35, 0.25],
          "guidance_deviation_reason": "Consensus EPS includes a one-time licence gain; I use revenue growth."}
    f = _flags(sc)
    assert "years12_off_consensus_earnings" not in f and "base_far_from_consensus_implied" not in f
    assert "years35_above_base_rate_p90" in f


def test_no_reference_in_the_pack_means_no_reference_flag():
    probe = {"base_iv": 378.92, "stage1_growth_path": [0.469, 0.731, 0.5, 0.35, 0.25]}
    f = cv.check_sample_harness_rules(probe, 614.61, enrich_data={"estimates": AMD_EST},
                                      pack_text="- CONSENSUS-IMPLIED VALUE: not available \u2014 x")[2]
    assert "base_far_from_consensus_implied" not in f and "years12_off_consensus_earnings" in f


def test_the_pack_says_when_there_is_no_reference(screener_data_stub):
    import capability_test as cap
    pack = str(cap.build_pack("GEV"))                      # the GEV fixture holds no estimates
    assert "- CONSENSUS-IMPLIED VALUE: not available" in pack


def test_the_pack_prints_the_reference_with_estimates(screener_data_stub, monkeypatch):
    import capability_test as cap
    import rs2_data
    orig = rs2_data.load_json
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00", "estimates": AMD_EST}
    monkeypatch.setattr(rs2_data, "load_json", lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p) else orig(p))
    pack = str(cap.build_pack("GEV"))
    line = next(l for l in pack.splitlines() if "CONSENSUS-IMPLIED VALUE" in l)
    # a value when the fixture holds every input, otherwise the named missing input - never silence
    assert "per share" in line or "not available —" in line

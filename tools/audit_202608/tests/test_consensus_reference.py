"""Phase 4 E10 (F1 of the 2026-09-24 Fable cross-review): cash-flow growth vs consensus EARNINGS,
the consensus-implied reference value, and the harness flags built on them.

The AMD probe grew a $5.1B cash-flow base at consensus REVENUE growth (+46.9%, +73.1%): its
"consensus plays out" case reached $13.0B in year 2 against consensus next-FY net income of
$25.4B, and it valued AMD at $378.92 against a $614.61 price.
"""
import math
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
# Revision 17: the reference's long run needs the company's record; with RONIC_T = +inf, no cycle, no working
# capital and base net income = owner earnings (D&A = capex) it reduces to revision 16's arithmetic, so the
# tests below that pin revision-16 numbers pass these inputs and keep their assertions.
REDUCTION = {"R_tc": math.inf, "ronic_t": math.inf, "cycle": False, "m_tc": None, "nwc_intensity": None,
             "stamps": []}


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
    r = cref.build(7.578e9, AMD_EST, 0.1045, 0.0375, AMD_SHARES, 0.122, record=REDUCTION, base_ni=7.578e9)
    assert [round(g, 3) for g in r["path"]] == [0.817, 1.055, 0.528, 0.325, 0.122]
    assert abs(r["value"] - 520.02) < 0.5
    # year 2 now sits with consensus earnings ($25.4B), not at half of it
    assert 7.578 * (1 + r["c1"]) * (1 + r["c2"]) > 25.0


def test_reference_value_matches_the_closed_form():
    # no growth and no terminal growth: a perpetuity, base / coe
    assert abs(cref.reference_value(100.0, [0, 0, 0, 0, 0], 0.10, 0.0, 10.0) - 100.0) < 1e-9
    assert cref.reference_value(100.0, [0.1] * 5, 0.03, 0.03, 10.0) is None     # coe must exceed g
    # whole-book test (LIVN): a base that is not positive goes to the EPS levels, which need D&A and capex
    assert cref.build(-5.0, AMD_EST, 0.1, 0.03, 10.0, 0.1)["reason"] == (
        "the fiscal-year owner-earnings base is not positive; D&A or capex missing")
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


def test_ratios_are_stamped_even_when_a_reason_silences_the_flags():
    sc = {"base_iv": 378.92, "stage1_growth_path": [0.469, 0.731, 0.5, 0.35, 0.25],
          "guidance_deviation_reason": "any sentence at all"}
    r = cv.consensus_ratios(sc, {"estimates": AMD_EST}, _probe_pack())
    # revision 17: the window choice is gone, so reference_window_used and reference_window_value are no longer stamped
    assert r == {"years12_ratio": 0.681, "base_to_civ": 0.729, "consensus_implied_value": 520.02,
                 "base_window_gap": None}
    assert cv.consensus_ratios({}, None, None) == {"years12_ratio": None, "base_to_civ": None,
                                                   "consensus_implied_value": None,
                                                   "base_window_gap": None}


def test_the_medoid_summary_and_the_verdict_carry_the_ratios():
    stamp = {"years12_ratio": 0.681, "base_to_civ": 0.729, "consensus_implied_value": 520.02}
    runs = [{"sample": n, "iv": iv, "plausible": True, "truncated": False,
             "scorecard": dict(stamp, base_iv=iv)} for n, iv in ((1, 379.0), (2, 380.0), (3, 381.0))]
    _, summary = cv.select_medoid_scorecard(runs, 614.61)
    assert {k: summary[k] for k in stamp} == stamp
    import depth_pipeline as dp
    doc = {"ticker": "AMD", "price": 614.61, "samples_run": 3, "converged": True, "spread_pct": 0.5,
           "median_iv": 380.0, "runs": runs, "scorecard": dict(summary, invalidation_rules=[])}
    v = dp.band_verdict(doc)
    assert {k: v.get(k) for k in stamp} == stamp


MU_EST = {"0y": {"revenue": {"analysts": 30, "growth": 2.4782},
                 "eps": {"avg": 73.57183, "analysts": 30, "growth": 7.8748, "year_ago": 8.29}},
          "+1y": {"revenue": {"analysts": 30, "growth": 0.908},
                  "eps": {"avg": 159.12122, "analysts": 30, "growth": 1.1628, "year_ago": 73.57183}}}
LIND_EST = {"0y": {"revenue": {"analysts": 6, "growth": 0.1334},
                   "eps": {"avg": 0.18083, "analysts": 6, "growth": 4.4444, "year_ago": -0.0525}},
            "+1y": {"revenue": {"analysts": 6, "growth": 0.1025},
                    "eps": {"avg": 0.56485, "analysts": 6, "growth": 2.1237, "year_ago": 0.18083}}}


def test_mu_trough_uses_consensus_eps_levels():
    """Fable check: MU's +787% is a trough recovery, not a growth rate; levels are well defined."""
    r = cref.build(5e9, MU_EST, 0.10, 0.0375, 1.12e9, 0.12, da=8e9, capex=14e9)
    assert r["method"] == "levels" and r["value"] and r["value"] > 0
    assert r["flows"][0] == 73.57183 * 1.12e9 + 8e9 - 14e9
    assert r["flows"][1] == 159.12122 * 1.12e9 + 8e9 - 14e9
    line = cref.pack_line(r, 5e9, 0.10, 0.0375, lambda v: f"${v / 1e9:.3f}B")
    assert line.startswith("- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $")
    # S3 C (brief §5.6): pack_line's clauses are now lower-cased and pipe-separated.
    assert "consensus EPS growth is unusable (EPS growth +787% for 0y is off a trough" in line


def test_lind_negative_base_uses_levels_and_the_harness_reads_it():
    r = cref.build(-2e7, LIND_EST, 0.11, 0.0375, 5.5e7, 0.08, da=6e7, capex=5e7)
    assert r["method"] == "levels" and r["value"] > 0
    line = cref.pack_line(r, -2e7, 0.11, 0.0375, lambda v: f"${v / 1e9:.3f}B")
    civ, _ = cv._pack_reference(line)
    assert civ == round(r["value"], 2)


def test_levels_need_a_positive_next_year_and_the_inputs():
    bad = {k: {"eps": dict(v["eps"], avg=-0.5)} for k, v in LIND_EST.items()}
    r = cref.build(1e7, bad, 0.11, 0.0375, 5.5e7, 0.08, da=6e7, capex=5e7)
    assert r["value"] is None and "no positive next-FY EPS level" in r["reason"]
    r = cref.build(1e7, LIND_EST, 0.11, 0.0375, 5.5e7, 0.08)            # no D&A / capex
    assert r["value"] is None and "D&A or capex missing" in r["reason"]


def test_no_revenue_estimate_fades_from_the_median_not_from_eps_growth():
    """Fable check: FSM has no next-FY revenue estimate; the old fallback started the fade at EPS
    growth, the more generous choice exactly when data was thinner."""
    est = {"0y": {"eps": {"analysts": 5, "growth": 1.1183, "year_ago": 0.66}},
           "+1y": {"eps": {"analysts": 5, "growth": 0.2668, "year_ago": 1.398}}}
    r = cref.build(4e8, est, 0.10, 0.0375, 3.07e8, 0.08, record=REDUCTION, base_ni=4e8)
    assert r["method"] == "growth" and [round(g, 4) for g in r["path"][2:]] == [0.08, 0.08, 0.08]


def test_next_fy_revenue_growth_and_flag():
    # Helper on a table like the one in MO_pack.md (+0.9% -> 0.009)
    table_pack = (
        "- CONSENSUS ESTIMATES   [yfinance, fetched 2026-09-26; sell-side estimates, not company guidance]\n"
        "| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | EPS analysts | growth |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| current FY | $20.577B | $20.429B | $20.801B | 12 | +2.2% | $5.68 | $5.63 | $5.72 | 12 | +4.7% |\n"
        "| next FY | $20.759B | $20.525B | $21.116B | 12 | +0.9% | $5.86 | $5.67 | $6.09 | 14 | +3.3% |\n"
    )
    assert cv.next_fy_revenue_growth(table_pack) == 0.009

    # On a pack without the table -> None
    assert cv.next_fy_revenue_growth("No table here") is None

    # Flag fires for years 3-5 of 0.030/0.028/0.025 against 0.009
    sc_fire = {"base_iv": 50.0, "stage1_growth_path": [0.02, 0.01, 0.030, 0.028, 0.025]}
    f1 = cv.check_sample_harness_rules(sc_fire, 50.0, desk_info={"desk_per_share_ivs": [50.0]},
                                       pack_text=table_pack)[2]
    assert "years35_above_revenue_cap_without_reason" in f1

    # Flag does not fire for 0.009/0.009/0.009
    sc_quiet1 = {"base_iv": 50.0, "stage1_growth_path": [0.02, 0.01, 0.009, 0.009, 0.009]}
    f2 = cv.check_sample_harness_rules(sc_quiet1, 50.0, desk_info={"desk_per_share_ivs": [50.0]},
                                       pack_text=table_pack)[2]
    assert "years35_above_revenue_cap_without_reason" not in f2

    # Flag does not fire for 0.013/0.012/0.012
    sc_quiet2 = {"base_iv": 50.0, "stage1_growth_path": [0.02, 0.01, 0.013, 0.012, 0.012]}
    f3 = cv.check_sample_harness_rules(sc_quiet2, 50.0, desk_info={"desk_per_share_ivs": [50.0]},
                                       pack_text=table_pack)[2]
    assert "years35_above_revenue_cap_without_reason" not in f3


def test_terminal_default_unit_cases():
    # rev_g2 0.009, median 0.043, anchor 0.0375, breakeven 0.0234 -> 0.0234
    val, reason = cref.terminal_default(0.0375, 0.0234, 0.009, 0.043)
    assert val == 0.0234 and reason is not None

    # rev_g2 0.030 -> 0.030
    val, reason = cref.terminal_default(0.0375, 0.0234, 0.030, 0.043)
    assert val == 0.030 and reason is not None

    # rev_g2 0.0555 -> 0.0375
    val, reason = cref.terminal_default(0.0375, 0.0234, 0.0555, 0.043)
    assert val == 0.0375 and reason is None

    # rev_g2 None -> 0.0375
    val, reason = cref.terminal_default(0.0375, 0.0234, None, 0.043)
    assert val == 0.0375 and reason is None

    # breakeven None -> 0.0375 with a reason saying the floor is not available
    val, reason = cref.terminal_default(0.0375, None, 0.009, 0.043)
    assert val == 0.0375 and "floor is not available" in (reason or "")


def test_pack_line_printed_tail_says_default_when_it_differs():
    ref = {"value": 100.0, "method": "growth", "path": [0.1] * 5, "c1": 0.1, "c2": 0.1,
           "levels": (10.0, 11.0), "range": None, "stub_months": None, "base_label": None,
           "levels_reason": None}
    # When anchor is None or equal: "terminal-growth anchor"
    line_anchor = cref.pack_line(ref, 10.0, 0.10, 0.0375, lambda v: f"${v:.1f}")
    assert "then a 5-year fade to the terminal-growth anchor 3.75%" in line_anchor

    # When anchor is passed and differs: "terminal-growth default"
    line_def = cref.pack_line(ref, 10.0, 0.10, 0.0234, lambda v: f"${v:.1f}", anchor=0.0375)
    assert "then a 5-year fade to the terminal-growth default 2.34%" in line_def



def test_years35_above_revenue_cap_is_cleared_by_a_guidance_deviation_reason():
    table_pack = ("| period | revenue avg | low | high | analysts | growth | EPS avg |\n"
                  "| next FY | $20.759B | $20.525B | $21.116B | 12 | +0.9% | $5.86 |\n")
    sc = {"base_iv": 50.0, "stage1_growth_path": [0.02, 0.01, 0.030, 0.028, 0.025],
          "guidance_deviation_reason": "dated evidence: raised multi-year guidance (8-K 2026-08-06)"}
    f = cv.check_sample_harness_rules(sc, 50.0, desk_info={"desk_per_share_ivs": [50.0]}, pack_text=table_pack)[2]
    assert "years35_above_revenue_cap_without_reason" not in f

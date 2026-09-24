"""Phase 4 E12 (joint AMD review with Fable, 2026-09-25): the share count, net debt and bull/bear
years 1-2 behind every published scenario, checked against the pack.

AMD (c) s3 added OpenAI's 160M warrant to every scenario, its bear case included; the existing
share check (>= 10%) missed its 9.8%. Four samples gave four net-debt values for one filed fact.
Bull and bear were unchecked while the base was pinned.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import consensus_valuation as cv  # noqa: E402

EST = {"0y": {"eps": {"avg": 7.57578, "low": 7.0, "high": 8.2, "analysts": 49, "growth": 0.8167, "year_ago": 4.17}},
       "+1y": {"eps": {"avg": 15.57069, "low": 9.6, "high": 20.25, "analysts": 50, "growth": 1.0553,
                       "year_ago": 7.57578}}}
PACK = ("- Shares outstanding: 1,632,475,042   [source: vendor financials]\n"
        "- [Arithmetic] NET DEBT (default net_debt for the firm frame): total debt $2.348B − cash $5.539B "
        "− short-term investments $4.139B = -$7.330B (negative = net cash). Use it as net_debt in the firm "
        "frame unless net_debt_reason says why.\n")


def _snapshot(tmp_path, shares_top, bear_shares=None, frame="equity", net_debt=None):
    scenarios = [{"name": "Base", "explicit_growth": [0.817, 1.055, 0.528, 0.325, 0.122]},
                 {"name": "Bull", "explicit_growth": [0.9664, 1.4695, 0.60, 0.40, 0.15]},
                 {"name": "Bear", "explicit_growth": [0.679, 0.371, -0.10, 0.02, 0.06]}]
    if bear_shares is not None:
        scenarios[2]["shares_diluted"] = bear_shares
    params = {"price": 609.43, "base_cf": 7.578, "shares_diluted": shares_top, "valuation_frame": frame,
              "scenarios": scenarios}
    if net_debt is not None:
        params["net_debt"] = net_debt
    call = {"tool": "run_financial_model", "params": params,
            "scenario_dcfs": [{"name": "Base", "dcf": {"per_share_iv": 464.47}},
                              {"name": "Bull", "dcf": {"per_share_iv": 933.25}},
                              {"name": "Bear", "dcf": {"per_share_iv": 70.69}}]}
    (tmp_path / "_research_snapshot.json").write_text(json.dumps({"calls": [call]}), encoding="utf-8")
    return tmp_path


def _sc(**kw):
    return dict({"base_iv": 464.47, "bull_iv": 933.25, "bear_iv": 70.69, "verdict_label": "overvalued"}, **kw)


def test_the_amd_s3_warrant_in_every_scenario_is_flagged(tmp_path):
    flags, st = cv.scenario_checks(_snapshot(tmp_path, 1.7925), _sc(), {"estimates": EST}, PACK, 609.43)
    assert st["base_shares_ratio"] == st["bull_shares_ratio"] == st["bear_shares_ratio"] == 1.098
    assert "shares_off_pack_without_reason" in flags and "dilution_in_bear" in flags


def test_contingent_dilution_only_where_it_vests_with_a_reason_is_clean(tmp_path):
    snap = _snapshot(tmp_path, 1.7925, bear_shares=1.6325)
    flags, st = cv.scenario_checks(snap, _sc(shares_reason="OpenAI warrant, vests on GW milestones"),
                                   {"estimates": EST}, PACK, 609.43)
    assert st["bear_shares_ratio"] == 1.0 and "dilution_in_bear" not in flags
    assert "shares_off_pack_without_reason" not in flags


def test_bull_and_bear_years12_are_stamped_against_the_consensus_high_low_path(tmp_path):
    _, st = cv.scenario_checks(_snapshot(tmp_path, 1.6325), _sc(), {"estimates": EST}, PACK, 609.43)
    assert st["bull_years12_ratio"] == 1.0       # 20.25 / 4.17, reached exactly
    assert st["bear_years12_ratio"] == 1.0       # 9.60 / 4.17, reached exactly


def test_net_debt_off_the_filed_default_needs_a_reason_in_the_firm_frame(tmp_path):
    flags, st = cv.scenario_checks(_snapshot(tmp_path, 1.6325, frame="firm", net_debt=-7.33), _sc(),
                                   {"estimates": EST}, PACK, 609.43)
    assert st["desk_frame"] == "firm" and st["desk_net_debt"] == -7.33
    assert "net_debt_off_default_without_reason" not in flags
    flags, _ = cv.scenario_checks(_snapshot(tmp_path, 1.6325, frame="firm", net_debt=-1.692), _sc(),
                                  {"estimates": EST}, PACK, 609.43)
    assert "net_debt_off_default_without_reason" in flags
    flags, _ = cv.scenario_checks(_snapshot(tmp_path, 1.6325, frame="firm", net_debt=-1.692),
                                  _sc(net_debt_reason="Excludes restricted cash"), {"estimates": EST}, PACK, 609.43)
    assert "net_debt_off_default_without_reason" not in flags
    assert cv._pack_net_debt_b(PACK) == -7.33


def test_a_self_label_that_contradicts_the_numbers_is_flagged_per_sample(tmp_path):
    flags, _ = cv.scenario_checks(_snapshot(tmp_path, 1.6325), _sc(base_iv=509.99, verdict_label="hold"),
                                  {"estimates": EST}, PACK, 609.43)
    assert "report_verdict_mismatch_sample" in flags


def test_no_snapshot_means_no_stamps_and_no_crash(tmp_path):
    flags, st = cv.scenario_checks(tmp_path, _sc(), None, None, None)
    assert flags == [] and all(v is None for k, v in st.items() if k != "bull_bear_anchor")
    assert st["bull_bear_anchor"] == "no consensus range (0 analysts)"


def test_the_pack_prints_one_net_debt_default(screener_data_stub):
    import capability_test as cap
    pack = str(cap.build_pack("GEV"))
    line = next(l for l in pack.splitlines() if "NET DEBT (default net_debt for the firm frame)" in l)
    assert "short-term investments" in line and cv._pack_net_debt_b(pack) is not None


def test_scenario_growth_is_read_from_the_scenario_not_the_top_level_base_path(tmp_path):
    """Real desk calls carry the base path as top-level explicit_growth and each scenario's own
    path as growth_rates; the desk result records what it applied. The first version of this
    check merged them and stamped the BASE path for bull and bear (dry run on AMD, 2026-09-25)."""
    params = {"price": 609.43, "base_cf": 7.578, "shares_diluted": 1.6325, "valuation_frame": "firm",
              "net_debt": -7.33, "explicit_growth": [0.817, 1.055, 0.528, 0.325, 0.122],
              "scenarios": [{"name": "Base", "growth_rates": [0.817, 1.055, 0.528, 0.325, 0.122]},
                            {"name": "Bull", "growth_rates": [0.9656, 1.6715, 0.55, 0.35, 0.18]},
                            {"name": "Bear", "growth_rates": [0.678, 0.2665, -0.1, 0.02, 0.06]}]}
    call = {"tool": "run_financial_model", "params": params, "scenario_dcfs": [
        {"name": "Base", "dcf": {"per_share_iv": 514.48, "explicit_growth": [0.817, 1.055, 0.528, 0.325, 0.122]}},
        {"name": "Bull", "dcf": {"per_share_iv": 842.15, "explicit_growth": [0.9656, 1.6715, 0.55, 0.35, 0.18]}},
        {"name": "Bear", "dcf": {"per_share_iv": 117.91, "explicit_growth": [0.678, 0.2665, -0.1, 0.02, 0.06]}}]}
    (tmp_path / "_research_snapshot.json").write_text(json.dumps({"calls": [call]}), encoding="utf-8")
    _, st = cv.scenario_checks(tmp_path, _sc(base_iv=514.48, bull_iv=842.15, bear_iv=117.91),
                               {"estimates": EST}, PACK, 609.43)
    assert st["bull_years12_ratio"] == 1.081 and st["bear_years12_ratio"] == 0.923



def test_one_analyst_gives_no_range_to_anchor_bull_and_bear(tmp_path):
    """Fable pre-(b) F1: LAMR and LIND have one next-FY analyst (high = low = average)."""
    one = {"0y": {"eps": {"avg": 6.056, "high": 6.056, "low": 6.056, "analysts": 1, "year_ago": 5.07}},
           "+1y": {"eps": {"avg": 6.48, "high": 6.48, "low": 6.48, "analysts": 1, "year_ago": 6.056}}}
    _, st = cv.scenario_checks(_snapshot(tmp_path, 1.6325), _sc(), {"estimates": one}, PACK, 609.43)
    assert st["bull_years12_ratio"] is None and st["bear_years12_ratio"] is None
    assert st["bull_bear_anchor"] == "no consensus range (1 analysts)"
    _, st = cv.scenario_checks(_snapshot(tmp_path, 1.6325), _sc(), {"estimates": EST}, PACK, 609.43)
    assert st["bull_bear_anchor"] == "consensus high/low"


def test_a_bull_and_base_with_the_same_value_are_matched_by_name(tmp_path):
    params = {"shares_diluted": 1.6325, "scenarios": [
        {"name": "Base", "growth_rates": [0.10, 0.10, 0.1, 0.1, 0.1]},
        {"name": "Bull", "growth_rates": [0.30, 0.30, 0.2, 0.2, 0.1]}]}
    call = {"tool": "run_financial_model", "params": params, "scenario_dcfs": [
        {"name": "Base", "dcf": {"per_share_iv": 500.0, "explicit_growth": [0.10, 0.10, 0.1, 0.1, 0.1]}},
        {"name": "Bull", "dcf": {"per_share_iv": 502.0, "explicit_growth": [0.30, 0.30, 0.2, 0.2, 0.1]}}]}
    inp = cv._desk_scenario_inputs([call], 502.0, role="bull")
    assert inp["name"] == "Bull" and inp["explicit_growth"][0] == 0.30
    inp = cv._desk_scenario_inputs([call], 500.0, role="base")
    assert inp["name"] == "Base"

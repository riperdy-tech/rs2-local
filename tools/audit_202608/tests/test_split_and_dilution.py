"""Revision 17, brief C4 (a split after the last filing) and C5 (the dilution factor is not applied twice)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))

import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import pack_facts  # noqa: E402
from test_review_b1_b4 import _byc, _gev_pack as _gev_pack_in  # noqa: E402
from test_terminal_and_frame import PACK, _dcf, _snapshot  # noqa: E402

PIPR_FILED = 17_785_000
PIPR_VENDOR = 70_670_291
GEV_EPS = 4.884e9 / 276e6          # the fixture's FY2025 net income / diluted shares


def _gev_pack(monkeypatch, *a, **k):
    """test_review_b1_b4's GEV pack, with its patches undone afterwards: it wraps rs2_data.load_json each time, so a
    second call in one test would inherit the first call's edits."""
    with monkeypatch.context() as m:
        return _gev_pack_in(m, *a, **k)


def _vendor(shares, eps):
    """A fin_edit: the vendor's share count and its (restated) diluted EPS for the latest filed fiscal year (brief F7)."""
    return lambda f: dict(f, Shares_Outstanding=shares,
                          Annual_Income_Statement=[dict(f["Annual_Income_Statement"][0], DilutedEPS=eps)]
                          + list(f["Annual_Income_Statement"][1:]))


def _h(*counts):
    """A filed history whose fiscal years end at 2025, one shares_diluted per year."""
    years = range(2025 - len(counts) + 1, 2026)
    return {str(y): {"shares_diluted": c} for y, c in zip(years, counts)}


# ---- C4: the detector -------------------------------------------------------------------------------------------

def test_piprs_final_test_inputs_are_a_4_for_1_split():
    s = cap._split_after_last_filing(PIPR_VENDOR, _h(17_500_000, 17_600_000, PIPR_FILED))
    assert s["k"] == 4 and s["reverse"] is False and s["multiplier"] == 4.0
    assert s["fy"] == 2025 and s["filed"] == PIPR_FILED and s["vendor"] == PIPR_VENDOR


def test_a_reverse_split_is_detected_with_a_multiplier_below_one():
    s = cap._split_after_last_filing(25_200_000, _h(100_000_000, 101_000_000))
    assert s["k"] == 4 and s["reverse"] is True and s["multiplier"] == 0.25


@pytest.mark.parametrize("k", [2, 3, 4, 5, 8, 10, 15, 20])
def test_every_k_is_found_within_3_percent_either_side(k):
    filed = 50_000_000
    for f in (1.0, 1.02, 0.98):
        assert cap._split_after_last_filing(filed * k * f, _h(filed))["k"] == k
        assert cap._split_after_last_filing(filed / (k * f), _h(filed))["k"] == k


@pytest.mark.parametrize("ratio", [1.0, 1.02, 1.5, 1.9, 2.15, 2.5, 6.1, 12.0, 25.0, 0.5 * 1.1])
def test_a_ratio_that_fits_no_k_is_not_a_split(ratio):
    # 1.9x is dilution, not a split; 6.1x is the ADS-unit shape
    assert cap._split_after_last_filing(50_000_000 * ratio, _h(50_000_000)) is None


def test_a_step_the_filed_series_already_shows_is_left_to_the_screeners_flag():
    # FY2024 100M -> FY2025 400M is the 4x step inside the filed series; the vendor's 1.6B is 4x the FY2025 count
    assert cap._split_after_last_filing(1_600_000_000, _h(100_000_000, 400_000_000)) is None
    assert cap._split_after_last_filing(400_000_000, _h(100_000_000, 200_000_000)) is None      # 2x step, 2x ratio
    # a step of another size between the last two years does not hide a 4x split after the filing
    assert cap._split_after_last_filing(1_200_000_000, _h(100_000_000, 300_000_000))["k"] == 4
    # a reverse step in the series is a reverse step: a forward split after it is not hidden
    assert cap._split_after_last_filing(400_000_000, _h(400_000_000, 100_000_000))["k"] == 4


def test_missing_zero_and_non_numeric_counts_are_not_a_split():
    assert cap._split_after_last_filing(None, _h(1e6)) is None
    assert cap._split_after_last_filing(0.0, _h(1e6)) is None                # 0.0 is a value, not a split
    assert cap._split_after_last_filing(4e6, {}) is None
    assert cap._split_after_last_filing(4e6, _h(None)) is None
    assert cap._split_after_last_filing(4e6, _h(0.0)) is None                 # a filed zero is no basis for a ratio
    assert cap._split_after_last_filing(4e6, _h(float("nan"))) is None
    assert cap._split_after_last_filing(float("nan"), _h(1e6)) is None


def test_the_latest_year_with_a_count_is_the_filed_count():
    # FY2025 holds no count: the ratio runs against FY2024's (the same year DATA 6B reports as filed_shares_fy)
    h = {"2024": {"shares_diluted": 20_000_000}, "2025": {"shares_diluted": None}}
    s = cap._split_after_last_filing(80_000_000, h)
    assert s["k"] == 4 and s["fy"] == 2024


# ---- C4 in the pack ---------------------------------------------------------------------------------------------

def _hist_pipr(counts=(17_500_000, 17_600_000, PIPR_FILED)):
    """GEV's fixture with its FY2023-25 diluted counts replaced by PIPR's and net income scaled to keep FY2025's EPS."""
    def edit(d):
        rows = d["tickers"]["GEV"]
        eps = rows["2025"]["net_income"] / rows["2025"]["shares_diluted"]
        for y, c in zip(("2023", "2024", "2025"), counts):
            rows[y]["shares_diluted"] = c
        rows["2025"]["net_income"] = eps * counts[-1]
        return d
    return edit


@pytest.mark.usefixtures("screener_data_stub")
def test_data_7_says_the_split_and_the_base_year_check_prints_numbers(monkeypatch):
    pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, hist_edit=_hist_pipr(),
                     fin_edit=_vendor(PIPR_VENDOR, GEV_EPS / 4), eps_year_ago=GEV_EPS / 4, country="United States")
    line7 = next(l for l in pack.splitlines() if l.startswith("- Share-count split suspected"))
    # revision 17, brief F7: a US company whose vendor EPS (restated, 4.42) times the multiplier agrees with the filed EPS
    assert line7 == ("- Share-count split suspected in the filed series: False. After the last filing: a 4-for-1 split "
                     "(filed FY2025 17.8M -> vendor 70.7M; the vendor's restated FY2025 EPS agrees); filed per-share "
                     "figures in DATA 5 and 6 are pre-split.")
    byc = _byc(pack)
    assert byc.startswith("- [Arithmetic] BASE-YEAR CHECK:") and "not available" not in byc
    assert "year-ago EPS of $4.42" in byc and "our filed FY2025 EPS is $4.42" in byc
    assert "the filed count x 4 for the split after the last filing (DATA 7)" in byc and "+0% apart" in byc
    assert "- split_after_last_filing: 4 | the vendor's share count is 4 times the last filed diluted count" in pack


@pytest.mark.usefixtures("screener_data_stub")
def test_the_aph_shape_a_count_twice_the_filed_one_is_a_2_for_1_split_now(monkeypatch):
    pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000,
                     fin_edit=_vendor(552e6, GEV_EPS / 2), eps_year_ago=GEV_EPS / 2, country="United States")
    assert ("After the last filing: a 2-for-1 split (filed FY2025 276.0M -> vendor 552.0M; the vendor's restated FY2025 "
            "EPS agrees)") in pack
    byc = _byc(pack)
    assert "not available" not in byc and "the filed count x 2 for the split" in byc and "+0% apart" in byc


@pytest.mark.usefixtures("screener_data_stub")
def test_a_reverse_split_after_the_last_filing_in_the_pack(monkeypatch):
    pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000,
                     fin_edit=_vendor(69e6, GEV_EPS * 4), eps_year_ago=GEV_EPS * 4, country="United States")
    assert ("After the last filing: a 1-for-4 reverse split (filed FY2025 276.0M -> vendor 69.0M; the vendor's restated "
            "FY2025 EPS agrees)") in pack
    byc = _byc(pack)
    assert "not available" not in byc and "the filed count / 4 for the split" in byc
    assert "- split_after_last_filing: 1/4 | the vendor's share count is 1/4 of the last filed diluted count" in pack


@pytest.mark.usefixtures("screener_data_stub")
def test_dilution_and_ads_units_are_not_splits_and_keep_not_available(monkeypatch):
    dil = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=lambda f: dict(f, Shares_Outstanding=276e6 * 1.9))
    assert "After the last filing: none detected." in dil
    assert "split_after_last_filing" not in dil
    assert _byc(dil).startswith("- BASE-YEAR CHECK: not available") and "differ by more than 15%" in _byc(dil)
    ads = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=lambda f: dict(f, Shares_Outstanding=276e6 * 6.1))
    assert "After the last filing: none detected." in ads
    assert _byc(ads).startswith("- BASE-YEAR CHECK: not available")


@pytest.mark.usefixtures("screener_data_stub")
def test_the_base_year_check_uses_the_split_adjusted_filed_shares_and_the_cap_is_never_asked(monkeypatch):
    # filed FY2025 EPS $17.70 (net income / 276M); the vendor's year-ago EPS, split-adjusted for a 2-for-1, is $7.00
    # against $8.85 filed per share on the adjusted count: the BASE-YEAR CHECK prints the adjusted count's EPS. Revision 18
    # removed the cap's action: `base_year_cap` is not called at all (it stays in the module, unused)
    calls = []
    real = cap.consensus_reference.base_year_cap
    monkeypatch.setattr(cap.consensus_reference, "base_year_cap",
                        lambda ni, shares, eps: (calls.append((ni, shares, eps)), real(ni, shares, eps))[1])
    pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000,
                     fin_edit=lambda f: dict(f, Shares_Outstanding=552e6), eps_year_ago=7.0)
    byc = _byc(pack)
    assert "our filed FY2025 EPS is $8.85" in byc and "year-ago EPS of $7.00" in byc
    assert calls == [] and "BASE-YEAR CAP" not in pack
    # the same inputs without a split: the pre-split count, as before
    pre = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=lambda f: f, eps_year_ago=7.0)
    assert calls == [] and "our filed FY2025 EPS is $" in _byc(pre)


@pytest.mark.usefixtures("screener_data_stub")
def test_the_fact_reaches_the_facts_object_and_the_defaults_block_reads_back_equal(monkeypatch):
    import rs2_data
    for edit, expect in ((lambda f: dict(f, Shares_Outstanding=552e6), 2.0),
                         (lambda f: dict(f, Shares_Outstanding=69e6), 0.25),
                         (lambda f: f, None)):
        pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=edit)
        text = pack
        parsed = pack_facts.from_text(text)
        assert parsed["split_after_last_filing"] == expect
        assert cap.LAST_PACK_FACTS["split_after_last_filing"] == expect
        assert pack_facts.parity(cap.LAST_PACK_FACTS, parsed) == []


def test_filed_diluted_series_matches_data_6bs_rounding():
    h = {"2023": {"shares_diluted": 1_234_567.6}, "2024": {"shares_diluted": None}, "2025": {"shares_diluted": 1_300_000.4}}
    assert cap._filed_diluted_series(h) == [(2023, 1234568.0), (2025, 1300000.0)]


# ---- C4: the DEFAULTS line and the stamp ---------------------------------------------------------------------------

def test_defaults_line_prints_only_when_a_split_was_detected_and_reads_back():
    base = dict(pack_facts.empty(), version=pack_facts.FACTS_VERSION)
    assert "split_after_last_filing" not in pack_facts.render_defaults_block(base)
    for m, printed in ((4.0, "4"), (2.0, "2"), (20.0, "20"), (0.25, "1/4"), (1 / 3, "1/3")):
        f = dict(base, split_after_last_filing=m)
        block = pack_facts.render_defaults_block(f)
        assert f"- split_after_last_filing: {printed} | " in block
    assert pack_facts._dp_split("4") == 4.0 and pack_facts._dp_split("1/4") == 0.25 and pack_facts._dp_split("1/3") == 1 / 3


def test_the_split_is_stamped_on_the_verdict(tmp_path):
    facts = dict(pack_facts.empty(), split_after_last_filing=4.0)
    d = _dcf(0.0898)
    _, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=facts)
    assert st["split_after_last_filing"] == 4.0
    _, none = cv.scenario_checks(tmp_path / "nowhere", {"base_iv": 1.0}, None, PACK, 1.0, facts=pack_facts.empty())
    assert none["split_after_last_filing"] is None


# ---- C5: the dilution factor is not applied twice ----------------------------------------------------------------

def _fin(ni, basic, diluted):
    return {"Quarterly_Income_Statement": [{"Date": "2026-06-30", "NetIncome": ni, "BasicEPS": basic,
                                            "DilutedEPS": diluted}]}


def test_the_census_shape_vendor_within_1_percent_of_filed_diluted_is_not_diluted_twice():
    V = 100_000_000
    fin = _fin(V * 2.5, 2.5, 2.5 / 1.0859)                              # k = 1.0859, B = V
    default, k, period, warning = cap._share_default(fin, V, filed_diluted=100_500_000)
    assert default == V and k == 1.0859 and warning is None and period["matches_filed"] is True
    line = "\n".join(cap._share_default_lines(V, default, k, period, warning))
    assert "— not applied: DATA 2's count already matches the filed diluted count" in line
    assert f"- Shares default: {V:,.0f}" in line
    # and without the filed count, the factor applies as before
    assert cap._share_default(fin, V)[0] == round(V * (2.5 / (2.5 / 1.0859)))


def test_a_genuine_dilution_case_applies_the_factor_as_today():
    V = 95_000_000                                                     # 5% below the filed diluted count
    fin = _fin(V * 2.5, 2.5, 2.5 / 1.06)
    default, k, period, warning = cap._share_default(fin, V, filed_diluted=100_000_000)
    assert default == round(V * (2.5 / (2.5 / 1.06))) and warning is None
    assert "matches_filed" not in period
    line = "\n".join(cap._share_default_lines(V, default, k, period, warning))
    assert "not applied" not in line and "applied to the default at 1.05 or above" in line


def test_the_1_percent_edge_and_the_threshold_and_the_missing_count():
    V = 100_000_000
    fin = _fin(V * 2.5, 2.5, 2.5 / 1.06)
    assert cap._share_default(fin, V, filed_diluted=V * 1.009)[0] == V                          # inside 1%
    assert cap._share_default(fin, V, filed_diluted=V / 1.009)[0] == V
    assert cap._share_default(fin, V, filed_diluted=V * 1.012)[0] == round(V * (2.5 / (2.5 / 1.06)))   # outside
    assert cap._share_default(fin, V, filed_diluted=None)[0] == round(V * (2.5 / (2.5 / 1.06)))
    assert cap._share_default(fin, V, filed_diluted=0.0)[0] == round(V * (2.5 / (2.5 / 1.06)))          # 0.0 is no count
    below = _fin(V * 2.5, 2.5, 2.5 / 1.02)                                                      # k under 1.05
    d, k, p, w = cap._share_default(below, V, filed_diluted=V)
    assert d == V and w is None and "matches_filed" not in p                                   # nothing to annotate


def test_a_departing_basic_count_keeps_its_own_warning():
    V = 100_000_000
    fin = _fin(V * 2.5 / 1.3, 2.5, 2.5 / 1.06)                          # B is 30% from V: 5.11's own warning
    default, k, period, warning = cap._share_default(fin, V, filed_diluted=V)
    assert default == V and warning and "from the basic count implied by filed EPS" in warning
    assert "matches_filed" not in period


def test_piprs_inputs_with_the_4_for_1_split_default_to_the_vendor_count():
    fin = _fin(PIPR_VENDOR * 2.5, 2.5, 2.5 / 1.0526)                    # the final test's factor: 74.39M without C5
    h = _h(17_500_000, 17_600_000, PIPR_FILED)
    split = cap._split_after_last_filing(PIPR_VENDOR, h)
    filed_today = PIPR_FILED * split["multiplier"]
    assert cap._share_default(fin, PIPR_VENDOR, filed_diluted=filed_today)[0] == PIPR_VENDOR      # 70,670,291
    assert cap._share_default(fin, PIPR_VENDOR, filed_diluted=PIPR_FILED)[0] == round(PIPR_VENDOR * 1.0526)  # pre-split count
    assert 74.3e6 < round(PIPR_VENDOR * 1.0526) < 74.5e6


@pytest.mark.usefixtures("screener_data_stub")
def test_the_pack_says_it_in_section_2_and_defaults_carry_the_vendor_count(monkeypatch):
    # GEV's filed FY2025 count is 276.0M; the vendor count is within 1% of it and the quarter's EPS says 1.0870
    def fin_edit(f):
        ni = 500_000_000.0
        f = dict(f, Shares_Outstanding=277e6)
        f["Quarterly_Income_Statement"] = [dict(f["Quarterly_Income_Statement"][0], NetIncome=ni,
                                                BasicEPS=ni / 277e6, DilutedEPS=ni / 277e6 / 1.087)] + \
            list(f["Quarterly_Income_Statement"][1:])
        return f
    pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=fin_edit)
    sec2 = [l for l in pack.splitlines() if l.startswith("- Shares dilution factor")][0]
    assert "— not applied: DATA 2's count already matches the filed diluted count" in sec2
    assert "- Shares default: 277,000,000" in pack
    assert "- shares_default: 277,000,000 | " in pack and "- shares_warning: not available | " in pack

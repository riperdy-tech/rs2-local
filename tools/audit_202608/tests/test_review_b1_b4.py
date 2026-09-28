"""Phase 4 review fixes (Opus 5.5 ruling, 2026-09-27), from the whole-book rerun.

B1 Vendor figures meet filed figures only when shown to match: EPS levels only with the vintage
   test passed; a filed year more than 12 months old with the test failed is "not verified", never
   "rolled"; the vendor's capex only with no unconverted currency and a statement dated at our FY end.
B2 The TTM window's reference is fenced like the fiscal-year one (BMRN printed $8.05 under a $27.3
   floor): its side of the fence, never its number.
B3 The fiscal year end comes from the vendor's dated statements when there is no TTM record (WSE and
   TOP close on 31 March; the Dec-31 default read WSE's FY2026 as "after today").
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402

B = 1e9
WSE_FIN = {"Annual_Income_Statement": [{"Date": "2026-03-31", "NetIncome": 498700000.0},
                                       {"Date": "2025-03-31", "NetIncome": 550300000.0}],
           "Capital_Expenditure": -21400000.0}
RNW_FIN = {"Annual_Income_Statement": [{"Date": "2026-03-31", "NetIncome": 1.0e10}],
           "Capital_Expenditure": -93966000000.0,
           "FX": {"statement_currency": "INR", "quote_currency": "USD", "converted": False,
                  "flag": "unreviewed_currency_mismatch"}}


# ---- B3: the fiscal year end ---------------------------------------------------------------

def _fake_data(monkeypatch, ttm=None, fin=None):
    import rs2_data
    orig = rs2_data.load_json

    def fake(p):
        s = str(p)
        if s.endswith("fundamentals_ttm.json"):
            return {"tickers": {"X": ttm} if ttm else {}}
        if "financials" in s and s.endswith("X.json"):
            return fin or {}
        return orig(p)
    monkeypatch.setattr(rs2_data, "load_json", fake)


def test_the_ttm_record_comes_first(monkeypatch):
    _fake_data(monkeypatch, ttm={"fy_leg_end": "2025-11-01"}, fin=WSE_FIN)
    assert cap._fye_month_day("X", with_source=True) == (11, 1, "ttm")
    assert cap._fye_month_day("X") == (11, 1)


def test_without_a_ttm_record_the_vendor_dates_decide(monkeypatch):
    _fake_data(monkeypatch, fin=WSE_FIN)
    assert cap._fye_month_day("X", with_source=True) == (3, 31, "vendor")      # WSE, TOP, RNW


def test_no_dates_at_all_is_reported_as_the_default(monkeypatch):
    _fake_data(monkeypatch, fin={})
    assert cap._fye_month_day("X", with_source=True) == (12, 31, "default")


def test_the_matching_net_income_confirms_the_label_year():
    assert cap._vendor_fy_end_for(WSE_FIN, 498700000, 2026) == (date(2026, 3, 31), None)
    assert cap._vendor_fy_end_for(WSE_FIN, 498700000 * 1.03, 2026) == (None, None)       # outside 2%
    assert cap._vendor_fy_end_for(WSE_FIN, None, 2026) == (None, None)


CX_FIN = {"Annual_Income_Statement": [{"Date": "2025-12-31", "NetIncome": 960000000.0},
                                      {"Date": "2024-12-31", "NetIncome": 939000000.0},
                                      {"Date": "2023-12-31", "NetIncome": 182000000.0}]}


def test_one_coincidental_match_in_another_year_leaves_the_label_standing():
    # CX: our consolidated FY2024 ($960M) equals the vendor's attributable FY2025; FY2023 does not shift
    assert cap._vendor_fy_end_for(CX_FIN, 960000000, 2024, prev_net_income=199000000) == (None, None)


def test_the_same_shift_in_two_consecutive_years_is_a_conflict():
    # our FY2024 = the vendor's 2025 and our FY2023 = the vendor's 2024: the label is in doubt (review R4)
    assert cap._vendor_fy_end_for(CX_FIN, 960000000, 2024, prev_net_income=939000000) == (None, date(2025, 12, 31))
    assert cap._vendor_fy_end_for(CX_FIN, 939000000, 2024, prev_net_income=182000000) == (date(2024, 12, 31), None)


# ---- B1: the vendor's capex ------------------------------------------------------------------

def test_unconverted_vendor_currency_never_meets_filed_income():
    ok, why = cap._vendor_capex_usable(RNW_FIN, date(2026, 3, 31))
    assert ok is False and "INR" in why


def test_the_vendor_statement_must_be_dated_at_our_fiscal_year_end():
    assert cap._vendor_capex_usable(WSE_FIN, date(2026, 3, 31)) == (True, None)
    assert cap._vendor_capex_usable(WSE_FIN, date(2026, 4, 6))[0] is True       # 52/53-week years
    assert cap._vendor_capex_usable(WSE_FIN, date(2025, 12, 31))[0] is False
    assert cap._vendor_capex_usable({}, date(2026, 3, 31))[0] is False


# ---- B1: EPS levels ---------------------------------------------------------------------------

EST = {"0y": {"eps": {"avg": 12.89, "analysts": 29, "growth": 0.655, "year_ago": 7.79}, "revenue": {"growth": 0.3}},
       "+1y": {"eps": {"avg": 16.34, "analysts": 29, "growth": 0.268}, "revenue": {"growth": 0.2, "analysts": 29}}}


def test_eps_levels_are_not_combined_with_filed_figures_on_an_unverified_vintage():
    blocked = cr.build(-0.3 * B, EST, 0.1, 0.0375, 0.48 * B, 0.096, da=2.0 * B, capex=0.5 * B, stub_months=8.8,
                       levels_block="the vendor's year-ago revenue does not match FY2025's filed revenue within 2%")
    assert blocked["value"] is None and "the EPS levels are not used" in blocked["reason"]
    allowed = cr.build(-0.3 * B, EST, 0.1, 0.0375, 0.48 * B, 0.096, da=2.0 * B, capex=0.5 * B, stub_months=8.8)
    assert allowed["method"] == "levels" and allowed["value"] > 0


def test_the_growth_method_is_exempt_from_the_levels_guard():
    ref = cr.build(3.732 * B, EST, 0.1045, 0.0375, 0.48 * B, 0.096, stub_months=10.8,
                   levels_block="anything")
    assert ref["method"] == "growth" and ref["value"] > 0


# ---- B2: the TTM window is fenced -------------------------------------------------------------

def test_a_ttm_window_outside_the_fence_prints_its_side_and_no_number():
    ref = cr.build(3.732 * B, EST, 0.1045, 0.0375, 0.48 * B, 0.096, stub_months=10.8)
    win = cr.window_check(ref, 3.732 * B, 3.732 * B * 1.655 ** 0.5 * 0.2, 2)       # BMRN's shape: -80%
    fenced = cr.fence_window(win, "below", (27.3, 400.0))
    line = cr.window_line(fenced, ref, 3.732 * B * 0.26, "2026-06-30", lambda v: f"${v / 1e9:.3f}B")
    # S3 C (brief §5.3/§5.6): the clause is lower-cased and its guidance_deviation_reason
    # instruction is gone (that rule now lives in the DEFAULTS block, §5.2); the fence and its
    # numbers stay.
    assert "lands below the street fence [$27.30, $400.00]" in line
    assert "worth $" not in line.split("on the TTM window")[1].split(" | ")[0]
    parsed = cv._pack_window(line)
    assert parsed["gap"] == -0.8 and parsed["ttm_value"] is None
    pack = cr.pack_line(ref, 3.732 * B, 0.1045, 0.0375, lambda v: f"${v / 1e9:.3f}B") + "\n" + line
    assert cv.reference_window({"base_iv": 60.0}, pack)[2] == "fy"
    assert cr.fence_window(win, None, None) is win


# ---- B1/B3 in the pack: not verified, and an unknown year end ---------------------------------

class _FixedNow(__import__("datetime").datetime):
    """Review R6: the pack's clock pinned to 2026-09-26, so the date-dependent cases never expire."""
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 26, 12, 0, tzinfo=tz)


def _gev_pack(monkeypatch, fye, year_ago, fin_edit=None, ttm_edit=None, hist_edit=None):
    import rs2_data
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00",
          "estimates": {"0y": {"eps": {"avg": 20.0, "low": 18.0, "high": 22.0, "analysts": 25, "growth": 0.13,
                                       "year_ago": 17.70},
                               "revenue": {"avg": 41e9, "analysts": 24, "growth": 0.08, "year_ago": year_ago}},
                        "+1y": {"eps": {"avg": 24.0, "low": 21.0, "high": 27.0, "analysts": 23, "growth": 0.20},
                                "revenue": {"avg": 45e9, "analysts": 22, "growth": 0.10}}}}
    orig = rs2_data.load_json

    def fake(p):
        s = str(p)
        if s.endswith("GEV.json") and "enrich" in s:
            return en
        out = orig(p)
        if fin_edit and s.endswith("GEV.json") and "financials" in s:
            out = fin_edit(json.loads(json.dumps(out)))
        if ttm_edit and s.endswith("fundamentals_ttm.json"):
            out = ttm_edit(json.loads(json.dumps(out)))
        if hist_edit and s.endswith("fundamentals_history.json"):
            out = hist_edit(json.loads(json.dumps(out)))
        return out
    monkeypatch.setattr(rs2_data, "load_json", fake)
    monkeypatch.setattr(cap, "_fye_month_day", lambda t, with_source=False: fye if with_source else fye[:2])
    monkeypatch.setattr(cap, "datetime", _FixedNow)
    return str(cap.build_pack("GEV"))


def _ref_line(pack):
    return next(l for l in pack.splitlines() if "CONSENSUS-IMPLIED VALUE" in l)


@pytest.mark.usefixtures("screener_data_stub")
def test_a_filed_year_over_12_months_old_needs_a_matching_vintage(monkeypatch):
    # FY2025 ended 1 August 2025: 13.8 months before the pinned 2026-09-26
    unverified = _ref_line(_gev_pack(monkeypatch, (8, 1, "ttm"), 30.0e9))
    assert "not available" in unverified and "not verified" in unverified
    assert "does not match its filed revenue within 2%" in unverified
    unknown = _ref_line(_gev_pack(monkeypatch, (8, 1, "ttm"), None))         # review R2
    assert "not verified" in unknown and "year-ago revenue is not available" in unknown
    # the fixture holds no growth base-rate median, so an accepted year still prints "not available",
    # for that reason and not for the vintage
    aligned = _ref_line(_gev_pack(monkeypatch, (8, 1, "ttm"), 38068000000))
    assert "not verified" not in aligned and "growth base-rate median missing" in aligned


@pytest.mark.usefixtures("screener_data_stub")
def test_an_unknown_year_end_builds_no_reference(monkeypatch):
    line = _ref_line(_gev_pack(monkeypatch, (12, 31, "default"), 38068000000))
    assert "the fiscal year end is unknown" in line


# ---- R1, R3, R5, R7 ----------------------------------------------------------------------------

def _byc(pack):
    return next(l for l in pack.splitlines() if "BASE-YEAR CHECK" in l)


@pytest.mark.usefixtures("screener_data_stub")
def test_the_base_year_check_across_a_split_is_withheld(monkeypatch):
    # APH's shape: SECTION 2's share count is twice the filed diluted count
    line = _byc(_gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000,
                          fin_edit=lambda f: dict(f, Shares_Outstanding=552e6)))
    assert line.startswith("- BASE-YEAR CHECK: not available") and "differ by more than 15%" in line
    assert "cannot be shown to be on one basis" in line                                  # R3


@pytest.mark.usefixtures("screener_data_stub")
def test_no_share_count_is_said_plainly_and_does_not_crash(monkeypatch):
    def drop(f):
        f.pop("Shares_Outstanding", None)
        return f
    line = _byc(_gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=drop))    # R1
    assert "SECTION 2 holds no share count" in line


@pytest.mark.usefixtures("screener_data_stub")
def test_a_failed_vintage_is_said_as_unproven_not_as_different(monkeypatch):
    line = _byc(_gev_pack(monkeypatch, (12, 31, "ttm"), 30.0e9))
    assert "does not match FY2025's filed revenue within 2%" in line
    assert "cannot be shown to be on one basis" in line and "are not on one basis" not in line


@pytest.mark.usefixtures("screener_data_stub")
def test_a_refused_vendor_capex_says_why(monkeypatch):
    def no_ttm_capex(d):
        d["tickers"]["GEV"]["fields"].pop("capex", None)
        return d

    def rupees(f):
        return dict(f, FX={"statement_currency": "INR", "converted": False,
                           "flag": "unreviewed_currency_mismatch"})
    def no_fy_capex(d):
        d["tickers"]["GEV"]["2025"].pop("capex", None)
        return d
    pack = _gev_pack(monkeypatch, (12, 31, "ttm"), 38068000000, fin_edit=rupees, ttm_edit=no_ttm_capex,
                     hist_edit=no_fy_capex)
    # S3 C (brief §5.6): the label drops "(default base_cf)".
    line = next(l for l in pack.splitlines() if l.startswith("- OWNER EARNINGS"))
    assert "not available" in line and "the vendor's capex is not used" in line and "INR" in line   # R5


def test_the_window_line_points_to_the_base_year_check_only_when_it_printed():
    ref = cr.build(3.732 * B, EST, 0.1045, 0.0375, 0.48 * B, 0.096, stub_months=10.8)
    win = cr.window_check(ref, 3.732 * B, 3.732 * B * 1.655 ** 0.5 * 1.56, 2)
    fmt = lambda v: f"${v / 1e9:.3f}B"  # noqa: E731
    # S3 C (brief §5.6): the clause is lower-cased.
    assert "the BASE-YEAR CHECK shows" in cr.window_line(win, ref, 1.0 * B, "2026-06-30", fmt)
    assert "BASE-YEAR" not in cr.window_line(win, ref, 1.0 * B, "2026-06-30", fmt, base_year_check=False)  # R7

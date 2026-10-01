"""P-2 (share counts off by a factor of 1,000): annotate and protect, never silently gate.

The screener's extractor now corrects a proven scale slip in a filed diluted count and writes the latest cover-page count
as `shares_cover`. rs2 side, tested here:
  1. SHARES ALERT in SECTION 2 when the latest filed diluted count (split-adjusted) and the vendor's differ by 100x or more;
     it names the factor and which count the cover count agrees with.
  2. A vendor count proven wrong (cover agrees with the filed count, company files 10-Ks) gives no share default; a
     foreign filer keeps the vendor count and gets one sentence.
  3. The peer trailing P/E leaves out a peer whose two counts differ by 100x or more, and says how many.
  4. The sweep's data-health scan logs audit_shares next to the series breaks, and does not block.
Synthetic tickers throughout.
"""
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import capability_test as cap  # noqa: E402
import pack_facts  # noqa: E402
from test_consensus_anchor_gate import frozen_env  # noqa: E402,F401  (registers the fixture)
from test_section_8_5_peer_pe import _factor_scores, _patch_load_json, _slice  # noqa: E402


# ---- the gap rule ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("filed,vendor,expect", [
    (1_000_000, 100_000_000, 100.0),            # exactly 100x is a gap
    (1_000_000, 99_900_000, None),              # 99.9x is not
    (100_000_000, 1_000_000, 0.01),             # exactly 1/100 is a gap
    (100_000_000, 1_010_000, None),
    (1_000_000, 1_000_000_000, 1000.0),
    (1_000_000, 1_000_000, None),
])
def test_the_gap_is_100x_or_more_either_way(filed, vendor, expect):
    assert cap._shares_scale_gap(filed, vendor) == expect


@pytest.mark.parametrize("filed,vendor", [(0.0, 1e9), (1e6, 0.0), (None, 1e9), (1e6, None), (True, 1e9),
                                          (float("nan"), 1e9), (1e6, float("inf")), (-1e6, 1e9)])
def test_a_missing_zero_or_unusable_count_is_no_gap(filed, vendor):
    # 0.0 is a value but not a count to divide by; the ZERO-on-file note owns that case
    assert cap._shares_scale_gap(filed, vendor) is None


# ---- the state: which count the cover agrees with -----------------------------------------------------------------

FILED, VENDOR = 1_000_000.0, 1_000_000_000.0


def _state(cover, tenk=True, filed=FILED, vendor=VENDOR):
    calls = []

    def is_10k():
        calls.append(1)
        return tenk
    g = cap._shares_gap_state(filed, vendor, cover, is_10k)
    return g, calls


def test_no_gap_gives_no_state_and_never_asks_the_filer_type():
    g, calls = _state({"val": 1e6}, filed=1e6, vendor=5e6)
    assert g is None and calls == []


def test_cover_agrees_with_the_filed_count_of_a_10k_filer_makes_the_vendor_count_unusable():
    g, calls = _state({"val": 1.2e6, "date": "2026-02-01"})
    assert g["agrees"] == "filed" and g["vendor_unusable"] is True and g["depositary"] is False
    assert g["ratio"] == 1000.0 and g["cover"] == 1.2e6 and g["cover_date"] == "2026-02-01"


def test_cover_agrees_with_the_filed_count_of_a_foreign_filer_keeps_the_vendor_count():
    g, _ = _state({"val": 1.2e6}, tenk=False)
    assert g["agrees"] == "filed" and g["vendor_unusable"] is False and g["depositary"] is True


def test_cover_agreeing_with_the_vendor_or_neither_withholds_nothing_and_skips_the_filer_test():
    g, calls = _state({"val": 9e8})
    assert g["agrees"] == "vendor" and not g["vendor_unusable"] and not g["depositary"] and calls == []
    g, calls = _state({"val": 5e7})
    assert g["agrees"] == "neither" and not g["vendor_unusable"] and calls == []


def test_no_cover_count_is_not_a_verdict():
    for cover in (None, {}, {"val": None}, {"val": 0.0}, {"val": "x"}):
        g, calls = _state(cover)
        assert g["agrees"] is None and g["cover"] is None and not g["vendor_unusable"] and calls == []


def test_agree_means_within_50_percent():
    assert _state({"val": 1.5e6})[0]["agrees"] == "filed"
    assert _state({"val": 1e6 / 1.5})[0]["agrees"] == "filed"
    assert _state({"val": 1.51e6})[0]["agrees"] == "neither"
    assert _state({"val": 1e6 / 1.51})[0]["agrees"] == "neither"


def test_the_alert_names_the_factor_the_counts_and_the_agreeing_count():
    g, _ = _state({"val": 1.1e6, "date": "2026-02-01"})
    t = cap._shares_alert_text(g, FILED, 2025, VENDOR)
    assert t.startswith("**SHARES ALERT") and "FY2025" in t and "split-adjusted" in t
    assert "1,000 times the filed count" in t
    assert "cover-page count (1,100,000, 2026-02-01) agrees with the filed count" in t
    assert "not usable" in t and "no share-count default" in t
    g, _ = _state({"val": 1.1e6}, tenk=False)
    t = cap._shares_alert_text(g, FILED, 2025, VENDOR)
    assert "The vendor count may be a depositary-share count." in t and "not usable" not in t
    g, _ = _state({"val": 9e8})
    assert "agrees with the vendor's count" in cap._shares_alert_text(g, FILED, 2025, VENDOR)
    assert "off-scale" in cap._shares_alert_text(g, FILED, 2025, VENDOR)
    g, _ = _state({"val": 5e7})
    assert "agrees with neither" in cap._shares_alert_text(g, FILED, 2025, VENDOR)
    g, _ = _state(None)
    assert "No cover-page count is held" in cap._shares_alert_text(g, FILED, 2025, VENDOR)
    g, _ = _state({"val": 1.1e9}, filed=1e9, vendor=1e6)       # vendor 1/1000 of the filed count
    assert "1/1,000 of the filed count" in cap._shares_alert_text(g, 1e9, 2025, 1e6)


# ---- the share default ----------------------------------------------------------------------------------------------

_FIN = {"Annual_Income_Statement": [{"Date": "2025-12-31", "NetIncome": 100.0, "BasicEPS": 1.0, "DilutedEPS": 0.8}]}


def test_vendor_unusable_returns_no_default_and_a_warning():
    d, k, period, warning = cap._share_default(_FIN, 100.0, vendor_unusable=True)
    assert (d, k, period) == (None, None, None) and "SHARES ALERT" in warning and "refuses" in warning


def test_the_default_is_unchanged_without_the_flag():
    assert cap._share_default(_FIN, 100.0) == cap._share_default(_FIN, 100.0, vendor_unusable=False)
    assert cap._share_default(_FIN, 100.0)[0] == 125.0       # 100 x (1.0 / 0.8): the existing dilution rule


# ---- the pack -------------------------------------------------------------------------------------------------------

def _gev(monkeypatch, vendor_mult=1.0, cover=None, fx=None, country="United States", hist_edit=None):
    """GEV's live pack with the vendor count scaled, a `shares_cover` record, an FX block and a country."""
    import rs2_data
    orig = rs2_data.load_json

    def fake(p):
        s = str(p)
        out = orig(p)
        if s.endswith("GEV.json") and "financials" in s and out:
            out = json.loads(json.dumps(out))
            out["Shares_Outstanding"] = out["Shares_Outstanding"] * vendor_mult
            if fx is not None:
                out["FX"] = fx
        if s.endswith("fundamentals_history.json") and out:
            out = json.loads(json.dumps(out))
            if cover is not None:
                out["shares_cover"] = {"GEV": cover}
            if hist_edit:
                out = hist_edit(out)
        if s.endswith("stocks.json"):
            return [{"symbol": "GEV", "country": country}]
        return out
    monkeypatch.setattr(rs2_data, "load_json", fake)
    return cap.build_pack("GEV", include_research=False)


def _sec2(pack):
    text = str(pack)
    i = text.index("## DATA 2 ")
    return text[i:text.index("\n## ", i + 5)], text


@pytest.mark.usefixtures("screener_data_stub")
def test_a_pack_with_agreeing_counts_has_no_alert_and_is_unchanged(frozen_env, monkeypatch):
    pack = _gev(monkeypatch)
    assert "SHARES ALERT" not in str(pack)
    assert pack.facts["shares_default"] is not None


@pytest.mark.usefixtures("screener_data_stub")
def test_a_10k_filer_whose_vendor_count_is_1000x_off_gets_the_alert_and_no_default(frozen_env, monkeypatch):
    base = _gev(monkeypatch)
    filed = base.facts["filed_shares_diluted"]
    pack = _gev(monkeypatch, vendor_mult=1000.0, cover={"val": filed * 1.02, "date": "2026-02-10", "filed": "2026-02-20"})
    sec2, text = _sec2(pack)
    assert "**SHARES ALERT" in text and text.index("SHARES ALERT") < text.index("## DATA 2 ")
    assert re.search(r"the vendor's count is [\d,]+ times the filed count", text) and "agrees with the filed count" in text
    assert pack.facts["shares_default"] is None
    assert "not usable" in text and "- Shares default:" not in sec2
    assert pack.facts["shares_warning"] and "SHARES ALERT" in pack.facts["shares_warning"]
    assert pack_facts.parity(pack.facts, pack_facts.from_text(text)) == []


@pytest.mark.usefixtures("screener_data_stub")
def test_a_foreign_filer_keeps_the_vendor_count_and_its_default(frozen_env, monkeypatch):
    base = _gev(monkeypatch)
    filed = base.facts["filed_shares_diluted"]
    cover = {"val": filed, "date": "2026-02-10"}
    fx = {"statement_currency": "EUR", "quote_currency": "USD", "converted": True}
    pack = _gev(monkeypatch, vendor_mult=1000.0, cover=cover, fx=fx)
    _, text = _sec2(pack)
    assert "The vendor count may be a depositary-share count." in text
    assert pack.facts["shares_default"] is not None and "not usable" not in text
    # a non-US 10-K-less company with no FX block is treated the same way: the country decides
    pack = _gev(monkeypatch, vendor_mult=1000.0, cover=cover, country="Israel")
    assert "depositary-share count" in str(pack) and pack.facts["shares_default"] is not None


@pytest.mark.usefixtures("screener_data_stub")
def test_the_share_default_is_unchanged_for_a_name_with_no_gap_whatever_the_cover_says(frozen_env, monkeypatch):
    base = _gev(monkeypatch)
    with_cover = _gev(monkeypatch, cover={"val": base.facts["filed_shares_diluted"] * 1e6})
    assert with_cover.facts["shares_default"] == base.facts["shares_default"]
    assert "SHARES ALERT" not in str(with_cover)
    assert str(with_cover) == str(base)


@pytest.mark.usefixtures("screener_data_stub")
def test_a_gap_with_no_cover_count_says_so_and_withholds_nothing(frozen_env, monkeypatch):
    pack = _gev(monkeypatch, vendor_mult=1000.0)
    _, text = _sec2(pack)
    assert "No cover-page count is held" in text and pack.facts["shares_default"] is not None


@pytest.mark.usefixtures("screener_data_stub")
def test_a_point_in_time_pack_has_no_alert(frozen_env, monkeypatch):
    import test_consensus_anchor_gate as tcag
    tcag._fake_asof_price_lookup(monkeypatch, price=180.0, asof_str="2026-03-31")
    tcag._fake_mri_asof(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31", include_research=False)
    assert "SHARES ALERT" not in str(pack)


# ---- the peer trailing P/E ------------------------------------------------------------------------------------------

def _peer_pack(monkeypatch, sd, vendors):
    """Fallback-branch peer P/E (no epsTtm anywhere): three peers, each with the vendor count given."""
    for sym, v in vendors.items():
        (sd / "financials" / f"{sym}.json").write_text(json.dumps({"Shares_Outstanding": v}), encoding="utf-8")
    stocks_list = [{"symbol": s, "price": 100.0, "metrics": {}, "peRatio": 0} for s in ("GEV", "PEER1", "PEER2", "PEER3")]
    hist = {"tickers": {
        "PEER1": {"2025": {"net_income": 1000.0, "shares_diluted": 50.0}},       # eps 20 -> 5x
        "PEER2": {"2025": {"net_income": 1000.0, "shares_diluted": 100.0}},      # eps 10 -> 10x
        "PEER3": {"2025": {"net_income": 1000.0, "shares_diluted": 200.0}},      # eps 5 -> 20x
    }}
    _patch_load_json(monkeypatch, {
        "factor_scores.json": _factor_scores({s: "X" for s in ("GEV", "PEER1", "PEER2", "PEER3")}),
        "stocks.json": stocks_list, "fundamentals_history.json": hist})
    return _slice(cap.build_pack("GEV", include_research=False), "DATA 8.5 - PEER CONTEXT")


@pytest.mark.usefixtures("screener_data_stub")
def test_a_peer_with_counts_100x_apart_is_left_out_and_counted(screener_data_stub, frozen_env, monkeypatch):
    sec85 = _peer_pack(monkeypatch, screener_data_stub, {"PEER1": 50_000.0, "PEER2": 100.0, "PEER3": 200.0})
    # PEER1's vendor count is 1000x its filed count: left out; PEER2 and PEER3 agree
    assert "trailing P/E (n=2" in sec85
    assert "1 cluster peer(s) left out of that trailing P/E" in sec85


@pytest.mark.usefixtures("screener_data_stub")
def test_peers_with_agreeing_or_unknown_counts_are_all_kept_and_nothing_is_said(screener_data_stub, frozen_env, monkeypatch):
    sec85 = _peer_pack(monkeypatch, screener_data_stub, {"PEER1": 50.0, "PEER2": 120.0})    # PEER3 has no vendor file
    assert "trailing P/E (n=3" in sec85 and "left out" not in sec85


# ---- the sweep's warning --------------------------------------------------------------------------------------------

def test_data_health_scan_logs_share_gaps_next_to_the_series_breaks_and_does_not_block(monkeypatch):
    import data_health
    import orchestrate_depth as od
    import rs2_data
    monkeypatch.setattr(rs2_data, "load_json", lambda p: {"tickers": {}})
    monkeypatch.setattr(data_health, "audit_series_breaks",
                        lambda book, hist: [{"ticker": "AAA", "field": "cash", "from_year": 2020, "from": 1, "to_year": 2021, "to": 1000}])
    monkeypatch.setattr(data_health, "audit_shares",
                        lambda book, hist: [{"ticker": "BBB", "field": "shares_diluted", "raw": 1000.0, "independent": 1e6,
                                             "corrected_to": 1e6}])
    logged = []
    monkeypatch.setattr(od, "log", logged.append)
    assert od.data_health_scan(["AAA", "BBB"]) is None
    text = "\n".join(logged)
    assert "1 provable 1000x scale break(s)" in text and "AAA cash" in text
    assert "1 book name(s) where the filed diluted share count and the vendor's differ" in text
    assert "BBB filed 1,000 vs vendor 1,000,000" in text and "NOT blocking" in text


def test_data_health_scan_with_only_share_gaps_still_logs_them(monkeypatch):
    import data_health
    import orchestrate_depth as od
    import rs2_data
    monkeypatch.setattr(rs2_data, "load_json", lambda p: {"tickers": {}})
    monkeypatch.setattr(data_health, "audit_series_breaks", lambda book, hist: [])
    monkeypatch.setattr(data_health, "audit_shares",
                        lambda book, hist: [{"ticker": "BBB", "field": "shares_diluted", "raw": 1000.0, "independent": 1e6,
                                             "corrected_to": 1e6}])
    logged = []
    monkeypatch.setattr(od, "log", logged.append)
    od.data_health_scan(["BBB"])
    assert any("no provable scale corruption" in m for m in logged)
    assert any("filed diluted share count and the vendor's differ" in m for m in logged)


def test_data_health_scan_logs_nothing_extra_when_the_sources_agree(monkeypatch):
    import data_health
    import orchestrate_depth as od
    import rs2_data
    monkeypatch.setattr(rs2_data, "load_json", lambda p: {"tickers": {}})
    monkeypatch.setattr(data_health, "audit_series_breaks", lambda book, hist: [])
    monkeypatch.setattr(data_health, "audit_shares", lambda book, hist: [])
    logged = []
    monkeypatch.setattr(od, "log", logged.append)
    od.data_health_scan(["AAA"])
    assert logged == ["data-health scan: no provable scale corruption in the book."]

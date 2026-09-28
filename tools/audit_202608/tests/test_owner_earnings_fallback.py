"""Phase 4 E14 (2026-09-25): labelled fallbacks for the OWNER EARNINGS default.

The revision-9 pack dry run found FSM and AU (40-F / 20-F filers) with no TTM record, and GPOR, FSM
and AU with no capex in any year (the screener's extractor maps only
PaymentsToAcquirePropertyPlantAndEquipment). Three of six retest names had no default base and no
reference. The fallbacks use the latest fiscal year's net income and the vendor's latest-annual
capex, labelled, and stamp the source on every verdict. The vendor stores capex NEGATIVE (FSM
-178,004,000; GPOR -527,569,000): a naive `ni + da - capex` would add it.
"""
import json
import re

import consensus_valuation as cv


def _edit(sd, name, fn):
    p = sd / name
    d = json.loads(p.read_text(encoding="utf-8"))
    fn(d)
    p.write_text(json.dumps(d), encoding="utf-8")


def _drop_capex(d):
    for rec in d["tickers"]["GEV"].values():
        if isinstance(rec, dict):
            rec.pop("capex", None)


# S3 C (brief §5.6): the label drops "(default base_cf)", the result is stated before "=" (with
# owner_earnings_source right after it, not at the end), and every $B figure is bare (no $/B — the
# section's header states the unit once, §5.7).
def _oe_line(pack):
    return next(l for l in pack.splitlines() if l.startswith("- [Arithmetic] OWNER EARNINGS")
               or l.startswith("- OWNER EARNINGS"))


def test_a_40f_filer_with_no_capex_tag_gets_fy_income_and_vendor_capex(screener_data_stub):
    import capability_test as cap
    sd = screener_data_stub
    _edit(sd, "fundamentals_ttm.json", lambda d: d["tickers"].pop("GEV"))          # no TTM (40-F)
    _edit(sd, "fundamentals_history.json", _drop_capex)                              # no capex tag
    _edit(sd, "financials/GEV.json", lambda d: d.update(Capital_Expenditure=-178004000.0,
                                                          Data_Fetched_Date="2026-09-17 18:38"))
    pack = str(cap.build_pack("GEV"))
    line = _oe_line(pack)
    assert "FY2025 net income (no TTM held) 4.884" in line
    assert "vendor latest-annual capex (financials, fetched 2026-09-17;" in line
    assert "OWNER EARNINGS 5.559 (owner_earnings_source: fy_ni+vendor_capex) = " in line   # 4.884 + 0.853 - 0.178
    assert cv._pack_owner_earnings_source(pack) == "fy_ni+vendor_capex"


def test_an_eandp_with_ttm_income_but_no_capex_uses_vendor_capex(screener_data_stub):
    import capability_test as cap
    sd = screener_data_stub
    _edit(sd, "fundamentals_ttm.json", lambda d: d["tickers"]["GEV"]["fields"].pop("capex"))
    _edit(sd, "fundamentals_history.json", _drop_capex)
    _edit(sd, "financials/GEV.json", lambda d: d.update(Capital_Expenditure=-527569000.0))
    pack = str(cap.build_pack("GEV"))
    line = _oe_line(pack)
    assert "TTM net income 9.529" in line and "(owner_earnings_source: ttm_ni+vendor_capex)" in line
    assert "OWNER EARNINGS 9.854 (owner_earnings_source: ttm_ni+vendor_capex) = " in line   # 9.529 + 0.853 - 0.528
    cash = next(l for l in pack.splitlines() if "CASH BASIS" in l)
    assert "vendor latest-annual capex" in cash                                      # one capex source


def test_a_positive_vendor_capex_is_refused(screener_data_stub):
    import capability_test as cap
    sd = screener_data_stub
    _edit(sd, "fundamentals_ttm.json", lambda d: d["tickers"].pop("GEV"))
    _edit(sd, "fundamentals_history.json", _drop_capex)
    _edit(sd, "financials/GEV.json", lambda d: d.update(Capital_Expenditure=178004000.0))
    pack = str(cap.build_pack("GEV"))
    assert "OWNER EARNINGS: not available" in pack   # S3 C (brief §5.6): label drops "(default base_cf)"
    assert "TTM capex missing" in pack
    assert cv._pack_owner_earnings_source(pack) is None


def test_a_filed_fiscal_year_capex_comes_before_the_vendor(screener_data_stub):
    import capability_test as cap
    sd = screener_data_stub
    _edit(sd, "fundamentals_ttm.json", lambda d: d["tickers"].pop("GEV"))
    pack = str(cap.build_pack("GEV"))
    line = _oe_line(pack)
    assert "FY2025 capex (no TTM capex held) 1.277" in line
    assert "(owner_earnings_source: fy_ni+fy_capex)" in line


def test_a_pack_with_ttm_inputs_is_unchanged_and_stamped_ttm_filed(screener_data_stub):
    import capability_test as cap
    pack = str(cap.build_pack("GEV"))
    line = _oe_line(pack)
    assert "owner_earnings_source" not in line
    assert line.startswith("- [Arithmetic] OWNER EARNINGS 8.681 = TTM net income 9.529")
    assert re.search(r"\u2212 TTM capex 1\.701\. Stock compensation", line)
    assert cv._pack_owner_earnings_source(pack) == "ttm_filed"

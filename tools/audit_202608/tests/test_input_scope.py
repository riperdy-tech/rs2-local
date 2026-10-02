"""Pack revision 20 (brief_input_scope_fixes.md section 4, the rs2 side): Fixes 1b, 1c, 2b and 3, on synthetic data.

  1b-1 pi: each branch; an unmeasured share (and a base year whose net income scope is unknown) is printed with its upper bound, stamped,
       and gated on a directional verdict only;
  1b-2 homogeneity: the attributed levels over the common shares equal the consolidated levels over shares / pi (net-income split), and an
       equity-split name keeps the parent's net income unscaled;
  1b-3 pi = 1 changes nothing;
  1b-4 the record's view: consolidated net income and equity; `record_scope_mixed` exactly when a window year falls back;
  1b-5 the TTM window, the cash bound and the DEFAULTS use pi; the desk equals the reference to $0.005 (AT1a's bar);
  1c-1 the per-share identity, its tolerance, the untested cases, the printed figures and the gate;
  2b-1 the cash term reads `cash`; the customer-money annotations change no number;
  3-1  the frozen thresholds just inside and outside, the untestable domain, the estimates `build` receives on a break, and the refused file.
  The new history fields are reviewed (the unreviewed-field sensor stays silent).
The book versions of 1b-2, 1b-3 and 1b-5 run on SP\\sd_scope (rev20work/book_checks.py); the 167 are never read.
"""
import copy
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import depth_gates  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import input_scope as isc  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
from test_throughcycle_reference import EST, _cycle_history  # noqa: E402

B = 1e9
RULE = isc.break_rule()


# ---- a synthetic pack with the input-scope fields ----------------------------------------------------------------------------------------

def _doc(base_updates=None, all_years=None, prov_extra=None):
    """The synthetic twelve-year history of test_throughcycle_reference (base year 2025: revenue 10.0B, net income 1.2B, D&A 0.5B, capex
    0.6B, 500M diluted shares), `all_years` applied to every year and `base_updates` to 2025; `prov_extra` joins the provenance. Every
    year's `equity` is the company's own (equity_scope parent, the screener follow-up's contract) unless `prov_extra` says otherwise."""
    hist = _cycle_history()
    hist[2025] = dict(hist[2025], revenue=10.0 * B, net_income=1.2 * B, da=0.5 * B, capex=0.6 * B, shares_diluted=500e6, ocf=1.5 * B,
                      sbc=0.1 * B, operating_income=10.0 * B * 0.12 * 1.4 - 0.05 * B)
    for y in range(2014, 2025):
        hist[y] = dict(hist[y], da=0.5 * B, capex=0.6 * B, shares_diluted=500e6)
    for y in hist:
        hist[y].update(all_years(y, hist[y]) if callable(all_years) else (all_years or {}))
    hist[2025].update(base_updates or {})
    prov = {"untagged_fields": {"GEV": []}, "equity_scope": {"GEV": {str(y): "parent" for y in hist}}}
    prov.update(prov_extra or {})
    return {"tickers": {"GEV": {str(y): r for y, r in hist.items()}}, "provenance": prov}


def _stubs(monkeypatch, doc, est=EST, bill=0.04, sector="Industrials", record=None):
    from datetime import datetime as _real

    class _Frozen(_real):
        @classmethod
        def now(cls, tz=None):
            return _real(2026, 9, 27, 12, 0, 0)
    for mod in (cap, rs2_data):
        monkeypatch.setattr(mod, "datetime", _Frozen, raising=False)
    monkeypatch.setattr(cap.company_news, "fetch", lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [], "errors": ["s"]})
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)
    row = {"n": 100, "p50": 5.0, "p90": 15.0, "share_ge_10": 20.0, "share_ge_20": 5.0, "share_ge_30": 1.0}
    monkeypatch.setattr(cap.base_rates, "base_rate_table", lambda *a, **k: ("$1-10B", {5: dict(row), 10: dict(row)}))
    monkeypatch.setattr(cap.growth_persistence, "persistence_for_growth", lambda *a, **k: (None, None))
    monkeypatch.setattr(rs2_data, "bill_rate_mean", lambda start, end: (bill, "stub") if bill is not None else (None, "stub: none"))
    real_lookup = rs2_data.sector_lookup
    monkeypatch.setattr(rs2_data, "sector_lookup", lambda t: (sector, real_lookup(t)[1]))
    enrich = {"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "estimates": est}
    orig = rs2_data.load_json

    def load(path):
        name = str(path)
        if name.endswith("fundamentals_history.json"):
            return doc
        if name.endswith("GEV.json") and "enrich" in name:
            return enrich
        return orig(path)
    monkeypatch.setattr(rs2_data, "load_json", load)
    calls = []
    real_build = cr.build

    def rec(*a, **k):
        out = real_build(*a, **k)
        calls.append({"kwargs": k, "out": out})
        return out
    monkeypatch.setattr(cr, "build", rec)
    return calls


def _pack(monkeypatch, doc, **kw):
    calls = _stubs(monkeypatch, doc, **kw)
    pack = cap.build_pack("GEV", include_research=False)
    return pack, (calls[-1] if calls else None)


def _ref_line(text):
    return next(l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE (reference" in l)


def _ri(est=EST):
    """reference_inputs on a fresh DataRoot (the stubs of `_stubs` in force), unquantized as the closure solves."""
    anchors = {"rf": 0.04, "ga": 0.0375, "breakeven": 0.022, "loading": {"Industrials": 1.0}}
    return cap.reference_inputs("GEV", cap.DataRoot(), est, anchors, {"erp": 0.045}, printed=False, today=date(2026, 9, 27))


# an NCI split of the base year: parent 1.2B of consolidated 1.5B (pi = 0.8); consolidated equity 7.5B against 6.0B
NCI = {"net_income_incl_nci": 1.5 * B, "equity_incl_nci": 7.5 * B}


def _with_nci(y, row):
    return {"net_income_incl_nci": row["net_income"] * 1.25, "equity_incl_nci": row["equity"] * 1.25}


# ---- 1b-1: pi -------------------------------------------------------------------------------------------------------------------------------

def test_1b1_pi_each_branch():
    row = {"net_income": 1.2 * B, "net_income_incl_nci": 1.5 * B, "equity": 6.0 * B, "equity_incl_nci": 7.5 * B}
    n = isc.nci_share(row, "parent", 2025, "parent")
    assert n["basis"] == "ni_split" and n["pi"] == pytest.approx(0.8) and n["stamps"] == []
    # an NCI carrying a loss share: the parent's net income above the consolidated, pi capped at 1
    capped = isc.nci_share(dict(row, net_income_incl_nci=1.1 * B), "parent", 2025, "parent")
    assert capped["basis"] == "ni_split" and capped["pi"] == 1.0
    # the consolidated net income not positive: the equity split, read only on an equity that is the company's own
    for es in isc.PARENT_EQUITY_SCOPES:
        eq = isc.nci_share(dict(row, net_income_incl_nci=-0.1 * B), "parent", 2025, es)
        assert eq["basis"] == "equity_split" and eq["pi"] == pytest.approx(0.8), es
    eq_none = isc.nci_share(dict(row, net_income_incl_nci=None), "parent", 2025, "parent_derived")
    assert eq_none["basis"] == "equity_split"
    # an nci_unknown equity (the consolidated figure kept), or one with no scope, is not read: the share is not measured
    for es in ("nci_unknown", None):
        un_eq = isc.nci_share(dict(row, net_income_incl_nci=None), "parent", 2025, es)
        assert un_eq["basis"] == "unmeasured" and un_eq["stamps"] == [isc.NCI_UNMEASURED], es
    # ... but with the net-income split measured, the equity's scope does not matter
    assert isc.nci_share(row, "parent", 2025, "nci_unknown")["basis"] == "ni_split"
    # no NCI: no_nci_filed or nci_zero_filed, or the income statement shows none and no NCI equity is held (negative equity: neither
    # split usable)
    neg = {"net_income": -0.2 * B, "net_income_incl_nci": -0.2 * B, "equity": -1.0 * B, "equity_incl_nci": -1.0 * B}
    assert isc.nci_share(neg, "parent", 2025, "parent")["basis"] == "no_nci" and isc.nci_share(neg, "parent", 2025, "parent")["pi"] == 1.0
    assert isc.nci_share(dict(neg, net_income_incl_nci=None), "parent", 2025, "parent")["basis"] == "no_nci"
    assert isc.nci_share(neg, "parent", 2025, "nci_unknown")["basis"] == "unmeasured"           # equal only because both are consolidated
    for ns in isc.NO_NCI_SCOPES:
        assert isc.nci_share(dict(neg, net_income_incl_nci=None, equity_incl_nci=None), ns, 2025, None)["basis"] == "no_nci", ns
    for es in isc.NO_NCI_SCOPES:
        assert isc.nci_share(dict(neg, net_income_incl_nci=None, equity_incl_nci=None), "parent", 2025, es)["basis"] == "no_nci", es
    # a filed zero NCI (nci_zero_filed): ProfitLoss is the parent's figure; with a positive net income the split is exactly 1
    zero_nci = isc.nci_share({"net_income": 1.0 * B, "net_income_incl_nci": 1.0 * B, "equity": 5.0 * B, "equity_incl_nci": 5.0 * B},
                             "nci_zero_filed", 2025, "nci_zero_filed")
    assert zero_nci["pi"] == 1.0 and zero_nci["stamps"] == []
    # NCI filed, neither split usable: unmeasured, pi = 1, stamped
    un = isc.nci_share(dict(neg, equity_incl_nci=-0.8 * B), "parent", 2025, "parent")
    assert un["basis"] == "unmeasured" and un["pi"] == 1.0 and un["stamps"] == [isc.NCI_UNMEASURED]
    assert isc.nci_share(dict(neg, equity_incl_nci=None), "parent", 2025, "parent")["basis"] == "unmeasured"   # SE filed, the NCI-inclusive not resolved
    # a base year whose net income scope is unknown: unmeasured, whatever the splits say
    unk = isc.nci_share(row, "nci_unknown", 2025)
    assert unk["basis"] == "nci_unknown" and unk["pi"] == 1.0 and unk["stamps"] == [isc.NCI_UNMEASURED]
    # a row written before Fix 1a (no field at all): pi = 1, its own stamp, no text
    old = isc.nci_share({"net_income": 1.2 * B, "equity": 6.0 * B}, None, 2025)
    assert old["basis"] == "scope_fields_absent" and old["pi"] == 1.0 and old["stamps"] == [isc.NCI_FIELDS_ABSENT]
    assert not isc.nci_text_due(old, [])
    # a filed zero is a value: an NCI equity of exactly the parent's means none filed
    zero = isc.nci_share({"net_income": 0.0, "net_income_incl_nci": 0.0, "equity": 0.0, "equity_incl_nci": 0.0}, "parent", 2025, "parent")
    assert zero["basis"] == "no_nci"


def test_1b1_an_unmeasured_share_is_printed_as_an_upper_bound_stamped_and_gated(screener_data_stub, monkeypatch):
    # NCI equity filed beside a negative parent equity, no consolidated net income: neither split usable
    doc = _doc(base_updates={"net_income_incl_nci": None, "equity": -1.0 * B, "equity_incl_nci": -0.8 * B})
    pack, call = _pack(monkeypatch, doc)
    f, text = pack.facts, str(pack)
    assert f["nci_attribution"]["pi"] == 1.0 and f["nci_attribution"]["basis"] == "unmeasured"
    assert isc.NCI_UNMEASURED in f["nci_attribution"]["stamps"]
    line = _ref_line(text)
    assert ("noncontrolling interests are filed but the common shareholders' share cannot be measured (neither the net-income nor the equity "
            "split is filed): this value includes their share of every level except net income, an upper bound") in line
    assert f["reference_status"] == "used" and f["consensus_implied_value"] is not None                 # printed and counted, never withheld
    assert "- NONCONTROLLING INTERESTS: FY2025: noncontrolling interests are filed" in text
    assert "- nci_attribution: π = 100.0% (not measurable, FY2025) | " in text
    stamps = isc.gate_stamps(f)
    assert isc.NCI_UNMEASURED in stamps
    _gate(stamps, "nci_share_unmeasured")


def test_1b1_a_base_year_with_an_unknown_net_income_scope_is_unmeasured(screener_data_stub, monkeypatch):
    doc = _doc(base_updates=NCI, prov_extra={"ni_scope": {"GEV": {"2025": "nci_unknown"}}})
    pack, call = _pack(monkeypatch, doc)
    f = pack.facts
    assert f["ni_scope"] == "nci_unknown" and f["nci_attribution"]["basis"] == "nci_unknown" and f["nci_attribution"]["pi"] == 1.0
    assert "net income included, an upper bound" in _ref_line(str(pack))
    assert isc.NCI_UNMEASURED in isc.gate_stamps(f)


def _gate_row(**over):
    row = {"direction": "undervalued", "gate_version": depth_gates.GATE_VERSION, "n_basis": 2, "fiduciary_verdict": "PASS",
           "kelly_fraction_pct": 5.0, "spread_pct": 10.0, "run_source": "orchestrator", "street_fence": {"low": 100.0, "high": 150.0},
           "median_iv": 120.0, "mos_vs_base_pct": 20.0, "flags": [], "producer_class": {"status": "ok", "depleting": False},
           "consensus_data_status": "ok", "pack_revision": 20, "crux_valid": True, "input_scope_stamps": []}
    row.update(over)
    return row


def _gate(stamps, reason):
    """A directional verdict carrying `stamps` is not actionable for `reason`; HOLD is unaffected; the row is judged, never changed."""
    assert depth_gates.GATE_VERSION == 8
    assert depth_gates.assess(_gate_row()) == (True, [])
    for dirn, over in (("undervalued", {}), ("overvalued", {"kelly_fraction_pct": 0.0})):
        row = _gate_row(direction=dirn, input_scope_stamps=list(stamps), **over)
        before = copy.deepcopy(row)
        ok, reasons = depth_gates.assess(row)
        assert ok is False and reasons == [reason] and row == before
    hold = _gate_row(direction="hold", input_scope_stamps=list(stamps))
    assert reason not in depth_gates.assess(hold)[1]


def test_gate_reasons_20_and_21_read_the_rows_stamps_and_nothing_else():
    _gate([isc.NCI_UNMEASURED], "nci_share_unmeasured")
    _gate([isc.PER_SHARE_UNVERIFIED], "per_share_basis_unverified")
    ok, reasons = depth_gates.assess(_gate_row(input_scope_stamps=[isc.NCI_UNMEASURED, isc.PER_SHARE_UNVERIFIED, isc.PER_SHARE_UNTESTED,
                                                                    isc.MONEY_EXCLUDED, isc.VENDOR_BREAK]))
    assert ok is False and reasons == ["nci_share_unmeasured", "per_share_basis_unverified"]
    # annotations that are not gate reasons, an absent field and a None field gate nothing
    assert depth_gates.assess(_gate_row(input_scope_stamps=[isc.PER_SHARE_UNTESTED, isc.MONEY_EXCLUDED, isc.LIABILITIES_EXCEED]))[0] is True
    for v in (None, "nci_share_unmeasured"):
        assert depth_gates.assess(_gate_row(input_scope_stamps=v))[0] is True
    row = _gate_row()
    row.pop("input_scope_stamps")
    assert depth_gates.assess(row)[0] is True
    # a row of gate version 7 is stale on the new version (reason 2), as every version bump does
    assert "pre_v3.1_gates" in depth_gates.assess(_gate_row(gate_version=7))[1]


def test_the_verdict_row_carries_the_packs_stamps(screener_data_stub, monkeypatch):
    """consensus_valuation writes the facts' stamps into consensus.json and depth_pipeline copies them onto the ledger row."""
    import consensus_valuation as cv
    import depth_pipeline as dp
    assert "input_scope_stamps" in Path(cv.__file__).read_text(encoding="utf-8")
    src = Path(dp.__file__).read_text(encoding="utf-8")
    assert '"input_scope_stamps": doc.get("input_scope_stamps")' in src
    assert isc.gate_stamps({"nci_attribution": {"stamps": ["b", "a"]}, "per_share_basis": {"stamps": ["a"]}}) == ["a", "b"]
    assert isc.gate_stamps(pack_facts.empty()) is None and isc.gate_stamps(None) is None


# ---- 1b-2: homogeneity ---------------------------------------------------------------------------------------------------------------------

def _consolidated_kwargs(monkeypatch, ni_parent, ni_cons, pi):
    """`reference_inputs`' kwargs with the attribution switched off, then put on the consolidated basis: the base and X carry the consolidated
    net income, and the share count is divided by pi."""
    with monkeypatch.context() as m:
        m.setattr(isc, "attribute_fy_base", lambda ref_fy, fy_rec, p: ref_fy)
        m.setattr(isc, "attribute_cash", lambda cash, p: cash)
        m.setattr(isc, "attribute_estimates", lambda est, p: est)
        kw = dict(_ri()["kwargs"])
    kw["base_cf"] = kw["base_cf"] + (ni_cons - ni_parent)
    kw["base_ni"] = kw["base_ni"] + (ni_cons - ni_parent)
    kw["shares"] = kw["shares"] / pi
    return kw


@pytest.mark.parametrize("bill", [0.04, None], ids=["cash-term", "no-cash-term"])
def test_1b2_the_attributed_levels_equal_the_consolidated_levels_over_shares_div_pi(screener_data_stub, monkeypatch, bill):
    _stubs(monkeypatch, _doc(base_updates=NCI), bill=bill)
    ri = _ri()
    pi = ri["scope"]["nci"]["pi"]
    assert ri["scope"]["nci"]["basis"] == "ni_split" and pi == pytest.approx(0.8)
    kw = ri["kwargs"]
    # every level but net income is attributed: the base, X's amortization, D&A, capex, revenue, the cash term and the vendor's revenue levels
    assert kw["base_cf"] == pytest.approx(1.2 * B + pi * (0.5 * B - 0.6 * B))
    assert kw["da"] == pytest.approx(pi * 0.5 * B) and kw["capex"] == pytest.approx(pi * 0.6 * B) and kw["base_revenue"] == pytest.approx(pi * 10.0 * B)
    for key in ("0y", "+1y"):
        for f in ("avg", "low", "high", "year_ago"):
            assert kw["estimates"][key]["revenue"][f] == pytest.approx(pi * EST[key]["revenue"][f])
        assert kw["estimates"][key]["revenue"]["growth"] == EST[key]["revenue"]["growth"] and kw["estimates"][key]["eps"] == EST[key]["eps"]
    assert EST["0y"]["revenue"]["avg"] == 10.8 * B                                                     # the vendor's own figures untouched
    attributed = cr.build(**kw)["value"]
    consolidated = cr.build(**_consolidated_kwargs(monkeypatch, 1.2 * B, 1.5 * B, pi))["value"]
    assert attributed is not None and abs(attributed / consolidated - 1) < 1e-9


def test_1b2_an_equity_split_name_keeps_the_parents_net_income_unscaled(screener_data_stub, monkeypatch):
    _stubs(monkeypatch, _doc(base_updates={"net_income_incl_nci": None, "equity_incl_nci": 7.5 * B}))
    ri = _ri()
    pi = ri["scope"]["nci"]["pi"]
    assert ri["scope"]["nci"]["basis"] == "equity_split" and pi == pytest.approx(0.8)
    kw = ri["kwargs"]
    assert kw["base_cf"] == pytest.approx(1.2 * B + pi * (0.5 * B - 0.6 * B))       # the parent's 1.2B stands
    x_parent = cap.throughcycle_record.adjusted_earnings(_doc()["tickers"]["GEV"]["2025"], [])
    assert kw["base_ni"] == pytest.approx(1.2 * B + pi * (x_parent - 1.2 * B))
    assert kw["base_cf"] != pytest.approx(pi * (1.2 * B + 0.5 * B - 0.6 * B))       # not pi x everything


# ---- 1b-3: pi = 1 changes nothing --------------------------------------------------------------------------------------------------------

def _switched_off(m):
    m.setattr(isc, "attribute_fy_base", lambda ref_fy, fy_rec, p: ref_fy)
    m.setattr(isc, "attribute_cash", lambda cash, p: cash)
    m.setattr(isc, "attribute_estimates", lambda est, p: est)
    m.setattr(isc, "record_view", lambda rows, scope=None, base_year=None, equity_scope=None: (rows, []))


def test_1b3_pi_of_one_changes_nothing(screener_data_stub, monkeypatch):
    # every year files a consolidated figure equal to the parent's: pi = 1 (net-income split), the view equals the rows
    doc = _doc(all_years=lambda y, r: {"net_income_incl_nci": r["net_income"], "equity_incl_nci": r["equity"]})
    pack_on, call_on = _pack(monkeypatch, doc)
    assert pack_on.facts["nci_attribution"]["pi"] == 1.0 and pack_on.facts["nci_attribution"]["basis"] == "ni_split"
    with monkeypatch.context() as m:
        _switched_off(m)
        pack_off, call_off = _pack(m, doc)
    assert call_on["out"]["value"] == call_off["out"]["value"] and str(pack_on) == str(pack_off)
    assert "NONCONTROLLING INTERESTS" not in str(pack_on) and "nci_attribution" not in str(pack_on)
    # and the history before Fix 1a (no field at all) gives the revision-19 pack apart from the revision line
    pack_old, call_old = _pack(monkeypatch, _doc())
    assert call_old["out"]["value"] == call_on["out"]["value"]


# ---- 1b-4: the record's view ---------------------------------------------------------------------------------------------------------------

def test_1b4_the_record_reads_consolidated_net_income_and_equity():
    rows = {"2024": {"net_income": 1.0, "net_income_incl_nci": 1.3, "equity": 5.0, "equity_incl_nci": 6.0, "revenue": 9.0},
            "2025": {"net_income": 1.2, "net_income_incl_nci": 1.5, "equity": 6.0, "equity_incl_nci": 7.5, "revenue": 10.0},
            "2023": {"net_income": 0.9, "equity": 4.0, "revenue": 8.0}}                          # written before Fix 1a: as filed
    view, mixed = isc.record_view(rows, {}, 2025)
    assert view["2025"]["net_income"] == 1.5 and view["2025"]["equity"] == 7.5 and view["2024"]["net_income"] == 1.3
    assert view["2023"] is rows["2023"] and rows["2025"]["net_income"] == 1.2 and mixed == []      # the rows themselves are not changed
    # a window year that falls back while NCI is filed: the consolidated equity unresolved, or a derived/unknown net income scope
    rows2 = dict(rows, **{"2024": {"net_income": 1.0, "net_income_incl_nci": None, "equity": 5.0, "equity_incl_nci": None}})
    assert isc.record_view(rows2, {}, 2025)[1] == [2024]
    rows3 = dict(rows, **{"2024": {"net_income": 1.0, "net_income_incl_nci": None, "equity": 5.0, "equity_incl_nci": 5.0}})
    assert isc.record_view(rows3, {}, 2025)[1] == []                                             # no NCI filed for it: not mixed
    assert isc.record_view(rows3, {2024: "parent_derived"}, 2025)[1] == [2024]
    rows4 = dict(rows, **{"2024": {"net_income": 1.0, "net_income_incl_nci": None, "equity": 5.0, "equity_incl_nci": 5.5}})
    assert isc.record_view(rows4, {}, 2025)[1] == [2024]                                         # NCI equity filed, the income falls back
    assert isc.record_view(rows3, {}, 2025, {2024: "nci_unknown"})[1] == [2024]                  # the equity scope shows NCI
    assert isc.record_view(rows3, {}, 2025, {2024: "nci_zero_filed"})[1] == []
    # outside the eight-year window: not stamped
    rows5 = dict(rows, **{"2016": {"net_income": 1.0, "net_income_incl_nci": None, "equity": 5.0, "equity_incl_nci": None}})
    assert isc.record_view(rows5, {}, 2025)[1] == []
    assert isc.mixed_stamp([2019, 2020]) == "record_scope_mixed:2019/2020" and isc.mixed_stamp([]) is None


def test_1b4_the_packs_record_is_the_view_and_the_mixed_years_are_stamped_and_printed(screener_data_stub, monkeypatch):
    def nci_years(y, r):
        if y == 2019:                                                       # NCI equity filed, the consolidated income not resolved
            return {"net_income_incl_nci": None, "equity_incl_nci": r["equity"] * 1.25}
        return _with_nci(y, r)
    pack, call = _pack(monkeypatch, _doc(all_years=nci_years))
    f, text = pack.facts, str(pack)
    rec = call["kwargs"]["record"]
    assert rec["scope_mixed_years"] == [2019] and "record_scope_mixed:2019" in f["nci_attribution"]["stamps"]
    assert "where only the company's own figures are filed (record_scope_mixed:2019)" in text
    # the record's returns read consolidated net income over consolidated equity: they differ from the parent-basis record
    plain, call_plain = _pack(monkeypatch, _doc())
    assert rec["R"] != call_plain["kwargs"]["record"]["R"]
    # DATA 5 prints both net income figures where they differ
    assert "| net income | net income incl. NCI |" in text and "`net income incl. NCI` is the consolidated figure" in text


# ---- 1b-5: the TTM window, the cash bound, the DEFAULTS and the desk -------------------------------------------------------------------------

def test_1b5_the_window_the_cash_bound_and_the_defaults_use_pi_and_the_desk_equals_the_reference(screener_data_stub, monkeypatch):
    plain, call_plain = _pack(monkeypatch, _doc())
    nci, call = _pack(monkeypatch, _doc(all_years=_with_nci))
    f0, f = plain.facts, nci.facts
    pi = f["nci_attribution"]["pi"]
    assert pi == pytest.approx(0.8) and f["nci_attribution"]["basis"] == "ni_split"
    # the cash term, the desk's cash bound and the reference's base: pi x
    assert f["excess_cash"] == pytest.approx(pi * f0["excess_cash"], abs=2e-6)
    assert f["base_year_cash_and_investments_b"] == pytest.approx(pi * f0["base_year_cash_and_investments_b"], abs=2e-6)
    assert call["kwargs"]["cash"]["cash"] == pytest.approx(pi * call_plain["kwargs"]["cash"]["cash"])
    assert call["kwargs"]["cash"]["interest"] == pytest.approx(pi * call_plain["kwargs"]["cash"]["interest"])
    # the TTM window's owner earnings (the OWNER EARNINGS default): TTM net income + pi x (D&A - capex) - pi x the interest on the cash
    ttm = cap.DataRoot().ttm("GEV").get("fields") or {}
    if isinstance(ttm.get("net_income"), (int, float)) and isinstance(ttm.get("capex"), (int, float)):
        i_l = call["kwargs"]["cash"]["interest"]
        assert f["owner_earnings_default_b"] == pytest.approx((ttm["net_income"] + pi * (0.5 * B - ttm["capex"]) - i_l) / B, abs=0.0011)
        assert "π 80.0% × (D&A (FY2025)" in str(nci)
    # the window check compares the attributed TTM base with the attributed fiscal-year base
    seen = []
    real_wc = cr.window_check
    monkeypatch.setattr(cr, "window_check", lambda ref, fy_base, ttm_base, q: seen.append((fy_base, ttm_base)) or real_wc(ref, fy_base, ttm_base, q))
    _pack(monkeypatch, _doc(all_years=_with_nci))
    assert seen and seen[-1][0] == pytest.approx(call["kwargs"]["base_cf"])
    # the reference line and the DEFAULTS say so
    text = str(nci)
    assert "consolidated business attributed to the common shares at π = 80.0%" in _ref_line(text)
    assert ("- NONCONTROLLING INTERESTS: FY2025 net income attributable to the company $1.200B of consolidated $1.500B (π = 80.0%, net-income "
            "split); the reference values the consolidated business and attributes π of it to the common shares") in text
    assert "- nci_attribution: π = 80.0% (net-income split, FY2025) | the defaults are the common shares' share" in text
    parsed = pack_facts.from_text(text)
    assert pack_facts.parity(f, parsed) == [] and parsed["nci_attribution"] is None                    # display-only, sidecar-only
    # AT1a: the desk on the printed facts equals the reference to $0.005
    ref = call["out"]
    args, why = cr.defaults_desk_args(ref, parsed)
    assert why is None
    real_round = getattr(fmt, "round", None)
    fmt.round = lambda x, nd=None: x
    try:
        res = fmt.unbundled_dcf(**args)
    finally:
        if real_round is None:
            del fmt.round
        else:
            fmt.round = real_round
    assert abs(res["per_share_iv"] - ref["value"]) < 0.005


# ---- 1c-1: the per-share check -------------------------------------------------------------------------------------------------------------

def test_1c1_the_identity_its_tolerance_and_the_untested_cases():
    row = {"net_income": 1.2 * B, "shares_diluted": 500e6, "eps_diluted": 2.40}
    ok = isc.per_share_check(row, 2025)
    assert ok["status"] == "verified" and ok["n_common_source"] == "net_income" and ok["gap"] == pytest.approx(0.0, abs=1e-12)
    assert ok["tolerance"] == pytest.approx(0.005 / 2.40 + 0.005) and ok["stamps"] == []
    # just inside and just outside X = 0.005 / |EPS| + 0.005
    x = 0.005 / 2.40 + 0.005
    assert isc.per_share_check(dict(row, net_income=2.40 * 500e6 * (1 + x * 0.999)))["status"] == "verified"
    out = isc.per_share_check(dict(row, net_income=2.40 * 500e6 * (1 + x * 1.001)), 2025)
    assert out["status"] == "unverified" and out["stamps"] == [isc.PER_SHARE_UNVERIFIED]
    # the available-to-common figure first, then net income less preferred dividends
    avail = isc.per_share_check(dict(row, net_income=1.3 * B, net_income_available_to_common_diluted=1.2 * B, preferred_dividends=0.1 * B))
    assert avail["n_common_source"] == "available_to_common" and avail["status"] == "verified"
    pref = isc.per_share_check(dict(row, net_income=1.3 * B, preferred_dividends=0.1 * B))
    assert pref["n_common_source"] == "net_income_less_preferred_dividends" and pref["status"] == "verified"
    assert isc.per_share_check(dict(row, net_income=1.3 * B))["status"] == "unverified"
    # a preferred dividend of 0.0 is a value
    assert isc.per_share_check(dict(row, preferred_dividends=0.0))["n_common_source"] == "net_income_less_preferred_dividends"
    # untested: |EPS| below $0.05, a missing fact, no shares
    for bad in (dict(row, eps_diluted=0.049), dict(row, eps_diluted=-0.04), dict(row, eps_diluted=None), dict(row, shares_diluted=None),
                dict(row, shares_diluted=0.0), dict(row, net_income=None), {k: v for k, v in row.items() if k != "eps_diluted"}):
        r = isc.per_share_check(bad)
        assert r["status"] == "untested" and r["stamps"] == [isc.PER_SHARE_UNTESTED], bad
    assert isc.per_share_check(dict(row, eps_diluted=-0.05, net_income=-0.025 * B))["status"] == "verified"


def test_1c1_an_unverified_basis_is_printed_with_both_figures_kept_in_the_facts_and_gated(screener_data_stub, monkeypatch):
    pack, call = _pack(monkeypatch, _doc(base_updates={"eps_diluted": 2.00}))
    f, text = pack.facts, str(pack)
    ps = f["per_share_basis"]
    assert ps["status"] == "unverified" and ps["eps_filed"] == 2.0 and ps["eps_implied"] == pytest.approx(2.4) and ps["gap"] == pytest.approx(0.2)
    figures = ("FY2025 net income / filed diluted shares = $2.40 against the filed diluted EPS $2.00 (+20.00%, beyond the reporting precision "
               "of ±0.75%)")
    assert f"- PER-SHARE CHECK: {figures}: the per-share basis of the filed figures is not verified (per_share_basis_unverified)" in text
    assert f"per-share basis not verified: {figures}" in _ref_line(text)
    assert f["reference_status"] == "used"                                                       # still printed
    _gate(isc.gate_stamps(f), "per_share_basis_unverified")
    verified, _ = _pack(monkeypatch, _doc(base_updates={"eps_diluted": 2.40}))
    assert verified.facts["per_share_basis"]["status"] == "verified" and "PER-SHARE CHECK" not in str(verified)
    untested, _ = _pack(monkeypatch, _doc())
    assert untested.facts["per_share_basis"]["status"] == "untested" and isc.PER_SHARE_UNTESTED in isc.gate_stamps(untested.facts)
    assert depth_gates.assess(_gate_row(input_scope_stamps=isc.gate_stamps(untested.facts)))[0] is True


# ---- 2b-1: the cash term and customer money --------------------------------------------------------------------------------------------------

def test_2b1_the_annotations_change_no_number_and_say_what_the_cash_excludes(screener_data_stub, monkeypatch):
    plain, call_plain = _pack(monkeypatch, _doc())
    money = {"cash_restricted": 0.02 * B, "customer_money_assets": 0.10 * B, "customer_money_liabilities": 0.30 * B,
             "insurance_reserves": 0.05 * B}
    ann, call = _pack(monkeypatch, _doc(base_updates=money), )
    assert call["out"]["value"] == call_plain["out"]["value"] and ann.facts["excess_cash"] == plain.facts["excess_cash"]
    assert call["kwargs"]["cash"] == call_plain["kwargs"]["cash"]                     # the cash term reads `cash`, the unrestricted line
    cm = ann.facts["customer_money"]
    assert cm["assets_b"] == 0.1 and cm["liabilities_b"] == 0.3 and cm["gap_b"] == pytest.approx(0.18)
    assert cm["stamps"] == [isc.MONEY_EXCLUDED, isc.LIABILITIES_EXCEED, isc.INSURANCE_FLOAT]
    assert ann.facts["cash_restricted_b"] == 0.02 and ann.facts["insurance_reserves_b"] == 0.05
    line = _ref_line(str(ann))
    assert ("; the excess cash is the unrestricted cash line: excludes restricted cash $0.020B, customer money held $0.100B, customer "
            "liabilities $0.300B (customer_money_excluded); customer liabilities exceed the separate customer assets and restricted cash by "
            "$0.180B: the unrestricted line may be funding customer obligations (customer_liabilities_exceed_separate_assets); insurance "
            "reserves $0.050B (insurance_float_present)") in line
    assert "- Total Cash & Cash Equivalents: $" in str(ann) and "(customer_money_excluded)" in str(ann).split("DATA 6 -", 1)[1]
    # a financial company: no insurance-float stamp (the engine's financial-sector rule treats it as operating)
    assert isc.INSURANCE_FLOAT not in isc.customer_money(money, financial=True)["stamps"]
    # the scope is printed when it is not the unrestricted line
    scoped, _ = _pack(monkeypatch, _doc(prov_extra={"cash_scope": {"GEV": {"2025": "total_no_restricted_filed"}}}))
    assert scoped.facts["cash_scope"] == "total_no_restricted_filed" and "cash_scope total_no_restricted_filed" in _ref_line(str(scoped))
    # the follow-up's null cell (only CashAndSecurities...Segregated filed beside the cash-flow total): the cash term is not available and both
    # lines say why
    seg, call_seg = _pack(monkeypatch, _doc(base_updates={"cash": None},
                                            prov_extra={"cash_scope": {"GEV": {"2025": "cash_unresolved_securities_segregated"}}}))
    assert call_seg["kwargs"]["cash"]["applies"] is False and seg.facts["excess_cash"] is None
    assert ("no excess-cash term (not available: cash_term_not_available); cash_scope cash_unresolved_securities_segregated"
            in _ref_line(str(seg)))
    # nothing filed: no annotation
    assert isc.customer_money({}, financial=False) == {"cash_restricted": None, "assets": None, "liabilities": None, "insurance_reserves": None,
                                                       "gap": None, "stamps": []}
    assert isc.cash_note("unrestricted_line", isc.customer_money({}, False), str) is None


# ---- 3-1: the vendor's revenue-basis break ---------------------------------------------------------------------------------------------------

def _est(s, k=None, eps_growth=None):
    """Estimates whose revenue step is s = ln(R1 / R0) and whose EPS step over it is k = ln((1 + c2) / (R1 / R0))."""
    r0 = 10.0 * B
    ratio = math.exp(s)
    c2 = eps_growth if eps_growth is not None else math.exp(k) * ratio - 1.0
    e = copy.deepcopy(EST)
    e["0y"]["revenue"].update(avg=r0)
    e["+1y"]["revenue"].update(avg=r0 * ratio, growth=ratio - 1.0, year_ago=r0)
    e["+1y"]["eps"].update(growth=c2, avg=e["0y"]["eps"]["avg"] * (1 + c2), year_ago=e["0y"]["eps"]["avg"])
    return e


def test_3_1_the_frozen_thresholds_just_inside_and_just_outside():
    lo, hi, klo, khi = RULE["rev_step_lo"], RULE["rev_step_hi"], RULE["k_lo"], RULE["k_hi"]
    assert (lo, hi, klo, khi) == (-0.10850538577173424, 0.4431367450274345, -0.39540604417565023, 0.7484252589850702)
    e = 1e-7
    assert isc.vendor_revenue_basis(_est(hi + e, klo - e))["status"] == "break_up"
    assert isc.vendor_revenue_basis(_est(hi - e, klo - e))["status"] == "consistent"
    assert isc.vendor_revenue_basis(_est(hi + e, klo + e))["status"] == "consistent"
    assert isc.vendor_revenue_basis(_est(lo - e, khi + e))["status"] == "break_down"
    assert isc.vendor_revenue_basis(_est(lo + e, khi + e))["status"] == "consistent"
    assert isc.vendor_revenue_basis(_est(lo - e, khi - e))["status"] == "consistent"
    up = isc.vendor_revenue_basis(_est(0.6, -0.5))
    assert up["stamps"] == [isc.VENDOR_BREAK] and up["s"] == pytest.approx(0.6) and up["k"] == pytest.approx(-0.5)
    assert up["c2"] == pytest.approx(math.exp(-0.5) * math.exp(0.6) - 1)


def test_3_1_the_untestable_domain():
    # EPS growth off a trough (beyond +150%): untested; a step outside the band is annotated, one inside is not
    out = isc.vendor_revenue_basis(_est(0.6, eps_growth=2.0))
    assert out["status"] == "untested" and out["k"] is None and out["stamps"] == [isc.VENDOR_UNTESTED]
    assert isc.vendor_revenue_basis(_est(0.1, eps_growth=2.0))["stamps"] == []
    neg = _est(0.6, -0.5)
    neg["+1y"]["eps"]["year_ago"] = -0.1                                                         # a non-positive EPS base
    assert isc.vendor_revenue_basis(neg)["status"] == "untested"
    none = copy.deepcopy(EST)
    none["+1y"]["revenue"] = {}
    assert isc.vendor_revenue_basis(none)["status"] == "not_available" and isc.vendor_revenue_basis(None)["status"] == "not_available"


def test_3_1_on_a_break_build_gets_the_estimates_without_the_next_fy_revenue(screener_data_stub, monkeypatch):
    est = _est(math.log(1.9), math.log(1.1111 / 1.9))
    est["0y"]["revenue"].update(avg=10.8 * B, year_ago=10.0 * B)
    est["+1y"]["revenue"].update(avg=10.8 * B * 1.9, year_ago=10.8 * B, growth=0.9)
    est["+1y"]["eps"].update(growth=0.1111, avg=3.0, year_ago=2.7)
    assert isc.vendor_revenue_basis(est)["status"] == "break_up"
    pack, call = _pack(monkeypatch, _doc(), est=est)
    sent, ref = call["kwargs"]["estimates"], call["out"]
    assert sent["+1y"]["revenue"] == {} and sent["0y"] == est["0y"] and sent["+1y"]["eps"] == est["+1y"]["eps"]
    assert est["+1y"]["revenue"]["avg"] == pytest.approx(10.8 * B * 1.9)                          # the vendor's record is untouched
    assert ref["path"][2:] == pytest.approx([0.05, 0.05, 0.05])                                  # years 3-5 at the base-rate median
    assert ref["revenue"] is None and ref["long_run_path"] == "owner_earnings_ratio"            # no revenue path
    f, text = pack.facts, str(pack)
    assert f["vendor_revenue_basis"]["status"] == "break_up" and f["vendor_revenue_basis"]["s"] == pytest.approx(math.log(1.9))
    assert ("(years 1-2 consensus EPS growth; years 3-5 fade from the base-rate median: the vendor's next-FY revenue step (+90.0%) is not "
            "carried by its EPS step (+11.1%), a change of level, not a growth rate)") in _ref_line(text)
    assert "| next FY | $20.520B |" in text                                                       # DATA 8 prints the vendor's figures as they are
    # the terminal-growth default reads the vendor's figures as they are (the record's own trend first)
    assert f["long_run"]["terminal_g_basis"] == "revenue_trend"


def test_3_1_an_untested_step_outside_the_band_is_one_clause(screener_data_stub, monkeypatch):
    est = copy.deepcopy(EST)
    est["+1y"]["revenue"].update(avg=10.8 * B * 1.9, growth=0.9)
    est["+1y"]["eps"].update(growth=2.0)                                                          # off a trough: untestable
    pack, call = _pack(monkeypatch, _doc(), est=est)
    assert pack.facts["vendor_revenue_basis"]["status"] == "untested" and call["kwargs"]["estimates"]["+1y"]["revenue"]["avg"] == 10.8 * B * 1.9
    assert ("the vendor's next-FY revenue step (+90.0%) could not be tested against its EPS step (consensus EPS growth is not usable here)"
            in _ref_line(str(pack)))


def test_3_1_the_threshold_file_is_checked_on_load_and_a_mismatch_refuses(tmp_path):
    raw = isc.RULE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == isc.RULE_SHA256 == "edd178cdea29e6246669df7622fafe667cefdc05230b58e022e3844a1271e3be"
    bad = tmp_path / "rule.json"
    bad.write_bytes(raw.replace(b"0.4431367450274345", b"0.4431367450274346"))
    with pytest.raises(RuntimeError, match="refused"):
        isc.break_rule(path=bad)
    good = tmp_path / "copy.json"
    good.write_bytes(raw)
    assert isc.break_rule(path=good) == RULE


# ---- the new history fields are reviewed -----------------------------------------------------------------------------------------------------

def test_the_new_history_fields_are_reviewed_and_the_sensor_stays_silent(screener_data_stub, monkeypatch):
    six = {"net_income_incl_nci", "equity_incl_nci", "cash_restricted", "customer_money_assets", "customer_money_liabilities", "insurance_reserves"}
    assert six <= cap.REVIEWED_HISTORY_KEYS and set(isc.HISTORY_FIELDS) <= cap.REVIEWED_HISTORY_KEYS
    every = {f: 0.01 * B for f in isc.HISTORY_FIELDS}
    every.update(eps_diluted=2.4, net_income_incl_nci=1.2 * B, equity_incl_nci=6.0 * B)
    pack, _ = _pack(monkeypatch, _doc(base_updates=every))
    assert "UNREVIEWED FIELDS PRESENT" not in str(pack)
    assert cap._unreviewed_history_fields({"2025": dict(every, some_new_field=1)}) == ["some_new_field"]

"""Revision 18, amendment 2, point 2: a missing provenance marker is a stated gap, never a silent change of basis.

`capability_test` used to read the marker as `(...get("untagged_fields") or {}).get(t) or []`, so a name the field extractor never
processed read the same as a name that tags every field, and its record was computed without subtracting goodwill and intangibles.
Now a missing entry means NO marker and `[]` means a marker with nothing untagged:
  - a name with no marker has no reference: status not_available, with the reason "the screener history has no tangible-capital
    fields for this name"; the DEFAULTS lines derived from its record (terminal_ronic, long_run, working_capital) print
    "not available" with the same reason;
  - tools/reference_closure.py refuses to build when an aggregate name has no marker, and names the count.
Names that carry a marker (all of the book's names) never reach this path: the pack text of the GEV fixture is unchanged (the golden
pack and the model-visible-change pin hold it; this file shows the three marker cases next to each other).
"""
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import pack_facts  # noqa: E402
import reference_closure as rc  # noqa: E402
import rs2_data  # noqa: E402
from test_rev18_part2 import _Root, _anchors, _rows  # noqa: E402
from test_throughcycle_reference import EST, _synthetic_pack  # noqa: E402

REASON = "the screener history has no tangible-capital fields for this name"


# ---- reading the marker ---------------------------------------------------------------------------------------------------

def test_a_missing_entry_means_no_marker_and_an_empty_list_means_a_marker_with_nothing_untagged():
    doc = {"provenance": {"untagged_fields": {"AAA": [], "BBB": ["goodwill", "amortization_intangibles"]}}}
    assert cap._marker_for(doc, "AAA") == []                                        # a marker: nothing untagged
    assert cap._marker_for(doc, "BBB") == ["goodwill", "amortization_intangibles"]  # a marker: partial
    assert cap._marker_for(doc, "CCC") is None                                      # no marker
    for bare in ({}, {"provenance": {}}, {"provenance": {"untagged_fields": {}}}, {"provenance": None}, {"provenance": {"untagged_fields": None}}):
        assert cap._marker_for(bare, "AAA") is None, bare                           # production's file: no marker for any name


def test_the_data_root_tells_the_cases_apart(monkeypatch):
    root = cap.DataRoot(sd=Path("."))
    root._hist = {"tickers": {}, "provenance": {"untagged_fields": {"AAA": [], "BBB": ["goodwill"]}}}
    assert root.untagged("AAA") == [] and root.untagged("AAA") is not None
    assert root.untagged("BBB") == ["goodwill"] and root.untagged("CCC") is None


# ---- build ----------------------------------------------------------------------------------------------------------------

def test_build_gives_no_value_and_the_reason_when_told_the_history_is_unreadable():
    kw = dict(base_cf=1.1e9, estimates=EST, coe=0.09, terminal_g=0.0375, shares=500e6, median_5y=0.05, base_ni=1.2e9, base_revenue=10e9)
    ok = cr.build(**kw)
    assert ok["value"] is not None and ok["reason"] is None
    out = cr.build(**kw, unavailable_reason=REASON)
    assert out["value"] is None and out["reason"] == REASON == cr.NO_MARKER_REASON and out["stamps"] == ["no_tangible_capital_marker"]
    assert out["long_run"] is None and out["wc"] is None and out["terminal_ronic"] is None and out["path"] is None


# ---- the pack: the three marker cases, side by side -------------------------------------------------------------------------

def _line(text, prefix):
    return next(l for l in text.splitlines() if l.startswith(prefix))


def test_a_name_with_no_marker_gets_no_reference_and_the_defaults_lines_say_why(screener_data_stub, monkeypatch):
    pack = _synthetic_pack(monkeypatch, no_marker=True)
    f, text = pack.facts, str(pack)
    assert f["reference_status"] == "not_available" and f["consensus_implied_value"] is None
    # the record's members are empty; the age of the base fiscal year is not part of the record and stays (finding 17)
    assert f["terminal_ronic"] is None and f["working_capital"] is None and f["reference_base_b"] is None
    assert f["long_run"]["stub_months"] is not None and all(v in (None, []) for k, v in f["long_run"].items() if k != "stub_months")
    # restated for pack revision 24 (R24.2): the line is not printed; the facts keep it
    assert "- CONSENSUS-IMPLIED VALUE" not in text and f["reference_line"] == f"- CONSENSUS-IMPLIED VALUE: not available — {REASON}"
    assert "CONSENSUS-IMPLIED VALUE (reference" not in text
    # revision 24 step 2b: the revision-24 pack prints no terminal_ronic line (a long-run default); the rev22 arm prints it, not available
    assert "\n- terminal_ronic: " not in text
    text22 = str(_synthetic_pack(monkeypatch, no_marker=True, pilot_arm="rev22"))
    assert _line(text22, "- terminal_ronic:").startswith(f"- terminal_ronic: not available | not available: {REASON}")
    for key in ("working_capital",):
        assert _line(text, f"- {key}:").startswith(f"- {key}: not available | not available: {REASON}"), key
    assert _line(text, "- long_run:").startswith("- long_run: cycle=none, ") and f" | not available: {REASON}" in _line(text, "- long_run:")
    assert "- reference_status:" not in text                                     # revision 24: not printed; the facts hold not_available
    assert pack_facts.parity(f, pack_facts.from_text(text)) == []               # the printed lines still read back as the facts


def test_a_name_with_no_marker_keeps_stub_months_and_the_desk_still_rolls_the_value_forward(screener_data_stub, monkeypatch):
    """Revision 18 follow-up, finding 17: stub_months (the base fiscal year's age) is not part of the record. Dropping it with the record made
    the desk skip the roll-forward to today without a stamp (financial_model_tool: roll = 1 without a stub)."""
    import financial_model_tool as fmt
    marker = _synthetic_pack(monkeypatch)
    nomarker = _synthetic_pack(monkeypatch, no_marker=True)
    stub = marker.facts["long_run"]["stub_months"]
    assert stub is not None and nomarker.facts["long_run"]["stub_months"] == stub
    parsed = pack_facts.from_text(str(nomarker))
    assert parsed["long_run"]["stub_months"] == stub and parsed["long_run"]["r_tc"] is None
    assert pack_facts.parity(nomarker.facts, parsed) == []
    path = [0.08, 0.07, 0.06, 0.05, 0.05]
    desk = lambda p: fmt.unbundled_dcf(base_cf=p["owner_earnings_default_b"], explicit_growth=path, wacc=p["coe_anchor"], terminal_g=p["terminal_g_default"],
                                       shares_diluted=p["shares_default"] / 1e9, fade_years=5, sbc_treatment="deducted_in_cf",
                                       terminal_ronic=p.get("terminal_ronic"), long_run=p.get("long_run"), working_capital=p.get("working_capital"),
                                       excess_cash=p.get("excess_cash"))
    out = desk(parsed)
    assert out["roll_forward_factor"] == pytest.approx((1.0 + parsed["coe_anchor"]) ** (stub / 12.0), abs=1e-6) and out["roll_forward_factor"] > 1.0
    assert desk(dict(parsed, long_run={}))["roll_forward_factor"] == 1.0           # what the desk did before the stub was kept


def test_a_marker_of_nothing_untagged_and_a_partial_marker_still_give_a_reference(screener_data_stub, monkeypatch):
    for untagged in ((), ("goodwill",), ("goodwill", "intangibles_ex_goodwill"), ("amortization_intangibles",)):
        pack = _synthetic_pack(monkeypatch, untagged=untagged)
        f, text = pack.facts, str(pack)
        assert f["reference_status"] == "used" and f["consensus_implied_value"] is not None, untagged
        assert REASON not in text, untagged
        assert f["terminal_ronic"] is not None and f["long_run"] and f["working_capital"] is not None, untagged
        assert "CONSENSUS-IMPLIED VALUE (reference, not a forecast)" in text


def test_the_marker_changes_nothing_for_a_name_that_carries_one(screener_data_stub, monkeypatch):
    """The guard is a code path the book's names never reach: with a marker present, the pack's text is the text of the code before
    this change. (tests/.../test_no_model_visible_change.py pins the GEV golden pack byte for byte; here the two ways of carrying a
    marker - [] and a partial list - differ from each other only through the record, as they always did.)"""
    plain, partial = _synthetic_pack(monkeypatch), _synthetic_pack(monkeypatch, untagged=["goodwill"])
    assert REASON not in str(plain) and REASON not in str(partial)
    assert str(plain) != str(partial)           # a partial marker is read, not ignored


# ---- reference_inputs -----------------------------------------------------------------------------------------------------

def test_reference_inputs_flags_the_missing_marker_and_build_follows(screener_data_stub, monkeypatch):
    _synthetic_pack(monkeypatch)                                                    # installs the synthetic history reader
    sector = rs2_data.sector_lookup("GEV")[0]
    base = dict(t="GEV", estimates=EST, today=date(2026, 9, 27), printed=True,
                anchors=_anchors(sector=sector), closure={"erp": 0.05})

    def root_for(marker):
        root = cap.DataRoot()
        doc = root.hist_doc()
        prov = dict(doc.get("provenance") or {})
        un = dict(prov.get("untagged_fields") or {})
        un.pop("GEV", None)
        if marker is not None:
            un["GEV"] = marker
        root._hist = dict(doc, provenance=dict(prov, untagged_fields=un))
        return root

    def ri_for(marker):
        return cap.reference_inputs(root=root_for(marker), **base)

    for marker in ([], ["goodwill"]):
        ri = ri_for(marker)
        assert ri["no_marker"] is False and ri["kwargs"]["unavailable_reason"] is None
        assert cr.build(**ri["kwargs"])["value"] is not None
    ri = ri_for(None)
    assert ri["no_marker"] is True and ri["kwargs"]["unavailable_reason"] == REASON
    out = cr.build(**ri["kwargs"])
    assert out["value"] is None and out["reason"] == REASON
    # the premium missing as well: the data defect is the reason that is stated
    gone = cap.reference_inputs(root=root_for(None), **dict(base, closure=None))
    assert gone["coe"] is None and cr.build(**gone["kwargs"])["reason"] == REASON


# ---- the closure's refusal ------------------------------------------------------------------------------------------------

class _MarkedRoot(_Root):
    """Written-down companies; `markers` is {ticker: marker list} - a ticker absent from it has NO marker."""

    def __init__(self, companies, markers):
        super().__init__(companies)
        self.markers = markers

    def untagged(self, t):
        return self.markers.get(t)


class _Anchors:
    """The four accessors build_closure reads first, and the sector lookups it makes for the aggregate."""
    def anchor_risk_free_rate(self):
        return 0.0501, "stub"

    def anchor_terminal_g(self):
        return 0.0375, "stub"

    def anchor_breakeven_10y(self):
        return 0.0234, "stub"

    def anchor_mature_erp(self):
        return 0.045, "stub"

    def sector_lookup(self, t):
        return "Industrials", "x"

    def coe_loading(self, sector):
        return 0.9, 0.9, "stub"

    def load_json(self, p):
        return None

    enrich_fetch_error = staticmethod(rs2_data.enrich_fetch_error)


def _companies(n):
    return {f"Z{i:02d}": ({"Market_Cap": 1e9 + i * 1e6, "FX": None, "Shares_Outstanding": 1e6}, _rows(), str(i)) for i in range(n)}


def test_the_closure_refuses_to_build_when_an_aggregate_name_has_no_marker_and_names_the_count(tmp_path):
    companies = _companies(10)
    markers = {t: [] for t in companies}
    for t in list(companies)[:3]:
        markers.pop(t)                                                              # three names the extractor never processed
    with pytest.raises(rc.Refused) as e:
        rc.build_closure(root=_MarkedRoot(companies, markers), cap_mod=cap, rs2_mod=_Anchors(), enrich_dir=tmp_path, asof="2026-10-02")
    msg = str(e.value)
    assert "3 of the aggregate's 10 names have no tangible-capital provenance marker" in msg and "nothing is published" in msg
    assert not any(t in msg for t in companies)                                     # a count, no ticker


def test_a_marker_of_nothing_untagged_or_a_partial_one_passes_the_closures_marker_check(tmp_path):
    companies = _companies(10)
    markers = {t: ([] if i % 2 else ["goodwill"]) for i, t in enumerate(companies)}
    with pytest.raises(rc.Refused) as e:                                            # past the marker check, the later floor refuses
        rc.build_closure(root=_MarkedRoot(companies, markers), cap_mod=cap, rs2_mod=_Anchors(), enrich_dir=tmp_path, asof="2026-10-02")
    assert "coverage floor" in str(e.value) and "provenance marker" not in str(e.value)


class _AnchorsReadingFiles(_Anchors):
    def load_json(self, p):
        return rs2_data.load_json(p)


def test_a_failed_vendor_fetch_in_the_consensus_cache_refuses_the_closure_and_is_not_no_coverage(tmp_path):
    """Revision 18 follow-up, finding 18: an error record has no `estimates`, so reading it as such counted a vendor outage as a name
    with no coverage and solved the closure on a smaller set. The record is asked first, and the build refuses, naming no ticker."""
    import json
    companies = _companies(10)
    markers = {t: [] for t in companies}
    (tmp_path / "Z03.json").write_text(json.dumps({"_ticker": "Z03", "_fetched_at": "2026-10-02T00:00:00+00:00", "_status": "error",
                                                   "_error": {"http_status": 503, "where": "info"}}), encoding="utf-8")
    with pytest.raises(rc.Refused) as e:
        rc.build_closure(root=_MarkedRoot(companies, markers), cap_mod=cap, rs2_mod=_AnchorsReadingFiles(), enrich_dir=tmp_path, asof="2026-10-02")
    msg = str(e.value)
    assert "error record of a failed vendor fetch (HTTP 503 at info)" in msg and "nothing is published" in msg and not any(t in msg for t in companies)
    # a no-coverage record (a good record whose estimates are null) is not a refusal for this reason (a new folder: json loads may be cached by path)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "Z03.json").write_text(json.dumps({"_ticker": "Z03", "_fetched_at": "2026-10-02T00:00:00+00:00", "estimates": None}), encoding="utf-8")
    with pytest.raises(rc.Refused) as e2:
        rc.build_closure(root=_MarkedRoot(companies, markers), cap_mod=cap, rs2_mod=_AnchorsReadingFiles(), enrich_dir=fresh, asof="2026-10-02")
    assert "coverage floor" in str(e2.value) and "vendor" not in str(e2.value)


def test_the_check_counts_only_a_missing_entry(tmp_path):
    cons = [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}]
    rc.check_markers(cons, _MarkedRoot({}, {"A": [], "B": ["goodwill"], "C": []}))               # no refusal
    with pytest.raises(rc.Refused, match="1 of the aggregate's 3"):
        rc.check_markers(cons, _MarkedRoot({}, {"A": [], "B": ["goodwill"]}))


# ---- the GEV fixture: unchanged with a marker, and only the stated lines change without one -------------------------------------
# (the committed slice of the history predates brief A and holds no marker; the stub in conftest.py gives GEV the marker [], which is
# what the code read for a missing marker before this change - so the golden pack holds - and this test takes it away again)

def _gev_fixture_pack(monkeypatch, marker, tmp_path):
    """build_pack("GEV") on the committed fixture slice exactly as test_no_model_visible_change.test_pack_byte_pin builds it; `marker`
    False builds it on a copy of the data directory (a new path: common.enable_json_cache caches files by path) from which the marker
    the stub gave GEV is removed (the slice predates brief A)."""
    import json
    import shutil
    import socket
    import common
    from datetime import datetime as _real
    import catalyst_research
    import valuation_backbone

    class _Blocked(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("Socket access blocked in test")
    monkeypatch.setattr(socket, "socket", _Blocked)
    monkeypatch.setattr(cap.company_news, "fetch", lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [], "errors": ["stubbed"]})
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)
    import gev_primary_fixture
    gev_primary_fixture.install(monkeypatch)                      # revision 21: the PRIMARY SOURCES section reads GEV's committed filings

    class _Frozen(_real):
        @classmethod
        def now(cls, tz=None):
            return _real(2026, 9, 27, 12, 0, 0)
    for mod in (cap, rs2_data, catalyst_research, valuation_backbone):
        monkeypatch.setattr(mod, "datetime", _Frozen, raising=False)
    if not marker:
        sd = tmp_path / "data_without_marker"
        shutil.copytree(cap.SD, sd)
        hist = sd / "fundamentals_history.json"
        doc = json.loads(hist.read_text(encoding="utf-8"))
        doc["provenance"]["untagged_fields"].pop("GEV")
        hist.write_text(json.dumps(doc), encoding="utf-8")
        monkeypatch.setattr(cap, "SD", sd)
        monkeypatch.setattr(common, "SD", sd)
    return str(cap.build_pack("GEV", include_research=False))


def test_the_gev_fixture_pack_is_the_golden_pack_with_a_marker_and_differs_only_in_the_stated_lines_without_one(screener_data_stub, monkeypatch, tmp_path):
    golden = (Path(__file__).resolve().parent / "fixture_data" / "golden_pack_GEV_rev22.md").read_bytes().replace(b"\r\n", b"\n")
    with_marker = _gev_fixture_pack(monkeypatch, True, tmp_path)
    assert with_marker.encode("utf-8") == golden                                    # unchanged: names that carry a marker never reach the guard
    cap._SEC_CACHE.clear()
    without = _gev_fixture_pack(monkeypatch, False, tmp_path)
    a, b = with_marker.splitlines(), without.splitlines()
    assert len(a) == len(b)
    changed = [(x, y) for x, y in zip(a, b) if x != y]
    # the fixture holds no consensus estimates, so its reference line is "not available" for that reason either way; the lines that
    # change are the three derived from the record and the terminal_g_default line's explanation, which read the record's basis
    assert [y.split(":")[0] for _x, y in changed] == ["- terminal_g_default", "- terminal_ronic", "- long_run", "- working_capital"], changed
    assert changed[0][1] == "- terminal_g_default: 3.75% | the Base terminal_g; more than 0.5 points away needs terminal_reason"
    for _x, y in changed[1:]:
        assert REASON in y

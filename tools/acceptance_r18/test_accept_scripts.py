"""Proves the acceptance scripts on SYNTHETIC data and tiny fixtures (revision 18, amendments 1 and 2). Nothing here is an acceptance run:

  - the "world" is the tree's committed GEV fixture slice plus a written-down twelve-year history, synthetic consensus estimates and a
    synthetic closure artifact, all in a temporary folder; MRI's anchors are read read-only from a copy of the backtest's c2 anchors;
  - AT8's script is exercised only on a three-name SYNTHETIC list in a temporary folder; the real list is never opened;
  - no network, no GPU, no model.

Run (from this folder):  python -m pytest test_accept_scripts.py -q -p no:cacheprovider
Run from the repository copy (tools/acceptance_r18/): add  --confcutdir tools/acceptance_r18  so the suite's own conftest.py (which stubs the bill
rate and the closure for every test) is not applied to a run that reads those through the real accessors.
Environment: RS2_TREE (default: the rs2 tree these scripts belong to), ACCEPT_SP (the scratchpad holding rs2-P4-s15, rs2-bt, backtest/ and
rev18/at1c_preview; default: this folder's grandparent when it holds them). Tests that need an absent tree or folder are skipped and say so.
"""
import copy
import csv
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import accept_common as ac  # noqa: E402  (blocks no socket on import)

TREE = ac.default_tree()
SP = Path(os.environ["ACCEPT_SP"]) if os.environ.get("ACCEPT_SP") else HERE.parents[1]
PY = sys.executable
pytestmark = pytest.mark.skipif(TREE is None or not (Path(TREE) / "tools" / "consensus_reference.py").exists(), reason="no rs2 tree found (set RS2_TREE)")
_root_conftest = sys.modules.get("conftest")
if _root_conftest is not None and TREE is not None and Path(getattr(_root_conftest, "__file__", "")).resolve() == (Path(TREE) / "conftest.py").resolve():
    pytest.skip("the rs2 suite's conftest.py is in effect (it stubs the bill rate and the closure); add --confcutdir <this folder>", allow_module_level=True)
MRI = SP / "backtest" / "out" / "c2" / "mri"
DATE = "2026-09-27"


# ---- the synthetic world ------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def world(tmp_path_factory):
    if not MRI.exists():
        pytest.skip("MRI anchors copy not found (ACCEPT_SP)")
    tmp = tmp_path_factory.mktemp("accept_world")
    sd, root = tmp / "sd", tmp / "root"
    (sd / "financials").mkdir(parents=True)
    (root / "enrich").mkdir(parents=True)
    fixture = Path(TREE) / "tools" / "audit_202608" / "tests" / "fixture_data"
    for f in sorted(fixture.glob("*.json")):
        if f.name.startswith("_"):
            continue
        if "__" in f.name:
            sub, leaf = f.name.split("__", 1)
            (sd / sub).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, sd / sub / leaf)
        else:
            shutil.copyfile(f, sd / f.name)
    (sd / "stocks.csv").write_text("Symbol,Name,Sector,Industry\nGEV,GE Vernova Inc.,Industrials,Specialty Industrial Machinery\n", encoding="utf-8")
    closure = tmp / "closure.json"
    closure.write_text(json.dumps({"asof": "2026-09-20", "erp": 0.04, "flag": None, "gap": 1e-12, "revision": 18, "members": 400, "coverage_share": 0.9,
                                   "sum_cap": 1e12, "sum_value": 1e12, "aggregate": {"constituents_without_marker": 0}, "inputs_sha256": {}}), encoding="utf-8")
    ns = ac.bootstrap(TREE, sd, MRI, root, DATE, closure=closure)
    cap = ns.cap
    sys.path.insert(0, str(Path(TREE) / "tools" / "audit_202608" / "tests"))
    import test_throughcycle_reference as ttr
    B = ttr.B
    hist = ttr._cycle_history(None)
    hist[2025] = dict(hist[2025], revenue=10.0 * B, net_income=1.2 * B, da=0.5 * B, capex=0.6 * B, shares_diluted=500e6, ocf=1.5 * B, sbc=0.1 * B,
                      operating_income=10.0 * B * 0.12 * 1.4 - 0.05 * B)
    for y in range(2014, 2025):
        hist[y] = dict(hist[y], da=0.5 * B, capex=0.6 * B, shares_diluted=500e6)
    doc = {"tickers": {"GEV": {str(y): r for y, r in hist.items()}}, "provenance": {"untagged_fields": {"GEV": []}}}
    (sd / "fundamentals_history.json").write_text(json.dumps(doc), encoding="utf-8")
    (root / "enrich" / "GEV.json").write_text(json.dumps({"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "estimates": ttr.EST}), encoding="utf-8")
    sys.modules["industry_taxonomy"] = None
    row = {"n": 100, "p50": 5.0, "p90": 15.0, "share_ge_10": 20.0, "share_ge_20": 5.0, "share_ge_30": 1.0}
    cap.base_rates.base_rate_table = lambda *a, **k: ("$1-10B", {5: dict(row), 10: dict(row)})
    cap.growth_persistence.persistence_for_growth = lambda *a, **k: (None, None)
    import build_day
    rows, meta = build_day.build_rows(ns, ["GEV"], progress=False, enrich_label="book")
    return SimpleNamespace(ns=ns, tmp=tmp, sd=sd, root=root, closure=closure, rows=rows, meta=meta, build_day=build_day, ttr=ttr)


def _copy(rows):
    return copy.deepcopy(rows)


# ---- build_day ------------------------------------------------------------------------------------------------------------------------

def test_build_day_records_the_pack_the_reference_the_independent_call_the_cash_state_and_the_hashes(world):
    r = world.rows["GEV"]
    assert r["error"] is None and r["status"] == "used" and r["printed_value"] is not None and "CONSENSUS-IMPLIED VALUE (reference" in r["text"]
    assert r["reference"]["value"] is not None and r["reference"]["method"] == "growth" and r["reference"]["estimates"]
    assert r["parity"]["pack_value"] == r["parity"]["ri_value"] and r["parity"]["args_equal"] is True
    assert set(r["cash"]) == {"filed", "applies", "financial", "stamps"} and r["cash"]["filed"] is True
    # finding 3: the record's source, date, age and status are read from the record (the label the operator passes is only noted)
    assert r["enrich"]["source"] == "enrich@2026-09-26" and r["enrich"]["date"] == "2026-09-26" and len(r["enrich"]["sha256"]) == 64
    assert r["enrich"]["status"] == "ok" and r["enrich"]["age_days"] == 1 and r["enrich"]["error_record"] is False
    assert world.meta["enrich_by_source"] == {"enrich@2026-09-26": 1} and world.meta["enrich_age_days_over_45"] == 0
    assert world.meta["enrich_label"] == "book" and world.meta["enrich_check"]["pass"] is True
    inputs = ac.inputs_record(world.ns)
    assert len(inputs["history_sha256"]) == 64 and len(inputs["closure_sha256"]) == 64 and inputs["mri_anchor_sha256"]
    assert inputs["pack_revision"] == 18 and inputs["date"] == DATE and inputs["resolved_dirs"]["screener_data_dir"] == str(world.sd.resolve())
    assert ac.constants(world.ns)["FACTS_VERSION"] == 6 and "Level anchor" in ac.constants(world.ns)["TASK"]


def _enrich_root(tmp_path, records):
    """A data root whose enrich/ holds `records` ({ticker: dict | None for a missing file}); every file is written as given."""
    (tmp_path / "enrich").mkdir(parents=True, exist_ok=True)
    for t, rec in records.items():
        if rec is not None:
            (tmp_path / "enrich" / f"{t}.json").write_text(json.dumps(rec), encoding="utf-8")
    return tmp_path


def test_the_enrich_entry_reads_the_record_and_the_check_fails_on_a_stale_an_error_an_undated_or_a_missing_record(world, tmp_path):
    """Finding 3: any record older than 45 days, an error record or a missing one fails the day (counted before, not enforced)."""
    from datetime import datetime
    fixed = datetime(2026, 9, 27, 12, 0, 0)
    good = {"_ticker": "A", "_fetched_at": "2026-09-26T12:00:00+00:00", "estimates": None}
    root = _enrich_root(tmp_path, {
        "OK": good, "EDGE": dict(good, _fetched_at="2026-08-13T12:00:00+00:00"),                  # 45 days: the limit itself
        "OLD": dict(good, _fetched_at="2026-08-12T12:00:00+00:00"),                               # 46 days
        "ERR": {"_ticker": "E", "_fetched_at": "2026-09-26T12:00:00+00:00", "_status": "error", "_error": {"http_status": 500, "where": "info"}},
        "UND": {"_ticker": "U", "estimates": None}, "BAD": dict(good, _fetched_at="yesterday"), "MISS": None})
    e = {t: ac.enrich_entry(root, t, fixed, world.ns.rs2) for t in ("OK", "EDGE", "OLD", "ERR", "UND", "BAD", "MISS")}
    assert [e[t]["status"] for t in e] == ["ok", "ok", "stale", "error_record", "undated", "undated", "missing"]
    assert e["EDGE"]["age_days"] == 45 and e["OLD"]["age_days"] == 46 and e["OK"]["source"] == "enrich@2026-09-26" and e["MISS"]["sha256"] is None
    assert e["ERR"]["error_record"] is True and e["OK"]["error_record"] is False and len(e["OK"]["sha256"]) == 64
    assert ac.enrich_check([e["OK"], e["EDGE"]])["pass"]
    for bad in ("OLD", "ERR", "UND", "BAD", "MISS"):
        assert not ac.enrich_check([e["OK"], e[bad]])["pass"], bad
    chk = ac.enrich_check(e.values())
    assert chk["records"] == 7 and chk["ok"] == 2 and chk["missing"] == 1 and chk["error_records"] == 1 and chk["undated"] == 2
    assert chk["older_than_45_days"] == 1 and not chk["pass"] and not ac.enrich_check([])["pass"]


def test_a_day_with_a_failed_enrich_record_fails_build_day_and_is_refused_by_the_ats(world, tmp_path, monkeypatch):
    names = tmp_path / "names.txt"
    names.write_text("GEV" + chr(10), encoding="utf-8")
    state = {}
    # the day's records are read from `state["root"]` (a new folder each time: json loads are cached by path); the pack is built as in the world
    monkeypatch.setattr(ac, "bootstrap", lambda *a, **k: SimpleNamespace(**dict(vars(world.ns), root=state["root"])))
    args = lambda out: ["--tree", str(TREE), "--root", str(world.root), "--sd", str(world.sd), "--mri", str(MRI), "--date", DATE, "--names", str(names),
                        "--closure", str(world.closure), "--out", str(out), "--enrich-label", "closure_enrich:2026-09-20"]
    good = json.loads((world.root / "enrich" / "GEV.json").read_text(encoding="utf-8"))

    def run(name, record):
        state["root"] = _enrich_root(tmp_path / name, {"GEV": record})
        return world.build_day.main(args(tmp_path / f"{name}.json"))
    assert run("ok", good) == 0
    meta, _rows = ac.load_day(tmp_path / "ok.json")
    assert meta["enrich_check"]["pass"] and meta["enrich_label"] == "closure_enrich:2026-09-20"
    assert run("stale", dict(good, _fetched_at="2026-08-01T12:00:00")) == 1                 # 57 days old on the day
    with pytest.raises(SystemExit) as e:
        ac.load_day(tmp_path / "stale.json")                                               # the file stands as the record, and no AT runs on it
    assert "enrich records failed their check" in str(e.value) and "older than 45 days 1" in str(e.value)
    assert run("error", {"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "_status": "error", "_error": {"http_status": 500, "where": "info"}}) == 1
    assert run("missing", None) == 1
    assert json.loads((tmp_path / "missing.json").read_text(encoding="utf-8"))["meta"]["enrich_check"]["missing"] == 1


def test_the_scripts_block_the_network_and_the_world_was_built_with_it_blocked(world):
    assert ac.network_is_blocked()


def test_the_anonymous_rows_carry_no_ticker(world):
    rows, meta = world.build_day.build_rows(world.ns, ["GEV"], progress=False, anonymous=True)
    (key,) = rows
    assert key != "GEV" and rows[key]["ticker"] is None
    dumped = json.dumps(ac.jsonable({k: {kk: vv for kk, vv in r.items() if kk != "text"} for k, r in rows.items()}))
    assert "GEV" not in dumped, "a ticker leaked into the anonymous rows"
    assert "GEV" not in json.dumps(meta)


# ---- AT1a and AT1e ---------------------------------------------------------------------------------------------------------------------

def test_at1a_passes_on_the_synthetic_name_and_fails_when_the_reference_differs_by_two_cents(world):
    import desk_checks
    res = desk_checks.desk_parity(world.ns, world.rows)
    assert res["pass"] and res["names_compared"] == 1 and res["max_abs_difference"] < 0.005
    bad = _copy(world.rows)
    bad["GEV"]["reference"]["value"] += 0.02
    res = desk_checks.desk_parity(world.ns, bad)
    assert not res["pass"] and res["differences_at_or_above_bar"] == 1


def test_at1a_records_the_desk_error_behind_a_base_valued_alone_fallback(world, monkeypatch):
    """Finding 8: the fallback (the Base valued alone because the desk's three-scenario call failed) is recorded with the desk's error."""
    import desk_checks
    real = world.ns.fmt.execute_financial_model
    monkeypatch.setattr(world.ns.fmt, "execute_financial_model", lambda call, ctx: {"error": "the scenarios are not ordered Bear < Base < Bull"})
    res = desk_checks.desk_parity(world.ns, world.rows)
    assert res["base_valued_alone"] == 1 and res["pass"] and res["pending_ruling_count"] == 0
    assert res["base_valued_alone_errors"] == [("GEV", "the scenarios are not ordered Bear < Base < Bull")]
    assert desk_checks.desk_parity(world.ns, world.rows, names=False)["base_valued_alone_errors"][0][0] is None
    monkeypatch.setattr(world.ns.fmt, "execute_financial_model", real)
    assert desk_checks.desk_parity(world.ns, world.rows)["base_valued_alone_errors"] == []


def test_at1a_a_name_the_desk_cannot_run_is_pending_the_reviewers_ruling_unless_its_year_one_level_is_not_positive(world, monkeypatch):
    import desk_checks
    # a non-positive year-1 level: listed, counted, not pending (the other name carries the test)
    rows = _copy(world.rows)
    rows["NEG"] = _copy(world.rows)["GEV"]
    rows["NEG"]["reference"]["base_cf"] = -1e9
    res = desk_checks.desk_parity(world.ns, rows)
    assert res["pass"] and res["names_compared"] == 1 and res["cannot_run_count"] == 1 and res["pending_ruling_count"] == 0
    assert res["cannot_run_listed"] == [("NEG", desk_checks.NONPOSITIVE_LEVEL)] and "label" not in res
    # any other reason: pending, not passed, and not a failure either
    real = world.ns.fmt.unbundled_dcf
    monkeypatch.setattr(world.ns.fmt, "execute_financial_model", lambda call, ctx: {"error": "x"})
    monkeypatch.setattr(world.ns.fmt, "unbundled_dcf", lambda **kw: {"error": "wacc must exceed terminal_g"})
    res = desk_checks.desk_parity(world.ns, world.rows)
    assert not res["pass"] and res["pending_ruling"] == [("GEV", "wacc must exceed terminal_g")] and res["pending_ruling_count"] == 1
    assert res["label"] == "PENDING" and res["differences_at_or_above_bar"] == 0 and "pending the reviewer's ruling" in res["summary"]
    assert desk_checks.desk_parity(world.ns, world.rows, names=False)["pending_ruling"] == [(None, "wacc must exceed terminal_g")]
    # one name compared, one pending: still not passed (the stand-in fails for the second name only, which carries a 1.0 $B base)
    mixed = _copy(world.rows)
    mixed["BAD"] = _copy(world.rows)["GEV"]
    mixed["BAD"]["reference"]["base_cf"] = 1e9
    monkeypatch.setattr(world.ns.fmt, "unbundled_dcf", lambda **kw: {"error": "boom"} if abs(kw["base_cf"] - 1.0) < 1e-12 else real(**kw))
    res = desk_checks.desk_parity(world.ns, mixed)
    assert not res["pass"] and res["pending_ruling_count"] == 1 and res["names_compared"] == 1 and res["label"] == "PENDING"


def test_a_pending_result_is_reported_as_pending_and_exits_one(tmp_path, capsys):
    result = {"at": "AT1a desk parity", "pass": False, "label": "PENDING", "summary": "x"}
    assert ac.finish(result, tmp_path / "r.json") == 1
    assert capsys.readouterr().out.startswith("PENDING  AT1a desk parity")
    assert ac.finish({"at": "A", "pass": False, "summary": "x"}, None) == 1 and capsys.readouterr().out.startswith("FAIL")


def test_at1a_counts_a_cash_only_reference_and_lists_nothing_else(world):
    import desk_checks
    rows = _copy(world.rows)
    rows["GEV"]["reference"]["method"] = "cash_only"
    res = desk_checks.desk_parity(world.ns, rows)
    assert res["cash_only_excluded"] == 1 and res["names_compared"] == 0 and not res["pass"]      # nothing compared: not a pass


def test_at1e_both_round_trips_hold_with_the_cash_term_and_the_bar_bites_without_it(world, monkeypatch):
    import desk_checks
    res = desk_checks.round_trips(world.ns, world.rows)
    assert res["pass"] and res["names_run"] == 1 and res["a_own_structure"]["max_abs_pp"] <= 0.1 and res["b_neutral_structure"]["max_abs_pp"] <= 0.1
    assert set(res["reported_not_a_bar"]) == {"a_without_cash_term", "b_without_cash_term"}
    # the defect the bar exists for: a reverse DCF that ignores the cash term returns the growth of (operating value + cash)
    real = world.ns.fmt.reverse_dcf_expectations_gap
    monkeypatch.setattr(world.ns.fmt, "reverse_dcf_expectations_gap", lambda **kw: real(**dict(kw, excess_cash=None)))
    res2 = desk_checks.round_trips(world.ns, world.rows)
    ec = world.ns.pack_facts.from_text(world.rows["GEV"]["text"]).get("excess_cash")
    assert (ec is None or ec == 0) or not res2["pass"]


def test_at1e_uses_five_percent_where_the_reference_has_no_year_one_growth_and_counts_what_it_cannot_run(world):
    import desk_checks
    rows = _copy(world.rows)
    rows["GEV"]["reference"]["method"] = "levels"
    g, how = desk_checks._gstar(rows["GEV"])
    assert g == 0.05 and "5%" in how
    cash_only = _copy(world.rows)
    cash_only["GEV"]["reference"]["method"] = "cash_only"
    res = desk_checks.round_trips(world.ns, cash_only)
    assert res["names_run"] == 0 and sum(res["cannot_run_by_reason"].values()) == 1 and not res["pass"]


# ---- the row-level ATs -----------------------------------------------------------------------------------------------------------------

def test_at1d_agrees_on_the_synthetic_name_and_finds_a_disagreement(world):
    import at_rows
    assert at_rows.at1d(world.rows)["pass"]
    bad = _copy(world.rows)
    bad["GEV"]["parity"]["ri_value"] += 0.02
    res = at_rows.at1d(bad)
    assert not res["pass"] and res["disagree_or_missing"] == 1
    missing = _copy(world.rows)
    missing["GEV"]["parity"] = None
    assert not at_rows.at1d(missing)["pass"]
    # finding 7: a pack that failed to build is a failure, not a name that is left out (the other names all agree)
    failed = dict(_copy(world.rows), BAD=dict(_row(), error="RuntimeError: boom", parity=None))
    res = at_rows.at1d(failed)
    assert not res["pass"] and res["not_built"] == 1 and res["agree_to_the_cent"] == 1 and res["disagree_or_missing"] == 1
    assert at_rows.at1d(failed, names=False)["details"][0][0] is None                # the 167: counts and classes only
    assert not at_rows.at1d({"BAD": dict(_row(), error="X")})["pass"]                  # nothing built at all


def _row(status="used", printed=100.0, price=100.0, value=None, **kw):
    return dict({"error": None, "status": status, "printed_value": printed, "price": price,
                 "reference": {"value": printed if value is None else value, "stamps": []}, "text": "", "facts": {}}, **kw)


def test_at3_is_revision_16s_share_minus_two_points():
    import at_rows
    rows18 = {f"N{i}": _row() for i in range(100)}
    for i in range(10):
        rows18[f"N{i}"] = _row(status="not_available", printed=None)
    rows16 = {f"N{i}": _row() for i in range(100)}
    for i in range(7):
        rows16[f"N{i}"] = _row(status=None, printed=None)
    assert at_rows.at3(rows18, rows16)["pass"] is False                      # 90% against 93% - 2 = 91%
    for i in range(7, 9):
        rows18[f"N{i}"] = _row()
    res = at_rows.at3(rows18, rows16)
    assert res["pass"] and res["share_rev18"] == 0.92 and res["share_rev16"] == 0.93
    assert not at_rows.at3({}, {})["pass"]
    short = {k: v for k, v in rows16.items() if k != "N99"}
    assert at_rows.at3(rows18, short)["names_only_in_rev16"] == 1


def test_at4_a_printed_number_at_or_below_zero_and_an_unmarked_zero_reference_fail():
    import at_rows
    ok = {"A": _row(), "B": _row(status="not_meaningful", printed=None, value=-3.0)}
    assert at_rows.at4(ok)["pass"] and at_rows.at4(ok)["references_at_or_below_zero"] == 1
    assert not at_rows.at4({"A": _row(printed=0.0)})["pass"]
    assert not at_rows.at4({"A": _row(printed=-1.0)})["pass"]
    assert not at_rows.at4({"A": _row(status="used", printed=5.0, value=0.004)})["pass"]            # a zero reference that still prints


def test_at5_median_and_the_ten_percent_of_gross_errors():
    import at_rows
    rows = {f"N{i}": _row(printed=100.0 * v) for i, v in enumerate([0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.0, 0.95, 1.05, 1.0])}
    assert at_rows.at5(rows)["pass"]
    low = {f"N{i}": _row(printed=65.0) for i in range(10)}
    assert not at_rows.at5(low)["pass"]                                                              # median 0.65
    wild = dict(rows, X=_row(printed=400.0), Y=_row(printed=20.0))
    res = at_rows.at5(wild)
    assert res["extreme"] == 2 and res["extreme_share"] > 0.10 and not res["pass"]
    assert not at_rows.at5({})["pass"]


def test_at6_constants_anchor_sentence_fence_and_cap(world):
    import at_rows
    consts = ac.constants(world.ns)
    assert at_rows.at6(world.rows, consts)["pass"]
    # the anchor sentence missing from a printed reference line, and a capped stamp
    bad = _copy(world.rows)
    bad["GEV"]["text"] = bad["GEV"]["text"].replace(consts["ANCHOR_ROLE"], "")
    assert not at_rows.at6(bad, consts)["pass"]
    capped = _copy(world.rows)
    capped["GEV"]["reference"]["stamps"] = ["base_year_capped"]
    assert not at_rows.at6(capped, consts)["pass"]
    assert not at_rows.at6(world.rows, dict(consts, PACK_REVISION=17))["pass"]
    assert not at_rows.at6(world.rows, dict(consts, FACTS_VERSION=5))["pass"]
    assert not at_rows.at6(world.rows, dict(consts, TASK="no bullet"))["pass"]


def test_at6_an_outside_fence_reference_prints_its_value_and_its_flag(world, monkeypatch):
    import at_rows
    cap = world.ns.cap
    value = world.rows["GEV"]["printed_value"]
    monkeypatch.setattr(cap, "_reference_outside_fence", lambda v, band: ("above", (1.0, value / 2)))
    rows, _meta = world.build_day.build_rows(world.ns, ["GEV"], progress=False)
    r = rows["GEV"]
    assert r["status"] == "outside_fence_above" and r["printed_value"] == value
    assert at_rows.at6(rows, ac.constants(world.ns))["pass"]
    bad = _copy(rows)
    bad["GEV"]["text"] = bad["GEV"]["text"].replace("outside the street-target fence [", "outside [")
    assert not at_rows.at6(bad, ac.constants(world.ns))["pass"]


def test_at9_counts_the_names_whose_cash_term_applies_and_reports_what_counts_against():
    import at_rows
    def cash(applies, filed=True, financial=False, stamps=()):
        return {"filed": filed, "applies": applies, "financial": financial, "stamps": list(stamps)}
    rows = {f"A{i}": _row(cash=cash(True)) for i in range(9)}
    rows["B"] = _row(cash=cash(False, stamps=["cash_term_not_available_no_bill_rate"]))
    rows["F"] = _row(cash=cash(False, financial=True))                          # financial: not in the population
    rows["N"] = _row(cash=cash(False, filed=False))                             # no filed cash figure: not in the population
    rows["U"] = _row(status="not_available", printed=None, cash=cash(False))    # no printed reference: not in the population
    res = at_rows.at9(rows)
    assert res["pass"] and res["population"] == 10 and res["applies"] == 9 and res["not_applied_by_stamp"] == {"cash_term_not_available_no_bill_rate": 1}
    rows["C"] = _row(cash=cash(False, stamps=["cash_term_not_available_fiscal_year_end_unknown"]))
    res = at_rows.at9(rows)
    assert not res["pass"] and res["share"] < 0.9 and "cash_term_not_available_fiscal_year_end_unknown" in res["not_applied_by_stamp"]
    assert not at_rows.at9({})["pass"]


# ---- the scripts as run: file in, verdict and result file out ---------------------------------------------------------------------------

def test_the_thin_scripts_run_from_a_day_file_and_never_overwrite_a_result(world, tmp_path):
    meta = dict(world.meta, inputs=ac.inputs_record(world.ns), constants=ac.constants(world.ns))
    day = tmp_path / "day.json"
    ac.write_result(day, {"meta": ac.jsonable(meta), "rows": ac.jsonable(world.rows)})
    for script in ("at1d_single_source.py", "at4_no_nonpositive.py", "at5_level_sanity.py", "at6_fence_cap_text.py", "at9_cash_alive.py",
                   "at1a_desk_parity.py", "at1e_round_trip.py"):
        out = tmp_path / (script + ".json")
        p = subprocess.run([PY, str(HERE / script), "--day", str(day), "--out", str(out)], capture_output=True, text=True)
        result = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        if script in ("at5_level_sanity.py", "at9_cash_alive.py"):                    # one synthetic name: V/P and the population depend on it
            assert out.exists(), p.stdout + p.stderr
            continue
        assert p.returncode == 0 and result.get("pass") is True and "PASS" in p.stdout, (script, p.stdout, p.stderr)
        again = subprocess.run([PY, str(HERE / script), "--day", str(day), "--out", str(out)], capture_output=True, text=True)
        assert again.returncode != 0 and "exists" in (again.stderr or "").lower()        # a result is a record: never overwritten
    day16 = tmp_path / "day16.json"
    ac.write_result(day16, {"meta": {"inputs": meta["inputs"]}, "rows": ac.jsonable(world.rows)})
    p = subprocess.run([PY, str(HERE / "at3_coverage.py"), "--day", str(day), "--day16", str(day16)], capture_output=True, text=True)
    assert p.returncode == 0 and "PASS" in p.stdout


def test_a_revision_16_day_built_on_other_data_is_refused_by_at3_and_at1b(world, tmp_path):
    """Finding 5: a different date, history or TTM or anchor hash, data root, screener folder, or other enrich records."""
    inputs = ac.inputs_record(world.ns)
    meta18 = {"inputs": inputs}
    rows = ac.jsonable(world.rows)
    assert ac.same_data(meta18, rows, meta18, rows) == []
    other = lambda **kw: {"inputs": dict(inputs, **kw)}
    cases = {"date": "2026-09-20", "history_sha256": "00" * 32, "ttm_sha256": "11" * 32, "mri_anchor_sha256": {"x.json": "22" * 32}, "root": "elsewhere",
             "resolved_dirs": dict(inputs["resolved_dirs"], screener_data_dir="elsewhere")}
    for key, value in cases.items():
        problems = ac.same_data(other(**{key: value}), rows, meta18, rows)
        assert problems and ("screener_data_dir" if key == "resolved_dirs" else key) in problems[0], (key, problems)
    changed = copy.deepcopy(rows)
    changed["GEV"]["enrich"]["sha256"] = "33" * 32
    assert "1 names' enrich records differ" in ac.same_data(meta18, changed, meta18, rows)[0]
    assert ac.same_data({}, rows, meta18, rows) and ac.same_data(meta18, rows, {"inputs": None}, rows)               # a day that records no inputs
    # the scripts: AT3 and AT1b refuse before they compute anything, and write no result
    day = tmp_path / "day.json"
    ac.write_result(day, {"meta": ac.jsonable(dict(world.meta, inputs=inputs, constants=ac.constants(world.ns))), "rows": rows})
    for name, meta16 in (("date", other(date="2026-09-20")), ("history", other(history_sha256="00" * 32)), ("noinputs", {})):
        day16 = tmp_path / f"day16_{name}.json"
        ac.write_result(day16, {"meta": ac.jsonable(meta16), "rows": rows})
        out = tmp_path / f"at3_{name}.json"
        p = subprocess.run([PY, str(HERE / "at3_coverage.py"), "--day", str(day), "--day16", str(day16), "--out", str(out)], capture_output=True, text=True)
        assert p.returncode != 0 and "refused" in p.stderr and "same data" in p.stderr and not out.exists(), (name, p.stdout, p.stderr)
        out = tmp_path / f"at1b_{name}.json"
        p = subprocess.run([PY, str(HERE / "at1b_reduction.py"), "--day16", str(day16), "--day", str(day), "--tree16", str(TREE), "--tree18", str(TREE),
                            "--out", str(out)], capture_output=True, text=True)
        assert p.returncode != 0 and "refused" in p.stderr and not out.exists(), (name, p.stdout, p.stderr)
    p = subprocess.run([PY, str(HERE / "at1b_reduction.py"), "--day16", str(tmp_path / "day16_date.json"), "--tree16", str(TREE), "--tree18", str(TREE)],
                       capture_output=True, text=True)
    assert p.returncode != 0 and "--day is required" in p.stderr


# ---- AT2 --------------------------------------------------------------------------------------------------------------------------------

def _artifact(**kw):
    doc = {"asof": "2026-10-02", "erp": 0.0375, "flag": None, "gap": 2e-16, "members": 700, "coverage_share": 0.95, "sum_cap": 5e13, "sum_value": 5e13,
           "inputs_sha256": {"fundamentals_history.json": "ab" * 32}, "aggregate": {"constituents_without_marker": 0},
           "consensus_vintage": {"date": "2026-10-01", "tickers_requested": 1644}}
    doc.update(kw)
    return doc


def test_at2_each_bar_and_the_marker_condition():
    import at2_closure
    from datetime import date
    day = date(2026, 10, 5)
    good = at2_closure.evaluate_artifact(_artifact(), day, "ab" * 32, 0, 1700)
    assert good["pass"] and len(good["checks"]) == 8
    cases = [dict(sum_value=5e13 * (1 + 1e-5)), dict(flag="bound_low"), dict(members=299), dict(coverage_share=0.59), dict(asof="2026-08-01"),
             dict(inputs_sha256={"fundamentals_history.json": "cd" * 32}), dict(aggregate={"constituents_without_marker": 2}), dict(asof="2026-10-09"),
             # finding 2: the consensus vintage is at most 45 days old on the acceptance day (46 days, a future date, none, unreadable)
             dict(consensus_vintage={"date": "2026-08-20"}), dict(consensus_vintage={"date": "2026-10-09"}), dict(consensus_vintage={}),
             dict(consensus_vintage=None), dict(consensus_vintage={"date": "soon"}), dict(consensus_vintage="2026-10-01")]
    for kw in cases:
        assert not at2_closure.evaluate_artifact(_artifact(**kw), day, "ab" * 32, 0, 1700)["pass"], kw
    assert not at2_closure.evaluate_artifact(_artifact(), day, "ab" * 32, 3, 1700)["pass"]           # amendment 2: 0 may be missing
    assert at2_closure.evaluate_artifact(_artifact(consensus_vintage={"date": "2026-08-21"}), day, "ab" * 32, 0, 1700)["pass"]   # 45 days: the limit itself


def test_at2_counts_the_aggregate_names_with_no_marker(world, monkeypatch):
    import at2_closure
    import reference_closure as rc
    monkeypatch.setattr(rc, "build_aggregate", lambda root, cap: ({"constituents": [{"ticker": "GEV"}, {"ticker": "ZZZ"}]}, {}))
    n, missing = at2_closure.aggregate_marker_counts(world.ns)
    assert (n, missing) == (2, 1)                                                      # GEV carries the marker [], ZZZ has none


# ---- AT1b -------------------------------------------------------------------------------------------------------------------------------

def _reduction_rows(ttr):
    B = ttr.B
    est = ttr.EST
    growth = {"method": "growth", "value": 1.0, "base_arg": 1.1 * B, "estimates": est, "coe": 0.09, "terminal_g": 0.0375, "shares": 500e6, "median_5y": 0.05,
              "stub_months": 3.0, "da": 0.5 * B, "capex": 0.6 * B, "levels_reason_arg": None, "levels": None, "levels_block_arg": None,
              "anchor_arg": 0.04}
    levels = dict(growth, method="levels", base_arg=-0.2 * B, levels_reason_arg="the fiscal-year owner-earnings base is not positive",
                  levels=[2.7 * 500e6 + 0.5 * B - 0.6 * B, 3.0 * 500e6 + 0.5 * B - 0.6 * B])
    blocked = dict(levels, levels_block_arg="the vendor's EPS levels may not be combined with the filed D&A and capex (vintage test failed)")
    return {"G1": {"reference": growth}, "L1": {"reference": levels}, "B1": {"reference": blocked}, "N1": {"reference": None}}


@pytest.mark.skipif(not (SP / "rs2-P4-s15").exists(), reason="revision 16's tree (fee17cf) not found")
def test_at1b_the_reduction_holds_on_synthetic_inputs_and_a_difference_is_found(world, tmp_path):
    import at1b_reduction
    rows = _reduction_rows(world.ttr)
    inputs = ac.inputs_record(world.ns)
    day = tmp_path / "day.json"                                           # revision 18's day on the same data (only its meta is read here)
    ac.write_result(day, {"meta": ac.jsonable({"inputs": inputs}), "rows": {}})
    day16 = tmp_path / "day16.json"
    ac.write_result(day16, {"meta": ac.jsonable({"inputs": inputs}), "rows": ac.jsonable(rows)})
    # what revision 16's build returns on these inputs, from the worker itself (a fresh process: one engine per process)
    w16 = tmp_path / "w16.json"
    p = subprocess.run([PY, str(HERE / "at1b_reduction.py"), "--worker", "rev16", "--tree", str(SP / "rs2-P4-s15"), "--day16", str(day16),
                        "--worker-out", str(w16)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    values = json.loads(w16.read_text(encoding="utf-8"))
    assert values["G1"]["value"] is not None and values["L1"]["value"] is not None
    assert values["B1"]["value"] is None                                  # finding 4: `levels_block` reaches revision 16's build and removes the levels method
    for key, v in values.items():
        rows[key]["reference"]["value"] = v["value"]                      # the day file's record of revision 16's own build
    day16b = tmp_path / "day16b.json"
    ac.write_result(day16b, {"meta": ac.jsonable({"inputs": inputs}), "rows": ac.jsonable(rows)})
    out = tmp_path / "at1b.json"
    p = subprocess.run([PY, str(HERE / "at1b_reduction.py"), "--day16", str(day16b), "--day", str(day), "--tree16", str(SP / "rs2-P4-s15"), "--tree18", str(TREE),
                        "--out", str(out)], capture_output=True, text=True)
    res = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 0 and res["pass"] and res["names"] == 3 and res["rev16_worker_differs_from_recorded"] == 0, p.stdout + p.stderr
    assert res["trees"]["rev16"]["commit"].startswith("fee17cf")
    # a day file whose recorded revision 16 value is not what revision 16's engine returns on its recorded inputs fails (finding 4)
    rows["G1"]["reference"]["value"] += 0.02
    day16c = tmp_path / "day16c.json"
    ac.write_result(day16c, {"meta": ac.jsonable({"inputs": inputs}), "rows": ac.jsonable(rows)})
    out2 = tmp_path / "at1b2.json"
    p = subprocess.run([PY, str(HERE / "at1b_reduction.py"), "--day16", str(day16c), "--day", str(day), "--tree16", str(SP / "rs2-P4-s15"), "--tree18", str(TREE),
                        "--out", str(out2)], capture_output=True, text=True)
    res2 = json.loads(out2.read_text(encoding="utf-8"))
    assert p.returncode == 1 and not res2["pass"] and res2["differences"] == 0 and res2["rev16_worker_differs_from_recorded"] == 1
    # compare() on its own: a value off by two cents, a name with no revision 18 value, a recorded value that differs, and one that is absent
    a = {"G1": {"value": 10.00, "method": "growth"}, "L1": {"value": None, "method": None}}
    rec = {"G1": 10.00, "L1": None}
    assert at1b_reduction.compare(a, {"G1": {"value": 10.00}, "L1": {"value": None}}, rec)["pass"]
    assert not at1b_reduction.compare(a, {"G1": {"value": 10.02}, "L1": {"value": None}}, rec)["pass"]
    assert not at1b_reduction.compare(a, {"G1": {"value": 10.00}}, rec)["pass"]
    assert not at1b_reduction.compare(a, {"G1": {"value": 10.00}, "L1": {"value": None}}, {"G1": 10.02, "L1": None})["pass"]
    assert not at1b_reduction.compare(a, {"G1": {"value": 10.00}, "L1": {"value": None}}, {"G1": 10.00})["pass"]
    assert not at1b_reduction.compare(a, {"G1": {"value": 10.00}, "L1": {"value": None}}, {"G1": 10.00, "L1": 3.0})["pass"]
    assert not at1b_reduction.compare({}, {}, {})["pass"]


# ---- AT1c -------------------------------------------------------------------------------------------------------------------------------

def test_at1c_the_draw_is_seeded_and_order_free_and_refuses_a_small_pool():
    import at1c_tested_design as c
    pool = [{"date": "2019", "cik": str(i), "nm": {}, "coe": 0.09, "gA": 0.04, "pi": 0.02, "V_S": 1.0} for i in range(500)]
    a = c.draw_paired(pool)
    b = c.draw_paired(list(reversed(pool)))
    assert len(a) == 200 and [p["cik"] for p in a] == [p["cik"] for p in b]
    assert [p["cik"] for p in a] != [p["cik"] for p in c.draw_paired(pool, seed=1)]
    with pytest.raises(ValueError):
        c.draw_paired(pool[:100])


def test_at1c_loads_a_pool_from_tiny_pickles_in_the_harnesss_layout(tmp_path):
    import pickle
    import at1c_tested_design as c
    bt = tmp_path / "bt"
    (bt / "mri").mkdir(parents=True)
    (bt / "out" / "inputs").mkdir(parents=True)
    (bt / "out" / "prelook").mkdir(parents=True)
    (bt / "mri" / "pit_anchors.json").write_text(json.dumps({"dates": {y: {"rf": 0.03, "gA": 0.04, "pi": 0.02} for y in c.YEARS}}), encoding="utf-8")
    for y in c.YEARS:
        nm = {"cik": "1", "adjL": 1.0, "rows": {}, "L": 2018, "stub_months": None, "untagged": ["goodwill"], "dc_tags": {}, "shares": 1e6, "m": 0.05, "sector": "X", "y_L": 0.01}
        pickle.dump({"pop": [nm, dict(nm, cik="2")]}, open(bt / "out" / "inputs" / f"inputs_{y}.pkl", "wb"))
        pickle.dump([{"cik": "1", "in_U": True, "V_B": 5.0, "V_S": 6.0}, {"cik": "2", "in_U": True, "V_B": None, "V_S": 7.0}],
                    open(bt / "out" / "prelook" / f"table_{y}.pkl", "wb"))
        (bt / "out" / "prelook" / f"result_candidate_{y}.json").write_text(json.dumps({"closure": {"erp_S": 0.05}}), encoding="utf-8")
    pool = c.load_pool(bt)
    assert len(pool) == 5 and pool[0]["coe"] == pytest.approx(1.0 * 0.05 + 0.04) and pool[0]["V_S"] == 6.0            # only the paired name (V_B > 0 and V_S > 0)
    inputs = c.to_inputs(pool[:1])
    assert inputs[0]["recorded_V_S"] == 6.0 and inputs[0]["untagged"] == ["goodwill"] and inputs[0]["coe"] == pool[0]["coe"]


@pytest.mark.skipif(not (SP / "rs2-bt").exists() or not (SP / "rev18" / "at1c_preview" / "out_harness.json").exists(),
                    reason="the backtest harness tree or the preview data are not there")
def test_at1c_reproduces_the_harness_values_on_synthetic_name_dates_and_a_changed_value_fails(tmp_path):
    prev = SP / "rev18" / "at1c_preview"
    names = json.loads((prev / "inputs.json").read_text(encoding="utf-8"))[:40]
    values = json.loads((prev / "out_harness.json").read_text(encoding="utf-8"))[:40]
    for nm, v in zip(names, values):
        nm["recorded_V_S"] = v["value"]
        nm["date"] = "synthetic"
    names = [nm for nm in names if nm["recorded_V_S"] is not None]
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(names), encoding="utf-8")
    out = tmp_path / "at1c.json"
    p = subprocess.run([PY, str(HERE / "at1c_tested_design.py"), "run", "--inputs", str(inputs), "--tree", str(TREE), "--bt-tree", str(SP / "rs2-bt"),
                        "--out", str(out)], capture_output=True, text=True)
    res = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 0 and res["pass"] and res["name_dates"] == len(names) and res["differences"] == 0, p.stdout + p.stderr
    names[3]["recorded_V_S"] += 0.02
    inputs2, out2 = tmp_path / "inputs2.json", tmp_path / "at1c2.json"
    inputs2.write_text(json.dumps(names), encoding="utf-8")
    p = subprocess.run([PY, str(HERE / "at1c_tested_design.py"), "run", "--inputs", str(inputs2), "--tree", str(TREE), "--bt-tree", str(SP / "rs2-bt"),
                        "--out", str(out2)], capture_output=True, text=True)
    assert p.returncode == 1 and json.loads(out2.read_text(encoding="utf-8"))["differences"] == 1


# ---- AT7 --------------------------------------------------------------------------------------------------------------------------------

def _mini_repo(path, body):
    path.mkdir()
    (path / "test_x.py").write_text(body, encoding="utf-8")
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], capture_output=True, text=True, check=True)
    run("init", "-q")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    return run("rev-parse", "HEAD").stdout.strip()


def test_at7_runs_the_suite_in_the_foreground_and_checks_the_pins(tmp_path):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    h_good = _mini_repo(good, "def test_ok():\n    assert True\n")
    _mini_repo(bad, "def test_no():\n    assert False\n")
    h_pin = _mini_repo(tmp_path / "pinned", "def test_ok():\n    assert True\n")
    run = lambda *args: subprocess.run([PY, str(HERE / "at7_suite.py"), "--python", PY, *args], capture_output=True, text=True)
    out = tmp_path / "at7.json"
    p = run("--tree", str(good), "--targets", "test_x.py", "--harness", f"{tmp_path / 'pinned'}@{h_pin[:10]}::test_x.py", "--out", str(out))
    res = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 0 and res["pass"] and "1 passed" in res["runs"][0]["summary_line"] and len(res["runs"]) == 2
    p = run("--tree", str(bad), "--targets", "test_x.py")
    assert p.returncode == 1 and "FAIL" in p.stdout
    p = run("--tree", str(good), "--targets", "test_x.py", "--harness", f"{tmp_path / 'pinned'}@{'0' * 10}::test_x.py")
    assert p.returncode == 1 and "is not the pinned commit" in p.stdout


def test_at7_without_a_harness_tests_the_backtest_harness_at_its_pinned_commit_and_fails_where_it_is_not_there(tmp_path):
    """Finding 6: the default is rs2-bt@40cb5cf::backtest_phase2/tests (a sibling of --tree); AT7 is never the rs2 suite alone."""
    import at7_suite
    assert at7_suite.DEFAULT_HARNESS == "rs2-bt@40cb5cf::backtest_phase2/tests"
    good = tmp_path / "tree" / "good"
    good.parent.mkdir()
    _mini_repo(good, "def test_ok():\n    assert True\n")
    run = lambda *args: subprocess.run([PY, str(HERE / "at7_suite.py"), "--python", PY, *args], capture_output=True, text=True)
    out = tmp_path / "at7_default.json"
    p = run("--tree", str(good), "--targets", "test_x.py", "--out", str(out))                  # no --harness, and no rs2-bt beside the tree
    res = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 1 and not res["pass"] and [r["name"] for r in res["runs"]] == ["rs2 suite", "harness rs2-bt"]
    assert res["runs"][0]["passed"] and not res["runs"][1]["passed"] and "is not the pinned commit 40cb5cf" in res["runs"][1]["summary_line"]
    # a relative worktree is a sibling of --tree
    h = _mini_repo(good.parent / "sibling", "def test_ok():\n    assert True\n")
    out2 = tmp_path / "at7_sibling.json"
    p = run("--tree", str(good), "--targets", "test_x.py", "--harness", f"sibling@{h[:10]}::test_x.py", "--out", str(out2))
    res2 = json.loads(out2.read_text(encoding="utf-8"))
    assert p.returncode == 0 and res2["pass"] and len(res2["runs"]) == 2 and res2["runs"][1]["commit"] == h


# ---- AT8: the guards and the counts, on a synthetic three-name list (the real list is never opened) ------------------------------------------

SYN = ["ZQAA", "ZQBB", "ZQCC"]


def _at8_setup(world, tmp_path, results=None, config_override=None, pre_name="pre.json"):
    import at8_untouched_look as a8
    lst = tmp_path / "list.txt"
    lst.write_text("\n".join(SYN) + "\n", encoding="utf-8")
    cfg = a8.configuration_of(ac.inputs_record(world.ns))
    cfg.update(config_override or {})
    pre = tmp_path / pre_name
    pre.write_text(json.dumps({"configuration": cfg, "results": results if results is not None else {k: True for k in a8.REQUIRED}}), encoding="utf-8")
    return a8, lst, pre


def _args(world, tmp_path, lst, pre, *extra, sha=None):
    return ["--tree", str(world.ns.tree), "--root", str(world.root), "--sd", str(world.sd), "--mri", str(MRI), "--date", DATE, "--closure", str(world.closure),
            "--untouched-list", str(lst), "--untouched-sha256", sha or ac.sha256_file(lst)[:12], "--preconditions", str(pre), "--lock", str(tmp_path / "lock"),
            "--out", str(tmp_path / "at8.json"), *extra]


def test_at8_refuses_without_the_flag_with_a_wrong_list_with_unmet_preconditions_and_after_the_look(world, tmp_path, capsys):
    a8, lst, pre = _at8_setup(world, tmp_path)
    stub = lambda ns, names, **k: ({"k1": copy.deepcopy(world.rows["GEV"])}, {"errors_by_class": {}, "enrich_by_source": {"untouched": 3},
                                                                           "enrich_age_days_max": 1, "enrich_age_days_over_45": 0})
    assert a8.main(_args(world, tmp_path, lst, pre), build_rows=stub) == 2                               # no --confirm-one-look
    assert a8.main(_args(world, tmp_path, lst, pre, "--confirm-one-look", sha="deadbeef00"), build_rows=stub) == 2   # wrong list sha
    err = capsys.readouterr().err
    assert "ZQ" not in err and not (tmp_path / "lock").exists()
    _, _, pre_bad = _at8_setup(world, tmp_path, results={k: (k != "AT2") for k in a8.REQUIRED}, pre_name="pre_bad.json")
    assert a8.main(_args(world, tmp_path, lst, pre_bad, "--confirm-one-look"), build_rows=stub) == 2          # AT2 not passed
    assert "AT2 is not recorded as passed" in capsys.readouterr().err and not (tmp_path / "lock").exists()
    _, _, pre_cfg = _at8_setup(world, tmp_path, config_override={"history_sha256": "00" * 32}, pre_name="pre_cfg.json")
    assert a8.main(_args(world, tmp_path, lst, pre_cfg, "--confirm-one-look"), build_rows=stub) == 2          # another configuration
    assert "configuration differs" in capsys.readouterr().err and not (tmp_path / "lock").exists()


def test_at8_takes_the_look_once_writes_counts_only_and_refuses_a_second_look(world, tmp_path, capsys):
    a8, lst, pre = _at8_setup(world, tmp_path)
    built = []

    def stub(ns, names, **k):
        built.append((len(names), k.get("anonymous"), k.get("keep_text")))
        return ({"k1": copy.deepcopy(world.rows["GEV"])}, {"errors_by_class": {}, "enrich_by_source": {"untouched": 3}, "enrich_age_days_max": 1,
                                                          "enrich_age_days_over_45": 0})
    rc = a8.main(_args(world, tmp_path, lst, pre, "--confirm-one-look"), build_rows=stub)
    out = capsys.readouterr()
    assert rc == 0 and built == [(3, True, True)] and (tmp_path / "lock").exists()
    text = (tmp_path / "at8.json").read_text(encoding="utf-8")
    result = json.loads(text)
    assert result["pass"] and set(result["bars"]) == {"AT1a", "AT1d", "AT4"} and result["counts"]["names"] == 3
    assert set(result["report_only"]) >= {"coverage", "share_below_0.9x_price", "median_vp", "outside_the_fence"}
    for name in SYN + ["GEV"]:
        assert name not in text and name not in out.out and name not in out.err                          # counts only
    assert "CONSENSUS-IMPLIED" not in text and result["list_sha256"] == ac.sha256_file(lst)
    # the second look is refused, nothing is built, and the first result stands
    again = a8.main(_args(world, tmp_path, lst, pre, "--confirm-one-look"), build_rows=lambda *a, **k: pytest.fail("a second look built something"))
    assert again == 2 and "already been taken" in capsys.readouterr().err and (tmp_path / "at8.json").read_text(encoding="utf-8") == text


def test_at8_a_failing_bar_is_a_failing_look_and_the_look_is_still_used(world, tmp_path, capsys):
    a8, lst, pre = _at8_setup(world, tmp_path)
    bad = copy.deepcopy(world.rows["GEV"])
    bad["reference"]["value"] += 0.5                                                                      # AT1a breaks
    stub = lambda ns, names, **k: ({"k1": bad}, {"errors_by_class": {}, "enrich_by_source": {}, "enrich_age_days_max": None, "enrich_age_days_over_45": 0})
    assert a8.main(_args(world, tmp_path, lst, pre, "--confirm-one-look"), build_rows=stub) == 1
    assert "FAIL" in capsys.readouterr().out and (tmp_path / "lock").exists()
    assert not json.loads((tmp_path / "at8.json").read_text(encoding="utf-8"))["bars"]["AT1a"]["pass"]


def test_the_name_list_loader_refuses_a_wrong_hash_without_naming_a_ticker(tmp_path):
    lst = tmp_path / "l.txt"
    lst.write_text("# c\nzqaa\nZQBB\nzqaa\n\n", encoding="utf-8")
    assert ac.load_names(lst) == ["ZQAA", "ZQBB"]
    assert ac.load_names(lst, ac.sha256_file(lst)[:8]) == ["ZQAA", "ZQBB"]
    with pytest.raises(ValueError) as e:
        ac.load_names(lst, "00000000")
    assert "ZQ" not in str(e.value)
    with pytest.raises(ValueError):
        ac.load_names(lst, "0000")                                    # a prefix shorter than 8 characters is not enough


def test_the_preconditions_checker_names_what_is_missing():
    import at8_untouched_look as a8
    cfg = {k: "x" for k in a8.CONFIG_KEYS}
    ok = {"configuration": dict(cfg), "results": {k: True for k in a8.REQUIRED}}
    assert a8.check_preconditions(ok, cfg) == []
    assert a8.check_preconditions({}, cfg)
    assert a8.check_preconditions(dict(ok, results={**ok["results"], "AT9": False}), cfg) == ["AT9 is not recorded as passed"]
    assert a8.check_preconditions(dict(ok, configuration=dict(cfg, tree_commit="y")), cfg) == ["the configuration differs from the one the ATs passed on: tree_commit"]
    assert a8.check_preconditions(dict(ok, configuration={}), cfg) and a8.check_preconditions(ok, {k: None for k in a8.CONFIG_KEYS})

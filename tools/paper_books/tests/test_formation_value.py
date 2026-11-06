"""formation_value.py (F10) on synthetic fixtures: a fake qwen_c.value.run subprocess, fake anchors, no network and no GPU."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import formation_run as FR  # noqa: E402
import formation_value as FV  # noqa: E402
import value_family as VF  # noqa: E402

T = "2026-11-30"
DEC = "2026-12-01T16:00:00Z"
HEAD = "c0ffee"
EXCL, EXCL_LIST = "OPXA", "OPXB"                                          # conftest's synthetic operator exclusions


def anchor_build(d, built_at, asof):
    d.mkdir(parents=True, exist_ok=True)
    for f in FV.ANCHOR_FILES:
        (d / f).write_text(json.dumps({"built_at": built_at, "asof": asof, "x": f}), encoding="utf-8")
    return d


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = SimpleNamespace(inputs=tmp_path / "inputs", value=tmp_path / "value", state=tmp_path / "state", runs=tmp_path / "runs",
                        live=tmp_path / "mri" / "outputs", calls=[], outcomes={})
    for k, v in (("INPUTS", w.inputs), ("VALUE", w.value), ("STATE", w.state), ("LOCK", w.state / "value.lock"), ("RUNS", w.runs)):
        monkeypatch.setattr(FV, k, v)
    monkeypatch.setattr(FR, "INPUTS", w.inputs)
    monkeypatch.setattr(FR, "STATE", w.state)
    real = FV.paths.resolve
    monkeypatch.setattr(FV.paths, "resolve", lambda key, *a, **k: w.live if key == "anchors_dir" else real(key, *a, **k))
    anchor_build(w.live, "2026-12-02T21:35:00+00:00", "2026-12-02")                 # live: after T
    anchor_build(w.live / "archive" / "2026-11-30" / "20261130T213000Z-aa", "2026-11-30T21:35:00+00:00", "2026-11-30")   # the pin
    anchor_build(w.live / "archive" / "2026-11-29" / "20261129T213000Z-bb", "2026-11-29T21:35:00+00:00", "2026-11-29")
    w.closure = tmp_path / "live_cache" / "reference_closure.json"                   # the live closure, dated before T
    w.closure.parent.mkdir()
    w.closure.write_text(json.dumps({"asof": "2026-11-04", "erp": 0.047}), encoding="utf-8")
    monkeypatch.setenv("RS2_REFERENCE_CLOSURE", str(w.closure))
    monkeypatch.setattr(FV, "stocks_rows", lambda commit: {t: {"symbol": t, "sector": "Industrials", "marketCap": 1e9}
                                                            for t in ("AAA", "BBB", "CCC", EXCL, EXCL_LIST)})
    monkeypatch.setattr(FV, "name_family", lambda cik, T: {"family": "operating", "reason": "synthetic"})
    monkeypatch.setattr(FV, "gpu_ok", lambda: (True, None))
    monkeypatch.setattr(FV, "git", lambda *a: HEAD if a[0] == "rev-parse" else "")
    monkeypatch.setattr(subprocess, "run", fake_value_run(w))
    monkeypatch.setattr(sys, "argv", ["formation_value.py", T])
    names = {}
    for t, state in (("AAA", "complete"), ("BBB", "analysis_incomplete"), (EXCL, "operator_excluded"), (EXCL_LIST, "complete")):
        p = tmp_path / "packets" / f"{t}.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps({"ticker": t, "decision_time_utc": DEC, "cik": "0000000001"}), encoding="utf-8")
        names[t] = {"packet": str(p), "packet_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "state": state}
    names["CCC"] = {"packet": None, "state": "analysis_incomplete", "reason": "packet_refused"}
    w.inputs.mkdir(parents=True)
    w.map = w.inputs / f"formation_{T}.json"
    w.map.write_text(json.dumps({"formation_T": T, "decision_time_utc": DEC, "output_commit": "abc123", "names": names}), encoding="utf-8")
    yield w
    FV.release_lock()


def fake_value_run(w):
    """Writes result.json where qwen_c.value.run would; w.outcomes[(ticker, seed)] is a status, "crash", or a dict merged in."""
    def run(argv, **kw):
        if argv[:3] != [sys.executable, "-m", "qwen_c.value.run"]:
            raise AssertionError(f"unexpected subprocess {argv}")
        w.calls.append((argv, kw))
        packet, seed = argv[3], int(argv[argv.index("--seed") + 1])
        src = Path(packet).read_bytes()
        pk = json.loads(src)
        out = w.outcomes.get((pk["ticker"], seed), "ok")
        if out == "crash":
            return SimpleNamespace(stdout="", stderr="Traceback: boom", returncode=1)
        rd = w.runs / f"{pk['ticker']}_20261201T160000Z_{hashlib.sha256(src).hexdigest()[:12]}_{seed}"
        rd.mkdir(parents=True, exist_ok=True)
        body = {"status": out if isinstance(out, str) else "ok", "ticker": pk["ticker"], "seed": seed, "T": DEC,
                "packet_sha256": hashlib.sha256(src).hexdigest(), "versions": {"git": [HEAD, False]}}
        if isinstance(out, dict):
            body.update(out)
        (rd / "result.json").write_text(json.dumps(body), encoding="utf-8")
        return SimpleNamespace(stdout=json.dumps({"status": body["status"]}), stderr="", returncode=0)
    return run


def finish_q1(w):
    w.state.mkdir(parents=True, exist_ok=True)
    (w.state / f"finished_{T}.flag").write_text("done")


def index(w):
    return json.loads((w.value / f"formation_{T}.json").read_text(encoding="utf-8"))


def test_waits_without_the_finished_flag_but_pins_the_anchors(world):
    assert FV.main() == 0
    assert world.calls == [] and not (world.value / f"formation_{T}.json").exists()
    man = json.loads((world.value / f"anchors_{T}" / "manifest.json").read_text(encoding="utf-8"))
    assert man["source"].endswith("20261130T213000Z-aa")                  # the newest build at or before the decision time
    assert {v["asof"] for v in man["files"].values()} == {"2026-11-30"}


def test_values_every_book_name_at_both_seeds_skips_excluded_and_resumes(world):
    finish_q1(world)
    sys.argv[:] = ["formation_value.py", T, "--limit", "1"]
    assert FV.main() == 0
    assert len(world.calls) == 1 and set(index(world)["names"]["AAA"]["slots"]) == {"1000"}
    sys.argv[:] = ["formation_value.py", T]
    assert FV.main() == 0
    tickers = [Path(c[0][3]).stem for c in world.calls]
    seeds = [c[0][c[0].index("--seed") + 1] for c in world.calls]
    assert list(zip(tickers, seeds)) == [("AAA", "1000"), ("AAA", "3000"), ("BBB", "1000"), ("BBB", "3000")]   # resumed, no repeat
    argv, kw = world.calls[0]
    assert kw["cwd"] == FV.ROOT == Path(FV.__file__).resolve().parents[2]
    assert kw["env"]["MRI_ANCHORS_DIR"] == str(world.value / f"anchors_{T}")
    assert argv[argv.index("--family") + 1] == "operating" and argv[argv.index("--sector") + 1] == "Industrials"
    idx = index(world)
    assert set(idx["names"]) == {"AAA", "BBB"}                            # excluded in the map, in operator_excluded.json, no packet
    s = idx["names"]["BBB"]["slots"]["3000"]
    assert s["status"] == "ok" and s["result_sha256"] == hashlib.sha256(Path(s["result"]).read_bytes()).hexdigest()
    assert idx["git"] == HEAD and (world.state / f"value_finished_{T}.flag").exists()
    world.calls.clear()
    assert FV.main() == 0 and world.calls == []


def test_engine_defect_stops_and_never_fills_the_slot(world):
    finish_q1(world)
    world.outcomes[("AAA", 3000)] = {"status": "engine_defect", "attempts": [{"detail": "engine defect in checks: KeyError"}]}
    assert FV.main() == 7
    idx = index(world)
    assert set(idx["names"]["AAA"]["slots"]) == {"1000"} and idx["names"]["AAA"]["failures"] == {"3000": 1}
    assert idx["names"]["AAA"]["asides"][0].endswith("_3000_aside1")
    assert "engine_defect" in (world.state / f"value_STOP_{T}.flag").read_text(encoding="utf-8")
    world.calls.clear()
    assert FV.main() == 7 and world.calls == []                           # a human must look


def test_a_crash_stops_like_a_defect(world):
    finish_q1(world)
    world.outcomes[("AAA", 1000)] = "crash"
    assert FV.main() == 7
    assert "crash" in (world.state / f"value_STOP_{T}.flag").read_text(encoding="utf-8")
    assert index(world)["names"]["AAA"]["slots"] == {}


def test_a_timeout_is_retried_not_filled(world):
    finish_q1(world)
    world.outcomes[("AAA", 1000)] = "timeout"
    assert FV.main() == 6
    assert not (world.state / f"value_STOP_{T}.flag").exists()
    world.outcomes[("AAA", 1000)] = "ok"
    assert FV.main() == 0 and index(world)["names"]["AAA"]["slots"]["1000"]["status"] == "ok"


def test_gpu_busy_yields_without_a_slot(world, monkeypatch):
    finish_q1(world)
    monkeypatch.setattr(FV, "gpu_ok", lambda: (False, "gpu_busy: another model"))
    assert FV.main() == 3 and world.calls == []


def test_refuses_anchors_after_T(world):
    import shutil
    shutil.rmtree(world.live / "archive")                                 # only the live build, dated after the decision
    with pytest.raises(SystemExit) as e:
        FV.main()
    assert "no MRI anchor build at or before" in str(e.value)
    assert not (world.value / f"anchors_{T}").exists()


def test_a_pinned_copy_dated_after_T_or_changed_is_refused(world):
    assert FV.main() == 0
    d = world.value / f"anchors_{T}"
    keep = (d / "sector_multiple_bands.json").read_bytes()
    (d / "sector_multiple_bands.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        FV.main()
    assert "does not recompute" in str(e.value)
    (d / "sector_multiple_bands.json").write_bytes(keep)
    assert FV.main() == 0                                                  # restored: accepted again
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))   # a consistent copy whose asof is after T
    anchor_build(d, "2026-11-30T21:35:00+00:00", "2026-12-02")
    man["files"] = FV.read_build(d)
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        FV.main()
    assert "after T" in str(e.value)


def test_a_missing_market_cap_is_a_named_no_call_without_a_run(world, monkeypatch):
    finish_q1(world)
    monkeypatch.setattr(FV, "stocks_rows", lambda commit: {"AAA": {"sector": "Industrials", "marketCap": 0},
                                                            "BBB": {"sector": "Industrials", "marketCap": 1e9}})
    assert FV.main() == 0
    s = index(world)["names"]["AAA"]["slots"]
    assert s["1000"] == {"status": "no_call", "reason": "field_missing", "detail": ["market_cap"], "result": None}
    assert {Path(c[0][3]).stem for c in world.calls} == {"BBB"}


def test_a_family_that_cannot_be_measured_is_not_recorded(world, monkeypatch):
    finish_q1(world)

    def offline(cik, T):
        raise OSError("SEC unreachable")
    monkeypatch.setattr(FV, "name_family", offline)
    assert FV.main() == 6 and world.calls == []
    assert not (world.value / f"formation_{T}.json").exists()


def test_waits_for_another_formation_with_q1_work_left(world):
    finish_q1(world)
    (world.inputs / "formation_2026-12-31.json").write_text(json.dumps({"names": {"ZZZ": {"state": "to_run"}}}), encoding="utf-8")
    assert FV.main() == 5 and world.calls == []


# ---------------------------------------------------------------- the family rule

def test_sic_families():
    assert VF.sic_family("6798") == ("family_not_built", "reit_or_real_estate")
    assert VF.sic_family("4911")[0] == "family_not_built"
    assert VF.sic_family("6282")[0] == "operating" and VF.sic_family("6411")[0] == "operating"
    assert VF.sic_family("6022")[0] == "financial" and VF.sic_family("1311")[0] == "commodity"
    assert VF.sic_family("7372")[0] == "operating" and VF.sic_family(None) == (None, "no SIC code")


def _facts(end, ai):
    """A synthetic companyfacts document: one annual 10-K accepted long before T, instants at `end`."""
    rows = lambda v: {"units": {"USD": [{"end": end, "val": v, "accn": "A1", "form": "10-K", "filed": "2026-02-01"}]}}   # noqa: E731
    return {"facts": {"us-gaap": {k: rows(v) for k, v in ai.items()}}}


def _subs(sic):
    return {"sic": sic, "filings": {"recent": {"form": ["10-K"], "accessionNumber": ["A1"], "filingDate": ["2026-02-01"],
                                               "acceptanceDateTime": ["2026-02-01T16:00:00.000Z"], "reportDate": ["2025-12-31"]}}}


def _f(oi):
    vals = lambda xs: {"values": [{"end": e, "value": v} for e, v in xs]}   # noqa: E731
    return {"operating_income": vals(oi), "revenue": vals([(e, 100.0) for e, _ in oi])}


def test_family_route_overturns_and_confirms():
    from datetime import datetime, timezone
    T_ = datetime(2026, 12, 1, tzinfo=timezone.utc)
    end, oi = "2025-12-31", [("2025-12-31", 10.0)]
    # a bank SIC whose balance sheet holds deposits: financial
    cf = _facts(end, {"Assets": 100.0, "Liabilities": 90.0, "Deposits": 60.0})
    assert VF.family(cf, _subs("6022"), _f(oi), T_)["family"] == "financial"
    # a financial SIC (6199) with no lending, deposit or insurance book and little borrowing: operating (the card-network case)
    cf = _facts(end, {"Assets": 100.0, "Liabilities": 50.0})
    r = VF.family(cf, _subs("6199"), _f(oi), T_)
    assert (r["classification"], r["route"], r["family"]) == ("financial", "operating", "operating")
    # an operating SIC with a lending book >= 50% of assets: financial
    cf = _facts(end, {"Assets": 100.0, "Liabilities": 80.0, "LoansReceivableNet": 60.0})
    assert VF.family(cf, _subs("7389"), _f(oi), T_)["family"] == "financial"
    # three loss years of the last four: family_not_built, whatever the route
    loss = [("2022-12-31", -1.0), ("2023-12-31", -1.0), ("2024-12-31", 0.0), (end, 5.0)]
    assert VF.family(_facts(end, {"Assets": 100.0, "Liabilities": 50.0}), _subs("7372"), _f(loss), T_)["family"] == "family_not_built"
    # a filing accepted after T is not read
    late = _facts(end, {"Assets": 100.0, "Liabilities": 90.0, "Deposits": 60.0})
    sub = _subs("7372")
    sub["filings"]["recent"]["acceptanceDateTime"] = ["2026-12-05T16:00:00.000Z"]
    sub["filings"]["recent"]["filingDate"] = ["2026-12-05"]
    for r in late["facts"]["us-gaap"].values():
        r["units"]["USD"][0]["filed"] = "2026-12-05"
    assert VF.family(late, sub, _f(oi), T_)["base_end"] is None


def test_a_set_archival_cost_of_equity_variable_stops_a_live_formation(monkeypatch):
    monkeypatch.setenv("RS2_ARCHIVAL_COE_DIR", "C:/pinned")
    with pytest.raises(SystemExit) as e:
        FV.main()
    assert "RS2_ARCHIVAL_COE_DIR" in str(e.value)


def test_a_frozen_formation_is_valued_without_the_finished_flag(world):
    (world.inputs / f"formation_{T}.frozen.json").write_bytes(world.map.read_bytes())
    assert FV.main() == 0
    assert [(Path(c[0][3]).stem, c[0][c[0].index("--seed") + 1]) for c in world.calls] == [
        ("AAA", "1000"), ("AAA", "3000"), ("BBB", "1000"), ("BBB", "3000")]
    assert (world.state / f"value_finished_{T}.flag").exists() and not (world.state / f"finished_{T}.flag").exists()


def test_the_closure_is_pinned_and_passed_to_every_valuation(world):
    finish_q1(world)
    assert FV.main() == 0
    pinned = world.value / f"closure_{T}" / "reference_closure.json"
    assert pinned.read_bytes() == world.closure.read_bytes()
    assert {kw["env"]["RS2_REFERENCE_CLOSURE"] for _, kw in world.calls} == {str(pinned)}
    assert index(world)["closure"]["sha256"] == hashlib.sha256(pinned.read_bytes()).hexdigest()
    world.closure.write_text(json.dumps({"asof": "2026-12-04", "erp": 0.05}), encoding="utf-8")   # the monthly rebuild in place
    assert FV.main() == 0 and pinned.read_bytes() != world.closure.read_bytes()                 # later passes keep the pinned copy


def test_a_live_closure_dated_after_T_is_never_pinned(world):
    world.closure.write_text(json.dumps({"asof": "2026-12-04", "erp": 0.05}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        FV.main()
    assert "after T" in str(e.value) and not (world.value / f"closure_{T}").exists()


def test_a_changed_pinned_closure_stops(world):
    assert FV.main() == 0
    (world.value / f"closure_{T}" / "reference_closure.json").write_text(json.dumps({"asof": "2026-11-04", "erp": 0.06}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        FV.main()
    assert "does not recompute" in str(e.value)

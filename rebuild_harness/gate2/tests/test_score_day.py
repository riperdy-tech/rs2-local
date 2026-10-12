"""Plan A0: the scoring-day procedure (refusals, the scoring date, Audit 1, and the rehearsal end to end on a mock run)."""
import json

import pytest

from rebuild_harness.gate2 import sample as sample_mod, score_day as sd, stage2_layer as sl
from rebuild_harness.gate2.tests.test_scoring_outcomes_freeze import run_mock


def test_the_scoring_date_is_the_earliest_data_snapshot_and_never_later():
    assert sd.scoring_date_from("2026-10-14", "2026-10-06", "2026-10-08") == "2026-10-06"
    assert sd.scoring_date_from("2026-10-14", "2026-10-06", "2026-10-08", given="2026-10-01") == "2026-10-01"
    with pytest.raises(ValueError):
        sd.scoring_date_from("2026-10-14", "2026-10-06", "2026-10-08", given="2026-10-07")


def test_preconditions_refuse_an_unfinished_run_unfinished_controls_and_the_packs_store(tmp_path):
    run_mock(tmp_path, n=2)
    pre = sd.preconditions(tmp_path, None, store=tmp_path / "s", packs_store=tmp_path / "s", memory=False)
    text = " ".join(pre["refusals"])
    assert "gate2_finished.flag" in text and "masked control" in text and "repeat control" in text and "packs' store" in text


def test_audit1_finds_look_ahead_counts_coverage_and_draws_a_fixed_hand_check_list():
    rows = [{"key": f"2025-10-31_{i:010d}", "date": "2025-10-31", "family": "operating"} for i in range(30)]
    outs = {r["key"]: {"cik": r["key"][11:], "ticker": "T", "quarters": {"q1": {"filed": "2025-11-10", "revenue_growth": 0.1, "operating_margin_change": 0.0}},
                       "annual": {"status": "ok", "year1_filed": "2026-02-20", "revenue_growth": 0.1, "operating_margin_change": None}} for r in rows}
    outs[rows[0]["key"]]["quarters"]["q1"]["filed"] = "2025-10-31"                   # filed ON T: a look-ahead violation
    outs[rows[1]["key"]]["annual"] = {"status": "year1_not_filed_by_scoring_date"}
    a = sd.audit1(outs, rows)
    assert len(a["look_ahead_violations"]) == 1 and a["look_ahead_violations"][0]["key"] == rows[0]["key"]
    c = a["coverage"]["2025-10-31|operating|growth"]
    assert c["rows"] == 30 and c["q1"] == 30 and c["annual"] == 29 and c["annual_year1_not_filed_by_scoring_date"] == 1
    assert a["coverage"]["2025-10-31|operating|margin"]["annual"] == 0                # None is missing; 0.0 would count
    assert len(a["hand_check"]) == 20 and [h["key"] for h in a["hand_check"]] == [h["key"] for h in sd.audit1(outs, rows)["hand_check"]]


def test_the_rehearsal_runs_every_stage_on_dummy_outcomes_writes_only_outside_the_state_and_agrees(tmp_path):
    state, out = tmp_path / "state", tmp_path / "rehearsal"
    smp = run_mock(state, n=6)
    sl.write_pfail({sl.job_key(j["date"], j["cik"]): {"status": "ok", "p_fail": 0.05} for j in sample_mod.jobs(smp)}, "m", "s", state)
    from rebuild_harness.gate2 import scoring
    rows, _s, _e = scoring.load_rows(state)
    base = tmp_path / "b.json"
    base.write_text(json.dumps({"companies": {r["key"]: {"baselines": {"growth": {"persistence": 0.03, "t4q": 0.02}, "margin": {"persistence": 0.0, "t4q": 0.0}},
                                                         "runrate": {"growth": 0.04, "margin": 0.001}} for r in rows},
                                "pop_median": {}, "pop_median_runrate": {}}), encoding="utf-8")
    assert sd.main(["rehearse", "--state-dir", str(state), "--baselines", str(base), "--out", str(out / "x"), "--draws", "50"]) == 0
    md = (out / "x" / "report.md").read_text(encoding="utf-8")
    assert "Negatives first" in md and "Independent recomputation" in md and "- mismatches: 0" in md and "Audit 1" in md
    assert sd.main(["rehearse", "--state-dir", str(state), "--baselines", str(base), "--out", str(state / "inside")]) == 2   # never into the state


def test_refresh_writes_a_new_dated_snapshot_with_its_sha256_builds_the_store_and_never_overwrites(tmp_path, monkeypatch):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CIK0000000001.json", json.dumps({"cik": 1, "facts": {}}))
    data = buf.getvalue()

    class Resp(io.BytesIO):
        headers = {"Last-Modified": "Wed, 14 Oct 2026 03:00:00 GMT"}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    built = []
    monkeypatch.setattr(sd, "_build_chunk", lambda args: built.append(args) or len(args[2]))

    class P:                                                           # an in-process Pool
        def __init__(self, n): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def map(self, f, xs): return [f(x) for x in xs]
    import multiprocessing
    monkeypatch.setattr(multiprocessing, "Pool", P)
    m = sd.refresh(tmp_path / "sec", tmp_path / "stores", workers=1, opener=lambda req: Resp(data))
    assert m["snapshot_date"] == "2026-10-14" and m["members"] == 1 and m["built"] == 1 and len(m["sha256"]) == 64
    assert (tmp_path / "sec" / "companyfacts_2026-10-14" / "companyfacts.zip").read_bytes() == data
    with pytest.raises(FileExistsError):
        sd.refresh(tmp_path / "sec", tmp_path / "stores", workers=1, opener=lambda req: Resp(data))

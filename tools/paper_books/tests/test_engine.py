"""m3o_engine tests: fixtures only (tests/world.py writes them). Run from the repo root:  python -m pytest tools/paper_books/tests -q"""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as W  # noqa: E402

E, fl = W.E, W.fl
T1, T2, T3 = W.T1, W.T2, W.T3
HIT = "Item 1.03 Bankruptcy or Receivership."


def act(L, T, series, t, kind="at_fill_open"):
    m = [l for l in L["actions"] if (l["formation_T"], l["arm"], l["ticker"], l["kind"]) == (T, series, t, kind)]
    assert len(m) == 1, (T, series, t, kind, len(m))
    return m[0]


def per(marks, series, i, group="main"):
    return marks["groups"][group]["series"][series]["periods"][i]


def r(t, d0, d1):
    """open-to-open return of t, from the fixture prices"""
    return W.price(t, date.fromisoformat(d1))[0] / W.price(t, date.fromisoformat(d0))[0] - 1.0


F1, F2, F3 = W.FILLS[T1], W.FILLS[T2], W.FILLS[T3]


def b_hit(T, days):
    return [(HIT, W.accepted_days_before(T, days))]


def q_world(tmp_path, days=30, **claim_kw):
    """B at T1 carries one occurred bankruptcy claim dated `days` before T1 and printed in its cited item."""
    w = W.World(tmp_path)
    occurred = W.date_days_before(T1, days).strftime("%B %d, %Y")
    w.set(T1, "B", items=[(f"On {occurred} the company announced a filing.", "2026-05-01T12:00:00Z")],
          claims=[W.claim(occurred_on=occurred, **claim_kw)])
    return w


# ---------------------------------------------------------------- E1: effects

def test_restricted_new_entry_is_redistributed(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "B", items=b_hit(T1, 30))
    L, marks = w.run()
    assert act(L, T1, "FB", "B")["action"] == "new_entry_restricted"
    assert act(L, T1, "FB", "B")["causes"] == ["B1"]
    for t in "ACDE":
        assert act(L, T1, "FB", t)["weight_target"] == pytest.approx(0.25)
    assert act(L, T1, "F", "B")["action"] == "enter"
    assert per(marks, "FB", 0)["gross"] == pytest.approx(sum(r(t, F1, F2) for t in "ACDE") / 4)
    assert per(marks, "F", 0)["gross"] == pytest.approx(sum(r(t, F1, F2) for t in ["A", "B", "C", "D", "E", "OPXA"]) / 6)


def test_restricted_incumbent_is_held_not_sold(tmp_path):
    w = W.World(tmp_path)
    w.set(T2, "C", items=b_hit(T2, 10))
    L, marks = w.run()
    a = act(L, T2, "FB", "C")
    assert a["action"] == "hold" and "pending_reunderwriting" in a["flags"]
    assert a["weight_target"] == pytest.approx(0.2)            # A, B, C, D, F
    assert act(L, T2, "FQ", "C")["action"] == "hold"


def test_exit_only_when_A0_drops_a_name(tmp_path):
    w = W.World(tmp_path)
    w.set(T2, "C", items=b_hit(T2, 10))
    L, _ = w.run()
    for s in ("F", "FB", "FQ", "FQ_decisions_only"):
        assert act(L, T2, s, "E")["action"] == "exit" and act(L, T2, s, "E")["reason"] == "left_A0_book"
        assert act(L, T2, s, "D")["action"] == "hold"
    assert act(L, T2, "FB", "C")["action"] != "exit"


# ---------------------------------------------------------------- B1

@pytest.mark.parametrize("days,restricted", [(179, True), (180, True), (181, False)])
def test_b1_180_day_boundary(tmp_path, days, restricted):
    w = W.World(tmp_path)
    w.set(T1, "B", items=b_hit(T1, days))
    L, _ = w.run()
    v = [l for l in L["verification"] if l["ticker"] == "B" and l["formation_T"] == T1][0]
    assert v["b1"]["restricted"] is restricted
    assert v["b1"]["rule"] == E.B1_NAME and "verified" not in E.B1_NAME
    assert (act(L, T1, "FB", "B")["action"] == "new_entry_restricted") is restricted


def test_b1_hit_without_acceptance_does_not_act(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "B", items=[(HIT, None)])
    L, _ = w.run()
    v = [l for l in L["verification"] if l["ticker"] == "B" and l["formation_T"] == T1][0]
    assert v["b1"]["hits"][0]["reason"] == "b_hit_undated" and v["b1"]["restricted"] is False
    assert act(L, T1, "FB", "B")["action"] == "enter"


def test_b1_acceptance_is_read_with_the_later_clock(tmp_path):
    # a Z clock may be Eastern wall time mislabelled Z: 2026-04-03T22:00:00Z is read as 22:00 New York = 2026-04-04 02:00Z
    assert E.accepted_at("2026-04-03T22:00:00Z").isoformat() == "2026-04-04T02:00:00+00:00"
    assert E.accepted_at("2026-04-03T10:00:00").isoformat() == "2026-04-03T14:00:00+00:00"


# ---------------------------------------------------------------- Q1

@pytest.mark.parametrize("days,restricted", [(179, True), (180, True), (181, False)])
def test_q1_180_day_boundary(tmp_path, days, restricted):
    L, _ = q_world(tmp_path, days).run()
    assert (act(L, T1, "FQ", "B")["action"] == "new_entry_restricted") is restricted
    assert act(L, T1, "FB", "B")["action"] == "enter"
    assert act(L, T1, "FQ_decisions_only", "B")["action"] == ("new_entry_restricted" if restricted else "enter")


def test_q1_undated_and_date_unsupported_escalate_and_do_not_act(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "B", items=[("The company filed.", "2026-05-01T12:00:00Z")], claims=[W.claim(occurred_on="not stated")])
    w.set(T1, "C", items=[("The company filed.", "2026-05-01T12:00:00Z")], claims=[W.claim(occurred_on="June 15, 2026")])
    L, marks = w.run()
    for t, why in (("B", "undated"), ("C", "date_unsupported")):
        assert act(L, T1, "FQ", t)["action"] == "enter"
        e = act(L, T1, "FQ", t, "escalation")
        assert e["action"] == "escalation" and e["reason"] == why and e["series_effect"] == "none"
    assert per(marks, "FQ", 0)["gross"] == pytest.approx(per(marks, "FB", 0)["gross"])


def test_q1_announced_pending_acts_without_a_date(tmp_path):
    L, _ = q_world(tmp_path, 30, status="announced_pending").run()
    assert act(L, T1, "FQ", "B")["action"] == "new_entry_restricted" and act(L, T1, "FQ", "B")["causes"] == ["Q1"]


def test_q1_unsupported_critical_claim_does_not_act(tmp_path):
    L, _ = q_world(tmp_path, 30, support="quote_not_found").run()
    assert act(L, T1, "FQ", "B")["action"] == "enter"
    v = [l for l in L["verification"] if l["ticker"] == "B" and l["formation_T"] == T1][0]
    assert v["q1"]["claims"][0]["reason"] == "unsupported_critical_claim"


def test_q1_non_critical_event_type_does_not_act(tmp_path):
    L, _ = q_world(tmp_path, 30, event_type="material_impairment").run()
    assert act(L, T1, "FQ", "B")["action"] == "enter"
    v = [l for l in L["verification"] if l["ticker"] == "B" and l["formation_T"] == T1][0]
    assert v["q1"]["n_noncritical"] == 1 and v["q1"]["claims"] == []


def test_date_forms():
    d = date(2026, 6, 30)
    for s in ("June 30, 2026", "Jun. 30, 2026", "30 June 2026", "30 Jun 2026", "2026-06-30", " June 30, 2026 "):
        assert E.parse_occurred_on(s) == d, s
    for s in ("not stated", "", "Q2 2026", "June 2026", "about June 30, 2026", None, "2026-02-30"):
        assert E.parse_occurred_on(s) is None, s
    assert {x[2] for x in E.scan_dates("on June 30, 2026 and 1 Jul 2026 and 2026-07-02.")} == \
        {d, date(2026, 7, 1), date(2026, 7, 2)}


# ---------------------------------------------------------------- A1S: pending, incomplete, partial

def test_pending_slot_is_cash_then_enters_at_the_first_open_after_finished_at(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "D", finished="2026-08-04T15:00:00.000000Z")          # after the 08-04 open (13:30Z): enters 08-05
    L, marks = w.run()
    a = act(L, T1, "FQ", "D")
    assert a["action"] == "analysis_pending" and a["weight_target"] == 0.0 and a["slot_weight"] == pytest.approx(0.2)
    res = act(L, T1, "FQ", "D", "pending_resolution")
    assert res["action"] == "enter_after_pending" and res["effective_session"] == "2026-08-05"
    p = per(marks, "FQ", 0)
    exp = 0.2 * (sum(r(t, F1, F2) for t in "ABCE")) + 0.2 * r("D", "2026-08-05", F2)
    assert p["gross"] == pytest.approx(exp)
    assert p["turnover_one_way"] == pytest.approx(0.5 * 0.8 + 0.5 * 0.2)
    assert p["cash_drag_pending"] == pytest.approx(0.2 * (r("D", F1, F2) - r("D", "2026-08-05", F2)))
    q = per(marks, "FQ_decisions_only", 0)                          # filled as in FB at the fill
    assert q["gross"] == pytest.approx(0.2 * sum(r(t, F1, F2) for t in "ABCDE"))
    assert act(L, T1, "FQ_decisions_only", "D")["action"] == "enter"


@pytest.mark.parametrize("finished,state,entry", [("2026-08-03T13:30:00.000000Z", "complete", None),
                                                  ("2026-08-03T13:30:00.000001Z", "analysis_pending", "2026-08-04")])
def test_fill_open_boundary(tmp_path, finished, state, entry):
    w = W.World(tmp_path)
    w.set(T1, "D", finished=finished)
    L, _ = w.run()
    q = [l for l in L["qwen"] if l["ticker"] == "D" and l["formation_T"] == T1 and l["kind"] == "at_fill_open"][0]
    assert q["analysis_state"] == state
    if entry:
        assert act(L, T1, "FQ", "D", "pending_resolution")["effective_session"] == entry


def test_complete_qwen_line_labels_the_self_claim_clock(tmp_path):
    L, _ = W.World(tmp_path).run()
    q = [l for l in L["qwen"] if l["ticker"] == "A" and l["formation_T"] == T1][0]
    assert q["finished_at_clock"] == "self_claim_of_the_runner" and q["analysis_state"] == "complete"


def test_pending_that_finishes_after_the_next_fill_appends_and_never_stops(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "D", finished=None)
    first, _ = w.write()
    assert first["actions"] > 0
    assert not [l for l in w.lines("actions") if l["kind"] == "pending_resolution"]
    w.set(T1, "D", finished="2026-09-02T15:00:00.000000Z", state="complete")       # after the 09-01 fill: the slot was cash all period
    again, new_marks = w.write()                                                    # stored fill-open lines are unchanged: no stop
    assert again["actions"] == 1 and again["qwen"] == 1 and again["verification"] == 1 and new_marks is False
    res = [l for l in w.lines("actions") if l["kind"] == "pending_resolution"]
    assert [l["action"] for l in res] == ["enter_after_pending"] and res[0]["effective_session"] == "2026-09-03"
    _, marks = w.run()
    assert per(marks, "FQ", 0)["n_cash_slots"] == 1                                 # an entry on or after the next fill is not in the period
    assert w.write()[0] == dict.fromkeys(E.LINE_FILES, 0)


def test_incomplete_slot_stays_cash_to_the_next_formation(tmp_path):
    w = W.World(tmp_path)
    w.set(T2, "F", state="analysis_incomplete", reason="runner_attempts", finished=None)
    L, marks = w.run()
    assert act(L, T2, "FQ", "F")["action"] == "analysis_pending"
    res = act(L, T2, "FQ", "F", "pending_resolution")
    assert res["action"] == "analysis_incomplete" and "runner_attempts" in res["reason"]
    p = per(marks, "FQ", 1)
    assert p["n_cash_slots"] == 1 and p["cash_drag_pending"] == 0.0
    assert p["cash_drag_incomplete"] == pytest.approx(0.2 * r("F", F2, F3))
    assert act(L, T2, "FQ_decisions_only", "F")["action"] == "enter"          # as in FB


def test_map_state_classifies_a_failed_run_with_a_run_dir(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "A", state="analysis_incomplete", reason="runner_attempts", finished="2026-08-03T15:00:00.000000Z", me_status="infra_error")
    w.set(T1, "B", state="pending", finished="2026-08-03T15:00:00.000000Z", me_status="infra_error")       # attempts left: unresolved
    w.set(T1, "C", state="pending", finished="2026-08-03T15:00:00.000000Z", me_status="malformed")         # malformed is final
    L, _ = w.run()
    assert act(L, T1, "FQ", "A", "pending_resolution")["action"] == "analysis_incomplete"
    assert "runner_attempts" in act(L, T1, "FQ", "A", "pending_resolution")["reason"]
    assert "pending_resolution" not in [l["kind"] for l in L["actions"] if l["ticker"] == "B"]
    assert "malformed" in act(L, T1, "FQ", "C", "pending_resolution")["reason"]
    assert act(L, T1, "FQ", "A")["action"] == "analysis_pending"                    # all three are cash slots, never a factor-only fill


def test_partial_analysis_is_flagged_but_eligible(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "A", run_status="analysis_incomplete")
    L, _ = w.run()
    assert "partial_analysis" in act(L, T1, "FQ", "A")["flags"] and act(L, T1, "FQ", "A")["action"] == "enter"
    q = [l for l in L["qwen"] if l["ticker"] == "A" and l["formation_T"] == T1][0]
    assert q["flags"] == ["partial_analysis"] and q["run_status"] == "analysis_incomplete"


def test_no_factor_only_fill_in_FQ(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "D", finished=None, state="to_run")
    L, _ = w.run()
    assert act(L, T1, "FQ", "D")["action"] != "enter"


# ---------------------------------------------------------------- excluded, zero, missing

def test_operator_excluded_tickers(tmp_path):
    L, marks = W.World(tmp_path).run()
    for s in ("FB", "FQ", "FQ_decisions_only"):
        assert act(L, T1, s, "OPXA")["action"] == "operator_excluded"
    assert act(L, T1, "F", "OPXA")["action"] == "enter" and act(L, T1, "F", "OPXA")["weight_target"] == pytest.approx(1 / 6)
    assert act(L, T1, "FB", "A")["weight_target"] == pytest.approx(0.2)
    assert per(marks, "F_ex_operator", 0)["n"] == 5


def test_zero_return_and_zero_weight_are_values(tmp_path):
    forms = [{"T": T1, "book": ["A", "ZERO", "DEAD", "B"]}, {"T": T2, "book": ["A", "ZERO", "B"]}, {"T": T3, "book": ["A", "ZERO", "B"]}]
    L, marks = W.World(tmp_path, forms).run()
    p = per(marks, "F", 0)
    assert p["no_price_series"] == []                                       # a 0.0 return is not a missing price
    assert p["gross"] == pytest.approx((r("A", F1, F2) + 0.0 - 1.0 + r("B", F1, F2)) / 4)
    a = act(L, T2, "F", "DEAD")                                             # DEAD fell to 0.0: weight 0.0, still a holding
    assert a["action"] == "exit" and a["weight_before"] == 0.0 and "weight_before" in a
    f = [l for l in L["factor"] if l["formation_T"] == T2 and l["ticker"] == "DEAD"][0]
    assert f["held_at_prior_formation"]["F"] is True
    assert act(L, T2, "F", "ZERO")["weight_before"] > 0 and act(L, T2, "F", "ZERO")["action"] == "hold"


def test_missing_price_is_held_as_cash_and_flagged(tmp_path):
    forms = [{"T": T1, "book": ["A", "GONE", "B"]}, {"T": T2, "book": ["A", "GONE", "B"]}, {"T": T3, "book": ["A", "B"]}]
    _, marks = W.World(tmp_path, forms).run()
    p = per(marks, "F", 0)
    assert p["no_price_series"] == [{"ticker": "GONE", "flag": "no_price_series", "event": "missing_entry_bar_held_as_cash"}]
    assert p["gross"] == pytest.approx((r("A", F1, F2) + r("B", F1, F2)) / 3)
    assert per(marks, "F", 1)["n"] == 3                                      # the slot is kept, at 0%


# ---------------------------------------------------------------- inputs refused / stops

def test_analysis_sha_mismatch_is_refused(tmp_path):
    w = W.World(tmp_path)
    w.set(T1, "A", tamper=True)
    with pytest.raises(E.Stop, match="does not hash to the manifest"):
        w.run()


def test_manifest_for_another_ticker_is_refused(tmp_path):
    w = W.World(tmp_path)
    w.materialize()
    mp = w.root / "runs" / f"{T1}_A" / "manifest.json"
    m = json.loads(mp.read_text())
    m["ticker"] = "B"
    mp.write_text(json.dumps(m))
    with pytest.raises(E.Stop, match="manifest of"):
        E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())


def test_a0_book_must_match_factor_scores(tmp_path):
    w = W.World(tmp_path)
    p = w.root / "factor_scores" / f"{w.commit(T1)}.json"
    fs = json.loads(p.read_text())
    fs["tickers"]["Z1"]["fct_band"] = "research_now"
    p.write_text(json.dumps(fs))
    with pytest.raises(E.Stop, match="not the stored A0 book"):
        w.run()


def test_name_missing_from_the_map_stops(tmp_path):
    w = W.World(tmp_path)
    w.materialize()
    mp = w.inputs / f"formation_{T1}.json"
    m = json.loads(mp.read_text())
    del m["names"]["C"]
    mp.write_text(json.dumps(m))
    with pytest.raises(E.Stop, match="no entry for A0 name C"):
        E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())


# ---------------------------------------------------------------- starts and groups

def test_series_start_at_the_first_formation_with_a_map_from_cash(tmp_path):
    forms = [{"T": T1, "book": ["A", "B", "OPXA"], "map": False}, {"T": T2, "book": ["A", "B", "C"]}, {"T": T3, "book": ["A", "B", "C"]}]
    L, marks = W.World(tmp_path, forms).run()
    assert [l["formation_T"] for l in L["formations"]] == [T2, T3]
    assert {l["action"] for l in L["actions"] if l["formation_T"] == T2 and l["kind"] == "at_fill_open"} == {"enter"}
    assert per(marks, "F", 0)["turnover_one_way"] == pytest.approx(0.5)
    assert all(l["weight_before"] == 0.0 for l in L["actions"] if l["formation_T"] == T2)


def test_retrospective_map_is_a_separate_one_period_group(tmp_path):
    forms = [{"T": T1, "book": ["A", "B", "C"], "label": "retrospective"}, {"T": T2, "book": ["A", "B", "C"]}, {"T": T3, "book": ["A", "B", "C"]}]
    L, marks = W.World(tmp_path, forms).run()
    assert set(marks["groups"]) == {"main", f"retrospective_{T1}"}
    retro = marks["groups"][f"retrospective_{T1}"]["series"]["FQ"]["periods"]
    assert len(retro) == 1 and retro[0]["exit"] == F2 and retro[0]["label"] == "retrospective"
    assert len(marks["groups"]["main"]["series"]["FQ"]["periods"]) == 2
    assert {act(L, T2, s, t)["action"] for s in E.SERIES for t in "ABC"} == {"enter"}       # never the retrospective book's successor
    assert act(L, T1, "FQ", "A")["label"] == "retrospective"
    assert act(L, T2, "FQ", "A")["label"] == "shadow_pre_3N_close" and act(L, T2, "F", "A")["label"] == "factor_only"


def test_missing_map_after_the_series_started_stops(tmp_path):
    forms = [{"T": T1, "book": ["A", "B"]}, {"T": T2, "book": ["A", "B"], "map": False}, {"T": T3, "book": ["A", "B"]}]
    with pytest.raises(E.Stop, match="no inputs map"):
        W.World(tmp_path, forms).run()


def test_no_map_yet_gives_nothing(tmp_path):
    forms = [{"T": T1, "book": ["A", "B"], "map": False}]
    L, marks = W.World(tmp_path, forms).run()
    assert marks["groups"] == {} and all(not v for v in L.values())


# ---------------------------------------------------------------- code revisions on every line

def test_lines_carry_code_revisions_and_the_engine_sha(tmp_path):
    L, _ = W.World(tmp_path).run()
    a = act(L, T1, "FQ", "A")
    assert a["qwen_c_commit"] == "qqqqqqqabc" and a["builder_code"] == {"packet.py": "bc-A"}
    for name in E.LINE_FILES:
        assert all(l["engine_sha256"] == E.ENGINE_SHA256 and l["engine_version"] == E.ENGINE_VERSION for l in L[name])
    assert "qwen_c_commit" not in act(L, T1, "F", "A")
    q = [l for l in L["qwen"] if l["ticker"] == "A" and l["formation_T"] == T1][0]
    assert q["qwen_c_commit"] == "qqqqqqqabc" and q["builder_code"] == {"packet.py": "bc-A"}


def test_prereg_constants():
    prereg = json.loads(E.PREREG_M3O.read_text(encoding="utf-8"))
    assert prereg["rules"]["B1"]["item_window_days_before_T"] == E.WINDOW_DAYS == 180
    assert set(prereg["arms"]) == {"F", "FB", "FQ"}


# ---------------------------------------------------------------- accounting

def test_F_equals_forward_ledger(tmp_path, monkeypatch):
    forms = [{"T": T1, "book": ["A", "B", "C", "DEAD", "OPXA"]}, {"T": T2, "book": ["A", "B", "GONE", "C", "OPXA"]},
             {"T": T3, "book": ["A", "C", "GONE", "OPXA"]}]
    w = W.World(tmp_path, forms)
    w.materialize()
    monkeypatch.setattr(fl, "HERE", w.forward)
    monkeypatch.setattr(fl, "FIRST_T", date(2026, 7, 31))
    monkeypatch.setattr(fl, "scoring_runs", lambda: [])

    def decision_for(T, runs):
        k = T.isoformat()
        return ({"run_id": "run" + k, "workflow": "fixture", "decision_time_utc": w.dec(k), "output_commit": w.commit(k),
                 "scoring_base": "b" * 40, "verdict": "PASS", "checks": {}, "input_issues": [], "mri": None}, fl.next_session(T), None)
    monkeypatch.setattr(fl, "decision_for", decision_for)
    by_commit = {w.commit(f["T"]): f["book"] for f in forms}
    monkeypatch.setattr(fl, "book", lambda res: (sorted(by_commit[res["output_commit"]]), {}))
    monkeypatch.setattr(fl, "fetch_prices", lambda tickers, start, end: (w.px, {"fixture": True}))
    monkeypatch.setattr(sys, "argv", ["forward_ledger.py", "--asof", "2026-10-16"])
    fl.main()
    mtm = json.loads(next(w.forward.glob("mtm_*.json")).read_text())
    _, marks = E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())
    assert len(mtm["periods"]) == 3
    for i, p in enumerate(mtm["periods"]):
        for theirs, ours in (("A0", "F"), ("A0_ex_operator", "F_ex_operator")):
            mine = per(marks, ours, i)
            assert mine["gross"] == pytest.approx(p[theirs]["gross"], abs=1e-12)
            assert mine["turnover_one_way"] == pytest.approx(p[theirs]["turnover_one_way"], abs=1e-12)
            for c in (0, 20, 60):
                assert mine[f"net_{c}bp"] == pytest.approx(p[theirs][f"net_{c}bp"], abs=1e-12)
            assert mine["n"] == p[theirs]["n"]
        assert per(marks, "F", i)["spy"] == pytest.approx(p["SPY"], abs=1e-12)


def test_quarterly_book_accounting_drifts_and_trades_only_in_rebalance_months():
    assert E.is_rebalance_month("2026-09-30", True) and E.is_rebalance_month("2026-12-31", True)
    assert not E.is_rebalance_month("2026-10-30", True) and not E.is_rebalance_month("2026-11-30", True)
    assert E.is_rebalance_month("2026-10-30", False)
    pre = {"CASH": 1.0}
    s1 = E.monthly_step(pre, {"A": 0.10, "B": 0.0}, {"A": 0.5, "B": 0.5})            # quarter: trade from cash
    assert s1["turnover"] == pytest.approx(0.5) and s1["post"]["A"] == pytest.approx(0.55 / 1.05)
    s2 = E.monthly_step(s1["post"], {"A": 0.0, "B": 0.10}, None)                     # skipped month: no order, weights drift
    assert s2["turnover"] == 0.0 and s2["orders"] is False
    assert s2["post"]["A"] == pytest.approx((0.55 / 1.05) / (1 + (0.55 / 1.05) * 0 + (0.5 / 1.05) * 0.10))
    s3 = E.monthly_step(s2["post"], {"A": 0.0, "B": 0.0}, {"A": 0.5, "B": 0.5})      # next quarter: turnover from drifted weights
    assert s3["turnover"] == pytest.approx(0.5 * (abs(0.5 - s2["post"]["A"]) + abs(0.5 - s2["post"]["B"])))
    assert E.monthly_step({"A": 0.5, "CASH": 0.5}, {"A": 0.1}, None)["post"]["CASH"] == pytest.approx(0.5 / 1.05)   # cash accrues 0
    assert E.monthly_step({"A": 0.5, "B": 0.5}, {"A": 0.0, "B": 0.0}, None)["gross_ret"] == 0.0                     # 0.0 is a value
    with pytest.raises(ValueError, match="missing next-session"):
        E.monthly_step({"A": 1.0}, {}, None)


# test_monthly_step_is_the_baselineA_function was removed on the move (2026-11-03): it imported stocks-workspace/scratch/baselineA, a
# cross-repository import. It passed in scratch on 2026-11-03 against the unchanged monthly_step.


def test_cumulative_and_drawdown():
    ps = [{"gross": g, "spy": 0.01, "turnover_one_way": 0.5, "cash_drag_pending": 0.0, "cash_drag_incomplete": 0.0,
           **{f"net_{c}bp": g - 0.5 * c / 1e4 for c in (0, 20, 60)}} for g in (0.10, -0.20, 0.05)]
    s = E.summarize(ps)
    assert s["cumulative_gross"] == pytest.approx(1.1 * 0.8 * 1.05 - 1)
    assert s["max_drawdown_gross"] == pytest.approx(0.8 - 1)
    assert s["factor_adjusted"] == "not_estimable" and s["not_yet_validated"] is True


# ---------------------------------------------------------------- the ledger

def test_a_rerun_appends_nothing(tmp_path):
    w = W.standard(tmp_path)
    first, new = w.write()
    assert new and all(first[k] > 0 for k in E.LINE_FILES)
    before = {p.name: p.read_bytes() for p in w.ledger.rglob("*.json*")}
    second, new2 = w.write()
    assert second == dict.fromkeys(E.LINE_FILES, 0) and new2 is False
    assert before == {p.name: p.read_bytes() for p in w.ledger.rglob("*.json*")}


@pytest.mark.parametrize("name,field,value", [("actions", "weight_target", 0.123), ("verification", "kind", "x"), ("qwen", "run_id", "other"),
                                              ("factor", "rank", 99), ("formations", "run_id", "other")])
def test_a_changed_stored_line_stops(tmp_path, name, field, value):
    w = W.standard(tmp_path)
    w.write()
    p = w.ledger / f"{name}.jsonl"
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    target = next(l for l in lines if field in l and (name != "actions" or l["arm"] == "FB"))
    target[field] = value
    p.write_text("\n".join(json.dumps(l, sort_keys=True) for l in lines) + "\n")
    with pytest.raises(E.Stop, match=name + ".jsonl"):
        w.write()


def test_a_stored_line_with_no_recomputation_stops(tmp_path):
    w = W.standard(tmp_path)
    w.write()
    p = w.ledger / "actions.jsonl"
    extra = json.loads(p.read_text().splitlines()[0])
    extra["ticker"] = "NOPE"
    p.write_text(p.read_text() + json.dumps(extra) + "\n")
    with pytest.raises(E.Stop, match="no recomputation"):
        w.write()


def test_changed_marks_stop_and_price_noise_does_not(tmp_path):
    w = W.standard(tmp_path)
    w.write()
    mp = next((w.ledger / "marks").glob("*.json"))
    m = json.loads(mp.read_text())
    m["groups"]["main"]["series"]["F"]["periods"][0]["gross"] += 1e-9           # below the tolerance: price-fetch noise
    mp.write_text(json.dumps(m))
    w.write()
    m["groups"]["main"]["series"]["F"]["periods"][0]["gross"] += 0.01
    mp.write_text(json.dumps(m))
    with pytest.raises(E.Stop, match="marks/"):
        w.write()


def test_a_new_price_fetch_or_map_update_does_not_stop_stored_lines(tmp_path):
    w = W.standard(tmp_path)
    w.write()
    inp = w.inputs / f"formation_{T1}.json"
    m = json.loads(inp.read_text())
    m["names"]["A"]["attempts"] = 2                                              # a harmless map change changes the map sha only
    inp.write_text(json.dumps(m))
    L, marks = E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())
    assert all(not E.reconcile(w.ledger / f"{k}.jsonl", k, L[k]) for k in E.LINE_FILES)


def test_nothing_is_written_when_a_later_file_differs(tmp_path):
    w = W.standard(tmp_path)
    w.write()
    p = w.ledger / "verification.jsonl"
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    lines[0]["b1"]["restricted"] = not lines[0]["b1"]["restricted"]
    p.write_text("\n".join(json.dumps(l, sort_keys=True) for l in lines) + "\n")
    w.set(T3, "A", items=b_hit(T3, 5))                                           # would also add a new line elsewhere
    sizes = {q.name: q.stat().st_size for q in w.ledger.glob("*.jsonl")}
    with pytest.raises(E.Stop):
        w.write()
    assert sizes == {q.name: q.stat().st_size for q in w.ledger.glob("*.jsonl")}


# ---------------------------------------------------------------- the checked-in fixtures

def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file() and "ledger" not in p.parts}


def test_checked_in_fixtures_are_the_standard_scenario(tmp_path):
    fixtures = Path(__file__).resolve().parent / "fixtures"
    W.standard(tmp_path / "regen")
    assert _tree(fixtures) == _tree(tmp_path / "regen")


def test_engine_on_the_checked_in_fixtures(tmp_path):
    fixtures = Path(__file__).resolve().parent / "fixtures"
    shutil.copytree(fixtures, tmp_path / "f")
    root = tmp_path / "f"
    L, marks = E.run(root / "forward", root / "inputs", root / "ledger",
                     factor_loader=lambda c: (root / "factor_scores" / f"{c}.json").read_bytes())
    assert [len(L[k]) for k in E.LINE_FILES] == [3, 19, 17, 16, 78]
    assert act(L, T1, "FB", "B")["action"] == "new_entry_restricted"
    assert act(L, T1, "FQ", "D", "pending_resolution")["effective_session"] == "2026-08-05"
    assert act(L, T2, "FQ", "F", "pending_resolution")["action"] == "analysis_incomplete"
    assert marks["asof_price_date"] == "2026-10-16"


def test_post_3n_label_flips_at_the_first_formation_after_close():
    # CLOSE_3N 2026-10-31: the 10-30 formation stays shadow, 11-30 on is paper_post_3N; F is never relabelled
    assert E.arm_label("FQ", "2026-10-30") == "shadow_pre_3N_close"
    assert E.arm_label("FB", "2026-11-30") == "paper_post_3N"
    assert E.arm_label("F", "2026-11-30") == "factor_only"
    assert E.arm_label("FQ", "2026-11-30", retro=True) == "retrospective"

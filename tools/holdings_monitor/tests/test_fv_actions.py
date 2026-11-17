"""WO_TB2b part 2: the monitor's warnings act on paper book FV (fv_actions.py). Synthetic names only; the engine's view, the packet builder, the
valuation slot, the consensus, prices, GPU and clock are all injected, so no network, GPU or real file is touched."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fv_actions as A
import monitor as M
import m3o_engine as E
from helpers import sha

T1 = "2026-11-30"
DECISION_1 = "2026-11-30T21:00:00Z"
READ_OK = "2026-12-02T01:00:00Z"                 # a read after the decision
READ_OLD = "2026-11-20T01:00:00Z"                # a read before it: the formation's valuation could see it
NOW = datetime(2026, 12, 3, 15, 0, tzinfo=timezone.utc)          # a Thursday, after the open
CHECK_COMMIT = "c" * 40


def jl(path):
    return M._jsonl(path)


class World:
    """A synthetic monitor root, value folder and set of injected parts."""

    def __init__(self, tmp_path):
        self.root, self.value = tmp_path / "monitor", tmp_path / "value"
        self.checks = tmp_path / "checks"
        self.tmp = tmp_path
        self.calls = {"build": [], "slot": [], "consensus": [], "prices": []}
        self.now = NOW
        self.names = {}                              # index names of T1
        self.view = {"T": T1, "decision_time_utc": DECISION_1, "held": ["AAA", "BBB"], "cut": 1.0, "lines": {}, "exits": [], "pending_T": None}
        self.closes = [{"date": "2026-11-27", "close": 10.0}, {"date": "2026-11-30", "close": 20.0}, {"date": "2026-12-02", "close": 30.0}]
        self.price_error = None
        self.build_refuses = False
        self.base, self.shares, self.shares2 = 1.0, 100.0, None
        self.consensus_status = "ok"
        self.slot_script = {}                        # seed -> outcome dict overriding a normal filled slot
        self.gpu_ok = True
        self.q1_waiting = False
        self.dirty_text = ""
        self.value_lock = True
        self.unlocked = 0
        self.index_name("AAA")
        self.index_name("BBB")
        self.checks.mkdir(parents=True)
        (self.checks / "check_1.json").write_text(json.dumps([{"verdict": "PASS", "pair": "PASS", "output_commit": CHECK_COMMIT,
                                                                "run_updated_at": "2026-11-01T00:00:00Z", "run_id": 1}]), encoding="utf-8")
        self.pin(T1)
        self.write_index()

    def pin(self, T):
        (self.value / f"anchors_{T}").mkdir(parents=True, exist_ok=True)
        (self.value / f"closure_{T}").mkdir(parents=True, exist_ok=True)
        (self.value / f"closure_{T}" / "reference_closure.json").write_text("{}", encoding="utf-8")

    def index_name(self, t, **over):
        self.names[t] = {"cik": 11, "sector": "Industrials", "family": "operating", "market_cap": 1000.0, "slots": {}, **over}

    def write_index(self, T=T1):
        self.value.mkdir(parents=True, exist_ok=True)
        (self.value / f"formation_{T}.json").write_text(json.dumps({"formation_T": T, "git": "g" * 40, "names": self.names}), encoding="utf-8")

    def warn(self, ticker, kind, read=READ_OK, n=1):
        line = {"kind": "resolved", "event_id": f"resolved:{ticker}:{kind}:{n}", "ticker": ticker, "warning_kind": kind, "run_id": f"{ticker}_{kind}_{n}",
                "decision_time_utc": read, "t": read}
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / "journal.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        return line["event_id"]

    # -- the injected parts
    def prices(self, t):
        self.calls["prices"].append(t)
        if self.price_error:
            raise M.MonitorError(self.price_error)
        return {"closes": self.closes}

    def build(self, ticker, T, commit, check_file, repo, cwd):
        self.calls["build"].append((ticker, T, commit))
        if self.build_refuses:
            raise M.PacketRefused("no packet")
        p = self.tmp / f"packet_{ticker}_{len(self.calls['build'])}.json"
        p.write_text(json.dumps({"ticker": ticker, "decision_time_utc": T}), encoding="utf-8")
        return {"packet": str(p), "packet_sha256": sha(p.read_bytes()), "builder_version": "v6"}

    def slot(self, n, seed, fields, anchors, closure):
        self.calls["slot"].append({"seed": seed, "fields": dict(fields), "anchors": str(anchors), "closure": str(closure), "packet": n["packet"]})
        if seed in self.slot_script:
            return self.slot_script[seed]
        shares = self.shares2 if (seed == 3000 and self.shares2 is not None) else self.shares
        body = {"status": "ok", "base": {"shares": shares}} if shares is not None else {"status": "ok", "base": {}}
        p = self.tmp / f"result_{Path(n['packet']).stem}_{seed}.json"
        p.write_text(json.dumps(body), encoding="utf-8")
        return {"outcome": "filled", "status": "ok", "reason": None, "result": str(p), "result_sha256": sha(p.read_bytes()), "seconds": 1.0, "git": "g" * 40}

    def consensus(self, n, fields, ok, anchors, closure):
        self.calls["consensus"].append({"seeds": sorted(ok), "market_cap": fields["market_cap"]})
        return {"status": self.consensus_status, "values": {"base": self.base}, "annotations": ["seeds_disagree"] if len(ok) > 1 else []}

    def run(self, dry_run=False, **over):
        kw = dict(value_dir=self.value, checks_dir=self.checks, screener_repo="repo", worktree="wt", dry_run=dry_run, engine=lambda: self.view,
                  build=self.build, slot=self.slot, consensus=self.consensus, prices=self.prices, gpu=lambda: (self.gpu_ok, None if self.gpu_ok else "gpu_busy"),
                  waiting=lambda: self.q1_waiting, dirty=lambda: self.dirty_text, lock_value=self._lock, unlock_value=self._unlock, clock=lambda: self.now)
        kw.update(over)
        return A.run_pass(self.root, **kw)

    def _lock(self):
        return self.value_lock

    def _unlock(self):
        self.unlocked += 1

    # -- reading back
    def journal(self, kind=None):
        rows = jl(self.root / "fv_actions.jsonl")
        return [r for r in rows if kind is None or r["kind"] == kind]

    def exits(self):
        return jl(self.value / "fv_exits.jsonl")

    @property
    def flag(self):
        return self.root / "state" / "fv_actions_STOP.flag"


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


# ---------------------------------------------------------------- 1. news_event

def test_news_event_exits_under_review_without_a_valuation(w):
    eid = w.warn("AAA", "news_event")
    rep = w.run()
    assert rep["exit"] == 0 and rep["decided"] == [{"ticker": "AAA", "warning_event_id": eid, "outcome": "under_review"}]
    assert w.calls["slot"] == [] and w.calls["build"] == [] and w.calls["prices"] == []
    (d,) = w.journal("decided")
    (rec,) = w.exits()
    assert d["event_id"] == "decided:" + eid and d["outcome"] == "under_review" and d["formation_T"] == T1 and d["run_id"] == "AAA_news_event_1"
    assert set(rec) == set(E.EXIT_KEYS) and rec["revaluation"] is None and d["revaluation"] is None
    assert rec == {"formation_T": T1, "ticker": "AAA", "reason": "under_review", "warning_kind": "news_event", "warning_event_id": eid,
                   "decided_utc": "2026-12-03T15:00:00Z", "effective_session": "2026-12-04", "revaluation": None}
    assert d["exit_record"] == rec and d["decided_utc"] == rec["decided_utc"]
    assert [(r, t) for r, t in [(x["formation_T"], x["ticker"]) for x, _ in E.fv_exits(w.value)]] == [(T1, "AAA")]   # the engine reads it without a stop


@pytest.mark.parametrize("now,expected", [(datetime(2026, 12, 4, 22, 0, tzinfo=timezone.utc), "2026-12-07"),      # Friday after the open: Monday
                                          (datetime(2026, 12, 5, 12, 0, tzinfo=timezone.utc), "2026-12-07"),      # Saturday
                                          (datetime(2026, 12, 3, 10, 0, tzinfo=timezone.utc), "2026-12-03"),      # before the open: the same day
                                          (datetime(2026, 12, 3, 14, 30, tzinfo=timezone.utc), "2026-12-04")])    # exactly at the open: strictly after
def test_effective_session_is_the_first_open_strictly_after_the_decision(w, now, expected):
    w.warn("AAA", "news_event")
    w.now = now
    w.run()
    (rec,) = w.exits()
    assert rec["effective_session"] == expected
    E.fv_exits(w.value)


# ---------------------------------------------------------------- 2. event_found: the cut

@pytest.mark.parametrize("base,cut,exits", [(14.9, 1.0, True), (15.0, 1.0, False), (30.0, 1.0, False),      # below, at, above the cut
                                            (-2.0, 1.0, True), (0.0, 1.0, True), (0.0, 0.0, False), (-1.0, 0.0, True), (5.0, None, False)])
def test_event_found_exits_below_the_cut_and_stays_at_or_above_it(w, base, cut, exits):
    """price_T 20, price_now 30: moved cap 1500; shares 100, so cheapness = base * 100 / 1500."""
    w.base, w.view["cut"] = base, cut
    w.warn("AAA", "event_found")
    rep = w.run()
    (d,) = w.journal("decided")
    cheap = base * 100.0 / 1500.0
    rv = d["revaluation"]
    assert rv["cheapness"] == pytest.approx(cheap) and rv["cut"] == cut and rv["value_base"] == base and rv["shares"] == 100.0
    assert d["outcome"] == ("revalued_not_cheap" if exits else "revalued_stays")
    assert len(w.exits()) == (1 if exits else 0)
    if exits:
        (rec,) = w.exits()
        assert rec["reason"] == "revalued_not_cheap" and rec["revaluation"] == rv and rec["warning_kind"] == "event_found"
        E.fv_exits(w.value)
    assert rep["exit"] == 0


def test_at_the_cut_stays_exactly(w):
    w.base, w.view["cut"] = 1.0, 100.0 / 1500.0                     # cheapness is exactly the cut
    w.warn("AAA", "thesis_changed")
    w.run()
    assert [d["outcome"] for d in w.journal("decided")] == ["revalued_stays"] and w.exits() == []


def test_a_zero_and_a_negative_cheapness_are_values_with_the_number_on_the_record(w):
    for t, base in (("AAA", 0.0), ("BBB", -3.0)):
        w.base = base
        w.warn(t, "event_found")
        w.run()
    recs = {r["ticker"]: r for r in w.exits()}
    assert recs["AAA"]["revaluation"]["cheapness"] == 0.0 and recs["AAA"]["revaluation"]["value_base"] == 0.0
    assert recs["BBB"]["revaluation"]["cheapness"] == pytest.approx(-300.0 / 1500.0) and recs["BBB"]["revaluation"]["reason"] is None


# ---------------------------------------------------------------- 3. no value

def reason_of(w):
    (d,) = w.journal("decided")
    assert d["outcome"] == "revalued_not_cheap" and len(w.exits()) == 1
    return d["revaluation"]["reason"]


def test_not_in_the_index_exits(w):
    del w.names["AAA"]
    w.write_index()
    w.warn("AAA", "event_found")
    w.run()
    assert reason_of(w) == "not_in_index" and w.calls["prices"] == [] and w.calls["slot"] == []


@pytest.mark.parametrize("field,value", [("cik", None), ("sector", ""), ("family", None), ("market_cap", None), ("market_cap", 0)])
def test_a_missing_field_exits(w, field, value):
    w.index_name("AAA", **{field: value})
    w.write_index()
    w.warn("AAA", "event_found")
    w.run()
    assert reason_of(w) == "field_missing" and w.calls["slot"] == []
    assert w.journal("decided")[0]["revaluation"]["detail"] == [field]


def test_a_packet_that_cannot_be_built_waits_twice_and_is_no_value_at_the_third_failure(w):
    w.build_refuses = True
    w.warn("AAA", "event_found")
    for k in (1, 2):                                                  # a refusal and a network failure look alike: it is tried again
        rep = w.run()
        assert rep["decided"] == [] and w.journal("decided") == [] and w.exits() == []
        assert [(x["reason"], x["attempt"]) for x in w.journal("waiting")] == [("packet_not_built", a) for a in range(1, k + 1)]
    w.run()
    d = w.journal("decided")[0]
    assert reason_of(w) == "packet_refused" and w.calls["slot"] == [] and d["revaluation"]["detail"] == "no packet"
    assert d["revaluation"]["packet_attempts"] == 3 and len(w.exits()) == 1


def test_a_packet_built_at_the_second_try_is_valued(w):
    w.build_refuses = True
    w.warn("AAA", "event_found")
    w.run()
    w.build_refuses = False
    w.run()
    assert w.journal("decided")[0]["revaluation"]["reason"] is None and len(w.calls["slot"]) == 2


def test_no_verified_commit_is_a_refused_packet_at_the_third_pass(w):
    (w.checks / "check_1.json").unlink()
    w.warn("AAA", "event_found")
    w.run(), w.run(), w.run()
    assert reason_of(w) == "packet_refused" and w.calls["build"] == []


def test_consensus_not_ok_exits(w):
    w.consensus_status = "no_call"
    w.warn("AAA", "event_found")
    w.run()
    assert reason_of(w).startswith("no_value")


def test_both_seeds_unchecked_exits_without_the_consensus(w):
    w.slot_script = {s: {"outcome": "filled", "status": "no_call", "reason": "thin_evidence", "result": None, "result_sha256": None, "seconds": 1.0, "git": "g"}
                     for s in (1000, 3000)}
    w.warn("AAA", "event_found")
    w.run()
    assert reason_of(w).startswith("no_value") and w.calls["consensus"] == []


def test_shares_missing_exits(w):
    w.shares = None
    w.warn("AAA", "event_found")
    w.run()
    assert reason_of(w) == "shares_missing"


def test_shares_that_differ_exit(w):
    w.shares2 = 101.0
    w.warn("AAA", "event_found")
    w.run()
    assert reason_of(w) == "shares_differ"


# ---------------------------------------------------------------- 4. the arithmetic and the slot's arguments

def test_the_moved_cap_the_cheapness_and_the_slot_arguments(w):
    w.base = 9.0
    w.warn("AAA", "event_found")
    w.run()
    (d,) = w.journal("decided")
    rv = d["revaluation"]
    assert (rv["price_T"], rv["price_now"], rv["market_cap"], rv["market_cap_moved"]) == (20.0, 30.0, 1000.0, 1500.0)
    assert rv["equity_value"] == 900.0 and rv["cheapness"] == pytest.approx(0.6) and rv["cut"] == 1.0
    assert [c["seed"] for c in w.calls["slot"]] == [1000, 3000]
    for c in w.calls["slot"]:
        assert c["fields"] == {"cik": 11, "sector": "Industrials", "family": "operating", "market_cap": 1500.0}
        assert c["anchors"] == str(w.value / f"anchors_{T1}") and c["closure"] == str(w.value / f"closure_{T1}" / "reference_closure.json")
    assert w.calls["consensus"] == [{"seeds": ["1000", "3000"], "market_cap": 1500.0}]
    assert w.calls["build"] == [("AAA", READ_OK, CHECK_COMMIT)] and w.calls["prices"] == ["AAA"]
    assert rv["packet"] and rv["packet_sha256"] and rv["code_commit"] == "g" * 40 and sorted(rv["slots"]) == ["1000", "3000"]
    assert rv["consensus_status"] == "ok" and rv["consensus_annotations"] == ["seeds_disagree"]


def test_price_t_is_the_last_bar_of_the_seven_days_before_the_formation(w):
    w.closes = [{"date": "2026-11-23", "close": 5.0}, {"date": "2026-11-25", "close": 8.0}, {"date": "2026-12-02", "close": 16.0}]
    w.warn("AAA", "event_found")
    w.run()
    rv = w.journal("decided")[0]["revaluation"]
    assert rv["price_T"] == 8.0 and rv["market_cap_moved"] == 2000.0           # 11-23 is 7 days before: in the window, but 11-25 is later


def test_pick_prices_edges():
    assert A.pick_prices({"closes": [{"date": "2026-11-20", "close": 5.0}, {"date": "2026-12-02", "close": 0.0}]}, T1) == (None, 0.0)   # 10 days before: no price_T; 0.0 is a close
    assert A.pick_prices({"closes": []}, T1) == (None, None)
    assert A.pick_prices({"closes": [{"date": "2026-11-30", "close": 3.0}, {"date": "2026-12-01", "close": float("nan")}]}, T1) == (3.0, 3.0)


def test_a_price_now_of_zero_is_a_value(w):
    w.closes = [{"date": "2026-11-30", "close": 20.0}, {"date": "2026-12-02", "close": 0.0}]
    w.warn("AAA", "event_found")
    w.run()
    rv = w.journal("decided")[0]["revaluation"]
    assert rv["market_cap_moved"] == 0.0 and w.calls["slot"][0]["fields"]["market_cap"] == 0.0


# ---------------------------------------------------------------- 5. not acted on

def test_warnings_that_are_not_acted_on(w):
    w.warn("ZZZ", "news_event")                                  # a name FV does not hold
    w.warn("AAA", "news_event", read=READ_OLD)                    # read before the decision
    eid = w.warn("BBB", "news_event")
    w.warn("BBB", "thesis_changed", n=2)                          # BBB: a news_event and another warning
    done = w.warn("AAA", "event_found", n=3)                      # already decided
    w.root.mkdir(parents=True, exist_ok=True)
    (w.root / "fv_actions.jsonl").write_text(json.dumps({"kind": "decided", "event_id": "decided:" + done, "warning_event_id": done, "ticker": "AAA"}) + "\n")
    rep = w.run()
    assert [d["ticker"] for d in rep["decided"]] == ["BBB"] and rep["decided"][0]["warning_event_id"] == eid
    assert [r["ticker"] for r in w.exits()] == ["BBB"] and w.calls["slot"] == []


def test_a_name_already_exiting_is_covered_not_acted_on(w):
    w.view["exits"] = [(T1, "AAA")]
    a, b = w.warn("AAA", "news_event"), w.warn("AAA", "event_found", n=2)
    rep = w.run()
    assert rep["decided"] == [] and sorted(rep["covered"]) == sorted([a, b]) and w.exits() == []
    cov = w.journal("covered")
    assert {c["warning_event_id"]: c["reason"] for c in cov} == {a: "already_exiting", b: "already_exiting"}
    assert w.calls["slot"] == [] and w.calls["prices"] == []
    assert w.run()["covered"] == []                                # written once: the next pass finds them handled


# ---------------------------------------------------------------- 6. several warnings on one ticker

def test_a_news_event_wins_without_a_valuation(w):
    a, b, c = w.warn("AAA", "event_found", n=1), w.warn("AAA", "news_event", read="2026-12-01T01:00:00Z", n=2), w.warn("AAA", "thesis_changed", n=3)
    rep = w.run()
    assert [(d["outcome"], d["warning_event_id"]) for d in rep["decided"]] == [("under_review", b)]
    assert {x["warning_event_id"]: x["reason"] for x in w.journal("covered")} == {a: "covered_by_news_event", c: "covered_by_news_event"}
    assert w.calls["slot"] == [] and w.calls["build"] == []


def test_two_revaluation_warnings_give_one_revaluation_on_the_newest(w):
    old = w.warn("AAA", "event_found", read="2026-12-01T01:00:00Z", n=1)
    new = w.warn("AAA", "thesis_changed", read="2026-12-02T09:00:00Z", n=2)
    w.run()
    assert [c[1] for c in w.calls["build"]] == ["2026-12-02T09:00:00Z"] and len(w.calls["slot"]) == 2
    (d,) = w.journal("decided")
    assert d["warning_event_id"] == new
    assert [(c["warning_event_id"], c["reason"], c["covered_by"]) for c in w.journal("covered")] == [(old, "covered_by_revaluation", "decided:" + new)]


# ---------------------------------------------------------------- 7. between the snapshot and the fill

def test_a_warning_waits_while_the_next_decision_is_not_priced_then_is_acted_on_under_it(w):
    eid = w.warn("AAA", "news_event", read="2026-12-29T01:00:00Z")
    w.view["pending_T"] = "2026-12-31"                            # fv_2026-12-31.json exists, its fill is not priced
    rep = w.run()
    assert rep["decided"] == [] and rep["waiting"] == [eid] and w.exits() == []
    (wl,) = w.journal("waiting")
    assert wl["reason"] == "decision_not_priced" and wl["warning_event_id"] == eid
    w.run()
    assert len(w.journal("waiting")) == 1                          # once per day
    w.names, w.view = {}, {**w.view, "T": "2026-12-31", "decision_time_utc": "2026-12-31T21:00:00Z", "pending_T": None, "held": ["AAA"]}
    w.index_name("AAA")
    w.write_index("2026-12-31")
    w.now = datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc)      # the new decision is priced
    rep = w.run()
    # the read (12-29) is before the new decision's time (12-31): its valuation could see it; the warning is not acted on under it
    assert rep["decided"] == []
    eid2 = w.warn("AAA", "news_event", read="2027-01-02T01:00:00Z", n=2)
    rep = w.run()
    assert [(d["warning_event_id"]) for d in rep["decided"]] == [eid2] and [r["formation_T"] for r in w.exits()] == ["2026-12-31"]


def test_a_warning_after_the_new_decision_waited_for_it_and_is_acted_on_under_it(w):
    eid = w.warn("AAA", "news_event", read="2026-12-31T22:00:00Z")      # after the snapshot's formation time, before its fill
    w.view["pending_T"] = "2026-12-31"
    w.run()
    assert w.exits() == []
    w.view = {**w.view, "T": "2026-12-31", "decision_time_utc": "2026-12-31T21:00:00Z", "pending_T": None, "held": ["AAA"]}
    w.write_index("2026-12-31")
    w.now = datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc)
    rep = w.run()
    assert [d["warning_event_id"] for d in rep["decided"]] == [eid]
    assert w.exits()[0]["formation_T"] == "2026-12-31" and w.exits()[0]["effective_session"] == "2027-01-05"


# ---------------------------------------------------------------- 8. resume, failures, the flag

def test_a_price_no_slot_has_used_is_taken_again_on_a_later_day(w):
    from datetime import timedelta
    w.warn("AAA", "event_found")
    w.gpu_ok = False
    assert w.run()["exit"] == 4 and w.calls["prices"] == ["AAA"] and w.calls["slot"] == []     # the GPU was busy: no slot used the price
    assert w.run()["exit"] == 4 and w.calls["prices"] == ["AAA"]                              # the same day: the price is kept
    w.now = w.now + timedelta(days=1)
    w.closes = w.closes + [{"date": w.now.date().isoformat(), "close": 60.0}]
    w.gpu_ok = True
    assert w.run()["exit"] == 0 and w.calls["prices"] == ["AAA", "AAA"]
    rv = w.journal("decided")[0]["revaluation"]
    assert rv["price_now"] == 60.0 and all(c["fields"]["market_cap"] == rv["market_cap_moved"] for c in w.calls["slot"])


def test_a_pass_stopped_after_seed_1000_runs_only_seed_3000_next(w):
    w.warn("AAA", "event_found")
    calls = {"n": 0}

    def gpu():
        calls["n"] += 1
        return (calls["n"] == 1), "gpu_busy"
    rep = w.run(gpu=gpu)
    assert rep["exit"] == 4 and [c["seed"] for c in w.calls["slot"]] == [1000] and w.journal("decided") == []
    assert sorted(json.loads((w.root / "state" / "fv_actions.json").read_text())["revals"].popitem()[1]["slots"]) == ["1000"]
    rep = w.run()
    assert rep["exit"] == 0 and [c["seed"] for c in w.calls["slot"]] == [1000, 3000]
    assert w.calls["prices"] == ["AAA"] and len(w.calls["build"]) == 1               # the price and the packet were kept
    assert len(w.journal("decided")) == 1 and w.journal("slot_filled")[0]["seed"] == 1000
    assert json.loads((w.root / "state" / "fv_actions.json").read_text())["revals"] == {}


def test_other_guards_end_the_pass_before_a_slot(w):
    w.warn("AAA", "event_found")
    w.q1_waiting = True
    assert w.run()["exit"] == 4
    w.q1_waiting, w.value_lock = False, False
    assert w.run()["exit"] == 4
    w.value_lock, w.dirty_text = True, " M tracked.py"
    assert w.run()["exit"] == 6
    assert w.calls["slot"] == [] and w.journal("decided") == [] and not w.flag.exists()
    w.dirty_text = ""
    assert w.run()["exit"] == 0 and len(w.calls["slot"]) == 2 and w.unlocked >= 1


def test_price_unavailable_waits_once_a_day_and_retries(w):
    eid = w.warn("AAA", "event_found")
    w.price_error = "no close"
    for _ in range(2):
        rep = w.run()
        assert rep["exit"] == 0 and rep["decided"] == []
    (wl,) = w.journal("waiting")
    assert wl["reason"] == "price_unavailable" and wl["warning_event_id"] == eid
    w.now = datetime(2026, 12, 4, 15, 0, tzinfo=timezone.utc)
    w.run()
    assert len(w.journal("waiting")) == 2
    w.price_error = None
    assert w.run()["decided"][0]["warning_event_id"] == eid and w.calls["slot"] != []
    w.closes = [{"date": "2026-11-30", "close": 0.0}, {"date": "2026-12-02", "close": 5.0}]     # a price_T that is not above zero also waits
    w.warn("BBB", "event_found")
    assert w.run()["decided"] == [] and w.journal("waiting")[-1]["warning_event_id"].endswith("BBB:event_found:1")


def test_a_price_unavailable_name_does_not_block_the_next_ticker(w):
    w.closes = [{"date": "2026-12-02", "close": 30.0}]              # no bar near the formation date: both wait
    w.warn("AAA", "news_event")
    w.warn("BBB", "event_found")
    rep = w.run()
    assert [d["ticker"] for d in rep["decided"]] == ["AAA"]
    assert [(x["ticker"], x["reason"]) for x in w.journal("waiting")] == [("BBB", "price_unavailable")]


def test_a_transport_failure_counts_and_the_third_writes_the_flag(w):
    w.warn("AAA", "event_found")
    w.slot_script = {1000: {"outcome": "transport", "detail": "timeout"}}
    assert w.run()["exit"] == 6 and not w.flag.exists()
    assert w.run()["exit"] == 6 and not w.flag.exists()
    rep = w.run()
    assert rep["exit"] == 7 and w.flag.exists() and "3 transport failures" in w.flag.read_text()
    assert [r["attempt"] for r in w.journal("slot_failed")] == [1, 2, 3] and w.journal("decided") == []


def test_a_code_defect_writes_the_flag_at_once_and_the_flag_refuses_the_next_pass(w):
    w.warn("AAA", "event_found")
    w.slot_script = {1000: {"outcome": "defect", "detail": "engine_defect: x"}}
    assert w.run()["exit"] == 7 and w.flag.exists()
    asked = []
    rep = w.run(engine=lambda: asked.append(1) or w.view)
    assert rep["exit"] == 7 and asked == [] and len(w.calls["slot"]) == 1                 # refused before the engine was read


def test_missing_pinned_folders_write_the_flag(w):
    os.remove(w.value / f"closure_{T1}" / "reference_closure.json")
    w.warn("AAA", "event_found")
    assert w.run()["exit"] == 7 and w.flag.exists() and w.calls["slot"] == []


def test_a_consensus_that_raises_is_a_defect(w):
    def boom(*a):
        raise ValueError("x")
    w.warn("AAA", "event_found")
    assert w.run(consensus=boom)["exit"] == 7 and w.flag.exists()


# ---------------------------------------------------------------- 9. a crash between the journal line and the record

def test_a_crash_between_the_journal_line_and_the_record_is_repaired(w):
    eid = w.warn("AAA", "news_event")
    w.run()
    (rec,) = w.exits()
    (w.value / "fv_exits.jsonl").unlink()                           # the record was never written
    w.view["exits"] = []
    w.now = datetime(2026, 12, 8, 15, 0, tzinfo=timezone.utc)       # a later pass
    rep = w.run()
    assert rep["repaired"] == ["AAA"] and w.exits() == [rec] and len(w.journal("decided")) == 1
    assert w.run(engine=lambda: {**w.view, "exits": [(T1, "AAA")]})["repaired"] == []
    assert len(w.exits()) == 1 and eid


def test_never_two_records_for_one_name_under_one_formation(w):
    assert A.append_exit(w.value, {"formation_T": T1, "ticker": "AAA"}) is True
    assert A.append_exit(w.value, {"formation_T": T1, "ticker": "AAA", "reason": "x"}) is False
    assert A.append_exit(w.value, {"formation_T": "2026-12-31", "ticker": "AAA"}) is True


# ---------------------------------------------------------------- 10. dry run, lock, engine

def test_dry_run_writes_nothing_and_runs_no_slot(w):
    w.warn("AAA", "news_event")
    w.warn("BBB", "event_found")
    before = sorted(p.name for p in w.tmp.rglob("*"))
    rep = w.run(dry_run=True)
    assert rep["exit"] == 0 and {x["ticker"]: x["action"] for x in rep["planned"]} == {"AAA": "under_review", "BBB": "revalue"}
    assert sorted(p.name for p in w.tmp.rglob("*")) == before
    assert w.calls == {"build": [], "slot": [], "consensus": [], "prices": []}
    assert "would do" in A.format_pass(rep)


def test_another_pass_holding_the_lock_exits_3(w):
    w.warn("AAA", "news_event")
    (w.root / "state").mkdir(parents=True)
    (w.root / "state" / "fv_actions.lock").write_text(str(os.getpid()))
    rep = w.run()
    assert rep["exit"] == 3 and w.exits() == []
    assert w.run(dry_run=True)["exit"] == 0                          # a dry run takes no lock


def test_the_lock_is_released_after_a_pass(w):
    w.warn("AAA", "news_event")
    w.run()
    assert not (w.root / "state" / "fv_actions.lock").exists()


def test_the_engine_failing_ends_the_pass_with_exit_2_and_nothing_written(w):
    w.warn("AAA", "news_event")

    def stop():
        raise E.Stop("a stored line differs")
    rep = w.run(engine=stop)
    assert rep["exit"] == 2 and "a stored line differs" in rep["notes"][0]
    assert w.exits() == [] and not (w.root / "fv_actions.jsonl").exists() and not (w.root / "state" / "fv_actions.json").exists()


def test_no_fv_decision_yet_holds_nothing(w):
    rep = w.run(engine=lambda: {"T": None, "decision_time_utc": None, "held": [], "cut": None, "lines": {}, "exits": [], "pending_T": None})
    assert rep["exit"] == 0 and rep["notes"] == ["FV holds nothing"]


# ---------------------------------------------------------------- the engine's view, from recomputed lines

def fv_line(T, t, action, cut=1.0, kind="at_fill_open", applied=None):
    line = {"arm": "FV", "kind": kind, "formation_T": T, "ticker": t, "action": action, "value": {"cut": cut}}
    if applied is not None:
        line["exit"] = {"applied": applied}
    return line


def test_view_from_lines(tmp_path):
    L = {"formations": [{"formation_T": "2026-11-30", "decision_time_utc": "2026-11-30T21:00:00Z"},
                        {"formation_T": "2026-12-31", "decision_time_utc": "2026-12-31T21:00:00Z"}],
         "actions": [fv_line("2026-11-30", "OLD", "enter"),
                     fv_line("2026-12-31", "AAA", "enter", cut=0.7), fv_line("2026-12-31", "BBB", "hold", cut=0.7), fv_line("2026-12-31", "CCC", "exit", cut=0.7),
                     fv_line("2026-12-31", "DDD", "enter", cut=0.7), fv_line("2026-12-31", "DDD", "exit", kind="between_formations", applied=True),
                     fv_line("2026-12-31", "EEE", "enter", cut=0.7), fv_line("2026-12-31", "EEE", "exit", kind="between_formations", applied=False)]}
    (tmp_path / "fv_2026-12-31.json").write_text("{}")
    (tmp_path / "fv_2027-01-29.json").write_text("{}")                # a snapshot after the decision in force, not priced
    v = A.view_from_lines(L, tmp_path)
    assert v["T"] == "2026-12-31" and v["decision_time_utc"] == "2026-12-31T21:00:00Z" and v["cut"] == 0.7
    assert v["held"] == ["AAA", "BBB", "EEE"] and set(v["lines"]) == {"AAA", "BBB", "CCC", "DDD", "EEE"} and v["pending_T"] == "2027-01-29"
    assert A.view_from_lines({"formations": [], "actions": []}, tmp_path)["T"] is None


# ---------------------------------------------------------------- the real slot, with the subprocess and the repository faked

def test_the_real_slot_runs_the_valuation_and_classifies_the_result(tmp_path, monkeypatch):
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps({"ticker": "AAA", "decision_time_utc": "2026-12-02T01:00:00Z"}), encoding="utf-8")
    n = {"packet": str(packet), "packet_sha256": "p" * 64}
    monkeypatch.setattr(A.FVAL, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(A.FVAL, "git", lambda *a: "head1")
    seen = []

    def fake(body):
        def run(cmd, **kw):
            seen.append((cmd, kw))
            rd, _ = A.FVAL.run_dir(n, int(cmd[-1]))
            rd.mkdir(parents=True)
            if body is not None:
                (rd / "result.json").write_text(json.dumps(body), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return run
    good = {"status": "ok", "versions": {"git": ["head1"]}, "packet_sha256": "p" * 64, "ticker": "AAA", "seed": 1000, "T": "2026-12-02T01:00:00Z"}
    fields = {"cik": 11, "sector": "Industrials", "family": "operating", "market_cap": 1500.0}
    monkeypatch.setattr(A.subprocess, "run", fake(good))
    r = A.real_slot(n, 1000, fields, "ANCH", "CLOS")
    assert r["outcome"] == "filled" and r["status"] == "ok" and r["git"] == "head1" and r["result_sha256"] and Path(r["result"]).is_file()
    cmd, kw = seen[0]
    assert cmd[1:3] == ["-m", "qwen_c.value.run"] and cmd[cmd.index("--market-cap") + 1] == "1500.0" and cmd[cmd.index("--seed") + 1] == "1000"
    assert kw["env"]["MRI_ANCHORS_DIR"] == "ANCH" and kw["env"]["RS2_REFERENCE_CLOSURE"] == "CLOS" and kw["env"]["PYTHONIOENCODING"] == "utf-8"
    monkeypatch.setattr(A.subprocess, "run", fake({**good, "versions": {"git": ["other"]}}))
    r = A.real_slot(n, 1000, fields, "ANCH", "CLOS")
    assert r["outcome"] == "defect" and len(r["aside"]) >= 1
    monkeypatch.setattr(A.subprocess, "run", fake({**good, "status": "timeout"}))
    assert A.real_slot(n, 1000, fields, "ANCH", "CLOS")["outcome"] == "transport"
    monkeypatch.setattr(A.subprocess, "run", fake(None))
    assert A.real_slot(n, 1000, fields, "ANCH", "CLOS")["outcome"] == "defect"      # a crash: no result.json

"""tests/test_reference_ledger_eval.py - revision 18 brief section 5.2: the frozen evaluation (tools/reference_ledger_eval.py); from revision 19 the
cohort's default revision is 19 (the synthetic ledgers below carry it) and the evaluation adds the call groups (tests/test_reference_ledger_r19.py).

SYNTHETIC data only. The metric functions are the backtest's (registration d09bb4a4 section 7); each is pinned here on a case
worked by hand. The end-to-end cases build a ledger through the real `snapshot` and a prices file, then evaluate it.
"""
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import reference_ledger as rl  # noqa: E402
import reference_ledger_eval as ev  # noqa: E402

CLOSURE = (0.05, "2026-12-20", {})


# ---- the backtest's metrics, by hand ---------------------------------------------------------------------------------

def test_spearman_ties_averaged_and_undefined_cases():
    assert ev.spearman([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
    assert ev.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # ties: x ranks 1.5, 1.5, 3, 4 against y ranks 1..4
    x, y = [1, 1, 2, 3], [1, 2, 3, 4]
    rx, ry = np.array([1.5, 1.5, 3, 4]), np.array([1, 2, 3, 4])
    expect = np.corrcoef(rx, ry)[0, 1]
    assert ev.spearman(x, y) == pytest.approx(expect)
    assert math.isnan(ev.spearman([1, 2], [1, 2]))               # fewer than 3
    assert math.isnan(ev.spearman([1, 1, 1], [1, 2, 3]))         # a constant


def test_apv_median_uses_the_40th_to_60th_percentile_of_returns_inclusive():
    r = [-0.3, -0.2, -0.1, 0.0, 0.02, 0.04, 0.06, 0.2, 0.3, 0.4]
    vp = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
    # the 40th percentile is 0.012 and the 60th 0.048: the names with R 0.02 and 0.04 -> V/P 1.0 and 1.1 -> median 1.05
    assert ev.apv_median(vp, r) == pytest.approx(1.05)
    assert math.isnan(ev.apv_median([], []))


def test_apv_is_the_geometric_mean_of_the_dates_medians_skipping_undefined():
    assert ev.apv([1.0, 4.0]) == pytest.approx(2.0)
    assert ev.apv([2.0, float("nan"), -1.0, 0.0]) == pytest.approx(2.0)
    assert math.isnan(ev.apv([float("nan")]))


def test_call_lift_buy_and_avoid_in_points():
    r = [-0.3, -0.2, -0.1, 0.0, 0.02, 0.04, 0.06, 0.2, 0.3, 0.4]
    vp = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
    # beat SPY (0.05): the last four of ten = 40%; the three buy calls (V/P >= 1.3) all beat it -> +60 points
    lift, n = ev.call_lift(vp, r, 0.05, buy=True)
    assert (round(lift, 9), n) == (60.0, 3)
    # underperform: the first six = 60%; the two avoid calls (V/P <= 0.7) both underperformed -> +40 points
    lift, n = ev.call_lift(vp, r, 0.05, buy=False)
    assert (round(lift, 9), n) == (40.0, 2)
    lift, n = ev.call_lift([1.0, 1.0], [0.1, 0.2], 0.0, buy=True)
    assert math.isnan(lift) and n == 0
    assert ev.call_lift([1.3], [0.0], 0.05, buy=True)[0] == pytest.approx((0.0 - 0.0) * 100)   # 0/1 hit - 0/1 hit = 0


# ---- dates and prices ------------------------------------------------------------------------------------------------

def test_add_months_clamps_the_day_and_crosses_years():
    assert ev.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert ev.add_months(date(2027, 1, 31), 13) == date(2028, 2, 29)
    assert ev.add_months(date(2027, 1, 4), 12) == date(2028, 1, 4)
    assert ev.add_months(date(2027, 11, 30), 36) == date(2030, 11, 30)


import hashlib as _hashlib


def _sha(path):
    return _hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path):
    return ev.load_prices(path, _sha(path))


def test_price_lookup_takes_the_last_observation_within_the_gap(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("date,ticker,close,adj_close,dividends,stock_splits\n2027-01-04,aaa,10,10,0,0\n2027-01-11,AAA,12,12,0,0\n"
                 "2027-01-12,AAA,-1,-1,0,0\n2027-01-13,AAA,x,x,0,0\n", encoding="utf-8")
    s = _load(f)["AAA"]
    assert ev.price_on_or_before(s, date(2027, 1, 4)) == 10.0
    assert ev.price_on_or_before(s, date(2027, 1, 10)) == 10.0          # six days after the last observation
    assert ev.price_on_or_before(s, date(2027, 1, 11)) == 12.0
    assert ev.price_on_or_before(s, date(2027, 1, 18)) == 12.0          # seven days: still inside
    assert ev.price_on_or_before(s, date(2027, 1, 19)) is None          # eight: no price (delisted or a hole)
    assert ev.price_on_or_before(s, date(2027, 1, 3)) is None
    assert ev.price_on_or_before(None, date(2027, 1, 4)) is None
    assert ev.total_return(s, date(2027, 1, 4), date(2027, 1, 11)) == pytest.approx(0.2)
    assert ev.total_return(s, date(2027, 1, 4), date(2027, 3, 1)) is None
    assert s[2] == {date(2027, 1, 4).toordinal(): 10.0, date(2027, 1, 11).toordinal(): 12.0}    # the unadjusted closes


def test_the_prices_file_is_hashed_and_needs_its_columns(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("date,ticker,close,adj_close,dividends,stock_splits\n2027-01-04,AAA,10,10,0,0\n", encoding="utf-8")
    assert "AAA" in ev.load_prices(f, _sha(f).upper())
    with pytest.raises(ValueError) as e:
        ev.load_prices(f, "0" * 64)
    assert "sha256" in str(e.value)
    g = tmp_path / "q.csv"
    g.write_text("date,ticker,close\n2027-01-04,AAA,10\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ev.load_prices(g, _sha(g))


# ---- one cross-section, end to end -----------------------------------------------------------------------------------

D0 = date(2027, 1, 4)
VP = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
RET = [-0.3, -0.2, -0.1, 0.0, 0.02, 0.04, 0.06, 0.2, 0.3, 0.4]
NAMES = [f"ZQ{c}" for c in "ABCDEFGHIJ"]


def _write_prices(path, returns, spy, d0=D0, h=12, extra=(), end_missing=(), start_missing=()):
    d1 = ev.add_months(d0, h)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "close", "adj_close", "dividends", "stock_splits"])
        for t, r in list(returns.items()) + [("SPY", spy)]:
            if t not in start_missing:
                w.writerow([d0.isoformat(), t, 10.0, 100.0, 0, 0])
            if t not in end_missing:
                w.writerow([d1.isoformat(), t, 10.0 * (1.0 + r), 100.0 * (1.0 + r), 0, 0])
        for line in extra:
            w.writerow(line)


def _full_row(t, d0=D0, **kw):
    r = {"date": d0.isoformat(), "ticker": t, "price": 10.0, "price_date": d0.isoformat(), "reference_value": 5.0,
         "reference_status": "used", "vp": 0.5, "coe": 0.09, "closure_erp": 0.05, "closure_asof": "2026-12-20", "revision": 19,
         "verdict": None}
    r.update(kw)
    return r


def _ledger(path, d0=D0, vps=VP, names=NAMES, extra_rows=()):
    rows = [_full_row(t, d0, reference_value=10.0 * v, vp=v) for t, v in zip(names, vps)]
    rows += list(extra_rows)
    rl.append_rows(path, rows)


def test_one_date_matches_the_hand_computed_values(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led)
    _write_prices(px, dict(zip(NAMES, RET)), 0.05)
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    a = res["groups"]["all"]["aggregate"]["excluded"]
    (p,) = res["groups"]["all"]["per_date"]
    x = p["excluded"]
    assert res["snapshot_dates"] == ["2027-01-04"] and res["asof"] == "2028-01-04" and res["report_only"] is True
    assert res["revision"] == 19 and res["other_revisions"] == {}
    assert (x["n"], p["rows"], p["not_valued"], p["no_price_at_start"], p["no_price_at_end"]) == (10, 10, 0, 0, 0)
    assert x["rho"] == pytest.approx(1.0)
    assert x["apv_median"] == pytest.approx(1.05) and a["APV"] == pytest.approx(1.05)
    assert (x["buy_lift"], x["buy_calls"], x["buy_thin"]) == (pytest.approx(60.0), 3, True)
    assert (x["avoid_lift"], x["avoid_calls"]) == (pytest.approx(40.0), 2)
    assert a["rho_mean"] == pytest.approx(1.0) and a["buy_lift_mean"] == pytest.approx(60.0)
    assert a["avoid_lift_mean"] == pytest.approx(40.0) and a["buy_thin_dates"] == 1
    # with every price present, the two bounds are the same as the excluded arm
    for arm in ("low", "high"):
        assert res["groups"]["all"]["aggregate"][arm] == a
    assert (p["price_checked"], p["price_mismatch"]) == (10, 0)


def test_unprinted_references_and_missing_prices_are_counted_not_dropped_silently(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led, extra_rows=[_full_row("ZQK", reference_status="not_meaningful", reference_value=-1.0, vp=-0.1),
                             _full_row("ZQL", reference_status="not_available", reference_value=None, vp=None),
                             _full_row("ZQM"),                               # a printed reference, but no price in the file
                             _full_row("ZQN", reference_status="outside_fence_above", reference_value=90.0, vp=9.0)])
    returns = dict(zip(NAMES, RET))
    returns["ZQN"] = 0.5
    _write_prices(px, returns, 0.05)
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    assert (p["rows"], p["not_valued"], p["no_price_at_start"], p["no_price_at_end"], p["excluded"]["n"]) == (14, 2, 1, 0, 11)


def test_a_name_with_no_price_at_the_end_is_counted_at_minus_100_percent_and_at_zero_excess(tmp_path):
    """The two bounds the pre-registration names: a name that has a price at T and none at T + h (delisted, taken over) is
    neither dropped nor guessed - it is counted once at R = -100% (low) and once at SPY's return (high)."""
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led, extra_rows=[_full_row("ZQX", reference_value=20.0, vp=2.0)])           # the highest V/P of the date
    returns = dict(zip(NAMES, RET))
    returns["ZQX"] = 0.0
    _write_prices(px, returns, 0.05, end_missing=("ZQX",))
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    assert (p["no_price_at_end"], p["excluded"]["n"], p["low"]["n"], p["high"]["n"]) == (1, 10, 11, 11)
    assert p["excluded"]["buy_calls"] == 3 and p["low"]["buy_calls"] == 4 and p["high"]["buy_calls"] == 4
    # low: the lost name's call lost (-100% < SPY): 3 of 4 buy calls beat SPY, 4 of 11 names beat it
    assert p["low"]["buy_lift"] == pytest.approx((3 / 4 - 4 / 11) * 100)
    # high: it earned exactly SPY's return, so it neither beat nor lagged it: 3 of 4 calls beat it, 4 of 11 names
    assert p["high"]["buy_lift"] == pytest.approx((3 / 4 - 4 / 11) * 100)
    # the avoid side (V/P <= 0.7: two calls, both underperformed SPY): the bounds part - low counts the lost name among
    # the 7 of 11 that lagged SPY, high among the 6 of 11 that did not
    assert p["low"]["avoid_lift"] == pytest.approx((1.0 - 7 / 11) * 100) and p["high"]["avoid_lift"] == pytest.approx((1.0 - 6 / 11) * 100)
    assert p["excluded"]["avoid_lift"] == pytest.approx((1.0 - 6 / 10) * 100)
    a = res["groups"]["all"]["aggregate"]
    assert a["names_without_end_price"] == 1 and a["names_valued_at_start"] == 11
    # a name with no price at the START is left out of every arm and counted
    _write_prices(px, returns, 0.05, start_missing=("ZQX",))
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    assert (p["no_price_at_start"], p["no_price_at_end"], p["low"]["n"], p["high"]["n"], p["excluded"]["n"]) == (1, 0, 10, 10, 10)


def test_the_lost_name_moves_the_statistics_the_way_the_bounds_say(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    names = [f"ZQ{i}" for i in range(6)]
    # three high-V/P names (two beat SPY, one is lost) and three low-V/P names
    vps = [1.5, 1.4, 1.35, 0.6, 0.65, 0.7]
    _ledger(led, vps=vps, names=names)
    returns = {"ZQ0": 0.3, "ZQ1": 0.2, "ZQ2": 0.0, "ZQ3": -0.2, "ZQ4": 0.01, "ZQ5": 0.1}
    _write_prices(px, returns, 0.05, end_missing=("ZQ2",))
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    # excluded: 2 buy calls, both beat SPY; of the 5 names with returns 3 beat it -> 100% - 60%
    assert p["excluded"]["buy_calls"] == 2 and p["excluded"]["buy_lift"] == pytest.approx((1.0 - 3 / 5) * 100)
    # low: the lost name lost: 3 buy calls, 2 beat; 3 of 6 names beat -> 66.7% - 50%
    assert p["low"]["buy_calls"] == 3 and p["low"]["buy_lift"] == pytest.approx((2 / 3 - 3 / 6) * 100)
    # high: counted at the return of SPY - neither beat nor lagged it: the same hits on the buy side
    assert p["high"]["buy_lift"] == pytest.approx((2 / 3 - 3 / 6) * 100)
    # avoid calls (V/P <= 0.7): three, two of which lagged SPY; the lost name is a lagger in low, not in high
    assert p["excluded"]["avoid_lift"] == pytest.approx((2 / 3 - 2 / 5) * 100)
    assert p["low"]["avoid_lift"] == pytest.approx((2 / 3 - 3 / 6) * 100) and p["high"]["avoid_lift"] == pytest.approx((2 / 3 - 2 / 6) * 100)


def test_the_cohort_is_the_snapshot_dates_a_full_horizon_before_asof(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    d_late = date(2027, 1, 20)
    _ledger(led)
    _ledger(led, d0=d_late)
    _ledger(led, d0=date(2026, 12, 28))                                     # before acceptance: not counted
    _write_prices(px, dict(zip(NAMES, RET)), 0.05, extra=[])
    s = _load(px)
    rows = rl.read_ledger(led)
    res = ev.evaluate(rows, s, D0, 12)                                       # asof = acceptance + 12 months
    assert res["snapshot_dates"] == ["2027-01-04"]
    res = ev.evaluate(rows, s, D0, 12, asof=date(2028, 1, 20))               # later, the second date is in
    assert res["snapshot_dates"] == ["2027-01-04", "2027-01-20"]
    assert res["groups"]["all"]["aggregate"]["dates"] == 2
    assert res["groups"]["all"]["aggregate"]["dates_without_spy"] == 1       # the file has no price within a week of that date
    res = ev.evaluate(rows, s, D0, 12, asof=date(2027, 6, 1))                # no date has a full horizon behind it
    assert res["snapshot_dates"] == [] and res["groups"]["all"]["aggregate"]["dates"] == 0


def test_the_untouched_split_partitions_the_rows_and_names_no_ticker(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led)
    _write_prices(px, dict(zip(NAMES, RET)), 0.05)
    untouched = set(NAMES[:3])
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12, untouched=untouched)
    n = {g: res["groups"][g]["per_date"][0]["excluded"]["n"] for g in ("all", "untouched", "book")}
    assert n == {"all": 10, "untouched": 3, "book": 7}
    assert "ZQ" not in json.dumps(res)
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    assert list(res["groups"]) == ["all"]


def test_the_status_split_reports_used_and_outside_the_fence_apart(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led, extra_rows=[_full_row("ZQN", reference_status="outside_fence_above", reference_value=90.0, vp=9.0),
                             _full_row("ZQO", reference_status="outside_fence_below", reference_value=1.0, vp=0.1),
                             _full_row("ZQP", reference_status="not_meaningful", reference_value=-1.0, vp=-0.1)])
    returns = dict(zip(NAMES, RET))
    returns.update({"ZQN": 0.5, "ZQO": -0.5, "ZQP": 0.0})
    _write_prices(px, returns, 0.05)
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    split = res["status_split"]["all"]
    assert split["used"]["rows"] == 10 and split["outside_fence"]["rows"] == 2
    assert split["used"]["aggregate"]["excluded"]["rho_mean"] == pytest.approx(1.0)
    # the whole printed cohort is the two together (the not_meaningful name is in neither)
    assert res["groups"]["all"]["per_date"][0]["excluded"]["n"] == 12
    assert split["outside_fence"]["aggregate"]["names_valued_at_start"] == 2
    assert res["definitions"]["status_split"] == {"used": ["used"], "outside_fence": ["outside_fence_above", "outside_fence_below"]}
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12, untouched={"ZQN"})
    assert res["status_split"]["untouched"]["outside_fence"]["aggregate"]["names_valued_at_start"] == 1
    assert res["status_split"]["book"]["outside_fence"]["aggregate"]["names_valued_at_start"] == 1


def test_only_revision_19_rows_are_in_the_cohort_and_the_others_are_reported_apart(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    old = [_full_row(f"ZO{i}", revision=18, reference_value=10.0 * v, vp=v) for i, v in enumerate(VP)]
    _ledger(led, extra_rows=old)
    returns = dict(zip(NAMES, RET))
    returns.update({f"ZO{i}": r for i, r in enumerate(RET)})
    _write_prices(px, returns, 0.05)
    rows = rl.read_ledger(led)
    res = ev.evaluate(rows, _load(px), D0, 12)
    assert res["groups"]["all"]["per_date"][0]["rows"] == 10 and res["revisions"] == {"18": 10, "19": 10}
    assert set(res["other_revisions"]) == {"18"} and "per_date" not in res["other_revisions"]["18"]["groups"]["all"]
    assert res["other_revisions"]["18"]["groups"]["all"]["aggregate"]["dates"] == 1
    res18 = ev.evaluate(rows, _load(px), D0, 12, revision=18)
    assert res18["revision"] == 18 and res18["groups"]["all"]["per_date"][0]["rows"] == 10 and set(res18["other_revisions"]) == {"19"}
    # no row of the asked-for revision: an empty cohort, the others still reported
    res20 = ev.evaluate(rows, _load(px), D0, 12, revision=20)
    assert res20["snapshot_dates"] == [] and set(res20["other_revisions"]) == {"18", "19"}


def test_a_ledger_price_far_from_the_files_unadjusted_close_is_counted_not_dropped(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led, extra_rows=[_full_row("ZQY", price=20.0, reference_value=10.0, vp=0.5)])
    returns = dict(zip(NAMES, RET))
    returns["ZQY"] = 0.0
    _write_prices(px, returns, 0.05)
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    assert (p["price_checked"], p["price_mismatch"], p["excluded"]["n"]) == (11, 1, 11)


def test_horizon_must_be_12_or_36():
    with pytest.raises(ValueError):
        ev.evaluate([], {}, D0, 24)


# ---- a synthetic forward run: snapshots through the ledger, then the frozen script ----------------------------------

def _synthetic(tmp_path, weeks=4, n=60, seed=7, horizon=12):
    """A ledger written by the real `snapshot` for `weeks` weekly dates and a prices file in which returns rise with V/P."""
    rng = np.random.default_rng(seed)
    names = [f"ZR{i:03d}" for i in range(n)]
    vp = {t: float(np.exp(rng.normal(0.0, 0.35))) for t in names}
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    dates = [date.fromordinal(D0.toordinal() + 7 * k) for k in range(weeks)]
    f = dict(inputs_fn=lambda t: {"v": 10.0 * vp[t], "coe": 0.09}, build_fn=lambda **kw: {"value": kw["v"]},
             fence_fn=lambda v, t: None, price_fn=lambda t: (10.0, "2027-01-04"), verdict_fn=lambda t: None)
    for d in dates:
        rl.snapshot(d.isoformat(), names[:40], set(names[40:]), ledger_path=led, closure=CLOSURE, revision=19, **f)
    with open(px, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "ticker", "close", "adj_close", "dividends", "stock_splits"])
        for d in dates:
            d1 = ev.add_months(d, horizon)
            for t in names + ["SPY"]:
                r = 0.05 if t == "SPY" else 0.10 * math.log(vp[t]) + float(rng.normal(0.0, 0.02))
                w.writerow([d.isoformat(), t, 10.0, 100.0, 0, 0])
                w.writerow([d1.isoformat(), t, 10.0 * (1.0 + r), 100.0 * (1.0 + r), 0, 0])
    lst = tmp_path / "ut.txt"
    lst.write_text("\n".join(names[40:]) + "\n", encoding="utf-8")
    return led, px, lst, dates, names


def test_the_frozen_script_runs_end_to_end_on_a_synthetic_ledger(tmp_path, capsys):
    led, px, lst, dates, names = _synthetic(tmp_path)
    out = tmp_path / "result.json"
    asof = ev.add_months(dates[-1], 12)
    rc = ev.main(["--ledger", str(led), "--prices", str(px), "--prices-sha256", _sha(px), "--acceptance-date", D0.isoformat(),
                  "--horizon", "12", "--asof", asof.isoformat(), "--untouched-list", str(lst), "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    res = json.loads(out.read_text(encoding="utf-8"))
    assert json.loads(printed) == res
    assert not any(t in printed for t in names)                    # aggregates only: no ticker anywhere
    assert res["snapshot_dates"] == [d.isoformat() for d in dates]
    assert set(res["groups"]) == {"all", "book", "untouched"} and set(res["status_split"]) == {"all", "book", "untouched"}
    allg = res["groups"]["all"]["aggregate"]
    assert allg["dates"] == 4 and allg["excluded"]["rho_mean"] > 0.5            # the planted relationship is found
    assert res["groups"]["book"]["per_date"][0]["excluded"]["n"] == 40 and res["groups"]["untouched"]["per_date"][0]["excluded"]["n"] == 20
    assert len(res["inputs"]["ledger_sha256"]) == 64 and res["inputs"]["prices_sha256"] == _sha(px) and res["revisions"] == {"19": 240}
    assert res["definitions"]["buy"] == 1.3 and res["definitions"]["avoid"] == 0.7


def test_the_script_refuses_a_prices_file_whose_hash_differs(tmp_path, capsys):
    led, px, lst, dates, names = _synthetic(tmp_path, weeks=1)
    rc = ev.main(["--ledger", str(led), "--prices", str(px), "--prices-sha256", "0" * 64, "--acceptance-date", D0.isoformat(),
                  "--horizon", "12"])
    assert rc == 2 and "sha256" in capsys.readouterr().err
    with pytest.raises(SystemExit):                                  # the hash is required
        ev.main(["--ledger", str(led), "--prices", str(px), "--acceptance-date", D0.isoformat(), "--horizon", "12"])


def test_the_script_computes_once_per_output_and_refuses_a_bad_ledger(tmp_path, capsys):
    led, px, lst, dates, names = _synthetic(tmp_path, weeks=1)
    out = tmp_path / "result.json"
    args = ["--ledger", str(led), "--prices", str(px), "--prices-sha256", _sha(px), "--acceptance-date", D0.isoformat(),
            "--horizon", "12", "--out", str(out)]
    assert ev.main(args) == 0
    first = out.read_bytes()
    assert ev.main(args) == 2 and out.read_bytes() == first          # never overwritten
    assert "already exists" in capsys.readouterr().err
    with open(led, "ab") as f:
        f.write(b'{"date":"2027-02-01"}\n')
    assert ev.main(args[:-2]) == 2                                   # a ledger line with another schema
    assert "schema mismatch" in capsys.readouterr().err


def test_an_empty_cohort_reports_it_and_exits_3(tmp_path, capsys):
    led, px, lst, dates, names = _synthetic(tmp_path, weeks=1)
    rc = ev.main(["--ledger", str(led), "--prices", str(px), "--prices-sha256", _sha(px), "--acceptance-date", D0.isoformat(),
                  "--horizon", "12", "--asof", "2027-06-01"])
    assert rc == 3
    assert json.loads(capsys.readouterr().out)["snapshot_dates"] == []


# ---- the price check and splits (revision 18 follow-up, finding 8) -------------------------------------------------------------------
# yfinance's Close is adjusted for splits as of the day it was fetched; the ledger's price is the quote of its own day. The check
# multiplies the file's close by the splits dated after the price's date, so a later split is not counted as a mismatch.

def _split_case(tmp_path, cases):
    """cases: {name: (file_close_on_d0, ledger_price, [(days_after_d0, ratio), ...])}; the base ten names are in the ledger too."""
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    from datetime import timedelta
    extra_rows, extra_px = [], []
    for t, (close, price, splits) in cases.items():
        extra_rows.append(_full_row(t, price=price, reference_value=price * 0.5, vp=0.5))
        extra_px.append([D0.isoformat(), t, close, 100.0, 0, 0])
        for days, ratio in splits:                                  # the split's row, dated `days` from the price date
            extra_px.append([(D0 + timedelta(days=days)).isoformat(), t, close, 100.0, 0, ratio])
    _ledger(led, extra_rows=extra_rows)
    _write_prices(px, dict(zip(NAMES, RET)), 0.05, extra=extra_px)
    res = ev.evaluate(rl.read_ledger(led), _load(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    return p


def test_a_split_after_the_price_date_is_not_counted_as_a_price_mismatch(tmp_path):
    p = _split_case(tmp_path, {
        "ZQ1": (2.5, 10.0, [(30, 4.0)]),                 # a 4-for-1 later: the file's close is a quarter of the quoted price
        "ZQ2": (100.0, 10.0, [(30, 0.1)]),               # a 1-for-10 reverse split later
        "ZQ3": (10.0 / 6.0, 10.0, [(30, 2.0), (60, 3.0)]),   # two splits: the factors multiply
    })
    assert (p["price_checked"], p["price_mismatch"]) == (13, 0)


def test_only_the_splits_after_the_price_date_adjust_it_and_a_real_mismatch_is_still_counted(tmp_path):
    p = _split_case(tmp_path, {
        "ZQ4": (10.0, 10.0, [(-10, 4.0)]),               # the split was BEFORE the price date: the file's close is already in the price's terms
        "ZQ5": (10.0, 10.0, [(0, 4.0)]),                 # the split's ex-date is the price date: that day's quote is post-split
        "ZQ6": (10.0, 10.0, [(30, 4.0)]),                # a later 4-for-1 and a close that does NOT match: 10 against 10 x 4 -> mismatch
        "ZQ7": (2.5, 10.4, [(30, 4.0)]),                 # 4% off after adjusting: mismatch
        "ZQ8": (2.5, 10.1, [(30, 4.0)]),                 # 1% off after adjusting: inside the check
    })
    assert (p["price_checked"], p["price_mismatch"]) == (15, 2)


def test_a_zero_or_empty_stock_splits_cell_is_no_split_and_the_column_is_required(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("date,ticker,close,adj_close,dividends,stock_splits\n2027-01-04,AAA,10,10,0,0\n2027-01-05,AAA,10,10,0,\n"
                 "2027-01-06,AAA,10,10,0,x\n2027-01-07,AAA,10,10,0,2.0\n", encoding="utf-8")
    s = _load(f)["AAA"]
    assert s[3] == {date(2027, 1, 7).toordinal(): 2.0}
    assert ev.split_factor_after(s, date(2027, 1, 6)) == 2.0 and ev.split_factor_after(s, date(2027, 1, 7)) == 1.0
    assert ev.split_factor_after(s, date(2027, 1, 4)) == 2.0
    g = tmp_path / "q.csv"
    g.write_text("date,ticker,close,adj_close,dividends\n2027-01-04,AAA,10,10,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stock_splits"):
        ev.load_prices(g, _sha(g))

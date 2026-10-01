"""tests/test_reference_ledger_eval.py - revision 18 brief section 5.2: the frozen evaluation (tools/reference_ledger_eval.py).

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


def test_price_lookup_takes_the_last_observation_within_the_gap(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("date,ticker,adj_close\n2027-01-04,aaa,10\n2027-01-11,AAA,12\n2027-01-12,AAA,-1\n2027-01-13,AAA,x\n",
                 encoding="utf-8")
    s = ev.load_prices(f)["AAA"]
    assert ev.price_on_or_before(s, date(2027, 1, 4)) == 10.0
    assert ev.price_on_or_before(s, date(2027, 1, 10)) == 10.0          # six days after the last observation
    assert ev.price_on_or_before(s, date(2027, 1, 11)) == 12.0
    assert ev.price_on_or_before(s, date(2027, 1, 18)) == 12.0          # seven days: still inside
    assert ev.price_on_or_before(s, date(2027, 1, 19)) is None          # eight: no price (delisted or a hole)
    assert ev.price_on_or_before(s, date(2027, 1, 3)) is None
    assert ev.price_on_or_before(None, date(2027, 1, 4)) is None
    assert ev.total_return(s, date(2027, 1, 4), date(2027, 1, 11)) == pytest.approx(0.2)
    assert ev.total_return(s, date(2027, 1, 4), date(2027, 3, 1)) is None


# ---- one cross-section, end to end -----------------------------------------------------------------------------------

D0 = date(2027, 1, 4)
VP = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
RET = [-0.3, -0.2, -0.1, 0.0, 0.02, 0.04, 0.06, 0.2, 0.3, 0.4]
NAMES = [f"ZQ{c}" for c in "ABCDEFGHIJ"]


def _write_prices(path, returns, spy, d0=D0, h=12, extra=()):
    d1 = ev.add_months(d0, h)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "adj_close"])
        for t, r in list(returns.items()) + [("SPY", spy)]:
            w.writerow([d0.isoformat(), t, 100.0])
            w.writerow([d1.isoformat(), t, 100.0 * (1.0 + r)])
        for line in extra:
            w.writerow(line)


def _ledger(path, d0=D0, vps=VP, names=NAMES, extra_rows=()):
    rows = []
    for t, v in zip(names, vps):
        rows.append({"date": d0.isoformat(), "ticker": t, "price": 10.0, "reference_value": 10.0 * v,
                     "reference_status": "used", "vp": v, "coe": 0.09, "closure_erp": 0.05, "closure_asof": "2026-12-20",
                     "revision": 18, "verdict": None})
    rows += list(extra_rows)
    rl.append_rows(path, rows)


def test_one_date_matches_the_hand_computed_values(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    _ledger(led)
    _write_prices(px, dict(zip(NAMES, RET)), 0.05)
    res = ev.evaluate(rl.read_ledger(led), ev.load_prices(px), D0, 12)
    a = res["groups"]["all"]["aggregate"]
    (p,) = res["groups"]["all"]["per_date"]
    assert res["snapshot_dates"] == ["2027-01-04"] and res["asof"] == "2028-01-04" and res["report_only"] is True
    assert (p["n"], p["rows"], p["not_valued"], p["no_price"]) == (10, 10, 0, 0)
    assert p["rho"] == pytest.approx(1.0)
    assert p["apv_median"] == pytest.approx(1.05) and a["APV"] == pytest.approx(1.05)
    assert (p["buy_lift"], p["buy_calls"], p["buy_thin"]) == (pytest.approx(60.0), 3, True)
    assert (p["avoid_lift"], p["avoid_calls"]) == (pytest.approx(40.0), 2)
    assert a["rho_mean"] == pytest.approx(1.0) and a["buy_lift_mean"] == pytest.approx(60.0)
    assert a["avoid_lift_mean"] == pytest.approx(40.0) and a["buy_thin_dates"] == 1


def test_unprinted_references_and_missing_prices_are_counted_not_dropped_silently(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"

    def extra(t, **kw):
        r = {"date": D0.isoformat(), "ticker": t, "price": 10.0, "reference_value": 5.0, "reference_status": "used", "vp": 0.5,
             "coe": 0.09, "closure_erp": 0.05, "closure_asof": "2026-12-20", "revision": 18, "verdict": None}
        r.update(kw)
        return r
    _ledger(led, extra_rows=[extra("ZQK", reference_status="not_meaningful", reference_value=-1.0, vp=-0.1),
                             extra("ZQL", reference_status="not_available", reference_value=None, vp=None),
                             extra("ZQM"),                                   # a printed reference, but no price in the file
                             extra("ZQN", reference_status="outside_fence_above", reference_value=90.0, vp=9.0)])
    returns = dict(zip(NAMES, RET))
    returns["ZQN"] = 0.5
    _write_prices(px, returns, 0.05)
    res = ev.evaluate(rl.read_ledger(led), ev.load_prices(px), D0, 12)
    (p,) = res["groups"]["all"]["per_date"]
    assert (p["rows"], p["not_valued"], p["no_price"], p["n"]) == (14, 2, 1, 11)    # the outside-fence name counts as printed


def test_the_cohort_is_the_snapshot_dates_a_full_horizon_before_asof(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    d_late = date(2027, 1, 20)
    _ledger(led)
    _ledger(led, d0=d_late)
    _ledger(led, d0=date(2026, 12, 28))                                     # before acceptance: not counted
    _write_prices(px, dict(zip(NAMES, RET)), 0.05, extra=[])
    s = ev.load_prices(px)
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
    res = ev.evaluate(rl.read_ledger(led), ev.load_prices(px), D0, 12, untouched=untouched)
    n = {g: res["groups"][g]["per_date"][0]["n"] for g in ("all", "untouched", "book")}
    assert n == {"all": 10, "untouched": 3, "book": 7}
    assert "ZQ" not in json.dumps(res)
    res = ev.evaluate(rl.read_ledger(led), ev.load_prices(px), D0, 12)
    assert list(res["groups"]) == ["all"]


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
             fence_fn=lambda v, t: None, price_fn=lambda t: 10.0, verdict_fn=lambda t: None)
    for d in dates:
        rl.snapshot(d.isoformat(), names[:40], set(names[40:]), ledger_path=led, closure=CLOSURE, revision=18, **f)
    with open(px, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "ticker", "adj_close"])
        for d in dates:
            d1 = ev.add_months(d, horizon)
            for t in names + ["SPY"]:
                r = 0.05 if t == "SPY" else 0.10 * math.log(vp[t]) + float(rng.normal(0.0, 0.02))
                w.writerow([d.isoformat(), t, 100.0])
                w.writerow([d1.isoformat(), t, 100.0 * (1.0 + r)])
    lst = tmp_path / "ut.txt"
    lst.write_text("\n".join(names[40:]) + "\n", encoding="utf-8")
    return led, px, lst, dates, names


def test_the_frozen_script_runs_end_to_end_on_a_synthetic_ledger(tmp_path, capsys):
    led, px, lst, dates, names = _synthetic(tmp_path)
    out = tmp_path / "result.json"
    asof = ev.add_months(dates[-1], 12)
    rc = ev.main(["--ledger", str(led), "--prices", str(px), "--acceptance-date", D0.isoformat(), "--horizon", "12",
                  "--asof", asof.isoformat(), "--untouched-list", str(lst), "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    res = json.loads(out.read_text(encoding="utf-8"))
    assert json.loads(printed) == res
    assert not any(t in printed for t in names)                    # aggregates only: no ticker anywhere
    assert res["snapshot_dates"] == [d.isoformat() for d in dates]
    assert set(res["groups"]) == {"all", "book", "untouched"}
    allg = res["groups"]["all"]["aggregate"]
    assert allg["dates"] == 4 and allg["rho_mean"] > 0.5            # the planted relationship is found
    assert res["groups"]["book"]["per_date"][0]["n"] == 40 and res["groups"]["untouched"]["per_date"][0]["n"] == 20
    assert len(res["inputs"]["ledger_sha256"]) == 64 and res["revisions"] == {"18": 240}
    assert res["definitions"]["buy"] == 1.3 and res["definitions"]["avoid"] == 0.7


def test_the_script_computes_once_per_output_and_refuses_a_bad_ledger(tmp_path, capsys):
    led, px, lst, dates, names = _synthetic(tmp_path, weeks=1)
    out = tmp_path / "result.json"
    args = ["--ledger", str(led), "--prices", str(px), "--acceptance-date", D0.isoformat(), "--horizon", "12",
            "--out", str(out)]
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
    rc = ev.main(["--ledger", str(led), "--prices", str(px), "--acceptance-date", D0.isoformat(), "--horizon", "12",
                  "--asof", "2027-06-01"])
    assert rc == 3
    assert json.loads(capsys.readouterr().out)["snapshot_dates"] == []

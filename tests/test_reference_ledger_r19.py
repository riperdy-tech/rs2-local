"""tests/test_reference_ledger_r19.py - revision 19, brief Part E (records): the forward ledger's verdict carries the crux, and the frozen evaluation
adds the four call groups.

  E1  VERDICT_KEYS gains direction_m, crux_valid, crux_inputs and actionable_reasons; validate_row types each; the production verdict_fn copies them from
      the overlay row (+inf written "unlimited");
  E2  tools/reference_ledger_eval.py reports, for crux calls, the calls the rule demoted, crux calls at default against with a departure, and crux calls
      the gate limited against inside both: count, mean excess total return against SPY and hit rate, in the three arms, with hand-computed figures.
SYNTHETIC data only. The overlay-arrival test of the verdict's own fields is in tools/audit_202608/tests/test_rev19_verdict.py.
"""
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import reference_ledger as rl  # noqa: E402
import reference_ledger_eval as ev  # noqa: E402

D0 = date(2027, 1, 4)
CRUX_COE = {"input": "coe", "own": 0.0735, "implied": 0.098, "at_default": False}


def _verdict(**over):
    v = {"label": "undervalued", "base_iv": 13.0, "published_at": "2027-01-01", "pack_revision": 19, "direction_m": "undervalued", "crux_valid": True,
         "crux_inputs": [dict(CRUX_COE)], "actionable_reasons": []}
    v.update(over)
    return v


def _row(t="AAA", **over):
    r = {"date": D0.isoformat(), "ticker": t, "price": 10.0, "price_date": D0.isoformat(), "reference_value": 12.0, "reference_status": "used", "vp": 1.2,
         "coe": 0.09, "closure_erp": 0.05, "closure_asof": "2026-12-20", "revision": 19, "verdict": _verdict()}
    r.update(over)
    return r


# ---- E1: the schema -------------------------------------------------------------------------------------------------------------------

def test_the_verdict_keys_are_the_four_old_and_the_four_new_in_order():
    assert rl.VERDICT_KEYS == ("label", "base_iv", "published_at", "pack_revision", "direction_m", "crux_valid", "crux_inputs", "actionable_reasons")
    assert rl.CRUX_INPUT_KEYS == ("input", "own", "implied", "at_default")


def test_a_row_with_every_new_key_is_accepted_and_each_may_be_null():
    rl.validate_row(_row())
    rl.validate_row(_row(verdict=_verdict(direction_m=None, crux_valid=None, crux_inputs=None, actionable_reasons=None)))
    rl.validate_row(_row(verdict=_verdict(crux_valid=False, crux_inputs=[], actionable_reasons=["outside_street_fence", "mos_beyond_150pct"])))
    rl.validate_row(_row(verdict=_verdict(crux_inputs=[dict(CRUX_COE, own="unlimited", implied=None, at_default=None),
                                                       {"input": "terminal_ronic", "own": 0.12, "implied": "unlimited", "at_default": True}])))
    rl.validate_row(_row(verdict=None))


@pytest.mark.parametrize("over", [
    dict(direction_m=3), dict(direction_m=["undervalued"]), dict(crux_valid="yes"), dict(crux_valid=1), dict(crux_valid=0),
    dict(crux_inputs="coe"), dict(crux_inputs={"input": "coe"}), dict(crux_inputs=["coe"]),
    dict(crux_inputs=[{"input": "coe", "own": 0.07, "implied": 0.09}]),                                       # a key missing
    dict(crux_inputs=[dict(CRUX_COE, extra=1)]),                                                                # a key too many
    dict(crux_inputs=[dict(CRUX_COE, input=5)]), dict(crux_inputs=[dict(CRUX_COE, own="0.07")]), dict(crux_inputs=[dict(CRUX_COE, own=float("nan"))]),
    dict(crux_inputs=[dict(CRUX_COE, implied=float("inf"))]), dict(crux_inputs=[dict(CRUX_COE, implied=True)]),
    dict(crux_inputs=[dict(CRUX_COE, at_default="no")]), dict(crux_inputs=[dict(CRUX_COE, at_default=1)]),
    dict(actionable_reasons="outside_street_fence"), dict(actionable_reasons=[1]), dict(actionable_reasons=[None]), dict(actionable_reasons={"a": 1}),
])
def test_each_new_key_is_typed(over):
    with pytest.raises(rl.LedgerSchemaError):
        rl.validate_row(_row(verdict=_verdict(**over)))


def test_a_verdict_missing_a_new_key_or_with_an_unknown_one_is_refused():
    for k in ("direction_m", "crux_valid", "crux_inputs", "actionable_reasons"):
        v = _verdict()
        v.pop(k)
        with pytest.raises(rl.LedgerSchemaError):
            rl.validate_row(_row(verdict=v))
    with pytest.raises(rl.LedgerSchemaError):
        rl.validate_row(_row(verdict=_verdict(crux="coe")))


def test_a_row_round_trips_through_the_ledger_file(tmp_path):
    led = tmp_path / "l.jsonl"
    rows = [_row("AAA"), _row("BBB", verdict=_verdict(crux_inputs=[{"input": "terminal_ronic", "own": "unlimited", "implied": 0.3, "at_default": False}]))]
    rl.append_rows(led, rows)
    assert rl.read_ledger(led) == rows
    # an infinite crux value never reaches a line: the file is strict JSON
    with pytest.raises(rl.LedgerSchemaError):
        rl.validate_row(_row(verdict=_verdict(crux_inputs=[dict(CRUX_COE, own=math.inf)])))


def test_the_production_verdict_copies_the_new_fields_from_the_overlay_row(tmp_path, monkeypatch):
    import capability_test  # noqa: F401  (production_adapters imports the pack modules)
    import depth_membership
    monkeypatch.setattr(depth_membership, "_current_book", lambda factor_path=None: ["TST"])
    (tmp_path / "cache").mkdir()
    overlay_row = {"ticker": "TST", "direction": "undervalued", "date": "2027-01-01", "pack_revision": 19, "direction_m": "undervalued", "crux_valid": True,
                   "scorecard": {"base_iv": 13.0}, "actionable_reasons": ["mos_beyond_150pct"],
                   "crux": [{"input": "coe", "own": 0.0735, "implied": 0.098, "at_default": False, "reason": "the model's text, not copied"},
                            {"input": "terminal_ronic", "own": math.inf, "implied": 0.3, "at_default": False, "reason": "r"}]}
    (tmp_path / "cache" / "depth_overlay.json").write_text(json.dumps({"tickers": {"TST": overlay_row}}), encoding="utf-8")
    verdict_fn = rl.production_adapters(tmp_path, today=date(2027, 1, 4))["verdict_fn"]
    v = verdict_fn("TST")
    assert v == {"label": "undervalued", "base_iv": 13.0, "published_at": "2027-01-01", "pack_revision": 19, "direction_m": "undervalued", "crux_valid": True,
                 "crux_inputs": [{"input": "coe", "own": 0.0735, "implied": 0.098, "at_default": False},
                                 {"input": "terminal_ronic", "own": "unlimited", "implied": 0.3, "at_default": False}],
                 "actionable_reasons": ["mos_beyond_150pct"]}
    rl.validate_row(_row(verdict=v))
    assert verdict_fn("NOPE") is None
    # a row from before revision 19 has none of them: present and None
    overlay_row.pop("crux"), overlay_row.pop("direction_m"), overlay_row.pop("crux_valid"), overlay_row.pop("actionable_reasons")
    older = tmp_path / "older"                                  # a new folder: the suite's json loads are cached by path
    (older / "cache").mkdir(parents=True)
    (older / "cache" / "depth_overlay.json").write_text(json.dumps({"tickers": {"TST": overlay_row}}), encoding="utf-8")
    old = rl.production_adapters(older, today=date(2027, 1, 4))["verdict_fn"]("TST")
    assert old["direction_m"] is None and old["crux_valid"] is None and old["crux_inputs"] is None and old["actionable_reasons"] is None
    rl.validate_row(_row(verdict=old))


# ---- E2: the evaluation -----------------------------------------------------------------------------------------------------------------

# Twelve calls on one snapshot date, ten in the cohort with prices at both ends, plus one with no price at the end and one with none at the start.
# SPY returns 5%. Each name's total return R, then its excess E = R - 0.05:
#   A1 undervalued, crux at default, inside both    R +0.25 -> E +0.20 (hit)
#   A2 undervalued, crux with a departure, inside   R +0.10 -> E +0.05 (hit)
#   A3 undervalued, crux with a departure, limited  R -0.15 -> E -0.20 (miss)
#   A4 overvalued, crux with a departure, limited   R -0.05 -> E -0.10 (hit)
#   A5 overvalued, at default, inside both          R +0.15 -> E +0.10 (miss)
#   D1 demoted undervalued (direction_m, label hold, no valid crux)   R +0.35 -> E +0.30 (hit)
#   D2 demoted overvalued                                              R +0.05 -> E 0.00 (zero excess: not a hit)
#   D3 demoted undervalued                                             R -0.25 -> E -0.30 (miss)
#   H1 a plain hold                    (in no group)
#   O1 a revision-18 undervalued call  (older revision: in no group)
#   L1 undervalued crux call with no price at the end: low arm R = -100% (E = -1.05, miss), high arm E = 0 (no hit)
#   N1 undervalued crux call with no price at the start: counted, left out
CASES = {
    "A1": (0.25, dict(verdict=_verdict(crux_inputs=[dict(CRUX_COE, at_default=True)], actionable_reasons=[]))),
    "A2": (0.10, dict(verdict=_verdict(crux_inputs=[dict(CRUX_COE, at_default=False)], actionable_reasons=["kelly_on_overvalued"]))),
    "A3": (-0.15, dict(verdict=_verdict(crux_inputs=[dict(CRUX_COE, at_default=False), dict(CRUX_COE, input="fade_years", at_default=True)],
                                        actionable_reasons=["outside_street_fence"]))),
    "A4": (-0.05, dict(verdict=_verdict(label="overvalued", direction_m="overvalued", crux_inputs=[dict(CRUX_COE, at_default=False)],
                                        actionable_reasons=["high_dispersion", "mos_beyond_150pct"]))),
    "A5": (0.15, dict(verdict=_verdict(label="overvalued", direction_m="overvalued", crux_inputs=[dict(CRUX_COE, at_default=True)], actionable_reasons=[]))),
    "D1": (0.35, dict(verdict=_verdict(label="hold", direction_m="undervalued", crux_valid=False, crux_inputs=[], actionable_reasons=["x"]))),
    "D2": (0.05, dict(verdict=_verdict(label="hold", direction_m="overvalued", crux_valid=False, crux_inputs=None, actionable_reasons=None))),
    "D3": (-0.25, dict(verdict=_verdict(label="hold", direction_m="undervalued", crux_valid=None, crux_inputs=None, actionable_reasons=None))),
    "H1": (0.01, dict(verdict=_verdict(label="hold", direction_m="hold", crux_valid=True))),
    "O1": (0.40, dict(verdict=_verdict(pack_revision=18, direction_m=None, crux_valid=None, crux_inputs=None, actionable_reasons=None))),
    "L1": (None, dict(verdict=_verdict(crux_inputs=[dict(CRUX_COE, at_default=False)], actionable_reasons=[]))),
    "N1": ("no start", dict(verdict=_verdict(crux_inputs=[dict(CRUX_COE, at_default=False)], actionable_reasons=[]))),
}


def _prices(path):
    d1 = ev.add_months(D0, 12)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "close", "adj_close", "dividends", "stock_splits"])
        w.writerow([D0.isoformat(), "SPY", 100.0, 100.0, 0, 0])
        w.writerow([d1.isoformat(), "SPY", 105.0, 105.0, 0, 0])
        for t, (r, _kw) in CASES.items():
            if r == "no start":
                w.writerow([d1.isoformat(), t, 10.0, 10.0, 0, 0])
                continue
            w.writerow([D0.isoformat(), t, 10.0, 100.0, 0, 0])
            if r is not None:
                w.writerow([d1.isoformat(), t, 10.0 * (1.0 + r), 100.0 * (1.0 + r), 0, 0])


def _cohort(tmp_path):
    led, px = tmp_path / "l.jsonl", tmp_path / "p.csv"
    rl.append_rows(led, [_row(t, **kw) for t, (_r, kw) in CASES.items()])
    _prices(px)
    import hashlib
    sha = hashlib.sha256(px.read_bytes()).hexdigest()
    return rl.read_ledger(led), ev.load_prices(px, sha), led, px, sha


def _approx(x):
    return pytest.approx(x, abs=1e-9)


def test_the_call_groups_match_the_hand_computed_figures(tmp_path):
    rows, prices, *_ = _cohort(tmp_path)
    res = ev.evaluate(rows, prices, D0, 12)
    cg = res["groups"]["all"]["call_groups"]
    assert list(cg) == list(ev.CALL_GROUPS) and res["revision"] == 19
    # 1. crux calls: A1..A5, L1, N1 (the label is directional)
    g = cg["crux_calls"]
    assert (g["calls"], g["no_price_at_start"], g["no_price_at_end"], g["no_spy_return"]) == (7, 1, 1, 0)
    assert g["excluded"] == {"count": 5, "mean_excess": _approx((0.20 + 0.05 - 0.20 - 0.10 + 0.10) / 5), "hit_rate": _approx(3 / 5)}   # A1, A2, A4 hit
    assert g["low"]["count"] == 6 and g["low"]["mean_excess"] == _approx((0.20 + 0.05 - 0.20 - 0.10 + 0.10 - 1.05) / 6)          # L1 at -100%: E = -1.05
    assert g["low"]["hit_rate"] == _approx(3 / 6)
    assert g["high"]["count"] == 6 and g["high"]["mean_excess"] == _approx((0.20 + 0.05 - 0.20 - 0.10 + 0.10 + 0.0) / 6) and g["high"]["hit_rate"] == _approx(3 / 6)
    # 2. the calls the rule demoted: D1 (hit), D2 (zero excess, no hit), D3 (miss); the call is direction_m
    g = cg["calls_the_rule_demoted"]
    assert g["calls"] == 3 and g["excluded"] == {"count": 3, "mean_excess": _approx((0.30 + 0.0 - 0.30) / 3), "hit_rate": _approx(1 / 3)}
    # 3. at default (A1, A5) against with a departure (A2, A3, A4, L1, N1)
    g = cg["crux_calls_at_default"]
    assert g["calls"] == 2 and g["excluded"] == {"count": 2, "mean_excess": _approx((0.20 + 0.10) / 2), "hit_rate": _approx(1 / 2)}
    g = cg["crux_calls_with_a_departure"]
    assert g["calls"] == 5 and g["excluded"]["count"] == 3 and g["excluded"]["mean_excess"] == _approx((0.05 - 0.20 - 0.10) / 3) and g["excluded"]["hit_rate"] == _approx(2 / 3)
    # 4. limited by the fence or the 150% cap (A3, A4) against inside both (A1, A2, A5, L1, N1)
    g = cg["crux_calls_gate_limited"]
    assert g["calls"] == 2 and g["excluded"] == {"count": 2, "mean_excess": _approx((-0.20 - 0.10) / 2), "hit_rate": _approx(1 / 2)}
    g = cg["crux_calls_inside_both"]
    assert g["calls"] == 5 and g["excluded"]["count"] == 3 and g["excluded"]["mean_excess"] == _approx((0.20 + 0.05 + 0.10) / 3) and g["excluded"]["hit_rate"] == _approx(2 / 3)
    assert g["no_price_at_end"] == 1 and g["no_price_at_start"] == 1


def test_a_row_of_another_revision_a_hold_and_an_unclassifiable_call_are_in_no_group(tmp_path):
    rows, prices, *_ = _cohort(tmp_path)
    members = ev._call_group_members(rows)
    names = {g: sorted(r["ticker"] for r, _c in members[g]) for g in ev.CALL_GROUPS}
    assert names["crux_calls"] == ["A1", "A2", "A3", "A4", "A5", "L1", "N1"]
    assert names["calls_the_rule_demoted"] == ["D1", "D2", "D3"]
    assert names["crux_calls_at_default"] == ["A1", "A5"] and names["crux_calls_with_a_departure"] == ["A2", "A3", "A4", "L1", "N1"]
    assert names["crux_calls_gate_limited"] == ["A3", "A4"] and names["crux_calls_inside_both"] == ["A1", "A2", "A5", "L1", "N1"]
    in_any = {t for v in names.values() for t in v}
    assert "H1" not in in_any and "O1" not in in_any
    # a call with no gate reasons on record (None) is in neither gate group; a crux call with no crux_inputs is in neither default group
    odd = [_row("Z1", verdict=_verdict(actionable_reasons=None, crux_inputs=None))]
    m = ev._call_group_members(odd)
    assert [r["ticker"] for r, _c in m["crux_calls"]] == ["Z1"] and not m["crux_calls_gate_limited"] and not m["crux_calls_inside_both"]
    assert not m["crux_calls_at_default"] and not m["crux_calls_with_a_departure"]
    # a call whose revision is 19 but whose verdict is missing or malformed is skipped
    assert not any(ev._call_group_members([_row("Z2", verdict=None), _row("Z3", verdict=_verdict(pack_revision=None)), _row("Z4", verdict=_verdict(pack_revision=True))]).values())


def test_a_demoted_call_with_a_valid_crux_is_not_demoted(tmp_path):
    """hold with direction_m directional and crux_valid True is a call the band or the fence held for another reason: not the rule's."""
    m = ev._call_group_members([_row("Y1", verdict=_verdict(label="hold", direction_m="undervalued", crux_valid=True))])
    assert not m["calls_the_rule_demoted"] and not m["crux_calls"]


def test_the_script_reports_the_groups_without_a_ticker_and_the_definitions_name_them(tmp_path, capsys):
    rows, prices, led, px, sha = _cohort(tmp_path)
    out = tmp_path / "result.json"
    asof = ev.add_months(D0, 12)
    rc = ev.main(["--ledger", str(led), "--prices", str(px), "--prices-sha256", sha, "--acceptance-date", D0.isoformat(), "--horizon", "12",
                  "--asof", asof.isoformat(), "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    res = json.loads(out.read_text(encoding="utf-8"))
    assert json.loads(printed) == res and not any(t in printed for t in CASES)
    assert res["revision"] == 19 and res["revisions"] == {"19": 12}
    assert set(res["groups"]["all"]["call_groups"]) == set(ev.CALL_GROUPS)
    assert res["definitions"]["call_groups"]["groups"] == list(ev.CALL_GROUPS)
    assert res["definitions"]["call_groups"]["gate_limiting_reasons"] == ["outside_street_fence", "mos_beyond_150pct"]
    assert res["other_revisions"] == {}                                                                     # (the rows' own revision is 19 here: O1's verdict is revision 18)
    # the revision flag still selects the cohort
    assert ev.evaluate(rows, prices, D0, 12, revision=18)["revision"] == 18


def test_an_untouched_split_gives_the_groups_per_part(tmp_path):
    rows, prices, *_ = _cohort(tmp_path)
    res = ev.evaluate(rows, prices, D0, 12, untouched={"A1", "A3", "D1"})
    u, b = res["groups"]["untouched"]["call_groups"], res["groups"]["book"]["call_groups"]
    assert u["crux_calls"]["calls"] == 2 and b["crux_calls"]["calls"] == 5
    assert u["calls_the_rule_demoted"]["calls"] == 1 and b["calls_the_rule_demoted"]["calls"] == 2

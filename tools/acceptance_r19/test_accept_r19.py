"""Proves revision 19's acceptance tooling: the P3 replays on the frozen runs (offline, sockets blocked, in a subprocess) and, in later sections,
Part I's measurement on synthetic data. Nothing here is an acceptance run.

Run (from the repository root):  python -m pytest tools/acceptance_r19/test_accept_r19.py -q -p no:cacheprovider --confcutdir tools/acceptance_r19
Environment: ACCEPT_SP (the scratchpad holding gpu_r18/tree, final/tree, sd_full and backtest/out/c2/mri). Tests that need it are skipped and say so.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
SP = Path(os.environ["ACCEPT_SP"]) if os.environ.get("ACCEPT_SP") else None
PY = sys.executable
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "tools" / "audit_202608"))

_have_sp = (SP is not None and (SP / "gpu_r18" / "tree" / "ab_reports" / "consensus").exists()
            and (SP / "final" / "tree" / "ab_reports" / "consensus").exists() and (SP / "backtest" / "out" / "c2" / "mri").exists())
needs_sp = pytest.mark.skipif(not _have_sp, reason="ACCEPT_SP does not hold the frozen runs (gpu_r18/tree, final/tree, backtest/out/c2/mri)")


@pytest.fixture(scope="module")
def replays():
    p = subprocess.run([PY, str(HERE / "p3_replays.py"), "--tree", str(TREE), "--sp", str(SP), "--json"], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout)


# ---- P3 (a): the label code on frozen answer calls that carry no crux ---------------------------------------------------------------------

@needs_sp
def test_p3a_every_frozen_sample_is_hold_and_a_directional_one_carries_no_valid_crux_missing(replays):
    samples = [s for key in ("labels_at10", "labels_final") for run in replays[key] for s in run["samples"]]
    assert len(samples) == 6 + 12                                             # the six AT10 samples and the final test's twelve
    assert len({run["run"] for run in replays["labels_final"]}) == 6
    for s in samples:
        assert s["label"] == "hold", s
        assert s["direction_m"] == s["recorded"], s                          # the revision-18 label is kept as direction_m
        if s["recorded"] in ("undervalued", "overvalued"):
            assert s["stamps"] == ["no_valid_crux:missing"] and s["reason"] == "missing", s
        else:
            assert s["stamps"] == [], s
    assert sum(1 for s in samples if s["recorded"] in ("undervalued", "overvalued")) >= 10


@needs_sp
def test_p3a_at_the_verdict_level_every_direction_is_hold_and_direction_m_is_the_published_direction(replays):
    runs = replays["labels_at10"] + replays["labels_final"]
    for run in runs:
        v = run["verdict"]
        assert v["direction"] == "hold", run["run"]
        assert v["direction_m"] == v["published"], run["run"]
        if v["direction_m"] in ("undervalued", "overvalued"):
            assert v["flags"] == ["no_valid_crux:missing"] and v["crux_valid"] is False
    published = {run["run"]: run["verdict"]["published"] for run in replays["labels_at10"]}
    assert published == {"UGI": "undervalued", "MPWR": "hold", "MU": "undervalued"}


# ---- P3 (b): the six AT10 answer calls through the revision-19 desk -------------------------------------------------------------------------

@needs_sp
def test_p3b_four_reproduce_mpwr_s2_changes_mu_s2_is_refused(replays):
    rows = {(r["run"], r["sample"]): r for r in replays["desk_at10"]}
    assert set(rows) == {("UGI", 1), ("UGI", 2), ("MPWR", 1), ("MPWR", 2), ("MU", 1), ("MU", 2)}
    for key in (("UGI", 1), ("UGI", 2), ("MPWR", 1), ("MU", 1)):
        assert rows[key]["error"] is None and rows[key]["desk"] == rows[key]["recorded_base"], key       # to the cent
    assert rows[("MPWR", 1)]["held"] is False
    mpwr2 = rows[("MPWR", 2)]
    assert mpwr2["recorded_base"] == 1017.44 and mpwr2["desk"] == 839.56 and mpwr2["held"] is True        # fix item 2: years 1-2 held at the levels
    mu2 = rows[("MU", 2)]
    assert mu2["desk"] is None and "excess_cash 68.274000 B is above the base fiscal year's cash and short-term investments 10.307000 B" in mu2["error"]


@needs_sp
def test_p3b_each_price_implied_value_reproduces_the_price_or_is_not_reachable_with_its_bound(replays):
    n_reachable = n_unreachable = 0
    for r in replays["desk_at10"]:
        pi = r["price_implied"]
        if r["desk"] is None:
            assert pi is None
            continue
        assert pi and "error" not in pi, r["run"]
        for name, blk in pi.items():
            if blk["reachable"]:
                n_reachable += 1
                if name == "fade_years":
                    lo, hi = blk["bracket_values"]
                    assert min(lo, hi) - 1e-9 <= r["price"] <= max(lo, hi) + 1e-9
                else:
                    assert abs(blk["base_at_value"] - r["price"]) <= 0.01, (r["run"], r["sample"], name)
            else:
                n_unreachable += 1
                assert blk["value"] is None and (blk["side"] in ("above", "below") or blk.get("not_available")), (r["run"], name)
                assert blk["bound"]["low"] is not None or blk.get("not_available")
    assert n_reachable > 0 and n_unreachable > 0


@needs_sp
def test_p3b_cross_check_the_solver_agrees_with_the_reviewers_rebuild_within_0_0005(replays):
    """The reviewer rebuilt each Base from the desk echo (matching within $0.004): UGI s1 implied coe 9.80% against its own 7.35%, MU s1 12.11% against 9.70%."""
    rows = {(r["run"], r["sample"]): r["price_implied"] for r in replays["desk_at10"]}
    ugi, mu = rows[("UGI", 1)]["coe"], rows[("MU", 1)]["coe"]
    assert abs(ugi["value"] - 0.0980) <= 0.0005 and abs(ugi["own"] - 0.0735) <= 0.0005
    assert abs(mu["value"] - 0.1211) <= 0.0005 and abs(mu["own"] - 0.0970) <= 0.0005


@needs_sp
def test_p3b_reported_not_a_bar_the_other_values_of_sample_1(replays):
    rows = {(r["run"], r["sample"]): r["price_implied"] for r in replays["desk_at10"]}
    ugi, mpwr = rows[("UGI", 1)], rows[("MPWR", 1)]
    assert abs(ugi["growth_years_3_5"]["value"] - (-0.137)) < 0.001 and abs(ugi["growth_years_3_5"]["own"] - 0.030) < 0.001
    assert ugi["terminal_ronic"]["reachable"] is False and ugi["fade_years"]["reachable"] is False
    assert abs(mpwr["coe"]["value"] - 0.0637) < 0.0005 and abs(mpwr["coe"]["own"] - 0.097) < 0.0005
    assert abs(mpwr["growth_years_3_5"]["value"] - 0.505) < 0.001 and abs(mpwr["growth_years_3_5"]["own"] - 0.199) < 0.001
    assert 38 <= mpwr["fade_years"]["value"] <= 39.5 and mpwr["fade_years"]["own"] == 4
    assert mpwr["terminal_g"]["reachable"] is False and mpwr["terminal_ronic"]["reachable"] is False


# ---- P3 (c): reason 19 -----------------------------------------------------------------------------------------------------------------------

def test_p3c_reason_19_fires_on_a_synthetic_directional_row_without_a_valid_crux():
    import depth_gates
    row = {"direction": "undervalued", "gate_version": depth_gates.GATE_VERSION, "n_basis": 2, "pack_revision": 19, "crux_valid": False}
    assert "directional_without_valid_crux" in depth_gates.assess(row)[1]
    assert "directional_without_valid_crux" not in depth_gates.assess(dict(row, crux_valid=True))[1]


@needs_sp
def test_p3c_reason_19_fires_on_none_of_the_replayed_rows(replays):
    import depth_gates
    for run in replays["labels_at10"] + replays["labels_final"]:
        v = run["verdict"]
        row = {"direction": v["direction"], "gate_version": depth_gates.GATE_VERSION, "pack_revision": 19, "crux_valid": v["crux_valid"]}
        assert "directional_without_valid_crux" not in depth_gates.assess(row)[1], run["run"]


# ---- G3: frozen-replay parity on the four development names' built packs --------------------------------------------------------------------

_have_dev = (_have_sp and (SP / "review_fitems" / "root_book" / "enrich").exists() and (SP / "sd_full").exists()
             and (SP / "closure_full" / "reference_closure.json").exists())


def test_g3_the_difference_helper_sees_what_it_should():
    sys.path.insert(0, str(HERE))
    import g3_replay_parity as g3
    assert g3.differences({"a": [1, 2.0], "b": None}, {"a": [1, 2.0], "b": None}) == []
    assert g3.differences({"a": [1, 2.0]}, {"a": [1, 2]}) == ["/a[1]"]
    assert g3.differences({"a": 1}, {"b": 1}) == ["/a", "/b"] and g3.differences({"a": (1, 2)}, {"a": [1, 3]}) == ["/a[1]"]
    assert g3.differences(float("nan"), float("nan")) == [] and g3.differences(float("inf"), float("inf")) == []


@pytest.mark.skipif(not _have_dev, reason="ACCEPT_SP does not hold the book day's data roots (review_fitems/root_book, sd_full, closure_full)")
def test_g3_the_replay_context_equals_the_fresh_one_on_the_four_development_names(tmp_path):
    names = tmp_path / "names.txt"
    names.write_text(chr(10).join(["UGI", "MPWR", "MU", "LAMR"]) + chr(10), encoding="utf-8")
    p = subprocess.run([PY, str(HERE / "g3_replay_parity.py"), "--tree", str(TREE), "--root", str(SP / "review_fitems" / "root_book"), "--sd", str(SP / "sd_full"),
                        "--mri", str(SP / "backtest" / "out" / "c2" / "mri"), "--date", "2026-10-02", "--closure", str(SP / "closure_full" / "reference_closure.json"),
                        "--names", str(names), "--json"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    result = json.loads(p.stdout)
    assert set(result) == {"UGI", "MPWR", "MU", "LAMR"}
    for name, r in result.items():
        assert r["differences"] == [] and r["keys"] >= 27, name


# ---- Part I: the levels method's earnings basis (measure only), on synthetic data -------------------------------------------------------------

def _lb():
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(TREE / "tools"))
    import levels_eps_basis as lb
    return lb


def test_part_i_classes_by_the_two_percent_rules():
    lb = _lb()
    m = lb.measure(10.1, 10.0, 2.0, 0.2)                      # within 2% of filed
    assert m["class"] == "gaap_like" and m["ya_over_filed"] == pytest.approx(1.01)
    m = lb.measure(12.0, 10.0, 2.0, 0.2)                      # filed plus stock pay, before tax
    assert m["class"] == "adjusted_like" and m["ya_over_filed_plus_pre_tax"] == pytest.approx(1.0)
    assert m["ya_over_filed_plus_after_tax"] == pytest.approx(12.0 / 11.6)
    assert lb.measure(15.0, 10.0, 2.0, 0.2)["class"] == "adjusted_like"      # above filed by more than 2%, whatever the stock pay
    assert lb.measure(15.0, 10.0, None, 0.2)["class"] == "adjusted_like"
    assert lb.measure(9.0, 10.0, 2.0, 0.2)["class"] == "unclassified"        # below filed by more than 2% and not filed plus stock pay
    assert lb.measure(10.2, 10.0, 2.0, 0.2)["class"] == "gaap_like"          # 2% is inside; filed wins over a filed-plus match
    assert lb.measure(10.21, 10.0, 0.1, 0.2)["class"] == "adjusted_like"


def test_part_i_no_filed_basis_and_zero_values_are_values():
    lb = _lb()
    assert lb.measure(None, 10.0, 1.0, 0.2)["class"] == "no_vendor_year_ago" and lb.measure(None, None, 1.0, 0.2)["class"] == "no_vendor_year_ago"
    assert lb.measure(float("nan"), 10.0, 1.0, 0.2)["class"] == "no_vendor_year_ago"
    assert lb.measure(10.0, None, 1.0, 0.2)["class"] == "no_filed_basis"
    m = lb.measure(0.0, 0.0, 0.0, 0.0)                                       # a zero is a number: both equal, so GAAP-like; no ratio, no restatement
    assert m["class"] == "gaap_like" and m["ya_over_filed"] is None and m["restate"] is None
    m = lb.measure(0.5, 0.0, 0.0, 0.2)
    assert m["class"] == "adjusted_like" and m["ya_over_filed_plus_pre_tax"] is None
    assert lb.measure(5.0, 4.0, 0.0, 0.2)["ya_over_filed_plus_after_tax"] == pytest.approx(1.25)
    m = lb.measure(-1.0, 2.0, 0.5, 0.2)                                      # a loss year-ago EPS cannot restate
    assert m["class"] == "unclassified" and m["restate"] is None
    assert lb.measure(8.0, 4.0, 1.0, 0.2)["restate"] == pytest.approx(0.5)


def test_part_i_restating_scales_both_levels_and_nothing_else():
    lb = _lb()
    est = {"0y": {"eps": {"avg": 8.0, "growth": 0.5, "year_ago": 5.0, "analysts": 4}, "revenue": {"avg": 1.0}},
           "+1y": {"eps": {"avg": 10.0, "growth": 0.25, "analysts": 4}}}
    out = lb.restated_estimates(est, 0.5)
    assert out["0y"]["eps"]["avg"] == 4.0 and out["+1y"]["eps"]["avg"] == 5.0
    assert out["0y"]["eps"]["growth"] == 0.5 and out["0y"]["revenue"] == {"avg": 1.0} and out["0y"]["eps"]["year_ago"] == 5.0
    assert est["0y"]["eps"]["avg"] == 8.0                                    # the input is not touched


def test_part_i_summary_counts_and_medians_carry_no_name():
    lb = _lb()
    recs = [dict(lb.measure(10.0, 10.0, 1.0, 0.2), restated_ratio=1.0),
            dict(lb.measure(14.0, 10.0, 1.0, 0.2), restated_ratio=0.5),
            dict(lb.measure(16.0, 10.0, 1.0, 0.2), restated_ratio=0.7),
            dict(lb.measure(5.0, 10.0, 1.0, 0.2), restated_ratio=2.0),
            dict(lb.measure(None, 10.0, 1.0, 0.2), restated_ratio=None)]
    s = lb.summarize(recs)
    assert s["names"] == 5 and s["counts"] == {"gaap_like": 1, "adjusted_like": 2, "loss_maker": 0, "unclassified": 1, "no_vendor_year_ago": 1, "no_filed_basis": 0}
    assert s["medians"]["ya_over_filed"] == pytest.approx(1.2) and s["medians"]["restated_ratio"] == pytest.approx(0.85)
    assert s["by_class"]["adjusted_like"]["ya_over_filed"] == pytest.approx(1.5) and s["by_class"]["adjusted_like"]["restated_ratio_available"] == 2
    assert s["by_class"]["no_vendor_year_ago"]["ya_over_filed"] is None and s["by_class"]["no_filed_basis"]["n"] == 0
    loss = lb.summarize([dict(lb.measure(1.0, -2.0, 0.5, 0.2), restated_ratio=None), dict(lb.measure(-3.0, -2.0, 0.5, 0.2), restated_ratio=None)])
    assert loss["counts"]["loss_maker"] == 2 and loss["counts"]["adjusted_like"] == 0 and loss["by_class"]["loss_maker"]["filed_eps_not_positive"] == 2   # a loss is its own class, not classed by sign
    assert lb.measure(-3.0, -2.0, 0.5, 0.2)["restate"] is None and lb.measure(0.0, 0.0, 0.0, 0.2)["class"] == "gaap_like"
    assert lb.summarize([])["medians"]["restated_ratio"] is None


def _fake_world(ticker_rows):
    """A namespace with a fake capability module, reference module and ledger wiring: `ticker_rows` {ticker: (ni, sbc, shares, ya, e0, e1, value)}."""
    import datetime
    import types
    import reference_ledger as rl
    h = {t: {"2025": {"net_income": v[0], "sbc": v[1], "pretax_income": 100.0, "tax_provision": 20.0}} for t, v in ticker_rows.items()}
    cap = types.SimpleNamespace(
        DataRoot=lambda: types.SimpleNamespace(history=lambda t: h[t], fin=lambda t: {}, shares_cover=lambda t: None),
        _shares_default_state=lambda t, fin, hh, c: (None, None, ticker_rows[t][2]),
        throughcycle_record=types.SimpleNamespace(tax_rate=lambda row: row["tax_provision"] / row["pretax_income"]))
    calls = []

    def build(**k):
        calls.append(k)
        e = k["estimates"]
        return {"method": "levels", "value": 10.0 * e["+1y"]["eps"]["avg"]}                # a value linear in the +1y level
    cref = types.SimpleNamespace(build=build)

    def adapters(root, today=None):
        return {"inputs_fn": lambda t: {"estimates": _est(ticker_rows[t]), "coe": 0.09}}
    return types.SimpleNamespace(cap=cap, cref=cref, root="r", fixed=datetime.datetime(2026, 10, 2, 12)), adapters, calls


def _est(v):
    return {"0y": {"eps": {"avg": v[4], "year_ago": v[3], "analysts": 3}}, "+1y": {"eps": {"avg": v[5], "analysts": 3}}}


def _day_rows(ticker_rows, anonymous=False):
    import hashlib
    rows = {}
    for t, v in ticker_rows.items():
        key = hashlib.sha256(t.encode()).hexdigest()[:12] if anonymous else t
        rows[key] = {"ticker": None if anonymous else t, "reference": {"method": "levels", "value": v[6], "estimates": _est(v)}}
    rows["GROWTH"] = {"ticker": "GROWTH", "reference": {"method": "growth", "value": 5.0, "estimates": {}}}
    return rows


WORLD = {"MU": (10.0, 3.0, 1.0, 14.0, 12.0, 20.0, 200.0),          # filed EPS 10.0, stock pay 3.0 per share, vendor year-ago 14.0
         "AAA": (10.0, 1.0, 1.0, 10.0, 11.0, 14.0, 140.0),
         "BBB": (10.0, 1.0, 1.0, 4.0, 5.0, 6.0, 60.0)}


def test_part_i_run_restates_the_levels_and_prints_only_the_development_name(monkeypatch, capsys):
    lb = _lb()
    import reference_ledger as rl
    ns, adapters, calls = _fake_world(WORLD)
    monkeypatch.setattr(rl, "production_adapters", adapters)
    result = lb.run(ns, _day_rows(WORLD), show="MU")
    assert result["names"] == 3 and result["levels_names_in_day"] == 3                       # the growth name is not a levels name
    assert result["counts"] == {"gaap_like": 1, "adjusted_like": 1, "loss_maker": 0, "unclassified": 1, "no_vendor_year_ago": 0, "no_filed_basis": 0}
    mu = result["shown"]
    assert mu["class"] == "adjusted_like" and mu["ya_over_filed"] == pytest.approx(1.4)
    assert mu["ya_over_filed_plus_pre_tax"] == pytest.approx(14.0 / 13.0) and mu["ya_over_filed_plus_after_tax"] == pytest.approx(14.0 / 12.4)
    assert mu["restated_ratio"] == pytest.approx(10.0 / 14.0)                                  # the levels x filed / year-ago: value x 10/14
    assert [c["estimates"]["+1y"]["eps"]["avg"] for c in calls] == pytest.approx([14.0, 6.0 * 2.5, 20.0 * 10.0 / 14.0])
    assert "AAA" not in json.dumps(result) and "BBB" not in json.dumps(result)
    assert lb.run(ns, _day_rows(WORLD), show="ZZZ")["shown"] is None


def test_part_i_an_anonymous_day_is_looked_up_through_the_names_file_in_memory(monkeypatch, tmp_path):
    lb = _lb()
    import reference_ledger as rl
    ns, adapters, _ = _fake_world(WORLD)
    monkeypatch.setattr(rl, "production_adapters", adapters)
    rows = _day_rows(WORLD, anonymous=True)
    names = tmp_path / "names.txt"
    names.write_text(chr(10).join(WORLD) + chr(10), encoding="utf-8")
    r = lb.run(ns, rows, names, show="MU")
    assert r["names"] == 3 and r["skipped_no_ticker"] == 0 and r["shown"]["class"] == "adjusted_like"
    r2 = lb.run(ns, rows, None, show="MU")                                                     # no names file: nothing can be looked up, said so
    assert r2["names"] == 0 and r2["skipped_no_ticker"] == 3 and r2["shown"] is None
    assert not any(t in json.dumps(r) for t in ("AAA", "BBB"))


def test_part_i_the_script_has_no_engine_import_that_changes_anything():
    src = (HERE / "levels_eps_basis.py").read_text(encoding="utf-8")
    assert "consensus_reference" not in src and "financial_model_tool" not in src and "PACK_REVISION" not in src

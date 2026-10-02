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

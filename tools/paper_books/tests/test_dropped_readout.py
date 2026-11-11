"""WO_DR1 tests: dropped_readout.py on synthetic action lines and a stub fetch. No network, no real books.
Run from the repo root:  python -m pytest tools/paper_books/tests -q"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dropped_readout as D  # noqa: E402

DAY0 = date(2026, 1, 5)
SESSIONS = [(DAY0 + timedelta(days=i)).isoformat() for i in range(31)]      # session index k = days after the first fill
T1, T2 = "2026-01-02", "2026-01-20"
TODAY = DAY0 + timedelta(days=32)                                          # so the last completed session is index 31 - 1 = 30


def line(t, action, causes=None, rule="E1", T=T1, fill=SESSIONS[0], kind="at_fill_open", arm="FQ"):
    l = {"arm": arm, "kind": kind, "formation_T": T, "fill_session": fill, "ticker": t, "action": action, "rule": rule}
    if causes is not None:
        l["causes"] = causes
    return l


def bars(open_, close_by_k, sessions=SESSIONS, fill_k=0):
    """{date: (open, close)}: the open at the fill session is `open_`; every other bar's open is the same, the close is close_by_k(k)."""
    return {d: (open_, close_by_k(k)) for k, d in enumerate(sessions) if k >= fill_k}


def fetch_of(table):
    return lambda tickers, start, end: ("stub", {t: v for t, v in table.items() if t in tickers})


SPY = bars(100.0, lambda k: 100.0 + k)       # +20 % at k = 20, +30 % at the last session (k = 30)


def run(lines, table, today=TODAY):
    return D.readout(lines, fetch_of({"SPY": SPY, **table}), today)


# ------------------------------------------------------------------ the group rules, one case per row of the table

@pytest.mark.parametrize("ln, group", [
    (line("A", "enter"), "kept"),
    (line("A", "hold"), "kept"),
    (line("A", "enter_after_pending", rule="A1S", kind="pending_resolution"), "kept"),
    (line("A", "hold", ["B1"]), "flagged_held"),
    (line("A", "hold", ["Q1", "B1"]), "flagged_held"),
    (line("A", "new_entry_restricted", ["B1"]), "dropped_code"),
    (line("A", "new_entry_restricted", ["Q1"]), "dropped_qwen"),
    (line("A", "new_entry_restricted", rule="Q1", kind="pending_resolution"), "dropped_qwen"),
    (line("A", "new_entry_restricted", ["B1", "Q1"]), "dropped_both"),
    (line("A", "analysis_pending", rule="A1S"), "other"),
    (line("A", "analysis_incomplete", rule="A1S", kind="pending_resolution"), "other"),
    (line("A", "operator_excluded"), "other"),
])
def test_group_rule(ln, group):
    assert D.group_of(ln) == group


def test_last_line_decides_and_other_arms_and_kinds_are_ignored():
    lines = [line("A", "analysis_pending", rule="A1S"), line("A", "enter_after_pending", rule="A1S", kind="pending_resolution"),
             line("B", "analysis_pending", rule="A1S"), line("B", "new_entry_restricted", rule="Q1", kind="pending_resolution"),
             line("C", "enter", arm="FB"), line("C", "operator_excluded"), line("C", "enter", kind="escalation")]
    names = D.formations(lines)[T1]["names"]
    assert names == {"A": ("kept", "enter_after_pending"), "B": ("dropped_qwen", "new_entry_restricted"),
                     "C": ("other", "operator_excluded")}


# ------------------------------------------------------------------ the arithmetic

def test_hand_computed_returns_mean_median_and_difference():
    lines = [line("K1", "enter"), line("K2", "enter"), line("K3", "hold"), line("D1", "new_entry_restricted", ["Q1"]),
             line("X", "analysis_pending", rule="A1S")]
    table = {"K1": bars(50.0, lambda k: 70.0 if k >= 20 else 50.0),         # +40 %
             "K2": bars(10.0, lambda k: 11.0 if k >= 20 else 10.0),         # +10 %
             "K3": bars(100.0, lambda k: 160.0 if k >= 20 else 100.0),      # +60 %
             "D1": bars(20.0, lambda k: 21.0 if k >= 20 else 20.0)}         # +5 %
    f = run(lines, table)["formations"][T1]
    kept = f["groups"]["kept"]
    assert (kept["n"], kept["n_priced"]) == (3, 3)
    assert kept["stats"][20]["mean"] == pytest.approx((0.4 + 0.1 + 0.6) / 3, abs=1e-6)
    assert kept["stats"][20]["median"] == pytest.approx(0.4)
    assert kept["stats"][20]["mean_minus_spy"] == pytest.approx((0.2 - 0.1 + 0.4) / 3, abs=1e-6)      # SPY is +20 %
    assert kept["stats"][20]["median_minus_spy"] == pytest.approx(0.2)
    assert f["spy"][20] == pytest.approx(0.2) and f["spy"]["to_date"] == pytest.approx(0.3)
    assert f["groups"]["dropped_qwen"]["stats"][20]["mean"] == pytest.approx(0.05)
    assert f["minus_kept"]["dropped_qwen"][20] == pytest.approx(0.05 - 1.1 / 3, abs=1e-6)
    assert f["minus_kept"]["dropped_code"][20] is None                      # no priced dropped_code name
    assert f["other"] == [{"ticker": "X", "action": "analysis_pending"}]


def test_horizon_not_reached_is_absent_not_zero():
    res = run([line("K", "enter"), line("D", "new_entry_restricted", ["Q1"])],
              {"K": bars(10.0, lambda k: 12.0), "D": bars(10.0, lambda k: 9.0)})
    f = res["formations"][T1]
    assert 60 not in f["groups"]["kept"]["names"][0]["returns"] and 60 not in f["spy"]
    assert set(f["groups"]["kept"]["names"][0]["returns"]) == {20, "to_date"}
    assert 60 not in f["groups"]["kept"]["stats"] and 60 not in f["minus_kept"]["dropped_qwen"]
    assert res["pooled"]["groups"][60]["kept"] == {"n": 0, "n_priced": 0, "mean": None, "median": None,
                                                    "mean_minus_spy": None, "median_minus_spy": None}
    assert res["pooled"]["minus_kept"]["dropped_qwen"][60] is None


def test_no_price_is_counted_and_never_dropped():
    lines = [line("K", "enter"), line("NOFILL", "enter"), line("NOAFTER", "enter"), line("ZEROOPEN", "enter")]
    table = {"K": bars(10.0, lambda k: 12.0),
             "NOFILL": bars(10.0, lambda k: 12.0, fill_k=1),                # first bar after the fill session
             "NOAFTER": {SESSIONS[0]: (10.0, 10.0)},                        # only the fill bar
             "ZEROOPEN": bars(0.0, lambda k: 1.0)}                          # no base to divide by
    g = run(lines, table)["formations"][T1]["groups"]["kept"]
    assert (g["n"], g["n_priced"], g["no_price"]) == (4, 1, 3)
    assert [x["ticker"] for x in g["names"] if x.get("no_price")] == ["NOAFTER", "NOFILL", "ZEROOPEN"]
    assert g["stats"][20]["n_priced"] == 1


def test_missing_bar_on_a_horizon_date_uses_the_last_bar_before_it_and_says_so():
    b = bars(10.0, lambda k: 10.0 + k)
    del b[SESSIONS[20]]                                                     # no bar on the 20th session; the 19th stands in
    row = run([line("K", "enter")], {"K": b})["formations"][T1]["groups"]["kept"]["names"][0]
    assert row["returns"][20] == pytest.approx(29.0 / 10.0 - 1.0)
    assert row["stale_bar"] == {20: SESSIONS[19]}


def test_a_zero_price_is_a_value():
    row = run([line("K", "enter")], {"K": bars(10.0, lambda k: 0.0 if k >= 20 else 10.0)})["formations"][T1]["groups"]["kept"]
    assert row["names"][0]["returns"][20] == -1.0
    assert row["stats"][20]["mean"] == -1.0


# ------------------------------------------------------------------ pooling and the file

def two_formations():
    late = SESSIONS[15]                                                     # the 20th session after it is past the data
    lines = [line("K1", "enter"), line("D1", "new_entry_restricted", ["Q1"]), line("D2", "new_entry_restricted", ["B1", "Q1"]),
             line("K1", "enter", T=T2, fill=late), line("D1", "new_entry_restricted", ["Q1"], T=T2, fill=late),
             line("D3", "new_entry_restricted", ["B1"], T=T2, fill=late)]
    table = {"K1": bars(10.0, lambda k: 12.0), "D1": bars(10.0, lambda k: 9.0), "D2": bars(10.0, lambda k: 8.0),
             "D3": bars(10.0, lambda k: 11.0)}
    return lines, table


def test_pooled_counts_each_name_once_per_formation_at_the_fixed_horizons():
    res = run(*two_formations())
    p = res["pooled"]["groups"]
    assert p[20]["kept"]["n"] == 1 and p[20]["kept"]["n_priced"] == 1          # formation 2 does not reach 20 sessions
    assert p[20]["dropped_qwen"]["n"] == 1 and p[20]["dropped_both"]["n"] == 1 and p[20]["dropped_code"]["n"] == 0
    assert res["formations"][T2]["groups"]["dropped_qwen"]["n"] == 1             # D1 is counted in both formations, once each
    assert res["pooled"]["minus_kept"]["dropped_qwen"][20] == pytest.approx(-0.1 - 0.2, abs=1e-6)
    assert res["pooled"]["minus_kept"]["dropped_code"][20] is None
    assert "to_date" not in p and set(res["fill_sessions"]) == {T1, T2}


def test_second_run_the_same_day_rewrites_the_same_file(tmp_path, monkeypatch):
    lines, table = two_formations()
    books = tmp_path / "books"
    (books / "m3o" / "ledger").mkdir(parents=True)
    (books / "m3o" / "ledger" / "actions.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(D.book_paths, "books", lambda: books)
    fetch = fetch_of({"SPY": SPY, **table})
    assert D.main(fetch, TODAY) == 0
    out = books / "m3o" / "readout"
    first = [p.name for p in out.iterdir()]
    assert first == [f"dropped_{SESSIONS[30]}.json"]
    (out / first[0]).write_text("stale", encoding="utf-8")
    assert D.main(fetch, TODAY) == 0
    assert [p.name for p in out.iterdir()] == first
    saved = json.loads((out / first[0]).read_text(encoding="utf-8"))
    assert saved["source"] == "stub" and saved["note"] == D.NOTE and saved["last_completed_session"] == SESSIONS[30]

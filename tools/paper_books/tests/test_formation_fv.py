"""formation_fv.py (the snapshot paper book FV reads, PREREG_m3o_bookV) on synthetic files: no network, no model. Run from the repo root:
python -m pytest tools/paper_books/tests -q"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import formation_fv as S  # noqa: E402

T = "2026-11-30"
NOW = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)                    # before the 09:30 open (14:30Z in December): fill 2026-12-01
EXCL, EXCL_LIST = "OPXA", "OPXB"                                          # conftest's synthetic operator exclusions


def jwrite(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")
    return p


def seed(tmp_path, t, k, status="ok", shares=100.0, **over):
    body = {"status": status} | ({"base": {"shares": shares}} if shares is not None else {})
    return {"status": status, "reason": None, "result": str(jwrite(tmp_path / "res" / f"{t}_{k}.json", {**body, **over}))}


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = SimpleNamespace(inputs=tmp_path / "inputs", value=tmp_path / "value", tmp=tmp_path)
    monkeypatch.setattr(S, "INPUTS", w.inputs)
    monkeypatch.setattr(S, "VALUE", w.value)
    book = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "NOCAP", "ZEROCAP", "SEEDA", EXCL, EXCL_LIST, "ONESEED"]
    m = {"formation_T": T, "decision_time_utc": "2026-11-30T21:00:00Z", "output_commit": "abc", "book": sorted(book),
         "names": {t: {"packet": f"{t}.json", "state": "operator_excluded" if t == EXCL else "complete"} for t in book},
         "fv_held": [{"ticker": "HLDA", "packet": "HLDA.json", "state": "built"}, {"ticker": "HLDB", "packet": "HLDB.json", "state": "built"}]}
    idx, cons = {}, {}

    def ok(t, base, cap=1000.0, shares=(100.0, 100.0), n=2):
        idx[t] = {"slots": {str(1000 + 2000 * i): seed(tmp_path, t, i, shares=s) for i, s in enumerate(shares[:n])}, "market_cap": cap}
        cons[t] = {"status": "ok", "values": {"base": base}}
    ok("AAA", 15.0)
    ok("EEE", 5.0, shares=(None, None))                                                       # results without base.shares
    ok("FFF", 5.0, shares=(100.0, 101.0))
    ok("NOCAP", 5.0, cap=None)
    ok("ZEROCAP", 5.0, cap=0)
    ok("HLDA", 0.0)                                                                           # a value of 0.0 is a value
    ok("HLDB", -2.0, cap=500.0)
    ok("ONESEED", 7.0, shares=(80.0,), n=1)
    idx["SEEDA"] = {"slots": {"1000": seed(tmp_path, "SEEDA", 0, shares=50.0), "3000": seed(tmp_path, "SEEDA", 1, status="reply_invalid", shares=None)},
                  "market_cap": 200.0}
    cons["SEEDA"] = {"status": "ok_with_reverts", "values": {"base": 4.0}}
    idx["CCC"] = {"slots": {"1000": {"status": "no_call", "reason": "field_missing", "result": None}}, "market_cap": 1000.0}
    cons["CCC"] = {"status": "no_call", "reason": ["no_call:field_missing"], "values": {}}
    idx["DDD"] = {"slots": {"1000": {"status": "no_call", "reason": "coe_unavailable", "result": None},
                            "3000": {"status": "reply_invalid", "reason": "bad", "result": None}}, "market_cap": 1000.0}   # no consensus entry
    idx[EXCL_LIST] = {"slots": {}, "market_cap": 1}
    cons[EXCL_LIST] = {"status": "ok", "values": {"base": 1.0}}
    w.map = jwrite(w.inputs / f"formation_{T}.json", m)
    w.index = jwrite(w.value / f"formation_{T}.json", {"formation_T": T, "names": idx})
    w.cons = jwrite(w.value / f"consensus_{T}.json", {"formation_T": T, "names": cons})
    w.out = w.value / f"fv_{T}.json"
    return w


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_every_reason_of_the_table_and_the_arithmetic(world, capsys):
    assert S.main(T, NOW) == 0
    snap = load(world.out)
    n = snap["names"]
    assert set(n) == {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "NOCAP", "ZEROCAP", "SEEDA", "ONESEED", "HLDA", "HLDB"}      # no operator-excluded name
    assert {t: n[t]["role"] for t in n} == {**{t: "book" for t in n}, "HLDA": "fv_held", "HLDB": "fv_held"}
    why = {t: (v["valued"], v["reason"]) for t, v in n.items() if not v["valued"]}
    assert why == {"BBB": (False, "not_in_index"), "CCC": (False, "no_value: no_call:field_missing"),
                   "DDD": (False, "no_value: no_call:coe_unavailable; reply_invalid:bad"), "EEE": (False, "shares_missing"),
                   "FFF": (False, "shares_differ"), "NOCAP": (False, "market_cap_missing"), "ZEROCAP": (False, "market_cap_missing")}
    assert all(v["value_base"] is None and v["shares"] is None and v["equity_value"] is None and v["market_cap"] is None and v["cheapness"] is None
               for v in (n[t] for t in why))
    assert n["AAA"] == {"role": "book", "valued": True, "reason": None, "value_base": 15.0, "shares": 100.0, "equity_value": 1500.0,
                        "market_cap": 1000.0, "cheapness": 1.5}
    assert (n["SEEDA"]["valued"], n["SEEDA"]["shares"], n["SEEDA"]["cheapness"]) == (True, 50.0, 4.0 * 50.0 / 200.0)          # one ok seed, one reply_invalid
    assert (n["ONESEED"]["valued"], n["ONESEED"]["equity_value"]) == (True, 560.0)                                                # one seed only
    assert (n["HLDA"]["valued"], n["HLDA"]["cheapness"], n["HLDA"]["value_base"]) == (True, 0.0, 0.0)                         # 0.0 is a value
    assert (n["HLDB"]["valued"], n["HLDB"]["cheapness"]) == (True, -2.0 * 100.0 / 500.0)                                     # so is a negative one
    assert (snap["formation_T"], snap["written_utc"], snap["fill_session"]) == (T, "2026-12-01T10:00:00Z", "2026-12-01")
    assert snap["consensus_sha256"] == hashlib.sha256(world.cons.read_bytes()).hexdigest()
    assert snap["index_sha256"] == hashlib.sha256(world.index.read_bytes()).hexdigest()
    assert snap["map_sha256"] == hashlib.sha256(world.map.read_bytes()).hexdigest()
    assert "wrote" in capsys.readouterr().out and not list(world.value.glob("*.tmp"))


def test_written_once_a_second_call_leaves_the_bytes(world, capsys):
    S.main(T, NOW)
    before = world.out.read_bytes()
    world.cons.write_text(json.dumps({"names": {}}), encoding="utf-8")                           # nothing is compared
    capsys.readouterr()
    assert S.main(T, datetime(2026, 12, 9, tzinfo=timezone.utc)) == 0
    assert "unchanged" in capsys.readouterr().out and world.out.read_bytes() == before


def test_before_the_start_nothing_is_written(world, capsys):
    assert S.main("2026-10-30", NOW) == 0
    assert "nothing to do" in capsys.readouterr().out and not list(world.value.glob("fv_*"))


@pytest.mark.parametrize("missing", ["cons", "index"])
def test_not_valued_yet(world, missing, capsys):
    getattr(world, missing).unlink()
    assert S.main(T, NOW) == 0
    assert "not valued yet" in capsys.readouterr().out and not world.out.exists()


def test_a_later_formation_map_means_fv_skips_this_one(world, capsys):
    jwrite(world.inputs / "formation_2026-12-31.frozen.json", {})                                # only a strict map name counts
    jwrite(world.inputs / f"formation_{T}_superseded_5.json", {})
    jwrite(world.inputs / "formation_2026-10-30.json", {})                                       # an earlier formation does not block
    assert S.main(T, NOW) == 0 and world.out.exists()
    world.out.unlink()
    jwrite(world.inputs / "formation_2026-12-31.json", {})
    capsys.readouterr()
    assert S.main(T, NOW) == 0
    assert "FV skips 2026-11-30" in capsys.readouterr().out and not world.out.exists()


@pytest.mark.parametrize("now,fill", [
    (datetime(2026, 12, 4, 22, 0, tzinfo=timezone.utc), "2026-12-07"),             # Friday after the close: across the weekend, Monday
    (datetime(2026, 12, 24, 22, 0, tzinfo=timezone.utc), "2026-12-28"),            # Thursday after the close: 12-25 is a holiday in the table, then a weekend
    (datetime(2026, 12, 1, 14, 29, 59, tzinfo=timezone.utc), "2026-12-01"),        # one second before the 09:30 open
    (datetime(2026, 12, 1, 14, 30, 0, tzinfo=timezone.utc), "2026-12-02"),         # at the open: strictly after is the next session
    (datetime(2026, 12, 1, 22, 0, tzinfo=timezone.utc), "2026-12-02"),
])
def test_the_fill_session_is_the_first_new_york_open_strictly_after_written(world, now, fill):
    S.main(T, now)
    assert load(world.out)["fill_session"] == fill


def test_a_ticker_in_the_book_and_in_fv_held_stops_and_writes_nothing(world):
    m = load(world.map)
    m["fv_held"].append({"ticker": "AAA", "packet": None, "state": "to_build"})
    jwrite(world.map, m)
    with pytest.raises(SystemExit, match="AAA"):
        S.main(T, NOW)
    assert not world.out.exists()


@pytest.mark.parametrize("absent", [True, False])
def test_a_missing_or_null_fv_held_means_no_held_names(world, absent):
    m = load(world.map)
    m.pop("fv_held") if absent else m.update(fv_held=None)
    jwrite(world.map, m)
    S.main(T, NOW)
    assert not [t for t, v in load(world.out)["names"].items() if v["role"] == "fv_held"]

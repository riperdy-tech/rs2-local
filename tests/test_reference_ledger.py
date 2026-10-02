"""tests/test_reference_ledger.py - revision 18 brief section 5: the forward ledger (tools/reference_ledger.py).

The ledger's one structural promise is that it is APPEND-ONLY, so most of this file proves that: the old bytes stay a prefix of
the new file, no call opens the file for anything but reading or appending, nothing truncates, replaces or deletes, and a schema
mismatch (in the file or in a new row) refuses before a byte is written. Everything else runs on fakes: the engine of the
ledger takes `reference_inputs`, the build, the fence, the price and the verdict as parameters (their production wiring waits
for revision 18 part 2). Tickers and the untouched list here are synthetic.
"""
import builtins
import io
import json
import os
import socket
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import reference_ledger as rl  # noqa: E402


def _row(t="AAA", d="2027-01-04", **kw):
    r = {"date": d, "ticker": t, "price": 10.0, "price_date": d, "reference_value": 12.0, "reference_status": "used", "vp": 1.2, "coe": 0.09,
         "closure_erp": 0.05, "closure_asof": "2026-12-20", "revision": 18, "verdict": None}
    r.update(kw)
    return r


def _fakes(values, prices=None, sides=None, verdicts=None):
    """inputs_fn / build_fn / fence_fn / price_fn / verdict_fn over per-ticker dicts (a missing price is None)."""
    prices = prices or {}
    sides = sides or {}
    verdicts = verdicts or {}

    def inputs_fn(t):
        if isinstance(values[t], Exception):
            raise values[t]
        return {"v": values[t], "coe": 0.09}

    return dict(inputs_fn=inputs_fn, build_fn=lambda **kw: {"value": kw["v"]}, fence_fn=lambda v, t: sides.get(t),
                price_fn=lambda t: (prices.get(t, 10.0), None if prices.get(t, 10.0) is None else "2027-01-02"), verdict_fn=lambda t: verdicts.get(t))


CLOSURE = (0.05, "2026-12-20", {"provenance": "x"})
VERDICT = {"label": "undervalued", "base_iv": 13.0, "published_at": "2027-01-01", "pack_revision": 18, "direction_m": "undervalued", "crux_valid": True,
           "crux_inputs": [{"input": "coe", "own": 0.0735, "implied": 0.098, "at_default": False}], "actionable_reasons": []}


# ---- the append-only guarantee ---------------------------------------------------------------------------------------

def test_the_fields_are_the_briefs_and_a_line_is_in_that_order(tmp_path):
    p = tmp_path / "l.jsonl"
    assert rl.FIELDS == ("date", "ticker", "price", "price_date", "reference_value", "reference_status", "vp", "coe",
                         "closure_erp", "closure_asof", "revision", "verdict")
    assert "group" not in rl.FIELDS and rl.VERDICT_KEYS == ("label", "base_iv", "published_at", "pack_revision", "direction_m", "crux_valid", "crux_inputs", "actionable_reasons")
    rl.append_rows(p, [_row("AAA"), _row("BBB")])
    lines = p.read_bytes().split(b"\n")
    assert lines[-1] == b"" and len(lines) == 3
    assert list(json.loads(lines[0])) == list(rl.FIELDS)


def test_a_second_append_leaves_every_old_byte_in_place(tmp_path):
    p = tmp_path / "l.jsonl"
    rl.append_rows(p, [_row("AAA"), _row("BBB")])
    before = p.read_bytes()
    n, skipped = rl.append_rows(p, [_row("AAA", d="2027-01-11"), _row("BBB", d="2027-01-11")])
    after = p.read_bytes()
    assert (n, skipped) == (2, 0)
    assert after.startswith(before) and len(after) > len(before)
    assert len(rl.read_ledger(p)) == 4


def test_the_same_date_and_ticker_is_skipped_never_rewritten(tmp_path):
    p = tmp_path / "l.jsonl"
    rl.append_rows(p, [_row("AAA", reference_value=12.0)])
    before = p.read_bytes()
    n, skipped = rl.append_rows(p, [_row("AAA", reference_value=99.0), _row("BBB")])
    assert (n, skipped) == (1, 1)
    after = p.read_bytes()
    assert after.startswith(before)
    assert [r["reference_value"] for r in rl.read_ledger(p)] == [12.0, 12.0]   # the old AAA line is untouched


def test_nothing_in_a_snapshot_opens_for_write_truncates_replaces_or_deletes(tmp_path, monkeypatch):
    p = tmp_path / "l.jsonl"
    modes = []
    real_open = builtins.open

    def spy(file, mode="r", *a, **k):
        modes.append(mode)
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(rl, "open", spy, raising=False)

    def boom(name):
        def f(*a, **k):
            raise AssertionError(f"{name} must never be called by the ledger")
        return f
    for obj, attr in ((os, "truncate"), (os, "remove"), (os, "unlink"), (os, "replace"), (os, "rename"),
                      (Path, "unlink"), (Path, "write_text"), (Path, "write_bytes"), (Path, "replace"), (Path, "rename"),
                      (Path, "open")):
        monkeypatch.setattr(obj, attr, boom(f"{obj.__name__}.{attr}"))
    monkeypatch.setattr(io, "open", boom("io.open"))
    monkeypatch.setattr(builtins, "open", boom("builtins.open"))   # the module's own `open` (the spy) is what it may use
    for d in ("2027-01-04", "2027-01-11"):
        rl.snapshot(d, ["AAA", "BBB"], set(), ledger_path=p, closure=CLOSURE, revision=18, **_fakes({"AAA": 12.0, "BBB": 8.0}))
    assert set(modes) <= {"rb", "ab"}, modes
    assert "ab" in modes


def test_an_existing_line_with_another_schema_refuses_and_nothing_is_written(tmp_path):
    p = tmp_path / "l.jsonl"
    rl.append_rows(p, [_row("AAA")])
    for bad in ({**_row("OLD"), "extra": 1}, {k: v for k, v in _row("OLD").items() if k != "vp"}):
        with open(p, "ab") as f:
            f.write((json.dumps(bad) + "\n").encode())
        before = p.read_bytes()
        with pytest.raises(rl.LedgerSchemaError):
            rl.append_rows(p, [_row("NEW", d="2027-02-01")])
        assert p.read_bytes() == before
        p.write_bytes(before.rsplit(b"\n", 2)[0] + b"\n")   # test scaffolding: drop the bad line again (not the module)


def test_a_new_row_with_another_schema_refuses_the_whole_batch(tmp_path):
    p = tmp_path / "l.jsonl"
    rl.append_rows(p, [_row("AAA")])
    before = p.read_bytes()
    for bad in ({**_row("BBB"), "extra": 1}, {k: v for k, v in _row("BBB").items() if k != "revision"},
                _row("BBB", reference_status="maybe"), _row("BBB", price=float("nan")), _row("BBB", price="10"),
                _row("BBB", price=float("inf")), _row("BBB", date="2027/01/04"), _row("BBB", revision=18.0),
                _row("BBB", verdict="buy"), _row("BBB", closure_asof="soon"), _row("BBB", price_date="soon"),
                _row("BBB", price=None, price_date="2027-01-04"),
                _row("BBB", verdict={"direction": "undervalued", "date": "2027-01-01", "median_iv": 13.0}),
                _row("BBB", verdict={**VERDICT, "extra": 1}), _row("BBB", verdict={**VERDICT, "base_iv": "13"}),
                _row("BBB", verdict={**VERDICT, "published_at": "yesterday"}),
                _row("BBB", verdict={**VERDICT, "pack_revision": 18.0}), _row("BBB", verdict={**VERDICT, "label": 3})):
        with pytest.raises(rl.LedgerSchemaError):
            rl.append_rows(p, [_row("GOOD", d="2027-02-01"), bad])      # the bad row is last: GOOD must not be written either
        assert p.read_bytes() == before


def test_two_rows_with_one_date_and_ticker_in_a_batch_refuse(tmp_path):
    p = tmp_path / "l.jsonl"
    with pytest.raises(rl.LedgerSchemaError):
        rl.append_rows(p, [_row("AAA"), _row("AAA")])
    assert not p.exists()


def test_a_corrupt_or_partial_ledger_is_refused_not_repaired(tmp_path):
    p = tmp_path / "l.jsonl"
    rl.append_rows(p, [_row("AAA")])
    good = p.read_bytes()
    for corrupt in (good + b"{not json}\n", good + good.rstrip(b"\n")[:40]):     # an invalid line; a partial last line
        p.write_bytes(corrupt)
        with pytest.raises(rl.LedgerSchemaError):
            rl.append_rows(p, [_row("BBB", d="2027-02-01")])
        assert p.read_bytes() == corrupt


def test_a_missing_ledger_is_created_with_its_directory(tmp_path):
    p = tmp_path / "cache" / "l.jsonl"
    assert rl.append_rows(p, [_row("AAA")]) == (1, 0)
    assert rl.append_rows(p, []) == (0, 0)


def test_the_default_ledger_is_in_cache_and_in_the_state_backup_set():
    import sync_state
    assert rl.DEFAULT_LEDGER == HERE / "cache" / "reference_ledger.jsonl"
    assert "reference_ledger.jsonl" in sync_state.STATE_FILES


# ---- status, price, zero ---------------------------------------------------------------------------------------------

def test_status_is_the_packs_rule():
    called = []

    def fence(side):
        def f():
            called.append(side)
            return side
        return f
    assert rl.classify_status(None, fence(None)) == "not_available"
    assert rl.classify_status(0.0, fence("above")) == "not_meaningful"
    assert rl.classify_status(-4.0, fence("above")) == "not_meaningful"
    assert rl.classify_status(0.004, fence("above")) == "not_meaningful"      # prints 0.00
    assert called == []                                                        # the fence is not evaluated for it
    assert rl.classify_status(0.005, fence(None)) == "used"
    assert rl.classify_status(50.0, fence("above")) == "outside_fence_above"
    assert rl.classify_status(1.0, fence("below")) == "outside_fence_below"
    assert rl.classify_status(10.0, fence(None)) == "used"


def test_snapshot_rows_values_and_zero_is_a_value(tmp_path):
    p = tmp_path / "l.jsonl"
    vals = {"USED": 12.0, "ABOVE": 40.0, "BELOW": 1.0, "ZERO": 0.0, "NEG": -3.0, "NONE": None, "NOPX": 12.0}
    s = rl.snapshot("2027-01-04", list(vals), set(), ledger_path=p, closure=CLOSURE, revision=18,
                    **_fakes(vals, prices={"NOPX": None}, sides={"ABOVE": "above", "BELOW": "below"},
                             verdicts={"USED": VERDICT}))
    rows = {r["ticker"]: r for r in rl.read_ledger(p)}
    assert s["rows_appended"] == 7 and s["no_price"] == 1 and s["errors"] == {}
    assert rows["USED"]["reference_status"] == "used" and rows["USED"]["vp"] == pytest.approx(1.2)
    assert rows["USED"]["verdict"] == VERDICT and rows["ABOVE"]["verdict"] is None
    assert rows["USED"]["price_date"] == "2027-01-02" and rows["NOPX"]["price_date"] is None
    assert rows["ABOVE"]["reference_status"] == "outside_fence_above" and rows["ABOVE"]["reference_value"] == 40.0
    assert rows["BELOW"]["reference_status"] == "outside_fence_below"
    assert rows["ZERO"]["reference_status"] == "not_meaningful" and rows["ZERO"]["reference_value"] == 0.0
    assert rows["ZERO"]["vp"] == 0.0
    assert rows["NEG"]["reference_status"] == "not_meaningful"
    assert rows["NONE"]["reference_status"] == "not_available" and rows["NONE"]["reference_value"] is None \
        and rows["NONE"]["vp"] is None
    assert rows["NOPX"]["price"] is None and rows["NOPX"]["vp"] is None and rows["NOPX"]["reference_value"] == 12.0
    for r in rows.values():
        assert r["coe"] == 0.09 and r["closure_erp"] == 0.05 and r["closure_asof"] == "2026-12-20" and r["revision"] == 18


def test_a_coe_of_zero_and_a_price_of_zero_are_values_not_absences(tmp_path):
    p = tmp_path / "l.jsonl"
    f = _fakes({"AAA": 5.0}, prices={"AAA": 0.0})
    f["inputs_fn"] = lambda t: {"v": 5.0, "coe": 0.0}
    rl.snapshot("2027-01-04", ["AAA"], set(), ledger_path=p, closure=CLOSURE, revision=18, **f)
    (r,) = rl.read_ledger(p)
    assert r["coe"] == 0.0 and r["price"] == 0.0 and r["vp"] is None     # no V/P at a zero price; the zero price is kept


def test_closure_fields_are_recorded_and_absent_when_there_is_no_closure(tmp_path):
    import datetime
    p = tmp_path / "l.jsonl"
    rl.snapshot("2027-01-04", ["AAA"], set(), ledger_path=p, closure=(0.0, datetime.date(2026, 12, 1), {}), revision=18,
                **_fakes({"AAA": 5.0}))
    rl.snapshot("2027-01-11", ["AAA"], set(), ledger_path=p, closure=None, revision=18, **_fakes({"AAA": 5.0}))
    rl.snapshot("2027-01-18", ["AAA"], set(), ledger_path=p, closure="no closure: artifact stale", revision=18,
                **_fakes({"AAA": 5.0}))
    a, b, c = rl.read_ledger(p)
    assert (a["closure_erp"], a["closure_asof"]) == (0.0, "2026-12-01")        # a premium of 0.0 is a value
    assert (b["closure_erp"], b["closure_asof"]) == (None, None)
    assert (c["closure_erp"], c["closure_asof"]) == (None, None)


def test_a_second_snapshot_on_one_date_adds_nothing(tmp_path):
    p = tmp_path / "l.jsonl"
    kw = dict(ledger_path=p, closure=CLOSURE, revision=18, **_fakes({"AAA": 5.0, "BBB": 6.0}))
    first = rl.snapshot("2027-01-04", ["AAA", "BBB"], set(), **kw)
    before = p.read_bytes()
    second = rl.snapshot("2027-01-04", ["AAA", "BBB"], set(), **kw)
    assert (first["rows_appended"], second["rows_appended"], second["skipped_existing"]) == (2, 0, 2)
    assert p.read_bytes() == before


# ---- the book, the untouched names, and what is never printed -------------------------------------------------------

def test_book_and_untouched_each_get_a_row_and_a_name_in_both_counts_once(tmp_path):
    p = tmp_path / "l.jsonl"
    vals = {t: 5.0 for t in ("BK1", "BK2", "UT1", "UT2", "BOTH")}
    s = rl.snapshot("2027-01-04", ["BK1", "bk2", "BOTH"], {"UT1", "ut2", "BOTH"}, ledger_path=p, closure=CLOSURE,
                    revision=18, **_fakes(vals))
    assert sorted(r["ticker"] for r in rl.read_ledger(p)) == ["BK1", "BK2", "BOTH", "UT1", "UT2"]
    assert (s["names_book"], s["names_untouched"], s["in_both_lists"], s["rows_appended"]) == (2, 3, 1, 5)
    assert s["status_counts"] == {"book": {"used": 2}, "untouched": {"used": 3}}


def test_a_failing_name_gets_no_row_is_counted_and_the_rest_are_written(tmp_path):
    p = tmp_path / "l.jsonl"
    vals = {"BK1": KeyError("BK1"), "BK2": 5.0, "UT1": ValueError("secret UT1 detail"), "UT2": 5.0}
    s = rl.snapshot("2027-01-04", ["BK1", "BK2"], {"UT1", "UT2"}, ledger_path=p, closure=CLOSURE, revision=18, **_fakes(vals))
    assert sorted(r["ticker"] for r in rl.read_ledger(p)) == ["BK2", "UT2"]
    assert s["errors"] == {"KeyError": 1, "ValueError": 1}
    text = json.dumps(s)
    assert "UT1" not in text and "UT2" not in text            # no untouched name, and no message of theirs, in the report
    assert any(x.startswith("BK1:") for x in s["error_samples_book_only"])


def test_the_summary_never_contains_a_ticker_on_a_clean_run(tmp_path):
    vals = {"ZQXA": 5.0, "ZQXB": 5.0, "ZQXU": 5.0}
    s = rl.snapshot("2027-01-04", ["ZQXA", "ZQXB"], {"ZQXU"}, ledger_path=tmp_path / "l.jsonl", closure=CLOSURE, revision=18,
                    **_fakes(vals))
    assert "ZQX" not in json.dumps(s)


def test_the_untouched_list_is_read_from_the_configured_path_and_checked(tmp_path, monkeypatch):
    f = tmp_path / "list.txt"
    f.write_text("# header\naaa\n\nBBB \nccc\n", encoding="utf-8")
    monkeypatch.delenv(rl.UNTOUCHED_ENV, raising=False)
    assert rl.load_untouched(f) == {"AAA", "BBB", "CCC"}
    monkeypatch.setenv(rl.UNTOUCHED_ENV, str(f))
    assert rl.load_untouched() == {"AAA", "BBB", "CCC"}
    import hashlib
    ok = hashlib.sha256(f.read_bytes()).hexdigest()
    assert rl.load_untouched(f, ok.upper()) == {"AAA", "BBB", "CCC"}
    with pytest.raises(ValueError) as e:
        rl.load_untouched(f, "0" * 64)
    assert "AAA" not in str(e.value)
    monkeypatch.delenv(rl.UNTOUCHED_ENV)
    with pytest.raises(FileNotFoundError):
        rl.load_untouched()                                    # never a default path
    with pytest.raises(FileNotFoundError):
        rl.load_untouched(tmp_path / "nope.txt")


# ---- offline and the CLI ---------------------------------------------------------------------------------------------

def test_block_network_makes_a_socket_raise(monkeypatch):
    for attr in ("socket", "getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, attr, getattr(socket, attr))        # restored after the test
    rl.block_network()
    with pytest.raises(RuntimeError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(RuntimeError):
        socket.getaddrinfo("localhost", 80)


def _wiring(vals, book):
    w = _fakes(vals)
    w.update(closure=CLOSURE, revision=18, book=list(book))
    return lambda data_root: dict(w, book=list(book))


def test_cli_writes_a_snapshot_and_prints_counts_only(tmp_path, monkeypatch, capsys):
    lst = tmp_path / "ut.txt"
    lst.write_text("ZQXU\n", encoding="utf-8")
    led = tmp_path / "l.jsonl"
    monkeypatch.setattr(rl, "block_network", lambda: None)
    monkeypatch.setattr(rl, "production_adapters", _wiring({"ZQXA": 5.0, "ZQXU": 5.0}, ["ZQXA"]))
    rc = rl.main(["--snapshot", "--untouched-list", str(lst), "--ledger", str(led)])
    out = capsys.readouterr()
    assert rc == 0 and "ZQX" not in out.out and "ZQX" not in out.err
    assert json.loads(out.out)["rows_appended"] == 2 and len(rl.read_ledger(led)) == 2


def test_cli_exits_nonzero_when_a_name_fails_and_refuses_without_the_list(tmp_path, monkeypatch, capsys):
    lst = tmp_path / "ut.txt"
    lst.write_text("ZQXU\n", encoding="utf-8")
    led = tmp_path / "l.jsonl"
    monkeypatch.setattr(rl, "block_network", lambda: None)
    monkeypatch.setattr(rl, "production_adapters", _wiring({"ZQXA": KeyError("x"), "ZQXU": 5.0}, ["ZQXA"]))
    assert rl.main(["--snapshot", "--untouched-list", str(lst), "--ledger", str(led)]) == 1
    capsys.readouterr()
    monkeypatch.delenv(rl.UNTOUCHED_ENV, raising=False)
    assert rl.main(["--snapshot", "--ledger", str(led)]) == 2
    assert "not configured" in capsys.readouterr().err


def test_cli_refuses_a_ledger_with_another_schema_without_writing(tmp_path, monkeypatch, capsys):
    lst = tmp_path / "ut.txt"
    lst.write_text("ZQXU\n", encoding="utf-8")
    led = tmp_path / "l.jsonl"
    led.write_bytes(b'{"date":"2027-01-04","ticker":"OLD"}\n')
    before = led.read_bytes()
    monkeypatch.setattr(rl, "block_network", lambda: None)
    monkeypatch.setattr(rl, "production_adapters", _wiring({"ZQXA": 5.0, "ZQXU": 5.0}, ["ZQXA"]))
    assert rl.main(["--snapshot", "--untouched-list", str(lst), "--ledger", str(led)]) == 2
    assert led.read_bytes() == before
    assert "schema mismatch" in capsys.readouterr().err


# ---- the runs file: one summary line per snapshot, counts by reason, no names ---------------------------------------------

def test_one_summary_line_per_snapshot_goes_to_the_append_only_runs_file_with_counts_and_no_names(tmp_path):
    p = tmp_path / "l.jsonl"
    runs = tmp_path / rl.RUNS_NAME
    vals = {"ZQXA": KeyError("ZQXA"), "ZQXB": 5.0, "ZQXU": ValueError("secret ZQXU detail"), "ZQXV": 5.0, "ZQXW": 5.0}
    s = rl.snapshot("2027-01-04", ["ZQXA", "ZQXB"], {"ZQXU", "ZQXV", "ZQXW"}, ledger_path=p, closure=CLOSURE, revision=18,
                    **_fakes(vals, prices={"ZQXW": None}))
    first = runs.read_bytes()
    lines = first.splitlines()
    assert len(lines) == 1 and first.endswith(b"\n")
    line = json.loads(lines[0])
    assert line == {"date": "2027-01-04", "revision": 18, "names": 5, "rows_appended": 3, "skipped_existing": 0, "no_price": 1,
                    "closure_erp_recorded": True, "status_counts": {"used": 3}, "failed_by_reason": {"KeyError": 1, "ValueError": 1},
                    "failed": 2}
    assert b"ZQX" not in first and "book" not in first.decode() and "untouched" not in first.decode()
    # a second snapshot appends a second line and leaves the first byte for byte
    rl.snapshot("2027-01-11", ["ZQXB"], set(), ledger_path=p, closure=CLOSURE, revision=18, **_fakes(vals))
    both = runs.read_bytes()
    assert both.startswith(first) and len(both.splitlines()) == 2
    assert s["errors"] == {"KeyError": 1, "ValueError": 1}


def test_the_runs_file_lives_next_to_the_ledger_unless_named(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    kw = dict(closure=CLOSURE, revision=18, **_fakes({"AAA": 5.0}))
    rl.snapshot("2027-01-04", ["AAA"], set(), ledger_path=tmp_path / "a" / "l.jsonl", **kw)
    assert (tmp_path / "a" / rl.RUNS_NAME).exists()
    rl.snapshot("2027-01-04", ["AAA"], set(), ledger_path=tmp_path / "b" / "l.jsonl", runs_path=tmp_path / "elsewhere.jsonl", **kw)
    assert (tmp_path / "elsewhere.jsonl").exists() and not (tmp_path / "b" / rl.RUNS_NAME).exists()
    assert rl.DEFAULT_LEDGER.parent == rl.HERE / "cache"

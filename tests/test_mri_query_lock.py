"""_mri_query and a locked MRI store: retry, then raise MriStoreLocked; never a silent [] for a lock."""
import subprocess
import sys
import time

import duckdb
import pytest

import rs2_data


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = tmp_path / "mri.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.execute("INSERT INTO t VALUES (7)")
    con.close()
    monkeypatch.setattr(rs2_data, "mri_duckdb_path", lambda: path)
    return path


def test_reads_normally(store):
    assert rs2_data._mri_query("SELECT x FROM t") == [(7,)]


def test_a_bad_query_is_still_an_absent_input(store):
    assert rs2_data._mri_query("SELECT nope FROM missing_table") == []


def test_a_lock_is_retried_then_read(store, monkeypatch):
    real = duckdb.connect
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise duckdb.IOException("IO Error: Cannot open file: The process cannot access the file because it is "
                                     "being used by another process.")
        return real(*a, **k)

    monkeypatch.setattr(duckdb, "connect", flaky)
    waits = []
    assert rs2_data._mri_query("SELECT x FROM t", _sleep=waits.append) == [(7,)]
    assert waits == [rs2_data._MRI_LOCK_WAIT_S] * 2


def test_a_lock_that_outlasts_the_retries_raises(store, monkeypatch):
    def locked(*a, **k):
        raise duckdb.IOException("IO Error: Could not set lock on file")

    monkeypatch.setattr(duckdb, "connect", locked)
    waits = []
    with pytest.raises(rs2_data.MriStoreLocked):
        rs2_data._mri_query("SELECT x FROM t", _sleep=waits.append)
    assert len(waits) == rs2_data._MRI_LOCK_RETRIES


def test_a_real_writer_in_another_process_is_seen_as_a_lock(store, monkeypatch):
    holder = subprocess.Popen([sys.executable, "-c",
                               f"import duckdb,time; c=duckdb.connect(r'{store}'); print('held', flush=True); time.sleep(20)"],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setattr(rs2_data, "_MRI_LOCK_RETRIES", 1)
        t0 = time.monotonic()
        with pytest.raises(rs2_data.MriStoreLocked):
            rs2_data._mri_query("SELECT x FROM t", _sleep=lambda s: None)
        assert time.monotonic() - t0 < 10
    finally:
        holder.kill()
        holder.wait()

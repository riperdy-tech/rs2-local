"""tests/test_reference_ledger_sync.py - revision 18 brief section 5.3: the forward ledger is in rs2-state's backup set.

sync_state resolves the state clone through paths.py (no hardcoded path); the ledger rides STATE_FILES like every other state
file. Same harness as tests/test_sync_state.py (a local bare repository and a clone of it)."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import reference_ledger as rl  # noqa: E402
import sync_state  # noqa: E402
from test_sync_state import _make_repos  # noqa: E402


def _row(t, d):
    return {"date": d, "ticker": t, "price": 10.0, "reference_value": 12.0, "reference_status": "used", "vp": 1.2, "coe": 0.09,
            "closure_erp": 0.05, "closure_asof": "2026-12-20", "revision": 18, "verdict": None}


def test_the_ledger_is_backed_up_byte_for_byte_and_each_sync_carries_the_appended_lines(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    ledger = cache / "reference_ledger.jsonl"
    monkeypatch.setattr(sync_state, "CACHE", cache)
    rl.append_rows(ledger, [_row("ZQA", "2027-01-04"), _row("ZQB", "2027-01-04")])
    assert "synced" in sync_state.main(repo_dir=clone)
    backup = clone / "cache" / "reference_ledger.jsonl"
    assert backup.read_bytes() == ledger.read_bytes()
    first = ledger.read_bytes()
    rl.append_rows(ledger, [_row("ZQA", "2027-01-11")])
    assert "synced" in sync_state.main(repo_dir=clone)
    assert backup.read_bytes() == ledger.read_bytes() and backup.read_bytes().startswith(first)
    tracked = subprocess.run(["git", "-C", str(clone), "ls-files"], capture_output=True, text=True, check=True).stdout
    assert "cache/reference_ledger.jsonl" in tracked


def test_a_missing_ledger_is_not_an_error_for_the_sync(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    assert "synced" in sync_state.main(repo_dir=clone)
    assert not (clone / "cache" / "reference_ledger.jsonl").exists()

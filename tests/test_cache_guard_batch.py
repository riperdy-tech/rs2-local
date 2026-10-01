"""The suite's guard of the closure's raw consensus batch (cache/closure_enrich/<vintage>/, revision 18).

The per-test cache guard (conftest.py) skips that subtree - it holds ~1,700 files and statting them twice per test made the suite
many times slower - so a session-level guard checks every vintage against its manifest.json (the file list and each file's
sha256, and the manifest's own hash) at the start and the end of the session. A test that alters a batch file must still fail."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("rs2_root_conftest", ROOT / "conftest.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _vintage(cache, names=("AAA", "BBB", "CCC"), vintage="2026-10-01", manifest=True):
    d = cache / "closure_enrich" / vintage
    d.mkdir(parents=True)
    files = {}
    for n in names:
        p = d / f"{n}.json"
        p.write_text(json.dumps({"_ticker": n, "estimates": {"0y": {}}}), encoding="utf-8")
        files[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    if manifest:
        (d / "manifest.json").write_text(json.dumps({
            "vintage": vintage, "file_sha256": files,
            "manifest_sha256": hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode()).hexdigest()}),
            encoding="utf-8")
    return d


def test_a_clean_vintage_passes_and_an_absent_batch_root_passes(tmp_path):
    assert guard.verify_batch_vintages(tmp_path) == []
    _vintage(tmp_path)
    assert guard.verify_batch_vintages(tmp_path) == []
    # a subfolder (a failed attempt moved aside) and non-record files are not part of the vintage
    aside = tmp_path / "closure_enrich" / "2026-10-01" / "_attempt1_broken_session"
    aside.mkdir()
    (aside / "ZZZ.json").write_text("{}", encoding="utf-8")
    assert guard.verify_batch_vintages(tmp_path) == []


def test_every_way_of_altering_a_batch_is_found(tmp_path):
    d = _vintage(tmp_path)
    (d / "AAA.json").write_text("{}", encoding="utf-8")                        # altered
    (d / "DDD.json").write_text("{}", encoding="utf-8")                        # added
    (d / "CCC.json").unlink()                                                  # removed (a fixture of this test's own)
    problems = guard.verify_batch_vintages(tmp_path)
    assert any("AAA.json differs from its manifest sha256" in p for p in problems)
    assert any("DDD.json is not in the manifest" in p for p in problems)
    assert any("CCC.json is in the manifest but missing" in p for p in problems)
    # a doctored manifest is found by its own hash; a vintage with records and no manifest, and an unreadable manifest, too
    d2 = _vintage(tmp_path, vintage="2026-11-01")
    man = json.loads((d2 / "manifest.json").read_text(encoding="utf-8"))
    man["file_sha256"]["AAA.json"] = "0" * 64
    (d2 / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert any("2026-11-01" in p and "differs" in p for p in guard.verify_batch_vintages(tmp_path))
    man["manifest_sha256"] = "x"
    (d2 / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert any("own hash" in p for p in guard.verify_batch_vintages(tmp_path))
    _vintage(tmp_path, vintage="2026-12-01", manifest=False)
    assert any("2026-12-01: records but no manifest.json" in p for p in guard.verify_batch_vintages(tmp_path))
    (tmp_path / "closure_enrich" / "2026-12-01" / "manifest.json").write_text("{", encoding="utf-8")
    assert any("2026-12-01: manifest.json is unreadable" in p for p in guard.verify_batch_vintages(tmp_path))


def test_a_test_that_alters_a_batch_file_fails_the_session_and_a_clean_session_passes(tmp_path):
    """End to end, in a throwaway project: the session-guard part of the real conftest.py (its header, the manifest check and the
    session fixture; the per-test fixtures that patch other modules are cut off, a throwaway project has none of those)."""
    text = (ROOT / "conftest.py").read_text(encoding="utf-8")
    cut = text.index("@pytest.fixture(autouse=True)" + chr(10) + "def _cache_must_stay_untouched")
    (tmp_path / "conftest.py").write_text(text[:cut], encoding="utf-8")
    d = _vintage(tmp_path / "cache")
    clean = tmp_path / "test_clean.py"
    clean.write_text("def test_nothing_touches_the_batch():\n    assert True\n", encoding="utf-8")
    env_args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), str(clean)]
    ok = subprocess.run(env_args, cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    clean.unlink()
    bad = tmp_path / "test_bad.py"
    bad.write_text(f"def test_alters_a_batch_file():\n    open(r'{d / 'AAA.json'}', 'a').write(' ')\n", encoding="utf-8")
    res = subprocess.run(env_args[:-1] + [str(bad)], cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode != 0
    assert "AAA.json differs from its manifest sha256" in res.stdout + res.stderr
    # and one that already starts altered fails before it runs
    res2 = subprocess.run(env_args[:-1] + [str(bad)], cwd=tmp_path, capture_output=True, text=True)
    assert res2.returncode != 0 and "does not match its manifest at session start" in res2.stdout + res2.stderr

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


# ---- the whole subtree: subfolders and the root of the batch folder (revision 18 follow-up, finding 7) ----------------------------------
# The manifest check reads only the *.json files directly inside each vintage folder (and says subfolders are not part of the vintage), so
# a test that wrote into `_attempt1_broken_session/`, or left a file at the root of cache/closure_enrich, passed the session guard.

def _tree_with_extras(cache):
    d = _vintage(cache)
    aside = d / "_attempt1_broken_session"
    aside.mkdir()
    (aside / "ZZZ.json").write_text("{}", encoding="utf-8")
    (aside / "deeper").mkdir()
    (aside / "deeper" / "note.txt").write_text("x", encoding="utf-8")
    (cache / "closure_enrich" / "names.txt").write_text("AAA\n", encoding="utf-8")        # a file at the root of the batch folder
    return d, aside


def test_the_tree_listing_covers_files_and_folders_at_every_depth_and_an_absent_root_is_empty(tmp_path):
    assert guard.closure_enrich_tree(tmp_path) == {}
    d, aside = _tree_with_extras(tmp_path)
    listing = guard.closure_enrich_tree(tmp_path)
    for rel in ("names.txt", "2026-10-01/AAA.json", "2026-10-01/manifest.json", "2026-10-01/_attempt1_broken_session/ZZZ.json",
                "2026-10-01/_attempt1_broken_session/deeper/note.txt", "2026-10-01/", "2026-10-01/_attempt1_broken_session/",
                "2026-10-01/_attempt1_broken_session/deeper/"):
        assert rel in listing, rel
    assert guard.compare_closure_enrich_tree(listing, guard.closure_enrich_tree(tmp_path)) == []


def test_every_way_of_altering_the_subtree_is_found_including_subfolders_and_the_root_file(tmp_path):
    d, aside = _tree_with_extras(tmp_path)
    before = guard.closure_enrich_tree(tmp_path)
    assert guard.verify_batch_vintages(tmp_path) == []                        # the manifest check is blind to all of these
    (aside / "ZZZ.json").write_text('{"changed": true}', encoding="utf-8")        # a subfolder file changed
    (aside / "NEW.json").write_text("{}", encoding="utf-8")                       # a subfolder file added
    (aside / "deeper" / "note.txt").unlink()                                      # a deeper file removed
    (tmp_path / "closure_enrich" / "names.txt").write_text("AAA\nBBB\n", encoding="utf-8")   # the root file changed
    (tmp_path / "closure_enrich" / "stray.csv").write_text("x", encoding="utf-8")            # a root file added
    (aside / "newdir").mkdir()                                                    # a folder added
    problems = guard.compare_closure_enrich_tree(before, guard.closure_enrich_tree(tmp_path))
    assert guard.verify_batch_vintages(tmp_path) == []
    for expect in ("_attempt1_broken_session/ZZZ.json was changed", "_attempt1_broken_session/NEW.json was added",
                   "_attempt1_broken_session/deeper/note.txt was removed", "names.txt was changed", "stray.csv was added",
                   "_attempt1_broken_session/newdir/ was added"):
        assert any(expect in p for p in problems), (expect, problems)
    # and deleting a whole folder or the root file is found
    before2 = guard.closure_enrich_tree(tmp_path)
    (tmp_path / "closure_enrich" / "names.txt").unlink()
    assert guard.compare_closure_enrich_tree(before2, guard.closure_enrich_tree(tmp_path)) == ["names.txt was removed"]


@pytest.mark.parametrize("target,expect", [
    ("2026-10-01/_attempt1_broken_session/ZZZ.json", "_attempt1_broken_session/ZZZ.json was changed"),
    ("2026-10-01/_attempt1_broken_session/NEW.json", "_attempt1_broken_session/NEW.json was added"),
    ("names.txt", "names.txt was changed"),
    ("stray.csv", "stray.csv was added"),
])
def test_a_test_that_writes_below_the_vintage_json_files_fails_the_session(tmp_path, target, expect):
    """End to end, as the session-guard test above: the same cut of the real conftest.py, and a test that touches only a subfolder or the
    root of the batch folder - paths the manifest check cannot see."""
    text = (ROOT / "conftest.py").read_text(encoding="utf-8")
    cut = text.index("@pytest.fixture(autouse=True)" + chr(10) + "def _cache_must_stay_untouched")
    (tmp_path / "conftest.py").write_text(text[:cut], encoding="utf-8")
    _tree_with_extras(tmp_path / "cache")
    base = tmp_path / "cache" / "closure_enrich"
    clean = tmp_path / "test_clean.py"
    clean.write_text("def test_nothing_touches_the_batch():\n    assert True\n", encoding="utf-8")
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path)]
    ok = subprocess.run(args + [str(clean)], cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr                                     # extras that already exist are not a failure
    clean.unlink()
    bad = tmp_path / "test_bad.py"
    bad.write_text(f"def test_writes_below_the_records():\n    open(r'{base / target}', 'a').write('x')\n", encoding="utf-8")
    res = subprocess.run(args + [str(bad)], cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode != 0 and "a test altered cache/closure_enrich" in res.stdout + res.stderr
    assert expect in res.stdout + res.stderr

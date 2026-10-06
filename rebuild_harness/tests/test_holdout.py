import json
import subprocess
from pathlib import Path

import pytest

from rebuild_harness import holdout


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


class FakeEngine:
    def __init__(self, name, files):
        self.engine_name, self.frozen_files = name, files

    def __call__(self, *a, **k):
        return {}


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "eng.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (r / "helper.py").write_text("X = 1\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "engine")
    return r


def test_window_classification():
    assert holdout.classify("2017-01-01") == "development" and holdout.classify("2022-12-31") == "development"
    assert holdout.classify("2023-01-01") == "holdout" and holdout.classify("2024-12-31") == "holdout"
    assert holdout.classify("2016-06-30") == "outside_development_and_holdout" and holdout.classify("2025-10-31") == "outside_development_and_holdout"
    assert holdout.touches_holdout(["2022-12-30", "2023-06-30", "2024-01-02"]) == ["2023-06-30", "2024-01-02"]


def test_development_dates_need_no_freeze(repo):
    e = FakeEngine("e", [repo / "eng.py"])
    info = holdout.enforce(["2017-06-30", "2022-06-30"], [e], None)
    assert info["holdout_dates"] == [] and info["frozen"] == {}


def test_a_holdout_date_without_a_freeze_file_is_refused(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py"])
    with pytest.raises(holdout.HoldoutRefused, match="no freeze file"):
        holdout.enforce(["2018-06-30", "2023-06-30"], [e], None)
    with pytest.raises(holdout.HoldoutRefused, match="no freeze file"):
        holdout.enforce(["2023-06-30"], [e], tmp_path / "missing.json")


def test_a_frozen_engine_passes_and_the_run_is_recorded_once(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py", repo / "helper.py"])
    fz = tmp_path / "freeze.json"
    holdout.write_freeze(fz, [e], repo=repo)
    info = holdout.enforce(["2023-06-30", "2024-06-28"], [e], fz, repo=repo)
    assert info["frozen"]["e"] == git(repo, "rev-parse", "HEAD")
    with pytest.raises(holdout.HoldoutRefused, match="run once"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo)
    holdout.enforce(["2023-06-30"], [e], fz, repo=repo, allow_rerun=True)


def test_an_engine_edited_after_the_freeze_is_refused(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    holdout.write_freeze(fz, [e], repo=repo)
    (repo / "eng.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="changed after the freeze"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo)


def test_a_commit_that_does_not_hold_the_file_is_refused(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    doc = holdout.write_freeze(fz, [e], repo=repo)
    # the working file is changed AND the freeze re-hashed to match, but the named commit still holds the old content
    (repo / "eng.py").write_text("def f():\n    return 3\n", encoding="utf-8")
    doc["engines"]["e"]["files"]["eng.py"] = holdout.sha256_file(repo / "eng.py")
    fz.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="does not hold the frozen file"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo)


def test_a_commit_that_is_not_an_ancestor_of_head_is_refused(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    doc = holdout.write_freeze(fz, [e], repo=repo)
    doc["engines"]["e"]["git_commit"] = "0" * 40
    fz.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="not an ancestor"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo)


def test_an_engine_missing_from_the_freeze_or_with_an_unlisted_file_is_refused(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py"])
    other = FakeEngine("other", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    holdout.write_freeze(fz, [e], repo=repo)
    with pytest.raises(holdout.HoldoutRefused, match="does not name engine 'other'"):
        holdout.enforce(["2023-06-30"], [e, other], fz, repo=repo)
    wider = FakeEngine("e", [repo / "eng.py", repo / "helper.py"])
    with pytest.raises(holdout.HoldoutRefused, match="does not list helper.py"):
        holdout.enforce(["2023-06-30"], [wider], fz, repo=repo)


def test_an_engine_with_no_declared_files_cannot_be_frozen(repo, tmp_path):
    e = FakeEngine("e", [])
    with pytest.raises(holdout.HoldoutRefused, match="no frozen_files"):
        holdout.write_freeze(tmp_path / "f.json", [e], repo=repo)


def test_a_refusal_happens_before_any_data_is_opened(tmp_path):
    """run_harness.run calls the lock first: a holdout date with no freeze raises before the data root is touched."""
    from rebuild_harness import engines, run_harness

    class Boom:
        price_source = None

        def __getattr__(self, name):
            raise AssertionError("the data layer was touched before the lock answered")

    with pytest.raises(holdout.HoldoutRefused):
        run_harness.run(["2023-06-30"], ["1"], [engines.earnings_yield], Boom(), tmp_path / "out")
    assert not (tmp_path / "out").exists()

import pytest

from backtest_phase2.tests import helpers
from backtest_phase2 import calibration_s1


@pytest.fixture(scope="session")
def trees(tmp_path_factory):
    """The two revisions' tools/ directories, extracted from git (fee17cf and ac68e25), byte for byte."""
    root = tmp_path_factory.mktemp("trees")
    return {"baseline": helpers.extract_tools(helpers.BASELINE_REV, root / "b"),
            "candidate": helpers.extract_tools(helpers.CANDIDATE_REV, root / "c")}


@pytest.fixture(scope="session")
def s1_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("cal") / "s1_calibration.json"
    calibration_s1.write(p)
    return str(p)


@pytest.fixture
def run(trees, tmp_path, s1_file):
    """run(arm, job) -> the worker's result dict; the candidate gets the s1 calibration unless the job names another."""
    def _run(arm, job):
        job = dict(job)
        if arm == "candidate" and "calibration" not in job:
            job["calibration"] = s1_file
        return helpers.run_worker(arm, trees[arm], job, tmp_path)
    return _run

"""Test plumbing: no network at all (urlopen and sockets fail loudly), the module on the path, fixtures and a fresh monitor root per test.

The monitor resolves its folders through tools/paper_books/book_paths.py when it is imported, so a throwaway rs2-state is pointed at here,
before any test module imports it. It holds a SYNTHETIC operator exclusion list (OPXA..OPXD; the real one is data in rs2-state and never in
this public repository) and byte copies of the frozen PREREG files from the real rs2-state (baseline_b checks the PREREG_m3n sha256;
a test compares the Q1 event map with PREREG_m3o). Same set-up as tools/paper_books/tests/conftest.py.
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path

import pytest

HM = Path(__file__).resolve().parents[1]                     # tools/holdings_monitor
sys.path.insert(0, str(HM))
sys.path.insert(0, str(HM.parent / "paper_books"))
sys.path.insert(0, str(HM.parents[1]))                       # the repo root (paths.py)
import paths  # noqa: E402

FIX = HM / "tests" / "fixtures"
SYNTHETIC_EXCLUDED = ["OPXA", "OPXB", "OPXC", "OPXD"]

_real_prereg = paths.resolve("rs2_state_dir") / "paper_books" / "prereg"
_tmp = Path(tempfile.mkdtemp(prefix="holdings_monitor_tests_"))
(_tmp / "rs2-state" / "paper_books" / "prereg").mkdir(parents=True)
for _name in ("PREREG_m3o.json", "PREREG_m3n.json"):
    shutil.copyfile(_real_prereg / _name, _tmp / "rs2-state" / "paper_books" / "prereg" / _name)
(_tmp / "rs2-state" / "paper_books" / "operator_excluded.json").write_text(json.dumps({"tickers": SYNTHETIC_EXCLUDED}), encoding="utf-8")
(_tmp / "gh_witness_archive").mkdir()
(_tmp / "screener-publish").mkdir()
_ENV = {"RS2_STATE_DIR": str(_tmp / "rs2-state"), "RS2_GH_WITNESS_DIR": str(_tmp / "gh_witness_archive"),
        "SCREENER_PUBLISH_REPO": str(_tmp / "screener-publish")}
_saved = {k: os.environ.get(k) for k in _ENV}
os.environ.update(_ENV)


def pytest_collection_finish(session):
    """The modules have resolved their folders at import; put the environment back so other suites see the real one."""
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test tried to use the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)


@pytest.fixture
def state_env():
    """The throwaway rs2-state environment, for a test that starts a subprocess importing the monitor."""
    return dict(_ENV)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "m3p"


@pytest.fixture
def fixture_json():
    return lambda name: json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixture_text():
    return lambda name: (FIX / name).read_text(encoding="utf-8")

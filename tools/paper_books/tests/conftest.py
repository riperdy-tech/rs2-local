"""Test setup for tools/paper_books: the modules resolve their folders through paths.py when they are imported, so a throwaway
rs2-state, witness archive and screener clone are pointed at here, before any test module imports them.

The throwaway rs2-state holds a SYNTHETIC operator exclusion list (OPXA..OPXD; the real one is data in rs2-state and never in this
public repository) and byte copies of the three frozen PREREG files from the real rs2-state (baseline_b checks the PREREG_m3n sha256).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                  # tools/paper_books
sys.path.insert(0, str(HERE.parents[2]))              # the repo root (paths.py)
import paths  # noqa: E402

SYNTHETIC_EXCLUDED = ["OPXA", "OPXB", "OPXC", "OPXD"]

_real_prereg = paths.resolve("rs2_state_dir") / "paper_books" / "prereg"
_tmp = Path(tempfile.mkdtemp(prefix="paper_books_tests_"))
(_tmp / "rs2-state" / "paper_books" / "prereg").mkdir(parents=True)
for name in ("PREREG_m3o.json", "PREREG_m3n.json", "PREREG_m3o_bookD.json"):
    shutil.copyfile(_real_prereg / name, _tmp / "rs2-state" / "paper_books" / "prereg" / name)
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

"""Group B decoupling: live code must stop importing the retired v2.0 generation.

WHY THIS FILE EXISTS. Retiring a module while a live module still imports it breaks the live
system silently. That already happened once: `valuation_engine.py` was on the hand-written
Group B list, but live `valuation_backbone.py:27` imports it for `dcf_value`. Archiving it broke
`consensus_valuation -> valuation_backbone -> valuation_engine` and took 7 tests with it. A
second one was worse because it was invisible: `rs2_data.py` imports `outcome_feedback` inside a
`try/except` that returns `""`, so archiving it produced no error at all - just a silently
empty calibration feed.

So these are structural tests, and one of them is a permanent census so the next retirement
cannot repeat either mistake.

IMPORT-GRAPH REASONS (they encode why each decoupling is safe):
  * `run_rs2.resolve_name` is a one-line passthrough to `rs2_data.resolve_name` (run_rs2.py:2029
    -> 2034), so `rebuild_briefs` can call the real owner directly with identical behaviour.
  * `rs2_data._track_record` is reachable only from `rs2_data.build_data_context`, which the
    live depth pipeline never calls - only `run_rs2.py:2434` does. It is Group B code living in a
    live file, and its `outcome_feedback` dependency is Group A.
"""
import ast
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[3]          # repo root
ARCHIVE = HERE / "_archive" / "retired_20260920"

# Directories that hold no live code. Pruned rather than filtered, so the walk does not descend
# into a search index or a virtualenv at all.
SKIP_DIRS = {"__pycache__", ".git", ".worktrees", ".pytest_cache", ".ruff_cache", ".claude",
             "_archive", "_quarantine", "scratch", "searxng", "research-venv", "node_modules"}


def _imports(path):
    """Top-level module names imported by this file's AST. Comments and docstrings excluded."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _live_py():
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield Path(root) / f


# ---- the two decouplings ---------------------------------------------------------------

def test_rebuild_briefs_no_longer_imports_run_rs2():
    assert "run_rs2" not in _imports(HERE / "rebuild_briefs.py")


def test_rebuild_briefs_resolves_names_through_rs2_data():
    src = (HERE / "rebuild_briefs.py").read_text(encoding="utf-8")
    assert "rs2_data.resolve_name" in src
    assert "run_rs2.resolve_name" not in src


def test_rs2_data_no_longer_imports_outcome_feedback():
    assert "outcome_feedback" not in _imports(HERE / "rs2_data.py")


def test_the_calibration_call_site_is_gone_too():
    # Removing the import while leaving the call would be a NameError on every prompt build.
    # Checked in the AST, not by a text scan: a text scan is the wrong instrument here, because
    # a docstring recording WHY the feed was dropped is legitimate - the same lesson
    # test_charter_single_source.py records for RS2.txt.
    tree = ast.parse((HERE / "rs2_data.py").read_text(encoding="utf-8", errors="replace"))
    called = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_track_record" not in called


# ---- the permanent census --------------------------------------------------------------

def test_no_live_module_imports_an_archived_module():
    """The guard that makes the next retirement safe.

    For every module sitting in the archive, no live file may import it. Reports the offending
    live files rather than a bare assertion, because the useful output is WHO still depends on
    what - the opposite of the hand-written list that failed before.
    """
    if not ARCHIVE.exists():
        pytest.skip("no archive in this checkout")
    archived = {p.stem for p in ARCHIVE.rglob("*.py") if p.is_file()}
    assert archived, "archive holds no .py files - the census would be vacuous"

    offenders = []
    for path in _live_py():
        if path.stem in archived:
            continue                       # the module itself, if it was restored
        hit = _imports(path) & archived
        if hit:
            offenders.append(f"{path.relative_to(HERE)} imports {sorted(hit)}")
    assert not offenders, (
        "live modules still import archived modules - retiring these would break the live "
        "system:\n  " + "\n  ".join(sorted(offenders)))

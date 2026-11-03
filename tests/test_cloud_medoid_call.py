"""The cloud arm's medoid call (Phase 6 blocker found in the Phase 4 window review, 2026-09-26).

`select_medoid_scorecard(runs, price, eff_tol)` was called as `(runs, med, price)`: the median went
in as the price and the price as the tolerance, so every cloud run "converged" and the fiduciary
checks judged the contract against the median instead of the market. The call now passes
everything after `runs` by keyword; this pins that for every caller outside the owner module.
The cloud arm itself (api_llm/) was archived on 2026-11-03.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name == "select_medoid_scorecard":
                yield node


def test_every_caller_outside_the_owner_passes_only_runs_positionally():
    owner = ROOT / "tools" / "audit_202608" / "consensus_valuation.py"
    code = [*ROOT.glob("*.py"), *(ROOT / "tools").rglob("*.py")]
    for path in code:
        if path == owner or "tests" in path.parts:
            continue
        if "select_medoid_scorecard" not in path.read_text(encoding="utf-8", errors="replace"):
            continue
        for call in _calls(path):
            assert len(call.args) <= 1, f"{path}: pass price/eff_tol by keyword"

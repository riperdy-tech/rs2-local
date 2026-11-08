"""Test setup for tools/archival_street: the folder's modules, J2's and K2's, and the repository root on sys.path. Every test is synthetic."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parent, HERE.parents[1] / "archival_j2", HERE.parents[1] / "archival_k2", HERE.parents[1] / "paper_books", HERE.parents[2]):
    sys.path.insert(0, str(p))

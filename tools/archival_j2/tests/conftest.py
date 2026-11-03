"""Test setup for tools/archival_j2: the folder's modules and the repository root (qwen_c, paths.py) on sys.path. Every test is synthetic."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                  # tools/archival_j2
sys.path.insert(0, str(HERE.parents[2]))              # the repo root

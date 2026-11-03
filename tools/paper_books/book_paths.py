"""Where the paper books and their inputs live, resolved through paths.py (no absolute or sibling path in this folder).

    books()              <rs2_state_dir>/paper_books        the books (data; private repo rs2-state)
    witness_archive()    paths.py gh_witness_dir            the GitHub run archive (raw logs; not in git)
    screener_repo()      paths.py screener_publish_repo     git objects of the screener's output commits (the dedicated clone)
    prereg(name)         <books>/prereg/<name>              frozen PREREG copies (they name tickers, so they stay off this public repo)
    operator_excluded()  <books>/operator_excluded.json     the operator's exclusions (data, never code); missing -> exit
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the rs2-local repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import paths  # noqa: E402


def books():
    return paths.resolve("rs2_state_dir") / "paper_books"


def witness_archive():
    return paths.resolve("gh_witness_dir")


def screener_repo():
    return paths.resolve("screener_publish_repo")


def prereg(name):
    return books() / "prereg" / name


def operator_excluded():
    p = books() / "operator_excluded.json"
    if not p.is_file():
        raise SystemExit(f"STOP: {p} is missing; the operator exclusions are data in rs2-state, never code")
    tickers = json.loads(p.read_text(encoding="utf-8")).get("tickers")
    if not isinstance(tickers, list) or not tickers or not all(isinstance(t, str) and t for t in tickers):
        raise SystemExit(f"STOP: {p} has no non-empty 'tickers' list")
    return set(tickers)

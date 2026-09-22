"""archive_census.py — does any live file still reference a retired artifact BY NAME?

    python tools/audit_202608/archive_census.py      # report; exit 1 if live CODE references one

WHY THIS EXISTS. Commit b1f345f archived `RS2-Analyst-Deep.Modelfile`, and
`api_llm/deep_api_run.py` read it for its framework text. `_rs2_framework()` then raised
FileNotFoundError on every request, reached in production through `cloud_backstop.py:197`, which
subprocess-launches that script for every ticker when the PC is off. The census that cleared the
archival missed it because it looked for imports and `<name>.py` mentions - and the archived file
was a `.Modelfile`. THE GAP WAS SCOPE, NOT METHOD.

Companion check: `tests/test_group_b_decoupling.py` asserts no live module IMPORTS an archived
module. This one covers the other way a reference can dangle - a path resolved at runtime.

WHY IT IS QUIET, though "any path literal" sounds noisy:
  * Only names actually in the archive are checked - a fixed, finite set.
  * Any name that STILL EXISTS live is skipped: a live reference to a live file is not evidence
    of anything. How many that removes depends on the tree - 40 in a working tree carrying
    untracked backup directories, 0 on a clean checkout - so no exclusion list is maintained by
    hand, and nothing here depends on the count.
  * It reads the file's STRUCTURE, not its text. Comments do not exist in an AST, so they are
    excluded for free; docstrings are excluded deliberately, because recording history is
    correct - `orchestrate_depth.py` says "Successor to orchestrate.py" and `api_chat.py` names
    `RS2.txt` to explain why it was replaced. A text scan flags every one of those.
"""
import ast
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
ARCHIVE = HERE / "_archive"

SKIP_DIRS = {"__pycache__", ".git", ".worktrees", ".pytest_cache", ".ruff_cache", ".claude",
             "_archive", "_quarantine", "scratch", "searxng", "research-venv", "node_modules",
             "site-packages"}
PY_EXT = ".py"
SCRIPT_EXTS = (".ps1", ".vbs")

# The ONE structural exemption, and it is not a silencing list. A test for this check HAS to
# contain the names it checks for, so scanning it would report its own fixtures as defects. Every
# other file in the tree is scanned, and this is never the place to add an entry to hide a real
# finding - a live reference must be fixed, not excused.
SELF_TEST = "tools/audit_202608/tests/test_archive_reference_census.py"

# Quoted spans in a .ps1/.vbs file. Those languages have no parser here, so this over-approximates
# on purpose. Harmless: only .py code references can fail the build, so an over-approximation in a
# script file can never produce a false failure.
_QUOTED = re.compile(r"'([^'\n]{3,})'|\"([^\"\n]{3,})\"")


def _pattern(name):
    """Whole-token pattern. Boundaries matter in BOTH directions.

    The first draft produced exactly two false positives, both `depth_orchestrate.log` matching
    archived `_orchestrate.log`; and `RS2.txt` must not match inside `RS2.txt.bak`.
    """
    return r"(?<![\w.-])" + re.escape(name) + r"(?![\w.])"


@lru_cache(maxsize=1)
def live_files():
    """Every live source file the census reads. Cached - the tree is walked several times."""
    out = []
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(PY_EXT) or f.endswith(SCRIPT_EXTS):
                out.append(Path(root) / f)
    return tuple(out)


@lru_cache(maxsize=1)
def live_names():
    """Every filename anywhere in the live tree - decides what is still live."""
    found = set()
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found.update(files)
    return frozenset(found)


@lru_cache(maxsize=1)
def archived_names():
    """(names_to_check, shadowed) - a name still present live is shadowed, not checked."""
    live = live_names()
    names, shadowed = {}, []
    if not ARCHIVE.exists():
        return {}, ()
    for p in ARCHIVE.rglob("*"):
        if not p.is_file():
            continue
        if p.name in live:
            shadowed.append(p.name)
            continue
        names.setdefault(p.name, []).append(str(p.relative_to(ARCHIVE)))
    return names, tuple(sorted(set(shadowed)))


def mentions(haystack, name):
    """True only on a whole-token match. Single-name form, used by the unit tests."""
    return re.search(_pattern(name), haystack or "") is not None


def _bulk(names):
    """One regex for every name, longest first so an overlap resolves to the longer name.

    A per-literal/per-name loop is O(literals x 425) and measured 46 SECONDS for this tree. This
    makes it one search per literal.
    """
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(r"(?<![\w.-])(?:" + alts + r")(?![\w.])")


def py_strings(source):
    """[(literal, is_docstring)] for a Python source. Comments are absent by construction.

    Docstrings are identified by position - the first statement of a module, class or function -
    so they can be reported for triage instead of failing the build.
    """
    tree = ast.parse(source)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, (id(node) in docs)


def script_strings(body):
    """Quoted spans from a .ps1/.vbs file. No parser, so this over-approximates."""
    out = []
    for m in _QUOTED.finditer(body or ""):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if s:
            out.append(s)
    return out


def scan(exempt=(SELF_TEST,)):
    """(code_hits, doc_hits); each hit is (relative_path, archived_name, literal)."""
    names, _ = archived_names()
    code_hits, doc_hits = [], []
    if not names:
        return code_hits, doc_hits
    rx = _bulk(names)
    skip = set(exempt)
    for path in live_files():
        rel = str(path.relative_to(HERE)).replace(os.sep, "/")
        if rel in skip:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if path.suffix == PY_EXT:
            try:
                pairs = list(py_strings(body))
            except SyntaxError:
                continue
        else:
            pairs = [(s, False) for s in script_strings(body)]
        for literal, is_doc in pairs:
            m = rx.search(literal)
            if m:
                hit = (rel, m.group(0), literal.strip()[:90])
                (doc_hits if is_doc else code_hits).append(hit)
    return code_hits, doc_hits


def main():
    names, shadowed = archived_names()
    print(f"  archived names checked      : {len(names)}")
    print(f"  auto-skipped (still live)   : {len(shadowed)}")
    print(f"  live files scanned          : {len(live_files())}")
    print("")
    code_hits, doc_hits = scan()

    print(f"  CODE references: {len(code_hits)}   <== must be 0")
    for rel, name, lit in code_hits:
        print(f"      {rel} -> {name}")
        print(f"          {lit!r}")
    print("")
    print(f"  DOCSTRING mentions (history - triage by eye): {len(doc_hits)}")
    seen = set()
    for rel, name, lit in doc_hits:
        if (rel, name) in seen:
            continue
        seen.add((rel, name))
        print(f"      {rel} -> {name}")
    print("")
    if code_hits:
        print("  FAIL - live code resolves a path to an archived file; it will fail at runtime.")
        return 1
    print("  CLEAN - no live code references an archived artifact by name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

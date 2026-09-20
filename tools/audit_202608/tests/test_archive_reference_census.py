"""No live file may reference an archived artifact by name.

THE BUG THIS EXISTS FOR. Commit b1f345f archived `RS2-Analyst-Deep.Modelfile`.
`api_llm/deep_api_run.py` read that file for its framework text, so `_rs2_framework()` raised
FileNotFoundError on every request - reached in production through `cloud_backstop.py:197`,
which subprocess-launches that script for every ticker when the PC is off.

The census that cleared the archival did not catch it, because it looked for imports and
`<name>.py` string references. The archived file was a `.Modelfile`. THE GAP WAS SCOPE, NOT
METHOD: it never looked at non-.py artifacts at all.

WHY THIS IS NOT NOISY, despite "any path literal" sounding like it must be:
  * It checks only names that are actually in the archive - a fixed, finite set.
  * It skips any name that STILL EXISTS live, because a live reference to a live file is not
    evidence of anything. That rule removes 40 names in a working tree that carries untracked
    backup directories and 0 on a clean checkout, so nobody maintains an exclusion list and
    nothing here depends on the count.
  * It reads the file's STRUCTURE, not its text. Comments do not exist in an AST, so they are
    excluded for free, and docstrings are excluded deliberately. Docstrings legitimately record
    history - `orchestrate_depth.py` saying "Successor to orchestrate.py", `api_chat.py` naming
    `RS2.txt` to explain why it was replaced - and a text scan would flag every one of them.
    Measured: 425 archived names, 66 live files -> 0 code references, 20 docstring mentions, all
    legitimate.
"""
from tools.audit_202608.archive_census import (
    archived_names, live_files, live_names, mentions, py_strings, scan, script_strings,
)


# ---- the matching rule -----------------------------------------------------------------

def test_mentions_requires_a_word_boundary():
    # The first draft produced exactly two false positives, both this: a live reference to
    # `depth_orchestrate.log` matched archived `_orchestrate.log`.
    assert mentions("depth_orchestrate.log", "_orchestrate.log") is False
    assert mentions("cache/orchestrate.log", "_orchestrate.log") is False


def test_mentions_matches_a_real_reference():
    assert mentions('ROOT / "RS2-Analyst-Deep.Modelfile"', "RS2-Analyst-Deep.Modelfile") is True
    assert mentions('"/x/y/RS2.txt"', "RS2.txt") is True


def test_mentions_does_not_match_an_extension_twin():
    assert mentions("RS2.txt.bak", "RS2.txt") is False


# ---- structure, not text ---------------------------------------------------------------

def test_comments_are_invisible_to_the_scan():
    # The property that makes this quieter than a text scan: an AST has no comment nodes.
    src = "# a comment mentioning RS2.txt and orchestrate.py\nX = 1\n"
    assert list(py_strings(src)) == []


def test_docstrings_are_separated_from_code():
    src = '"""Module docstring naming RS2.txt."""\nX = "archive/RS2.txt"\n'
    pairs = list(py_strings(src))
    assert ("Module docstring naming RS2.txt.", True) in pairs
    assert ("archive/RS2.txt", False) in pairs


def test_a_nested_function_docstring_is_also_treated_as_prose():
    src = 'def f():\n    """Names orchestrate.py."""\n    return "ok"\n'
    assert ("Names orchestrate.py.", True) in list(py_strings(src))


def test_script_strings_reads_quoted_spans():
    body = "$x = 'run_rs2.py'\n$y = \"orchestrate.py\"\n"
    got = script_strings(body)
    assert "run_rs2.py" in got
    assert "orchestrate.py" in got


# ---- the census itself -----------------------------------------------------------------

def test_the_census_scans_a_non_trivial_tree():
    """Guards against passing vacuously - a census over nothing asserts nothing.

    Asserts only what holds on a CLEAN CHECKOUT. An earlier version also asserted
    `shadowed > 0`, which is true in a working tree carrying untracked backup directories and
    false in a fresh clone - so the guard passed only on the machine that wrote it. Caught by
    running the suite in a worktree at HEAD with just the staged files overlaid.
    """
    names, _ = archived_names()
    assert len(names) > 100, f"only {len(names)} archived names - is the archive present?"
    assert len(list(live_files())) > 20, "too few live files scanned - is the tree complete?"
    # The shadow rule must be APPLIED, which is checkable anywhere, rather than merely
    # TRIGGERED, which is not. A checked name that still exists live would mean a live file is
    # being reported as an archived one.
    assert not (set(names) & set(live_names())), (
        "a name still present live is being checked - the shadow rule is not being applied")


def test_mentions_of_archived_names_are_a_real_measurement():
    # At least one archived name must be MENTIONED somewhere, or the scan is not running.
    _, doc_hits = scan()
    assert doc_hits, "expected some docstring mentions; finding none suggests a broken scan"


def test_no_live_file_references_an_archived_artifact():
    """The guard. A failure here means an archival left a live reference pointing at nothing.

    Fix the reference in the same change rather than adding an exception: an exception list is
    how the original defect stayed invisible.
    """
    code_hits, _ = scan()
    assert not code_hits, (
        "live code references archived files by name - these paths will fail at runtime:\n  "
        + "\n  ".join(f"{rel} -> {nm}   ({lit})" for rel, nm, lit in code_hits))

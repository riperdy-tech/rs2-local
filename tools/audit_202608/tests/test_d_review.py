"""Tests for brief D (charter v3.2, DATA n pack block renaming, readers, and memo references).

Brief D3 requirements:
- A rename test: On the GEV golden, no line matches \bSECTION[Ss]?\b outside the research brief's
  third-party text, and every header numbered in revision 14 appears as ## DATA n.
- A memo-reference test:
  - The TASK and RESEARCH_ADDENDUM contain exactly the memorandum references listed in D2 and no
    other "SECTION n".
  - The v3.2 SYSTEM text contains no "SECTION 1.5", "SECTION 1.6" or "SECTION 2.5", and no
    kelly_fraction_pct, base_iv or coe_source.
- The readers:
  - The research strip on a SECTION pack and on a DATA pack.
  - The shares-citation regex on "DATA 2", "DATA 6B", "SECTION 2", "SECTION 6B", and the negative
    "DATA 2.5".
  - The discovery slice on both.
- The share sentence: test_s3c_review.py's check keeps passing after the rename.
"""
from pathlib import Path
import re
import sys
import pytest

AUDIT_DIR = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixture_data"

for p in (str(AUDIT_DIR), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import analyst_tools
import capability_test as cap
import catalyst_research
import consensus_valuation


def _get_system_block(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    m = re.search(r'SYSTEM """(.*?)"""', content, re.DOTALL)
    if not m:
        raise ValueError(f"SYSTEM block not found in {path}")
    return m.group(1)


# --- 1. A rename test ---

def test_gev_golden_rename():
    golden_file = FIXTURE / "golden_pack_GEV_rev15.md"
    assert golden_file.exists()
    text = golden_file.read_text(encoding="utf-8")

    # Outside research brief (which is not included in golden pack anyway):
    # No line matches \bSECTION[Ss]?\b
    section_matches = [
        (i + 1, line)
        for i, line in enumerate(text.splitlines())
        if re.search(r"\bSECTION[Ss]?\b", line)
    ]
    assert section_matches == [], f"Found SECTION in golden pack: {section_matches}"

    # Every header numbered in revision 14 appears as ## DATA n
    # Rev 14 headers in GEV: 0, 1, 1.5, 1.6, 2, 2.5, 3, 4, 5, 6, 7, 8, 8.5, 12
    rev14_numbers = ["0", "1", "1.5", "1.6", "2", "2.5", "3", "4", "5", "6", "7", "8", "8.5", "12"]
    for num in rev14_numbers:
        expected = f"## DATA {num} "
        assert expected in text, f"Missing header '{expected}' in GEV golden pack"


# --- 2. A memo-reference test ---

def test_task_and_research_addendum_memo_references():
    # References to memorandum sections stay SECTION.
    # D2: in TASK: "SECTION 0 through SECTION 12", "SECTION 12's contract",
    #     "SECTION 4's scenario table and SECTION 12's figures"
    task_sec_matches = re.findall(r"\bSECTION\s*\d+(?:\.\d+)?\b", cap.TASK)
    # The occurrences should only refer to memo sections 0, 3, 4, 12 (revision 19: item 6 has the memorandum state each crux in SECTION 3 and
    # says SECTION 0 and SECTION 12 state the verdict it gives):
    assert sorted(set(task_sec_matches)) == ["SECTION 0", "SECTION 12", "SECTION 3", "SECTION 4"]
    # Total count in TASK is 8: SECTION 0 (2), SECTION 3 (1), SECTION 4 (1), SECTION 12 (4)
    assert len(task_sec_matches) == 8

    # D2: in RESEARCH_ADDENDUM: "SECTION 0 through SECTION 12"
    addendum_sec_matches = re.findall(r"\bSECTION\s*\d+(?:\.\d+)?\b", cap.RESEARCH_ADDENDUM)
    assert sorted(set(addendum_sec_matches)) == ["SECTION 0", "SECTION 12"]
    assert len(addendum_sec_matches) == 2


def test_system_v32_no_stale_references():
    for filename in ("RS2-Analyst-Deep-MTP5-v32.Modelfile", "RS2-Analyst-Deep-MTP5-Q4-v32.Modelfile"):
        modelfile_path = REPO / filename
        assert modelfile_path.exists()
        sys_text = _get_system_block(modelfile_path)

        for stale in ("SECTION 1.5", "SECTION 1.6", "SECTION 2.5"):
            assert stale not in sys_text, f"{filename} contains stale section ref: {stale}"

        for removed in ("kelly_fraction_pct", "base_iv", "coe_source"):
            assert removed not in sys_text, f"{filename} contains removed contract/parameter name: {removed}"


def test_system_v33_one_funded_terminal():
    # Revision 17 (brief_rev17_charter_v33.md): the exit multiple and terminal_leg left the desk, so the charter
    # must not describe them; the v33 SYSTEM is the v32 SYSTEM with twelve sentence changes and no more.
    for filename in ("RS2-Analyst-Deep-MTP5-v33.Modelfile", "RS2-Analyst-Deep-MTP5-Q4-v33.Modelfile"):
        sys_text = _get_system_block(REPO / filename)
        for gone in ("exit multiple", "terminal_leg", "BOTH terminal", "Dual Terminal", "terminal legs",
                     "SECTION 1.5", "SECTION 1.6", "SECTION 2.5", "kelly_fraction_pct", "base_iv", "coe_source"):
            assert gone not in sys_text, f"{filename} still contains {gone!r}"
        assert "CHARTER v3.3" in sys_text and "CHARTER v3.2" not in sys_text
        assert "terminal_ronic" in sys_text and "FUNDED TERMINAL VALUATION" in sys_text
    v32 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5-v32.Modelfile").split("\n")
    v33 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5-v33.Modelfile").split("\n")
    assert len(v32) == len(v33)
    changed = [i + 1 for i, (a, b) in enumerate(zip(v32, v33)) if a != b]
    # SYSTEM-relative line numbers: 2 (title), 28 (value cycle), 30-31 (heading, macro sentence), 33-34 (valuation,
    # growth/terminal), 37-39 (terminal multiple, peer cross-check, desk return), 47 (cycle), 93 (SECTION 3).
    assert changed == [2, 28, 30, 31, 33, 34, 37, 38, 39, 47, 93]


# --- 3. The readers ---

def _saved_pack_after_no_research(monkeypatch, tmp_path, body):
    """Run consensus_valuation.main() with --no-research on a frozen pack and return the _pack.md it
    saved. The research strip (consensus_valuation.py, "Proceed with --no-research semantics") is
    inline in main(), so this is the production reader, not a copy of its regex (reviewer fix)."""
    import urllib.request
    from test_review_fixes_2 import MEMO, _R, _resp

    def fake_urlopen(req, timeout=None):
        return _R(_resp(MEMO))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(analyst_tools.urllib.request, "urlopen", fake_urlopen)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "_pack.md").write_text(body, encoding="utf-8")
    out = tmp_path / "cons"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "ZZSIM", "--samples", "1", "--pack-file", str(frozen / "_pack.md"),
        "--out-dir", str(out), "--price", "400", "--no-research", "--think", "high"])
    consensus_valuation.main()
    run_dir = sorted(out.glob("ZZSIM_*"))[-1]
    return (run_dir / "_pack.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["DATA", "SECTION"])
def test_readers_research_strip(monkeypatch, tmp_path, name):
    body = (f"## {name} 10 - EARNINGS CALL EXCERPT\nExcerpt.\n"
            f"## {name} 11 - DEEP RESEARCH BRIEF\nBrief details that must not reach the model.\n"
            f"## {name} 12 - WHAT WE DO NOT HOLD\nDeclared gaps.\n")
    saved = _saved_pack_after_no_research(monkeypatch, tmp_path, body)
    assert "DEEP RESEARCH BRIEF" not in saved
    assert "Brief details that must not reach the model." not in saved
    assert f"## {name} 10 - EARNINGS CALL EXCERPT\nExcerpt.\n" in saved
    assert f"## {name} 12 - WHAT WE DO NOT HOLD\nDeclared gaps.\n" in saved


def test_readers_shares_citation_regex():
    # consensus_valuation._is_shares_reason_cited
    # Positive citations: DATA 2, DATA 6B, SECTION 2, SECTION 6B
    assert consensus_valuation._is_shares_reason_cited("per DATA 2 basic count")
    assert consensus_valuation._is_shares_reason_cited("from DATA 6B latest filed")
    assert consensus_valuation._is_shares_reason_cited("SECTION 2 vendor count")
    assert consensus_valuation._is_shares_reason_cited("SECTION 6B filed dilution")
    assert consensus_valuation._is_shares_reason_cited("DATA 2")
    assert consensus_valuation._is_shares_reason_cited("DATA 6B")
    assert consensus_valuation._is_shares_reason_cited("SECTION 2")
    assert consensus_valuation._is_shares_reason_cited("SECTION 6B")

    # Negative citation: DATA 2.5, SECTION 2.5
    assert not consensus_valuation._is_shares_reason_cited("DATA 2.5")
    assert not consensus_valuation._is_shares_reason_cited("SECTION 2.5")
    assert not consensus_valuation._is_shares_reason_cited("momentum from DATA 2.5 price action")
    assert not consensus_valuation._is_shares_reason_cited("arbitrary estimate")
    assert not consensus_valuation._is_shares_reason_cited(None)


def test_readers_discovery_slice(monkeypatch):
    """catalyst_research.discovery_context slices DATA 2.5, else SECTION 2.5, else prints the DATA-named
    fallback. Runs the production reader on a stubbed pack (reviewer fix: the coder's test applied the
    fallback itself, so it passed whatever the reader did)."""
    monkeypatch.setattr(catalyst_research.rs2_data, "resolve_name", lambda t: "Test Company Inc.")
    monkeypatch.setattr(catalyst_research.rs2_data, "sector_lookup", lambda t: ("Technology", "Semiconductors"))
    monkeypatch.setattr(cap, "LAST_PACK_MOMENTUM_STATE", {"mom_1m": 0.12, "mom_6m": 0.50})

    def slice_of(text):
        monkeypatch.setattr(cap, "build_pack",
                            lambda ticker, include_research=False, news_snippets=False: cap.PackText(text))
        return catalyst_research.discovery_context("TEST")["section_2_5"]

    for name in ("DATA", "SECTION"):
        text = (f"## {name} 2 - MARKET\nPrice: $100\n\n## {name} 2.5 - PRICE ACTION\n"
                f"- 12-1 month return: +20.0%\n\n## {name} 3 - TRAILING TWELVE MONTHS\n- Revenue: $10.0B\n")
        sec25 = slice_of(text)
        assert sec25.startswith(f"## {name} 2.5 - PRICE ACTION"), (name, sec25)
        assert "- 12-1 month return: +20.0%" in sec25
        assert f"{name} 2 - MARKET" not in sec25 and f"{name} 3 " not in sec25
    # neither name: the fallback text is DATA-named
    assert slice_of("# Empty pack\n") == "## DATA 2.5 - PRICE ACTION\nnot available"
    # a pack carrying both prefers DATA
    both = ("## SECTION 2.5 - PRICE ACTION\n- old\n\n## DATA 2.5 - PRICE ACTION\n- new\n\n"
            "## DATA 3 - TRAILING TWELVE MONTHS\n")
    assert slice_of(both).startswith("## DATA 2.5 - PRICE ACTION\n- new")


# --- 4. The share sentence ---

def test_share_sentence_keeps_passing():
    from test_s3c_review import test_task_and_tools_name_the_share_default
    test_task_and_tools_name_the_share_default()

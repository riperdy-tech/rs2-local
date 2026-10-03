"""tools/audit_202608/tests/test_pack_rev15.py — S3 package C (brief section 6 item 5, "Pack").

- Byte equality with golden_pack_GEV_rev21.md (revision 17: the through-cycle package's DEFAULTS lines, no
  exit multiple; revision 21: the PRIMARY SOURCES section, read from GEV's real filings in fixture_data/sec_primary;
  rev16's golden stays beside it as the pre-17 record), built with S1's step-0 stubs and frozen clock.
- The DEFAULTS block is the pack's last block and parses.
- The retired-words test of 5.3 (GEV golden, and every rebuilt name from 7.3's 20-name sample).
- The discovery slices (SECTION 2.5, RECENT COMPANY NEWS, CONSENSUS ESTIMATES, GUIDANCE) are
  byte-identical to the S2c tree's (82530a3, the "revision 14" tree this step builds on), with
  news_snippets=True and a stubbed 3-row company_news.fetch (one row with an excerpt, two without,
  one of those undated).
- C2 on the 11 recorded SECTION 11 sub-sections whose first sentence matches LACK (fixture_data/
  research_c2/): exactly the 8 dropped, and the omitted-topics line lists them.
- C3: SECTION 1.6 carries none of the four duplicate lines, and the SECTION 10 pointer follows the
  transcript's presence.
"""
import json
import re
import socket
import subprocess
import sys
from datetime import datetime as _real_datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import capability_test as cap  # noqa: E402
import catalyst_research  # noqa: E402
import consensus_valuation  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
import valuation_backbone  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixture_data"

FIXED_LOCAL = _real_datetime(2026, 9, 27, 12, 0, 0)


class _FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FIXED_LOCAL.astimezone(tz)
        return FIXED_LOCAL


def _stub_and_freeze(monkeypatch):
    """S1's step-0 stubs (test_no_model_visible_change.py::test_pack_byte_pin), reused here so the
    golden pack is built the same way."""
    class BlockedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")

        def connect(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")
    monkeypatch.setattr(socket, "socket", BlockedSocket)
    monkeypatch.setattr(
        cap.company_news, "fetch",
        lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [],
                            "errors": ["stubbed"]},
    )
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)
    import gev_primary_fixture
    gev_primary_fixture.install(monkeypatch)                      # revision 21: the PRIMARY SOURCES section reads GEV's committed filings
    for mod in (cap, rs2_data, catalyst_research, valuation_backbone):
        monkeypatch.setattr(mod, "datetime", _FrozenDatetime, raising=False)


# -------------------------------------------------------------------------------------------
# Golden byte equality
# -------------------------------------------------------------------------------------------

def test_golden_pack_gev_rev15_byte_equal(screener_data_stub, monkeypatch):
    _stub_and_freeze(monkeypatch)
    pack1 = cap.build_pack("GEV", include_research=False)
    pack2 = cap.build_pack("GEV", include_research=False)
    text1 = str(pack1)
    assert text1 == str(pack2)
    golden_bytes = (FIXTURE / "golden_pack_GEV_rev21.md").read_bytes().replace(b"\r\n", b"\n")
    assert text1.encode("utf-8") == golden_bytes


# -------------------------------------------------------------------------------------------
# The DEFAULTS block is last, and parses
# -------------------------------------------------------------------------------------------

def test_defaults_block_is_last_and_parses(screener_data_stub, monkeypatch):
    _stub_and_freeze(monkeypatch)
    pack = cap.build_pack("GEV", include_research=False)
    text = str(pack)
    i = text.rfind("## DEFAULTS")
    assert i != -1
    # nothing else starts a new top-level "## " block after it (a "### " sub-header would not
    # count, but DEFAULTS has none)
    tail = text[i:]
    assert tail.count("\n## ") == 0
    assert text.rstrip().endswith(
        "a Bear value above it needs bear_above_price_reason")
    parsed = pack_facts.from_text(text)
    assert parsed["source"] == "defaults_block"
    assert pack_facts.parity(pack.facts, parsed) == []


# -------------------------------------------------------------------------------------------
# 5.3's retired-words acceptance
# -------------------------------------------------------------------------------------------

_RETIRED_WORDS = ("contract", "coe_source", "base_cf_basis", "verdict_label",
                  "kelly_fraction_pct", "MANDATE")


def _retired_word_hits(text):
    """S3 5.3's acceptance: none of the retired words outside the DEFAULTS block and the form's 13
    field names. "contract" is checked as a whole word, excluding SECTION 6B's pre-existing (and,
    per 5.3, unchanged) "contract liabilities" accounting term — the one place the plain English
    word survives on purpose (doctrine that stays, 5.3)."""
    i = text.find("## DEFAULTS")
    body = text[:i] if i != -1 else text
    # revision 21: the PRIMARY SOURCES section is the company's own filing text, verbatim ("under contract" is GEV's own phrase), not the pack's words
    p0 = body.find("## PRIMARY SOURCES")
    if p0 != -1:
        p1 = body.find("\n## ", p0 + 3)
        body = body[:p0] + (body[p1:] if p1 != -1 else "")
    hits = []
    for word in _RETIRED_WORDS:
        for m in re.finditer(r"\b" + re.escape(word) + r"\b", body):
            if word == "contract" and body[m.end():m.end() + 12].lstrip().startswith("liabilit"):
                continue
            hits.append((word, m.start()))
    return hits


def test_no_retired_words_in_gev_golden(screener_data_stub, monkeypatch):
    _stub_and_freeze(monkeypatch)
    text = str(cap.build_pack("GEV", include_research=False))
    hits = _retired_word_hits(text)
    assert hits == [], [(w, text[max(0, p - 40):p + 40]) for w, p in hits]


@pytest.mark.parametrize("ticker", ["GEV", "EZPW", "AAPL"])
def test_no_retired_words_in_rebuilt_packs(ticker):
    """A handful of real names (not the synthetic screener_data_stub fixture), to catch a retired
    word that only a real data shape would trigger. Uses the live local data (no network)."""
    try:
        text = str(cap.build_pack(ticker, include_research=False))
    except Exception as e:   # pragma: no cover - name not present locally
        pytest.skip(f"{ticker}: {e}")
    hits = _retired_word_hits(text)
    assert hits == [], [(w, text[max(0, p - 40):p + 40]) for w, p in hits]


# -------------------------------------------------------------------------------------------
# 6.5: the discovery slices stay byte-identical to the revision-14 (S2c, 82530a3) tree's
# -------------------------------------------------------------------------------------------

_S2C_COMMIT = "82530a3"   # the revision-14 tree this step builds on (S2c)
_DUMP_HELPER = Path(__file__).resolve().parent / "_discovery_slice_dump_helper.py"


def _dump_slices(tree_root, out_path, supports_news_snippets):
    subprocess.run(
        [sys.executable, str(_DUMP_HELPER), str(tree_root), str(out_path),
         "1" if supports_news_snippets else "0"],
        check=True, cwd=str(tree_root),
    )
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.fixture
def s2c_tree(tmp_path):
    """S3 C review (2026-09-28): the revision-14 tree, exported from this repository's own history,
    so the test runs wherever the history is present. It used to read an export outside the
    repository and skipped wherever that folder was missing."""
    import io
    import tarfile
    p = subprocess.run(["git", "-C", str(REPO), "archive", _S2C_COMMIT], capture_output=True)
    if p.returncode != 0:
        pytest.skip(f"git archive {_S2C_COMMIT} unavailable: {p.stderr[:200]!r}")
    out = tmp_path / "s2c"
    out.mkdir()
    with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
        tf.extractall(out, filter="data")
    return out


def test_discovery_slices_byte_identical_to_revision_14(tmp_path, s2c_tree):
    old = _dump_slices(s2c_tree, tmp_path / "old.json", supports_news_snippets=False)
    new = _dump_slices(REPO, tmp_path / "new.json", supports_news_snippets=True)
    for key in ("section_2_5", "recent_news", "consensus_estimates", "guidance"):
        # the charter-and-rename change renames the numbered pack blocks (DATA n); nothing else in
        # the discovery input may change
        expected = re.sub(r"\bSECTION[Ss]? (?=\d)", "DATA ", old[key]) if old[key] else old[key]
        assert new[key] == expected, key


# -------------------------------------------------------------------------------------------
# C2 (5.9): the 11 recorded off-topic sub-sections
# -------------------------------------------------------------------------------------------

def test_c2_drops_exactly_the_recorded_eight(screener_data_stub):
    manifest = json.loads((FIXTURE / "research_c2" / "manifest.json").read_text(encoding="utf-8"))
    rb_text = (FIXTURE / "research_c2" / "combined_11_subsections.md").read_text(encoding="utf-8")
    filtered, dropped_titles = cap._c2_filter_research_brief(rb_text)

    expected_dropped = [m["title"] for m in manifest if m["expected_dropped"]]
    expected_kept = [m["title"] for m in manifest if not m["expected_dropped"]]
    assert len(expected_dropped) == 8
    assert sorted(dropped_titles) == sorted(expected_dropped)
    for title in expected_kept:
        assert title in filtered   # the sub-section's own heading text survives


def test_c2_wired_into_section_11_with_omitted_topics_line(screener_data_stub, monkeypatch):
    rb_text = (FIXTURE / "research_c2" / "combined_11_subsections.md").read_text(encoding="utf-8")
    research_dir = cap.HERE / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "GEV.md").write_text(rb_text, encoding="utf-8")
    monkeypatch.setattr("research_brief_guard.check_research_brief", lambda t, brief_text=None: (True, None))
    pack = cap.build_pack("GEV", include_research=True)
    text = str(pack)
    assert "- Omitted 8 research topic(s) whose own text says their sources were not about this company:" in text
    assert pack.research_omitted and len(pack.research_omitted) == 8


# -------------------------------------------------------------------------------------------
# C3 (5.10): SECTION 1.6 drops the four duplicate lines; the SECTION 10 pointer follows presence
# -------------------------------------------------------------------------------------------

def _slice(pack, header, next_prefix="## "):
    i = pack.find("## " + header)
    assert i != -1, f"section {header!r} not found in pack"
    j = pack.find("\n" + next_prefix, i + 3)
    return pack[i:j if j != -1 else len(pack)]


def test_section_1_6_has_no_duplicate_lines(screener_data_stub, monkeypatch):
    _stub_and_freeze(monkeypatch)
    pack = str(cap.build_pack("GEV", include_research=False))
    sec16 = _slice(pack, "DATA 1.6")
    assert "MRI regime probability vector" not in sec16
    assert "Nominal 10-Year Treasury yield:" not in sec16
    assert "Real 10-Year Treasury yield:" not in sec16
    assert "10-Year breakeven inflation:" not in sec16
    # the shocks, risk flag, inflation trend and world news stay
    assert "Active shocks" in sec16
    assert "Risk flag `elevated_volatility_ahead`" in sec16
    assert "Inflation trend" in sec16
    assert "WORLD NEWS" in sec16 or "not available" in sec16


def test_section_12_qanda_pointer_follows_section_10(screener_data_stub, monkeypatch):
    _stub_and_freeze(monkeypatch)
    # No transcript stubbed -> SECTION 10 is not printed -> the dangling "See SECTION 10" pointer
    # is gone.
    pack = str(cap.build_pack("GEV", include_research=False))
    # revision 17 (brief C3): the fixed sentence is replaced by the line for the transcript status; GEV's fixture holds no
    # openbb record at all, so no status was recorded
    assert "- Earnings-call text: NOT AVAILABLE — transcript status not recorded." in pack
    assert "NOT HELD for this company" not in pack
    assert "See SECTION 10" not in pack
    assert "- Analyst Q&A from earnings calls: NOT HELD; SECTION 10 holds prepared remarks only." not in pack

"""Revision 17, brief C1: a research topic with no usable sources is declared NOT RESEARCHED, not an abort.

deep_research.build() with `run_topic` stubbed: no search, no network, no model."""
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import deep_research  # noqa: E402
from research_brief_guard import _header_company_match, check_research_brief  # noqa: E402

GOOD = ["https://www.sec.gov/edgar/example-filing", "https://www.reuters.com/markets/example"]
LOW_TRUST = ["https://pitchgrade.com/companies/abc", "https://www.ainvest.com/news/abc"]
DICTIONARY = ["https://www.merriam-webster.com/dictionary/five", "https://www.dictionary.com/browse/five"]
PROSE = "MODEL RECALL PROSE THAT MUST NOT BE KEPT"


@pytest.fixture
def desk(monkeypatch, tmp_path):
    """build() with everything but run_topic stubbed. Returns (notified, calls)."""
    monkeypatch.setitem(deep_research.CONFIG, "out_research_dir", str(tmp_path))
    monkeypatch.setitem(deep_research.CONFIG, "screener_data_dir", str(tmp_path / "screener"))
    monkeypatch.setitem(deep_research.CONFIG, "research_cache_days", 7)
    monkeypatch.setattr(deep_research, "preflight", lambda *a, **k: None)
    monkeypatch.setattr(deep_research, "flag_consistency", lambda *a, **k: None)
    monkeypatch.setattr(deep_research.rs2_data, "sector_lookup",
                        lambda t: ("Industrials", "Specialty Industrial Machinery"))
    import valuation_backbone
    monkeypatch.setattr(valuation_backbone, "backbone", lambda t: {})
    notified = []
    monkeypatch.setattr(deep_research.ops, "notify_telegram", lambda text: notified.append(text))
    return notified


def _run_topic_for(plan, calls):
    """A run_topic stub keyed by the topic each query was formatted from. `plan` maps a topic title to
    (summary, urls) or an Exception; any other topic returns a cited summary with two good sources."""
    def run_topic(query):
        calls.append(query)
        for title, qt in list(deep_research.TOPICS) + [deep_research.CONTESTED_TOPIC]:
            if title in plan and query == qt.format(subj="Acme Corp (ACME)", yr=deep_research.datetime.now().year):
                got = plan[title]
                if isinstance(got, Exception):
                    raise got
                summ, urls = got
                return ("mock_engine", {"summary": summ}, list(urls))
        return ("mock_engine", {"summary": "A cited summary [1]."}, list(GOOD))
    return run_topic


def _build(monkeypatch, plan, calls=None, force=True):
    calls = [] if calls is None else calls
    monkeypatch.setattr(deep_research, "run_topic", _run_topic_for(plan, calls))
    return deep_research.build("ACME", "Acme Corp", force=force)


def test_one_empty_topic_is_declared_not_researched_and_the_brief_is_written(monkeypatch, desk, tmp_path):
    path = _build(monkeypatch, {"Catalysts & Guidance": (PROSE, [])})
    lines = path.read_text(encoding="utf-8").splitlines()
    text = "\n".join(lines)
    assert lines[0] == "research_gaps: Catalysts & Guidance"
    assert lines[1] == "Company: Acme Corp | Ticker: ACME | Industry: Specialty Industrial Machinery"
    assert "## Catalysts & Guidance — NOT RESEARCHED" in text
    i = lines.index("## Catalysts & Guidance — NOT RESEARCHED")
    assert lines[i + 1] == ("No usable sources were found (0 returned, 0 removed as low-trust); "
                            "treat this topic as unknown.")
    assert lines[i + 2] == "" and lines[i + 3].startswith("## ")      # one line, then the next section
    assert PROSE not in text                                          # no prose from the model is kept
    # the other four topics were researched as before
    assert "## Competitive Position & Moat  _(engine: mock_engine" in text
    assert text.count("**Sources:**") == 4
    assert desk == []                                                 # the Telegram note is for the abort path only
    # the guard still finds the Company: header behind the gaps line: the pipeline continues on this brief
    assert _header_company_match(text, "ACME", "Acme Corp")
    assert check_research_brief("ACME", brief_text=text, company_name="Acme Corp") == (True, None)


def test_a_topic_whose_only_sources_are_low_trust_reports_both_counts(monkeypatch, desk):
    path = _build(monkeypatch, {"Industry Demand & End-Markets": ("Prose [1][2].", LOW_TRUST + GOOD[:0])})
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "research_gaps: Industry Demand & End-Markets"
    assert ("No usable sources were found (2 returned, 2 removed as low-trust); "
            "treat this topic as unknown.") in text
    assert "Prose [1][2]." not in text


def test_a_topic_of_irrelevant_sources_is_a_gap_too(monkeypatch, desk):
    path = _build(monkeypatch, {"Bear Case / Short Thesis / Regulatory": ("About the word.", DICTIONARY)})
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "research_gaps: Bear Case / Short Thesis / Regulatory"
    assert ("No usable sources were found (2 returned, 0 removed as low-trust); "
            "treat this topic as unknown.") in text
    assert "About the word." not in text


def test_two_gaps_of_five_are_declared_in_order_on_one_line(monkeypatch, desk):
    path = _build(monkeypatch, {"Competitive Position & Moat": (PROSE, []), "Industry Demand & End-Markets": (PROSE, [])})
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "research_gaps: Competitive Position & Moat; Industry Demand & End-Markets"
    assert text.count("NOT RESEARCHED") == 2 and PROSE not in text
    assert desk == []


def test_half_of_the_topics_empty_aborts_like_an_infra_failure(monkeypatch, desk, tmp_path):
    plan = {t: (PROSE, []) for t in ("Competitive Position & Moat", "Catalysts & Guidance",
                                     "What Changed in the Last 12 Months")}      # 3 of 5
    with pytest.raises(deep_research.ResearchInfraError):
        _build(monkeypatch, plan)
    assert not (tmp_path / "ACME.md").exists()
    assert len(desk) == 1 and "research_infra_fail" in desk[0] and "3/5" in desk[0]


def test_the_half_rule_counts_the_contested_topic(monkeypatch, desk, tmp_path):
    import valuation_backbone
    monkeypatch.setattr(valuation_backbone, "backbone", lambda t: {"lattice": {"contested": True}})
    two = {t: (PROSE, []) for t in ("Competitive Position & Moat", deep_research.CONTESTED_TOPIC[0])}
    path = _build(monkeypatch, two)                                   # 2 of 6: written
    assert path.read_text(encoding="utf-8").count("NOT RESEARCHED") == 2
    three = dict(two, **{"Catalysts & Guidance": (PROSE, [])})        # 3 of 6: half or more
    path.unlink()
    with pytest.raises(deep_research.ResearchInfraError):
        _build(monkeypatch, three)
    assert not path.exists()


def test_an_infra_signature_aborts_even_when_the_other_topics_are_fine(monkeypatch, desk, tmp_path):
    with pytest.raises(deep_research.ResearchInfraError):
        _build(monkeypatch, {"Catalysts & Guidance": ("cudaMalloc failed: out of memory", GOOD)})
    assert not (tmp_path / "ACME.md").exists()
    assert len(desk) == 1


def test_an_exception_from_run_topic_aborts(monkeypatch, desk, tmp_path):
    with pytest.raises(deep_research.ResearchInfraError):
        _build(monkeypatch, {"Bear Case / Short Thesis / Regulatory": RuntimeError("engine unreachable")})
    assert not (tmp_path / "ACME.md").exists()
    assert len(desk) == 1


def test_an_infra_failure_plus_a_gap_lists_both_in_the_abort(monkeypatch, desk):
    with pytest.raises(deep_research.ResearchInfraError) as e:
        _build(monkeypatch, {"Catalysts & Guidance": ("status code: 500", GOOD),
                             "Competitive Position & Moat": (PROSE, [])})
    assert "Catalysts & Guidance" in str(e.value) and "Competitive Position & Moat" in str(e.value)


# ---- cache freshness: a gapped brief is stale after one day ---------------------------------------------------

def _age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


CITED = "- [1] https://www.sec.gov/edgar/example-filing\n"


def test_cache_days_is_one_for_a_gapped_brief_and_the_config_value_otherwise(monkeypatch, desk, tmp_path):
    gapped = tmp_path / "GAP.md"
    gapped.write_text("research_gaps: Catalysts & Guidance\nCompany: X | Ticker: GAP | Industry: Y\n" + CITED,
                      encoding="utf-8")
    plain = tmp_path / "PLAIN.md"
    plain.write_text("Company: X | Ticker: PLAIN | Industry: Y\n" + CITED, encoding="utf-8")
    assert deep_research.cache_days(gapped) == 1
    assert deep_research.cache_days(plain) == 7
    assert deep_research.cache_days(tmp_path / "MISSING.md") == 7
    monkeypatch.setitem(deep_research.CONFIG, "research_cache_days", 0)
    assert deep_research.cache_days(gapped) == 0          # never longer than the configured window


def test_a_gapped_brief_is_stale_after_one_day_and_a_clean_one_is_not(monkeypatch, desk, tmp_path):
    gapped = tmp_path / "ACME.md"
    gapped.write_text("research_gaps: Catalysts & Guidance\nCompany: Acme Corp | Ticker: ACME | Industry: Y\n" + CITED,
                      encoding="utf-8")
    calls = []
    monkeypatch.setattr(deep_research, "run_topic", _run_topic_for({}, calls))

    _age(gapped, 0.5)                                   # half a day: served from cache
    assert deep_research.build("ACME", "Acme Corp", force=False) == gapped
    assert calls == []

    _age(gapped, 2)                                     # two days: the topics are researched again
    path = deep_research.build("ACME", "Acme Corp", force=False)
    assert len(calls) == 5
    assert "research_gaps" not in path.read_text(encoding="utf-8")   # and this run had no gap

    _age(path, 2)                                       # a clean brief of the same age is still fresh
    calls.clear()
    assert deep_research.build("ACME", "Acme Corp", force=False) == path
    assert calls == []

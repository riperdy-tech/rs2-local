"""Brief R26-A1, SPEC revision 26 section 1: the fact checks, the usable rule, the pack's section ids, and a stage-1 session end to end with a scripted
stub model (no GPU, no Ollama, no network)."""
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import analyst_tools as at  # noqa: E402
import llm_provider as prov  # noqa: E402
import r26_stages as r26  # noqa: E402
import r26_late as late  # noqa: E402

DAC_PACK = TESTS_DIR.parents[3] / "pilot_r25" / "frozen_p4sf" / "DAC" / "r25_sf" / "_pack.md"          # scratch/rev23 beside the worktrees; skipped elsewhere


# ---------------------------------------------------------------- normalization

@pytest.mark.parametrize("quote,source", [
    ("Operating revenues increased by $12.2 million", "Operating  revenues\nincreased by $12.2   million to"),
    ("Operating revenues increased by $12.2 million", "operating revenues increased by $ 12.2 million"),            # spaces where tags were; case
    ("it’s the company’s “best” year", "it's the company's \"best\" year"),                      # curly quotes
    ("margin of 12–5%", "margin of 12-5%"), ("up − 3%", "up - 3%"),                                       # dashes, minus sign
    ("**Net income** was `5`", "Net income was 5"),                                                                # markdown marks
    ("revenue of $5", "revenue of $5"),                                                                  # non-breaking spaces
])
def test_normalization_makes_these_the_same_text(quote, source):
    assert r26.find_quote(source, quote)


@pytest.mark.parametrize("quote,source", [
    ("margin of 1.5%", "margin of 15%"), ("margin of 15%", "margin of 1.5%"),                                      # punctuation inside a number is kept
    ("net income rose", "net revenue rose"), ("", "anything"), ("   ", "anything"),
])
def test_normalization_does_not_make_these_the_same_text(quote, source):
    assert not r26.find_quote(source, quote)


def test_the_span_is_in_the_sources_own_characters():
    src = "Header.   Operating   revenues rose  12%.  Footer"
    (a, b), = r26.find_quote(src, "operating revenues rose 12%")
    assert src[a:b] == "Operating   revenues rose  12%"


# ---------------------------------------------------------------- proximity

def test_content_words_are_four_letters_or_more_without_stopwords_with_plurals_folded():
    assert r26.content_words("Net operating margins of the Company in FY2025 (USD m)") == {"operating", "margin"}
    assert r26.content_words("the and was for 12 Q2 EBIT") == {"ebit"}
    assert r26.content_words("Revenues; revenue. Industries and industry") == {"revenue", "industry"}


def test_proximity_window_is_300_characters_each_side_of_the_quote():
    quote = "increased by 5 percent"
    for gap, ok in ((299, True), (300, False)):
        before = "margin" + "." * gap + quote                      # the word's last character is `gap` + 1 before the quote: 300 characters back at gap 299
        assert (r26.proximity(before, r26.find_quote(before, quote), "", "margin")[0] == []) is ok, ("before", gap)
        after = quote + "." * gap + "margin"                        # the word's first character is 300 characters on at gap 299
        assert (r26.proximity(after, r26.find_quote(after, quote), "", "margin")[0] == []) is ok, ("after", gap)


def test_a_word_cut_by_the_window_edge_counts_whole():
    quote = "increased by 5 percent"
    src = "." * 5 + "marginal" + "." * 296 + quote                  # the window starts inside "marginal"
    assert r26.proximity(src, r26.find_quote(src, quote), "", "marginal")[0] == []


def test_the_window_counts_characters_not_words_and_names_what_is_missing():
    quote = "increased by 5 percent"
    src = "operating " + "." * 289 + quote + "." * 289 + " segment"
    miss, _ = r26.proximity(src, r26.find_quote(src, quote), "segment", "operating margin")
    assert miss == ["margin"]


def test_the_best_occurrence_wins():
    quote = "rose 5 percent"
    src = "unrelated text " + quote + (" ." * 400) + " Operating margin " + quote
    miss, span = r26.proximity(src, r26.find_quote(src, quote), "", "operating margin")
    assert miss == [] and span[0] > 400                                              # the second occurrence has both words, the first none
    assert r26.proximity("rose 5 percent in operating margin", [(0, 14)], "", "operating margin")[0] == []


def test_no_content_word_means_nothing_to_find():
    assert r26.proximity("abc", [(0, 3)], "A B", "x of y")[0] == []


# ---------------------------------------------------------------- value forms

@pytest.mark.parametrize("value,quote,ok", [
    (12.5, "margin rose to 12.5%", True), (12.5, "rose 12.5 percent", True), (12.5, "up $12.5 million", True), (12_500_000, "$12.5 million", True), (12.5, "12,500 thousand", False),
    (274.4, "revenues of $274.4 million", True), (274.4, "revenues of $ 274.4m", True), (1.2, "$1.2 billion", True), (1200, "$1.2 billion", False),
    (1_200_000_000, "$1.2 billion", True), (274400000, "$274,400,000", True), (274400000, "$274.4 million", True),
    (-5.2, "a loss of (5.2)", True), (-5.2, "down -5.2%", True), (-5.2, "down −5.2%", True), (5.2, "down -5.2%", False), (-5.2, "down 5.2%", False),
    (0.125, "margin rose to 12.5%", False), (125, "margin rose to 12.5%", False), (12.5, "margin rose to 125%", False), (12.5, "2012.5", False),
    (0, "revenue of 0 vessels", True), (0.0, "a filed zero prints 0.000", True), (10, "three-year 10 year term", True), (10, "year 2010", False),
    (2.5, "2.5x leverage", True), (3, "three vessels", False), (1000, "1,000 ships", True), (1000, "1.000 ships", False),
])
def test_value_forms(value, quote, ok):
    assert r26.value_in_quote(value, quote) is ok


def test_a_null_value_is_not_checked_and_bool_is_not_a_number():
    f = _fact(value=None, quote="The fleet is chartered through 2029.")
    assert r26.check_fact(f, "x " + f["quote"])["value_status"] == "value_null"
    assert "value must be a number or null" in r26.validate_fact_shape(_fact(value=True))


# ---------------------------------------------------------------- the three checks together, and the usable rule

def _fact(**kw):
    f = {"fact_id": "F1", "source": "page:https://x.test/a", "quote": "Operating revenues increased by $12.2 million, to $274.4 million in the quarter.",
         "entity": "Danaos container vessels", "metric": "operating revenues", "period": "Q2 2026", "value": 274.4, "unit": "USD m",
         "basis": "filed_gaap", "duration_years": None}
    f.update(kw)
    return f


PAGE = "Danaos container vessels chartered. Operating  revenues increased by $12.2 million, to $274.4 million in the quarter. Fleet notes follow."


def test_a_verified_near_fact_with_its_value_is_usable():
    r = r26.check_fact(_fact(), PAGE)
    assert (r["quote_status"], r["proximity_status"], r["value_status"], r["usable"], r["unusable_reason"]) == ("quote_verified", "near", "value_in_quote", True, None)


def test_a_quote_not_in_the_source_is_unusable():
    r = r26.check_fact(_fact(quote="Operating revenues increased by $99.9 million"), PAGE)
    assert r["quote_status"] == "quote_not_found" and r["proximity_status"] == "not_checked" and not r["usable"]
    assert r["value_status"] == "value_not_in_quote"


def test_a_far_metric_is_unusable_and_names_the_missing_words():
    far = "Operating revenues increased by $12.2 million" + " filler" * 100 + " Danaos container vessels"
    r = r26.check_fact(_fact(quote="Operating revenues increased by $12.2 million", entity="Danaos fleet", metric="operating revenues"), far)
    assert r["quote_status"] == "quote_verified" and r["proximity_status"] == "metric_not_near_quote" and r["missing_words"] == ["danaos", "fleet"]
    assert not r["usable"] and r["unusable_reason"] == "metric_not_near_quote: danaos, fleet"


def test_a_value_not_in_the_quote_makes_a_fact_association_uncertain_and_unusable():
    r = r26.check_fact(_fact(value=999), PAGE)                                            # cross-check 23, item 5: the value must be in the quote
    assert r["value_status"] == "value_not_in_quote" and r["usable"] is False and r["unusable_code"] == "association_uncertain"
    assert r["unusable_reason"] == "association_uncertain: value_not_in_quote"
    assert r26.check_fact(_fact(value=None, quote="The fleet is chartered through 2029."), "x The fleet is chartered through 2029. Danaos container vessels operating revenues")["usable"] is True


def test_an_unresolved_source_is_unusable_with_its_reason():
    r = r26.check_fact(_fact(), None)
    assert r["quote_status"] == "quote_not_found" and not r["usable"] and r["unusable_reason"] == "source not resolved"


def test_a_quote_over_400_characters_is_flagged_and_still_checked():
    q = "Operating revenues " + "word " * 100
    r = r26.check_fact(_fact(quote=q, value=None), "Danaos container vessels " + q)
    assert r["quote_over_400_chars"] is True and r["usable"] is True


@pytest.mark.parametrize("change,problem", [
    ({"fact_id": ""}, "fact_id must be a non-empty string"), ({"source": "somewhere"}, "source must be pack:"), ({"basis": "audited"}, "basis must be one of"),
    ({"value": "5"}, "value must be a number or null"), ({"duration_years": -1}, "duration_years must be"), ({"duration_years": "forever"}, "duration_years must be"),
    ({"quote": ""}, "quote must be a non-empty string"),
])
def test_shape_problems(change, problem):
    assert any(problem in p for p in r26.validate_fact_shape(_fact(**change)))


def test_a_good_fact_and_the_allowed_duration_forms_have_no_shape_problem():
    for d in (None, 0, 3, 2.5, "ongoing"):
        assert r26.validate_fact_shape(_fact(duration_years=d)) == []
    f = _fact()
    del f["period"]
    assert r26.validate_fact_shape(f) == ["period is missing"]


# ---------------------------------------------------------------- the pack's section ids

PACK = """# DATA PACK - XYZ   (pack revision 26)

## DATA 0 - HOW TO READ THIS PACK
- zero text

## DATA 5 - FISCAL-YEAR INCOME & CASH FLOW   [Filed; $B]
| Revenue | 1.0 |
### DATA 6A - WORKING CAPITAL   [$B]
inventory 5
## DATA 6 - FISCAL-YEAR BALANCE SHEET   [Filed]
total assets 9
### DATA 6B - CAPITAL STRUCTURE   [$B]
debt 3
## GUIDANCE & CONSENSUS   [company's own release]
none
## PRIMARY SOURCES   [filings]
Intro line.

[P1] 6-K earnings release, filed 2026-08-04
> Operating revenues increased by $12.2 million.
> Net income was $5 million.

[P2] 20-F annual report
> The fleet has 75 vessels.
## DATA 11 - DEEP RESEARCH BRIEF   [by another model]
# DEEP RESEARCH BRIEF - XYZ
## Competitive Position & Moat  _(engine: x)_
moat text
## DEFAULTS   [each desk input]
shares 5

---

You are underwriting this company for real money. TASK TEXT.
"""


def test_pack_section_ids():
    s = r26.pack_sections(PACK)
    assert list(s) == ["data-0", "data-5", "data-6a", "data-6", "data-6b", "guidance-consensus", "primary-sources", "data-11", "defaults", "primary-p1", "primary-p2"]
    assert "inventory 5" in s["data-6a"] and "inventory 5" not in s["data-6"]
    assert "inventory 5" in s["data-5"]                                               # a ### section is inside its ## parent
    assert "total assets 9" in s["data-6"] and "debt 3" in s["data-6"] and "debt 3" in s["data-6b"]
    assert "moat text" in s["data-11"] and "moat text" not in s["defaults"]            # a brief's own headings are not sections
    assert s["primary-p1"].startswith("[P1]") and "75 vessels" not in s["primary-p1"] and "Net income was $5 million." in s["primary-p1"]
    assert "75 vessels" in s["primary-sources"] and "75 vessels" in s["primary-p2"]
    assert "TASK TEXT" in s["defaults"]                                                # the TASK is cut by split_task, not by the sections
    assert r26.section_id("DATA 5") == "data-5" and r26.section_id("PRIMARY P1") == "primary-p1" and r26.section_id("data-6A") == "data-6a"


def test_a_repeated_heading_gets_a_numbered_id():
    s = r26.pack_sections("## DATA 5 - A\nx\n## DATA 5 - B\ny\n")
    assert list(s) == ["data-5", "data-5-2"] and "y" in s["data-5-2"] and "y" not in s["data-5"]


def test_split_task_cuts_the_valuation_task_and_what_follows_it():
    body, split = r26.split_task(PACK + "\nRESEARCH RULES - addendum")
    assert split and "TASK TEXT" not in body and "RESEARCH RULES" not in body and body.rstrip().endswith("shares 5")
    assert r26.split_task("no task here") == ("no task here", False)


@pytest.mark.skipif(not DAC_PACK.exists(), reason="the frozen DAC pack is not on this machine")
def test_the_ids_of_a_real_pack():
    pack = DAC_PACK.read_text("utf-8")
    s = r26.pack_sections(pack)
    for sid in ("data-1", "data-1.5", "data-2", "data-5", "data-6a", "data-6c", "data-7", "data-8", "data-9", "primary-sources", "primary-p1", "data-11", "data-12", "defaults",
                "population-ranges", "growth-base-rates", "recent-company-news", "catalyst-brief", "guidance-consensus"):
        assert sid in s, sid
    body, split = r26.split_task(pack)
    assert split and "You are underwriting this company" not in body
    line = next(l for l in s["primary-p1"].split("\n") if l.startswith("> Operating revenues increased"))
    q = line[2:].strip()
    ev = r26.Evidence(body, {})
    text, why = ev.resolve("pack:PRIMARY P1")
    assert why is None and r26.find_quote(text, q)


# ---------------------------------------------------------------- the stage-1 session, scripted

class Script:
    """A stub model: each step is a function (request body) -> assistant message dict, or a dict."""

    def __init__(self, *steps):
        self.steps, self.bodies = list(steps), []

    def __call__(self, body, timeout):
        self.bodies.append(json.loads(json.dumps(body)))
        step = self.steps[len(self.bodies) - 1]
        msg = step(body) if callable(step) else step
        return {"message": msg, "done_reason": "stop", "prompt_eval_count": 1000, "eval_count": 20}


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


PAGE_URL = "https://ir.test/q2"
PAGE_TEXT = "Danaos Corporation second quarter. Operating revenues increased by $12.2 million, to $274.4 million in the three months ended June 30, 2026. Utilization stayed high."


@pytest.fixture
def stub_world(monkeypatch):
    def fake_search(query, why="", snap=None, n=6, query_cache=None):
        res = [{"title": "Danaos Q2", "url": PAGE_URL, "snippet": "Danaos chartered fleet contract backlog stood at $3.1 billion with an average remaining term of 3.4 years."}]
        if query_cache is not None:
            query_cache[query] = res
        return {"query": query, "why": why, "n_results": 1, "results": res, "refetch_warning": False, "cache_hit": False}

    def fake_fetch(url, snap=None, cap=9000, url_cache=None, known_urls=None, _fallback=True):
        rec = {"url": url, "chars": len(PAGE_TEXT), "text": PAGE_TEXT, "full_text": PAGE_TEXT}
        if url_cache is not None:
            url_cache[url] = rec
        return {"url": url, "part": 1, "parts": 1, "chars": len(PAGE_TEXT), "text": PAGE_TEXT, "cache_hit": False}

    monkeypatch.setattr(at, "search_web", fake_search)
    monkeypatch.setattr(at, "fetch_page", fake_fetch)


def _facts_call(*facts, **kw):
    return call("register_facts", facts=list(facts), **kw)


def _run(tmp_path, monkeypatch, *steps, **kw):
    script = Script(*steps)
    monkeypatch.setattr(prov, "chat", script)
    d = r26.run_stage1("m", PACK, tmp_path / "s1", verbose=False, seed=5, **kw)
    return d, script


def test_stage_1_end_to_end(tmp_path, monkeypatch, stub_world):
    good_pack = _fact(fact_id="F1", source="pack:primary-p1", quote="Operating revenues increased by $12.2 million.", value=12.2, unit="USD m",
                      entity="XYZ", metric="operating revenues", period="Q2 2026")
    good_page = _fact(fact_id="F2", source=f"page:{PAGE_URL}", quote="Operating revenues increased by $12.2 million, to $274.4 million", value=274.4,
                      entity="Danaos Corporation", metric="operating revenues")
    good_query = _fact(fact_id="F3", source="query:Q1", quote="contract backlog stood at $3.1 billion with an average remaining term of 3.4 years", value=3.1,
                       unit="USD bn", entity="Danaos chartered fleet", metric="contract backlog", period="2026", duration_years=3.4)
    made_up = _fact(fact_id="F4", source="pack:data-5", quote="Revenue was 1.0 billion dollars exactly", value=1.0)
    stray = _fact(fact_id="F5", source="pack:primary-p2", quote="The fleet has 75 vessels.", value=75, unit="vessels", entity="Danaos", metric="margin")
    nosrc = _fact(fact_id="F6", source="page:https://never.test/fetched", quote="anything at all", value=None)
    summary = "Danaos charters container ships. " * 3
    d, script = _run(
        tmp_path, monkeypatch,
        call("search_web", query="danaos backlog", why="backlog"),
        call("fetch_page", url=PAGE_URL),
        _facts_call(good_pack, good_page, good_query, made_up, stray, nosrc),
        call("register_facts", facts=[], done=True, research_summary=summary))
    by = {f["fact_id"]: f for f in d["facts"]}
    assert [f["fact_id"] for f in d["facts"]] == ["F1", "F2", "F3", "F4", "F5", "F6"]
    assert by["F1"]["usable"] and by["F2"]["usable"] and by["F3"]["usable"]
    assert by["F3"]["statuses"]["value_status"] == "value_in_quote" and by["F3"]["duration_years"] == 3.4
    assert by["F4"]["statuses"]["quote_status"] == "quote_not_found" and not by["F4"]["usable"]
    assert by["F5"]["statuses"]["proximity_status"] == "metric_not_near_quote" and by["F5"]["statuses"]["missing_words"] == ["danaos", "margin"] and not by["F5"]["usable"]
    assert "was not fetched" in by["F6"]["unusable_reason"] and not by["F6"]["usable"]
    assert d["done"] is True and d["incomplete"] is False and d["incomplete_reason"] is None
    assert d["summary"] == summary.strip() and d["counts"] == {"facts": 6, "usable": 3, "unusable": 3}
    assert [x[0] for x in r26.unusable_listing(d)] == ["F4", "F5", "F6"] and len(r26.usable_facts(d)) == 3
    on_disk = json.loads((tmp_path / "s1" / "dossier.json").read_text("utf-8"))
    assert on_disk == json.loads(json.dumps(d, default=str))
    assert (tmp_path / "s1" / "_research_snapshot.json").exists()
    # the session: a fresh message list from the blind pack and the stage-1 TASK only
    first = script.bodies[0]
    assert len(first["messages"]) == 2 and first["messages"][0] == {"role": "system", "content": late.STAGE_SYSTEM["stage1"]} and first["messages"][1]["role"] == "user"
    text = first["messages"][1]["content"]
    assert "TASK TEXT" not in text and "You are underwriting" not in text and "STAGE 1 OF 4" in text and "data-5, data-6a" in text and "primary-p2" in text
    assert sorted(t["function"]["name"] for t in first["tools"]) == ["fetch_page", "register_facts", "search_web"]
    assert first["options"]["seed"] == 5 and first["think"] == "high"
    # the tool result the model got back names each fact's statuses
    last_tool = [m for m in script.bodies[3]["messages"] if m["role"] == "tool"][-1]["content"]
    assert "quote_not_found" in last_tool and "usable" in last_tool


def test_a_session_that_never_finishes_is_marked_incomplete(tmp_path, monkeypatch, stub_world):
    f = _fact(source="query:Q1", quote="contract backlog stood at $3.1 billion", value=3.1, entity="Danaos fleet", metric="contract backlog")
    d, script = _run(tmp_path, monkeypatch, call("search_web", query="q"), _facts_call(f), call("search_web", query="q2"), max_turns=3)
    assert d["done"] is False and d["incomplete"] is True and d["incomplete_reason"] == "turn_budget"
    assert d["counts"]["facts"] == 1 and d["summary"] == ""
    assert any("Two turns remain" in str(m["content"]) for m in script.bodies[2]["messages"])


def test_a_turn_without_a_tool_call_gets_one_nudge_then_ends_incomplete(tmp_path, monkeypatch, stub_world):
    d, script = _run(tmp_path, monkeypatch, {"role": "assistant", "content": "Here is my view."}, {"role": "assistant", "content": "Still my view."})
    assert d["incomplete"] is True and d["incomplete_reason"] == "no_tool_call" and len(script.bodies) == 2
    assert script.bodies[1]["messages"][-1]["content"] == r26.NUDGE


def test_done_without_a_summary_is_not_accepted(tmp_path, monkeypatch, stub_world):
    d, script = _run(tmp_path, monkeypatch, call("register_facts", facts=[], done=True), call("register_facts", facts=[], done=True, research_summary="Fine."))
    assert d["done"] is True and d["summary"] == "Fine." and len(script.bodies) == 2
    assert "not accepted" in [m for m in script.bodies[1]["messages"] if m["role"] == "tool"][-1]["content"]


def test_a_repeated_fact_id_is_rejected_and_a_malformed_fact_is_kept_unusable(tmp_path, monkeypatch, stub_world):
    good = _fact(source="query:Q1", quote="contract backlog stood at $3.1 billion", value=3.1, entity="Danaos fleet", metric="contract backlog")
    bad = dict(_fact(fact_id="F9"), basis="made up")
    d, _ = _run(tmp_path, monkeypatch, call("search_web", query="q"), _facts_call(good, dict(good), bad),
                call("register_facts", facts=[], done=True, research_summary="x"))
    assert [f["fact_id"] for f in d["facts"]] == ["F1", "F9"] and d["rejected"] == [{"fact_id": "F1", "why": "fact_id already registered"}]
    assert d["facts"][1]["usable"] is False and d["facts"][1]["unusable_reason"].startswith("malformed: basis must be one of")


def test_a_summary_over_600_words_is_annotated_not_cut(tmp_path, monkeypatch, stub_world):
    d, _ = _run(tmp_path, monkeypatch, call("register_facts", facts=[], done=True, research_summary="word " * 700))
    assert d["summary_over_600_words"] is True and d["summary_words"] == 700 and d["done"] is True


def test_the_search_budget_ends_research_but_not_registration(tmp_path, monkeypatch, stub_world):
    d, script = _run(tmp_path, monkeypatch, call("search_web", query="a"), call("search_web", query="b"),
                     call("register_facts", facts=[], done=True, research_summary="s"), max_search_calls=1)
    assert [t["function"]["name"] for t in script.bodies[1]["tools"]] == ["register_facts"] and d["done"] is True


def test_the_stage_sessions_take_only_the_artifacts_the_spec_names():
    assert r26.fresh_messages("stage1", {"blind_pack": "P", "task": "T"})[1]["content"].endswith("T")
    with pytest.raises(ValueError, match="may not be handed"):
        r26.fresh_messages("stage1", {"blind_pack": "P", "task": "T", "price": 10})
    with pytest.raises(ValueError, match="may not be handed"):
        r26.fresh_messages("stage3", {"dossier": {}, "stage2_reasoning": "text"})
    with pytest.raises(ValueError, match="may not be handed"):
        r26.fresh_messages("stage2", {"blind_pack": "", "consensus_corrected": {}})
    # stages 2-4 are built (brief R26-A2, tests/test_r26_stages24.py): their sessions are made from the same allow-lists
    assert r26.fresh_messages("stage2", {"blind_pack": "P", "task": "T"})[1]["content"].endswith("T")
    assert set(r26.ARTIFACTS.values()) == {"dossier.json", "forecasts.json", "reveal.json", "final.json"}


# ---------------------------------------------------------------- coordinator ruling 2: the pack company's name for pack: sources only

def test_pack_company_name_and_ticker_satisfy_entity_words_for_pack_sources_only():
    q = "Operating revenues increased by $12.2 million."
    pack_text = "## DATA 5 - X\n" + q + (" ." * 300) + "\n"
    ev = r26.Evidence(pack_text, {})
    led = r26.Ledger(ev, company="Danaos Corporation", ticker="DAC")
    f = _fact(source="pack:data-5", quote=q, entity="Danaos Corporation DAC", metric="operating revenues", value=12.2)
    led.register({"facts": [f]})
    r = led.facts[0]
    assert r["usable"] and r["statuses"]["entity_from_pack_company"] == ["danaos"] and r["statuses"]["missing_words"] == []
    # a metric word is never waived, and other entity words still count
    led.register({"facts": [dict(f, fact_id="F2", entity="Danaos fleet", metric="danaos revenues")]})
    assert led.facts[1]["statuses"]["missing_words"] == ["danaos", "fleet"] and not led.facts[1]["usable"]
    # page: sources stay strict
    ev.fetched["https://x.test/a"] = "https://x.test/a"
    ev.url_cache["https://x.test/a"] = {"full_text": q + (" ." * 300)}
    led.register({"facts": [dict(f, fact_id="F3", source="page:https://x.test/a")]})
    assert led.facts[2]["statuses"]["missing_words"] == ["danaos"] and "entity_from_pack_company" not in led.facts[2]["statuses"] and not led.facts[2]["usable"]

"""Revision 19, Part G: harness support for the acceptance run (brief_rev19.md section 8). No behaviour change in production.

  G1 the per-sample evidence caches a session made itself are written down (record only: the messages and tool results are the same with and without);
  G2 `--seed-base K`: sample i draws with seed K + i (1000 by default, as before), recorded in consensus.json, the retry offsets kept;
  G3 frozen-replay parity: the desk context a `--pack-file` replay builds from the sidecar equals the fresh run's, key for key and value for value
     (the four development names' packs are checked by tools/acceptance_r19/g3_replay_parity.py).
Every session is the real loop with a mocked `_post` (urlopen): no network, no model.
"""
import copy
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import pack_facts  # noqa: E402
from test_desk_continuation import MEMO, _call, _desk, _serve, _snap, _turn  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN, _ctx, _happy_params  # noqa: E402

OK = _happy_params(**_ALL_REASONS_GIVEN)


# ---- G1: the evidence caches ---------------------------------------------------------------------------------------------------------------

def _stubs(monkeypatch):
    """A search and a page fetch with no network, that fill the cache dicts they are given as the real ones do."""
    def search(query, why="", snap=None, n=6, query_cache=None):
        res = {"query": query, "n_results": 1, "results": [{"title": "T", "url": "https://example.com/a", "snippet": "a snippet about the query"}]}
        if query_cache is not None:
            query_cache[query.strip().lower()] = res
        return res

    def fetch(url, snap=None, cap=9000, url_cache=None, known_urls=None, _fallback=True):
        res = {"url": url, "text": "the page text of " + url, "chars": 20, "parts": 1}
        if url_cache is not None:
            url_cache[url] = {"url": url, "chars": 20, "text": res["text"]}
        return res
    monkeypatch.setattr(at, "search_web", search)
    monkeypatch.setattr(at, "fetch_page", fetch)


def _script():
    return [_turn(tool_calls=_call("search_web", {"query": "Testco capex guidance"})),
            _turn(tool_calls=_call("fetch_page", {"url": "https://example.com/a"})),
            _desk(OK), _turn(MEMO)]


def _session(monkeypatch, tmp_path, **kw):
    bodies = _serve(monkeypatch, _script())
    _stubs(monkeypatch)                               # after _serve: its search stub refuses the network
    report, think, meta = at.chat_with_tools("test-model", "test-pack", tmp_path, verbose=False, desk_context=_ctx(price=50.0), **kw)
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))
    return bodies, report, meta, snap


def _stable(meta):
    return {k: v for k, v in meta.items() if k not in ("elapsed_s",)}


def test_a_session_that_made_its_own_caches_writes_them_down(monkeypatch, tmp_path):
    _, _, _, snap = _session(monkeypatch, tmp_path)
    q = json.loads((tmp_path / "evidence_query_cache.json").read_text(encoding="utf-8"))
    u = json.loads((tmp_path / "evidence_url_cache.json").read_text(encoding="utf-8"))
    assert list(q) == ["testco capex guidance"] and q["testco capex guidance"]["results"][0]["url"] == "https://example.com/a"
    assert u["https://example.com/a"]["text"] == "the page text of https://example.com/a"      # the full page, which the snapshot's parts do not hold in one piece


def test_a_cache_the_caller_passed_is_the_callers_to_persist_and_is_not_written(monkeypatch, tmp_path):
    qc, uc = {}, {}
    _session(monkeypatch, tmp_path, query_cache=qc, url_cache=uc)
    assert qc and uc and not (tmp_path / "evidence_query_cache.json").exists() and not (tmp_path / "evidence_url_cache.json").exists()
    # only the one it made: a caller passing the page cache alone still gets the query cache written
    _session(monkeypatch, tmp_path / "half", url_cache={})
    assert (tmp_path / "half" / "evidence_query_cache.json").exists() and not (tmp_path / "half" / "evidence_url_cache.json").exists()


def test_the_messages_and_tool_results_are_identical_with_and_without_the_write(monkeypatch, tmp_path):
    a_bodies, a_report, a_meta, a_snap = _session(monkeypatch, tmp_path / "write")
    monkeypatch.setattr(at, "_write_own_evidence_caches", lambda *a, **k: None)
    b_bodies, b_report, b_meta, b_snap = _session(monkeypatch, tmp_path / "nowrite")
    assert (tmp_path / "write" / "evidence_query_cache.json").exists() and not (tmp_path / "nowrite" / "evidence_query_cache.json").exists()
    assert a_bodies == b_bodies                                    # every request the model was sent, message for message
    assert a_report == b_report and _stable(a_meta) == _stable(b_meta)

    def strip(snap):
        out = copy.deepcopy(snap)
        out.pop("elapsed_s", None)
        for c in out.get("calls", []):
            c.pop("ts", None)
        return out
    assert strip(a_snap) == strip(b_snap)                          # and every tool result the snapshot recorded
    # the same again with caller-passed caches (the other branch of the condition)
    c_bodies, c_report, c_meta, _ = _session(monkeypatch, tmp_path / "own", query_cache={}, url_cache={})
    assert c_bodies == a_bodies and c_report == a_report


# ---- G2: --seed-base -------------------------------------------------------------------------------------------------------------------

SAMPLE_PACK = ("## SECTION 8: EXPECTATIONS & CONSENSUS RECONCILIATION\n| Period | Revenue Avg | Low | High | Analysts | Growth |\n"
               "| next FY | $10.0B | $9.5B | $10.5B | 10 | +3.9% |\n- CONSENSUS-IMPLIED VALUE: $120.00\n- Shares outstanding: 1,000,000,000\n")
MEMO12 = ("SECTION 0. EXECUTIVE VERDICT\n" + "\n".join(f"  detail line {n} of the institutional memorandum." for n in range(400)) +
          "\nSECTION 12. MACHINE CONTRACT\n```json:underwriting\n"
          '{"base_iv": 120.0, "bull_iv": 140.0, "bear_iv": 100.0, "verdict_label": "undervalued", "base_probability": 0.5, "bull_probability": 0.3, '
          '"bear_probability": 0.2, "conviction_score": 10, "business_quality_moat": 3, "kelly_fraction_pct": 2.0, "base_cf_used": 1.0, '
          '"base_cf_basis": "other", "stage1_growth_path": [0.1, 0.08, 0.04, 0.04, 0.04]}\n```\n')


def _run_main(monkeypatch, tmp_path, extra_argv, *, empty_first=True, tools=True):
    seeds = []

    def fake_chat(model, content, out_dir, **kwargs):
        seeds.append(kwargs.get("seed"))
        if empty_first and len(seeds) == 1:
            return "", "thinking", {"done_reason": "stop", "generated_tokens": 10, "eval_rate": 10.0, "eval_duration_s": 1.0}
        return MEMO12, "thinking", {"done_reason": "stop", "generated_tokens": 100, "eval_rate": 10.0, "eval_duration_s": 1.0}
    monkeypatch.setattr(at, "chat_with_tools", fake_chat)
    tmp_path.mkdir(parents=True, exist_ok=True)
    pack_file = tmp_path / "pack.md"
    pack_file.write_text(SAMPLE_PACK, encoding="utf-8")
    out_dir = tmp_path / "out"
    argv = ["consensus_valuation.py", "TEST", "--price", "100.0", "--samples", "2", "--pack-file", str(pack_file), "--out-dir", str(out_dir)]
    monkeypatch.setattr(sys, "argv", argv + (["--tools"] if tools else []) + extra_argv)
    cv.main()
    doc = json.loads(next(out_dir.glob("TEST_*")).joinpath("consensus.json").read_text(encoding="utf-8"))
    return seeds, doc


def test_the_default_seed_base_is_1000_as_before_and_is_recorded(monkeypatch, tmp_path):
    assert cv.SEED_BASE_DEFAULT == 1000
    seeds, doc = _run_main(monkeypatch, tmp_path, [])
    # sample 1: its empty report is retried with seed + 50000; sample 2 draws once
    assert seeds == [1001, 1001 + 50000, 1002] and doc["seed_base"] == 1000


def test_seed_base_k_gives_sample_i_the_seed_k_plus_i_and_the_retry_offset_is_kept(monkeypatch, tmp_path):
    seeds, doc = _run_main(monkeypatch, tmp_path, ["--seed-base", "7000"])
    assert seeds == [7001, 7001 + 50000, 7002] and doc["seed_base"] == 7000
    seeds, doc = _run_main(monkeypatch, tmp_path / "zero", ["--seed-base", "0"])
    assert seeds == [1, 1 + 50000, 2] and doc["seed_base"] == 0                       # 0 is a value, not an absence


def test_the_no_tools_path_and_the_continuation_use_the_seed_base_too(monkeypatch, tmp_path):
    bodies = []

    class _R:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self, n=-1):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        empty = len(bodies) == 1
        return _R({"message": {"content": "" if empty else MEMO12, "thinking": "t"}, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 10})
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    pack_file = tmp_path / "pack.md"
    pack_file.write_text(SAMPLE_PACK, encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "TEST", "--price", "100.0", "--samples", "1", "--pack-file", str(pack_file),
                                      "--out-dir", str(out_dir), "--seed-base", "400"])
    cv.main()
    assert [b["options"]["seed"] for b in bodies] == [401, 401 + 50000]
    # a truncated report is continued with the +100 offset
    seen = {}
    monkeypatch.setattr(cv, "continue_report", lambda **kw: (seen.update(kw), ("", "", {"done_reason": "error"}))[1])
    bodies.clear()

    def truncated(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return _R({"message": {"content": "x" * 2000, "thinking": "t"}, "done_reason": "length", "prompt_eval_count": 10, "eval_count": 10})
    monkeypatch.setattr(urllib.request, "urlopen", truncated)
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "TEST", "--price", "100.0", "--samples", "1", "--pack-file", str(pack_file),
                                      "--out-dir", str(tmp_path / "out2"), "--seed-base", "400"])
    cv.main()
    assert seen["seed"] == 401 + 100


def test_no_literal_1000_seed_remains_in_the_harness():
    src = Path(HERE / "audit_202608" / "consensus_valuation.py").read_text(encoding="utf-8")
    assert "1000 + i" not in src and src.count("seed_base + i") == 5


# ---- G3: frozen-replay parity ----------------------------------------------------------------------------------------------------------------

def _sidecar_round_trip(facts, tmp_path):
    pack_facts.write_sidecar(tmp_path, facts)
    return pack_facts.read_sidecar(tmp_path)


def _equal(a, b, path=""):
    """Key for key and value for value (a float nan equals itself; +inf equals +inf); returns the paths that differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}/{k}")
            else:
                out += _equal(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return [f"{path}[len]"] if len(a) != len(b) else [d for i, (x, y) in enumerate(zip(a, b)) for d in _equal(x, y, f"{path}[{i}]")]
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return []
    return [] if (a == b and type(a) is type(b)) else [path]


def test_the_replay_context_from_the_sidecar_equals_the_fresh_runs_for_a_built_pack(screener_data_stub, monkeypatch, tmp_path):
    from test_rev18_part1 import _pack_with_bill_rate
    pack = _pack_with_bill_rate(monkeypatch, 0.04)
    fresh = cv.build_desk_context(pack.facts, 123.45, "GEV", "GE Vernova Inc.")
    replay = cv.build_desk_context(_sidecar_round_trip(pack.facts, tmp_path), 123.45, "GEV", "GE Vernova Inc.")
    assert _equal(fresh, replay) == []
    assert fresh["rf_eff"] is not None and fresh["nominal_gdp_trend"] is not None and fresh["base_year_cash_and_investments_b"] is not None
    assert set(fresh) >= {"price", "levels", "long_run", "working_capital", "terminal_ronic", "rf_eff", "nominal_gdp_trend", "ticker", "company"}


def test_the_replay_context_survives_an_infinite_return_and_the_no_reference_pack(screener_data_stub, monkeypatch, tmp_path):
    from test_throughcycle_reference import _synthetic_pack
    # a facts object whose terminal_ronic is +inf: JSON writes Infinity and reads it back as the same float
    pack = _synthetic_pack(monkeypatch)
    facts = dict(pack.facts, terminal_ronic=math.inf)
    fresh = cv.build_desk_context(facts, 50.0, "GEV", "GEV")
    replay = cv.build_desk_context(_sidecar_round_trip(facts, tmp_path), 50.0, "GEV", "GEV")
    assert _equal(fresh, replay) == [] and replay["terminal_ronic"] == math.inf
    # a pack with no reference
    nope = _synthetic_pack(monkeypatch, enrich_override={"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "estimates": None})
    d2 = tmp_path / "nope"
    d2.mkdir()
    assert _equal(cv.build_desk_context(nope.facts, 50.0, "GEV", "GEV"), cv.build_desk_context(_sidecar_round_trip(nope.facts, d2), 50.0, "GEV", "GEV")) == []


def test_the_replay_context_is_the_one_function_main_uses():
    src = Path(HERE / "audit_202608" / "consensus_valuation.py").read_text(encoding="utf-8")
    assert "desk_context = build_desk_context(facts, price, t, company_name, run_date=datetime.now().date().isoformat())" in src and src.count("desk_context = {") == 0


def test_the_desk_context_carries_the_runs_date_and_the_desk_holds_a_citation_to_it(screener_data_stub):
    """C7: the crux's form check read today's date when the context had none, so a replay of an older run judged its citations against the wrong day."""
    import consensus_valuation as cv
    import financial_model_tool as fmt
    import capability_test as cap
    pack = cap.build_pack("GEV")
    assert cv.build_desk_context(pack.facts, 123.45, "GEV", "GE Vernova Inc.")["run_date"] is None
    ctx = cv.build_desk_context(pack.facts, 123.45, "GEV", "GE Vernova Inc.", run_date="2020-06-01")
    assert ctx["run_date"] == "2020-06-01" and len(ctx) == len(cv.build_desk_context(pack.facts, 123.45, "GEV", "GE Vernova Inc."))
    problems = lambda d, c: fmt.crux_check.form_problems([{"input": "coe", "reason": "r", "citations": [{"source": "DATA 5", "date": d, "quote": "q" * 40}]}],
                                                         c.get("run_date") or fmt.datetime.date.today().isoformat())
    assert any("is after the run's date 2020-06-01" in x for x in problems("2021-01-01", ctx))                    # today's date would have let it pass
    assert problems("2021-01-01", cv.build_desk_context(pack.facts, 123.45, "GEV", "GE Vernova Inc.")) == []


def test_the_equality_helper_sees_a_difference():
    assert _equal({"a": [1, 2.0], "b": None}, {"a": [1, 2.0], "b": None}) == []
    assert _equal({"a": [1, 2.0]}, {"a": [1, 2]}) == ["/a[1]"] and _equal({"a": 1}, {"b": 1}) == ["/a", "/b"]
    assert _equal({"a": (1, 2)}, {"a": [1, 3]}) == ["/a[1]"] and _equal(float("nan"), float("nan")) == []

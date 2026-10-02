"""Muse integration, M6 and M8 item 6: the engine and model digests reach every record, each at its owner, and an Ollama run's
records are unchanged.

  per turn      analyst_tools.turn_metrics: engine, draft_n, draft_n_accepted, reasoning_in_content, sampling_stripped,
                ignored_options, system_injected, when the response carries them
  per sample    chat_with_tools meta and the `runs` rows of consensus.json: engine (first turn), engine_consistent, draft totals
  per run       consensus.json: provider, engine
  per verdict   depth_pipeline.band_verdict: model (the tag) and serving
  downstream    the overlay copies the whole row; the forward ledger's reader ignores the extra key

seed_base (also listed in M6 for consensus.json) is revision 19's G2 and is not built here."""
import copy
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
REPO = AUDIT_DIR.parents[1]
for p in (str(AUDIT_DIR), str(REPO), str(REPO / "tests"), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
sys.stdout = _ORIG_STDOUT

import analyst_tools as at  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import depth_pipeline as dp  # noqa: E402
import llm_provider as prov  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
from llamacpp_fakes import chat_body, completion, fake_llama, muse_env, tool_call  # noqa: E402,F401
from test_consensus_anchor_gate import _DUMMY_PACK, _SAMPLE_MEMO  # noqa: E402

REPORT = "y" * 6000
OLD_TURN_KEYS = {"prompt_tokens", "prompt_eval_s", "gen_tokens", "gen_s", "load_s", "done_reason", "n_tool_calls"}
OLD_META_KEYS = {"tool_calls", "done_reason", "stub_rejected", "turns", "generated_tokens", "eval_duration_s", "eval_rate",
                 "evidence_hits", "evidence_misses", "research_calls", "repeat_calls", "desk_runs", "desk_validation_errors",
                 "report_turn_headroom_tokens", "elapsed_s", "think_configured", "failure", "window_retry_used",
                 "continuation_for_desk"}
SERVING_KEYS = {"provider", "build", "build_manifest_sha256", "model_sha256", "drafter_sha256", "server_cmdline_sha256",
                "system_sha256", "provider_sha256"}


# ------------------------------------------------------------------ per turn: turn_metrics

BASE = {"message": {"content": "x"}, "done_reason": "stop", "prompt_eval_count": 5, "eval_count": 3}


def test_an_ollama_turn_record_is_unchanged():
    assert set(at.turn_metrics(BASE)) == OLD_TURN_KEYS


def test_every_provenance_field_the_response_carries_reaches_the_turn_record():
    eng = {"pid": 7, "build": "b11272"}
    resp = dict(BASE, engine=eng, draft_n=30, draft_n_accepted=21, reasoning_in_content=False,
                sampling_stripped={"temperature": 0.6}, ignored_options=["num_ctx", "think"], system_injected=True)
    t = at.turn_metrics(resp)
    assert t["engine"] == eng and t["draft_n"] == 30 and t["draft_n_accepted"] == 21
    assert t["reasoning_in_content"] is False and t["sampling_stripped"] == {"temperature": 0.6}
    assert t["ignored_options"] == ["num_ctx", "think"] and t["system_injected"] is True
    assert set(t) == OLD_TURN_KEYS | set(at.TURN_PROVENANCE_KEYS)


def test_zero_false_empty_and_none_are_values_not_absences():
    t = at.turn_metrics(dict(BASE, draft_n=0, draft_n_accepted=0, reasoning_in_content=False, sampling_stripped={},
                             ignored_options=[], system_injected=False))
    assert t["draft_n"] == 0 and t["draft_n_accepted"] == 0 and t["reasoning_in_content"] is False
    assert t["sampling_stripped"] == {} and t["ignored_options"] == [] and t["system_injected"] is False
    t2 = at.turn_metrics(dict(BASE, draft_n=None, draft_n_accepted=None))         # a plain server reports no draft counters
    assert "draft_n" in t2 and t2["draft_n"] is None and "engine" not in t2


def test_only_the_fields_present_are_recorded():
    assert set(at.turn_metrics(dict(BASE, system_injected=True))) == OLD_TURN_KEYS | {"system_injected"}


def test_the_provenance_keys_are_exactly_the_briefs_list():
    assert at.TURN_PROVENANCE_KEYS == ("engine", "draft_n", "draft_n_accepted", "reasoning_in_content", "sampling_stripped",
                                       "ignored_options", "system_injected")


def test_the_cause_of_a_refused_turn_is_recorded_only_when_there_is_one():
    assert "server_error_cause" not in at.turn_metrics({"message": {}, "done_reason": "server_error", "http_status": 500})
    t = at.turn_metrics({"message": {}, "done_reason": "server_error", "http_status": 500, "server_error_cause": "context_overflow"})
    assert t["server_error_cause"] == "context_overflow"


# ------------------------------------------------------------------ per sample: chat_with_tools meta

@pytest.fixture
def session(muse_env, monkeypatch, tmp_path):
    monkeypatch.setattr(at, "search_web", lambda *a, **k: {"results": [], "n_results": 0, "query": "q"})

    def go(**kw):
        return at.chat_with_tools(muse_env.cfg["model_tag"], "PACK", tmp_path / "s", think="high", verbose=False,
                                  max_model_calls=0, **kw)
    return go


def test_every_turn_and_the_sample_carry_the_engine_and_the_draft_totals(muse_env, session, tmp_path):
    muse_env.fake.script = [("json", 200, completion("", finish="tool_calls", tool_calls=[tool_call()])),
                            ("json", 200, completion(REPORT))]
    rep, think, meta = session()
    assert rep == REPORT and meta["failure"] is None and len(meta["turns"]) == 2
    engine = json.loads(muse_env.engine_file.read_text(encoding="utf-8"))
    for t in meta["turns"]:
        assert t["engine"] == engine and t["draft_n"] == 30 and t["draft_n_accepted"] == 21
        assert t["reasoning_in_content"] is False and t["sampling_stripped"] == {"presence_penalty": 0.05}
        assert t["system_injected"] is True and "num_ctx" in t["ignored_options"] and "think" in t["ignored_options"]
    assert meta["engine"] == engine and meta["engine_consistent"] is True
    assert meta["draft_n"] == 60 and meta["draft_n_accepted"] == 42
    snap = json.loads((tmp_path / "s" / "_research_snapshot.json").read_text(encoding="utf-8"))
    assert all("engine" in t and "draft_n" in t for t in snap["turns"])


def test_a_mid_sample_engine_change_is_flagged(muse_env, monkeypatch, tmp_path):
    muse_env.fake.script = [("json", 200, completion("", finish="tool_calls", tool_calls=[tool_call()])),
                            ("json", 200, completion(REPORT))]

    def swap(*a, **k):
        muse_env.write_engine(vram_loaded_mib=20000)             # a different record; every pin still holds
        return {"results": [], "n_results": 0, "query": "q"}
    monkeypatch.setattr(at, "search_web", swap)
    rep, think, meta = at.chat_with_tools(muse_env.cfg["model_tag"], "PACK", tmp_path / "s", think="high", verbose=False,
                                          max_model_calls=0)
    assert meta["engine_consistent"] is False and meta["engine"]["vram_loaded_mib"] == 21937


def test_zero_draft_counts_sum_as_zero_not_none(muse_env, session):
    from llamacpp_fakes import timings
    muse_env.fake.script = [("json", 200, completion(REPORT, tim=timings(draft_n=0, draft_n_accepted=0)))]
    rep, think, meta = session()
    assert meta["draft_n"] == 0 and meta["draft_n_accepted"] == 0


def test_a_plain_server_without_draft_counters_gives_none_totals(muse_env, session):
    muse_env.fake.script = [("json", 200, completion(REPORT, tim={"prompt_ms": 1.0, "predicted_ms": 2.0, "predicted_n": 3}))]
    rep, think, meta = session()
    assert meta["draft_n"] is None and meta["draft_n_accepted"] is None and meta["engine_consistent"] is True


def test_an_ollama_sample_meta_and_turns_are_unchanged(monkeypatch, tmp_path):
    import urllib.request

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"message": {"role": "assistant", "content": REPORT}, "done_reason": "stop", "eval_count": 5,
                               "prompt_eval_count": 50, "prompt_eval_duration": 1, "eval_duration": 2}).encode()
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: R())
    rep, think, meta = at.chat_with_tools("m", "PACK", tmp_path / "s", think=False, verbose=False, max_model_calls=0)
    assert set(meta) == OLD_META_KEYS
    assert set(meta["turns"][0]) == OLD_TURN_KEYS | {"turn", "think", "est_prompt_tokens", "num_predict"}


def test_turns_provenance_of_no_engine_is_empty_and_zero_is_kept():
    assert prov.turns_provenance([]) == {} and prov.turns_provenance([{"done_reason": "stop"}]) == {}
    out = prov.turns_provenance([{"engine": {"a": 1}, "draft_n": 0, "draft_n_accepted": 0}, {"engine": {"a": 1}, "draft_n": 0}])
    assert out == {"engine": {"a": 1}, "engine_consistent": True, "draft_n": 0, "draft_n_accepted": 0}


# ------------------------------------------------------------------ per sample and per run: consensus.json

def _frozen_pack(tmp_path):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    pack_file = frozen / "_pack.md"
    pack_file.write_text(_DUMMY_PACK, encoding="utf-8")
    facts = pack_facts.from_text(_DUMMY_PACK)
    facts["source"] = "build"
    facts["consensus_data_status"] = "enrich_missing"
    pack_facts.write_sidecar(frozen, facts)
    return pack_file


def _run_cv(monkeypatch, tmp_path, capsys, model, extra=()):
    pack_file = _frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--model", model, "--ctx", "98304", "--price", "100",
                                      "--samples", "1", "--no-early-stop", "--pack-file", str(pack_file),
                                      "--out-dir", str(out_dir), *extra])
    cv.main()
    capsys.readouterr()
    (d,) = out_dir.glob("GEV_*")
    return json.loads((d / "consensus.json").read_text(encoding="utf-8"))


def test_the_runs_row_and_the_doc_carry_the_engine_under_llamacpp(muse_env, monkeypatch, tmp_path, capsys, screener_data_stub):
    muse_env.fake.script = [("json", 200, completion(_SAMPLE_MEMO, usage=(100, 500)))]
    doc = _run_cv(monkeypatch, tmp_path, capsys, muse_env.cfg["model_tag"])
    engine = json.loads(muse_env.engine_file.read_text(encoding="utf-8"))
    (row,) = doc["runs"]
    assert row["engine"] == engine and row["engine_consistent"] is True and row["draft_n"] == 30 and row["draft_n_accepted"] == 21
    assert doc["provider"] == "llamacpp" and doc["engine"] == engine
    assert doc["model"] == muse_env.cfg["model_tag"]


def test_the_runs_row_copies_a_tools_sessions_meta(muse_env, monkeypatch, tmp_path, capsys, screener_data_stub):
    meta_engine = {"pid": 1, "build": "b11272"}

    def fake_session(model, pack, out_dir, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        return _SAMPLE_MEMO, "", {"tool_calls": 0, "done_reason": "stop", "generated_tokens": 500, "eval_rate": 40.0,
                                  "eval_duration_s": 12.0, "engine": meta_engine, "engine_consistent": False,
                                  "draft_n": 100, "draft_n_accepted": 0, "turns": [], "failure": None}
    monkeypatch.setattr(at, "chat_with_tools", fake_session)
    doc = _run_cv(monkeypatch, tmp_path, capsys, muse_env.cfg["model_tag"], extra=("--tools",))
    (row,) = doc["runs"]
    assert row["engine"] == meta_engine and row["engine_consistent"] is False
    assert row["draft_n"] == 100 and row["draft_n_accepted"] == 0                   # 0 is a value
    assert doc["engine"] == meta_engine and doc["provider"] == "llamacpp"


def test_an_ollama_run_has_a_provider_and_nothing_else_new(monkeypatch, tmp_path, capsys, screener_data_stub):
    import urllib.request

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"message": {"content": _SAMPLE_MEMO}, "done_reason": "stop", "eval_count": 500,
                               "prompt_eval_count": 100}).encode()
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: R())
    doc = _run_cv(monkeypatch, tmp_path, capsys, "m")
    (row,) = doc["runs"]
    assert doc["provider"] == "ollama" and "engine" not in doc
    for k in ("engine", "engine_consistent", "draft_n", "draft_n_accepted"):
        assert k not in row


def test_doc_provenance_names_the_provider_and_takes_the_first_engine():
    assert prov.doc_provenance([{"iv": 1}]) == {"provider": prov.provider_name()}
    assert prov.doc_provenance([{"iv": 1}, {"engine": {"e": 1}}, {"engine": {"e": 2}}])["engine"] == {"e": 1}


def test_run_row_provenance_prefers_the_session_meta_then_the_response():
    assert prov.run_row_provenance({}, {}) == {} and prov.run_row_provenance(None, None) == {}
    assert prov.run_row_provenance({"engine": {"a": 1}, "engine_consistent": True, "draft_n": 0, "draft_n_accepted": 0}, {}) == {
        "engine": {"a": 1}, "engine_consistent": True, "draft_n": 0, "draft_n_accepted": 0}
    assert prov.run_row_provenance({}, {"engine": {"b": 2}, "draft_n": 3, "draft_n_accepted": 1}) == {
        "engine": {"b": 2}, "engine_consistent": True, "draft_n": 3, "draft_n_accepted": 1}


# ------------------------------------------------------------------ per verdict row: band_verdict

def _doc(**over):
    d = {"ticker": "TEST", "price": 100.0, "model": "the-tag", "runs": [{"iv": 120.0, "plausible": True, "truncated": False,
                                                                       "flags": [], "basis": True}],
         "median_iv": 120.0, "spread_pct": None, "samples_run": 1}
    d.update(over)
    return d


def test_the_verdict_row_serving_under_llamacpp_is_the_pins_of_the_engine_that_answered(muse_env):
    engine = json.loads(muse_env.engine_file.read_text(encoding="utf-8"))
    v = dp.band_verdict(_doc(provider="llamacpp", engine=engine, model=muse_env.cfg["model_tag"]))
    assert v["model"] == muse_env.cfg["model_tag"]
    cfg = muse_env.cfg
    assert v["serving"] == {"provider": "llamacpp", "build": cfg["build"], "build_manifest_sha256": cfg["build_manifest_sha256"],
                            "model_sha256": cfg["model_sha256"], "drafter_sha256": cfg["drafter_sha256"],
                            "server_cmdline_sha256": cfg["server_cmdline_sha256"], "system_sha256": cfg["system_sha256"],
                            "provider_sha256": prov.provider_sha256()}
    assert set(v["serving"]) == SERVING_KEYS


def test_a_llamacpp_verdict_with_no_engine_shows_the_gap_as_none(muse_env):
    v = dp.band_verdict(_doc(provider="llamacpp", model=muse_env.cfg["model_tag"]))
    assert v["serving"] == {"provider": "llamacpp", **{k: None for k in SERVING_KEYS - {"provider"}}}


def _ollama_manifest(tmp_path, monkeypatch, model="rs2-analyst-deep-mtp5-v33", tag="latest"):
    d = tmp_path / "ollama_models" / "manifests" / "registry.ollama.ai" / "library" / model
    d.mkdir(parents=True)
    manifest = {"schemaVersion": 2, "layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:aaa"},
                                               {"mediaType": "application/vnd.ollama.image.system", "digest": "sha256:" + "f" * 64}]}
    raw = json.dumps(manifest).encode()
    (d / tag).write_bytes(raw)
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "ollama_models"))
    return hashlib.sha256(raw).hexdigest()


def test_the_verdict_row_serving_under_ollama_is_read_from_the_manifest_file(monkeypatch, tmp_path):
    sha = _ollama_manifest(tmp_path, monkeypatch)
    v = dp.band_verdict(_doc(provider="ollama", model="rs2-analyst-deep-mtp5-v33"))
    assert v["serving"] == {"provider": "ollama", "model": "rs2-analyst-deep-mtp5-v33", "manifest_sha256": sha,
                            "system_layer_digest": "sha256:" + "f" * 64}
    assert v["model"] == "rs2-analyst-deep-mtp5-v33"


def test_an_ollama_model_with_a_tag_is_read_from_its_tag_file(monkeypatch, tmp_path):
    sha = _ollama_manifest(tmp_path, monkeypatch, model="somemodel", tag="q4")
    assert prov.ollama_serving("somemodel:q4")["manifest_sha256"] == sha


def test_an_unreadable_ollama_manifest_gives_none_digests_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "nowhere"))
    v = dp.band_verdict(_doc(provider="ollama", model="rs2-analyst-deep-mtp5"))
    assert v["serving"] == {"provider": "ollama", "model": "rs2-analyst-deep-mtp5", "manifest_sha256": None,
                            "system_layer_digest": None}


def test_a_doc_without_a_provider_gets_no_serving_key(monkeypatch):
    v = dp.band_verdict(_doc())
    assert "serving" not in v and v["model"] == "the-tag"


def test_the_whole_chain_the_verdict_rows_serving_equals_the_pins(muse_env, monkeypatch, tmp_path, capsys, screener_data_stub):
    """registration I2: a run through the provider, then the verdict row built from its consensus.json."""
    muse_env.fake.script = [("json", 200, completion(_SAMPLE_MEMO, usage=(100, 500)))]
    doc = _run_cv(monkeypatch, tmp_path, capsys, muse_env.cfg["model_tag"])
    v = dp.band_verdict(doc)
    cfg = muse_env.cfg
    assert v["model"] == cfg["model_tag"]
    assert v["serving"] == {"provider": "llamacpp", "build": cfg["build"], "build_manifest_sha256": cfg["build_manifest_sha256"],
                            "model_sha256": cfg["model_sha256"], "drafter_sha256": cfg["drafter_sha256"],
                            "server_cmdline_sha256": cfg["server_cmdline_sha256"], "system_sha256": cfg["system_sha256"],
                            "provider_sha256": prov.provider_sha256()}


# ------------------------------------------------------------------ downstream: the overlay and the forward ledger

SERVING = {"provider": "llamacpp", "build": "b11272", "build_manifest_sha256": "a" * 64, "model_sha256": "b" * 64,
           "drafter_sha256": "c" * 64, "server_cmdline_sha256": "d" * 64, "system_sha256": "e" * 64, "provider_sha256": "f" * 64}


def test_the_overlay_copies_the_serving_block_with_the_row(tmp_path, monkeypatch):
    ledger = tmp_path / "depth_ledger.jsonl"
    row = {"ticker": "AAA", "direction": "hold", "gate_version": None, "n_basis": 2, "run_source": "orchestrator",
           "date": "2026-10-02", "model": "the-tag", "serving": SERVING}
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    overlay = tmp_path / "depth_overlay.json"
    monkeypatch.setattr(od, "LEDGER", ledger)
    monkeypatch.setattr(od, "OVERLAY", overlay)
    monkeypatch.setattr(od, "THESIS_CACHE", tmp_path / "depth_thesis.json")
    assert od.rebuild_overlay() == 1
    published = json.loads(overlay.read_text(encoding="utf-8"))["tickers"]["AAA"]
    assert published["serving"] == SERVING and published["model"] == "the-tag"


def test_the_forward_ledgers_reader_ignores_the_extra_key(tmp_path, monkeypatch):
    import depth_membership
    sys.path.insert(0, str(REPO / "tools"))
    import reference_ledger as rl
    monkeypatch.setattr(depth_membership, "_current_book", lambda factor_path=None: [])
    root = tmp_path / "root"
    (root / "cache").mkdir(parents=True)
    row = {"ticker": "AAA", "direction": "undervalued", "date": "2026-10-02", "pack_revision": 19,
           "scorecard": {"base_iv": 150.0}, "serving": SERVING, "model": "the-tag"}
    (root / "cache" / "depth_overlay.json").write_text(json.dumps({"tickers": {"AAA": row}}), encoding="utf-8")
    verdict = rl.production_adapters(root, today=date(2026, 10, 2))["verdict_fn"]("AAA")
    assert verdict == {"label": "undervalued", "base_iv": 150.0, "published_at": "2026-10-02", "pack_revision": 19}
    assert "serving" not in verdict
    ledger_row = {"date": "2026-10-02", "ticker": "AAA", "price": 100.0, "price_date": "2026-10-01", "reference_value": 120.0,
                  "reference_status": "used", "vp": 0.83, "coe": 0.09, "closure_erp": 0.05, "closure_asof": "2026-09-20",
                  "revision": 19, "verdict": verdict}
    rl.validate_row(ledger_row)                                                      # the schema is exactly its own keys


def test_the_depth_ledger_readers_pass_a_row_with_serving_through_unchanged(tmp_path, monkeypatch):
    import depth_triggers
    ledger = tmp_path / "depth_ledger.jsonl"
    row = {"ticker": "AAA", "direction": "hold", "date": "2026-10-02", "serving": SERVING}
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(depth_triggers, "LEDGER", ledger)
    assert depth_triggers.newest_verdicts()["AAA"] == row

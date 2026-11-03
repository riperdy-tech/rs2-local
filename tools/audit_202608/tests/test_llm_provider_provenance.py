"""Muse integration, M6 and M8 item 6: the engine and model digests reach every record, each at its owner, and an Ollama run's
records are unchanged.

  per turn      analyst_tools.turn_metrics: engine, draft_n, draft_n_accepted, reasoning_in_content, sampling_stripped,
                ignored_options, system_injected, when the response carries them
  per sample    chat_with_tools meta and the `runs` rows of consensus.json: engine (first turn), engine_consistent, draft totals
  per run       consensus.json: provider, engine
  per verdict   depth_pipeline.band_verdict: model (the tag) and serving
  downstream    the overlay copies the whole row; the forward ledger's reader ignores the extra key

seed_base (also listed in M6 for consensus.json) is revision 19's G2 and is not built here.

2026-11-03: the llamacpp cases left with the provider (_archive/retired_20261103/README_muse.md); what remains is the Ollama
side and the provider-neutral helpers."""
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
from test_consensus_anchor_gate import _DUMMY_PACK, _SAMPLE_MEMO  # noqa: E402

REPORT = "y" * 6000
OLD_TURN_KEYS = {"prompt_tokens", "prompt_eval_s", "gen_tokens", "gen_s", "load_s", "done_reason", "n_tool_calls"}
OLD_META_KEYS = {"tool_calls", "done_reason", "stub_rejected", "turns", "generated_tokens", "eval_duration_s", "eval_rate",
                 "evidence_hits", "evidence_misses", "research_calls", "repeat_calls", "desk_runs", "desk_validation_errors",
                 "report_turn_headroom_tokens", "elapsed_s", "think_configured", "failure", "window_retry_used",
                 "continuation_for_desk"}


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
    # revision 21: the follow-up record and the refusal count; revision 24 (R24.2): stage B's record and the Base before and after it
    assert set(meta) == OLD_META_KEYS | {"crux_followup", "primary_refusals", "reference_revision", "base_iv_stage_a", "base_iv_final"}
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
    base = {"label": "undervalued", "base_iv": 150.0, "published_at": "2026-10-02", "pack_revision": 19}
    assert {k: verdict[k] for k in base} == base
    # revision 19 (Part E) adds the crux fields; the serving record never reaches the ledger
    assert set(verdict) - set(base) == {"direction_m", "crux_valid", "crux_inputs", "actionable_reasons"}
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

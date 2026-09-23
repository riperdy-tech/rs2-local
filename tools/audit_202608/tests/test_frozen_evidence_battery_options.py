"""tests/test_frozen_evidence_battery_options.py — P4.0b (PHASE_4_ANALYST.md): the new
consensus_valuation.py options the frozen-evidence dispersion battery needs — `--pack-file`,
`--evidence-store`, `--temperature`, `--no-early-stop`, `--out-dir`.

Every test drives `consensus_valuation.main()` against a FAKE Ollama client: `urllib.request`'s
module-level `urlopen` is monkeypatched (both `consensus_valuation.py`'s own `import
urllib.request` inside `main()` and `analyst_tools.py`'s module-level one resolve to the SAME
global module object, so one patch covers both the non-tools and the --tools code paths). Nothing
here touches the GPU, the network, or production cache/ — the repo-root conftest.py's autouse
fixture fails the test if anything under cache/ changes, and every consensus run below is pointed
at a tmp_path via --out-dir precisely so `ab_reports/consensus` is never touched either.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import consensus_valuation as cv  # noqa: E402


MEMO = (
    "SECTION 0. EXECUTIVE VERDICT\n"
    + "\n".join(f"  detail line {n} of the institutional memorandum." for n in range(400))
    + "\nSECTION 12. MACHINE CONTRACT\n"
    "```json:underwriting\n"
    '{"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0, "base_probability": 0.5, '
    '"bull_probability": 0.3, "bear_probability": 0.2, "conviction_score": 10, '
    '"business_quality_moat": 3, "kelly_fraction_pct": 2.0, '
    '"base_cf_used": 1.0, "base_cf_basis": "other"}\n'
    "```\n"
)


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ollama_payload(content=MEMO, **over):
    body = {"message": {"content": content}, "done_reason": "stop",
            "eval_count": 500, "prompt_eval_count": 100}
    body.update(over)
    return body


@pytest.fixture
def fake_ollama(monkeypatch):
    """Every /api/chat turn returns the same complete memorandum (converged, no tool calls);
    every request body sent is recorded in order."""
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(json.loads(req.data.decode()))
        return _FakeResponse(_ollama_payload())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def _out_run_dir(out_dir, ticker="GEV"):
    dirs = list(out_dir.glob(f"{ticker}_*"))
    assert len(dirs) == 1, f"expected exactly one run dir, found {dirs}"
    return dirs[0]


# ---- --pack-file: verbatim reuse, byte-identical, build_pack skipped -------------------------

def test_pack_file_reused_verbatim_and_build_pack_never_called(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    frozen = tmp_path / "frozen_pack.md"
    frozen_content = "# DATA PACK - GEV (frozen)\n\nSome frozen content shared by every sample.\n"
    frozen.write_text(frozen_content, encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("build_pack must not be called when --pack-file is given")
    monkeypatch.setattr(cv.cap, "build_pack", boom)

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir)])
    cv.main()

    d = _out_run_dir(out_dir)
    # byte-identical: the saved _pack.md, and what was actually sent to the model
    assert (d / "_pack.md").read_text(encoding="utf-8") == frozen_content
    assert fake_ollama[0]["messages"][0]["content"] == frozen_content

    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert doc["pack_source"] == f"frozen:{frozen}"
    assert doc["pack_sha256"] == hashlib.sha256(frozen_content.encode("utf-8")).hexdigest()


def test_pack_file_stays_identical_across_every_sample_of_one_run(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    """Pack reuse is byte-identical ACROSS SAMPLES too — sample 2 and 3 must see exactly what
    sample 1 saw, not a re-derived pack."""
    frozen = tmp_path / "frozen_pack.md"
    frozen_content = "# DATA PACK - GEV (frozen)\n\nFixed content.\n"
    frozen.write_text(frozen_content, encoding="utf-8")

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "3",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir)])
    cv.main()

    assert len(fake_ollama) == 3
    contents = {call["messages"][0]["content"] for call in fake_ollama}
    assert contents == {frozen_content}


# ---- --temperature: refusal at 0, parse errors, valid pass-through ----------------------------

def test_temperature_zero_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--temperature", "0"])
    with pytest.raises(ValueError, match="temperature 0 is refused"):
        cv.main()
    assert "HARD FAIL" in capsys.readouterr().out


def test_temperature_not_a_number_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["consensus_valuation.py", "GEV", "--temperature", "not-a-number"])
    with pytest.raises(ValueError):
        cv.main()
    assert "HARD FAIL" in capsys.readouterr().out


def test_valid_temperature_is_passed_through_and_recorded(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--temperature", "0.3", "--out-dir", str(out_dir)])
    cv.main()

    assert fake_ollama[0]["options"]["temperature"] == 0.3
    doc = json.loads((_out_run_dir(out_dir) / "consensus.json").read_text(encoding="utf-8"))
    assert doc["temperature"] == 0.3


def test_no_temperature_flag_records_none(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    """The Modelfile default (0.6) applies when --temperature is not given — the harness never
    passes options.temperature at all, and consensus.json records that honestly as None rather
    than guessing at the Modelfile's current value."""
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--out-dir", str(out_dir)])
    cv.main()

    assert "temperature" not in fake_ollama[0]["options"]
    doc = json.loads((_out_run_dir(out_dir) / "consensus.json").read_text(encoding="utf-8"))
    assert doc["temperature"] is None


# ---- --no-early-stop: runs every requested sample, even when early samples agree --------------

def test_adaptive_mode_early_stops_at_two_agreeing_samples(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    """Baseline: confirms the fake harness DOES trigger the existing early-stop path (both
    samples parse to the same base_iv, well inside the 15% early bar) — the contrast case for
    the next test."""
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv",
                        ["consensus_valuation.py", "GEV", "--price", "100", "--out-dir", str(out_dir)])
    cv.main()
    assert len(fake_ollama) == 2
    doc = json.loads((_out_run_dir(out_dir) / "consensus.json").read_text(encoding="utf-8"))
    assert doc["early_stop"] is True
    assert doc["samples_run"] == 2


def test_no_early_stop_runs_every_requested_sample(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    """Same agreeing samples as above, but --no-early-stop must force the full 3 — the battery
    needs full samples for dispersion, even when the first two would have been enough to stop."""
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--no-early-stop",
        "--out-dir", str(out_dir)])
    cv.main()
    assert len(fake_ollama) == 3
    doc = json.loads((_out_run_dir(out_dir) / "consensus.json").read_text(encoding="utf-8"))
    assert doc["early_stop"] is False
    assert doc["samples_run"] == 3
    assert doc["no_early_stop"] is True


# ---- --out-dir: isolation from ab_reports/consensus --------------------------------------------

def test_out_dir_isolates_the_run_from_ab_reports_consensus(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    before = set(cv.OUT.glob("GEV_*")) if cv.OUT.exists() else set()
    out_dir = tmp_path / "battery_out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--out-dir", str(out_dir)])
    cv.main()

    after = set(cv.OUT.glob("GEV_*")) if cv.OUT.exists() else set()
    assert after == before, "a --out-dir run must never write into ab_reports/consensus"
    assert list(out_dir.glob("GEV_*")), "the run must land under the given --out-dir instead"


def test_default_out_dir_is_still_ab_reports_consensus(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    """Confirms --out-dir is additive, not a behaviour change for every existing caller that
    never passes it (depth_pipeline.run_consensus does not)."""
    monkeypatch.setattr(cv, "OUT", tmp_path / "ab_reports" / "consensus")
    monkeypatch.setattr(sys, "argv",
                        ["consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
                         "--no-early-stop"])
    cv.main()
    assert list(cv.OUT.glob("GEV_*"))


# ---- --evidence-store: round-trips, and shared across every sample of one run -----------------

def test_evidence_store_round_trips_and_is_shared_across_samples(
        monkeypatch, tmp_path, screener_data_stub):
    """Sample 1 issues a search_web call that hits the (fake) network once; sample 2 issues the
    SAME query and must be served from the shared evidence store — no second network call — and
    the store persisted to disk after the run must reload with that query already in it."""
    import analyst_tools as at

    frozen = tmp_path / "frozen_pack.md"
    frozen.write_text("# DATA PACK - GEV (frozen)\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    out_dir = tmp_path / "out"

    QUERY = "GEV fiscal 2027 backlog guidance"
    ollama_calls = []
    search_calls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        if "11434" in url:
            ollama_calls.append(1)
            n = len(ollama_calls)
            if n in (1, 3):
                # turn 1 of each sample: issue the tool call
                payload = {"message": {"content": "", "tool_calls": [
                    {"function": {"name": "search_web", "arguments": {"query": QUERY}}}]},
                           "done_reason": "stop", "eval_count": 10}
            else:
                # turn 2 of each sample: deliver the memorandum, no more tool calls
                payload = _ollama_payload()
            return _FakeResponse(payload)
        # anything else is the SearXNG search call
        search_calls.append(url)
        return _FakeResponse({"results": [
            {"title": "SEC 10-K", "url": "https://example.test/sec-10k",
             "content": "backlog guidance snippet"}]})

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "2", "--no-early-stop",
        "--tools", "--pack-file", str(frozen),
        "--evidence-store", str(evidence_dir), "--out-dir", str(out_dir)])
    cv.main()

    # new queries still hit the web — but only ONCE for a query repeated across samples
    assert len(search_calls) == 1, "sample 2's repeated query must not re-hit the network"

    doc = json.loads((_out_run_dir(out_dir) / "consensus.json").read_text(encoding="utf-8"))
    runs = {r["sample"]: r for r in doc["runs"]}
    assert runs[1]["evidence_store_misses"] >= 1
    assert runs[1]["evidence_store_hits"] == 0
    assert runs[2]["evidence_store_hits"] >= 1, "sample 2 must see what sample 1 already fetched"

    # round-trip: what was saved to disk reloads as the same evidence
    qc, uc = cv._load_evidence_store(evidence_dir)
    assert QUERY in qc
    assert (evidence_dir / "query_cache.json").exists()


def test_evidence_store_hits_and_misses_are_none_when_not_using_the_store(
        monkeypatch, tmp_path, fake_ollama, screener_data_stub):
    """Without --evidence-store the new per-sample fields are None (not 0) — honest absence,
    non-negotiable 4 (rs2-local/AGENTS.md): 0.0 is a value, not an absence."""
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--out-dir", str(out_dir)])
    cv.main()
    doc = json.loads((_out_run_dir(out_dir) / "consensus.json").read_text(encoding="utf-8"))
    assert doc["runs"][0]["evidence_store_hits"] is None
    assert doc["runs"][0]["evidence_store_misses"] is None
    assert doc["evidence_store_dir"] is None

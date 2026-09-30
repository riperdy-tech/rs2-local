"""Revision 17, brief C3: the transcript line says why the text is missing.

openbb_data.fetch() records `transcript_status`; DATA 12 prints a different line for each of ok / not_covered /
source_failed and for a cache written before the field existed. No network: every source is stubbed."""
import json
import socket
import sys
import types
from datetime import datetime as _real_datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))

import capability_test as cap  # noqa: E402
import openbb_data  # noqa: E402

FIXED_UTC = _real_datetime(2026, 9, 29, 23, 59, 0, tzinfo=timezone.utc)


class _FrozenNow(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_UTC if tz is not None else FIXED_UTC.replace(tzinfo=None)


TRANSCRIPT = {"quarter": 2, "year": 2026, "excerpt": "Operator: Good day. CEO: Demand was strong.", "source": "defeatbeta"}


@pytest.fixture
def bench(monkeypatch, tmp_path):
    """openbb_data.fetch() with every source stubbed and its cache and quota redirected. `bench.set(...)`
    chooses what each source does; `bench.fetch()` returns the record fetch() wrote."""
    monkeypatch.setattr(openbb_data, "CACHE", tmp_path)
    monkeypatch.setattr(openbb_data, "_forward_growth", lambda t: {})
    monkeypatch.setattr(openbb_data, "datetime", _FrozenNow)
    state = types.SimpleNamespace(fmp_key=None, fmp_left=100, bumps=[], defeatbeta=None, fmp=None)
    monkeypatch.setattr(openbb_data.quota, "key", lambda name: state.fmp_key)
    monkeypatch.setattr(openbb_data.quota, "remaining", lambda name: state.fmp_left)
    monkeypatch.setattr(openbb_data.quota, "bump", lambda name, n: state.bumps.append((name, n)))

    def defeatbeta(t):
        if isinstance(state.defeatbeta, Exception):
            raise state.defeatbeta
        return state.defeatbeta
    monkeypatch.setattr(openbb_data, "_transcript_defeatbeta", defeatbeta)

    def fmp_transcript(*a, **k):
        if isinstance(state.fmp, Exception):
            raise state.fmp
        return types.SimpleNamespace(results=state.fmp)
    # every other obb call raises AttributeError inside fetch()'s _safe wrappers: those fields stay {}
    monkeypatch.setattr(openbb_data, "_obb", lambda: types.SimpleNamespace(
        equity=types.SimpleNamespace(fundamental=types.SimpleNamespace(transcript=fmp_transcript))))

    def fetch():
        (tmp_path / "openbb_ZZZ.json").unlink(missing_ok=True)       # a cached day is returned as it was written
        return openbb_data.fetch("ZZZ")
    state.fetch = fetch
    return state


def test_a_transcript_from_defeatbeta_is_ok(bench):
    bench.defeatbeta = dict(TRANSCRIPT)
    d = bench.fetch()
    assert d["transcript_status"] == "ok"
    assert d["transcript_excerpt"] == TRANSCRIPT
    assert bench.bumps == []


def test_a_source_that_answers_with_nothing_is_not_covered(bench):
    bench.defeatbeta = None
    d = bench.fetch()
    assert d["transcript_status"] == "not_covered" and d["transcript_excerpt"] is None


def test_a_failing_source_is_source_failed_with_the_error_trimmed_to_80_and_the_date(bench):
    bench.defeatbeta = RuntimeError("HTTP Error: HTTP GET error on 'https://huggingface.co/datasets/bwzheng2010/"
                                    "yahoo-finance-data/resolve/main/data/stock_earning_call_transcripts.parquet' "
                                    "(HTTP 404)")
    d = bench.fetch()
    assert d["transcript_excerpt"] is None
    err = "HTTP Error: HTTP GET error on 'https://huggingface.co/datasets/bwzheng2010/yahoo-finance-data/resolve"[:80]
    assert d["transcript_status"] == f"source_failed: {err} (2026-09-29)"
    assert len(err) == 80


def test_an_error_is_one_line_and_an_empty_message_names_the_exception(bench):
    bench.defeatbeta = RuntimeError("first line\n  second   line")
    assert bench.fetch()["transcript_status"] == "source_failed: first line second line (2026-09-29)"
    bench.defeatbeta = AssertionError()
    assert bench.fetch()["transcript_status"].startswith("source_failed: AssertionError (")


def test_the_status_is_cached_with_the_record(bench, tmp_path):
    bench.defeatbeta = RuntimeError("HTTP 404")
    bench.fetch()
    assert json.loads((tmp_path / "openbb_ZZZ.json").read_text(encoding="utf-8"))["transcript_status"] == \
        "source_failed: HTTP 404 (2026-09-29)"


def test_the_fmp_fallback_runs_only_with_a_key_and_quota_and_is_recorded_too(bench):
    bench.defeatbeta = None
    bench.fmp = [types.SimpleNamespace(content="CEO: Demand was strong.", quarter=2, year=2026)]
    assert bench.fetch()["transcript_status"] == "not_covered"          # no key: the fallback does not run
    assert bench.bumps == []
    bench.fmp_key = "k"
    d = bench.fetch()
    assert d["transcript_status"] == "ok" and d["transcript_excerpt"]["source"] == "fmp"
    assert bench.bumps == [("fmp", 1)]


def test_the_fallback_answering_with_nothing_keeps_not_covered_and_failing_makes_it_source_failed(bench):
    bench.fmp_key = "k"
    bench.defeatbeta, bench.fmp = None, []
    assert bench.fetch()["transcript_status"] == "not_covered"
    bench.fmp = RuntimeError("FMP 402 payment required")
    assert bench.fetch()["transcript_status"] == "source_failed: FMP 402 payment required (2026-09-29)"


def test_a_failed_source_outranks_another_source_that_found_nothing(bench):
    # defeatbeta raised, FMP answered "none": coverage is unknown, not absent
    bench.fmp_key = "k"
    bench.defeatbeta, bench.fmp = RuntimeError("HTTP 404"), []
    assert bench.fetch()["transcript_status"] == "source_failed: HTTP 404 (2026-09-29)"
    # defeatbeta raised, FMP has it: the transcript is there
    bench.fmp = [types.SimpleNamespace(content="CEO: Demand was strong.", quarter=3, year=2026)]
    d = bench.fetch()
    assert d["transcript_status"] == "ok" and d["transcript_excerpt"]["source"] == "fmp"


# ---- what DATA 12 prints ---------------------------------------------------------------------------------------

NOT_COVERED = "- Earnings-call text: NOT HELD — the source has no transcript for this company."
FAILED = ("- Earnings-call text: NOT AVAILABLE — the transcript source failed (HTTP 404, 2026-09-29); the call "
          "is not in this pack, so search for it if you need management's own words.")
UNRECORDED = "- Earnings-call text: NOT AVAILABLE — transcript status not recorded."
QA = "- Analyst Q&A from earnings calls: NOT HELD; DATA 10 holds prepared remarks only."


def test_the_transcript_line_by_status():
    line = cap._transcript_line
    assert line({"transcript_status": "not_covered"}, False) == NOT_COVERED
    assert line({"transcript_status": "source_failed: HTTP 404 (2026-09-29)"}, False) == FAILED
    assert line({}, False) == UNRECORDED and line(None, False) == UNRECORDED
    assert line({"transcript_status": "source_failed: broken"}, False) == UNRECORDED       # not the recorded shape
    assert line({"transcript_status": "ok", "transcript_excerpt": TRANSCRIPT}, True) == QA
    assert line({"transcript_status": "not_covered"}, True) == QA                          # DATA 10 printed: unchanged


def _pack(monkeypatch, tmp_path, record):
    class BlockedSocket(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("Socket access blocked in test")
    monkeypatch.setattr(socket, "socket", BlockedSocket)
    monkeypatch.setattr(cap.company_news, "fetch",
                        lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [], "errors": ["stubbed"]})
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)
    (tmp_path / "cache").mkdir(exist_ok=True)
    (tmp_path / "cache" / "openbb_GEV.json").write_text(json.dumps(record), encoding="utf-8")
    return str(cap.build_pack("GEV", include_research=False))


@pytest.mark.parametrize("record, line", [
    ({"metrics": {}, "forward_growth": {}, "transcript_excerpt": None, "transcript_status": "not_covered"}, NOT_COVERED),
    ({"metrics": {}, "forward_growth": {}, "transcript_excerpt": None,
      "transcript_status": "source_failed: HTTP 404 (2026-09-29)"}, FAILED),
    # a cache written before the field existed
    ({"metrics": {}, "forward_growth": {}, "transcript_excerpt": None}, UNRECORDED),
])
def test_data_12_prints_the_line_for_each_status(screener_data_stub, monkeypatch, tmp_path, record, line):
    pack = _pack(monkeypatch, tmp_path, record)
    assert line in pack
    assert "NOT HELD for this company" not in pack and "## DATA 10 - EARNINGS CALL EXCERPT" not in pack


def test_data_12_with_a_transcript_is_unchanged(screener_data_stub, monkeypatch, tmp_path):
    pack = _pack(monkeypatch, tmp_path, {"metrics": {}, "forward_growth": {}, "transcript_excerpt": TRANSCRIPT,
                                         "transcript_status": "ok"})
    assert "## DATA 10 - EARNINGS CALL EXCERPT" in pack and QA in pack
    assert "- Earnings-call text:" not in pack

"""A vendor HTTP error is a failed fetch, never "no coverage" (revision 18 follow-up, after the closure batch's "Invalid Crumb" 401s).

enrich_ticker.enrich() used to swallow every vendor exception into nulls, so a broken Yahoo session produced records that read as
a name with no consensus. Now an HTTP 401, 429 or 5xx on a core request (info, calendar, estimates) makes an ERROR record
(`_status: "error"`, no `estimates` key). The closure batch and the depth pipeline retry it, then stop and report; the pack says
the fetch failed. No network: yfinance is replaced throughout."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608" / "tests"))

import enrich_ticker as et  # noqa: E402
import rs2_data  # noqa: E402


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _HTTPError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        if code is not None:
            self.response = _Resp(code)


class YFRateLimitError(Exception):
    pass


# ---- reading the vendor's error -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("exc,expect", [
    (_HTTPError("boom", 401), 401), (_HTTPError("boom", 429), 429), (_HTTPError("boom", 503), 503), (_HTTPError("boom", 500), 500),
    (YFRateLimitError("Too Many Requests. Rate limited. Try after a while."), 429),
    (RuntimeError('HTTP Error 401: {"finance":{"error":{"code":"Unauthorized","description":"Invalid Crumb"}}}'), 401),
    (RuntimeError("429 Client Error: Too Many Requests for url: https://query2.finance.yahoo.com"), 429),
    (RuntimeError("status code 502 from the gateway"), 502),
    (RuntimeError("Invalid Crumb"), 401),
    (_HTTPError("not found", 404), None), (_HTTPError("bad request", 400), None),
    (KeyError("currentPrice"), None), (ValueError("could not convert 500 rows"), None), (ConnectionError("reset by peer"), None),
])
def test_the_vendors_http_errors_are_told_from_everything_else(exc, expect):
    assert et._vendor_http_status(exc) == expect


# ---- enrich() ---------------------------------------------------------------------------------------------------------------

def _ticker(info=None, calendar=None, estimates=None, raises=None):
    """A yf.Ticker stand-in: `raises` maps an attribute to the exception its access raises."""
    raises = raises or {}

    class T:
        def __init__(self, sym):
            self.sym = sym

        def _get(self, name, value):
            if name in raises:
                raise raises[name]
            return value

        @property
        def info(self):
            return self._get("info", info if info is not None else {"heldPercentInstitutions": 0.7, "targetMeanPrice": 10.0,
                                                                    "targetLowPrice": 8.0, "targetHighPrice": 12.0})

        @property
        def calendar(self):
            return self._get("calendar", calendar)

        @property
        def options(self):
            return ()

        @property
        def earnings_estimate(self):
            return self._get("earnings_estimate", estimates)

        @property
        def revenue_estimate(self):
            return self._get("revenue_estimate", estimates)

        @property
        def eps_trend(self):
            return self._get("eps_trend", None)

        @property
        def eps_revisions(self):
            return self._get("eps_revisions", None)

        def history(self, *a, **k):
            return None
    return T


@pytest.fixture
def vendor(monkeypatch):
    def install(**kw):
        monkeypatch.setattr(et.yf, "Ticker", _ticker(**kw))
        monkeypatch.setattr(et, "fetch_sibling_targets", lambda t, i: (None, "stubbed"))
    return install


@pytest.mark.parametrize("where,code", [("info", 401), ("calendar", 503), ("earnings_estimate", 429)])
def test_an_http_error_on_a_core_request_makes_an_error_record_with_no_estimates_key(vendor, where, code):
    vendor(raises={where: _HTTPError("x", code)})
    rec = et.enrich("aaa")
    assert rec["_status"] == "error" and rec["_ticker"] == "AAA" and "estimates" not in rec
    assert rec["_error"] == {"http_status": code, "where": "estimates" if where == "earnings_estimate" else where}
    assert et.is_error_record(rec) and rs2_data.enrich_fetch_error(rec) == (code, rec["_error"]["where"])
    assert rec["_fetched_at"]


def test_a_vendor_answer_with_no_estimates_is_no_coverage_not_an_error(vendor):
    vendor()
    rec = et.enrich("aaa")
    assert rec["estimates"] is None and "_status" not in rec and not et.is_error_record(rec)
    assert rs2_data.enrich_fetch_error(rec) is None
    assert rec["institutional_pct"] == 70.0                       # the rest of the record is as it was


def test_an_error_that_is_not_http_is_still_swallowed_as_before(vendor):
    vendor(raises={"info": KeyError("x"), "earnings_estimate": ValueError("y")})
    rec = et.enrich("aaa")
    assert "_status" not in rec and rec["estimates"] is None and rec["institutional_pct"] is None


def test_the_readers_ignore_records_that_are_not_errors():
    for rec in (None, {}, {"estimates": None}, {"_status": "ok"}, "x", [], {"_status": "error", "_error": "weird"}):
        got = rs2_data.enrich_fetch_error(rec)
        assert got is None or rec == {"_status": "error", "_error": "weird"}
    assert rs2_data.enrich_fetch_error({"_status": "error", "_error": "weird"}) == (None, None)    # still an error record


# ---- the retry --------------------------------------------------------------------------------------------------------------

def _err(code=401):
    return {"_ticker": "AAA", "_fetched_at": "2026-10-01T00:00:00+00:00", "_status": "error",
            "_error": {"http_status": code, "where": "info"}}


def test_enrich_with_retry_retries_once_after_a_cooloff_and_returns_the_first_good_record(monkeypatch):
    seq = [_err(), {"_ticker": "AAA", "estimates": {"0y": {}}}]
    monkeypatch.setattr(et, "enrich", lambda t: seq.pop(0))
    slept, reset = [], []
    rec = et.enrich_with_retry("aaa", cooloff=7.0, sleep=slept.append, before_retry=lambda: reset.append(1))
    assert rec["estimates"] and slept == [7.0] and reset == [1] and seq == []


def test_enrich_with_retry_gives_the_last_error_record_when_the_retry_fails_too(monkeypatch):
    seq = [_err(401), _err(429), _err(500)]
    monkeypatch.setattr(et, "enrich", lambda t: seq.pop(0))
    slept = []
    rec = et.enrich_with_retry("aaa", retries=1, sleep=slept.append)
    assert et.is_error_record(rec) and rec["_error"]["http_status"] == 429 and len(slept) == 1 and len(seq) == 1


def test_enrich_with_retry_does_not_sleep_for_a_good_record_or_when_told_not_to_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(et, "enrich", lambda t: (calls.append(t), {"_ticker": t, "estimates": None})[1])
    slept = []
    assert not et.is_error_record(et.enrich_with_retry("aaa", sleep=slept.append)) and slept == [] and calls == ["aaa"]
    monkeypatch.setattr(et, "enrich", lambda t: _err())
    assert et.is_error_record(et.enrich_with_retry("aaa", retries=0, sleep=slept.append)) and slept == []


# ---- the CLI ----------------------------------------------------------------------------------------------------------------

def test_the_cli_writes_a_good_record_and_never_overwrites_a_name_with_an_error_record(tmp_path, monkeypatch, capsys):
    out = tmp_path / "enrich"
    out.mkdir()
    old = {"_ticker": "AAA", "_fetched_at": "2026-09-01T00:00:00+00:00", "estimates": {"0y": {}}}
    (out / "AAA.json").write_text(json.dumps(old), encoding="utf-8")
    before = (out / "AAA.json").read_bytes()
    monkeypatch.setattr(et, "enrich", lambda t: _err(401))
    monkeypatch.setattr(et.time, "sleep", lambda s: None)
    assert et.main(["enrich_ticker.py", "aaa"], out_dir=out) == 3
    assert (out / "AAA.json").read_bytes() == before                      # the old record stands
    err = capsys.readouterr().err
    assert "FAILED" in err and "HTTP 401" in err and "unchanged" in err
    monkeypatch.setattr(et, "enrich", lambda t: {"_ticker": t, "estimates": None})
    assert et.main(["enrich_ticker.py", "bbb"], out_dir=out) == 0
    assert json.loads((out / "BBB.json").read_text(encoding="utf-8"))["estimates"] is None
    assert et.main(["enrich_ticker.py"], out_dir=out) == 1


# ---- the closure batch: retry, then stop and report ---------------------------------------------------------------------------

def _batch(tmp_path, monkeypatch, enrich_fn, names, vintage="2026-10-01"):
    import closure_enrich_batch as ceb
    monkeypatch.setattr(ceb, "HERE", tmp_path)
    monkeypatch.setattr(ceb.time, "sleep", lambda s: None)
    monkeypatch.setattr(et.time, "sleep", lambda s: None)
    monkeypatch.setattr(ceb, "_reset_session", lambda: None)
    monkeypatch.setattr(ceb.enrich_ticker, "enrich", enrich_fn)
    lst = tmp_path / "names.txt"
    lst.write_text("\n".join(names) + "\n", encoding="utf-8")
    rc = ceb.main(["--names", str(lst), "--date", vintage, "--workers", "1"])
    d = tmp_path / "cache" / "closure_enrich" / vintage
    return rc, d, json.loads((d / "manifest.json").read_text(encoding="utf-8"))


GOOD = lambda t: {"_ticker": t, "estimates": {"0y": {}}, "institutional_pct": 70.0}


def test_a_transient_error_record_is_retried_and_the_name_is_kept(tmp_path, monkeypatch):
    seen = {}

    def fn(t):
        seen[t] = seen.get(t, 0) + 1
        return _err(401) if (t == "BBB" and seen[t] == 1) else GOOD(t)
    rc, d, man = _batch(tmp_path, monkeypatch, fn, ["AAA", "BBB", "CCC"])
    assert rc == 0 and seen["BBB"] == 2 and man["files"] == 3 and man["stopped_on"] is None
    assert man["stats"]["failed_after_retry"] == 0 and man["stats"]["fetched"] == 3
    assert "_status" not in json.loads((d / "BBB.json").read_text(encoding="utf-8"))


def test_a_persistent_error_record_stops_the_batch_writes_nothing_for_the_name_and_reports(tmp_path, monkeypatch, capsys):
    seen = {}

    def fn(t):
        seen[t] = seen.get(t, 0) + 1
        return _err(429) if t == "BBB" else GOOD(t)
    rc, d, man = _batch(tmp_path, monkeypatch, fn, ["AAA", "BBB", "CCC", "DDD"])
    assert rc == 3
    assert (d / "AAA.json").exists() and not (d / "BBB.json").exists()          # no error record stored as the name's data
    assert "CCC" not in seen and "DDD" not in seen                              # the names after it were not attempted
    assert seen["BBB"] == 2                                                     # tried, then retried once
    assert man["stopped_on"] == {"http_status": 429, "where": "info", "names_left": 2}
    assert man["failure_types"] == {"http_429": 1} and man["stats"]["failed_after_retry"] == 1 and man["files"] == 1
    assert "STOPPED" in capsys.readouterr().err
    # the manifest still matches its files, and a later run resumes where it stopped
    import hashlib
    assert man["manifest_sha256"] == hashlib.sha256("".join(f"{k}:{v}{chr(10)}" for k, v in sorted(man["file_sha256"].items())).encode()).hexdigest()
    rc2, d2, man2 = _batch(tmp_path, monkeypatch, GOOD, ["AAA", "BBB", "CCC", "DDD"])
    assert rc2 == 0 and man2["files"] == 4 and man2["stats"]["skipped_existing"] == 1 and man2["stopped_on"] is None


def test_an_error_record_never_counts_as_estimates_null(tmp_path, monkeypatch):
    rc, d, man = _batch(tmp_path, monkeypatch, lambda t: _err(500), ["AAA"])
    assert rc == 3 and man["stats"]["estimates_null"] == 0 and man["stats"]["fetched"] == 0 and man["files"] == 0


def test_a_suspect_null_record_that_turns_into_an_error_on_its_retry_also_stops(tmp_path, monkeypatch):
    seen = {}

    def fn(t):
        seen[t] = seen.get(t, 0) + 1
        if seen[t] == 1:
            return {"_ticker": t, "estimates": None, "institutional_pct": None, "analyst_target_mean": None}
        return _err(401)
    rc, d, man = _batch(tmp_path, monkeypatch, fn, ["AAA", "BBB"])
    assert rc == 3 and man["files"] == 0 and man["stopped_on"]["http_status"] == 401 and "BBB" not in seen


# ---- the depth pipeline ------------------------------------------------------------------------------------------------------

def test_the_pipelines_gate_passes_a_good_or_missing_record_and_stops_on_a_failed_fetch(tmp_path):
    import depth_pipeline as dp
    d = tmp_path / "enrich"
    d.mkdir()
    (d / "OKK.json").write_text(json.dumps({"_ticker": "OKK", "estimates": None}), encoding="utf-8")
    (d / "ERR.json").write_text(json.dumps(_err(401)), encoding="utf-8")
    called = []
    fetch = lambda t: (called.append(t), _err(503))[1]
    assert dp.enrich_error_gate("OKK", d, fetch) == (True, None)               # no coverage is not a failed fetch
    assert dp.enrich_error_gate("MISSING", d, fetch) == (True, None)           # a missing record is the pack's to report
    assert called == []
    before = (d / "ERR.json").read_bytes()
    ok, why = dp.enrich_error_gate("ERR", d, fetch)
    assert (ok, why) == (False, "enrich_fetch_failed: HTTP 503 at info") and called == ["ERR"]
    assert (d / "ERR.json").read_bytes() == before                             # nothing written


def test_the_pipelines_gate_replaces_the_error_record_when_the_retry_succeeds(tmp_path):
    import depth_pipeline as dp
    d = tmp_path / "enrich"
    d.mkdir()
    (d / "ERR.json").write_text(json.dumps(_err(429)), encoding="utf-8")
    good = {"_ticker": "ERR", "estimates": {"0y": {}}}
    assert dp.enrich_error_gate("ERR", d, lambda t: good) == (True, None)
    assert json.loads((d / "ERR.json").read_text(encoding="utf-8")) == good


def test_the_pipeline_exits_10_on_a_failed_fetch_and_the_orchestrators_name_the_reason():
    src = (HERE / "depth_pipeline.py").read_text(encoding="utf-8")
    assert "sys.exit(10)" in src and "enrich_error_gate(t)" in src
    for f in ("orchestrate_depth.py", "depth_ondemand.py"):
        assert '10: "enrich_fetch_failed"' in (HERE / f).read_text(encoding="utf-8"), f

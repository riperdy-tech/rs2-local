"""enrich() against the REAL yfinance stack with a fake HTTP session (revision 18, amendment 2 follow-up, finding 4).

The installed yfinance (1.4.1) defaults to `hide_exceptions = True` (yfinance/config.py): its own scrapers catch an HTTP error, log it and
return None (scrapers/quote.py `_fetch`, scrapers/analysis.py `_fetch`), so an "Invalid Crumb" 401 or a 500 reached enrich() as an empty
answer - `estimates: None`, institutional_pct None - and read as "no coverage". Only a 429 (yfinance raises YFRateLimitError itself) was an
error record. tests/test_enrich_error_status.py replaces yfinance.Ticker; THIS file does not: the real Ticker, YfData, scrapers and
their config run, and only the HTTP session underneath is a fake (the approach of the reviewer's probe, review_p34/yf_http_probe.py).
No socket is opened; every test also blocks them.

The fake session answers by endpoint:
  info        quoteSummary(financialData ...)   and   v7/finance/quote   and   fundamentals-timeseries (info's third request)
  calendar    quoteSummary(calendarEvents)
  estimates   quoteSummary(earningsTrend)
  options / DXY history (v8 chart, v7 options): not core requests
A policy maps an endpoint to a (status, body); an endpoint not in it answers 200 with a good body.
"""
import json
import socket
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import enrich_ticker as et  # noqa: E402
import rs2_data  # noqa: E402

yf_data = pytest.importorskip("yfinance.data")
from yfinance._http import HTTPError  # noqa: E402

BODY_401 = '{"finance":{"result":null,"error":{"code":"Unauthorized","description":"Invalid Crumb"}}}'
BODY_500 = '{"finance":{"result":null,"error":{"code":"Internal Server Error"}}}'
BODY_429 = "Too Many Requests"
BODY_404 = '{"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"Quote not found for symbol: ZZ"}}}'
BODY_503 = "<html><body><h1>503 Service Unavailable</h1></body></html>"
FAIL = {401: BODY_401, 500: BODY_500, 429: BODY_429, 404: BODY_404, 503: BODY_503}


def _raw(v):
    return {"raw": v, "fmt": str(v)}


def _period(eps=None, rev=None, trend=None, revisions=None):
    """One earningsTrend entry; every key the scraper reads must be present (an empty dict is a block Yahoo answers without data)."""
    def block(d):
        return {k: _raw(v) for k, v in (d or {}).items()}
    return {"earningsEstimate": block(eps), "revenueEstimate": block(rev), "epsTrend": block(trend), "epsRevisions": block(revisions)}


FULL_TREND = [
    dict(period="0y", **_period({"avg": 2.7, "low": 2.6, "high": 2.8, "numberOfAnalysts": 20, "growth": 0.125, "yearAgoEps": 2.4},
                                {"avg": 10.8e9, "low": 10.5e9, "high": 11e9, "numberOfAnalysts": 18, "growth": 0.08, "yearAgoRevenue": 10e9},
                                {"current": 2.7, "7daysAgo": 2.69, "30daysAgo": 2.65, "60daysAgo": 2.6, "90daysAgo": 2.5},
                                {"upLast7days": 1, "upLast30days": 3, "downLast7days": 0, "downLast30days": 1})),
    dict(period="+1y", **_period({"avg": 3.0, "low": 2.8, "high": 3.2, "numberOfAnalysts": 19, "growth": 0.11, "yearAgoEps": 2.7},
                                 {"avg": 11.6e9, "numberOfAnalysts": 17})),
]
PARTIAL_TREND = [dict(period="0y", **_period({"avg": 2.7, "numberOfAnalysts": 5})), dict(period="+1y", **_period())]
NO_COVERAGE_TREND = []                                             # Yahoo answers 200 with an empty trend: the name has no estimates


def _summary(**modules):
    return json.dumps({"quoteSummary": {"result": [modules], "error": None}})


def good_bodies(trend):
    return {
        "info_summary": _summary(financialData={"targetMeanPrice": _raw(10.0), "targetLowPrice": _raw(8.0), "targetHighPrice": _raw(12.0),
                                                "numberOfAnalystOpinions": _raw(12)},
                                 defaultKeyStatistics={"heldPercentInstitutions": _raw(0.7), "shortPercentOfFloat": _raw(0.02)}),
        "info_quote": json.dumps({"quoteResponse": {"result": [{"symbol": "X", "regularMarketPrice": 9.5}], "error": None}}),
        "info_timeseries": json.dumps({"timeseries": {"result": [{"meta": {"symbol": ["X"]}}], "error": None}}),
        "calendar": _summary(calendarEvents={"earnings": {"earningsDate": [4102444800]}}),     # 2100-01-01
        "estimates": _summary(earningsTrend={"trend": trend}),
        "other": "{}",
    }


def endpoint_of(url, params):
    if "fundamentals-timeseries" in url:
        return "info_timeseries"
    if "/v7/finance/quote" in url:
        return "info_quote"
    if "quoteSummary" in url:
        modules = (params or {}).get("modules", "")
        if "calendarEvents" in modules:
            return "calendar"
        if "earningsTrend" in modules:
            return "estimates"
        return "info_summary"
    return "other"


class FakeResp:
    def __init__(self, url, status, body):
        self.status_code, self.url, self.text = status, url, body
        self.headers = {}
        self.content = body.encode("utf-8")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            e = HTTPError(f"{self.status_code} Client Error for url: {self.url}")
            e.response = self
            raise e


class FakeSession:
    proxies = None

    def __init__(self, policy, trend):
        self.policy, self.bodies, self.calls = policy, good_bodies(trend), []

    def get(self, url=None, params=None, **k):
        ep = endpoint_of(url, params)
        self.calls.append(ep)
        status = self.policy.get(ep, 200)
        return FakeResp(url, status, FAIL[status] if status != 200 else self.bodies[ep])

    post = get


_N = [0]


@pytest.fixture
def real_stack(monkeypatch):
    """Install a fake HTTP session under the real yfinance and return run(policy, trend) -> (record, session)."""
    class _Blocked(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("socket blocked in test")
    monkeypatch.setattr(socket, "socket", _Blocked)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dns blocked in test")))
    monkeypatch.setattr(yf_data.YfData, "_get_cookie_and_crumb", lambda self, timeout=30: ("fakecrumb", "basic"))
    monkeypatch.setattr(yf_data.YfData, "_set_cookie_strategy", lambda self, strategy, have_lock=False: None)
    monkeypatch.setattr(et, "fetch_sibling_targets", lambda t, i: (None, "stubbed"))       # reads the screener data dir, not the vendor
    inst = yf_data.YfData()
    real_session = inst._session

    def run(policy=None, trend=FULL_TREND):
        _N[0] += 1                                            # a new symbol each run: yfinance caches some answers per URL
        sess = FakeSession(policy or {}, trend)
        monkeypatch.setattr(inst, "_session", sess)
        return et.enrich(f"ZZ{_N[0]}"), sess
    yield run
    inst._session = real_session


# ---- the controls: a good answer, no coverage, a partial answer -----------------------------------------------------------------

def test_a_good_answer_is_a_good_record_with_estimates(real_stack):
    rec, sess = real_stack()
    assert "_status" not in rec and not et.is_error_record(rec)
    assert rec["institutional_pct"] == 70.0 and rec["analyst_target_mean"] == 10.0
    est = rec["estimates"]
    assert est["0y"]["eps"]["avg"] == 2.7 and est["0y"]["eps"]["analysts"] == 20 and est["+1y"]["revenue"]["avg"] == 11.6e9
    assert rec["next_earnings_date"] == "2100-01-01"
    assert {"info_summary", "info_quote", "info_timeseries", "calendar", "estimates"} <= set(sess.calls)


def test_no_coverage_stays_a_good_record_with_no_estimates(real_stack):
    rec, _ = real_stack(trend=NO_COVERAGE_TREND)
    assert "_status" not in rec and not et.is_error_record(rec) and rs2_data.enrich_fetch_error(rec) is None
    assert "estimates" in rec and rec["estimates"] is None
    assert rec["institutional_pct"] == 70.0                    # the rest of the record is as it was


def test_a_vendor_404_on_every_request_is_no_coverage_not_an_error(real_stack):
    """Yahoo answers 404 for a symbol it does not know: that is a name with nothing to fetch, not a failed fetch."""
    rec, _ = real_stack({ep: 404 for ep in ("info_summary", "info_quote", "info_timeseries", "calendar", "estimates")})
    assert "_status" not in rec and "estimates" in rec and rec["estimates"] is None and rec["institutional_pct"] is None


def test_a_partial_answer_stays_a_good_record_with_what_the_vendor_gave(real_stack):
    rec, _ = real_stack(trend=PARTIAL_TREND)
    assert "_status" not in rec and not et.is_error_record(rec)
    est = rec["estimates"]
    assert est is not None and est["0y"]["eps"]["avg"] == 2.7 and est["0y"]["eps"]["analysts"] == 5
    assert est["0y"]["eps"]["low"] is None and est["0y"]["revenue"]["avg"] is None and est["+1y"]["eps"]["avg"] is None
    assert rec["institutional_pct"] == 70.0 and rec["next_earnings_date"] == "2100-01-01"


# ---- an HTTP error on each core request ---------------------------------------------------------------------------------------

CORE = [("info_summary", "info"), ("info_quote", "info"), ("info_timeseries", "info"), ("calendar", "calendar"), ("estimates", "estimates")]


@pytest.mark.parametrize("code", [401, 500, 429])
@pytest.mark.parametrize("endpoint,where", CORE, ids=[c[0] for c in CORE])
def test_an_http_error_on_any_core_request_makes_an_error_record(real_stack, endpoint, where, code):
    rec, sess = real_stack({endpoint: code})
    assert et.is_error_record(rec) and rec["_status"] == "error", (endpoint, code, rec.get("estimates"))
    assert rec["_error"] == {"http_status": code, "where": where} and "estimates" not in rec
    assert rs2_data.enrich_fetch_error(rec) == (code, where) and rec["_fetched_at"]


@pytest.mark.parametrize("code", [401, 500, 429])
def test_every_core_request_failing_at_once_is_an_error_record_not_nulls(real_stack, code):
    rec, _ = real_stack({ep: code for ep, _w in CORE})
    assert et.is_error_record(rec) and rec["_error"]["http_status"] == code and "estimates" not in rec


@pytest.mark.parametrize("code", [401, 500, 429])
def test_a_failure_of_a_request_that_is_not_core_is_not_an_error_record(real_stack, code):
    """The options chain and the DXY history are annotations (their own `_options_error` / `_dxy_error` keys), not core requests."""
    rec, _ = real_stack({"other": code})
    assert not et.is_error_record(rec) and "_status" not in rec
    assert rec["estimates"]["0y"]["eps"]["avg"] == 2.7 and rec["institutional_pct"] == 70.0


def test_the_retry_wrapper_retries_a_real_stack_401_and_keeps_the_good_record(real_stack, monkeypatch):
    rec0, sess = real_stack({"info_summary": 401})
    assert et.is_error_record(rec0)
    sess.policy.clear()                                        # the session recovers
    slept = []
    rec = et.enrich_with_retry(rec0["_ticker"], cooloff=3.0, sleep=slept.append)
    assert not et.is_error_record(rec) and rec["estimates"]["0y"]["eps"]["avg"] == 2.7 and slept == []
    sess.policy["info_summary"] = 401                          # still broken after the retry: the last error record
    rec = et.enrich_with_retry(rec0["_ticker"], cooloff=3.0, sleep=slept.append)
    assert et.is_error_record(rec) and slept == [3.0]


# ---- an error on the request yfinance serves from its own cache (YfData.cache_get: Ticker.info's third request) ---------------------
# Revision 18 follow-up, finding 1: a repeat of a cached request never reaches _make_request, so the recorder saw nothing and the
# status-less error that followed read as "no coverage". Measured on this stack before the fix: the first attempt was an error record,
# the retry and a second fetch of the name were good-looking records with targets and ownership null.

@pytest.fixture
def one_name(real_stack, monkeypatch):
    """(name, set_policy, session): one symbol enriched several times, the fake session's policy changed between the calls."""
    _N[0] += 1
    inst = yf_data.YfData()
    sess = FakeSession({}, FULL_TREND)
    monkeypatch.setattr(inst, "_session", sess)
    yf_data.YfData.cache_get.cache_clear()
    return f"ZZ{_N[0]}", sess


def _timeseries_calls(sess):
    return sess.calls.count("info_timeseries")


@pytest.mark.parametrize("code", [500, 503, 401])
def test_a_persistent_error_on_info_timeseries_is_an_error_record_on_every_attempt(one_name, code):
    name, sess = one_name
    sess.policy["info_timeseries"] = code
    rec = et.enrich_with_retry(name, retries=1, cooloff=0.0, sleep=lambda s: None)
    assert et.is_error_record(rec) and rec["_error"] == {"http_status": code, "where": "info"} and "estimates" not in rec
    assert rec["_ticker"] == name
    assert _timeseries_calls(sess) >= 4                  # the retry asked the vendor again: two requests per attempt (the cookie strategy)
    rec2 = et.enrich(name)                                # and a later call of the same name in the same process
    assert et.is_error_record(rec2) and rec2["_error"]["http_status"] == code


def test_a_500_on_info_timeseries_that_clears_before_the_retry_gives_the_good_record(one_name):
    name, sess = one_name
    sess.policy["info_timeseries"] = 500
    rec = et.enrich_with_retry(name, retries=1, cooloff=0.0, sleep=lambda s: None, before_retry=sess.policy.clear)
    assert not et.is_error_record(rec) and "_status" not in rec
    assert rec["analyst_target_mean"] == 10.0 and rec["institutional_pct"] == 70.0 and rec["estimates"]["0y"]["eps"]["avg"] == 2.7


def test_a_second_fetch_of_a_name_after_a_500_asks_the_vendor_again(one_name):
    name, sess = one_name
    sess.policy["info_timeseries"] = 500
    first = et.enrich(name)
    assert et.is_error_record(first)
    sess.policy.clear()
    before = _timeseries_calls(sess)
    second = et.enrich(name)
    assert _timeseries_calls(sess) == before + 1          # the 500 was not kept in yfinance's cache
    assert not et.is_error_record(second) and second["analyst_target_mean"] == 10.0 and second["institutional_pct"] == 70.0


def test_an_error_response_already_in_the_cache_is_an_error_record_when_it_is_served(one_name):
    """The recorder also sees a response yfinance serves from its cache: poison the cache with a 500 (as an earlier caller outside any
    core request would have), and the next enrich of the name reports it, then clears it."""
    name, sess = one_name
    sess.policy["info_timeseries"] = 500
    seen_url = [None]
    real_get = sess.get

    def spy(url=None, params=None, **k):
        if "fundamentals-timeseries" in (url or ""):
            seen_url[0] = url
        return real_get(url, params, **k)
    sess.get = spy
    et.enrich(name)                                       # records the timeseries URL
    sess.get = real_get
    assert seen_url[0] is not None
    yf_data.YfData.cache_get.cache_clear()
    inst = yf_data.YfData()
    yf_data.YfData.cache_get._rs2_original(inst, url=seen_url[0])    # the 500 is now in the cache, outside any core request
    assert yf_data.YfData.cache_get.cache_info().currsize == 1
    sess.policy.clear()
    before = _timeseries_calls(sess)
    rec = et.enrich(name)
    assert et.is_error_record(rec) and rec["_error"] == {"http_status": 500, "where": "info"}
    assert _timeseries_calls(sess) == before              # served from the cache, not from the session
    rec2 = et.enrich(name)                                # the error was cleared: the vendor is asked, and answers
    assert not et.is_error_record(rec2) and rec2["institutional_pct"] == 70.0


# ---- the recorder is per thread and leaves nothing behind -------------------------------------------------------------------------

def test_a_response_on_another_thread_or_outside_a_core_request_is_not_recorded(real_stack):
    import threading
    inst = yf_data.YfData()
    sess = FakeSession({"other": 500}, FULL_TREND)
    inst._session = sess
    assert getattr(et._SEEN, "statuses", None) is None
    gate_in, gate_out, result = threading.Event(), threading.Event(), {}

    def core():
        try:
            with et._core_request("info"):
                gate_in.set()
                gate_out.wait(5)
            result["core"] = "clean"
        except et.VendorHTTPError as e:
            result["core"] = ("error", e.status)

    th = threading.Thread(target=core)
    th.start()
    gate_in.wait(5)
    # while the core block is open on the other thread, this thread makes a request that answers 500: it is not the core block's
    assert inst._make_request("https://example.invalid/v8/finance/chart/X", request_method=sess.get).status_code == 500
    gate_out.set()
    th.join(5)
    assert result["core"] == "clean"
    # outside any core request nothing is recorded, and the state is as it was after a block that failed
    inst._make_request("https://example.invalid/v8/finance/chart/X", request_method=sess.get)
    assert getattr(et._SEEN, "statuses", None) is None
    with pytest.raises(et.VendorHTTPError):
        with et._core_request("calendar"):
            inst._make_request("https://example.invalid/v8/finance/chart/X", request_method=sess.get)
    assert getattr(et._SEEN, "statuses", None) is None
    with pytest.raises(KeyError):                                  # a failure with no bad response is left as it was
        with et._core_request("calendar"):
            raise KeyError("x")
    assert getattr(et._SEEN, "statuses", None) is None


def test_the_recorder_is_installed_once(real_stack):
    first = yf_data.YfData._make_request
    et._install_status_recorder()
    et._install_status_recorder()
    assert yf_data.YfData._make_request is first and first._rs2_records_status is True

"""P4 D10 — SECTION 1.6's WORLD NEWS block (world_news.py + capability_test.py wiring).

Part A tests `world_news.digest()` itself: fixtures only — tiny REAL parquet files built with
duckdb `COPY ... TO ... (FORMAT PARQUET)`, read back through the exact `read_parquet()` code path
digest() uses. Only the git layer is faked (`world_news._mri_repo` / `refresh_run_history` /
`_git_show`) — no network, no real git, no real MRI repo. Partition keys and columns match the
real manifest.json/parquet schema this module reads (MEASURED 2026-09-24 against
macro-regime-indicator@origin/run-history).

Part B tests capability_test.py's SECTION 1.6 wiring: `world_news.digest` itself is monkeypatched
(fast, deterministic), proving the pack renders exactly the text D10 specifies from a given digest
result, in both live and point-in-time mode.
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import world_news as wn  # noqa: E402
import capability_test as cap  # noqa: E402


CLS_COLUMNS = [("news_id", "VARCHAR"), ("classified_at", "TIMESTAMP"), ("severity", "DOUBLE"),
              ("confidence", "DOUBLE"), ("summary", "VARCHAR"), ("secular_theme", "VARCHAR")]
# `body` is NOT a real column of this store (MEASURED: items carries only body_chars/body_sha256,
# no raw text) — it rides on the FIXTURE only, to prove the items query never selects it.
ITEMS_COLUMNS = [("news_id", "VARCHAR"), ("source", "VARCHAR"), ("published_at", "TIMESTAMP"),
                 ("body", "VARCHAR")]


def _write_parquet(path, columns, rows):
    con = duckdb.connect()
    try:
        col_defs = ", ".join(f"{n} {t}" for n, t in columns)
        placeholders = ", ".join("?" for _ in columns)
        con.execute(f"CREATE TABLE t ({col_defs})")
        if rows:
            con.executemany(f"INSERT INTO t VALUES ({placeholders})", rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY t TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()


class FakeRunHistory:
    """A fake `origin/run-history` ref: a manifest dict plus a store of local parquet files,
    served by a monkeypatched `world_news._git_show` keyed on the exact
    `outputs/news_history/...` path real code asks for."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.partitions = {}     # manifest "partitions": key -> {"rows":..., "sha256":...}
        self.files = {}          # "outputs/news_history/<key>" -> local Path

    def add_classifications(self, d, rows):
        key = f"classifications/{d.year}/{d.month:02d}/classifications_{d.isoformat()}.parquet"
        path = self.tmp_path / "cls" / f"{d.isoformat()}.parquet"
        _write_parquet(path, CLS_COLUMNS, rows)
        self.partitions[key] = {"rows": len(rows), "sha256": "fake"}
        self.files[f"outputs/news_history/{key}"] = path
        return key

    def add_items(self, d, rows):
        key = f"items/{d.year}/{d.month:02d}/items_{d.isoformat()}.parquet"
        path = self.tmp_path / "items" / f"{d.isoformat()}.parquet"
        _write_parquet(path, ITEMS_COLUMNS, rows)
        self.partitions[key] = {"rows": len(rows), "sha256": "fake"}
        self.files[f"outputs/news_history/{key}"] = path
        return key

    def git_show(self, mri_repo, path, timeout=60):
        if path == wn.MANIFEST_PATH:
            return json.dumps({"partitions": self.partitions}).encode("utf-8")
        local = self.files.get(path)
        return local.read_bytes() if local and local.exists() else None


@pytest.fixture
def fake_run_history(tmp_path, monkeypatch):
    frh = FakeRunHistory(tmp_path)
    monkeypatch.setattr(wn, "_mri_repo", lambda: "FAKE_MRI_REPO")
    monkeypatch.setattr(wn, "refresh_run_history", lambda mri_repo: (True, ""))
    monkeypatch.setattr(wn, "_git_show", frh.git_show)
    monkeypatch.setattr(wn, "CACHE_PATH", tmp_path / "cache" / "world_news_digest.json")
    return frh


def _cls(news_id, classified_at, severity, confidence, summary, secular_theme=None):
    return (news_id, classified_at, severity, confidence, summary, secular_theme)


def _item(news_id, source, published_at, body="n/a"):
    return (news_id, source, published_at, body)


# ── Part A: world_news.digest() ─────────────────────────────────────────────────────────────

def test_window_selection_15_days_excluded_14_included(fake_run_history):
    asof = date(2026, 9, 24)
    fake_run_history.add_classifications(date(2026, 9, 10), [        # end - 14: INCLUDED
        _cls("n_in", datetime(2026, 9, 10, 1, 0), 0.5, 0.5,
             "Included row about regional airline capacity expansion plans announced quietly")])
    fake_run_history.add_classifications(date(2026, 9, 9), [         # end - 15: EXCLUDED
        _cls("n_out", datetime(2026, 9, 9, 1, 0), 0.9, 0.9,
             "Excluded row about a totally different steel tariff dispute overseas entirely")])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result["n_considered"] == 1
    ids = [r["summary"] for r in result["top"]]
    assert any("Included row" in s for s in ids)
    assert not any("Excluded row" in s for s in ids)
    assert "Excluded row" not in json.dumps(result)


def test_ranking_order_severity_then_confidence_then_classified_at(fake_run_history):
    # news_id is deliberately alphabetized BACKWARDS from the expected rank order below, so a
    # regression that accidentally sorted by news_id (or by insertion/fetch order) instead of by
    # (severity, confidence, classified_at) cannot pass this test by coincidence.
    asof = date(2026, 9, 24)
    t0 = datetime(2026, 9, 24, 10, 0)
    fake_run_history.add_classifications(asof, [
        _cls("z_housing", t0, 0.9, 0.5,
             "Housing market rebounds sharply as mortgage rates ease this quarter nationwide"),
        _cls("y_semiconductor", t0, 0.5, 0.9,
             "Semiconductor export controls tighten between Washington and Beijing this month"),
        _cls("x_labor", t0 + timedelta(hours=1), 0.5, 0.5,
             "Labor union negotiations stall at major automaker plants across several states"),
        _cls("w_copper", t0, 0.5, 0.5,
             "Copper mining output falls after strikes disrupt Chilean operations broadly"),
    ])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    # Expected: housing (severity 0.9) > semiconductor (confidence 0.9 beats the 0.5/0.5 pair) >
    # labor (later classified_at breaks the tie with copper) > copper.
    assert [r["summary"][:3] for r in result["top"]] == ["Hou", "Sem", "Lab", "Cop"]


def test_dedupe_jaccard_hormuz_rewordings_collapse_fed_row_kept(fake_run_history):
    # news_id is deliberately NOT alphabetized in rank order (the high-severity Hormuz row sorts
    # last, the low-severity one sorts first) — proves the SURVIVOR of the dedupe pair is chosen
    # by rank (severity), not by incidental news_id/fetch order.
    asof = date(2026, 9, 24)
    s_hormuz_high = ("Iran closes the Strait of Hormuz to oil tankers, sending crude prices "
                     "sharply higher across global energy markets this week")
    s_hormuz_low = ("Strait of Hormuz closure keeps oil tankers blocked, holding crude prices "
                    "sharply elevated across global energy markets")        # jaccard ~0.52 vs high
    s_fed = ("The Federal Reserve raised interest rates by 25 basis points, citing persistent "
            "inflation pressure in the labor market")                      # jaccard 0.0 vs both
    fake_run_history.add_classifications(asof, [
        _cls("a_hormuz_low_severity", datetime(2026, 9, 24, 2, 0), 0.8, 0.8, s_hormuz_low),
        _cls("m_fed_unrelated", datetime(2026, 9, 24, 3, 0), 0.7, 0.7, s_fed),
        _cls("z_hormuz_high_severity", datetime(2026, 9, 24, 1, 0), 0.9, 0.9, s_hormuz_high),
    ])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    summaries = [r["summary"] for r in result["top"]]
    assert s_hormuz_high in summaries
    assert s_fed in summaries
    assert s_hormuz_low not in summaries
    assert len(result["top"]) == 2


def test_theme_list_excludes_rows_already_in_top_and_respects_theme_n(fake_run_history):
    asof = date(2026, 9, 24)
    t0 = datetime(2026, 9, 24, 1, 0)
    # 5 distinct-topic, theme-tagged rows, descending severity. top_n=1 -> only "alpha" lands in
    # top; theme_n=2 -> themes takes the next 2 of the remaining 4.
    fake_run_history.add_classifications(asof, [
        _cls("alpha", t0, 0.9, 0.9, "Oil refinery outages ripple through Gulf coast fuel supply "
                                    "chains this week", "energy_transition"),
        _cls("beta", t0, 0.8, 0.8, "Cloud data-center capex accelerates across hyperscalers amid "
                                   "AI demand surge", "ai_compute"),
        _cls("gamma", t0, 0.7, 0.7, "Humanoid robotics pilots expand in automotive assembly "
                                    "plants nationwide", "physical_ai"),
        _cls("delta", t0, 0.6, 0.6, "Regional bank lending standards tighten amid commercial "
                                    "real estate concerns broadly", "energy_transition"),
        _cls("epsilon", t0, 0.5, 0.5, "Grid operators warn of summer capacity shortfalls amid "
                                      "rising electricity demand nationwide", None),
    ])
    result = wn.digest(asof=asof, days=14, top_n=1, theme_n=2)
    assert len(result["top"]) == 1
    assert "Oil refinery" in result["top"][0]["summary"]
    assert len(result["themes"]) == 2
    theme_summaries = [r["summary"] for r in result["themes"]]
    assert not any("Oil refinery" in s for s in theme_summaries)      # already in top -> excluded
    assert any("Cloud data-center" in s for s in theme_summaries)     # next-highest theme row
    assert any("Humanoid robotics" in s for s in theme_summaries)
    assert not any("Grid operators" in s for s in theme_summaries)    # secular_theme empty


def test_asof_mode_excludes_rows_classified_after_asof(fake_run_history):
    asof = date(2026, 9, 24)
    fake_run_history.add_classifications(asof, [
        _cls("ok", datetime(2026, 9, 24, 1, 0), 0.5, 0.5,
             "Kept row classified exactly on the asof date itself with room to spare"),
        _cls("future", datetime(2026, 9, 25, 1, 0), 0.9, 0.9,
             "Excluded row whose classified_at timestamp lands one full day after asof"),
    ])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result["n_considered"] == 1
    assert "Kept row" in result["top"][0]["summary"]


def test_asof_mode_excludes_rows_published_after_asof(fake_run_history):
    asof = date(2026, 9, 24)
    fake_run_history.add_classifications(asof, [
        _cls("ok", datetime(2026, 9, 24, 1, 0), 0.5, 0.5,
             "Kept row published safely before the asof cutoff with clean provenance"),
        _cls("leaked", datetime(2026, 9, 24, 1, 0), 0.9, 0.9,
             "Excluded row whose matching item was published after the asof cutoff date"),
    ])
    fake_run_history.add_items(asof, [
        _item("ok", "wire_a", datetime(2026, 9, 23, 12, 0)),
        _item("leaked", "wire_b", datetime(2026, 9, 25, 12, 0)),   # published AFTER asof
    ])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result["n_considered"] == 1
    assert "Kept row" in result["top"][0]["summary"]


def test_empty_window_is_a_valid_empty_result_not_a_failure(fake_run_history):
    asof = date(2026, 9, 24)
    # No partitions added at all -> manifest parses fine, but the window is genuinely empty.
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result is not None
    assert result["n_considered"] == 0
    assert result["top"] == []
    assert result["themes"] == []
    assert result["stale_days"] is None


def test_first_partition_date_reported_when_asof_predates_the_feed(fake_run_history):
    fake_run_history.add_classifications(date(2026, 7, 27), [
        _cls("n1", datetime(2026, 7, 27, 1, 0), 0.5, 0.5, "The feed's earliest ever classified "
                                                          "headline about a port strike")])
    result = wn.digest(asof=date(2026, 3, 31), days=14, top_n=12, theme_n=4)
    assert result["top"] == []
    assert result["first_partition_date"] == "2026-07-27"


def test_stale_days_computed_from_newest_classified_vs_end(fake_run_history):
    asof = date(2026, 9, 24)
    fake_run_history.add_classifications(date(2026, 9, 20), [        # 4 days before asof
        _cls("n1", datetime(2026, 9, 20, 1, 0), 0.5, 0.5, "A four-day-stale headline about "
                                                          "regional port congestion easing")])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result["stale_days"] == 4

    fake_run_history.add_classifications(date(2026, 9, 21), [        # 3 days before asof
        _cls("n2", datetime(2026, 9, 21, 1, 0), 0.5, 0.5, "A three-day-fresh headline about "
                                                          "a separate manufacturing survey")])
    result2 = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result2["stale_days"] == 3


def test_fetch_failure_still_builds_from_existing_ref(fake_run_history, monkeypatch):
    asof = date(2026, 9, 24)
    fake_run_history.add_classifications(asof, [
        _cls("n1", datetime(2026, 9, 24, 1, 0), 0.5, 0.5,
             "A headline read from whatever origin/run-history already holds locally")])
    monkeypatch.setattr(wn, "refresh_run_history",
                        lambda mri_repo: (False, "simulated network failure"))
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert result["fetch"] == {"ok": False, "note": "simulated network failure"}
    assert result["n_considered"] == 1
    assert "headline read from" in result["top"][0]["summary"]


def test_cache_fallback_within_3_days_and_not_after(fake_run_history, monkeypatch):
    cached_payload = {
        "window_days": 14, "first_partition_date": "2026-07-27", "newest_classified": "2026-09-20",
        "n_considered": 1, "stale_days": 4,
        "top": [{"date": "2026-09-20", "source": "wire_a", "severity": 0.5, "secular_theme": "",
                "summary": "A cached headline from three days ago"}],
        "themes": [],
    }

    def _write_cache_aged(age_days):
        payload = dict(cached_payload)
        payload["fetched_at"] = (datetime.now() - timedelta(days=age_days)).isoformat()
        wn.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        wn.CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")

    # Total live-build failure: no mri_repo resolvable at all.
    monkeypatch.setattr(wn, "_mri_repo", lambda: None)

    _write_cache_aged(3)
    result = wn.digest()                      # live (asof=None)
    assert result is not None
    assert result["n_considered"] == 1
    assert result["top"][0]["summary"] == "A cached headline from three days ago"

    _write_cache_aged(4)
    result2 = wn.digest()
    assert result2 is None


def test_asof_mode_never_touches_the_live_cache(fake_run_history, monkeypatch):
    """Point-in-time mode must not serve today's cached digest when its own build is empty."""
    monkeypatch.setattr(wn, "_mri_repo", lambda: None)          # force total build failure
    cached_payload = {
        "window_days": 14, "first_partition_date": "2026-07-27", "newest_classified": "2026-09-24",
        "n_considered": 1, "stale_days": 0,
        "top": [{"date": "2026-09-24", "source": "wire_a", "severity": 0.9, "secular_theme": "",
                "summary": "TODAYS_NEWS_MUST_NEVER_LEAK_INTO_THE_PAST"}],
        "themes": [], "fetched_at": datetime.now().isoformat(),
    }
    wn.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    wn.CACHE_PATH.write_text(json.dumps(cached_payload), encoding="utf-8")

    result = wn.digest(asof=date(2026, 3, 31))
    assert result is not None
    assert result["top"] == []
    assert "TODAYS_NEWS_MUST_NEVER_LEAK_INTO_THE_PAST" not in json.dumps(result)


def test_items_query_selects_only_the_listed_columns(fake_run_history):
    """Structural proof (the SQL itself never names a body/meta column) plus a behavioural proof
    (a marker planted only in the unselected `body` column never reaches the digest output)."""
    src = Path(wn.__file__).read_text(encoding="utf-8")
    assert "SELECT news_id, source, published_at FROM read_parquet" in src

    asof = date(2026, 9, 24)
    fake_run_history.add_classifications(asof, [
        _cls("n1", datetime(2026, 9, 24, 1, 0), 0.5, 0.5,
             "A headline whose matching item carries a body column nothing should read")])
    fake_run_history.add_items(asof, [
        _item("n1", "wire_a", datetime(2026, 9, 24, 0, 0), body="SECRET_BODY_MARKER_MUST_NOT_LEAK"),
    ])
    result = wn.digest(asof=asof, days=14, top_n=12, theme_n=4)
    assert "SECRET_BODY_MARKER_MUST_NOT_LEAK" not in json.dumps(result)
    assert result["top"][0]["source"] == "wire_a"     # the join itself still worked


# ── Part B: capability_test.py SECTION 1.6 wiring ───────────────────────────────────────────

def _slice(pack, header, next_prefix="## "):
    """Byte-identical to test_pack_enrichment.py's own `_slice` helper: the text of ONE
    `## <header>` block, up to (not including) the next `## `-prefixed line."""
    s = str(pack)
    i = s.find("## " + header)
    assert i != -1, f"section {header!r} not found in pack"
    j = s.find("\n" + next_prefix, i + 3)
    return s[i:j if j != -1 else len(s)]


def _fake_digest(result):
    def _f(asof=None):
        return result
    return _f


def _fake_mri_asof(monkeypatch, degraded=True):
    """Minimal stub of every rs2_data.asof_* accessor SECTION 1.5/1.6 reads, so build_pack(asof=)
    runs with no real duckdb/network — same pattern test_point_in_time_pack.py uses."""
    import rs2_data
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": 0.043, "real_10y": 0.02,
                                         "breakeven_10y": 0.023},
        "risk_free_source": {"nominal_10y": "fake", "real_10y": "fake", "breakeven_10y": "fake"},
        "implied_erp": None, "implied_cost_of_equity": None, "sector_loadings": {},
        "erp_source": "unavailable", "degraded": degraded,
        "degradation_reasons": ["fake"], "anchor_run_asof": None,
    })
    monkeypatch.setattr(rs2_data, "asof_terminal_g", lambda asof: (None, "fake"))
    monkeypatch.setattr(rs2_data, "asof_secondary_macro_series", lambda asof: {
        "t10y2y": (0.25, str(asof)), "baa10y": (1.4, str(asof)), "hy_oas": (3.0, str(asof))})
    monkeypatch.setattr(rs2_data, "asof_regime_vector", lambda asof, max_age_days=None: {
        "date": str(asof), "probabilities": {"goldilocks": 0.29, "reflation": 0.22,
                                             "stagflation": 0.18, "recession": 0.17,
                                             "tightening": 0.13},
        "headline": "goldilocks", "headline_probability": 0.29, "margin": 0.07})
    monkeypatch.setattr(rs2_data, "asof_shock_register", lambda asof: {
        "asof": str(asof), "shocks": [], "elevated_volatility_ahead": False})
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp", lambda asof: (None, "fake"))
    monkeypatch.setattr(rs2_data, "asof_inflation_trend", lambda asof: {"cpi_yoy": None,
                                                                        "pce_yoy": None})


def _fake_asof_price_lookup(monkeypatch, price=100.0, asof_str="2026-03-31"):
    monkeypatch.setattr(cap, "_asof_price_lookup",
                        lambda t, asof_date, lookback_days=400: {"price": price, "asof": asof_str,
                                                                 "series": {asof_str: price}})


_SAMPLE_DIGEST = {
    "window_days": 14, "n_considered": 5, "newest_classified": "2026-09-24", "stale_days": 0,
    "top": [
        {"date": "2026-09-23", "source": "bbc_world", "severity": 0.85, "secular_theme": "",
         "summary": "Iran rejects US demands over the Strait of Hormuz blockade"},
        {"date": "2026-09-22", "source": "cnbc", "severity": 0.7, "secular_theme": "",
         "summary": "Fed raises rates 25bp to 3.75-4.00 percent"},
    ],
    "themes": [
        {"date": "2026-09-21", "source": "scmp", "severity": 0.6, "secular_theme": "ai_compute",
         "summary": "Hyperscaler AI capex accelerates into next year"},
    ],
}


def test_live_pack_world_news_block_renders_top_and_themes(screener_data_stub, monkeypatch):
    import world_news
    monkeypatch.setattr(world_news, "digest", _fake_digest(_SAMPLE_DIGEST))
    pack = cap.build_pack("GEV")
    sec16 = _slice(pack, "SECTION 1.6 - STATE OF THE WORLD")
    assert ("- WORLD NEWS, last 14 days — one-line AI summaries of dated headlines from the MRI "
            "news feed (context, not verified facts; check anything you rely on). 5 items "
            "considered, newest classified 2026-09-24:") in sec16
    assert ("  - 2026-09-23 | bbc_world | Iran rejects US demands over the Strait of Hormuz "
            "blockade  (severity 0.85)") in sec16
    assert ("  - 2026-09-22 | cnbc | Fed raises rates 25bp to 3.75-4.00 percent  "
            "(severity 0.70)") in sec16
    assert "- Structural themes in the news (same feed):" in sec16
    assert ("  - 2026-09-21 | ai_compute | Hyperscaler AI capex accelerates into next year"
            in sec16)


def test_live_pack_world_news_not_available_when_digest_none(screener_data_stub, monkeypatch):
    import world_news
    monkeypatch.setattr(world_news, "digest", _fake_digest(None))
    pack = cap.build_pack("GEV")
    sec16 = _slice(pack, "SECTION 1.6 - STATE OF THE WORLD")
    assert ("- WORLD NEWS: not available — MRI news feed unavailable this run (no live digest "
            "and no usable cache)") in sec16


def test_live_pack_world_news_stale_prefix_at_4_not_at_3(screener_data_stub, monkeypatch):
    import world_news
    stale = dict(_SAMPLE_DIGEST, stale_days=4)
    monkeypatch.setattr(world_news, "digest", _fake_digest(stale))
    pack = cap.build_pack("GEV")
    sec16 = _slice(pack, "SECTION 1.6 - STATE OF THE WORLD")
    assert "- STALE (4 days) — WORLD NEWS, last 14 days" in sec16

    not_stale = dict(_SAMPLE_DIGEST, stale_days=3)
    monkeypatch.setattr(world_news, "digest", _fake_digest(not_stale))
    pack2 = cap.build_pack("GEV")
    sec16b = _slice(pack2, "SECTION 1.6 - STATE OF THE WORLD")
    assert "STALE (" not in sec16b
    assert "- WORLD NEWS, last 14 days" in sec16b


def test_asof_pack_world_news_not_available_with_first_partition_date(screener_data_stub, monkeypatch):
    import world_news
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    empty_pit = {"window_days": 14, "n_considered": 0, "newest_classified": None,
                "stale_days": None, "top": [], "themes": [], "first_partition_date": "2026-07-27"}
    calls = []

    def _fake(asof=None):
        calls.append(asof)
        return empty_pit
    monkeypatch.setattr(world_news, "digest", _fake)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec16 = _slice(pack, "SECTION 1.6 - STATE OF THE WORLD")
    assert "- WORLD NEWS: not available (point-in-time) — the news history does not reach back to this date" in sec16
    assert "2026-07-27" not in sec16          # no post-asof date, even as metadata
    # Wired correctly: digest() was called WITH the asof date, not live (None).
    assert calls == [cap._parse_asof("2026-03-31")]


def test_asof_pack_world_news_renders_when_rows_present(screener_data_stub, monkeypatch):
    import world_news
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    monkeypatch.setattr(world_news, "digest", _fake_digest(_SAMPLE_DIGEST))
    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec16 = _slice(pack, "SECTION 1.6 - STATE OF THE WORLD")
    assert "- WORLD NEWS, last 14 days" in sec16
    assert "the news history does not reach back to this date" not in sec16
    assert "Iran rejects US demands over the Strait of Hormuz blockade" in sec16

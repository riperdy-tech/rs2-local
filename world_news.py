#!/usr/bin/env python3
"""world_news.py — the MRI news-theme summary for SECTION 1.6 "STATE OF THE WORLD" (P4 D10).

WHY (PHASE_4_PACK_SPEC.md D10): SECTION 1.6 was specified to carry "the news-theme summary" and
never did — the analyst values companies with no signal of what happened since its training
cutoff (a live war, a new Fed hiking cycle, a multi-decade-high 10-year yield are all invisible to
it unless this pack states them). The MRI's OWN local duckdb store (rs2_data.mri_duckdb_path(),
the raw_observations/anchor_runs tables the asof_* accessors read) carries no news after
2026-05-30: the cloud run classifies news continuously, but only pushes the result to the
macro-regime-indicator repo's `origin/run-history` branch, never to the local store. This module
is a second, independent, read-only MRI accessor for that branch — `git fetch` / `git show` only,
never the working tree, never a checkout, never a commit, never the MRI pipeline.

SOURCE (MEASURED 2026-09-24): mri_repo = paths.resolve("mri_dir", ...) (the macro-regime-indicator
repo root). `origin/run-history` holds `outputs/news_history/manifest.json` — a flat
{"partitions": {"classifications/YYYY/MM/classifications_YYYY-MM-DD.parquet": {"rows":...,
"sha256":...}, "items/YYYY/MM/items_YYYY-MM-DD.parquet": {...}, ...}} map — plus the two daily
partition families it lists. A classification partition's date always equals every row's own
`classified_at` date (one daily batch per file); an items partition is an ingestion batch and can
trail a few days behind its rows' `published_at`, hence the "3 days before" lookback below.
`classifications` carries news_id/classified_at/severity/confidence/summary/secular_theme; `items`
carries news_id/source/published_at (plus body_chars/body_sha256 hashes — there is no raw
article-body column in this store at all, and nothing here ever selects one; the items query below
names exactly three columns, never `SELECT *`).

Never touches KIS, never runs the MRI or depth pipelines, never writes to mri_repo.
"""
import json
import re
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import paths
import rs2_data

HERE = Path(__file__).resolve().parent
CACHE_PATH = HERE / "cache" / "world_news_digest.json"
CACHE_MAX_AGE_DAYS = 3
RUN_HISTORY_REF = "origin/run-history"
MANIFEST_PATH = "outputs/news_history/manifest.json"

# Jaccard dedupe token rule (brief-specified, verbatim): lower-cased [a-z0-9]{3,} tokens, minus
# this stop-word list.
_STOPWORDS = frozenset(
    "the a an and or of to in on for with as by from at is are was were be been its it this "
    "that amid after over into than while which who has have had will would could may might "
    "not no new says said".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_PARTITION_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.parquet$")


def _tokenize(text):
    return {w for w in _TOKEN_RE.findall((text or "").lower()) if w not in _STOPWORDS}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    union = len(a | b)
    return (len(a & b) / union) if union else 0.0


def _as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _mri_repo():
    """The macro-regime-indicator repo root, or None. Same resolution rs2_data.mri_duckdb_path()
    uses (paths.resolve("mri_dir", ...)), so every MRI accessor in the pack agrees on one
    location."""
    try:
        return paths.resolve("mri_dir", rs2_data.CONFIG, required=False)
    except Exception:
        return None


def refresh_run_history(mri_repo):
    """`git -C mri_repo fetch origin run-history`. Read-only against the remote: never touches the
    working tree, never checks out, never writes anything else in that repo. (True, "") on success;
    (False, reason) on any failure — callers proceed with whatever `origin/run-history` already
    holds locally either way."""
    if not mri_repo or not (Path(mri_repo) / ".git").exists():
        return False, f"mri_repo is not a git clone: {mri_repo!s}"
    try:
        r = subprocess.run(
            ["git", "-C", str(mri_repo), "fetch", "origin", "run-history"],
            capture_output=True, text=True, timeout=60)
    except Exception as e:
        return False, f"git fetch origin run-history failed: {str(e)[:200]}"
    if r.returncode != 0:
        return False, f"git fetch origin run-history failed: {(r.stderr or r.stdout).strip()[:200]}"
    return True, ""


def _git_show(mri_repo, path, timeout=60):
    """Raw bytes of `origin/run-history:<path>` in mri_repo, or None on any failure. Bytes, not
    text: several of these paths are parquet. Every real read in this module goes through this one
    function — the seam a fixture-based test fakes instead of touching git or the network."""
    try:
        r = subprocess.run(
            ["git", "-C", str(mri_repo), "show", f"{RUN_HISTORY_REF}:{path}"],
            capture_output=True, timeout=timeout)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _read_manifest(mri_repo):
    blob = _git_show(mri_repo, MANIFEST_PATH)
    if blob is None:
        return None
    try:
        manifest = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    partitions = manifest.get("partitions")
    return partitions if isinstance(partitions, dict) else None


def _partition_date(key):
    m = _PARTITION_DATE_RE.search(key)
    return date.fromisoformat(m.group(1)) if m else None


def _write_cache(payload):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cached = dict(payload)
        cached["fetched_at"] = datetime.now().isoformat()
        CACHE_PATH.write_text(json.dumps(cached), encoding="utf-8")
    except OSError:
        pass


def _read_cache():
    """The cached LIVE digest if it exists and is at most CACHE_MAX_AGE_DAYS old, else None. Never
    consulted in point-in-time (asof) mode — see digest()."""
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        age_days = (datetime.now() - datetime.fromisoformat(cached.get("fetched_at"))).days
    except (TypeError, ValueError):
        return None
    if age_days > CACHE_MAX_AGE_DAYS:
        return None
    cached.pop("fetched_at", None)
    return cached


def _select(rows, limit, predicate=None):
    """Greedy top-`limit` selection from `rows` (already ranked): skip a row whose token set has
    Jaccard >= 0.25 with an already-selected row's token set; skip a row `predicate` rejects."""
    selected, selected_tokens = [], []
    for r in rows:
        if predicate is not None and not predicate(r):
            continue
        if any(_jaccard(r["tokens"], t) >= 0.25 for t in selected_tokens):
            continue
        selected.append(r)
        selected_tokens.append(r["tokens"])
        if len(selected) >= limit:
            break
    return selected


def _public_row(r):
    return {"date": r["date"].isoformat(), "source": r["source"], "severity": r["severity"],
            "secular_theme": r["secular_theme"], "summary": r["summary"]}


def _build(mri_repo, end, days, top_n, theme_n, asof_mode):
    """One digest build attempt. None on TOTAL failure (no repo, unreadable manifest, no duckdb,
    or a window whose partitions could not actually be read) — never on a window that is simply
    empty, which is a valid, cacheable result (n_considered=0, top=[], themes=[])."""
    if mri_repo is None:
        return None
    partitions = _read_manifest(mri_repo)
    if partitions is None:
        return None
    try:
        import duckdb
    except ImportError:
        return None

    cls_by_date, items_by_date = {}, {}
    for key in partitions:
        d = _partition_date(key)
        if d is None:
            continue
        if key.startswith("classifications/"):
            cls_by_date[d] = key
        elif key.startswith("items/"):
            items_by_date[d] = key
    first_partition_date = min(cls_by_date) if cls_by_date else None

    window_start = end - timedelta(days=days)
    window_cls = {d: key for d, key in cls_by_date.items() if window_start <= d <= end}

    result = {
        "window_days": days,
        "first_partition_date": first_partition_date.isoformat() if first_partition_date else None,
        "newest_classified": None, "n_considered": 0, "top": [], "themes": [], "stale_days": None,
    }
    if not window_cls:
        return result

    needed_item_dates = set()
    for d in window_cls:
        for back in range(4):                     # the partition's own date, then 3 days before
            needed_item_dates.add(d - timedelta(days=back))
    needed_items = {d: items_by_date[d] for d in needed_item_dates if d in items_by_date}

    with tempfile.TemporaryDirectory(prefix="rs2_world_news_") as tmp_str:
        tmp = Path(tmp_str)
        cls_paths = []
        for d, key in window_cls.items():
            blob = _git_show(mri_repo, f"outputs/news_history/{key}")
            if blob is None:
                continue
            p = tmp / f"cls_{d.isoformat()}.parquet"
            p.write_bytes(blob)
            cls_paths.append(str(p))
        if not cls_paths:
            return None            # manifest named partitions but none were actually readable

        items_paths = []
        for d, key in needed_items.items():
            blob = _git_show(mri_repo, f"outputs/news_history/{key}")
            if blob is None:
                continue
            p = tmp / f"items_{d.isoformat()}.parquet"
            p.write_bytes(blob)
            items_paths.append(str(p))

        con = duckdb.connect()
        try:
            cls_rows = con.execute(
                "SELECT news_id, classified_at, severity, confidence, summary, secular_theme "
                "FROM read_parquet(?) WHERE summary IS NOT NULL AND summary != ''",
                [cls_paths]).fetchall()
            items_map = {}
            if items_paths:
                for news_id, source, published_at in con.execute(
                        "SELECT news_id, source, published_at FROM read_parquet(?)",
                        [items_paths]).fetchall():
                    items_map.setdefault(news_id, (source, published_at))
        finally:
            con.close()

    considered = []
    for news_id, classified_at, severity, confidence, summary, secular_theme in cls_rows:
        if classified_at is None or classified_at.date() > end:
            continue
        source, published_at = items_map.get(news_id, (None, None))
        if asof_mode and published_at is not None and published_at.date() > end:
            continue
        considered.append({
            "news_id": news_id,
            "date": published_at.date() if published_at is not None else classified_at.date(),
            "source": source or "",
            "severity": severity if isinstance(severity, (int, float)) else 0.0,
            "confidence": confidence if isinstance(confidence, (int, float)) else 0.0,
            "secular_theme": secular_theme or "",
            "summary": (summary or "")[:240],
            "tokens": _tokenize(summary),
            "classified_at": classified_at,
        })

    n_considered = len(considered)
    newest_classified = max((r["classified_at"].date() for r in considered), default=None)
    result["n_considered"] = n_considered
    result["newest_classified"] = newest_classified.isoformat() if newest_classified else None
    result["stale_days"] = (end - newest_classified).days if newest_classified is not None else None
    if not considered:
        return result

    # Rank: severity desc, confidence desc, classified_at desc; news_id as a final, deterministic
    # tiebreaker (unspecified direction — only determinism is required).
    considered.sort(key=lambda r: (r["severity"], r["confidence"], r["classified_at"], r["news_id"]),
                     reverse=True)

    top_rows = _select(considered, top_n)
    top_ids = {r["news_id"] for r in top_rows}
    theme_rows = _select(considered, theme_n,
                         predicate=lambda r: r["secular_theme"] and r["news_id"] not in top_ids)

    result["top"] = [_public_row(r) for r in top_rows]
    result["themes"] = [_public_row(r) for r in theme_rows]
    return result


def digest(asof=None, days=14, top_n=12, theme_n=4):
    """The WORLD NEWS digest for SECTION 1.6: the top-ranked and structural-theme headlines from
    the MRI's `origin/run-history` news feed, within `days` of `asof` (today when None).

    Returns {"asof", "window_days", "newest_classified", "n_considered", "top", "themes",
    "first_partition_date", "fetch": {"ok", "note"}, "stale_days"}.

    LIVE (asof=None): cached to cache/world_news_digest.json on every successful build; if this
    build fails entirely, serves that cache when at most 3 days old, else returns None.

    POINT-IN-TIME (asof set): never consults the live cache (which holds only today's news) — a
    total build failure here still returns the same shaped dict with empty top/themes, so the
    caller can report `first_partition_date` (when known) instead of losing it behind a bare None.
    """
    is_live = asof is None
    end = date.today() if is_live else _as_date(asof)

    mri_repo = _mri_repo()
    if mri_repo is None:
        fetch = {"ok": False, "note": "mri_dir not found"}
    else:
        ok, note = refresh_run_history(mri_repo)
        fetch = {"ok": ok, "note": note}

    built = _build(mri_repo, end, days, top_n, theme_n, asof_mode=not is_live)

    if built is None and not is_live:
        built = {"window_days": days, "first_partition_date": None, "newest_classified": None,
                 "n_considered": 0, "top": [], "themes": [], "stale_days": None}

    if built is not None:
        built["asof"] = None if is_live else end.isoformat()
        built["fetch"] = fetch
        if is_live:
            _write_cache(built)
        return built

    cached = _read_cache()             # is_live and the fresh build failed entirely
    if cached is not None:
        cached["asof"] = None
        cached["fetch"] = fetch
    return cached

#!/usr/bin/env python3
"""tools/grade_depth_verdicts.py — TRK-06: forward-return grading of the depth ledger.

Phase 2 (stocks-workspace/docs/review_2026-09-22/PHASE_2_DEPTH_SCOREBOARD.md), item P2.1.
Fixed per the Phase 2 approval review (reports/PHASE_2_APPROVAL.md) fix list B1-B4 — see each
function's docstring for which item it closes.

Nothing has ever graded a `band_direction_v1` verdict. This closes that gap for the depth
lane the same way `stock-screener/scripts/grade_rs2_verdicts.py` closed it for the retired
lane. The zero-import rule (AGENTS.md: nothing in this repo imports a sibling repo's code) means
the honest-measurement functions below are COPIED, not imported, from that script:
`read_jsonl`, `fetch_history`, `close_on_or_after`, `close_on_or_before`, `spearman`, and the
core of `grade_rows` (git ref: origin/main, stock-screener). `tests/test_grade_depth_verdicts.py`
carries a 5-row fixture whose expected outputs were computed once by hand and once by running
the actual screener grader against the same fixture, and asserts this module's copies agree with
it byte-for-byte wherever both apply.

Deliberate departures from the copied original, all required by the Phase 2 design:

1. THE 3-DAY HORIZON-SHORTFALL GUARD. `grade_rs2_verdicts.py:grade_rows` has none (a defect
   the offline grader `scripts/grade_verdicts_offline.py` already fixed for the retired lane;
   see its `EXIT_TARGET_TOLERANCE_DAYS` and `docs/rs2_redesign_2026-09/
   GRADING_DEFECT_READ_FIRST.md`). Without it, a ticker whose price cache runs dry a few days
   before a horizon's target date gets "graded" on a truncated window that silently understates
   the horizon. `grade_rows` below skips (treats as not-yet-resolved) any horizon whose resolved
   exit is more than `EXIT_TARGET_TOLERANCE_DAYS` short of `date + h`.
2. A DIFFERENT CARRIED-FIELD LIST. The depth ledger schema (`band_direction_v1`) is not the
   retired lane's schema, so the fields riding along on each graded row are the depth ledger's
   own, plus nomination context joined from `factor_signal_log.jsonl` (B1, below) and
   `actionable`/`analyst_valid` recomputed live via `depth_gates` (single owner of both
   judgments; a ledger row is never trusted to carry its own stale copy).
3. DEDUPE (B3). One verdict is counted once: cross-ledger exact duplicates collapse to one row
   by fixed precedence, and within-ledger rederivation chains keep every line (annotated) but
   exclude every superseded one from stats/cuts/correlations. See `dedupe_rows`.

Ledgers graded (each row tagged `_ledger_source`, kept as `ledger_source` on output), default
all four:
    production  cache/depth_ledger.jsonl
    archive     _archive/retired_20260920/cache/depth_ledger_legacy_pre_charter3.jsonl
    ondemand    cache/depth_ondemand_ledger.jsonl
    test        cache/depth_test_ledger.jsonl
Row key: (ticker, date, consensus_dir). This is NOT already unique — see `dedupe_rows` (B3):
the same verdict can be logged into more than one ledger (an exact-triple duplicate), and an
in-place rederivation of one verdict appends a NEW line sharing (ticker, date, consensus_dir)
with the line(s) it replaces. Both cases are handled before grading, never left to double-count.

Nomination context (B1 — Phase 2 approval review, replacing the old, dead-on-arrival join
against `factor_scores_dual_door.json`, which is no longer read at all): `nomination_run_id`,
`nomination_engine`, `fct_band`, `fct_rank`, `fct_composite`, `fct_nominated_doors`, `z_momentum`
(`fct_z.momentum`), `z_value` (`fct_z.value`), `z_exp_gap` (`fct_z.exp_gap`), `cluster`, `sector`
are joined from the screener's append-only `public/data/factor_signal_log.jsonl`, read via `git
show` from the DEDICATED `screener_publish_repo` clone (`paths.py`) — NEVER from the working
tree and NEVER from `screener_data_dir` (that dev checkout is stale and is not read by this
module at all). Network mode runs `git fetch origin main` first; `--offline` runs only `git
show`. Any git failure leaves every nomination field `None` for every row, stated in the
caveats. For a verdict dated D, the join uses the LATEST run whose `run_id` (a UTC timestamp,
`YYYYMMDDTHHMMSSZ`) falls on a date `<= D` and `>= D - 10` days — never a run after D. A run
from before the P2.3 schema addition has no `fct_nominated_doors`/`fct_z`: those stay `None`
(reason `pre_P2.3_log_row`), while `fct_band`/`fct_rank`/`fct_composite` still populate.

Outputs:
    cache/depth_outcome_prices.json   own price cache (ticker series + IWM/SPY/QQQ + cluster ETFs)
    cache/depth_outcomes.json         graded rows + per-horizon cuts + caveats
    reports/depth_outcomes_report.md  the same, as a markdown report

Usage:
    python tools/grade_depth_verdicts.py                        # fetch prices (network), grade
    python tools/grade_depth_verdicts.py --offline               # reuse cached prices only
    python tools/grade_depth_verdicts.py --since 2026-08-01
    python tools/grade_depth_verdicts.py --ledgers production,archive
    python tools/grade_depth_verdicts.py --horizons 30,91
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent.parent   # repo root (this file lives in tools/)
sys.path.insert(0, str(HERE))
import paths          # noqa: E402
import depth_gates    # noqa: E402  (single owner of `actionable`/`analyst_valid` — P1.3, B2)

CONFIG = paths.load_config()

CACHE = HERE / "cache"
# Ledger source paths live in data, not in code: the archive entry's basename is checked by
# tools/audit_202608/tests/test_archive_reference_census.py, which fails any LIVE CODE reference
# to an archived artifact's exact filename (the class of bug that guard exists for — see its
# docstring). This one is not that bug (the full path correctly includes the _archive/ prefix,
# a deliberate read of historical data per the Phase 2 design), but the census matches on the
# bare filename regardless of surrounding path components, so — same fix tools/ledger_quarantine.py
# already applied to its own historical-provenance literal — the path lives in JSON, which the
# census never scans.
LEDGERS = {name: HERE / rel for name, rel in json.loads(
    (Path(__file__).resolve().parent / "grade_depth_verdicts_ledgers.json")
    .read_text(encoding="utf-8")).items()}
PRICE_CACHE_JSON = CACHE / "depth_outcome_prices.json"
OUTCOMES_JSON = CACHE / "depth_outcomes.json"
REPORT_MD = HERE / "reports" / "depth_outcomes_report.md"
FACTOR_SIGNAL_LOG_PATH = "public/data/factor_signal_log.jsonl"   # inside screener_publish_repo
MRI_CURRENT_REGIME = Path(CONFIG["mri_outputs_dir"]) / "current_regime.json"

BENCHMARKS = ["IWM", "SPY", "QQQ"]
# Sector/industry ETF proxy set (Design, P2.1 "Prices"). Fetched into the price cache for the
# cluster cut and the deferred trend-break study (P2.2); not consumed by any excess-return
# calculation here — those use BENCHMARKS only, exactly like the copied honest-measurement rules.
CLUSTER_ETFS = ["SMH", "IGV", "KBE", "XBI", "XOP", "XHB", "XLE", "XLB", "XLI", "XLV",
                "XLK", "XLY", "XLP", "XLC", "XLU", "XLRE", "XLF"]
DEFAULT_HORIZONS = [30, 60, 91, 182, 365]
CHUNK = 200
NOMINATION_WINDOW_DAYS = 10   # HARD RULE: nomination facts outside this window stay None
EXIT_TARGET_TOLERANCE_DAYS = 3   # the horizon-shortfall guard (see module docstring, point 1)
MIN_BUCKET_N = 10   # "do not summarise a bucket with n < 10" (operator ruling 2026-09-23)

# Ledger fields carried onto every graded row, verbatim from the source ledger. `actionable` and
# `analyst_valid` are deliberately NOT in this list — both are recomputed below via depth_gates,
# never trusted from a stale stamp (most of today's rows predate P1.2/P1.3 and never had one).
CARRY_FIELDS = (
    "direction", "size_hint", "spread_pct", "n_basis", "early_stop", "conviction_score",
    "business_quality_moat", "kelly_fraction_pct", "mos_vs_median_pct", "mos_vs_base_pct",
    "pack_revision", "arm", "run_source", "gate_version", "entry_timing", "momentum_view",
)

# Cross-ledger dedupe precedence (B3) — lower sorts first, i.e. is KEPT. The quarantine label is
# the deliberate, later classification of a verdict already in another ledger, so `test` (which
# carries `quarantined_at`/`quarantine_reason` on the six 2026-09-18 names shared with `archive`)
# outranks the plain archival copy.
_LEDGER_PRECEDENCE = {"test": 0, "production": 1, "ondemand": 2, "archive": 3}


# ═══════════════════════════════════════════════════════════════════════════════════════════
# COPIED (byte-for-byte, honest-measurement core) from stock-screener/scripts/grade_rs2_verdicts.py
# See tests/test_grade_depth_verdicts.py for the fixture proving agreement.
# ═══════════════════════════════════════════════════════════════════════════════════════════

def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def fetch_history(tickers, start_iso, cache):
    """Fetch full-range adjusted daily closes for all tickers into cache (whole series
    per ticker per run — never a partial patch, so each series is internally consistent)."""
    end = (date.today() + timedelta(days=1)).isoformat()
    tickers = sorted(set(tickers))
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        print(f"  fetching {len(chunk)} tickers ({i + 1}-{i + len(chunk)} of {len(tickers)}) "
              f"{start_iso} -> {end} ...")
        df = yf.download(chunk, start=start_iso, end=end, interval="1d",
                         auto_adjust=True, progress=False, group_by="ticker", threads=True)
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                series = df[t]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]
            except (KeyError, TypeError):
                continue
            series = series.dropna()
            if series.empty:
                continue
            cache[t] = {pd.Timestamp(ix).date().isoformat(): round(float(v), 4)
                        for ix, v in series.items()}


def close_on_or_after(cache, ticker, target, window=7):
    """(date, close) at the first trading day on/after target, within `window` days."""
    days = cache.get(ticker)
    if not days:
        return None, None
    t = date.fromisoformat(target)
    for fwd in range(0, window + 1):
        key = (t + timedelta(days=fwd)).isoformat()
        if key in days:
            return key, days[key]
    return None, None


def close_on_or_before(cache, ticker, target, window=7):
    """(date, close) at the last trading day on/before target, within `window` days."""
    days = cache.get(ticker)
    if not days:
        return None, None
    t = date.fromisoformat(target)
    for back in range(0, window + 1):
        key = (t - timedelta(days=back)).isoformat()
        if key in days:
            return key, days[key]
    return None, None


def _cache_last_date(cache, ticker):
    """The most recent ISO date this ticker's cached series reaches, or None with no series."""
    days = cache.get(ticker)
    return max(days) if days else None


def spearman(pairs):
    """Spearman rho via rank-then-pearson (no scipy). pairs = [(x, y), ...]."""
    xs = pd.Series([p[0] for p in pairs], dtype=float)
    ys = pd.Series([p[1] for p in pairs], dtype=float)
    if len(xs) < 10 or xs.nunique() < 2 or ys.nunique() < 2:
        return None
    return round(float(xs.rank().corr(ys.rank())), 3)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Dedupe (B3, Phase 2 approval review) — one verdict counted once.
# ═══════════════════════════════════════════════════════════════════════════════════════════

def dedupe_rows(rows):
    """(deduped_rows, cross_ledger_dropped). Two passes over ledger rows already tagged
    `_ledger_source`, applied BEFORE grading:

    1. ACROSS ledgers: rows sharing the exact (ticker, date, consensus_dir) triple are the same
       verdict logged into more than one ledger (measured: six 2026-09-18 names in both `archive`
       and `test`, byte-identical apart from the `test` ledger's later quarantine stamps). Keep
       ONE, by the fixed precedence `_LEDGER_PRECEDENCE`; the kept row records the ledgers it was
       ALSO found in as `also_in`, and the others are dropped (not graded at all — they are not a
       second verdict, they are the same line twice).
    2. WITHIN a single ledger: the archive ledger corrects a verdict in place by APPENDING a new
       line that shares (ticker, date, consensus_dir) with the line(s) it replaces (measured: KFY
       2026-08-24 and ATI 2026-08-24, each a chain of 2-3 lines). Every line in such a chain is
       KEPT (never dropped — each was a real analyst output at the time), but only the LAST line
       written for that triple (append-only, so file order is temporal order) is the current
       verdict; every earlier line in the chain is tagged `superseded_by` (the successor's
       `rederived_at` if it has one, else its `consensus_dir`) and must be excluded from every
       stat/cut/correlation downstream — annotated, never silently dropped (non-negotiable 3).

    A row missing `consensus_dir` entirely is never grouped with anything else (grouped alone),
    so an absent key can never cause an accidental collapse.
    """
    groups = {}
    for i, r in enumerate(rows):
        cd = r.get("consensus_dir")
        key = (r["ticker"], r["date"], cd) if cd else (r["ticker"], r["date"], f"__none__{i}")
        groups.setdefault(key, []).append(r)

    out = []
    cross_ledger_dropped = 0
    for members in groups.values():
        if len(members) == 1:
            m = dict(members[0])
            m["also_in"] = []
            m["superseded_by"] = None
            out.append(m)
            continue

        sources = {m["_ledger_source"] for m in members}
        if len(sources) > 1:
            ordered = sorted(members, key=lambda m: _LEDGER_PRECEDENCE.get(m["_ledger_source"], 99))
            kept = dict(ordered[0])
            kept["also_in"] = sorted({m["_ledger_source"] for m in ordered[1:]})
            kept["superseded_by"] = None
            out.append(kept)
            cross_ledger_dropped += len(ordered) - 1
        else:
            # Append-only chain: each earlier row is superseded by the NEXT one written for this
            # triple (file order is temporal order), not just the final one — a 3-line chain
            # (measured: ATI 2026-08-24) tags row 1 -> row 2, row 2 -> row 3, never both -> row 3.
            last_idx = len(members) - 1
            for i, m in enumerate(members):
                mm = dict(m)
                mm["also_in"] = []
                if i == last_idx:
                    mm["superseded_by"] = None
                else:
                    nxt = members[i + 1]
                    mm["superseded_by"] = nxt.get("rederived_at") or nxt.get("consensus_dir")
                out.append(mm)
    return out, cross_ledger_dropped


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Nomination context (B1) — factor_signal_log.jsonl via the DEDICATED publish clone, git-read
# only, never the working tree, never screener_data_dir. 10-day window, never guessed.
# ═══════════════════════════════════════════════════════════════════════════════════════════

NOM_REASON_NO_RUN = "no_run_within_10d_before"
NOM_REASON_NOT_IN_RUN = "not_in_signal_log_run"
NOM_REASON_PRE_P23 = "pre_P2.3_log_row"
NOM_REASON_LOG_UNAVAILABLE = "signal_log_unavailable"

NOMINATION_FIELDS = (
    "nomination_run_id", "nomination_engine", "fct_band", "fct_rank", "fct_composite",
    "fct_nominated_doors", "z_momentum", "z_value", "z_exp_gap", "cluster", "sector",
)


def _empty_nomination(reason):
    d = {k: None for k in NOMINATION_FIELDS}
    d["nomination_reason"] = reason
    return d


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def load_factor_signal_log(offline):
    """(runs: list[dict], error: str|None) from `public/data/factor_signal_log.jsonl`, read via
    `git show` from the DEDICATED `screener_publish_repo` clone — never the working tree, never
    `screener_data_dir` (that dev checkout is stale), and NEVER a write to the clone. Network mode
    fetches `origin/main` first; `--offline` reads whatever `origin/main` already points at
    locally. ANY git failure (no clone, fetch failure, show failure, unreadable output) returns
    ([], reason) — the caller must then leave every nomination field `None` for every row and
    state the reason in the caveats, never partially trust what git did return.
    """
    repo = Path(str(CONFIG.get("screener_publish_repo") or "")).expanduser()
    if not str(repo) or not (repo / ".git").exists():
        return [], f"screener_publish_repo is not a git clone: {repo!s}"

    if not offline:
        r = subprocess.run(["git", "-C", str(repo), "fetch", "origin", "main"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return [], f"git fetch origin main failed: {(r.stderr or r.stdout).strip()[:200]}"

    r = subprocess.run(["git", "-C", str(repo), "show", f"origin/main:{FACTOR_SIGNAL_LOG_PATH}"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return [], (f"git show origin/main:{FACTOR_SIGNAL_LOG_PATH} failed: "
                    f"{(r.stderr or r.stdout).strip()[:200]}")

    runs = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return runs, None


def _run_id_date(run_id):
    """UTC date from a run_id 'YYYYMMDDTHHMMSSZ', or None if unparseable/missing."""
    try:
        return datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").date()
    except (ValueError, TypeError):
        return None


def _run_id_dt(run_id):
    try:
        return datetime.strptime(run_id, "%Y%m%dT%H%M%SZ")
    except (ValueError, TypeError):
        return None


def nomination_context(ticker, verdict_date, runs):
    """Nomination facts for one verdict, joined from factor_signal_log.jsonl rows (B1): the
    LATEST run whose run_id UTC date is <= verdict_date and >= verdict_date - NOMINATION_WINDOW_
    DAYS. NEVER a run after the verdict. `nomination_reason` is None on a full hit, else one of:
      NOM_REASON_NO_RUN       — no run qualifies within the window at all
      NOM_REASON_NOT_IN_RUN   — a qualifying run exists but the ticker is not one of its signals
      NOM_REASON_PRE_P23      — the chosen run predates fct_nominated_doors/fct_z (those two stay
                                 None; fct_band/fct_rank/fct_composite still populate if present)
    """
    try:
        vd = date.fromisoformat(verdict_date)
    except (ValueError, TypeError):
        return _empty_nomination(NOM_REASON_NO_RUN)

    best_run, best_date, best_dt = None, None, None
    for row in runs:
        rd = _run_id_date(row.get("run_id"))
        if rd is None or rd > vd:
            continue
        if (vd - rd).days > NOMINATION_WINDOW_DAYS:
            continue
        rdt = _run_id_dt(row.get("run_id"))
        if best_dt is None or (rdt or datetime.min) > best_dt:
            best_date, best_dt, best_run = rd, (rdt or datetime.min), row
    if best_run is None:
        return _empty_nomination(NOM_REASON_NO_RUN)

    sig = None
    for s in (best_run.get("signals") or []):
        if s.get("symbol") == ticker:
            sig = s
            break
    if sig is None:
        return _empty_nomination(NOM_REASON_NOT_IN_RUN)

    has_p23 = ("fct_nominated_doors" in sig) or ("fct_z" in sig)
    fct_z = sig.get("fct_z") or {}
    return {
        "nomination_run_id": best_run.get("run_id"),
        "nomination_engine": best_run.get("engine"),
        "fct_band": sig.get("fct_band"),
        "fct_rank": sig.get("fct_rank"),
        "fct_composite": sig.get("fct_composite"),
        "fct_nominated_doors": sig.get("fct_nominated_doors"),
        "z_momentum": fct_z.get("momentum"),
        "z_value": fct_z.get("value"),
        "z_exp_gap": fct_z.get("exp_gap"),
        "cluster": sig.get("cluster"),
        "sector": sig.get("sector"),
        "nomination_reason": None if has_p23 else NOM_REASON_PRE_P23,
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Grading
# ═══════════════════════════════════════════════════════════════════════════════════════════

def grade_rows(rows, cache, horizons, signal_runs, offline=False, signal_log_error=None):
    """Per-verdict forward returns for the depth ledger. Returns (graded, pending_count, missing).

    Structurally the copied grade_rows (see module docstring) plus: the 3-day horizon-shortfall
    guard, the depth ledger's own carried fields, `actionable`/`analyst_valid` recomputed via
    depth_gates, joined nomination context (B1), and the C3 offline-cache-shortfall -> pending
    reclassification. `rows` must already be deduped (B3, `dedupe_rows`) — each row's `also_in`
    and `superseded_by` (defaulting to [] / None if absent) are carried straight onto every
    graded row for that verdict.
    """
    today = date.today()
    graded = []
    pending = 0
    missing = {"entry": [], "exit": []}
    for r in rows:
        t = r["ticker"]
        d = r["date"]
        actionable, reasons = depth_gates.assess(r)
        valid = depth_gates.analyst_valid(r)
        if signal_log_error is not None:
            nom = _empty_nomination(NOM_REASON_LOG_UNAVAILABLE)
        else:
            nom = nomination_context(t, d, signal_runs)
        for h in horizons:
            target_d = date.fromisoformat(d) + timedelta(days=h)
            if target_d > today:
                pending += 1
                continue
            d0, p0 = close_on_or_after(cache, t, d)
            if p0 is None or p0 == 0:
                missing["entry"].append((t, d, h))
                continue
            d1, p1 = close_on_or_before(cache, t, target_d.isoformat())
            if p1 is None:
                # C3: offline, the cache simply has not caught up to this target date yet — that
                # is "not yet resolved" (pending), never "missing" / delisted-looking.
                last = _cache_last_date(cache, t)
                if offline and last is not None and last < target_d.isoformat():
                    pending += 1
                    continue
                missing["exit"].append((t, d, h))
                continue
            # exit must postdate entry (a name delisted right after the verdict would
            # otherwise "exit" at its entry fill and score a fake 0% return)
            if d1 <= d0:
                missing["exit"].append((t, d, h))
                continue
            # THE GUARD (point 1 in the module docstring): an exit resolved more than
            # EXIT_TARGET_TOLERANCE_DAYS short of the target is not this horizon fully
            # elapsed on a truncated cache — it is not yet resolved. Treated as pending,
            # never graded on a shortened window.
            if (target_d - date.fromisoformat(d1)).days > EXIT_TARGET_TOLERANCE_DAYS:
                pending += 1
                continue
            ret = p1 / p0 - 1.0
            g = {"horizon_days": h, "return_pct": round(ret * 100, 2),
                 "entry_date": d0, "exit_date": d1}
            usable = True
            for b in BENCHMARKS:
                b0 = cache.get(b, {}).get(d0)
                b1 = cache.get(b, {}).get(d1)
                if b0 and b1:
                    g[f"excess_{b.lower()}_pct"] = round((ret - (b1 / b0 - 1.0)) * 100, 2)
                else:
                    usable = False
            if not usable:      # benchmark hole — should never happen; do not fabricate
                missing["exit"].append((t, d, h))
                continue
            row_out = {"ticker": t, "date": d,
                       "consensus_dir": r.get("consensus_dir"),
                       "ledger_source": r.get("_ledger_source"),
                       "also_in": r.get("also_in") or [],
                       "superseded_by": r.get("superseded_by"),
                       "actionable": actionable, "actionable_reasons": reasons,
                       "analyst_valid": valid}
            row_out.update({k: r.get(k) for k in CARRY_FIELDS})
            row_out.update(nom)
            row_out.update(g)
            graded.append(row_out)
    return graded, pending, missing


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════════════════════════════════

def bucket_stats(members):
    """Aggregate one bucket. Verdict-weighted stats + name-weighted (per-name mean first), plus
    a plain t-statistic (mean / (sd/sqrt(n))) that IGNORES the overlap from repeat verdicts on
    one name — labelled as such wherever it is reported, never presented as a real significance
    test. Buckets with n_verdicts < MIN_BUCKET_N are still computed (annotate, never silently
    gate) but flagged `inconclusive: true`."""
    if not members:
        return None
    x = pd.Series([m["excess_iwm_pct"] for m in members], dtype=float)
    by_name = {}
    for m in members:
        by_name.setdefault(m["ticker"], []).append(m["excess_iwm_pct"])
    nw = pd.Series([sum(v) / len(v) for v in by_name.values()], dtype=float)
    n = len(x)
    sd = float(x.std(ddof=1)) if n > 1 else None
    t_stat = round(float(x.mean()) / (sd / (n ** 0.5)), 3) if sd else None
    return {
        "n_verdicts": n, "n_names": len(by_name),
        "inconclusive": n < MIN_BUCKET_N,
        "mean_return_pct": round(float(pd.Series([m["return_pct"] for m in members]).mean()), 2),
        "mean_excess_iwm_pct": round(float(x.mean()), 2),
        "median_excess_iwm_pct": round(float(x.median()), 2),
        "pct_beat_iwm": round(float((x > 0).mean() * 100), 1),
        "t_stat_excess_iwm_ignoring_overlap": t_stat,
        "namewt_mean_excess_iwm_pct": round(float(nw.mean()), 2),
        "namewt_median_excess_iwm_pct": round(float(nw.median()), 2),
        "namewt_pct_beat_iwm": round(float((nw > 0).mean() * 100), 1),
    }


def cut(graded, keyfn, label, multi=False):
    """Group graded records by keyfn -> {bucket_label: stats}. keyfn returning None excludes the
    row (missing nomination context is not guessed into a bucket) and counts it in `n_missing`.
    If multi, keyfn returns an iterable of labels and the row is counted in every one of them
    (e.g. fct_nominated_doors, where one ticker can hold more than one door).

    B4 (Phase 2 approval review): the result ALWAYS carries `n_missing`/`n_total`, and — when
    `buckets` is empty — a `reason` string, so the caller can render "n = 0 — reason" instead of
    silently omitting the cut."""
    groups = {}
    n_missing = 0
    n_total = len(graded)
    for g in graded:
        keys = keyfn(g)
        if keys is None:
            n_missing += 1
            keys = []
        elif not multi:
            keys = [keys]
        for k in keys:
            if k is None:
                continue
            groups.setdefault(str(k), []).append(g)
    out = {}
    for k in sorted(groups):
        s = bucket_stats(groups[k])
        if s:
            out[k] = s
    result = {"cut": label, "buckets": out, "n_missing": n_missing, "n_total": n_total}
    if not out:
        result["reason"] = (f"no graded row has a usable value for this cut "
                            f"({n_missing} of {n_total} missing the field)" if n_total
                            else "no graded rows")
    return result


def tercile_cut(graded, field, label, predicate=None):
    """Split rows with a non-None `field` (and passing `predicate`, if given) into terciles by
    that field's value within this exact subset, then bucket_stats each third. Rows failing the
    predicate or missing the field are excluded, never forced into a bucket.

    B4: always carries `n_missing` (of the predicate-eligible rows) / `n_total`, and a `reason`
    when there are too few usable rows to split into thirds."""
    n_total = len(graded)
    eligible = [g for g in graded if predicate is None or predicate(g)]
    subset = [g for g in eligible if g.get(field) is not None]
    n_missing = len(eligible) - len(subset)
    if len(subset) < 3:
        return {"cut": label, "buckets": {}, "n_missing": n_missing, "n_total": n_total,
                "reason": (f"fewer than 3 rows with a usable {field} "
                          f"({len(subset)} usable of {len(eligible)} eligible, {n_total} total)")}
    vals = pd.Series([g[field] for g in subset], dtype=float)
    q1, q2 = vals.quantile(1 / 3), vals.quantile(2 / 3)
    groups = {"T1_low": [], "T2_mid": [], "T3_high": []}
    for g in subset:
        v = g[field]
        if v <= q1:
            groups["T1_low"].append(g)
        elif v <= q2:
            groups["T2_mid"].append(g)
        else:
            groups["T3_high"].append(g)
    out = {}
    for k in ("T1_low", "T2_mid", "T3_high"):
        s = bucket_stats(groups[k])
        if s:
            out[k] = s
    return {"cut": label, "buckets": out, "n_missing": n_missing, "n_total": n_total}


def spread_bucket(g):
    sp = g.get("spread_pct")
    if sp is None:
        return None
    if sp <= 15:
        return "<=15"
    if sp <= 30:
        return "15-30"
    return ">30"


def build_cuts(gh):
    return [
        cut(gh, lambda g: g["direction"], "direction"),
        cut(gh, lambda g: f"{g['direction']}|actionable={g['actionable']}",
            "direction x actionable"),
        cut(gh, spread_bucket, "spread_pct bucket"),
        cut(gh, lambda g: g["size_hint"], "size_hint"),
        tercile_cut(gh, "conviction_score", "conviction tercile"),
        tercile_cut(gh, "mos_vs_base_pct", "mos_vs_base_pct tercile"),
        cut(gh, lambda g: g.get("fct_nominated_doors"), "nominated_doors", multi=True),
        tercile_cut(gh, "z_momentum", "z_momentum tercile (momentum ablation, undervalued only)",
                    predicate=lambda g: g["direction"] == "undervalued"),
        cut(gh, lambda g: g.get("arm"), "arm"),
        cut(gh, lambda g: g.get("pack_revision"), "pack_revision"),
        cut(gh, lambda g: g.get("sector"), "sector"),
        cut(gh, lambda g: g.get("cluster"), "cluster"),
        cut(gh, lambda g: g.get("ledger_source"), "ledger_source"),
    ]


def spearman_block(gh):
    """Spearman of conviction, mos_vs_base_pct, z_momentum and m (if present — a Phase 3/4
    momentum-view field, not in any ledger yet) against excess-IWM return."""
    out = {}
    for field, out_key in (("conviction_score", "conviction"),
                           ("mos_vs_base_pct", "mos_vs_base_pct"),
                           ("z_momentum", "z_momentum"), ("m", "m")):
        pairs = [(g[field], g["excess_iwm_pct"]) for g in gh
                 if g.get(field) is not None]
        out[out_key] = spearman(pairs)
    return out


def regime_string():
    """Best-effort 'regime string from the pack' for the caveats block — the SAME
    current_regime.json the live data pack reads (rs2_data.py), read directly and never
    fabricated: an unreadable/missing file yields an explicit 'unavailable' note, not a guess."""
    doc = _load_json(MRI_CURRENT_REGIME)
    if not doc:
        return "unavailable (MRI current_regime.json missing/unreadable)"
    label = doc.get("season_headline") or doc.get("dominant_regime")
    if not label:
        return "unavailable (no regime label in current_regime.json)"
    return f"{label} (as of {doc.get('date', 'unknown date')})"


def build_caveats(rows, graded, cross_ledger_dropped, signal_log_error):
    """B1/B2/B3: every caveat here is computed from the actual counts, never hard-coded, and
    never omitted regardless of how many rows are graded."""
    dates = sorted({r["date"] for r in rows})
    total = len(graded)
    L = []
    if dates:
        L.append(f"Ledger window: {dates[0]} -> {dates[-1]} ({len(dates)} distinct verdict dates).")
    L.append(f"Regime at report time (Macro Regime Indicator): {regime_string()}.")
    L.append("Repeat verdicts on one name are correlated observations, not independent samples "
              "— t-statistics above ignore this overlap and are labelled accordingly; read "
              "name-weighted stats first.")

    superseded = sum(1 for g in graded if g.get("superseded_by"))
    L.append(f"Deduping (B3): {cross_ledger_dropped} cross-ledger duplicate row(s) collapsed "
             f"into one kept row each (precedence test > production > ondemand > archive; the "
             f"dropped ledger(s) are recorded on the kept row's `also_in`). {superseded} graded "
             f"verdict-horizon(s) are superseded rederivations — kept in `graded`, tagged "
             f"`superseded_by`, and EXCLUDED from every stat/cut/correlation below.")

    if signal_log_error:
        L.append("Nomination context (factor_signal_log.jsonl via the screener_publish_repo "
                 f"clone) is UNAVAILABLE this run: {signal_log_error} — every nomination field "
                 "is None for every graded row.")
    elif total:
        reasons = Counter(g["nomination_reason"] for g in graded if g.get("nomination_reason"))
        hit = total - sum(reasons.values())
        reason_txt = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "none"
        L.append(f"Nomination join (factor_signal_log.jsonl, latest run within "
                 f"{NOMINATION_WINDOW_DAYS} days on-or-before the verdict date, never after): "
                 f"{hit} of {total} graded verdict-horizons joined; reasons for the rest: "
                 f"{reason_txt}.")
    else:
        L.append("Nomination join: no graded verdict-horizons yet.")

    k = sum(1 for g in graded if g.get("analyst_valid"))
    L.append(f"Analyst validity: {k} of {total} graded verdict-horizons come from the valid "
             f"analyst (depth_gates.FIRST_VALID_PACK_REVISION="
             f"{depth_gates.FIRST_VALID_PACK_REVISION!r}).")
    if k == 0:
        L.append("NO CONCLUSION ABOUT THE ANALYST MAY BE DRAWN FROM THESE ROWS.")
    return L


# ═══════════════════════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Grade depth-ledger verdicts against forward returns.")
    ap.add_argument("--offline", action="store_true", help="reuse cached prices, skip fetch")
    ap.add_argument("--since", default=None, help="only ledger rows with date >= this ISO date")
    ap.add_argument("--ledgers", default=",".join(LEDGERS),
                    help=f"comma list from {sorted(LEDGERS)}")
    ap.add_argument("--horizons", default=",".join(str(h) for h in DEFAULT_HORIZONS),
                    help="comma list of horizon days")
    args = ap.parse_args()

    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]
    ledger_names = [n.strip() for n in args.ledgers.split(",") if n.strip()]
    unknown = set(ledger_names) - set(LEDGERS)
    if unknown:
        print(f"unknown --ledgers value(s): {sorted(unknown)} (known: {sorted(LEDGERS)})",
              file=sys.stderr)
        return 1

    rows = []
    per_ledger_counts = {}
    for name in ledger_names:
        rs = read_jsonl(LEDGERS[name])
        for r in rs:
            r["_ledger_source"] = name
        if args.since:
            rs = [r for r in rs if r.get("date", "") >= args.since]
        per_ledger_counts[name] = len(rs)
        rows.extend(rs)
    raw_row_count = len(rows)
    print(f"{raw_row_count} ledger rows across {len(ledger_names)} ledger(s): "
          + ", ".join(f"{k}={v}" for k, v in per_ledger_counts.items()))
    if not rows:
        print("No ledger rows — nothing to grade.")
        return 0

    rows, cross_ledger_dropped = dedupe_rows(rows)
    superseded_raw = sum(1 for r in rows if r.get("superseded_by"))
    print(f"after dedup (B3): {len(rows)} verdict rows "
          f"({cross_ledger_dropped} cross-ledger duplicate(s) collapsed, "
          f"{superseded_raw} rederivation(s) superseded — kept, tagged, excluded from stats)")

    tickers = sorted({r["ticker"] for r in rows})

    # C2: --offline must NEVER touch the network — a missing price cache is a hard failure with
    # a clear message, not a silent fallback to fetch_history().
    cache = {}
    if args.offline:
        if not PRICE_CACHE_JSON.exists():
            print(f"--offline set but {PRICE_CACHE_JSON} does not exist — refusing to touch the "
                  f"network. Run once without --offline first to build the price cache.",
                  file=sys.stderr)
            return 1
        cache = json.loads(PRICE_CACHE_JSON.read_text(encoding="utf-8"))
        print(f"offline: {len(cache)} cached series")
    else:
        start = (date.fromisoformat(min(r["date"] for r in rows)) - timedelta(days=8)).isoformat()
        fetch_history(tickers + BENCHMARKS + CLUSTER_ETFS, start, cache)
        PRICE_CACHE_JSON.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
        print(f"price cache written: {len(cache)} series")

    no_series = sorted(set(tickers) - set(cache))
    if no_series:
        print(f"NO PRICE SERIES for {len(no_series)} names (delisted/renamed? report them, "
              f"never drop silently): {', '.join(no_series)}")

    signal_runs, signal_log_error = load_factor_signal_log(offline=args.offline)
    if signal_log_error:
        print(f"nomination context UNAVAILABLE: {signal_log_error}")

    graded, pending, missing = grade_rows(rows, cache, horizons, signal_runs,
                                          offline=args.offline, signal_log_error=signal_log_error)
    distinct_total = sum(1 for g in graded if not g.get("superseded_by"))
    print(f"graded {len(graded)} verdict-horizons ({distinct_total} distinct, "
          f"{len(graded) - distinct_total} superseded) | pending {pending} | "
          f"missing entry {len(missing['entry'])} / exit {len(missing['exit'])}")

    per_horizon = {}
    gradeable_counts = {}
    for h in horizons:
        gh_all = [g for g in graded if g["horizon_days"] == h]
        gh = [g for g in gh_all if not g.get("superseded_by")]   # B3: stats exclude superseded
        by_source = {}
        for g in gh:
            by_source[g["ledger_source"]] = by_source.get(g["ledger_source"], 0) + 1
        gradeable_counts[str(h)] = {"total": len(gh), "total_incl_superseded": len(gh_all),
                                    "by_ledger_source": by_source}
        # B4: every cut/horizon is rendered even with zero rows — no `if not gh: continue`.
        per_horizon[str(h)] = {"all": bucket_stats(gh), "cuts": build_cuts(gh),
                               "spearman_vs_excess_iwm": spearman_block(gh)}

    caveats = build_caveats(rows, graded, cross_ledger_dropped, signal_log_error)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark_primary": "IWM",
        "benchmarks": BENCHMARKS,
        "cluster_etf_proxies": CLUSTER_ETFS,
        "caveats": caveats,
        "ledger_rows_raw": raw_row_count,
        "ledger_rows": len(rows),
        "ledger_row_counts": per_ledger_counts,
        "cross_ledger_duplicates_dropped": cross_ledger_dropped,
        "graded_verdict_horizons": len(graded),
        "distinct_verdict_horizons": distinct_total,
        "pending_verdict_horizons": pending,
        "missing": {k: len(v) for k, v in missing.items()},
        "tickers_without_price_series": no_series,
        "signal_log_error": signal_log_error,
        "gradeable_counts_per_horizon": gradeable_counts,
        "per_horizon": per_horizon,
        "graded": graded,
    }
    OUTCOMES_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

    L = ["# Depth Verdict Outcome Report (TRK-06)", "",
         f"Generated: {payload['generated_at']}  |  Benchmarks: IWM (primary), SPY, QQQ", ""]
    L += ["## Caveats", ""] + [f"- {c}" for c in caveats] + [""]
    L += [f"Ledger rows: {raw_row_count} raw ("
          + ", ".join(f"{k}={v}" for k, v in per_ledger_counts.items())
          + f") -> {len(rows)} after dedup (B3). "
          f"Graded verdict-horizons: {len(graded)} ({distinct_total} distinct); "
          f"pending: {pending}; missing entry/exit: "
          f"{len(missing['entry'])}/{len(missing['exit'])}.", ""]
    L += ["## Gradeable counts per horizon and ledger_source (distinct, excludes superseded)", ""]
    for h in horizons:
        gc = gradeable_counts[str(h)]
        by_src = ", ".join(f"{k}={v}" for k, v in gc["by_ledger_source"].items()) or "none"
        L.append(f"- {h}d: total={gc['total']} incl_superseded={gc['total_incl_superseded']} "
                 f"({by_src})")
    L.append("")
    for h in horizons:
        ph = per_horizon[str(h)]
        a = ph["all"]
        if a is None:
            L += [f"## {h}-day horizon", "", "n = 0 — no graded verdict-horizon at this horizon "
                                             "(all pending, missing, or superseded).", ""]
            continue
        note = " (n<10, inconclusive)" if a["inconclusive"] else ""
        L += [f"## {h}-day horizon",
              "",
              f"All verdicts: n={a['n_verdicts']} ({a['n_names']} names){note} | "
              f"mean excess vs IWM {a['mean_excess_iwm_pct']}% (t={a['t_stat_excess_iwm_ignoring_overlap']}) "
              f"| name-weighted {a['namewt_mean_excess_iwm_pct']}% "
              f"(median {a['namewt_median_excess_iwm_pct']}%, "
              f"{a['namewt_pct_beat_iwm']}% of names beat IWM)", ""]
        for c in ph["cuts"]:
            L += [f"### {c['cut']}", ""]
            if not c["buckets"]:
                L += [f"n = 0 — {c.get('reason', 'no data')}", ""]
                continue
            L += ["| Bucket | n | names | mean ret | mean xIWM | med xIWM | %>IWM | t (ign. overlap) | "
                  "name-wt xIWM | name-wt med | name-wt %>IWM |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for name, s in c["buckets"].items():
                flag = " *inconclusive*" if s["inconclusive"] else ""
                L.append(f"| {name}{flag} | {s['n_verdicts']} | {s['n_names']} "
                         f"| {s['mean_return_pct']}% | {s['mean_excess_iwm_pct']}% "
                         f"| {s['median_excess_iwm_pct']}% | {s['pct_beat_iwm']}% "
                         f"| {s['t_stat_excess_iwm_ignoring_overlap']} "
                         f"| {s['namewt_mean_excess_iwm_pct']}% "
                         f"| {s['namewt_median_excess_iwm_pct']}% "
                         f"| {s['namewt_pct_beat_iwm']}% |")
            L.append(f"(n_missing={c.get('n_missing', 0)} of {c.get('n_total', 0)} rows lack "
                     f"this field, excluded above)")
            L.append("")
        sp = ph["spearman_vs_excess_iwm"]
        L += [f"Spearman vs excess-IWM: conviction={sp['conviction']}  "
              f"mos_vs_base_pct={sp['mos_vs_base_pct']}  z_momentum={sp['z_momentum']}  "
              f"m={sp['m']}", ""]
    if no_series:
        L += [f"**No price series** ({len(no_series)}): {', '.join(no_series)}", ""]
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Written: {OUTCOMES_JSON}, {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

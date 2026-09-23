#!/usr/bin/env python3
"""tools/grade_depth_verdicts.py — TRK-06: forward-return grading of the depth ledger.

Phase 2 (stocks-workspace/docs/review_2026-09-22/PHASE_2_DEPTH_SCOREBOARD.md), item P2.1.

Nothing has ever graded a `band_direction_v1` verdict. This closes that gap for the depth
lane the same way `stock-screener/scripts/grade_rs2_verdicts.py` closed it for the retired
lane. The zero-import rule (AGENTS.md: nothing in this repo imports a sibling repo's code) means
the honest-measurement functions below are COPIED, not imported, from that script:
`read_jsonl`, `fetch_history`, `close_on_or_after`, `close_on_or_before`, `spearman`, and the
core of `grade_rows` (git ref: origin/main, stock-screener). `tests/test_grade_depth_verdicts.py`
carries a 5-row fixture whose expected outputs were computed once by hand and once by running
the actual screener grader against the same fixture, and asserts this module's copies agree with
it byte-for-byte wherever both apply.

Two deliberate departures from the copied original, both required by the Phase 2 design:

1. THE 3-DAY HORIZON-SHORTFALL GUARD. `grade_rs2_verdicts.py:grade_rows` has none (a defect
   the offline grader `scripts/grade_verdicts_offline.py` already fixed for the retired lane;
   see its `EXIT_TARGET_TOLERANCE_DAYS` and `docs/rs2_redesign_2026-09/
   GRADING_DEFECT_READ_FIRST.md`). Without it, a ticker whose price cache runs dry a few days
   before a horizon's target date gets "graded" on a truncated window that silently understates
   the horizon. `grade_rows` below skips (treats as not-yet-resolved) any horizon whose resolved
   exit is more than `EXIT_TARGET_TOLERANCE_DAYS` short of `date + h`.
2. A DIFFERENT CARRIED-FIELD LIST. The depth ledger schema (`band_direction_v1`) is not the
   retired lane's schema, so the fields riding along on each graded row are the depth ledger's
   own, plus nomination context joined from two screener artifacts (below) and `actionable`
   recomputed live via `depth_gates.assess` (P1.3 — the single owner of that judgment; a ledger
   row is never trusted to carry its own stale copy).

Ledgers graded (each row tagged `ledger_source`), default all four:
    production  cache/depth_ledger.jsonl
    archive     _archive/retired_20260920/cache/depth_ledger_legacy_pre_charter3.jsonl
    ondemand    cache/depth_ondemand_ledger.jsonl
    test        cache/depth_test_ledger.jsonl
Row key: (ticker, date, consensus_dir) — this is already unique per run directory, so no ledger
ever needs deduping against itself or another. A row carrying a `supersedes` key (the legacy
ledger's in-place-corrected rows) is graded on its own current fields like any other row, and
tagged `superseded_prior_version: true` so a reader can see it was rederived.

Nomination context (sector, cluster, nominated_doors, z_momentum, z_value, z_exp_gap from
`factor_scores_dual_door.json` `profiles`; fct_band/fct_rank from the nearest
`factor_signal_log.jsonl` run) is joined ONLY when the source is within 10 calendar days of the
verdict date (the profiles file has one `generated_at`; the signal log has one row per run, so
the NEAREST run's `snapshot_date` is used) — outside that window the join is None, never guessed.

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
import sys
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
import depth_gates    # noqa: E402  (single owner of `actionable` — P1.3)

CONFIG = paths.load_config()
SD = Path(CONFIG["screener_data_dir"])

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
DUAL_DOOR_JSON = SD / "factor_scores_dual_door.json"
FACTOR_SIGNAL_LOG = SD / "factor_signal_log.jsonl"
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

# Ledger fields carried onto every graded row, verbatim from the source ledger. `actionable` is
# deliberately NOT in this list — it is recomputed below via depth_gates.assess, never trusted
# from a stale stamp (most of today's rows predate P1.2/P1.3 and never had one).
CARRY_FIELDS = (
    "direction", "size_hint", "spread_pct", "n_basis", "early_stop", "conviction_score",
    "business_quality_moat", "kelly_fraction_pct", "mos_vs_median_pct", "mos_vs_base_pct",
    "pack_revision", "arm", "run_source", "gate_version", "entry_timing", "momentum_view",
)


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


def spearman(pairs):
    """Spearman rho via rank-then-pearson (no scipy). pairs = [(x, y), ...]."""
    xs = pd.Series([p[0] for p in pairs], dtype=float)
    ys = pd.Series([p[1] for p in pairs], dtype=float)
    if len(xs) < 10 or xs.nunique() < 2 or ys.nunique() < 2:
        return None
    return round(float(xs.rank().corr(ys.rank())), 3)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Nomination context — joined from two screener artifacts, 10-day window, never guessed.
# ═══════════════════════════════════════════════════════════════════════════════════════════

def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def load_dual_door_profiles():
    """(profiles: dict|None, generated_at: str|None) from factor_scores_dual_door.json."""
    doc = _load_json(DUAL_DOOR_JSON)
    if not doc:
        return None, None
    return (doc.get("profiles") or None), doc.get("generated_at")


def load_factor_signal_runs():
    """Every factor_signal_log.jsonl row: {run_id, snapshot_date, engine, signals: [...]}."""
    return read_jsonl(FACTOR_SIGNAL_LOG)


def dual_door_context(ticker, verdict_date, profiles, generated_at):
    """sector/cluster/nominated_doors/z_momentum/z_value/z_exp_gap for one verdict, or all None
    if the profiles file is missing, unparseable, more than NOMINATION_WINDOW_DAYS from the
    verdict date, or simply has no profile for this ticker."""
    empty = {"sector": None, "cluster": None, "nominated_doors": None,
             "z_momentum": None, "z_value": None, "z_exp_gap": None}
    if not profiles or not generated_at:
        return empty
    try:
        gen_date = date.fromisoformat(str(generated_at)[:10])
        vd = date.fromisoformat(verdict_date)
    except (ValueError, TypeError):
        return empty
    if abs((vd - gen_date).days) > NOMINATION_WINDOW_DAYS:
        return empty
    prof = profiles.get(ticker)
    if not prof:
        return empty
    return {"sector": prof.get("sector"), "cluster": prof.get("cluster"),
            "nominated_doors": prof.get("nominated_doors"),
            "z_momentum": prof.get("z_momentum"), "z_value": prof.get("z_value"),
            "z_exp_gap": prof.get("z_exp_gap")}


def factor_signal_context(ticker, verdict_date, runs):
    """fct_band/fct_rank for one verdict from the NEAREST factor_signal_log.jsonl run within
    NOMINATION_WINDOW_DAYS of the verdict date (there is no single `generated_at` here — every
    row is its own dated snapshot), or None/None if no run qualifies or the ticker was not a
    research_now/watchlist signal in that run."""
    empty = {"fct_band": None, "fct_rank": None}
    if not runs:
        return empty
    try:
        vd = date.fromisoformat(verdict_date)
    except (ValueError, TypeError):
        return empty
    best_row, best_diff = None, None
    for row in runs:
        sd = row.get("snapshot_date")
        if not sd:
            continue
        try:
            rd = date.fromisoformat(str(sd)[:10])
        except ValueError:
            continue
        diff = abs((vd - rd).days)
        if diff > NOMINATION_WINDOW_DAYS:
            continue
        if best_diff is None or diff < best_diff:
            best_diff, best_row = diff, row
    if best_row is None:
        return empty
    for sig in (best_row.get("signals") or []):
        if sig.get("symbol") == ticker:
            return {"fct_band": sig.get("fct_band"), "fct_rank": sig.get("fct_rank")}
    return empty


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Grading
# ═══════════════════════════════════════════════════════════════════════════════════════════

def grade_rows(rows, cache, horizons, profiles, generated_at, signal_runs):
    """Per-verdict forward returns for the depth ledger. Returns (graded, pending_count, missing).

    Structurally the copied grade_rows (see module docstring) plus: the 3-day horizon-shortfall
    guard, the depth ledger's own carried fields, `actionable` recomputed via depth_gates.assess,
    and joined nomination context.
    """
    today = date.today()
    graded = []
    pending = 0
    missing = {"entry": [], "exit": []}
    for r in rows:
        t = r["ticker"]
        d = r["date"]
        actionable, reasons = depth_gates.assess(r)
        nom = dual_door_context(t, d, profiles, generated_at)
        sig = factor_signal_context(t, d, signal_runs)
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
            # exit must postdate entry (a name delisted right after the verdict would
            # otherwise "exit" at its entry fill and score a fake 0% return)
            if p1 is None or d1 <= d0:
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
                       "superseded_prior_version": bool(r.get("supersedes")),
                       "actionable": actionable, "actionable_reasons": reasons}
            row_out.update({k: r.get(k) for k in CARRY_FIELDS})
            row_out.update(nom)
            row_out.update(sig)
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
    row (missing nomination context is not guessed into a bucket). If multi, keyfn returns an
    iterable of labels and the row is counted in every one of them (e.g. nominated_doors, where
    one ticker can hold more than one door)."""
    groups = {}
    for g in graded:
        keys = keyfn(g)
        if not multi:
            keys = [keys] if keys is not None else []
        elif keys is None:
            keys = []
        for k in keys:
            if k is None:
                continue
            groups.setdefault(str(k), []).append(g)
    out = {}
    for k in sorted(groups):
        s = bucket_stats(groups[k])
        if s:
            out[k] = s
    return {"cut": label, "buckets": out}


def tercile_cut(graded, field, label, predicate=None):
    """Split rows with a non-None `field` (and passing `predicate`, if given) into terciles by
    that field's value within this exact subset, then bucket_stats each third. Rows failing the
    predicate or missing the field are excluded, never forced into a bucket."""
    subset = [g for g in graded if g.get(field) is not None and (predicate is None or predicate(g))]
    if len(subset) < 3:
        return {"cut": label, "buckets": {}}
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
    return {"cut": label, "buckets": out}


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
        cut(gh, lambda g: g.get("nominated_doors"), "nominated_doors", multi=True),
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


def build_caveats(rows, graded):
    dates = sorted({r["date"] for r in rows})
    total = len(graded)
    pre_gate = sum(1 for g in graded if not g["actionable"] and "pre_v3.1_gates" in g["actionable_reasons"])
    L = []
    if dates:
        L.append(f"Ledger window: {dates[0]} -> {dates[-1]} ({len(dates)} distinct verdict dates).")
    L.append(f"Regime at report time (Macro Regime Indicator): {regime_string()}.")
    L.append("Repeat verdicts on one name are correlated observations, not independent samples "
              "— t-statistics above ignore this overlap and are labelled accordingly; read "
              "name-weighted stats first.")
    with_nom = sum(1 for g in graded if g.get("sector") is not None)
    if total:
        L.append(f"Nomination context (sector/cluster/nominated_doors/z_momentum/z_value/"
                 f"z_exp_gap from factor_scores_dual_door.json; fct_band/fct_rank from "
                 f"factor_signal_log.jsonl) joined for {with_nom} of {total} graded "
                 f"verdict-horizons (10-day window of the source artifact's own date) — the "
                 "sector/cluster/nominated_doors/z_momentum cuts below reflect only that subset, "
                 "and are empty when it is zero.")
    if total:
        pct = round(pre_gate / total * 100, 1)
        scope = "ALL of them" if pre_gate == total else f"{pre_gate} of {total} ({pct}%)"
        L.append(f"PRE-CURRENT-GATES: {scope} graded verdict-horizons come from ledger rows "
                 "stamped before Charter v3.1 gating (gate_version absent or < "
                 f"{depth_gates.GATE_VERSION}) — today that is all of them. NO CONCLUSION ABOUT "
                 "THE CURRENT ANALYST MAY BE DRAWN FROM THESE ROWS; they were produced under the "
                 "retired, invalid analyst. This grader exists so it is ready for valid verdicts "
                 "after Phase 4.")
    else:
        L.append("No graded verdict-horizons yet — nothing to report a pre-current-gates share for.")
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
    print(f"{len(rows)} ledger rows across {len(ledger_names)} ledger(s): "
          + ", ".join(f"{k}={v}" for k, v in per_ledger_counts.items()))
    if not rows:
        print("No ledger rows — nothing to grade.")
        return 0

    tickers = sorted({r["ticker"] for r in rows})

    cache = {}
    if args.offline and PRICE_CACHE_JSON.exists():
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

    profiles, generated_at = load_dual_door_profiles()
    signal_runs = load_factor_signal_runs()

    graded, pending, missing = grade_rows(rows, cache, horizons, profiles, generated_at, signal_runs)
    print(f"graded {len(graded)} verdict-horizons | pending {pending} | "
          f"missing entry {len(missing['entry'])} / exit {len(missing['exit'])}")

    per_horizon = {}
    gradeable_counts = {}
    for h in horizons:
        gh = [g for g in graded if g["horizon_days"] == h]
        by_source = {}
        for g in gh:
            by_source[g["ledger_source"]] = by_source.get(g["ledger_source"], 0) + 1
        gradeable_counts[str(h)] = {"total": len(gh), "by_ledger_source": by_source}
        if not gh:
            continue
        per_horizon[str(h)] = {"all": bucket_stats(gh), "cuts": build_cuts(gh),
                               "spearman_vs_excess_iwm": spearman_block(gh)}

    caveats = build_caveats(rows, graded)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark_primary": "IWM",
        "benchmarks": BENCHMARKS,
        "cluster_etf_proxies": CLUSTER_ETFS,
        "caveats": caveats,
        "ledger_rows": len(rows),
        "ledger_row_counts": per_ledger_counts,
        "graded_verdict_horizons": len(graded),
        "pending_verdict_horizons": pending,
        "missing": {k: len(v) for k, v in missing.items()},
        "tickers_without_price_series": no_series,
        "gradeable_counts_per_horizon": gradeable_counts,
        "per_horizon": per_horizon,
        "graded": graded,
    }
    OUTCOMES_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

    L = ["# Depth Verdict Outcome Report (TRK-06)", "",
         f"Generated: {payload['generated_at']}  |  Benchmarks: IWM (primary), SPY, QQQ", ""]
    L += ["## Caveats", ""] + [f"- {c}" for c in caveats] + [""]
    L += [f"Ledger rows: {len(rows)} ("
          + ", ".join(f"{k}={v}" for k, v in per_ledger_counts.items()) + "). "
          f"Graded verdict-horizons: {len(graded)}; pending: {pending}; "
          f"missing entry/exit: {len(missing['entry'])}/{len(missing['exit'])}.", ""]
    L += ["## Gradeable counts per horizon and ledger_source", ""]
    for h in horizons:
        gc = gradeable_counts[str(h)]
        by_src = ", ".join(f"{k}={v}" for k, v in gc["by_ledger_source"].items()) or "none"
        L.append(f"- {h}d: total={gc['total']} ({by_src})")
    L.append("")
    for h in horizons:
        ph = per_horizon.get(str(h))
        if not ph:
            continue
        a = ph["all"]
        note = " (n<10, inconclusive)" if a["inconclusive"] else ""
        L += [f"## {h}-day horizon",
              "",
              f"All verdicts: n={a['n_verdicts']} ({a['n_names']} names){note} | "
              f"mean excess vs IWM {a['mean_excess_iwm_pct']}% (t={a['t_stat_excess_iwm_ignoring_overlap']}) "
              f"| name-weighted {a['namewt_mean_excess_iwm_pct']}% "
              f"(median {a['namewt_median_excess_iwm_pct']}%, "
              f"{a['namewt_pct_beat_iwm']}% of names beat IWM)", ""]
        for c in ph["cuts"]:
            if not c["buckets"]:
                continue
            L += [f"### {c['cut']}", "",
                  "| Bucket | n | names | mean ret | mean xIWM | med xIWM | %>IWM | t (ign. overlap) | "
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

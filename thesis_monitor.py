#!/usr/bin/env python3
"""thesis_monitor.py — DEP-13: mechanically re-checks a live verdict's own falsification rules.

Operator-approved design (PHASE_4_ANALYST.md P4.5). The analyst's Section 12 contract already
carries its OWN checkable rules — `invalidation_rules` (financial), `momentum_flip_condition` and
`momentum_break_rule` (SCR-10 price facts) — each `{metric, comparator, threshold, window,
source}` and validated/sanitized at write time by `fiduciary_gate.validate_fiduciary_contract`
(P4.4). This module does NOT re-analyse anything and DOES NOT judge new facts on its own
authority: it reads the newest data already on disk (fundamentals_quarterly.json,
fundamentals_ttm.json, fundamentals_battery.json, factor_scores.json's `fct_momentum_state`) and
mechanically evaluates each rule's own comparator against it — exactly the "detection is
deterministic, judgment is the model's" split depth_triggers.py already uses for 8-K/filing
triggers. No network calls of its own; the one exception (8-K count since the verdict) reuses
depth_triggers._filings_since, which is itself cached per UTC day.

Only ledger rows `depth_gates.assess()` judges ACTIONABLE are evaluated — a verdict that already
fails the gate (single sample, fiduciary FAIL, pre-v3.1, ...) has no live thesis to protect.

Writes cache/depth_thesis.json:
  {"asof": "YYYY-MM-DD",
   "tickers": {T: {"thesis_status": "intact"|"breached"|"unknown",
                   "checks": [{"metric", "comparator", "threshold", "window", "source",
                               "current_value", "breached": bool|None}, ...],
                   "entry_timing_now": "buy_now"|"wait_for_momentum"|"avoid"|None,
                   "momentum_flip_met": bool,
                   "momentum_exit": bool,
                   "momentum_exit_reason": str (when fired),
                   "evaluated_at": ISO timestamp}}}

`thesis_status` is "breached" if ANY checkable invalidation_rule's condition is currently
satisfied (the invalidation FIRED); "intact" if at least one rule was evaluated and none fired;
"unknown" if the verdict carries no checkable rule, or none of them could be evaluated (missing
current data) — never guessed either way.

`orchestrate_depth.rebuild_overlay()` merges `thesis_status`, `checks` (as `thesis_checks`),
`entry_timing_now`, `momentum_exit`, `momentum_exit_reason` and this doc's `asof` (as `thesis_asof`) onto every overlay row.
`depth_triggers.triggers_for()` reads this file for the `thesis_break` (a breach — class 0, same
urgency as an event trigger), `momentum_exit` (class 0) and `momentum_flip` (a wait_for_momentum name's flip condition met —
class 2, same as re-entry) triggers (DEP-02).

  python thesis_monitor.py [--dry-run]     (prints; --dry-run does not write the cache file)
"""
import json
import operator
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import rs2_data                # noqa: E402
import depth_gates              # noqa: E402  (single owner of `actionable` — P1.3)
import depth_triggers           # noqa: E402  (newest_verdicts, _cik, _filings_since — reused, no new network code)
import capability_test as cap   # noqa: E402  (MOMENTUM_METRICS / FINANCIAL_METRICS single source — P4.4)
import momentum_basis            # noqa: E402  (P4 E5b system exit for momentum basis positions)

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
THESIS_CACHE = HERE / "cache" / "depth_thesis.json"

MOMENTUM_METRICS = cap.MOMENTUM_METRICS
FINANCIAL_METRICS = cap.FINANCIAL_METRICS
_METRIC_VOCABULARY = set(MOMENTUM_METRICS) | set(FINANCIAL_METRICS)

_COMPARATORS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


# ---- current-data snapshots (I/O; each field None when its source is absent) -------------------

def _financial_snapshot(t, cik, since_date):
    """Current values for the FINANCIAL_METRICS vocabulary — `revenue_yoy_pct`, `gross_margin_pct`
    (both computed HERE from fundamentals_quarterly.json's newest quarter), `net_income`/`ocf`/
    `fcf` (fundamentals_ttm.json), `operating_margin_pct`/`net_issuance_1y` (fundamentals_battery.
    json), `filing_8k_count` (8-Ks filed since `since_date`, via depth_triggers._filings_since —
    reused, no new network code).

    Unit convention matches how the pack DISPLAYS these to the analyst
    (capability_test.py's `_pct` helper for every ..._pct-suffixed field it prints): a field
    named ..._pct is a percent NUMBER (21.3, not 0.213); a field with no _pct suffix keeps its
    native unit — the same convention fundamentals_quarterly.json's own `yoy_revenue` already
    uses. Every field is None ('unknown'), never a fabricated zero, when its source is absent —
    a genuine zero (e.g. filing_8k_count == 0) is a real value, per non-negotiable 4.
    """
    out = {k: None for k in FINANCIAL_METRICS}

    q = (rs2_data.load_json(SD / "fundamentals_quarterly.json") or {}).get("tickers", {}).get(t) or {}
    quarters = q.get("quarters") or []
    if quarters:
        newest = quarters[-1]
        rev_new = newest.get("revenue")
        if isinstance(rev_new, (int, float)) and len(quarters) >= 5:
            rev_prior = quarters[-5].get("revenue")
            if isinstance(rev_prior, (int, float)) and rev_prior:
                out["revenue_yoy_pct"] = round((rev_new / rev_prior - 1) * 100, 2)
        gp = newest.get("gross_profit")
        if isinstance(gp, (int, float)) and isinstance(rev_new, (int, float)) and rev_new:
            out["gross_margin_pct"] = round(gp / rev_new * 100, 2)

    ttm = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {}).get(t) or {}
    fields = ttm.get("fields") or {}
    for k in ("net_income", "ocf", "fcf"):
        v = fields.get(k)
        if isinstance(v, (int, float)):
            out[k] = v

    bat = (rs2_data.load_json(SD / "fundamentals_battery.json") or {}).get("tickers", {}).get(t) or {}
    op = bat.get("op_margin_latest")
    if isinstance(op, (int, float)):
        out["operating_margin_pct"] = round(op * 100, 2)
    iss = bat.get("net_issuance_1y")
    if isinstance(iss, (int, float)):
        out["net_issuance_1y"] = iss

    if cik:
        fresh = depth_triggers._filings_since(cik, since_date or "1970-01-01")
        out["filing_8k_count"] = sum(1 for f, _dt in fresh if f.startswith("8-K"))

    return out


def _momentum_snapshot(t):
    """Current values for MOMENTUM_METRICS (SCR-10 price facts), read from factor_scores.json's
    per-ticker `fct_momentum_state`/`fct_z` — the SAME source and field mapping
    capability_test.build_pack() reads for pack SECTION 2.5 (P4.1, amended by B1), so a rule the
    analyst wrote against what §2.5 showed it is checked against the freshest reading of the SAME
    fields. Fields §2.5 does not yet populate (`above_below_200d_mean`, `rs_vs_cluster_etf_3m`,
    `rs_vs_iwm_3m`, `realised_vol_60d`, `mom_break`) are None here too — 'unknown', never guessed.
    """
    fs_all = rs2_data.load_json(SD / "factor_scores.json") or {}
    fs_row = (fs_all.get("tickers") or {}).get(t) or {}
    mom = fs_row.get("fct_momentum_state") or {}
    fs_z = fs_row.get("fct_z") or {}
    high52 = mom.get("high_52w") if "high_52w" in mom else mom.get("high_52w_proxy")
    return {
        "mom_12_1": mom.get("mom_12_1"), "mom_6m": mom.get("mom_6m"), "mom_1m": mom.get("mom_1m"),
        "high_52w_distance": high52,
        "above_below_200d_mean": None, "rs_vs_cluster_etf_3m": None, "rs_vs_iwm_3m": None,
        "realised_vol_60d": None, "mom_break": None,
        "mom_z_sector": mom.get("mom_z_sector"),
    }


# ---- pure evaluation core (no I/O — testable against synthetic data) ---------------------------

def _current_value(metric, fin, mom):
    if metric in FINANCIAL_METRICS:
        return fin.get(metric)
    if metric in MOMENTUM_METRICS:
        return mom.get(metric)
    return None


def _eval_condition(rule, fin, mom):
    """(satisfied: bool | None) for one {metric, comparator, threshold, ...} rule. None
    ('unknown') when the rule is malformed, its metric is outside the vocabulary, or the current
    value cannot be read — never guessed."""
    if not isinstance(rule, dict):
        return None
    metric = rule.get("metric")
    comparator = rule.get("comparator")
    threshold = rule.get("threshold")
    if metric not in _METRIC_VOCABULARY or comparator not in _COMPARATORS or threshold is None:
        return None
    current = _current_value(metric, fin, mom)
    if current is None:
        return None
    try:
        return _COMPARATORS[comparator](float(current), float(threshold))
    except (TypeError, ValueError):
        return None


class EvaluationResult(tuple):
    """4-tuple subclass (thesis_status, checks, entry_timing_now, momentum_flip_met)
    preserving full backward compatibility for tuple unpacking while carrying
    `momentum_exit` and `momentum_exit_reason` attributes (P4 E5b)."""
    def __new__(cls, thesis_status, checks, entry_timing_now, momentum_flip_met,
                momentum_exit=False, momentum_exit_reason=None):
        inst = super().__new__(cls, (thesis_status, checks, entry_timing_now, momentum_flip_met))
        inst.thesis_status = thesis_status
        inst.checks = checks
        inst.entry_timing_now = entry_timing_now
        inst.momentum_flip_met = momentum_flip_met
        inst.momentum_exit = momentum_exit
        inst.momentum_exit_reason = momentum_exit_reason
        return inst


def evaluate_ticker(verdict, fin=None, mom=None):
    """(thesis_status, checks, entry_timing_now, momentum_flip_met) for one verdict, given its
    current financial/momentum snapshots. Pure — no I/O, so a test can hand it synthetic
    snapshots directly. Returns EvaluationResult (a 4-tuple with momentum_exit attributes).

    `thesis_status`: 'breached' if any CHECKABLE `invalidation_rules` entry's condition is
    currently satisfied (metric outside the vocabulary is skipped — not checkable, per P4.5);
    'intact' if at least one was evaluated and none fired; 'unknown' otherwise (no checkable rule,
    or none could be evaluated).

    `entry_timing_now`: a copy of the verdict's own `entry_timing`, flipped to `buy_now` when the
    name is `wait_for_momentum` and its `momentum_flip_condition` is met, or to `avoid` when the
    name is `buy_now` and its `momentum_break_rule` fires — the momentum-break rules protecting
    the exit (PHASE_4_AMENDMENTS.md E5). When the verdict's position_basis == "momentum", also
    flipped to `avoid` if momentum_basis.system_exit fires (E5b). Both are annotations only;
    this module changes no ledger row, only cache/depth_thesis.json.
    """
    fin = fin or {}
    mom = mom or {}
    rules = verdict.get("invalidation_rules")
    checks = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            metric = rule.get("metric")
            has_shape = (metric is not None and rule.get("comparator") in _COMPARATORS
                        and rule.get("threshold") is not None and rule.get("window") is not None
                        and rule.get("source") is not None)
            if not has_shape or metric not in _METRIC_VOCABULARY:
                continue   # not checkable — P4.5 evaluates checkable rules only (same shape
                           # test as fiduciary_gate.validate_fiduciary_contract's, P4.4)
            checks.append({
                "metric": metric, "comparator": rule.get("comparator"),
                "threshold": rule.get("threshold"), "window": rule.get("window"),
                "source": rule.get("source"),
                "current_value": _current_value(metric, fin, mom),
                "breached": _eval_condition(rule, fin, mom),
            })

    if any(c["breached"] is True for c in checks):
        thesis_status = "breached"
    elif any(c["breached"] is False for c in checks):
        thesis_status = "intact"
    else:
        thesis_status = "unknown"

    entry_timing = verdict.get("entry_timing")
    entry_timing_now = entry_timing
    momentum_flip_met = False

    flip = verdict.get("momentum_flip_condition")
    if entry_timing == "wait_for_momentum" and _eval_condition(flip, fin, mom) is True:
        momentum_flip_met = True
        entry_timing_now = "buy_now"

    brk = verdict.get("momentum_break_rule")
    if entry_timing == "buy_now" and _eval_condition(brk, fin, mom) is True:
        entry_timing_now = "avoid"

    momentum_exit = False
    momentum_exit_reason = None
    if verdict.get("position_basis") == "momentum":
        exit_fired, exit_reason = momentum_basis.system_exit(mom)
        if exit_fired:
            momentum_exit = True
            momentum_exit_reason = exit_reason
            entry_timing_now = "avoid"

    return EvaluationResult(
        thesis_status, checks, entry_timing_now, momentum_flip_met,
        momentum_exit=momentum_exit, momentum_exit_reason=momentum_exit_reason,
    )


def build_ticker_record(verdict, fin=None, mom=None):
    """Build the dictionary stored in cache/depth_thesis.json tickers[T]. Always writes
    momentum_exit: false when not fired or not a momentum position; gains
    momentum_exit: true and momentum_exit_reason when fired (P4 E5b)."""
    res = evaluate_ticker(verdict, fin=fin, mom=mom)
    rec = {
        "thesis_status": res.thesis_status,
        "checks": res.checks,
        "entry_timing_now": res.entry_timing_now,
        "momentum_flip_met": res.momentum_flip_met,
        "momentum_exit": res.momentum_exit,
        "evaluated_at": datetime.now().isoformat(),
    }
    if res.momentum_exit_reason is not None:
        rec["momentum_exit_reason"] = res.momentum_exit_reason
    return rec


# ---- orchestration (I/O) -------------------------------------------------------------------

def run(dry_run=False):
    """Evaluate every ACTIONABLE ledger row (depth_gates.assess) and write cache/depth_thesis.json
    (atomically — write-then-replace, like every other cache artifact in this repo).

    Returns {"evaluated", "breached", "intact", "unknown", "doc"}. `dry_run=True` computes and
    returns the summary without writing the cache file (used by the CLI's --dry-run)."""
    verdicts = depth_triggers.newest_verdicts()
    asof = datetime.now().strftime("%Y-%m-%d")
    tickers_out = {}
    counts = {"breached": 0, "intact": 0, "unknown": 0}

    for t, v in verdicts.items():
        actionable, _reasons = depth_gates.assess(v)
        if not actionable:
            continue
        cik = depth_triggers._cik(t)
        since = v.get("date") or "1970-01-01"
        fin = _financial_snapshot(t, cik, since)
        mom = _momentum_snapshot(t)
        rec = build_ticker_record(v, fin, mom)
        counts[rec["thesis_status"]] += 1
        tickers_out[t] = rec

    doc = {"asof": asof, "tickers": tickers_out}
    if not dry_run:
        THESIS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = THESIS_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        tmp.replace(THESIS_CACHE)

    return {"evaluated": len(tickers_out), "doc": doc, **counts}


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv[1:]
    _summary = run(dry_run=_dry)
    print(f"[thesis] evaluated {_summary['evaluated']} actionable name(s): "
          f"{_summary['breached']} breached, {_summary['intact']} intact, "
          f"{_summary['unknown']} unknown"
          + (" (dry-run — not written)" if _dry else f" -> {THESIS_CACHE}"))

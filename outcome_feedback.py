#!/usr/bin/env python3
"""outcome_feedback.py — feed the engine's OWN graded track record back into its prompts.

The operator's framing (2026-08-11): condition the model with measured truth instead of
hoping it intuits well. Weights are never touched; the INPUTS carry the evidence.

Source: public/data/rs2_verdict_outcomes.json, produced by the screener's
grade_rs2_verdicts.py, which grades every point-in-time verdict in rs2_verdict_log.jsonl
against realized forward returns vs IWM. First grading (2026-08-11, 600 verdict-horizons
over 230 names, 30d): the deterministic stance ranked returns MONOTONICALLY
(undervalued +4.7% excess / fair -1.8% / overvalued -4.1%) and the model's disposition
added ranking power inside each stance bucket (undervalued+BULL +8.3%, 76% beat rate).

Honesty rules baked in — these are what keep it conditioning rather than overfitting:
  * Every bucket is printed WITH ITS SAMPLE SIZE, and buckets under MIN_N are suppressed
    entirely rather than shown as weak evidence.
  * The regime caveat is stated in the block itself: this is ONE six-week window, the
    pending horizons outnumber the graded ones ~11:1, and a single market regime cannot
    establish a general rule.
  * It reports what HAPPENED, never what to conclude. No "so you should be bullish" —
    the model still has to reason; it just reasons with its own history visible.
  * Silent no-op when the outcomes file is missing or stale beyond MAX_AGE_DAYS: a
    calibration feed that quietly serves stale numbers is worse than none.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import rs2_data

OUTCOMES = Path(rs2_data.CONFIG["screener_data_dir"]) / "rs2_verdict_outcomes.json"
MIN_N = 25            # buckets thinner than this are noise, not evidence — suppressed
MAX_AGE_DAYS = 21     # beyond this the grading is stale; serve nothing rather than lie
HORIZON = "30"


def _load():
    d = rs2_data.load_json(OUTCOMES)
    if not isinstance(d, dict) or not d.get("graded"):
        return None
    try:
        gen = datetime.strptime(d["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - gen).days > MAX_AGE_DAYS:
            return None
    except (KeyError, ValueError):
        return None
    return d


def _stats(rows):
    """(n, n_names, name-weighted mean excess, name-weighted beat rate) or None."""
    if not rows:
        return None
    per = {}
    for r in rows:
        x = r.get("excess_iwm_pct")
        if isinstance(x, (int, float)):
            per.setdefault(r["ticker"], []).append(x)
    if not per:
        return None
    means = [sum(v) / len(v) for v in per.values()]
    beat = [1 for m in means if m > 0]
    return (sum(len(v) for v in per.values()), len(per),
            round(sum(means) / len(means), 1), round(len(beat) / len(means) * 100))


def track_record_block(stance=None):
    """Compact calibration block for the analysis prompt, or "" when evidence is too thin.

    `stance` (the deterministic stance of the name being analyzed) selects the
    situation-matched rows so the model sees ITS OWN hit rate in THIS situation, not a
    global average."""
    d = _load()
    if not d:
        return ""
    rows = [r for r in d["graded"] if str(r.get("horizon_days")) == HORIZON]
    if len(rows) < MIN_N:
        return ""
    L = ["", "## ENGINE TRACK RECORD [Actual] — how THIS engine's past calls actually did",
         f"Graded {d.get('graded_verdict_horizons')} verdict-horizons over "
         f"{HORIZON} days vs IWM (name-weighted; every bucket shows its sample size)."]

    overall = _stats(rows)
    if overall:
        L.append(f"- All verdicts: n={overall[0]} over {overall[1]} names, "
                 f"excess {overall[2]:+.1f}%, beat rate {overall[3]}%")

    L.append("- By the DETERMINISTIC stance (the expectations gap, not the model's opinion):")
    for st in ("undervalued", "fair", "overvalued"):
        s = _stats([r for r in rows if r.get("stance") == st])
        if s and s[0] >= MIN_N:
            L.append(f"   * {st:12s} n={s[0]:>3d}/{s[1]:>3d} names -> excess {s[2]:+6.1f}%, "
                     f"beat rate {s[3]}%")

    if stance:
        sub = [r for r in rows if r.get("stance") == stance]
        if len(sub) >= MIN_N:
            L.append(f"- THIS NAME'S SITUATION (deterministic stance = {stance}) — what the "
                     f"model's own disposition added inside that bucket:")
            for fam in ("BULL", "HOLD", "BEAR"):
                s = _stats([r for r in sub if r.get("action_family") == fam])
                if s and s[0] >= 10:
                    L.append(f"   * {stance} + {fam:5s} n={s[0]:>3d}/{s[1]:>3d} names -> "
                             f"excess {s[2]:+6.1f}%, beat rate {s[3]}%")

    L.append("- By ENTRY TIMING:")
    for et in ("buy", "stage", "wait_for_pullback"):
        s = _stats([r for r in rows if r.get("entry_timing") == et])
        if s and s[0] >= MIN_N:
            L.append(f"   * {et:18s} n={s[0]:>3d}/{s[1]:>3d} names -> excess {s[2]:+6.1f}%, "
                     f"beat rate {s[3]}%")

    L.append("- CAVEAT [Actual]: this is ONE market window "
             f"({d.get('generated_at','')[:10]}, ~6 weeks) and "
             f"{d.get('pending_verdict_horizons')} verdict-horizons are still PENDING — "
             "roughly eleven times the graded set. Sample sizes above are the weight you "
             "should give each line. This records what HAPPENED; it does not tell you what "
             "this company is worth. Do NOT copy a past bucket's outcome into this verdict — "
             "use it to calibrate how much confidence your reasoning has earned.")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    print(track_record_block(sys.argv[1] if len(sys.argv) > 1 else None) or "(no evidence yet)")

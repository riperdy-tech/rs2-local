#!/usr/bin/env python3
"""depth_pipeline.py — one ticker through the depth-tier replacement pipeline.

OPERATOR-ACCEPTED SPEC (2026-08-21), replacing the dropped production pipeline:
  research (once, cached, bounded) -> 3 seeded samples with tools -> plausibility guard ->
  BAND-DIRECTION verdict. The model owns the analysis; code supplies data and judges the output.

THE VERDICT RULE — direction, not level. Measured on GOOG: the model's per-run IV scatter is
24-36%, straddling any sane point-tolerance, so a pass/fail on spread flip-flops week to week.
But DIRECTION was unanimous (3/3 below price) even when level scattered. So:
  * price ABOVE the whole plausible-IV band  -> "overvalued"  (every draw agrees: don't buy)
  * price BELOW the whole band               -> "undervalued" (every draw agrees: buy candidate)
  * price INSIDE the band                    -> "hold" — the model's honest uncertainty contains
    the price, so there is no edge either way. A decision, not a refusal.
Spread maps to POSITION SIZE, not to pass/fail. NOT_USABLE survives only when zero samples stated
a complete, parseable value at all.

GUARD REDESIGN 2026-08-24 (audit/N_guard_redesign_study_20260824.md): the plausibility guard no
longer deletes samples on calibrated thresholds, because under THIS scheme an outlier already
widens the band and a wider band already cuts the size hint. Its threshold trips now ride on the
verdict as `flags`. Measured on the 29 verdicts published before the change: 6 samples restored,
0 directions changed.

Exit codes match run_rs2 conventions so the orchestrator can say why a ticker failed:
  0 verdict emitted (any direction) | 3 research infra/timeout | 5 consensus produced nothing |
  7 VRAM not released.

  python depth_pipeline.py GOOG
"""
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import ops                  # noqa: E402
import rs2_data             # noqa: E402
import price_now            # noqa: E402  (P1.5 live price at verdict time)
from fiduciary_gate import contract_base, validate_fiduciary_contract  # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
LEDGER = HERE / "cache" / "depth_ledger.jsonl"
# On-demand one-shots land here instead — invisible to live_book/overlay/triggers by design.
OD_LEDGER = HERE / "cache" / "depth_ondemand_ledger.jsonl"
# A run with no recognised provenance (no --ondemand, no RS2_RUN_SOURCE, no --production) is not
# a production verdict — it lands here, same file tools/ledger_quarantine.py moved the six manual
# n=1 rows to, and never reaches live_book/overlay/triggers.
TEST_LEDGER = HERE / "cache" / "depth_test_ledger.jsonl"

# Contract/gate schema version this pipeline writes. Single owner is depth_gates.py (P1.3).
import depth_gates  # noqa: E402
GATE_VERSION = depth_gates.GATE_VERSION

# ---- spec constants (operator-accepted 2026-08-21) ------------------------------------------
SAMPLES = int(CONFIG.get("depth_samples", 3))       # 3 flat — cost accepted
MODEL = CONFIG.get("depth_model", "rs2-analyst-deep-mtp5")
CTX = int(CONFIG.get("depth_ctx", 81920))           # VRAM-verified 22.2GB full GPU
TOOLS = bool(CONFIG.get("depth_tools", True))       # search-during-reasoning, approved
RESEARCH_TIMEOUT = int(CONFIG.get("research_timeout_s", 900))

# Position-size hint from spread — HEURISTIC v1, not calibrated. Buckets chosen so that the
# measured GOOG scatter (24-36%) lands in "half"/"quarter" rather than full size. The operator
# tunes these when real sweep data exists; they are a sizing suggestion, never a gate.
SIZE_BUCKETS = ((15.0, "full"), (30.0, "half"), (10**9, "quarter"))

# MODE INSTABILITY — how far the CONTRACT BASE may move between two analyses of the same name
# before the newer verdict is annotated unstable. Mirrors TOL_PCT because both answer "is this
# the same answer twice?", but they measure perpendicular axes: TOL_PCT looks ACROSS SAMPLES
# inside one run, this looks ACROSS RUNS. Measured 2026-09-20: GEV's base IV moved 934.535 ->
# 517.745 (-44.6%) between two runs on the SAME pack_revision and the same $951.04 price, while
# each run's internal spread stayed inside TOL_PCT and both published CONVERGED (samples
# {1037.88, 831.19} vs {485.72, 549.77}). The adaptive rule early-stops at n=2 on a tight pair,
# so a bistable model can have one mode certified as converged and nothing can tell. A BAR, not
# a gate: it annotates, and must never re-cut direction, size, or drop a sample.
INSTABILITY_TOL_PCT = 25.0


def iv_instability(current_iv, prior_iv, tol_pct=INSTABILITY_TOL_PCT):
    """(None | {prior_iv, current_iv, delta_pct, unstable}) — pure. No I/O, no judgment.

    None when either side is missing or non-positive: a name analysed for the first time has
    no predecessor, and absence is not evidence of a move. Guards the 0.0 case explicitly
    rather than relying on truthiness, because 0.0 is a value, not an absence.
    """
    try:
        cur, pri = float(current_iv), float(prior_iv)
    except (TypeError, ValueError):
        return None
    if cur <= 0 or pri <= 0:
        return None
    delta = round((cur / pri - 1) * 100, 1)
    return {"prior_iv": pri, "current_iv": cur, "delta_pct": delta,
            "unstable": abs(delta) > tol_pct}


def _prior_verdict(ticker, ledgers):
    """The newest ledger row for `ticker`, or None. NEVER raises.

    A name can sit in BOTH the book ledger and the on-demand ledger, so the predecessor is the
    newest row by `date`, not the first ledger that mentions it — taking the book row when a
    one-shot ran last week would compare against a stale level and report a move that did not
    happen. Ties fall to the later ledger, then the later line, so the result is deterministic.

    Tolerates a malformed line, a torn last line (a half-written ledger is normal, and the
    control tower's cloud reader was required to tolerate the same), a missing file, and a
    permission error. This is context for an annotation; it must never be able to fail a live
    analysis.
    """
    if not ticker:
        return None
    best, best_key = None, None
    for li, led in enumerate(ledgers or ()):
        try:
            with open(led, encoding="utf-8") as fh:
                for ri, line in enumerate(fh):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(row, dict) and row.get("ticker") == ticker:
                        key = (str(row.get("date") or ""), li, ri)
                        if best_key is None or key > best_key:
                            best, best_key = row, key
        except Exception:
            continue
    return best


def _kill_tree(proc):
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_research(t):
    """deep_research.py in the research venv — self-caching (research_cache_days), infra-error
    aware (exit 3), bounded here exactly like run_rs2.run_research. Frees the research model's
    VRAM before the analyst loads."""
    rv = Path(CONFIG["research_venv_python"])
    if not rv.exists():
        print("[depth] WARN research-venv missing — proceeding without fresh research", flush=True)
        return
    print(f"[depth] research {t} (cache-aware, bound {RESEARCH_TIMEOUT}s)", flush=True)
    # UNLOAD THE ANALYST FIRST (bug found live on ABNB, 2026-08-21 15:49). The previous
    # ticker's analyst model (~22.2GB at ctx 81920) stays resident between children, and the
    # post-research barrier then demands >=20GB free for the analyst re-load - impossible with
    # the analyst itself still holding the card. Research (9.3GB) and analyst cannot coexist on
    # 24GB, so the ticker must START by clearing the card. Best-effort: if the card is already
    # clear this is a no-op poll.
    ops.wait_unloaded(
        CONFIG["ollama_endpoint"], MODEL,
        need_free_mb=11000,          # enough for the research model + ctx, not the full 20GB
        timeout_s=int(CONFIG.get("vram_unload_timeout_s", 180)))
    # COMPANY NAME IS MANDATORY CONTEXT, not garnish (2026-08-29). This spawn passed only the
    # ticker, so every depth brief searched as a bare "{T} stock" — deep_research printed its
    # "WARNING no company name" on every single run — and CART's moat section came back about
    # the industrial-carts market instead of Instacart. run_rs2 always passed the name; depth
    # didn't. Resolution is zero-network (screener stocks.csv, cached in rs2_data).
    name = rs2_data.resolve_name(t)
    if not name:
        print(f"[depth] WARN no company name for {t} — research will search the bare ticker",
              flush=True)
    brief_asof, brief_age_days = _research_brief_provenance(t)
    max_age = float(CONFIG.get("research_max_age_days", 14))
    force = bool(brief_age_days is not None and brief_age_days > max_age)
    if force:
        print(f"[depth] research brief for {t} is {brief_age_days:.1f}d old (> {max_age:.0f}d) — forcing refresh",
              flush=True)
    cmd = [str(rv), str(HERE / "deep_research.py"), t]
    if force:
        cmd.append("--force")
    if name:
        cmd.append(name)
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    timed_out = False
    try:
        out, err = proc.communicate(timeout=RESEARCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out, err = proc.communicate()
    for line in (out or "").splitlines():
        if "[deep_research]" in line:
            print("   " + line, flush=True)
    ok, detail = ops.wait_unloaded(
        CONFIG["ollama_endpoint"], CONFIG.get("research_model"),
        need_free_mb=int(CONFIG.get("vram_free_required_mb", 20000)),
        timeout_s=int(CONFIG.get("vram_unload_timeout_s", 180)))
    if not ok:
        print(f"[depth] ::VRAM:: research model not released — {detail}", flush=True)
        sys.exit(7)
    if timed_out:
        print(f"[depth] ::HARD FAIL:: research exceeded {RESEARCH_TIMEOUT}s — killed tree.",
              flush=True)
        sys.exit(3)
    if proc.returncode == 3:
        print(f"[depth] ::HARD FAIL:: research infra error — not analysing on a poisoned brief.",
              flush=True)
        sys.exit(3)


def run_consensus(t, samples=None, price_quote=None):
    """consensus_valuation.py as a subprocess (stdout inherited, so progress is visible live).
    Returns the newest consensus.json for the ticker, written by this invocation.
    Defaults to adaptive 2-escalate consensus (early-stops at n=2 if spread <= 15%, else n=3)."""
    before = {p.name for p in (HERE / "ab_reports" / "consensus").glob(f"{t}_*")}
    cmd = [sys.executable, str(HERE / "tools" / "audit_202608" / "consensus_valuation.py"),
           t, "--model", MODEL, "--ctx", str(CTX), "--think", "high"]
    if price_quote and price_quote.get("price") is not None:
        cmd.extend(["--price", str(price_quote["price"])])
        if price_quote.get("asof"):
            cmd.extend(["--price-asof", str(price_quote["asof"])])
    if samples is not None:
        cmd.extend(["--samples", str(samples)])
    if TOOLS:
        cmd.append("--tools")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"[depth] consensus subprocess exit {r.returncode}", flush=True)
        sys.exit(5)
    new = [p for p in (HERE / "ab_reports" / "consensus").glob(f"{t}_*")
           if p.name not in before and (p / "consensus.json").exists()]
    if not new:
        print("[depth] consensus wrote no output dir", flush=True)
        sys.exit(5)
    d = max(new, key=lambda p: p.name)
    return d, json.loads((d / "consensus.json").read_text(encoding="utf-8"))


# ---- fiduciary contract gate (final output stage, added 2026-09-20) --------------------------
# The consensus scorecard publishes its contract fields with a historical `median_` prefix even
# though they now carry the MEDOID sample's values (see select_medoid_scorecard). The validator
# speaks the unprefixed Section 12 names. Mapping them explicitly matters: passing the scorecard
# through verbatim meant `bull_iv`/`bear_iv`/`kelly_fraction_pct` all arrived as None, so the
# validator saw a base case with no scenarios and returned PASS on every contract it was given.
CONTRACT_FIELD_MAP = (
    ("median_bull_iv", "bull_iv"),
    ("median_bear_iv", "bear_iv"),
    ("median_kelly_fraction_pct", "kelly_fraction_pct"),
    ("median_quality_moat", "business_quality_moat"),
    ("median_conviction_score", "conviction_score"),
)
CONTRACT_PASSTHROUGH = ("reentry_tranches", "asymmetric_payoff_skew",
                        "base_probability", "bull_probability", "bear_probability")


# contract_base() was defined HERE as well until 2026-09-20. It now lives in fiduciary_gate.py
# and is imported at the top of this module, so the pipeline, the validator and the auditor share
# ONE definition. `depth_sanity` held a third copy carrying an extra `or lo` fallback that this
# module lacked, which meant the three could disagree about which IV was the base - they diverged
# on real data whenever `base_iv` existed and differed from `median_iv`. The import rebinds the
# name in this namespace, so existing readers of `depth_pipeline.contract_base` are unaffected.


def build_contract(scorecard):
    """Section 12 contract as `fiduciary_gate.validate_fiduciary_contract` expects to receive it."""
    sc = scorecard or {}
    card = {"base_iv": contract_base(sc)}
    for src, dst in CONTRACT_FIELD_MAP:
        val = sc.get(src)
        card[dst] = val if val is not None else sc.get(dst)
    for key in CONTRACT_PASSTHROUGH:
        if sc.get(key) is not None:
            card[key] = sc[key]
    return card


def fiduciary_verdict_gate(v, price):
    """FINAL OUTPUT STAGE — enforce the underwriting contract before capital can be sized.

    Why here and not only in the auditor: `depth_sanity.py` runs AFTER the verdict has been
    written, ledgered and notified, and it is read-only. Measured on GEV 2026-09-20 — the verdict
    went out carrying `kelly_fraction_pct: 8.98` beside `mos_vs_median_pct: -1.7`, and the only
    component that noticed was the audit, one step too late to withhold it.

    FAILS CLOSED. A contract that cannot support a position is sized to ZERO and stamped FAIL.
    It is never quietly re-sized: per the operator rule every verdict is an underwriting proposal
    for real capital, and a silent haircut reads as approval.
    """
    sc = v.get("scorecard") or {}
    base = contract_base(sc)
    if not price or base is None:
        v.update({"fiduciary_verdict": "NOT_APPLICABLE", "fiduciary_violations": [],
                  "fiduciary_amendments": []})
        return v

    card = build_contract(sc)
    ok, san, issues = validate_fiduciary_contract(card, price)

    # A Kelly CLAMP is returned as a non-fatal repair, but it is fatal to the POSITION: it fires
    # precisely when the contract's own edge test is non-positive (expected return <= 0, or
    # Base IV <= Price). That is the condition under which no capital may be committed.
    clamped = [i for i in issues if "Clamped Kelly" in i]
    violations = list(issues) if not ok else clamped

    v["fiduciary_amendments"] = [i for i in issues if i not in violations]
    v["fiduciary_violations"] = violations

    if violations:
        v["fiduciary_verdict"] = "FAIL"
        # Record what the contract claimed before overriding it, so the override is auditable
        # and the original is not lost.
        v["fiduciary_overridden_kelly_pct"] = card.get("kelly_fraction_pct")
        v["kelly_fraction_pct"] = 0.0
        v["size_hint"] = "zero"
        v.setdefault("flags", []).append("FIDUCIARY_CONTRACT_FAIL")
        v["flags"] = sorted(set(v["flags"]))
        note = (f"fiduciary contract FAIL — position sized to zero "
                f"(base ${base:,.2f} vs price ${price:,.2f}, contract Kelly "
                f"{card.get('kelly_fraction_pct')}%)")
        v["reason"] = f"{v['reason']}; {note}" if v.get("reason") else note
        return v

    v["fiduciary_verdict"] = "PASS"
    # Adopt the sanitized values, so what is published is what actually passed validation.
    if san.get("kelly_fraction_pct") is not None:
        v["kelly_fraction_pct"] = san["kelly_fraction_pct"]
    if san.get("asymmetric_payoff_skew") is not None:
        v["asymmetric_payoff_skew"] = san["asymmetric_payoff_skew"]
    return v


def band_verdict(doc):
    """Direction-of-band verdict per the accepted spec, enriched with the Section 12 Underwriting Contract.
    Judges only USABLE, COMPLETE samples.

    `flags` carries forward the threshold trips that used to DELETE a sample and, since the
    2026-08-24 guard redesign, only annotate it. They are published so a wide band can be
    explained rather than merely displayed; they gate nothing.
    """
    price = doc.get("price")
    good = [r for r in doc.get("runs", []) if r.get("iv") and r.get("plausible")
            and not r.get("truncated")]
    ivs = sorted(r["iv"] for r in good)
    v = {"ticker": doc["ticker"], "price": price, "date": datetime.now().strftime("%Y-%m-%d"),
         "model": doc.get("model"), "samples_run": doc.get("samples_run") or len(doc.get("runs", [])),
         "n_basis": len(ivs), "iv_band_low": ivs[0] if ivs else None,
         "iv_band_high": ivs[-1] if ivs else None,
         "median_iv": doc.get("median_iv"),
         "spread_pct": doc.get("spread_pct"),
         "flags": sorted({f for r in good for f in (r.get("flags") or [])}),
         "pack_revision": doc.get("pack_revision", 1),
         "scheme": "band_direction_v1"}

    # Attach Institutional Scorecard Underwriting Contract (Charter v3.1 / Section 12)
    scorecard = doc.get("scorecard") or {}
    v.update({
        "scorecard": scorecard,
        "conviction_score": scorecard.get("median_conviction_score"),
        "business_quality_moat": scorecard.get("median_quality_moat"),
        "kelly_fraction_pct": scorecard.get("median_kelly_fraction_pct"),
        "asymmetric_payoff_skew": scorecard.get("asymmetric_payoff_skew"),
        "bull_iv": scorecard.get("median_bull_iv"),
        "bear_iv": scorecard.get("median_bear_iv"),
        "reentry_tranches": scorecard.get("reentry_tranches"),
        "thesis_invalidation_triggers": scorecard.get("thesis_invalidation_triggers") or [],
        "converged": doc.get("converged"),
        "early_stop": doc.get("early_stop"),
        "mode": doc.get("mode"),
    })

    if not ivs or not price:
        v.update({"direction": "NOT_USABLE", "size_hint": None,
                  # Present-and-None rather than absent: a consumer must be able to tell
                  # "no prior to compare" from "this key was never written".
                  "instability": None,
                  "fiduciary_verdict": "NOT_APPLICABLE",
                  "fiduciary_violations": [], "fiduciary_amendments": [],
                  "reason": "zero plausible complete samples — malfunction path, not a verdict"})
        return v

    tol = float(doc.get("tolerance_pct") or 25.0)
    spread = v["spread_pct"] if v["spread_pct"] is not None else 0.0
    reason_notes = []

    if price > ivs[-1]:
        d = "overvalued"        # every plausible draw values it below the price
        # Asymmetric Compounder Moat Override (Charter v3.1 / Anti-Vacuum Principle):
        # A wide-moat compounder (moat >= 4.0, skew >= 2.0x, positive Kelly) trading near Base IV (<= 10%)
        # represents durable compounding with massive asymmetric upside; do not label cigar-butt "overvalued".
        moat = scorecard.get("median_quality_moat") or scorecard.get("business_quality_moat")
        skew = scorecard.get("asymmetric_payoff_skew")
        kelly = scorecard.get("median_kelly_fraction_pct") or scorecard.get("kelly_fraction_pct")
        if moat and float(moat) >= 4.0 and skew and float(skew) >= 2.0 and kelly and float(kelly) > 0:
            if price <= 1.10 * ivs[-1]:
                d = "hold"
                reason_notes.append(f"fairly valued with asymmetric upside (moat {moat}/5, skew {skew}x) — hold/starter tranche")
    elif price < ivs[0]:
        d = "undervalued"       # every plausible draw values it above the price
    else:
        d = "hold"              # price inside the model's honest uncertainty — no edge

    # STRICT NON-CONVERGENCE GATE:
    # If the models fundamentally disagree beyond tolerance (spread > 25%), capital cannot be committed.
    if spread > tol:
        if d == "undervalued":
            d = "hold"
            reason_notes.append(f"high dispersion (spread {spread:.1f}% > {tol:.0f}%) — model disagreement prohibits capital allocation")
        v.setdefault("flags", []).append("HIGH_DISPERSION_QUARANTINE")
        v["flags"] = sorted(set(v["flags"]))

    size = next(lbl for cap, lbl in SIZE_BUCKETS if spread <= cap)

    # LOST-SAMPLE SIZING PENALTY:
    # If a sample was dropped (e.g. truncation/crash), the band is artificially narrowed.
    # Cap size to 'half'; 'full' size strictly requires complete 3/3 samples (or an early stop at n=2).
    # `samples_run` is only what got RECORDED, so a sample that raised before recording made this
    # count 2 and the rule could never fire - the loss it exists to punish was the one thing it
    # could not see. `samples_attempted` is the honest denominator; the fallback keeps older
    # snapshots behaving exactly as before.
    early_stop = doc.get("early_stop", False)
    samples_attempted = (doc.get("samples_attempted")
                         or (2 if early_stop
                             else (doc.get("samples_run") or len(doc.get("runs", [])))))
    if samples_attempted == 3 and len(ivs) == 2 and not early_stop:
        if size == "full":
            size = "half"
            reason_notes.append("sample lost — size capped at half")

    if len(ivs) == 1:
        size = "quarter"        # a one-sample basis is directional at best; never size it up
        reason_notes.append("single plausible sample — direction weak, size capped")

    if reason_notes:
        v["reason"] = "; ".join(reason_notes)

    cbase = contract_base(scorecard)

    # MODE INSTABILITY (2026-09-20) — ANNOTATION ONLY. Direction, size and Kelly below are
    # computed from THIS run alone and this detector must not move any of them. Both sides go
    # through contract_base so "the base IV" has one definition on both sides of the compare.
    prior = _prior_verdict(doc.get("ticker"), (LEDGER, OD_LEDGER))
    # A ledger row is a VERDICT, not a scorecard: its contract base is nested under `scorecard`,
    # while its top-level `median_iv` is the cross-sample DISPERSION statistic. Reading the top
    # level compares this run's BASE against the prior's MEDIAN - two different quantities - and
    # GEV's real row (top-level base_iv absent, median 517.745, scorecard base 549.77) reported a
    # 0.0% move on a run that had in fact moved 44.6%. Rows preceding the scorecard fall back to
    # the median, which is the documented legacy rule inside contract_base.
    prior_card = (prior or {}).get("scorecard") or prior
    v["instability"] = iv_instability(cbase, contract_base(prior_card))
    if v["instability"] and v["instability"]["unstable"]:
        v.setdefault("flags", []).append("MODE_INSTABILITY")
        v["flags"] = sorted(set(v["flags"]))
        ins = v["instability"]
        note = (f"mode instability: base IV moved {ins['delta_pct']:+.1f}% since the prior "
                f"verdict (${ins['prior_iv']:,.2f} -> ${ins['current_iv']:,.2f}) — within-run "
                f"spread cannot see this, so convergence here is not stability")
        v["reason"] = f"{v['reason']}; {note}" if v.get("reason") else note

    # LOW-EFFORT RESCUE (2026-09-20) — ANNOTATION ONLY. The harness forces a memorandum turn at
    # `think: "low"` when a run ends on a tool-call stub, so a rescued sample was reasoned at a
    # different effort level from its siblings. That status was persisted per sample but never
    # reached runs[]/consensus.json, so a band could mix the two and still read as clean - a
    # false-confidence defect in the verdict itself. Only samples actually USED matter: a rescued
    # sample that was implausible or truncated never reached the band, and its rescue status is
    # irrelevant to the published number. The note used to claim "or an exhausted budget" as well;
    # the predicate never checked that key, and the budget path does not lower the effort anyway.
    rescued = [r.get("sample") for r in good
               if r.get("stub_rejected") or r.get("forced_report")]
    if rescued:
        v.setdefault("flags", []).append("LOW_EFFORT_RESCUE")
        v["flags"] = sorted(set(v["flags"]))
        note = (f"low-effort rescue: sample(s) {', '.join(str(s) for s in rescued)} ended on a "
                f"tool-call stub and were written at REDUCED reasoning effort (`think: \"low\"`) "
                f"— not comparable to a normal sample")
        v["reason"] = f"{v['reason']}; {note}" if v.get("reason") else note

    # FORCED REPORT (2026-09-21) — ANNOTATION ONLY, and deliberately a SEPARATE flag from
    # LOW_EFFORT_RESCUE. When both tool budgets are reached the harness forces the memorandum at
    # the SAME `think` level, and `analyst_tools.py:513` tags that turn `budget_exhausted`. So the
    # sample is NOT lower-effort - but it was cut short rather than concluding, which is a
    # provenance a reader has to be able to see. Reading only `forced_report` left this path
    # invisible, so a forced report published exactly like a sample that had finished naturally.
    forced = [r.get("sample") for r in good if r.get("budget_exhausted")]
    if forced:
        v.setdefault("flags", []).append("FORCED_REPORT")
        v["flags"] = sorted(set(v["flags"]))
        note = (f"forced report: sample(s) {', '.join(str(s) for s in forced)} reached the "
                f"tool-budget ceiling and had the memorandum forced at the configured reasoning "
                f"effort — cut short rather than concluding")
        v["reason"] = f"{v['reason']}; {note}" if v.get("reason") else note

    v.update({"direction": d, "size_hint": size,
              # Dispersion-anchor MoS: retained unchanged so existing readers keep working.
              "mos_vs_median_pct": round((v["median_iv"] / price - 1) * 100, 1)
              if v["median_iv"] else None,
              # Fiduciary MoS: measured against the CONTRACT base, the same IV that owns Kelly.
              "mos_vs_base_pct": round((cbase / price - 1) * 100, 1) if cbase else None})
    return fiduciary_verdict_gate(v, price)


def _run_source():
    """Resolution order (P1.2): --ondemand always wins (it is an explicit, unambiguous request);
    then the env marker a spawner sets (RS2_RUN_SOURCE=orchestrator|cloud); then --production for
    an operator-invoked production run; anything else is an unmarked manual run and is routed to
    the test ledger, never the production one."""
    if "--ondemand" in sys.argv:
        return "ondemand"
    env_src = os.environ.get("RS2_RUN_SOURCE")
    if env_src in ("orchestrator", "cloud"):
        return env_src
    if "--production" in sys.argv:
        return "manual_production"
    return "manual"


def _research_brief_provenance(t):
    """(research_brief_asof ISO string, age_days) from research/{T}.md's mtime, or (None, None)
    if the brief does not exist — never a fabricated freshness."""
    path = Path(CONFIG["out_research_dir"]) / f"{t.upper()}.md"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None, None
    asof = datetime.fromtimestamp(mtime).isoformat()
    age_days = round((time.time() - mtime) / 86400, 2)
    return asof, age_days


def _pipeline_commit():
    """`git rev-parse --short HEAD`, best-effort. None on any failure — never fabricated."""
    try:
        r = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            sha = r.stdout.strip()
            return sha or None
    except Exception:
        pass
    return None


def stamp_and_route(v, t, run_source, quote=None):
    """Attach the P1.2/P1.5 provenance fields to verdict dict `v` (in place) and pick which ledger it
    belongs in. Returns (ledger_path, notice_or_None) — `notice` is the loud manual-run warning,
    non-None only when `run_source` resolved to "manual" (unmarked: no --ondemand, no
    --production, no recognised RS2_RUN_SOURCE).

    Split out of `main()` so routing/stamping is testable against a synthetic verdict without
    spawning the research/consensus subprocesses (tests/test_depth_pipeline_routing.py).
    """
    v["run_source"] = run_source
    v["arm"] = "local"
    v["pack_source"] = "fresh"
    brief_asof, brief_age_days = _research_brief_provenance(t)
    v["research_brief_asof"] = brief_asof
    v["research_brief_age_days"] = brief_age_days
    # Live price at verdict time is P1.5 — from price_now.quote(t).
    if quote and quote.get("price") is not None:
        v["price"] = quote["price"]
        v["price_asof"] = quote.get("asof")
        v["price_source"] = quote.get("source")
        v.pop("price_asof_reason", None)
    else:
        v.setdefault("price_asof", None)
        v.setdefault("price_source", None)
        v.setdefault("price_asof_reason", "live price capture is P1.5 — quote unavailable")
    v["gate_version"] = GATE_VERSION
    v["pipeline_commit"] = _pipeline_commit()

    if run_source == "ondemand":
        return OD_LEDGER, None
    if run_source in ("orchestrator", "cloud", "manual_production"):
        return LEDGER, None
    notice = (f"[depth] ::NOTICE:: manual run (no --ondemand, no --production, no "
              f"RS2_RUN_SOURCE) — {t} written to {TEST_LEDGER.name}, NOT the production ledger")
    return TEST_LEDGER, notice


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "").upper()
    if not t:
        print("usage: depth_pipeline.py TICKER [--no-research] [--ondemand] [--production] "
              "[--samples N]")
        sys.exit(2)

    # LIVE PRICE AT VERDICT TIME (P1.5): obtain the quote before research; hard-fail on None.
    quote = price_now.quote(t)
    if not quote or quote.get("price") is None:
        print("::HARD FAIL:: live price unavailable", flush=True)
        sys.exit(8)

    # ON-DEMAND (2026-08-30): identical analysis, DIFFERENT ledger. A row in the main ledger
    # is a membership event — live_book() unions ledger tickers forever, rebuild_overlay
    # publishes the newest row unfiltered to the site, and rotation re-queues it every 90d.
    # An operator-requested one-shot must stay out of all of that, so it lands in
    # OD_LEDGER, which nothing downstream reads (see depth_ondemand.py).
    ondemand = "--ondemand" in sys.argv
    samples = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else None
    run_source = _run_source()
    t0 = time.time()
    if "--no-research" not in sys.argv:
        run_research(t)
    d, doc = run_consensus(t, samples=samples, price_quote=quote)
    v = band_verdict(doc)
    v["consensus_dir"] = d.name
    if ondemand:
        v["ondemand"] = True

    # ---- provenance on every row + ledger routing (P1.2/P1.5) -----------------------------------
    # A bare `python depth_pipeline.py TICKER` (no --ondemand/--production, no RS2_RUN_SOURCE)
    # resolves to "manual" and is routed to the test ledger, loudly — exactly how the six n=1
    # rows tools/ledger_quarantine.py moved got into the production ledger in the first place.
    ledger, notice = stamp_and_route(v, t, run_source, quote=quote)
    if notice:
        print(notice, flush=True)
        try:
            ops.notify_telegram(notice)
        except Exception:
            pass

    (d / "verdict_depth.json").write_text(json.dumps(v, indent=2), encoding="utf-8")

    ledger.parent.mkdir(exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(v) + "\n")
    print(f"\n[depth] {t}: {v['direction'].upper()}"
          + (f" | band ${v['iv_band_low']}-${v['iv_band_high']} vs price ${v['price']}"
             if v.get("iv_band_low") else "")
          + (f" | size {v['size_hint']}" if v.get("size_hint") else "")
          + (f" | conviction {v['conviction_score']}/15" if v.get("conviction_score") is not None else "")
          + (f" | Kelly {v['kelly_fraction_pct']}%" if v.get("kelly_fraction_pct") is not None else "")
          + f" | {time.time()-t0:.0f}s -> {d / 'verdict_depth.json'}", flush=True)
    if ondemand:
        # The verdict delivery for BOTH on-demand paths (sweep boundary and idle runner).
        try:
            ops.notify_telegram(
                f"[RS2 on-demand] {t}: {v['direction'].upper()}"
                + (f" | band ${v['iv_band_low']}-${v['iv_band_high']} vs ${v['price']}"
                   if v.get("iv_band_low") is not None else "")
                + (f" | size {v['size_hint']}" if v.get("size_hint") else "")
                + (f" | conviction {v.get('conviction_score')}/15" if v.get("conviction_score") is not None else "")
                + (f" | {v.get('reason')}" if v.get("reason") else "")
                + f" | {time.time()-t0:.0f}s")
        except Exception:
            pass
    audit_verdict(t, ledger)


def audit_verdict(t, ledger=LEDGER):
    """Run depth_sanity on the verdict just written, IN THIS PROCESS.

    Until now the only caller of depth_sanity was an interactive watcher script that lived
    outside the repo and died with its session - while the sweep itself runs detached and
    outlives any session. So the one component built to catch silent sample loss was itself
    silent exactly when nobody was watching. Auditing belongs to the pipeline, not to whoever
    happens to be looking.

    Never fatal: a defect in the auditor must not fail a ticker whose analysis is sound (the same
    rule the old pipeline learned when an oversized audit context killed a good MU run). A FAIL
    is recorded and alerted; the verdict still stands and the operator decides.

    `ledger`: the ledger this verdict was actually appended to (P1.2 routes on `run_source`, so
    it is not always the production LEDGER). Every append path is audited against ITS OWN ledger
    (P1.8) — without the override sanity would audit the ticker's stale production-ledger row, or
    report "no verdict on file", for anything written to OD_LEDGER or TEST_LEDGER.
    """
    try:
        r = subprocess.run(
            [sys.executable, str(HERE / "tools" / "audit_202608" / "depth_sanity.py"), t]
            + (["--ledger", str(ledger)] if ledger != LEDGER else []),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        out = (r.stdout or "").strip()
        print(out, flush=True)
        line = {2: "FAIL", 1: "WARN"}.get(r.returncode, "CLEAN")
        with (HERE / "cache" / "depth_audit.log").open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {t} {datetime.now():%Y-%m-%d %H:%M:%S} [{line}] ===\n{out}\n")
        if r.returncode == 2:
            try:
                ops.notify_telegram(f"[RS2 depth] {t} verdict FAILED sanity audit:\n"
                                    f"{out[:600]}")
            except Exception:
                pass
    except Exception as e:
        print(f"[depth] audit did not run (non-fatal): {str(e)[:120]}", flush=True)


if __name__ == "__main__":
    main()

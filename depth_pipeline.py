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
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import ops                  # noqa: E402
import rs2_data             # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
LEDGER = HERE / "cache" / "depth_ledger.jsonl"

# ---- spec constants (operator-accepted 2026-08-21) ------------------------------------------
SAMPLES = int(CONFIG.get("depth_samples", 3))       # 3 flat — cost accepted
MODEL = CONFIG.get("depth_model", "rs2-analyst-deep")
CTX = int(CONFIG.get("depth_ctx", 81920))           # VRAM-verified 22.2GB full GPU
TOOLS = bool(CONFIG.get("depth_tools", True))       # search-during-reasoning, approved
RESEARCH_TIMEOUT = int(CONFIG.get("research_timeout_s", 900))

# Position-size hint from spread — HEURISTIC v1, not calibrated. Buckets chosen so that the
# measured GOOG scatter (24-36%) lands in "half"/"quarter" rather than full size. The operator
# tunes these when real sweep data exists; they are a sizing suggestion, never a gate.
SIZE_BUCKETS = ((15.0, "full"), (30.0, "half"), (10**9, "quarter"))


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
    proc = subprocess.Popen([str(rv), str(HERE / "deep_research.py"), t],
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


def run_consensus(t):
    """consensus_valuation.py as a subprocess (stdout inherited, so progress is visible live).
    Returns the newest consensus.json for the ticker, written by this invocation."""
    before = {p.name for p in (HERE / "ab_reports" / "consensus").glob(f"{t}_*")}
    cmd = [sys.executable, str(HERE / "tools" / "audit_202608" / "consensus_valuation.py"),
           t, "--samples", str(SAMPLES), "--model", MODEL, "--ctx", str(CTX)]
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


def band_verdict(doc):
    """Direction-of-band verdict per the accepted spec. Judges only USABLE, COMPLETE samples.

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
    if not ivs or not price:
        v.update({"direction": "NOT_USABLE", "size_hint": None,
                  "reason": "zero plausible complete samples — malfunction path, not a verdict"})
        return v
    if price > ivs[-1]:
        d = "overvalued"        # every plausible draw values it below the price
    elif price < ivs[0]:
        d = "undervalued"       # every plausible draw values it above the price
    else:
        d = "hold"              # price inside the model's honest uncertainty — no edge
    spread = v["spread_pct"] if v["spread_pct"] is not None else 0.0
    size = next(lbl for cap, lbl in SIZE_BUCKETS if spread <= cap)
    if len(ivs) == 1:
        size = "quarter"        # a one-sample basis is directional at best; never size it up
        v["reason"] = "single plausible sample — direction weak, size capped"
    v.update({"direction": d, "size_hint": size,
              "mos_vs_median_pct": round((v["median_iv"] / price - 1) * 100, 1)
              if v["median_iv"] else None})
    return v


def main():
    t = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
    if not t:
        print("usage: depth_pipeline.py TICKER [--no-research]")
        sys.exit(2)
    t0 = time.time()
    if "--no-research" not in sys.argv:
        run_research(t)
    d, doc = run_consensus(t)
    v = band_verdict(doc)
    v["consensus_dir"] = d.name
    (d / "verdict_depth.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
    LEDGER.parent.mkdir(exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(v) + "\n")
    print(f"\n[depth] {t}: {v['direction'].upper()}"
          + (f" | band ${v['iv_band_low']}-${v['iv_band_high']} vs price ${v['price']}"
             if v.get("iv_band_low") else "")
          + (f" | size {v['size_hint']}" if v.get("size_hint") else "")
          + f" | {time.time()-t0:.0f}s -> {d / 'verdict_depth.json'}", flush=True)
    audit_verdict(t)


def audit_verdict(t):
    """Run depth_sanity on the verdict just written, IN THIS PROCESS.

    Until now the only caller of depth_sanity was an interactive watcher script that lived
    outside the repo and died with its session - while the sweep itself runs detached and
    outlives any session. So the one component built to catch silent sample loss was itself
    silent exactly when nobody was watching. Auditing belongs to the pipeline, not to whoever
    happens to be looking.

    Never fatal: a defect in the auditor must not fail a ticker whose analysis is sound (the same
    rule the old pipeline learned when an oversized audit context killed a good MU run). A FAIL
    is recorded and alerted; the verdict still stands and the operator decides.
    """
    try:
        r = subprocess.run(
            [sys.executable, str(HERE / "tools" / "audit_202608" / "depth_sanity.py"), t],
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

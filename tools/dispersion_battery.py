#!/usr/bin/env python3
"""tools/dispersion_battery.py — P4.0b: the frozen-evidence dispersion battery.

PHASE_4_ANALYST.md P4.0b / PHASE_4_AMENDMENTS.md A2, B5, B6. Measures where the analyst's
run-to-run IV dispersion comes from by holding the DATA fixed across every sample of a name's
run — one frozen pack, one shared evidence store — so a spread across samples reflects sampling,
not a moving pack or a re-fetched web.

For each requested name this script:
  1. builds (or reuses, if already on disk) ONE frozen pack — capability_test.build_pack() +
     TASK + RESEARCH_ADDENDUM, exactly what consensus_valuation.py's own --tools path would
     assemble — under `<out>/<NAME>/_pack.md`;
  2. gives it ONE evidence-store directory, `<out>/<NAME>/_evidence/`, shared by every sample;
  3. runs tools/audit_202608/consensus_valuation.py ONCE with `--pack-file`, `--evidence-store`,
     `--no-early-stop`, `--samples`, `--tools` and `--out-dir <out>/<NAME>/arm_<ARM>/`, so every
     sample draws on the byte-identical pack and the same shared query/URL cache.

It NEVER calls depth_pipeline.py, orchestrate_depth.py, deep_research.py or sync_state.py, never
runs the model directly (only the consensus_valuation.py subprocess does, and only outside
--dry-run), never writes a ledger, and never publishes. `--out-dir` on every consensus invocation
keeps every run inside THIS script's own `--out` root — never `ab_reports/consensus`, never
`cache/`.

Arms (PHASE_4_ANALYST.md P4.0b): A = current settings (Modelfile's own temperature, no
override); B = `--temperature 0.3`; C = anchor CoE supplied + desk mandatory, which depends on
P4.6 (rate engine wired) — not built in this phase. Selecting `--arm C` refuses loudly rather
than silently running arm A under arm C's label (a STOP condition, not a threshold tweak —
rs2-local/AGENTS.md §0).

RESUMABLE, at the granularity consensus_valuation.py's own architecture allows: it commits to a
brand-new timestamped run directory on every invocation and writes consensus.json only once a
run completes (nothing mid-run is ever partially written to that file), so THIS script's resume
check is "does a complete consensus.json for this name+arm, with samples_run >= the requested
count, already exist under its arm directory?" — if so, that name is skipped. A crashed,
half-finished consensus_valuation.py invocation leaves sample*.md files but no consensus.json,
so it is correctly NOT treated as complete and is retried from sample 1 (consensus_valuation.py
itself has no mid-run checkpoint to resume from; adding one is out of this phase's scope).

Usage:
  python tools/dispersion_battery.py --names FIX,AMD,DXC,GEV --samples 3 --arm A \\
      --out tools/audit_202608/ab_reports/dispersion_20260924
  python tools/dispersion_battery.py --names GEV --samples 1 --arm A --dry-run
"""
import argparse
import json
import statistics as st
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]           # repo root (rs2-local)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import rs2_data                     # noqa: E402
import capability_test as cap       # noqa: E402

CONSENSUS_SCRIPT = HERE / "tools" / "audit_202608" / "consensus_valuation.py"
DEFAULT_MODEL = rs2_data.CONFIG.get("depth_model", "rs2-analyst-deep-mtp5")
DEFAULT_CTX = int(rs2_data.CONFIG.get("depth_ctx", 81920))

# Arm presets. None means "pass no --temperature override" — the consensus subprocess then runs
# at the Modelfile's own PARAMETER temperature 0.6 (RS2-Analyst-Deep-MTP5.Modelfile).
ARM_TEMPERATURE = {"A": None, "B": 0.3}
ARM_C_BLOCKED = ("arm C (anchor CoE supplied + desk mandatory) needs P4.6, which P4.0b does not "
                 "build. Run arm A or B, or land P4.6 first.")


def _quote(s):
    """Wrap an argument containing whitespace in quotes, for a copy-pasteable printed command
    line only — the real subprocess call below passes `cmd` as a list and needs no quoting."""
    s = str(s)
    return f'"{s}"' if " " in s else s


def build_frozen_pack(name, pack_path):
    """Write capability_test.build_pack(name) + TASK + RESEARCH_ADDENDUM to `pack_path`, unless
    a pack is already there (reused verbatim — the battery is resumable at the name level too:
    a re-run must not rebuild a pack a prior attempt already froze). Returns (pack_text, reused).

    NO OLLAMA CALL: build_pack() reads only static data files (screener data, enrich/,
    financials/) — nothing in its call graph touches urllib/requests/ollama. Safe under
    --dry-run and under cache/DEPTH_PAUSED, and safe to call for every name even when this
    script will not go on to run any sample.
    """
    if pack_path.exists():
        return pack_path.read_text(encoding="utf-8"), True
    pack_text = cap.build_pack(name)
    pack = pack_text + "\n\n---\n\n" + cap.TASK + cap.RESEARCH_ADDENDUM
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(pack, encoding="utf-8")
    return pack, False


def consensus_command(name, samples, arm, temperature, pack_path, evidence_dir, consensus_out,
                      model=DEFAULT_MODEL, ctx=DEFAULT_CTX):
    """The exact consensus_valuation.py command line for one name's battery run."""
    cmd = [sys.executable, str(CONSENSUS_SCRIPT), name,
           "--model", model, "--ctx", str(ctx), "--think", "high", "--tools",
           "--samples", str(samples), "--no-early-stop",
           "--pack-file", str(pack_path),
           "--evidence-store", str(evidence_dir),
           "--out-dir", str(consensus_out)]
    eff_temp = temperature if temperature is not None else ARM_TEMPERATURE.get(arm)
    if eff_temp is not None:
        cmd += ["--temperature", str(eff_temp)]
    return cmd


def _existing_complete_run(consensus_out, name, samples):
    """The newest consensus.json under `consensus_out` for `name` whose samples_run >= `samples`,
    or None. This IS the battery's resume granularity — see the module docstring."""
    if not consensus_out.exists():
        return None
    best = None
    for run_dir in sorted(consensus_out.glob(f"{name}_*")):
        cj = run_dir / "consensus.json"
        if not cj.exists():
            continue
        try:
            doc = json.loads(cj.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (doc.get("samples_run") or 0) >= samples:
            if best is None or doc.get("generated_at", "") > best.get("generated_at", ""):
                best = doc
    return best


def sample_direction(iv, price):
    """Diagnostic-only three-way call for ONE sample treated as its own single-point band —
    mirrors (does not import) the core comparison in depth_pipeline.band_verdict
    (depth_pipeline.py:404-419), MINUS the moat override and the dispersion gate, both of which
    apply to the run's aggregate band rather than to a single sample. This never gates or
    publishes: it exists only so the battery can report whether individual samples already agree
    on a call before dispersion is even considered (PHASE_4_AMENDMENTS.md B6).
    """
    if iv is None or not price:
        return None
    if price > iv:
        return "overvalued"
    if price < iv:
        return "undervalued"
    return "hold"


def summarize_run(name, doc):
    price = doc.get("price")
    runs = doc.get("runs") or []
    per_sample = []
    for r in runs:
        sc = r.get("scorecard") or {}
        per_sample.append({
            "sample": r.get("sample"),
            "base_iv": r.get("iv"),
            "bull_iv": sc.get("bull_iv"),
            "bear_iv": sc.get("bear_iv"),
            "direction": sample_direction(r.get("iv"), price),
            "secs": r.get("secs"),
            "truncated": r.get("truncated"),
            "forced_report": r.get("forced_report"),
            "budget_exhausted": r.get("budget_exhausted"),
            "stub_rejected": r.get("stub_rejected"),
            "evidence_store_hits": r.get("evidence_store_hits"),
            "evidence_store_misses": r.get("evidence_store_misses"),
        })
    directions = [s["direction"] for s in per_sample if s["direction"] is not None]
    direction_agreement = bool(directions) and len(set(directions)) == 1
    first_two = [r.get("iv") for r in runs[:2]
                if r.get("iv") and r.get("plausible") and not r.get("truncated")]
    spread_first_two = ((max(first_two) / min(first_two) - 1) * 100
                        if len(first_two) == 2 else None)
    return {
        "ticker": name, "price": price,
        "pack_source": doc.get("pack_source"), "pack_sha256": doc.get("pack_sha256"),
        "temperature": doc.get("temperature"),
        "samples_run": doc.get("samples_run"), "spread_pct": doc.get("spread_pct"),
        "spread_pct_first_two": (round(spread_first_two, 1)
                                 if spread_first_two is not None else None),
        "direction_agreement": direction_agreement, "directions": directions,
        "median_iv": doc.get("median_iv"), "converged": doc.get("converged"),
        "samples": per_sample,
    }


def run_name(name, args, out_root):
    name = name.upper()
    name_dir = out_root / name
    pack_path = name_dir / "_pack.md"
    evidence_dir = name_dir / "_evidence"
    consensus_out = name_dir / f"arm_{args.arm}"

    pack, reused = build_frozen_pack(name, pack_path)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    eff_temp = args.temperature if args.temperature is not None else ARM_TEMPERATURE.get(args.arm)
    cmd = consensus_command(name, args.samples, args.arm, args.temperature, pack_path,
                            evidence_dir, consensus_out, model=args.model, ctx=args.ctx)

    if args.dry_run:
        print(f"[dry-run] {name}: pack {'reused' if reused else 'built'} at {pack_path} "
              f"({len(pack):,} chars) | evidence store: {evidence_dir}", flush=True)
        print("  " + " ".join(_quote(c) for c in cmd), flush=True)
        return {"ticker": name, "dry_run": True, "pack_path": str(pack_path),
                "pack_reused": reused, "evidence_store": str(evidence_dir), "command": cmd}

    existing = _existing_complete_run(consensus_out, name, args.samples)
    if existing is not None:
        print(f"[dispersion] {name}: already complete ({existing.get('samples_run')} samples) "
              "— skipping", flush=True)
        return summarize_run(name, existing)

    print(f"[dispersion] {name}: running arm {args.arm}"
          + (f" (temperature {eff_temp})" if eff_temp is not None else "") + " ...", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"[dispersion] {name}: consensus subprocess exit {r.returncode}", flush=True)
        return {"ticker": name, "error": f"consensus subprocess exit {r.returncode}"}

    doc = _existing_complete_run(consensus_out, name, args.samples)
    if doc is None:
        print(f"[dispersion] {name}: consensus produced no complete run", flush=True)
        return {"ticker": name, "error": "no complete consensus run produced"}
    print(f"[dispersion] {name}: done in {time.time() - t0:.0f}s", flush=True)
    return summarize_run(name, doc)


def main():
    ap = argparse.ArgumentParser(description="P4.0b frozen-evidence dispersion battery")
    ap.add_argument("--names", required=True,
                    help="comma-separated tickers, e.g. FIX,AMD,DXC,GEV")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--arm", required=True, choices=["A", "B", "C"])
    ap.add_argument("--temperature", type=float, default=None,
                    help="override the arm's default temperature (arm A: none, arm B: 0.3)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ctx", type=int, default=DEFAULT_CTX)
    ap.add_argument("--dry-run", action="store_true",
                    help="build packs and evidence-store dirs, print the consensus_valuation "
                         "command lines, run nothing")
    args = ap.parse_args()

    if args.arm == "C":
        print(f"[dispersion] ::HARD FAIL:: {ARM_C_BLOCKED}", flush=True)
        raise SystemExit(ARM_C_BLOCKED)

    names = [x.strip().upper() for x in args.names.split(",") if x.strip()]
    if not names:
        raise SystemExit("--names must list at least one ticker")

    out_root = args.out or (HERE / "tools" / "audit_202608" / "ab_reports"
                            / f"dispersion_{datetime.now().strftime('%Y%m%d')}")
    out_root.mkdir(parents=True, exist_ok=True)

    results = [run_name(name, args, out_root) for name in names]

    if args.dry_run:
        return

    # ---- overall battery metrics -------------------------------------------------------------
    # PHASE_4_ANALYST.md success metric (>= 80% of names spread <= 15% at n=2, base IV stable)
    # plus PHASE_4_AMENDMENTS.md B6's direction addition (>= 90% of names agree on direction).
    ok = [r for r in results if "error" not in r]
    n = len(ok)
    with_spread = [r for r in ok if r.get("spread_pct_first_two") is not None]
    share_spread_le_15 = (sum(1 for r in with_spread if r["spread_pct_first_two"] <= 15.0)
                          / len(with_spread)) if with_spread else None
    share_direction_agree = (sum(1 for r in ok if r.get("direction_agreement")) / n) if n else None
    all_secs = [s.get("secs") for r in ok for s in r.get("samples", []) if s.get("secs")]
    median_secs = st.median(all_secs) if all_secs else None

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "arm": args.arm, "samples_requested": args.samples, "names": names,
        "out_dir": str(out_root),
        "results": results,
        "overall": {
            "n_names": n,
            "share_spread_le_15pct_first_two_samples": (
                round(share_spread_le_15 * 100, 1) if share_spread_le_15 is not None else None),
            "share_all_samples_agree_on_direction": (
                round(share_direction_agree * 100, 1) if share_direction_agree is not None
                else None),
            "median_sample_time_s": median_secs,
        },
    }
    (out_root / "battery_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n[dispersion] battery complete -> {out_root / 'battery_summary.json'}")
    print(f"  spread<=15% (first two samples): "
          f"{summary['overall']['share_spread_le_15pct_first_two_samples']}%")
    print(f"  direction agreement: {summary['overall']['share_all_samples_agree_on_direction']}%")
    print(f"  median sample time: {median_secs}s" if median_secs else "  median sample time: n/a")


if __name__ == "__main__":
    main()

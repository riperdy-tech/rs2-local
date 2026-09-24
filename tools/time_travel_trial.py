#!/usr/bin/env python3
"""tools/time_travel_trial.py — Phase 4 E4.3: the point-in-time (time-travel) trial.

Evaluates the new analyst (charter v3.1 / pack rev 6 / model rs2-analyst-deep-mtp5-v31) on
briefings dated `--asof` (research OFF, point-in-time pack mode — `capability_test.build_pack`'s
`asof=` parameter), graded against what price did from `--asof` to `--horizon-end`. This tests
the VALUATION ENGINE, not research (PHASE_4_AMENDMENTS.md E4). It INFORMS; it does not gate.

For each requested name this script:
  1. builds (or reuses, if already on disk) ONE point-in-time pack — capability_test.build_pack(
     name, asof=...) + TASK, with NO RESEARCH_ADDENDUM (research is off) — under
     `<out>/<NAME>/_pack.md`;
  2. runs tools/audit_202608/consensus_valuation.py ONCE with `--pack-file` (so it never rebuilds
     the pack itself), `--price`/`--price-asof` (the SAME as-of close the pack itself used — see
     below for why this is mandatory), `--no-research` (there is no literal `--no-tools` flag in
     consensus_valuation.py; omitting `--tools` already means tools off by default, and
     `--no-research` is the flag that actually exists for turning research off — see the
     REPORT for this discrepancy against the work order's exact wording), `--samples`, `--model`,
     `--out-dir <out>/<NAME>/consensus/`;
  3. grades the result: the realized return from the as-of close to the horizon-end close, vs
     IWM, using the SAME price fetch/cache machinery `tools/grade_depth_verdicts.py` (the
     production grader) already uses — `fetch_history`/`close_on_or_after`/`close_on_or_before`,
     imported directly, not reimplemented; and the verdict's direction/m/momentum_view/
     entry_timing via `depth_pipeline.band_verdict(consensus_doc)` — the single canonical
     computation of those fields (non-negotiable 5, single owner per field) — called here as a
     PURE FUNCTION on an already-written consensus.json dict. This NEVER calls
     `depth_pipeline.main()`, `orchestrate_depth.py`, `deep_research.py` or `sync_state.py`,
     never runs Ollama directly (only the `consensus_valuation.py` subprocess does, and only
     outside `--dry-run`), never writes a ledger, and never publishes.

WHY `--price`/`--price-asof` ARE MANDATORY HERE. `consensus_valuation.py`'s own `price` variable
— used for every MoS/direction/plausibility comparison — defaults to TODAY's live
`financials/{T}.json` price whenever `--price` is not given, REGARDLESS of `--pack-file`: a
frozen pack reused verbatim does not re-derive price for the harness. Omitting `--price` on a
point-in-time run would silently grade the model's point-in-time valuation against TODAY's price
— exactly the look-ahead this trial exists to keep out. `capability_test._asof_price_lookup` (the
same historical close the pack itself embedded) is called again here, once per name, to supply it.

Usage:
  python tools/time_travel_trial.py --names AMD,MU,NVDA,DELL,ANET,GEV,FIX,CAT,COST,DXC \\
      --asof 2026-03-31 --horizon-end 2026-06-30 --samples 1 \\
      --model rs2-analyst-deep-mtp5-v31 --out tools/audit_202608/ab_reports/timetravel_20260924
  python tools/time_travel_trial.py --names GEV --asof 2026-03-31 --horizon-end 2026-06-30 \\
      --dry-run
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]           # repo root (rs2-local)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import rs2_data                     # noqa: E402
import capability_test as cap       # noqa: E402
import grade_depth_verdicts as gdv  # noqa: E402  (price fetch/cache — the grader's own machinery)
import depth_pipeline               # noqa: E402  (band_verdict — pure computation, never main())

CONSENSUS_SCRIPT = HERE / "tools" / "audit_202608" / "consensus_valuation.py"
DEFAULT_MODEL = "rs2-analyst-deep-mtp5-v31"


def _quote(s):
    """Wrap an argument containing whitespace in quotes, for a copy-pasteable printed command
    line only — the real subprocess call below passes `cmd` as a list and needs no quoting."""
    s = str(s)
    return f'"{s}"' if " " in s else s


def build_asof_pack(name, asof_date, pack_path, force=False):
    """Write capability_test.build_pack(name, asof=asof_date) + TASK to `pack_path`, unless a
    pack is already there and force=False (reused verbatim — resumable at the name level, same
    discipline as tools/dispersion_battery.py's build_frozen_pack). Returns (pack_text, reused).

    NO OLLAMA CALL: build_pack() reads static data files plus one historical-price network fetch
    (no model inference) — safe under --dry-run.
    """
    if pack_path.exists() and not force:
        return pack_path.read_text(encoding="utf-8"), True
    pack_text = cap.build_pack(name, asof=asof_date)
    pack = pack_text + "\n\n---\n\n" + cap.TASK
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(pack, encoding="utf-8")
    return pack, False


def consensus_command(name, samples, model, pack_path, consensus_out, asof_price, asof_price_date):
    """The exact consensus_valuation.py command line for one name's trial run. No `--tools`
    (already the default) and `--no-research`: see the module docstring for why this, not a
    literal `--no-tools`, is what actually turns research off in the current harness."""
    return [sys.executable, str(CONSENSUS_SCRIPT), name,
            "--model", model, "--think", "high",
            "--samples", str(samples), "--no-early-stop",
            "--pack-file", str(pack_path),
            "--no-research",
            "--price", str(asof_price), "--price-asof", str(asof_price_date),
            "--out-dir", str(consensus_out)]


def _existing_complete_run(consensus_out, name, samples):
    """The newest consensus.json under `consensus_out` for `name` whose samples_run >= `samples`,
    or None — the trial's resume granularity, identical to dispersion_battery.py's own."""
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


def run_name(name, asof_date, args, out_root):
    """Build the pack, fetch the as-of price, run (or reuse) consensus_valuation. Returns a dict:
    under --dry-run, {"ticker", "dry_run": True, ...}; on success, the consensus.json dict itself
    (tagged with "ticker"); on failure, {"ticker", "error"}."""
    name = name.upper()
    name_dir = out_root / name
    pack_path = name_dir / "_pack.md"
    consensus_out = name_dir / "consensus"

    force = getattr(args, "force_pack", False)
    pack, reused = build_asof_pack(name, asof_date, pack_path, force=force)

    coe_data = rs2_data.asof_coe_anchor(name, asof_date)
    coe_components = {
        "rf": coe_data.get("rf"),
        "sector_loading": coe_data.get("sector_loading"),
        "erp": coe_data.get("erp"),
        "erp_source": coe_data.get("erp_source"),
    }

    px_data = cap._asof_price_lookup(name, asof_date)
    if px_data is None:
        print(f"[time-travel] {name}: no as-of close found near {asof_date.isoformat()} — "
              "skipping", flush=True)
        return {"ticker": name, "error": "no_asof_price"}

    cmd = consensus_command(name, args.samples, args.model, pack_path, consensus_out,
                            px_data["price"], px_data["asof"])

    if args.dry_run:
        print(f"[dry-run] {name}: pack {'reused' if reused else 'built'} at {pack_path} "
              f"({len(pack):,} chars) | as-of close ${px_data['price']} ({px_data['asof']}) | "
              f"CoE anchor {coe_data['coe_anchor_asof']}% "
              f"(rf {coe_data['rf']}%, load {coe_data['sector_loading']}x, erp {coe_data['erp']}%)",
              flush=True)
        print("  " + " ".join(_quote(c) for c in cmd), flush=True)
        return {"ticker": name, "dry_run": True, "pack_path": str(pack_path),
                "pack_chars": len(pack), "pack_reused": reused,
                "asof_price": px_data["price"], "asof_price_date": px_data["asof"],
                "coe_anchor_asof": coe_data["coe_anchor_asof"],
                "coe_anchor_components": coe_components,
                "rf_asof": coe_data["rf"],
                "sector_loading": coe_data["sector_loading"],
                "erp_asof": coe_data["erp"],
                "command": cmd}

    existing = _existing_complete_run(consensus_out, name, args.samples)
    if existing is not None:
        print(f"[time-travel] {name}: already complete ({existing.get('samples_run')} "
              "samples) — skipping", flush=True)
        existing["ticker"] = name
        existing["coe_anchor_asof"] = coe_data["coe_anchor_asof"]
        existing["coe_anchor_components"] = coe_components
        existing["rf_asof"] = coe_data["rf"]
        existing["sector_loading"] = coe_data["sector_loading"]
        existing["erp_asof"] = coe_data["erp"]
        return existing

    print(f"[time-travel] {name}: running (as-of price ${px_data['price']}, "
          f"{px_data['asof']}) ...", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"[time-travel] {name}: consensus subprocess exit {r.returncode}", flush=True)
        return {"ticker": name, "error": f"consensus subprocess exit {r.returncode}"}

    doc = _existing_complete_run(consensus_out, name, args.samples)
    if doc is None:
        print(f"[time-travel] {name}: consensus produced no complete run", flush=True)
        return {"ticker": name, "error": "no complete consensus run produced"}
    print(f"[time-travel] {name}: done in {time.time() - t0:.0f}s", flush=True)
    doc["ticker"] = name
    doc["coe_anchor_asof"] = coe_data["coe_anchor_asof"]
    doc["coe_anchor_components"] = coe_components
    doc["rf_asof"] = coe_data["rf"]
    doc["sector_loading"] = coe_data["sector_loading"]
    doc["erp_asof"] = coe_data["erp"]
    return doc


def grade_name(name, asof_iso, horizon_iso, price_cache, doc):
    """One graded row: the realized return from the as-of close to the horizon-end close, vs
    IWM, plus the verdict's direction/m/momentum_view/entry_timing from
    depth_pipeline.band_verdict (pure computation on `doc`, never depth_pipeline.main()).

    Entry/exit convention matches tools/grade_depth_verdicts.py's own grade_rows exactly: entry
    is the first trading day ON OR AFTER `asof_iso` (close_on_or_after), exit is the last trading
    day ON OR BEFORE `horizon_iso` (close_on_or_before) — the same asymmetry the production
    grader uses for every verdict it grades.
    """
    verdict = depth_pipeline.band_verdict(doc)
    d0, p0 = gdv.close_on_or_after(price_cache, name, asof_iso)
    d1, p1 = gdv.close_on_or_before(price_cache, name, horizon_iso)
    b0 = (price_cache.get("IWM") or {}).get(d0) if d0 else None
    b1 = (price_cache.get("IWM") or {}).get(d1) if d1 else None
    ret = (p1 / p0 - 1.0) if (p0 and p1) else None
    excess = (ret - (b1 / b0 - 1.0)) if (ret is not None and b0 and b1) else None

    row = {
        "ticker": name,
        "direction": verdict.get("direction"),
        "m": verdict.get("m"),
        "base_iv": doc.get("median_iv"),
        "price_at_asof": doc.get("price"),
        "mos_pct": doc.get("median_mos_pct"),
        "coe_anchor_asof": doc.get("coe_anchor_asof"),
        "coe_anchor_components": doc.get("coe_anchor_components"),
        "rf_asof": doc.get("rf_asof"),
        "sector_loading": doc.get("sector_loading"),
        "erp_asof": doc.get("erp_asof"),
        "momentum_view": verdict.get("momentum_view"),
        "entry_timing": verdict.get("entry_timing"),
        "position_basis": verdict.get("position_basis"),
        "entry_date": d0, "entry_price": p0,
        "exit_date": d1, "exit_price": p1,
        "return_pct": round(ret * 100, 2) if ret is not None else None,
        "excess_vs_iwm_pct": round(excess * 100, 2) if excess is not None else None,
        "samples_run": doc.get("samples_run"), "converged": doc.get("converged"),
    }
    # Hit rule: an undervalued call hits if it beat IWM; an overvalued call hits if it lagged
    # IWM. hold/NOT_USABLE are not scored — there is no directional claim to check (informational
    # only; this trial does not gate on it).
    hit = None
    if row["excess_vs_iwm_pct"] is not None:
        if row["direction"] == "undervalued":
            hit = row["excess_vs_iwm_pct"] > 0
        elif row["direction"] == "overvalued":
            hit = row["excess_vs_iwm_pct"] < 0
    row["hit"] = hit
    return row


def write_markdown(out_root, args, rows):
    lines = [f"# Time-travel trial — as of {args.asof} -> {args.horizon_end}", "",
             f"Model: `{args.model}` | samples/name: {args.samples} | research OFF "
             "(point-in-time pack mode)", "",
             "| ticker | direction | base IV | price@asof | MoS | momentum_view | "
             "entry_timing | position_basis | 3mo return | excess vs IWM | hit |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    scored = [r for r in rows if isinstance(r, dict) and r.get("hit") is not None]
    hits = sum(1 for r in scored if r["hit"])
    for r in rows:
        if not isinstance(r, dict) or "error" in r:
            t = r.get("ticker", "?") if isinstance(r, dict) else "?"
            lines.append(f"| {t} | ERROR: {r.get('error') if isinstance(r, dict) else r} | | | "
                         "| | | | | | |")
            continue
        lines.append(
            f"| {r['ticker']} | {r.get('direction')} | "
            f"{r.get('base_iv')} | {r.get('price_at_asof')} | "
            f"{r.get('mos_pct')} | {r.get('momentum_view')} | {r.get('entry_timing')} | "
            f"{r.get('position_basis')} | "
            f"{r.get('return_pct')} | {r.get('excess_vs_iwm_pct')} | "
            f"{'HIT' if r.get('hit') else ('MISS' if r.get('hit') is False else 'n/a')} |")
    lines += ["", f"**Hit table**: {hits}/{len(scored)} directional calls beat/lagged IWM as "
             "claimed (hold/NOT_USABLE/errors excluded — informational only, this trial does "
             "not gate)."]
    (out_root / "trial_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Phase 4 E4.3 time-travel (point-in-time) trial")
    ap.add_argument("--names", required=True, help="comma-separated tickers")
    ap.add_argument("--asof", required=True, help="briefing date, e.g. 2026-03-31")
    ap.add_argument("--horizon-end", required=True, help="grading date, e.g. 2026-06-30")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="build packs, fetch as-of prices, print the consensus_valuation "
                         "command lines, run nothing")
    ap.add_argument("--force-pack", action="store_true",
                    help="rebuild packs even if already cached on disk")
    args = ap.parse_args()

    names = [x.strip().upper() for x in args.names.split(",") if x.strip()]
    if not names:
        raise SystemExit("--names must list at least one ticker")

    asof_date = cap._parse_asof(args.asof)
    horizon_date = cap._parse_asof(args.horizon_end)
    if horizon_date <= asof_date:
        raise SystemExit(f"--horizon-end ({horizon_date}) must be after --asof ({asof_date})")
    asof_iso, horizon_iso = asof_date.isoformat(), horizon_date.isoformat()

    out_root = args.out or (HERE / "tools" / "audit_202608" / "ab_reports"
                            / f"timetravel_{datetime.now().strftime('%Y%m%d')}")
    out_root.mkdir(parents=True, exist_ok=True)

    docs = [run_name(name, asof_date, args, out_root) for name in names]

    if args.dry_run:
        (out_root / "trial_summary.json").write_text(
            json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                       "dry_run": True, "asof": asof_iso, "horizon_end": horizon_iso,
                       "model": args.model, "samples": args.samples, "names": names,
                       "results": docs}, indent=2),
            encoding="utf-8")
        print(f"\n[time-travel] dry-run complete -> {out_root / 'trial_summary.json'}")
        return

    # Grading: one price-history fetch covering every name + IWM, from just before `asof` (entry
    # is close_on_or_after, so nothing earlier is needed) through the horizon end.
    price_cache = {}
    fetch_start = (asof_date - timedelta(days=10)).isoformat()
    gdv.fetch_history(names + ["IWM"], fetch_start, price_cache)

    rows = []
    for name, doc in zip(names, docs):
        if not isinstance(doc, dict) or "error" in doc:
            rows.append(doc)
            continue
        rows.append(grade_name(name, asof_iso, horizon_iso, price_cache, doc))

    scored = [r for r in rows if isinstance(r, dict) and r.get("hit") is not None]
    hits = sum(1 for r in scored if r["hit"])
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "asof": asof_iso, "horizon_end": horizon_iso, "model": args.model,
        "samples": args.samples, "names": names, "out_dir": str(out_root),
        "results": rows,
        "overall": {"n_names": len(names), "n_scored": len(scored), "n_hit": hits,
                   "hit_rate_pct": round(hits / len(scored) * 100, 1) if scored else None},
    }
    (out_root / "trial_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_markdown(out_root, args, rows)
    print(f"\n[time-travel] trial complete -> {out_root / 'trial_summary.json'}")
    print(f"  hit rate: {summary['overall']['hit_rate_pct']}% ({hits}/{len(scored)} scored)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""publish_reports.py — publish RS2 research + outcomes to the screener site.

Writes into the screener repo's public/data/rs2/:
  index.json            ALL runs, METADATA ONLY (small): {generated_at, tickers:{T:{latest, history:[...]}}}
  {TICKER}/{ts}.json    ONE run, FULL TEXT: {verdict, final_md, research_md, raw:{s1..s6, fed_data}}

Bounded: keep the newest K (default 8) full-text bundles per ticker; older runs stay LISTED in
index.json (verdict metadata) but their full text is pruned. A run's content is immutable, so a
bundle is written once (skipped if it already exists) -> minimal git churn.

Security: a secret-guard refuses to write any bundle whose text contains a known API key (loaded
from .secrets.json) or a Tavily-key pattern. Research briefs carry only public news URLs.

Standalone:  python publish_reports.py [--k 8] [--limit-tickers T1,T2]
Importable:  from publish_reports import publish ; publish()
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
SD = Path(CONFIG["screener_data_dir"])
REPORTS = Path(CONFIG["out_reports_dir"])
RESEARCH = Path(CONFIG["out_research_dir"])
OUT = SD / "rs2"
DEFAULT_K = 8

# stage file -> key in the bundle's "raw" object (human order preserved for the UI accordion)
STAGE_FILES = [
    ("s1", "S1_macro_classify.md"),
    ("s2", "S2_quality.md"),
    ("s3", "S3_valuation.md"),
    ("s3_inputs", "S3_valuation_inputs.json"),
    ("s4", "S4_scenarios.md"),
    ("s4_result", "S4_valuation_result.md"),
    ("s5", "S5_conviction.md"),
    ("s6", "S6_redteam_audit.md"),
    ("fed_data", "_fed_data.md"),
]
FOLDER_RE = re.compile(r"^(?P<t>.+)_(?P<d>\d{8})_(?P<tm>\d{6})$")


def _secret_patterns():
    """Literal secrets from .secrets.json (never committed) + generic key regexes."""
    literals = set()
    sec = HERE / ".secrets.json"
    if sec.exists():
        try:
            for v in json.loads(sec.read_text(encoding="utf-8")).values():
                if isinstance(v, str) and len(v) >= 12:
                    literals.add(v)
        except Exception:
            pass
    regexes = [re.compile(r"tvly-[A-Za-z0-9_\-]{16,}"), re.compile(r"sk-[A-Za-z0-9]{20,}")]
    return literals, regexes


def _has_secret(text, literals, regexes):
    for lit in literals:
        if lit in text:
            return True
    return any(rx.search(text) for rx in regexes)


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _iso_date(ts, fallback):
    try:
        return datetime.strptime(ts[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except Exception:
        return fallback


def _meta(v, ts, date, folder):
    """Small metadata record for index.json (one per run, always kept)."""
    return {
        "ts": ts, "date": v.get("date") or date,
        "action": v.get("action"), "conviction": v.get("conviction"),
        "stance": v.get("stance"), "method": v.get("method"),
        "expectations_gap_pts": v.get("expectations_gap_pts"),
        "mos_pct": v.get("mos_pct"), "fair_value": v.get("fair_value"),
        "recommended_weight_pct": v.get("recommended_weight_pct"),
        "band_at_analysis": v.get("band_at_analysis"), "report": folder,
    }


def _scan():
    """({TICKER: [(ts, date, folder_path, verdict) newest-first]}, {TICKER: {ts, ...} unreadable}).
    Runs whose verdict.json won't parse land in the second dict so the prune step can PRESERVE
    their already-published bundles — silently skipping them made one torn/corrupt local file
    delete the run's published site bundle on the next push."""
    runs, corrupt = {}, {}
    if not REPORTS.exists():
        return runs, corrupt
    for d in REPORTS.iterdir():
        if not d.is_dir():
            continue
        m = FOLDER_RE.match(d.name)
        if not m:
            continue
        t = m.group("t").upper()
        ts = f"{m.group('d')}_{m.group('tm')}"
        try:
            v = json.loads((d / "verdict.json").read_text(encoding="utf-8-sig"))
        except Exception:
            corrupt.setdefault(t, set()).add(ts)
            continue
        runs.setdefault(t, []).append((ts, _iso_date(ts, v.get("date")), d, v))
    for t in runs:
        runs[t].sort(key=lambda r: r[0], reverse=True)
    return runs, corrupt


def _bundle(t, ts, date, folder, v, literals, regexes):
    """Full-text bundle for one run. Returns dict or None if it would leak a secret."""
    raw = {}
    for key, fname in STAGE_FILES:
        txt = _read(folder / fname)
        if txt is not None:
            raw[key] = txt
    research = _read(folder / "research.md")          # per-run snapshot (preferred)
    if research is None:
        research = _read(RESEARCH / f"{t}.md")         # fallback for backfilled runs
    research_gen = None
    if research:
        mm = re.search(r"Generated:\s*([0-9\-: ]+)", research)
        research_gen = mm.group(1).strip() if mm else None
    bundle = {
        "ticker": t, "ts": ts, "date": v.get("date") or date,
        "verdict": v, "final_md": _read(folder / "FINAL.md"),
        "research_md": research, "research_generated": research_gen, "raw": raw,
    }
    if _has_secret(json.dumps(bundle, ensure_ascii=False), literals, regexes):
        return None
    return bundle


def publish(k=DEFAULT_K, only=None, verbose=True):
    literals, regexes = _secret_patterns()
    runs, corrupt = _scan()
    if only:
        only = {x.upper() for x in only}
        runs = {t: r for t, r in runs.items() if t in only}
    OUT.mkdir(parents=True, exist_ok=True)

    index = {}
    written = pruned = skipped = blocked = 0
    for t, rlist in runs.items():
        tdir = OUT / t
        history = [_meta(v, ts, date, folder.name) for ts, date, folder, v in rlist]
        index[t] = {"latest": history[0], "history": history}
        keep_ts = {ts for ts, *_ in rlist[:k]} | corrupt.get(t, set())   # never prune a run we couldn't read
        # write newest-K full bundles (skip if already present — content is immutable)
        for ts, date, folder, v in rlist[:k]:
            dst = tdir / f"{ts}.json"
            if dst.exists():
                skipped += 1
                continue
            b = _bundle(t, ts, date, folder, v, literals, regexes)
            if b is None:
                blocked += 1
                if verbose:
                    print(f"  ! {t} {ts}: SECRET pattern detected — bundle NOT written", flush=True)
                continue
            tdir.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
            written += 1
        # prune full text beyond newest-K (metadata stays in index)
        if tdir.exists():
            for f in tdir.glob("*.json"):
                if f.stem not in keep_ts:
                    f.unlink(missing_ok=True)
                    pruned += 1

    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "k_full_per_ticker": k, "count": len(index), "tickers": index}
    (OUT / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    if verbose:
        print(f"published rs2/: {len(index)} tickers | bundles +{written} skip {skipped} "
              f"pruned {pruned} blocked {blocked} -> {OUT}", flush=True)
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=DEFAULT_K, help="full-text bundles kept per ticker")
    ap.add_argument("--limit-tickers", default="", help="comma list to restrict (testing)")
    args = ap.parse_args()
    only = [x for x in args.limit_tickers.split(",") if x.strip()] or None
    publish(k=args.k, only=only)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())

#!/usr/bin/env python3
"""rederive_verdicts.py — recompute published verdicts whose lost votes are recoverable.

WHY. The IV parser gained two patterns after the sweep began (`e602cd4`, `8caae7c`), each added
because a real vote had been discarded — the report stated a value in a phrasing no pattern
recognised. Those commits fixed FUTURE runs only. Verdicts already published on the old patterns
still rest on a smaller sample base than the evidence on disk supports.

This is a pure re-derivation: it re-parses the STORED sample reports with today's patterns, applies
the SAME plausibility guard and the SAME band rule, and appends a corrected row to the append-only
ledger. No model is run, no GPU is used, nothing is deleted — the original row stays in history.

It refuses to change a verdict DIRECTION. Recovering a parser miss should widen a band and correct
a size hint; if it would flip a published buy/sell/hold call, that is a bigger decision than a
tooling fix and stops for the operator.

  python tools/audit_202608/rederive_verdicts.py            # report only
  python tools/audit_202608/rederive_verdicts.py --apply    # append corrected rows
"""
import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

from consensus_valuation import extract_iv, plausibility  # noqa: E402
import depth_pipeline as dp  # noqa: E402

# BOTH imports rebind sys.stdout to their own TextIOWrapper over the SAME buffer, so whichever is
# garbage-collected first closes it under the other and every print raises "I/O operation on
# closed file". Take an independent duplicate of fd 1 instead; nothing else can close it.
import io  # noqa: E402
import os  # noqa: E402
sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8",
                              errors="replace", line_buffering=True)

LEDGER = HERE / "cache" / "depth_ledger.jsonl"
CONS = HERE / "ab_reports" / "consensus"


def newest():
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            v = json.loads(line)
            out[v["ticker"]] = v
    return out


def main():
    apply = "--apply" in sys.argv
    changed = []
    for t, v in sorted(newest().items()):
        d = CONS / (v.get("consensus_dir") or "")
        cj = d / "consensus.json"
        if not cj.exists():
            continue
        doc = json.loads(cj.read_text(encoding="utf-8"))
        price = doc.get("price")
        touched = False
        for r in doc.get("runs", []):
            if r.get("iv"):
                continue                       # already had a value
            sp = d / f"sample{r['sample']}.md"
            if not sp.exists():
                continue
            vals = extract_iv(sp.read_text(encoding="utf-8", errors="replace"), price)
            if not vals:
                continue                       # genuinely stated no value
            iv = st.median(vals)
            ok, why = plausibility(iv, price, t)
            r["iv"] = iv
            r["all_iv_mentions"] = sorted(set(vals))[:8]
            r["plausible"] = ok
            r["reasons"] = why
            r["recovered_by"] = "rederive_verdicts: parser patterns added after this run"
            touched = True
        if not touched:
            continue
        good = [r["iv"] for r in doc["runs"]
                if r.get("iv") and r.get("plausible") and not r.get("truncated")]
        doc["median_iv"] = st.median(good) if good else None
        doc["spread_pct"] = (round((max(good) / min(good) - 1) * 100, 1)
                             if len(good) >= 2 else None)
        nv = dp.band_verdict(doc)
        nv["consensus_dir"] = v["consensus_dir"]
        nv["rederived_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        nv["supersedes"] = {"n_basis": v.get("n_basis"), "band": [v.get("iv_band_low"),
                            v.get("iv_band_high")], "spread_pct": v.get("spread_pct"),
                            "size_hint": v.get("size_hint")}
        flip = nv["direction"] != v["direction"]
        print(f"{t}: n_basis {v['n_basis']} -> {nv['n_basis']} | "
              f"band ${v['iv_band_low']}-${v['iv_band_high']} -> "
              f"${nv['iv_band_low']}-${nv['iv_band_high']} | "
              f"spread {v['spread_pct']} -> {nv['spread_pct']} | "
              f"size {v['size_hint']} -> {nv['size_hint']}"
              + ("   *** DIRECTION WOULD FLIP — SKIPPED, operator decision ***" if flip else ""))
        if flip:
            continue
        changed.append((t, doc, nv, cj))
    if not changed:
        print("\nnothing to re-derive.")
        return 0
    if not apply:
        print(f"\n{len(changed)} verdict(s) would be corrected. Re-run with --apply to append.")
        return 0
    for t, doc, nv, cj in changed:
        cj.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        (cj.parent / "verdict_depth.json").write_text(json.dumps(nv, indent=2), encoding="utf-8")
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(nv) + "\n")
    print(f"\nappended {len(changed)} corrected verdict(s); originals remain in ledger history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

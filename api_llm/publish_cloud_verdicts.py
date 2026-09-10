#!/usr/bin/env python3
"""publish_cloud_verdicts.py - put cloud-arm verdicts into the book, exactly like local ones.

OPERATOR DECISION 2026-08-25 (option A): cloud verdicts join the SAME ledger and the SAME
overlay as local ones, stamped with their provenance, and are pushed to the screener repo by
the same path. Approved on the strength of the 28-ticker A/B: flash agrees with the local Qwen
arm 75-79% and with ITSELF 82%, so the cross-model difference sits inside flash's own
run-to-run noise (api_llm/DEEPSEEK_V4_FLASH_AB_20260824.md).

KNOWN COST OF THIS DECISION, accepted deliberately: depth_triggers treats a name with a verdict
as no longer BASELINE work, so publishing here stops the local sweep from queueing these names.
They return to the local arm only on an 8-K, a 10-Q/10-K, an 8% move, a PACK_REVISION bump, or
the 90-day rotation.

WHAT IS PUBLISHED. Every --fresh run of the publishable model whose ticker is in the live book.
OPERATOR DECISION 2026-09-07: local and cloud verdicts are the SAME KIND OF RESULT and are treated
as such - the newest verdict for a name wins, whichever arm produced it. The earlier rule that a
LOCAL newest verdict was protected from a cloud publish is retired (it existed while the cloud arm
was an experiment; the continuity arm, api_llm/cloud_backstop.py, serves the same trigger queue
the PC does, so a cloud refresh IS the scheduled re-run for that trigger).
Replay runs (--dir) are excluded by construction: they duplicate names the local arm has done.

REPORT BUNDLES. orchestrate_depth.build_report_bundles() reads ab_reports/consensus/{dir}, which
a cloud run does not have - it would silently skip every cloud ticker and the site's depth panel
would show a verdict with no reports behind it. So this script writes those bundles itself, in
the same schema, from the cloud run directory.

ENGINE UNTOUCHED. rebuild_overlay() and publish_overlay() are imported and called, not modified.

  python api_llm/publish_cloud_verdicts.py --dry-run     # show what would be published
  python api_llm/publish_cloud_verdicts.py               # write ledger + bundles + overlay
  python api_llm/publish_cloud_verdicts.py --push        # ...and push to the screener repo
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "audit_202608"))

_STDOUT_KEEPALIVE = [sys.stdout]
import orchestrate_depth as od     # noqa: E402  rebuild_overlay, publish_overlay, LEDGER, SD

DEEP_API = HERE / "deep_api"
# The id the cloud arm currently runs (deep_api_run.MODEL). Runs stamped with anything else are
# held back - that is what kept a one-ticker deepseek-v4-pro cost probe out of the book, and it
# must be moved in step with MODEL or the arm bills and publishes nothing.
#
# This is NOT the validation claim the deepseek-v4-flash pin carried. That model was measured over
# 28 names against the local arm (DEEPSEEK_V4_FLASH_AB_20260824.md). deepseek-flash (V4.1 Flash)
# has NOT been through that A/B; DeepSeek's "surpasses V4 Pro" is a vendor benchmark, not a
# measurement against RS2 bands. Operator decision 2026-09-10: publish now, A/B afterwards.
PUBLISHABLE_MODEL = "deepseek-flash"
# A pack with NO SECTION 11 at all is a different animal from one with a stale brief: the model
# analysed the name with no web research behind it beyond its own tool calls. Held back from the
# book by default; --include-no-brief overrides.
NO_BRIEF_HELD = True


def cloud_runs():
    """Newest --fresh cloud run per ticker, preferring the re-derived (current-guard) verdict."""
    out = {}
    for d in sorted(DEEP_API.glob("*_2026*")):
        cj = d / "consensus_rederived.json"
        if not cj.exists():
            cj = d / "consensus.json"
        vj = d / ("verdict_rederived.json" if (d / "verdict_rederived.json").exists()
                  else "verdict_depth.json")
        if not (cj.exists() and vj.exists()):
            continue
        doc = json.loads(cj.read_text(encoding="utf-8"))
        if doc.get("pack_source") != "fresh":
            continue                      # replays duplicate local names - never publish them
        if doc.get("model") != PUBLISHABLE_MODEL:
            continue
        out[doc["ticker"]] = (d, doc, json.loads(vj.read_text(encoding="utf-8")))
    return out


def write_bundle(t, d, doc, v):
    """Same schema as orchestrate_depth.build_report_bundles, sourced from the cloud run dir.
    Written to od.PENDING_REPORTS (out-of-tree staging); od.publish_overlay copies these into the
    dedicated publish clone after its reset and clears them once pushed. Writing them straight into
    the clone would let publish_overlay's `checkout -B main origin/main` reset clobber them."""
    out_dir = od.PENDING_REPORTS
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    for r in doc.get("runs", []):
        sp = d / f"sample{r['sample']}.md"
        samples.append({"sample": r["sample"], "iv": r.get("iv"),
                        "plausible": r.get("plausible"),
                        "reasons": r.get("reasons") or [], "flags": r.get("flags") or [],
                        "truncated": r.get("truncated"), "secs": r.get("secs"),
                        "report": sp.read_text(encoding="utf-8", errors="replace")
                        if sp.exists() else ""})
    bundle = {"ticker": t, "run": d.name, "verdict": v, "samples": samples,
              "arm": "cloud_api", "model": doc.get("model"),
              "research_brief_age_days": doc.get("research_brief_age_days")}
    dst = out_dir / f"{t}.json"
    txt = json.dumps(bundle)
    if not dst.exists() or dst.read_text(encoding="utf-8") != txt:
        # atomic: this runs BEFORE publish_overlay takes the screener lock, so a concurrent local
        # sweep's `git add depth_reports` (under that lock) must never see a half-written bundle.
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_text(txt, encoding="utf-8")
        tmp.replace(dst)
        return True
    return False


def main():
    dry = "--dry-run" in sys.argv
    push = "--push" in sys.argv
    keep_no_brief = "--include-no-brief" in sys.argv
    runs = cloud_runs()
    # The overlay is keyed to the screener's book. A name outside it (an ad-hoc test run) would
    # add a row nothing tracks, so it is not publishable however good the run was.
    book = set(od.live_book())
    pub, skip_nobrief, skip_book = [], [], []
    for t, (d, doc, v) in sorted(runs.items()):
        if t not in book:
            skip_book.append(t)
            continue
        if doc.get("research_brief_age_days") is None and NO_BRIEF_HELD and not keep_no_brief:
            skip_nobrief.append(t)
            continue
        pub.append((t, d, doc, v))
    print(f"cloud --fresh {PUBLISHABLE_MODEL} runs: {len(runs)} | not in the live book: "
          f"{len(skip_book)} {skip_book if skip_book else ''} | no-brief held back: "
          f"{len(skip_nobrief)}")
    if skip_nobrief:
        print("  held: " + " ".join(skip_nobrief) + "   (--include-no-brief to publish anyway)")
    print(f"TO PUBLISH: {len(pub)}")
    from collections import Counter
    print("  directions: " + ", ".join(f"{k}={n}" for k, n in
                                       Counter(v["direction"] for _, _, _, v in pub).items()))
    ages = [doc.get("research_brief_age_days") for _, _, doc, _ in pub]
    ages = [a for a in ages if a is not None]
    if ages:
        print(f"  research brief age: median {sorted(ages)[len(ages)//2]:.1f}d  max {max(ages):.1f}d")
    if dry:
        for t, d, doc, v in pub:
            print(f"  {t:6} {v['direction']:12} band {v.get('iv_band_low')}-{v.get('iv_band_high')}"
                  f" vs ${v.get('price')} | spread {doc.get('spread_pct')}% | {d.name}")
        print("\n--dry-run: nothing written.")
        return

    lines, bundles = [], 0
    for t, d, doc, v in pub:
        rec = dict(v)
        rec.update({"arm": "cloud_api", "model": doc.get("model"),
                    "pack_source": "fresh",
                    "research_brief_age_days": doc.get("research_brief_age_days"),
                    "pack_revision": doc.get("pack_revision", 1),
                    "published_by": "api_llm/publish_cloud_verdicts.py",
                    "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        rec.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
        lines.append(json.dumps(rec))
        bundles += write_bundle(t, d, doc, rec)
    with od.LEDGER.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"ledger: +{len(lines)} cloud verdicts -> {od.LEDGER}")
    print(f"report bundles written: {bundles} -> {od.PENDING_REPORTS} (staged for publish)")
    print(f"overlay rebuilt: {od.rebuild_overlay()} tickers -> {od.OVERLAY}")
    if push:
        od.publish_overlay()
    else:
        print("NOT PUSHED. Re-run with --push to copy into the screener repo and push.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""publish_only.py — regenerate + publish the site artifacts WITHOUT running any ticker.

The publish phase of orchestrate.main (overlay -> rs2 bundles -> ledger -> git push), reusing
the same functions so there is one implementation. Needed after a deterministic repatch
(repatch_verdicts.py rewrites verdict.json in place, but the overlay is only rebuilt during a
sweep, so the live site keeps the pre-repatch numbers until the next 08:00 run).

  python tools/publish_only.py            # regenerate, commit, push
  python tools/publish_only.py --no-push  # regenerate + commit locally only
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import orchestrate as orc          # noqa: E402
import publish_reports             # noqa: E402
import verdict_ledger              # noqa: E402


def main():
    no_push = "--no-push" in sys.argv
    state = orc.load(orc.STATE) or {}
    if not state:
        print("no analysis_state.json — nothing to publish")
        return 1

    overlay = orc.aggregate_overlay(state)
    orc.save(orc.OVERLAY, overlay)
    print(f"overlay written: {overlay['count']} tickers -> {orc.OVERLAY}")

    pub = publish_reports.publish(verbose=False)
    print(f"rs2 reports published: {pub['count']} tickers")

    vl = verdict_ledger.sync()
    print(f"verdict ledger: +{vl['appended']} appended")

    if no_push:
        print("push: skipped (--no-push)")
        return 0

    orc.git(["add", str(orc.OVERLAY), str(orc.SD / "rs2"), str(orc.SD / "rs2_verdict_log.jsonl")])
    committed, cmsg = orc.git(["commit", "-m",
                               f"chore(llm): RS2 overlay + reports {overlay['generated_at']} "
                               f"({overlay['count']} names, methodology repatch)"])
    if not committed:
        print(f"commit: {cmsg.strip()[:120]}")
        return 0
    for attempt in (1, 2, 3):
        orc.git(["fetch", "origin", "main"])
        orc.git(["checkout", "--", str(orc.SD / "scan.log")])   # log file: origin's version wins
        mok, _ = orc.git(["merge", "-X", "ours", "--no-edit", "origin/main"])
        if not mok:
            orc.git(["merge", "--abort"])
        pok, msg = orc.git(["push"])
        if pok:
            print(f"git push: ok ({msg.splitlines()[-1] if msg else ''})")
            return 0
        print(f"git push attempt {attempt} failed — re-syncing...")
    print("::ERROR:: git push FAILED after 3 attempts — SITE OVERLAY IS STALE.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

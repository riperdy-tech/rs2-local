"""prepare.py - the CPU preparation of gate 2 (SPEC_rebuild.md Addenda O and W): the five replay-date contexts.

    python -m rebuild_harness.gate2.prepare [--state-dir DIR] [--dates D ...] [--workers 3] [--limit-ciks N]

For each replay date this runs `env.prepare_dates` with the registered configuration and nothing else: the point-in-time store, the D5 daily raw closes with the monthly file behind them (M6),
the strict SIC as filed (Addendum O 3: no current-dated fallback), the priors vintage of year(T) - 1 (read by `PopulationPriors.vintage_for`), the engine-consistent ERP (Addenda L1, M).  It writes
`ctx/universe_<date>.json` and `ctx/context_<date>.pkl`; a date whose pickle exists is skipped and said so (never overwritten).  No outcome and no return is read; no GPU, no model, no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--dates", nargs="*", default=list(config.DATES))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit-ciks", type=int, help="rehearsal only: the first N companies of the id map (use with a --state-dir other than the real one)")
    a = ap.parse_args(argv)
    if a.limit_ciks and (a.state_dir is None or Path(a.state_dir).resolve() == config.STATE_DIR.resolve()):
        print("REFUSED: --limit-ciks needs a --state-dir other than the real one")
        return 2
    from . import env as env_mod
    g = env_mod._g1r()
    res = env_mod.prepare_dates(a.dates, state_dir=a.state_dir, workers=a.workers, limit_ciks=a.limit_ciks, store=g.DEFAULT_STORE, id_map=g.DEFAULT_IDMAP,
                                prices_daily=config.WORKSPACE / "data" / "prices_daily", prices_monthly=g.DEFAULT_PRICES, headers=g.DEFAULT_HEADERS, crosswalk=g.DEFAULT_CROSSWALK,
                                sic=g.DEFAULT_SIC, priors_dir=config.WORKSPACE / "data" / "priors_v3", strict_classification=True)
    print(json.dumps(sorted(res, key=lambda r: r["date"]), indent=1, default=str))
    return 1 if any("error" in r for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())

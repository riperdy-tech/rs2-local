"""closure_monthly.py - the monthly rebuild of cache/reference_closure.json (the cost of equity's equity premium), so it never ages past
rs2_data's 45-day limit (found 2026-11-04: no task rebuilt it, and the 10-04 build would have stopped the 11-30 valuations).

    python tools/closure_monthly.py [--date YYYY-MM-DD] [--passes 12] [--wait-s 1200]

Steps: the aggregate's names (reference_closure.build_aggregate, no network) -> closure_enrich_batch.py over them (the one networked step;
resumable; Yahoo answers HTTP 429 to bursts, so on exit 3 it waits `wait_s` and resumes, at most `passes` times) -> reference_closure.py
--build. The build refuses below its coverage floor and then publishes nothing, so a short fetch never replaces a good premium.
Run on the 15th (task RS2-Reference-Closure): its asof is never after a month-end formation's T, and it is about two weeks old when the
next month's valuations run. Exit codes: 0 built; 3 fetch still stopped after every pass; 2 the build refused; 1 anything else.
"""
import argparse
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TOOLS = HERE / "tools"


def names_file(day):
    """Write the aggregate's tickers to cache/closure_enrich/names_<day>.txt; returns its path."""
    sys.path[:0] = [str(HERE), str(TOOLS), str(TOOLS / "audit_202608")]
    import capability_test as cap
    import reference_closure as rc
    agg, _ = rc.build_aggregate(cap.DataRoot(), cap)
    path = HERE / "cache" / "closure_enrich" / f"names_{day}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted({c["ticker"] for c in agg["constituents"]})) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--passes", type=int, default=12)
    ap.add_argument("--wait-s", type=int, default=1200)
    a = ap.parse_args(argv)
    names = names_file(a.date)
    print(f"names: {names}", flush=True)
    for n in range(1, a.passes + 1):
        rc = subprocess.run([sys.executable, "-u", str(TOOLS / "closure_enrich_batch.py"), "--names", str(names), "--workers", "1",
                             "--date", a.date], cwd=HERE).returncode
        print(f"enrich pass {n}: exit {rc}", flush=True)
        if rc == 0:
            break
        if rc != 3:
            return 1
        time.sleep(a.wait_s)
    else:
        return 3
    rc = subprocess.run([sys.executable, str(TOOLS / "reference_closure.py"), "--build", "--asof", a.date,
                         "--enrich-dir", str(HERE / "cache" / "closure_enrich" / a.date)], cwd=HERE).returncode
    print(f"build: exit {rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())

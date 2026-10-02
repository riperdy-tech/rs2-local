"""AT1e (amendment 2, point 3): the reverse DCF's two round trips, each within 0.1 pp with the cash term.

  python at1e_round_trip.py --day <day.json from build_day.py> [--out <result.json>]

(a) own structure: price = unbundled_dcf at a constant stage-1 growth g*, reverse_dcf_expectations_gap (same excess cash) returns g*. (b) neutral structure: price = _neutral_reference_dcf at g* plus the excess cash per share, the neutral solve returns g*. g* = the reference's year-1 growth, 5% where there is none. Both without the cash term are reported, not a bar.
The day is re-created from the file's own record (the same tree, data directories, date and closure artifact); sockets are blocked.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402
import desk_checks  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", required=True, type=Path)
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    meta, rows = ac.load_day(a.day)
    ns = ac.bootstrap_from_day(meta)
    result = desk_checks.round_trips(ns, rows)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

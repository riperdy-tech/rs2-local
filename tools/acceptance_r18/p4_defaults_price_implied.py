"""P4 (brief_rev19.md section 5, a bar): the book arithmetic of the DEFAULTS runs.

  python p4_defaults_price_implied.py --day <day.json from build_day.py> [--out <result.json>]

For every name with a printed reference and a DEFAULTS run, each of its six DEFAULTS price-implied values either reproduces the pack's price within $0.01
when substituted (unrounded), or is not reachable with its bound named; 0 errors. Names with no DEFAULTS run are counted with the reason. The day is
re-created from the file's own record (the same tree, data directories, date and closure artifact); sockets are blocked.
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
    result = desk_checks.defaults_price_implied(ns, rows)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

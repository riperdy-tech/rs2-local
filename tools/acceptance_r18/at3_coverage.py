"""AT3 (brief section 6): the share of book names with a printed reference is at least revision 16's share on the same day and data, minus 2 points.

  python at3_coverage.py --day <day.json from build_day.py> [--day16 <rev16 day.json>] [--out <result.json>]

Printed means status used or outside the fence (revision 16: a printed value). A name that did not build counts as having none.
Refused unless the revision 16 day was built on the same data as the day (date, history, TTM and MRI anchor hashes, data root, enrich records).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402
import at_rows  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", required=True, type=Path)
    ap.add_argument("--day16", required=True, type=Path, help="build_day.py run with revision 16's tree (fee17cf) on the same day and data")
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    ac.block_network()
    meta, rows = ac.load_day(a.day)
    m16, rows16 = ac.load_day(a.day16)
    ac.require_same_data(m16, rows16, meta, rows)                # finding 5: revision 16's day on other data is no baseline
    result = at_rows.at3(rows, rows16)
    result["day16_file_sha256"] = ac.sha256_file(a.day16)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

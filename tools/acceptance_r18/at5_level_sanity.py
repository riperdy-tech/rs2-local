"""AT5 (brief section 6): the book's median V/P lies in [0.70, 1.45] and at most 10% of names lie above 3x or below 1/3x their price.

  python at5_level_sanity.py --day <day.json from build_day.py> [] [--out <result.json>]

A gross-error detector, not a calibration claim. Over the names with a printed reference and a price.
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
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    ac.block_network()
    meta, rows = ac.load_day(a.day)
    result = at_rows.at5(rows)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

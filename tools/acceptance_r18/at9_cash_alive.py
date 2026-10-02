"""AT9 (amendment 1): among non-financial book names with a printed reference and a filed cash figure, the cash term applies to at least 90%.

  python at9_cash_alive.py --day <day.json from build_day.py> [] [--out <result.json>]

Unknown fiscal year ends and missing bill rates count against it and are reported by stamp.
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
    result = at_rows.at9(rows)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

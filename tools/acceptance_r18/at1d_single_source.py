"""AT1d (brief section 6): the pack's printed reference = build(**reference_inputs(...)) to the cent for every book name.

  python at1d_single_source.py --day <day.json from build_day.py> [] [--out <result.json>]

The independent call is build_day's (a fresh DataRoot, the files read again, the ledger's production wiring).
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
    result = at_rows.at1d(rows)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

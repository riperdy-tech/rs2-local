"""AT5' (brief_rev19.md 10b, the operator's restatement of AT5; post-hoc, recorded as such): the book's median V/P lies in [0.70, 1.45], the share above 3x
or below 1/3x is reported with its census and not marked, and the reviewer's gross-error read binds.

  python at5_level_sanity.py --day <day.json from build_day.py> [--gross-error-read <read.json> [--read-sha256 <sha256 or a prefix of 8+>]] [--out <result.json>]

A gross-error detector, not a calibration claim. Over the names with a printed reference and a price. The read is the reviewer's file (a hashed input: its
sha256 is recorded in the result and, with --read-sha256, must match). Revision 20 (brief_input_scope_fixes.md 9.3-9.4), version 2: {"at": "AT5
gross-error read", "version": 2, "day_file_sha256": <this day file's>, "tree_commit": <the day's meta.inputs.tree_commit>, "reviewer", "written_at",
"reads": {<row key>: {"unit_or_scale_error": true|false, "input_scope_error": true|false, "input_scope_category"?: nci|customer_money|
vendor_revenue_basis|other, "basis": "<the numbers>"}}, "notes"?}, one entry for EVERY extreme. Without it, without every such entry, or with a duplicate,
unknown or out-of-day key, the result is PENDING (exit 1, never a pass); an entry marking either error FAILS. No ticker is written to the result.
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
    ap.add_argument("--gross-error-read", default=None, type=Path)
    ap.add_argument("--read-sha256", default=None)
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    ac.block_network()
    meta, rows = ac.load_day(a.day)
    read = read_sha = None
    dups = []
    if a.gross_error_read is not None:
        raw = Path(a.gross_error_read).read_bytes()
        read_sha = ac.sha256_file(a.gross_error_read)
        if a.read_sha256 is not None:
            want = str(a.read_sha256).strip().lower()
            if len(want) < 8 or not read_sha.startswith(want):
                print("refused: the gross-error read's sha256 differs from the expected value; it is not used", file=sys.stderr)
                return 2
        read, dups = at_rows.parse_read(raw)
        if read is None:
            read = {}
    elif a.read_sha256 is not None:
        print("refused: --read-sha256 names a read but no --gross-error-read was given", file=sys.stderr)
        return 2
    day_sha = ac.sha256_file(a.day)
    result = at_rows.at5(rows, read=read, read_sha256=read_sha, day_sha256=day_sha, tree_commit=((meta or {}).get("inputs") or {}).get("tree_commit"),
                         read_duplicates=dups)
    result["day_file_sha256"] = day_sha
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

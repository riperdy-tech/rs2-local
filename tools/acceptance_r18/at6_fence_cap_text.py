"""AT6 (brief section 6, restated for revision 19, brief_rev19.md section 13, and for revision 20, brief_input_scope_fixes.md section 10): every outside-fence reference prints its value and flag; no base_year_capped stamp anywhere; the anchor-role sentence is in every printed reference line; the TASK's item 6 is present and the Level-anchor bullet is gone; every pack's DEFAULTS has the price_implied line; PACK_REVISION is 20 and FACTS_VERSION is 8.

  python at6_fence_cap_text.py --day <day.json from build_day.py> [] [--out <result.json>]

The constants (PACK_REVISION, FACTS_VERSION, ANCHOR_ROLE, TASK) are those build_day recorded from the tree under test.
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
    result = at_rows.at6(rows, meta["constants"])
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

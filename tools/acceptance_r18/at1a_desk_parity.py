"""AT1a (brief section 6, amendment 1 point 3): desk = reference to the cent on default inputs for every book name with a printed reference.

  python at1a_desk_parity.py --day <day.json from build_day.py> [--out <result.json>]

The desk is run on the facts the pack prints (parsed back from the DEFAULTS block) with the reference's own base and growth path at full precision; |desk - reference| < $0.005 on UNROUNDED values. Cash-only references are excluded and counted; any other name the desk cannot run is listed with the reason.
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
    result = desk_checks.desk_parity(ns, rows)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

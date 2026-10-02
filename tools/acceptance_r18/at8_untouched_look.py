"""AT8 (brief section 6, amendment 2 point 4): THE ONE LOOK at the 167 untouched names. It runs once, last, on the configuration AT1-AT7 and AT9
passed on, and never again. Counts only: no name is printed, logged, written or put in an error message.

  python at8_untouched_look.py --tree <final commit> --root <data root with enrich/ for the 167> --sd <history dir> --mri <anchors dir>
        --date YYYY-MM-DD --untouched-list <untouched167.txt> --untouched-sha256 <hex prefix, 8+ chars> --closure <artifact>
        --preconditions <acceptance.json> --lock <path of the lock file> --confirm-one-look --out <result.json>

Refuses (before it reads a single name) unless: --confirm-one-look is given; the list's sha256 matches; the preconditions file records AT1a, AT1b,
AT1c, AT1d, AT1e, AT2, AT3, AT4, AT5, AT6, AT7 and AT9 as passed on the SAME configuration (tree commit, history sha256, closure sha256, date,
MRI anchor hashes) as this run; and the lock file does not exist. The lock file is created (exclusively) before anything is built, so a look
that stops on an integrity item is still the one look: "if an integrity item fails, stop and report; there is no second look".

Pass / fail (the bars): AT1a, AT1d and AT4 on the 167. Report only: coverage, the share below 0.9x price, the median V/P, the count outside the
fence. The pack text and the rows are held in memory and never written.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402
import at_rows  # noqa: E402
import desk_checks  # noqa: E402

REQUIRED = ("AT1a", "AT1b", "AT1c", "AT1d", "AT1e", "AT2", "AT3", "AT4", "AT5", "AT6", "AT7", "AT9")
CONFIG_KEYS = ("tree_commit", "history_sha256", "closure_sha256", "date", "mri_anchor_sha256")


def configuration_of(inputs):
    """The configuration a day is stated by: the keys of `inputs_record` that make one run the same configuration as another."""
    return {k: inputs.get(k) for k in CONFIG_KEYS}


def check_preconditions(doc, config):
    """Problems (a list of strings; empty when the look may run). `doc`: {"configuration": {...}, "results": {"AT1a": true, ...}}."""
    problems = []
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), dict) or not isinstance(doc.get("configuration"), dict):
        return ["the preconditions file is not {configuration, results}"]
    for at in REQUIRED:
        if doc["results"].get(at) is not True:
            problems.append(f"{at} is not recorded as passed")
    for k in CONFIG_KEYS:
        if doc["configuration"].get(k) is None or doc["configuration"].get(k) != config.get(k):
            problems.append(f"the configuration differs from the one the ATs passed on: {k}")
    return problems


def take_lock(path):
    """Create the lock exclusively. Raises FileExistsError when the look has already run (or started)."""
    with open(path, "x", encoding="utf-8") as f:
        f.write("the one look at the untouched names was taken; it is never repeated\n")


def look(ns, rows):
    """The look's result from the rows in memory (counts only). Pass = AT1a, AT1d and AT4; the rest is reported."""
    a1a = desk_checks.desk_parity(ns, rows, names=False)
    a1d = at_rows.at1d(rows, names=False)
    a4 = at_rows.at4(rows, names=False)
    return summarize(rows, a1a, a1d, a4)


def summarize(rows, a1a, a1d, a4):
    built = {k: r for k, r in rows.items() if r.get("error") is None}
    printed = [r for r in built.values() if r.get("status") in at_rows.PRINTED]
    vps = [r["printed_value"] / r["price"] for r in printed if r.get("printed_value") is not None and isinstance(r.get("price"), (int, float)) and r["price"] > 0]
    ok = bool(a1a["pass"] and a1d["pass"] and a4["pass"])
    report_only = {"names": len(rows), "built": len(built), "build_errors": len(rows) - len(built),
                   "with_a_printed_reference": len(printed), "coverage": (len(printed) / len(rows)) if rows else None,
                   "share_below_0.9x_price": (sum(1 for v in vps if v < 0.9) / len(vps)) if vps else None,
                   "median_vp": statistics.median(vps) if vps else None,
                   "outside_the_fence": sum(1 for r in printed if r["status"] != "used")}
    return {"at": "AT8 the look at the untouched names", "pass": ok, "bars": {"AT1a": a1a, "AT1d": a1d, "AT4": a4}, "report_only": report_only,
            "summary": f"AT1a {'pass' if a1a['pass'] else 'FAIL'}, AT1d {'pass' if a1d['pass'] else 'FAIL'}, AT4 {'pass' if a4['pass'] else 'FAIL'}; "
                       f"coverage {report_only['coverage']}, below 0.9x {report_only['share_below_0.9x_price']}, median V/P {report_only['median_vp']}, "
                       f"outside the fence {report_only['outside_the_fence']}"}


def main(argv=None, build_rows=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("tree", "root", "sd", "mri", "untouched-list", "preconditions", "lock", "out", "closure"):
        ap.add_argument("--" + name, type=Path, required=name != "closure")
    ap.add_argument("--date", required=True)
    ap.add_argument("--untouched-sha256", required=True)
    ap.add_argument("--confirm-one-look", action="store_true")
    a = ap.parse_args(argv)
    if not a.confirm_one_look:
        print("refused: the look needs --confirm-one-look (it runs once and never again)", file=sys.stderr)
        return 2
    try:
        names = ac.load_names(a.untouched_list, a.untouched_sha256)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if a.lock.exists():
        print("refused: the look has already been taken (the lock file exists); it is never repeated", file=sys.stderr)
        return 2
    ns = ac.bootstrap(a.tree, a.sd, a.mri, a.root, a.date, closure=a.closure)
    config = configuration_of(ac.inputs_record(ns))
    import json
    problems = check_preconditions(json.loads(a.preconditions.read_text(encoding="utf-8")), config)
    if problems:
        print("refused: " + "; ".join(problems), file=sys.stderr)
        return 2
    try:
        take_lock(a.lock)
    except FileExistsError:
        print("refused: the look has already been taken (the lock file exists); it is never repeated", file=sys.stderr)
        return 2
    if build_rows is None:
        import build_day
        build_rows = build_day.build_rows
    rows, meta = build_rows(ns, names, keep_text=True, anonymous=True, progress=True, enrich_label="untouched")
    result = look(ns, rows)
    result["counts"] = {"names": len(names), "build_errors_by_class": meta["errors_by_class"], "enrich_by_source": meta["enrich_by_source"],
                        "enrich_age_days_max": meta["enrich_age_days_max"], "enrich_older_than_45_days": meta["enrich_age_days_over_45"]}
    result["configuration"] = config
    result["list_sha256"] = ac.sha256_file(a.untouched_list)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

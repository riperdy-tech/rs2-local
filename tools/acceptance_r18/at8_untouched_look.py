"""AT8 (brief section 6, amendment 2 point 4): THE ONE LOOK at the 167 untouched names. It runs once, last, on the configuration AT1-AT7 and AT9
passed on, and never again. Counts only: no name is printed, logged, written or put in an error message.

  python at8_untouched_look.py --tree <final commit> --root <data root with enrich/ for the 167> --sd <history dir> --mri <anchors dir>
        --date YYYY-MM-DD --untouched-list <untouched167.txt> --untouched-sha256 <hex prefix, 8+ chars> --closure <artifact>
        --results <folder holding the AT result files> --day <the book's day file> --confirm-one-look --out <result.json>

Refuses (before it reads a single name) unless: --confirm-one-look is given; the list's sha256 matches; the lock file (LOCK_PATH, one fixed path
that no argument changes) does not exist; and the AT RESULT FILES in --results (each written by its own script: AT1a, AT1b, AT1c, AT1d, AT1e,
AT2, AT3, AT4, AT5, AT6, AT7, AT9 and P4, exactly one each) record `pass: true` and were run on the SAME configuration as this run. Nothing is
typed in: the configuration is the one the book's day file (--day) records, and each result file must name that day file's sha256 (or, AT1c,
AT1b's revision 18 tree, AT7, AT2, the tree commit / the history and artifact hashes) - and it must equal this run's: tree commit, a CLEAN
tree, history sha256, closure sha256, date, MRI anchor hashes and the bill-rate store's sha256.
Then, still before the lock: the 167's enrich records must all be present, none an error record, every one dated and at most 45 days old
on the date (counts only). The lock file is created (exclusively) before anything is built, so a look that stops on an integrity item after
that is still the one look: "if an integrity item fails, stop and report; there is no second look". The result's `configuration` adds the
digests of the enrich records (their count and the sha256 of their sorted sha256s).

Pass / fail (the bars): AT1a, AT1d and AT4 on the 167, and (revision 19, brief H) P4 on the 167's DEFAULTS runs: each DEFAULTS price-implied value
reproduces the pack's price within $0.01 when substituted, or is not reachable with its bound named. Report only: coverage, the share below 0.9x
price, the median V/P, the count outside the fence; these level figures are labelled "second look, not independent (first look: the 2026-10-02 gap
measurement)": the 2026-10-02 gap measurement saw the level of these names first, so this look repeats it and does not test it afresh.
The pack text and the rows are held in memory and never written.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402
import at_rows  # noqa: E402
import desk_checks  # noqa: E402

REQUIRED = ("AT1a", "AT1b", "AT1c", "AT1d", "AT1e", "AT2", "AT3", "AT4", "AT5", "AT6", "AT7", "AT9", "P4")
DAY_BASED = ("AT1a", "AT1b", "AT1d", "AT1e", "AT3", "AT4", "AT5", "AT6", "AT9", "P4")   # their result files name the day file they ran on
# revision 19 (brief H): what the look's level figures are, said on the figures themselves
SECOND_LOOK_LABEL = "second look, not independent (first look: the 2026-10-02 gap measurement)"
CONFIG_KEYS = ("tree_commit", "tree_clean", "history_sha256", "closure_sha256", "date", "mri_anchor_sha256", "bill_rate_sha256")
# THE lock: one fixed path, in no repository and no argument. A different path would allow a second look.
LOCK_PATH = Path.home() / ".rs2_acceptance" / "rev18_at8_one_look.lock"


def configuration_of(inputs):
    """The configuration a day is stated by: the keys of `inputs_record` that make one run the same configuration as another."""
    return {k: inputs.get(k) for k in CONFIG_KEYS}


def load_at_results(folder):
    """({"AT1a": result, ...}, problems) from the *.json files in `folder`: a file is an AT result when it holds an "at" label; the key is the
    label's first word. A file that is no AT result (the day file, say) is ignored; a required AT recorded twice is a problem."""
    out, problems = {}, []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append("a file in the results folder is not readable JSON")
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("at"), str):
            continue
        key = doc["at"].split()[0] if doc["at"].split() else ""
        if key not in REQUIRED:
            continue
        if key in out:
            problems.append(f"{key} is recorded more than once in the results folder")
        out[key] = doc
    return out, problems


def check_preconditions(results, day_meta, day_sha256, config):
    """Problems (a list of strings; empty when the look may run). `results`: {"AT1a": the result file's dict, ...}; `day_meta`: the book day
    file's meta; `day_sha256`: that file's sha256; `config`: this run's configuration (`configuration_of`)."""
    problems = []
    if not isinstance(results, dict) or not isinstance(day_meta, dict):
        return ["the results or the day file are not in the form the scripts write"]
    for at in REQUIRED:
        r = results.get(at)
        if not isinstance(r, dict):
            problems.append(f"{at} has no result file")
        elif r.get("pass") is not True:
            problems.append(f"{at} is not recorded as passed")
    day_config = configuration_of(day_meta.get("inputs") or {})
    for k in CONFIG_KEYS:
        if day_config.get(k) is None or day_config.get(k) != config.get(k):
            problems.append(f"the configuration differs from the one the ATs passed on: {k}")
    if config.get("tree_clean") is not True or day_config.get("tree_clean") is not True:
        problems.append("the tree is not clean (uncommitted changes): the look runs on a committed configuration only")
    for at in DAY_BASED:
        r = results.get(at)
        if isinstance(r, dict) and r.get("day_file_sha256") != day_sha256:
            problems.append(f"{at} was not run on the day file given")
    commit = config.get("tree_commit")
    checks = (("AT1b", ((results.get("AT1b") or {}).get("trees") or {}).get("rev18", {}).get("commit")),
              ("AT1c", (results.get("AT1c") or {}).get("tree_commit")),
              ("AT7", (((results.get("AT7") or {}).get("runs") or [{}])[0] or {}).get("commit")))
    for at, got in checks:
        if isinstance(results.get(at), dict) and (commit is None or got != commit):
            problems.append(f"{at} was not run on this tree commit")
    at2 = results.get("AT2")
    if isinstance(at2, dict) and (at2.get("history_sha256") != config.get("history_sha256") or at2.get("artifact_sha256") != config.get("closure_sha256")):
        problems.append("AT2 was not run on this history and closure artifact")
    return problems


def enrich_precheck(ns, names):
    """F14, counts only: are the names' enrich records present, no error record, dated and at most 45 days old on the day? Plus their digests
    (the count and the sha256 of the sorted per-record sha256s: nothing that names a ticker)."""
    entries = [ac.enrich_entry(ns.root, t, ns.fixed, ns.rs2) for t in names]
    chk = ac.enrich_check(entries)
    shas = sorted(e["sha256"] for e in entries if e["sha256"])
    chk["digests"] = {"records": len(shas), "sha256_of_sorted_record_sha256": ac.sha256_text("\n".join(shas))}
    return chk


def take_lock(path=None):
    """Create the lock exclusively (LOCK_PATH unless a test names another). Raises FileExistsError when the look has already run (or started)."""
    path = Path(LOCK_PATH if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write("the one look at the untouched names was taken; it is never repeated\n")


def look(ns, rows):
    """The look's result from the rows in memory (counts only). Pass = AT1a, AT1d, AT4 and P4; the rest is reported."""
    a1a = desk_checks.desk_parity(ns, rows, names=False)
    a1d = at_rows.at1d(rows, names=False)
    a4 = at_rows.at4(rows, names=False)
    p4 = desk_checks.defaults_price_implied(ns, rows, names=False)
    return summarize(rows, a1a, a1d, a4, p4)


def summarize(rows, a1a, a1d, a4, p4):
    built = {k: r for k, r in rows.items() if r.get("error") is None}
    printed = [r for r in built.values() if r.get("status") in at_rows.PRINTED]
    vps = [r["printed_value"] / r["price"] for r in printed if r.get("printed_value") is not None and isinstance(r.get("price"), (int, float)) and r["price"] > 0]
    ok = bool(a1a["pass"] and a1d["pass"] and a4["pass"] and p4["pass"])
    report_only = {"label": SECOND_LOOK_LABEL, "names": len(rows), "built": len(built), "build_errors": len(rows) - len(built),
                   "with_a_printed_reference": len(printed), "coverage": (len(printed) / len(rows)) if rows else None,
                   "share_below_0.9x_price": (sum(1 for v in vps if v < 0.9) / len(vps)) if vps else None,
                   "median_vp": statistics.median(vps) if vps else None,
                   "outside_the_fence": sum(1 for r in printed if r["status"] != "used")}
    return {"at": "AT8 the look at the untouched names", "pass": ok, "bars": {"AT1a": a1a, "AT1d": a1d, "AT4": a4, "P4": p4}, "report_only": report_only,
            "summary": f"AT1a {'pass' if a1a['pass'] else 'FAIL'}, AT1d {'pass' if a1d['pass'] else 'FAIL'}, AT4 {'pass' if a4['pass'] else 'FAIL'}, "
                       f"P4 {'pass' if p4['pass'] else 'FAIL'}; level figures ({SECOND_LOOK_LABEL}): coverage {report_only['coverage']}, "
                       f"below 0.9x {report_only['share_below_0.9x_price']}, median V/P {report_only['median_vp']}, "
                       f"outside the fence {report_only['outside_the_fence']}"}


def main(argv=None, build_rows=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("tree", "root", "sd", "mri", "untouched-list", "results", "day", "out", "closure"):
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
    if Path(LOCK_PATH).exists():
        print("refused: the look has already been taken (the lock file exists); it is never repeated", file=sys.stderr)
        return 2
    results, problems = load_at_results(a.results)
    day_meta, _day_rows = ac.load_day(a.day)
    ns = ac.bootstrap(a.tree, a.sd, a.mri, a.root, a.date, closure=a.closure)
    config = configuration_of(ac.inputs_record(ns))
    problems += check_preconditions(results, day_meta, ac.sha256_file(a.day), config)
    if problems:
        print("refused: " + "; ".join(problems), file=sys.stderr)
        return 2
    pre = enrich_precheck(ns, names)                                            # before the lock: a record that is not there is no look
    if not pre["pass"]:
        print(f"refused: the untouched names' enrich records are not all usable: {pre['ok']} of {pre['records']} ok; missing {pre['missing']}, "
              f"error records {pre['error_records']}, undated {pre['undated']}, older than {ac.ENRICH_MAX_AGE_DAYS} days "
              f"{pre['older_than_%d_days' % ac.ENRICH_MAX_AGE_DAYS]}", file=sys.stderr)
        return 2
    try:
        take_lock()
    except FileExistsError:
        print("refused: the look has already been taken (the lock file exists); it is never repeated", file=sys.stderr)
        return 2
    if build_rows is None:
        import build_day
        build_rows = build_day.build_rows
    rows, meta = build_rows(ns, names, keep_text=True, anonymous=True, progress=True, enrich_label="untouched")
    result = look(ns, rows)
    result["counts"] = {"names": len(names), "build_errors_by_class": meta["errors_by_class"], "enrich_by_source": meta["enrich_by_source"],
                        "enrich_age_days_max": meta["enrich_age_days_max"], "enrich_older_than_45_days": meta["enrich_age_days_over_45"],
                        "enrich_check": meta.get("enrich_check")}
    result["configuration"] = dict(config, enrich_digests=pre["digests"])
    result["list_sha256"] = ac.sha256_file(a.untouched_list)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

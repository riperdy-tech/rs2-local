"""AT2 (brief section 6, strengthened by amendment 2 point 1): the closure.

  python at2_closure.py --artifact <cache/reference_closure.json> --tree <rs2 final commit> --sd <the day's screener data dir (history)>
                        --mri <anchors dir> --root <data root> --date YYYY-MM-DD [--out <result.json>]
  (--aggregate-from-day <day.json> re-creates the day instead of the four paths above)

The bars, on the artifact:
  1. |sum(V x shares) - sum(cap)| / sum(cap) <= 1e-6                      6. the artifact's recorded input hash of fundamentals_history.json
  2. no bound flag                                                           equals the sha256 of the history file the day is on (it is
  3. members >= 300 and coverage >= 60% of the aggregate's capitalisation    the artifact "rebuilt on that history", amendment 2 point 1)
  4. the artifact is no older than 45 days on the acceptance day, and so is the consensus vintage it was solved on (`consensus_vintage.date`)
  5. (amendment 2) the history carries brief A's provenance marker for every name of the closure's aggregate (a superset of its members):
     0 may be missing. The aggregate is rebuilt here by the closure's own `build_aggregate` on the day's history.
Offline: every socket is blocked; nothing is written but the result.
"""
import argparse
import json
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402


def evaluate_artifact(doc, acceptance_day, history_sha256, missing_marker_count, aggregate_names, *, max_age_days=45):
    """The artifact-side bars as a pure function; `missing_marker_count` is the aggregate's names with no marker."""
    checks = []

    def chk(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
    gap, sum_cap = doc.get("gap"), doc.get("sum_cap")
    sv = doc.get("sum_value")
    recomputed = abs(sv - sum_cap) / sum_cap if (isinstance(sv, (int, float)) and isinstance(sum_cap, (int, float)) and sum_cap) else None
    chk("identity: |sum V x shares - sum cap| / sum cap <= 1e-6", recomputed is not None and recomputed <= 1e-6 and isinstance(gap, (int, float)) and gap <= 1e-6,
        f"recomputed {recomputed}, recorded gap {gap}")
    chk("no bound flag", doc.get("flag") is None, f"flag {doc.get('flag')}")
    members, cov = doc.get("members"), doc.get("coverage_share")
    chk("members >= 300 covering >= 60% of the aggregate's capitalisation", isinstance(members, int) and members >= 300 and isinstance(cov, (int, float)) and cov >= 0.60,
        f"members {members}, coverage {cov}")
    try:
        age = (acceptance_day - _date.fromisoformat(str(doc.get("asof"))[:10])).days
    except ValueError:
        age = None
    chk(f"artifact no older than {max_age_days} days on the acceptance day", age is not None and 0 <= age <= max_age_days, f"as of {doc.get('asof')}, {age} days old")
    cv = doc.get("consensus_vintage")
    try:
        vintage_age = (acceptance_day - _date.fromisoformat(str(cv.get("date") if isinstance(cv, dict) else None)[:10])).days
    except ValueError:
        vintage_age = None
    chk(f"consensus vintage no older than {max_age_days} days on the acceptance day", vintage_age is not None and 0 <= vintage_age <= max_age_days,
        f"vintage {cv.get('date') if isinstance(cv, dict) else None}, {vintage_age} days old")
    rec_hash = (doc.get("inputs_sha256") or {}).get("fundamentals_history.json")
    chk("the artifact was built on the history file of the day (sha256)", rec_hash is not None and rec_hash == history_sha256,
        f"artifact {str(rec_hash)[:12]}, day {str(history_sha256)[:12]}")
    chk("amendment 2: every name of the closure's aggregate carries brief A's marker (0 missing)", missing_marker_count == 0,
        f"{missing_marker_count} of {aggregate_names} aggregate names have no marker")
    chk("the artifact itself records 0 constituents without a marker", (doc.get("aggregate") or {}).get("constituents_without_marker") == 0,
        f"recorded {(doc.get('aggregate') or {}).get('constituents_without_marker')}")
    ok = all(c["pass"] for c in checks)
    return {"at": "AT2 closure", "pass": ok, "checks": checks, "summary": "; ".join(f"{'ok' if c['pass'] else 'FAIL'}: {c['check'].split(':')[0]}" for c in checks)}


def aggregate_marker_counts(ns):
    """(aggregate names, how many have no marker) on the day's history, through the closure's own build_aggregate."""
    import reference_closure as rc
    root = ns.cap.DataRoot()
    agg, _stats = rc.build_aggregate(root, ns.cap)
    cons = agg["constituents"]
    return len(cons), sum(1 for c in cons if root.untagged(c["ticker"]) is None)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", required=True, type=Path)
    ap.add_argument("--tree", type=Path)
    ap.add_argument("--sd", type=Path)
    ap.add_argument("--mri", type=Path)
    ap.add_argument("--root", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--aggregate-from-day", type=Path, default=None)
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    if a.aggregate_from_day:
        meta, _rows = ac.load_day(a.aggregate_from_day)
        ns = ac.bootstrap_from_day(meta)
    else:
        ns = ac.bootstrap(a.tree, a.sd, a.mri, a.root, a.date, closure=a.artifact)
    doc = json.loads(a.artifact.read_text(encoding="utf-8"))
    n_agg, missing = aggregate_marker_counts(ns)
    result = evaluate_artifact(doc, _date.fromisoformat(a.date), ac.sha256_file(Path(ns.sd) / "fundamentals_history.json"), missing, n_agg)
    result["artifact_sha256"] = ac.sha256_file(a.artifact)
    result["history_sha256"] = ac.sha256_file(Path(ns.sd) / "fundamentals_history.json")
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

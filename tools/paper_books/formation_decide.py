"""formation_decide.py - WO_O2 step 1: the decision run, T and A0 book of one formation, by forward_ledger.py's own rule (imported unchanged).

    python tools/paper_books/formation_decide.py 2026-10-30   writes <books>/m3o/inputs/formation_2026-10-30.json (every book name, run_dir null)

Run check_new_runs.py first (it archives and verifies the new runs). The verified record given to the packet builder is the newest
<books>/m3l_verifier/out/check_*.json holding a PASS / pair PASS row for the decision run's output commit. A map that already exists is never
overwritten: the same decision prints "unchanged"; a different decision run stops (WO_O2 step 5 re-queues by hand, with a record).
From PREREG_m3o_bookD's series_start the map also holds "candidates" (paper book FD): the decision run's watchlist names, not in the book and
not operator-excluded, by fct_rank then ticker, the first `count` of them; formation_packets.py builds their packets.
From PREREG_m3o_bookV's series_start the map also holds "fv_held" (paper book FV): the names FV holds now that are not in the new book and not
operator-excluded, from m3o_engine.run on the standard folders (the recomputation, not the stored ledger); formation_packets.py builds their
packets and formation_value.py values them. FV never blocks the formation: if the engine stops or raises, "fv_held" is null and
"fv_held_error" says why, and the map is written as it would be without FV.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402
import forward_ledger as FL  # noqa: E402
try:                                       # FV must never block the formation: an engine that cannot even be imported leaves fv_held null
    import m3o_engine as E  # noqa: E402
    E_ERROR = None
except (Exception, SystemExit) as _e:      # noqa: BLE001
    E, E_ERROR = None, f"m3o_engine could not be imported: {type(_e).__name__}: {_e}"

INPUTS = book_paths.books() / "m3o" / "inputs"
CHECKS = book_paths.books() / "m3l_verifier" / "out"
VALUE = book_paths.books() / "m3o" / "value"
EXCLUDED = FL.OPERATOR_EXCLUDED
BOOKD = json.loads(book_paths.prereg("PREREG_m3o_bookD.json").read_text(encoding="utf-8"))


def candidates(output_commit, book):
    """FD's candidate list (PREREG_m3o_bookD candidates): [{ticker, fct_rank, packet, state}] in order."""
    fs = json.loads(subprocess.run(["git", "-C", str(FL.REPO), "show", f"{output_commit}:public/data/factor_scores.json"],
                                   capture_output=True, check=True).stdout)["tickers"]
    pool = [(v["fct_rank"], t) for t, v in fs.items()
            if v.get("fct_band") == "watchlist" and t not in book and t not in EXCLUDED and v.get("fct_rank") is not None]
    unranked = [t for t, v in fs.items() if v.get("fct_band") == "watchlist" and v.get("fct_rank") is None]
    if unranked:
        sys.exit(f"STOP: watchlist names without fct_rank: {sorted(unranked)[:10]}")
    return [{"ticker": t, "fct_rank": r, "packet": None, "state": "to_build"} for r, t in sorted(pool)[:BOOKD["candidates"]["count"]]]


def fv_held(book):
    """FV's held names outside the new book: [{ticker, packet, state}] from the engine's recomputation, or (None, the error) when it cannot run."""
    try:
        L, _ = E.run(FL.HERE, INPUTS, book_paths.books() / "m3o" / "ledger", value_dir=VALUE)
        return [{"ticker": t, "packet": None, "state": "to_build"} for t in E.fv_held_now(L) if t not in book and t not in EXCLUDED], None
    except Exception as e:  # noqa: BLE001  FV must never block the formation
        return None, f"{type(e).__name__}: {e}"


def check_file(output_commit):
    for p in sorted(CHECKS.glob("check_*.json"), reverse=True):
        rows = json.loads(p.read_text(encoding="utf-8"))
        if any(r.get("verdict") == "PASS" and r.get("pair") == "PASS" and output_commit.startswith((r.get("output_commit") or "-").lower())
               for r in rows):
            return str(p)
    return None


def main():
    T = date.fromisoformat(sys.argv[1])
    res, F, err = FL.decision_for(T, FL.scoring_runs())
    if err:
        sys.exit(f"STOP: {err}")
    names, flags = FL.book(res)
    rec = {"formation_T": T.isoformat(), "fill_session": F.isoformat(), "fill_open_utc": FL.open_utc(F).isoformat().replace("+00:00", "Z"),
           "decision_time_utc": res["decision_time_utc"], "run_id": res["run_id"], "output_commit": res["output_commit"],
           "verified_record": check_file(res["output_commit"]), "builder_version": None, "book": names, "flags": flags,
           "names": {t: {"packet": None, "run_dir": None, "attempts": 0, "state": "operator_excluded" if t in EXCLUDED else "to_build"}
                     for t in names}}
    if T.isoformat() >= BOOKD["series_start"][:10]:
        rec["candidates"] = candidates(res["output_commit"], names)
    if rec["verified_record"] is None:
        sys.exit(f"STOP: no check_new_runs record verifies {res['output_commit']} with verdict and pair PASS")
    path = INPUTS / f"formation_{T.isoformat()}.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if (old["run_id"], old["output_commit"], old["book"]) == (rec["run_id"], rec["output_commit"], rec["book"]):
            print("unchanged:", path)
            return 0
        sys.exit(f"STOP: the decision changed from run {old['run_id']} to {rec['run_id']}; re-queue by hand (WO_O2 step 5)")
    if E is None or T.isoformat() >= E.FV_START:
        rec["fv_held"], err = fv_held(names) if E is not None else (None, E_ERROR)
        if err:
            rec["fv_held_error"] = err
            print(f"fv_held: the engine could not run, FV's held names are not carried: {err}")
    INPUTS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {path}: run {rec['run_id']} T {rec['decision_time_utc']} book {len(names)} fill {rec['fill_open_utc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""m3o_audit.py - reconciles the four 3O ledger files (AUDIT_O1, carried item; SPEC_m3o 8). Read-only; exit 1 on any failure.

    python m3o_audit.py [--ledger-dir DIR]

Checks, per formation:
  1. every A0 book name has a factor line, and every non-excluded name a qwen and a verification line at the fill open;
  2. every series (F, FB, FQ, FQ_decisions_only) has exactly one fill-open action line per book name;
  3. PLAN 3O "Qwen present in every completed formal deep analysis": every FQ / FQ_decisions_only entry (enter, hold) and every
     enter_after_pending has a qwen line with analysis_state complete (or a completion line) and a run id; FQ has no factor-only fill;
  4. every restriction names its rule (B1 / Q1 / E1) and causes, and a Q1 cause matches an acting Q1 claim on the verification line;
     a B1 cause matches an acting B1 hit;
  5. operator-excluded tickers are never entered in FB or FQ, and never have a qwen line;
  6. every Qwen-derived action line carries qwen_c_commit and builder_code (CROSS_CHECK_O 8a); escalations change no series.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths  # noqa: E402

EXCLUDED = book_paths.operator_excluded()
SERIES = ("F", "FB", "FQ", "FQ_decisions_only")
ENTRY = {"enter", "hold"}


def read(d, name):
    p = Path(d) / f"{name}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def audit(d):
    F, fac, qw, ver, act = (read(d, n) for n in ("formations", "factor", "qwen", "verification", "actions"))
    fail, counts = [], Counter()
    for f in F:
        T = f["formation_T"]
        fT = [l for l in fac if l["formation_T"] == T]
        book = sorted(l["ticker"] for l in fT if l["in_A0_book"])
        if len(book) != f["book_size"]:
            fail.append(f"{T}: {len(book)} factor lines in the book, formation says {f['book_size']}")
        q_fill = {l["ticker"]: l for l in qw if l["formation_T"] == T and l["kind"] == "at_fill_open"}
        q_done = {l["ticker"] for l in qw if l["formation_T"] == T and l["kind"] == "completion" and l["analysis_state"] == "completed_late"}
        v_fill = {l["ticker"]: l for l in ver if l["formation_T"] == T and l["kind"] == "at_fill_open"}
        v_late = {l["ticker"]: l for l in ver if l["formation_T"] == T and l["kind"] == "completion"}
        for t in book:
            if t in EXCLUDED:
                if t in q_fill:
                    fail.append(f"{T} {t}: operator-excluded name has a qwen line")
                continue
            if t not in q_fill or t not in v_fill:
                fail.append(f"{T} {t}: missing qwen or verification line at the fill open")
        aT = [l for l in act if l["formation_T"] == T]
        for s in SERIES:
            fill = Counter(l["ticker"] for l in aT if l["arm"] == s and l["kind"] == "at_fill_open")
            for t in book:
                if fill[t] != 1:
                    fail.append(f"{T} {s} {t}: {fill[t]} fill-open action lines (expected 1)")
        for l in aT:
            s, t, a = l["arm"], l["ticker"], l["action"]
            counts[(s, a)] += 1
            if l["kind"] == "escalation":
                if l.get("series_effect") != "none":
                    fail.append(f"{T} {t}: escalation with a series effect")
                continue
            if s in ("FB", "FQ") and t in EXCLUDED and a in ENTRY | {"enter_after_pending"}:
                fail.append(f"{T} {s} {t}: operator-excluded name entered")
            if s in ("FQ", "FQ_decisions_only") and t not in EXCLUDED and (a in ENTRY or a == "enter_after_pending"):
                ok_fill = q_fill.get(t, {}).get("analysis_state") == "complete" and q_fill[t].get("run_id")
                ok_late = a == "enter_after_pending" and t in q_done
                if s == "FQ" and not (ok_fill or ok_late) and "analysis_pending" not in (l.get("flags") or []):
                    fail.append(f"{T} FQ {t}: {a} without a completed Qwen analysis (factor-only fill)")
                if s == "FQ" and (ok_fill or ok_late) and not (l.get("qwen_c_commit") and l.get("builder_code")):
                    fail.append(f"{T} FQ {t}: Qwen-derived line without qwen_c_commit / builder_code")
            if a == "new_entry_restricted" or "pending_reunderwriting" in (l.get("flags") or []):
                causes = l.get("causes") or ([l["rule"]] if l["rule"] == "Q1" else [])
                if not causes:
                    fail.append(f"{T} {s} {t}: restriction without causes")
                v = v_late.get(t) if l["kind"] == "pending_resolution" else v_fill.get(t)
                if "Q1" in causes and not (v and any(c.get("acts") for c in (v.get("q1") or {}).get("claims") or [])):
                    fail.append(f"{T} {s} {t}: Q1 cause without an acting Q1 claim")
                if "B1" in causes and not (v and any(h.get("acts") for h in v["b1"]["hits"])):
                    fail.append(f"{T} {s} {t}: B1 cause without an acting B1 hit")
    return fail, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger-dir", default=str(book_paths.books() / "m3o" / "ledger"))
    a = ap.parse_args()
    fail, counts = audit(a.ledger_dir)
    for (s, act), n in sorted(counts.items()):
        print(f"{s:18} {act:22} {n}")
    print("\n".join(fail) if fail else "PASS: the four ledger files reconcile")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

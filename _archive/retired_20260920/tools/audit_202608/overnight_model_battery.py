#!/usr/bin/env python3
"""overnight_model_battery.py — pick the depth-tier model, unattended, against a deadline.

Operator brief (2026-08-24, 00:00): test the candidates, narrow to two, spend the remaining time
testing those two as hard as possible, conclusive answer by 07:30.

THE CANDIDATES, and why the field is what it is. Every Qwen3.8 quant carries the MTP head in the
blob (`qwen35.nextn_predict_layers = 1`, `nextn.*` tensors), so MTP is NOT a quantization
tradeoff - it is one parameter, `draft_num_predict`. That collapses the field to:
    q5      rs2-analyst-deep        Q5 UD, no draft      (INCUMBENT)
    q5+mtp  rs2-analyst-deep-mtp5   Q5 UD, draft 4
    q4      rs2-analyst-deep-q4     Q4,    no draft
    q4+mtp  rs2-analyst-deep-mtp    Q4,    draft 4

PHASES
  1 SCREEN   one name on any arm lacking a fresh measurement -> rank by ch/s at equal quality.
  2 BREADTH  the two finalists over several names, including a THIN-DATA name (2-year history
             stresses different behaviour than GOOG's 12).
  3 TUNE     draft_num_predict on the winner (2 / 4 / 6). Unsloth suggests 1-6; acceptance is
             hardware- and workload-dependent, so the shipped 4 is a default, not a finding.
  4 REPEAT   same name twice on the winner to size run-to-run scatter, so the headline speed
             number carries an error bar instead of pretending n=1 is precise.

DEADLINE IS HARD. Before every run the script checks whether the worst-case duration still fits;
if not it stops and writes what it has. A partial battery with an honest boundary beats a
complete one that was still running when the operator woke up.

Results stream to ab_reports/overnight_battery/results.jsonl after EVERY run, so a crash or a
kill loses at most one run.

  python tools/audit_202608/overnight_model_battery.py --deadline 07:15
"""
import io
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OUT = HERE / "ab_reports" / "overnight_battery"
CAP = HERE / "ab_reports" / "capability_test"
RESULTS = OUT / "results.jsonl"

# NARROWED BEFORE THE BATTERY RAN, by discovery rather than by burning GPU on it: every
# Qwen3.8 quant carries the MTP head, so Q5+MTP DOMINATES Q4+MTP - same draft head, better
# weights, and Q4 was separately measured 5% SLOWER than Q5. The Q4 arms are therefore dead
# branches and testing them would spend hours confirming a foregone conclusion.
# Both finalists are rebuilt from Modelfiles in the same way so their SYSTEM blocks are
# byte-identical; the incumbent tag rs2-analyst-deep bakes CRLF that ollama's Modelfile parser
# normalises to LF, a 463-character difference that would otherwise ride along as a confound.
ARMS = {
    "q5":     "rs2-deep-q5base",        # incumbent weights+prompt, no draft head
    "q5+mtp": "rs2-analyst-deep-mtp5",  # identical, plus draft_num_predict 4
}
# GOOG: contamination catch. PM: basis-change catch. CART: THIN data (few years) - a different
# stress, and the one the GOOG-only evidence cannot speak to.
# GOOG contamination catch | PM basis-change catch | CART + GRDN thin data |
# AVGO a name whose verdict already exists, as an independent sanity anchor.
NAMES = ["GOOG", "PM", "CART", "GRDN", "AVGO"]
CTX = 81920
WORST_CASE_MIN = 32          # slowest observed single capability run + margin

# Substance checks, reused from effort_ab (spaces -> whitespace class: reports hard-wrap).
CHECKS = {
    "GOOG": [("contamination", r"297\.9|non-?operating|one-?off|54\.8%|unusually high relative"),
             ("refuses to capitalise", r"not used as the primary DCF|not the primary.{0,30}base"
                                       r"|exclud\w+ from the (?:DCF|base)|normali[sz]\w+ (?:the )?"
                                       r"(?:earnings|base)"),
             ("P/E misleading", r"misleading|distorted by"),
             ("working capital", r"working capital|ΔWC|change in WC")],
    "PM":   [("basis change", r"reporting-?basis change|basis change|excise"),
             ("artifact not event", r"not a business event|rather than a business event"
                                    r"|presentation change|reclassif|different reporting basis"),
             ("post-2016 trend", r"(?:from|since|post-?)\s*(?:FY)?\s*2016")],
    "CART": [("states a value", r"intrinsic value|fair value|\bIV\b"),
             ("labels assumptions", r"\[Assumption\]|\[Estimate\]"),
             ("declares thin data", r"only \d+ (?:fiscal )?years?|limited history|short history"
                                    r"|thin (?:data|history)|two years|2 years|insufficient history")],
}
# GRDN and AVGO get CART's generic checks: state a value, label assumptions, and declare thin
# data when the history is short. GRDN holds 2 fiscal years, so "declares thin data" is a real
# discriminator there rather than a formality.
for _t in ("GRDN", "AVGO"):
    CHECKS[_t] = CHECKS["CART"]
# The test that caught medium inventing a number the pack hands over.
WC_FILED = re.compile(r"28[.,]7", re.I)


def log(m):
    print(f"[battery {datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def flex(p):
    return p.replace(" ", r"\s+")


def grade(d, ticker):
    rep = (d / "REPORT.md").read_text(encoding="utf-8", errors="replace")
    thp = d / "_thinking.md"
    th = thp.read_text(encoding="utf-8", errors="replace") if thp.exists() else ""
    both = rep + "\n" + th
    got = {lb: bool(re.search(flex(p), both, re.I)) for lb, p in CHECKS.get(ticker, [])}
    return got, len(rep), len(th), bool(WC_FILED.search(rep)) if ticker == "GOOG" else None


def run(arm, ticker, draft=None, tag=""):
    """One capability run. Returns a result dict, or None if it failed."""
    model = ARMS[arm] if draft is None else f"rs2-deep-draft{draft}"
    label = f"ob-{arm}{tag}" if draft is None else f"ob-draft{draft}"
    t0 = time.time()
    before = {p.name for p in CAP.glob(f"{ticker}_*")}
    r = subprocess.run([sys.executable, str(HERE / "tools" / "audit_202608" / "capability_test.py"),
                        ticker, "--model", model, "--think", "high", "--ctx", str(CTX),
                        "--label", label],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=WORST_CASE_MIN * 60 + 600)
    secs = round(time.time() - t0)
    new = [p for p in CAP.glob(f"{ticker}_*") if p.name not in before and (p / "REPORT.md").exists()]
    if not new:
        log(f"   {arm} {ticker}: FAILED — {(r.stderr or r.stdout or '')[-160:]}")
        return None
    d = max(new, key=lambda p: p.name)
    checks, rlen, tlen, wc = grade(d, ticker)
    res = {"arm": arm, "model": model, "ticker": ticker, "draft": draft, "secs": secs,
           "report_chars": rlen, "thinking_chars": tlen, "output_chars": rlen + tlen,
           "ch_per_s": round((rlen + tlen) / secs, 1),
           "checks": checks, "checks_passed": sum(checks.values()), "checks_total": len(checks),
           "used_filed_wc": wc, "dir": d.name,
           "at": datetime.now().isoformat(timespec="seconds")}
    OUT.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(res) + "\n")
    log(f"   {arm:7s} {ticker:5s} {secs:5d}s  {res['ch_per_s']:6.1f} ch/s  "
        f"checks {res['checks_passed']}/{res['checks_total']}"
        + (f"  filed-WC {'YES' if wc else 'NO'}" if wc is not None else ""))
    return res


def load_prior():
    """Runs already measured this session, so the battery does not repeat GPU time."""
    prior = []
    known = [("q5", "GOOG", 1374, 30486, 68838), ("q4", "GOOG", 1377, 28383, 66661),
             ("q4+mtp", "GOOG", 771, 48261, 44238)]
    for arm, t, s, r, th in known:
        prior.append({"arm": arm, "ticker": t, "secs": s, "report_chars": r,
                      "thinking_chars": th, "output_chars": r + th,
                      "ch_per_s": round((r + th) / s, 1), "source": "earlier this session"})
    return prior


def main():
    dl = sys.argv[sys.argv.index("--deadline") + 1] if "--deadline" in sys.argv else "07:15"
    hh, mm = (int(x) for x in dl.split(":"))
    deadline = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    if deadline < datetime.now():
        deadline += timedelta(days=1)
    log(f"deadline {deadline:%H:%M} — {(deadline - datetime.now()).total_seconds()/3600:.1f}h available")

    def time_left():
        return (deadline - datetime.now()).total_seconds() / 60

    def can_run(n=1):
        return time_left() > WORST_CASE_MIN * n + 10

    log("FINALISTS (fixed by discovery, not by screening): q5 vs q5+mtp")
    log("   MTP is a PARAMETER, not a quantization choice - every Qwen3.8 quant carries the")
    log("   nextn head. Q5+MTP therefore dominates Q4+MTP, and Q4 measured 5% slower than Q5.")
    finalists = ["q5", "q5+mtp"]

    # ---- PHASE 2: breadth on the finalists ---------------------------------------------------
    log("PHASE 2 — breadth: finalists across names incl. thin-data CART")
    for ticker in NAMES:
        for arm in finalists:
            if not can_run():
                log("   deadline guard: stopping breadth")
                break
            run(arm, ticker)

    # ---- PHASE 3: draft tuning on the leader -------------------------------------------------
    done = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines()] \
        if RESULTS.exists() else []
    by_arm = {}
    for r in done:
        by_arm.setdefault(r["arm"], []).append(r)
    leader = max(by_arm, key=lambda a: sum(x["ch_per_s"] for x in by_arm[a]) / len(by_arm[a])) \
        if by_arm else finalists[0]
    log(f"PHASE 3 — draft_num_predict tuning on {leader}")
    base_model = ARMS[leader]
    for n in (2, 6, 8):
        if not can_run():
            log("   deadline guard: skipping tuning")
            break
        mf = HERE / f"_tune_draft{n}.Modelfile"
        mf.write_text(f"FROM {base_model}\nPARAMETER draft_num_predict {n}\n", encoding="utf-8")
        c = subprocess.run(["ollama", "create", f"rs2-deep-draft{n}", "-f", str(mf)],
                           capture_output=True, text=True, timeout=1800)
        if c.returncode != 0:
            log(f"   draft{n} build failed: {(c.stderr or '')[-120:]}")
            continue
        run(leader, "GOOG", draft=n)
        mf.unlink(missing_ok=True)

    # ---- PHASE 4: repeatability on the leader ------------------------------------------------
    log(f"PHASE 4 — repeatability: second GOOG run on {leader} to size run-to-run scatter")
    if can_run():
        run(leader, "GOOG", tag="-rep")

    log(f"battery complete — {time_left():.0f} min to spare. results -> {RESULTS}")


if __name__ == "__main__":
    main()

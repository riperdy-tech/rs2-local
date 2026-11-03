"""b2_day.py - P6.7 acceptance B2 (PHASE_6_FOLLOWUP_RECALL.md, run 2): the prospective recall test's daily gather.

  python b2_day.py setup <commit>     once: a detached worktree of rs2-fix at <commit> (rs2-B2) whose ledger holds the
                                      newest production verdict of each of the 104 population names (recall/population.json),
                                      their consensus directories copied in (read-only source: production rs2-local)
  python b2_day.py                    one gather day: followup_gather.run with the population names as candidates, no
                                      price step, in batches of BATCH names with PAUSE_S between batches (the dry run of
                                      2026-10-02 asked SearXNG's Reuters engine ~315 times in 20 minutes and got it
                                      suspended; the batches keep the rate down - the gather of each name is the same).
                                      No GPU, no model. One line per batch to days.log.

Where things live (moved 2026-11-03 out of a Claude temp scratchpad, where the task could be cleaned away): this script in
rs2-local/tools/b2_recall; its data - the rs2-B2 worktree, recall/population.json and logs/ - in the `b2_recall_dir` of
paths.py (stocks-workspace/data/b2_recall), off this public repository. The frozen rs2-B2 tree runs the gather unchanged.

A starved day fails loudly (review 2026-11-03, D_screener_scratch.md B1a): SearXNG stayed down 11-01 to 11-03 and every batch
still logged "errors 0", because followup_gather counts only names that raised, not news queries that failed. Each batch is
now preceded and followed by a SearXNG probe, and the news queries that errored that day are counted from the tree's
cache/followup_news; any of these logs "FAILED" and the day exits 2. The gather itself still runs (the filings step needs no
SearXNG): annotate, never silently gate.

Everything writes only that tree's cache/: nothing reaches the live store. The reads come later (run at the end of the
window, on the inbox of each event's day, by a separate runner).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
import paths  # noqa: E402

DATA = str(paths.resolve("b2_recall_dir"))
TREE = os.path.join(DATA, "rs2-B2")
SOURCE = os.path.join(DATA, "rs2-fix")      # setup only; the 2026-10-02 setup used a worktree since retired
PROD = os.path.join(REPO, "ab_reports", "consensus")
POPULATION = os.path.join(DATA, "recall", "population.json")
LOGS = os.path.join(DATA, "logs")
DAYS_LOG = os.path.join(LOGS, "days.log")
PY = r"C:\Program Files\Python312\python.exe"
BATCH = 26
PAUSE_S = 600
PROBE_WAIT_S = 900                          # the first probe waits this long for the 05:40 docker window to bring SearXNG up


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(DAYS_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def tickers():
    return sorted(p["ticker"] for p in json.load(open(POPULATION, encoding="utf-8")))


def newest_dir(t):
    """The newest production consensus directory of `t` that has a verdict_depth.json."""
    best = None
    for d in os.listdir(PROD):
        if d.rsplit("_", 2)[0] == t and os.path.exists(os.path.join(PROD, d, "verdict_depth.json")):
            if best is None or d.rsplit("_", 2)[1:] > best.rsplit("_", 2)[1:]:
                best = d
    return best


def setup(commit):
    if os.path.exists(TREE):
        raise SystemExit(f"{TREE} exists; remove it first (git worktree remove) to set up again")
    subprocess.run(["git", "-C", SOURCE, "worktree", "add", "--detach", TREE, commit], check=True)
    cons = os.path.join(TREE, "ab_reports", "consensus")
    os.makedirs(cons, exist_ok=True)
    rows = []
    for t in tickers():
        d = newest_dir(t)
        if d is None:
            raise SystemExit(f"{t}: no production consensus directory with a verdict_depth.json")
        shutil.copytree(os.path.join(PROD, d), os.path.join(cons, d))
        v = json.load(open(os.path.join(PROD, d, "verdict_depth.json"), encoding="utf-8"))
        assert v["ticker"] == t and v["consensus_dir"] == d, (t, d)
        rows.append(v)
    os.makedirs(os.path.join(TREE, "cache"), exist_ok=True)
    with open(os.path.join(TREE, "cache", "depth_ledger.jsonl"), "w", encoding="utf-8") as fh:
        for r in sorted(rows, key=lambda r: (r["date"], r["ticker"])):
            fh.write(json.dumps(r) + "\n")
    json.dump({r["ticker"]: {"consensus_dir": r["consensus_dir"], "date": r["date"]} for r in rows},
              open(os.path.join(DATA, "ledger_index.json"), "w", encoding="utf-8"), indent=1)
    log(f"setup: {TREE} at {commit}; ledger = {len(rows)} verdicts (newest production per population name)")


def searxng_up():
    """True when the tree's searxng_url answers a JSON search with HTTP 200."""
    url = json.load(open(os.path.join(TREE, "config.json"), encoding="utf-8")).get("searxng_url")
    if not url:
        return False
    try:
        with urllib.request.urlopen(f"{url}/search?q=test&format=json", timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def news_query_errors(names, day):
    """(errored, asked): the news queries of `names` on UTC date `day` that recorded an error, from the tree's cache."""
    errored = asked = 0
    for t in names:
        path = os.path.join(TREE, "cache", "followup_news", t, f"{day}.json")
        try:
            queries = json.load(open(path, encoding="utf-8")).get("queries") or {}
        except (OSError, ValueError):
            continue
        for q in queries.values():
            asked += 1
            errored += bool(isinstance(q, dict) and q.get("error"))
    return errored, asked


def batch(names, wait_s=0):
    t0 = datetime.now(timezone.utc)
    deadline = time.time() + wait_s
    up_before = searxng_up()
    while not up_before and time.time() < deadline:
        time.sleep(30)
        up_before = searxng_up()
    code = ("import sys, json; sys.dont_write_bytecode = True; import followup_gather; "
            f"g = followup_gather.run(scope={{'held': [], 'candidates': {names!r}, 'price': []}}); "
            "print('GATHER', json.dumps({k: g[k] for k in ('followed', 'floor_events', 'inbox', 'errors', 'written')}, default=str))")
    out = subprocess.run([PY, "-c", code], cwd=TREE, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=4 * 3600)
    with open(os.path.join(LOGS, f"gather_{datetime.now():%Y%m%d}.log"), "a", encoding="utf-8") as fh:
        fh.write(out.stdout + "\n--- stderr ---\n" + out.stderr)
    summary = next((l for l in out.stdout.splitlines() if l.startswith("GATHER")), None)
    brief = out.stderr[-300:]
    if summary:
        g = json.loads(summary[len("GATHER "):])
        brief = (f"followed {sum(len(v) for v in g['followed'].values())}, inbox files {len(g['inbox'])}, "
                 f"floor events {sum(len(v) for v in g['floor_events'].values())}, errors {len(g['errors'])}, "
                 f"written {g['written']}")
    up_after = searxng_up()
    errored, asked = news_query_errors(names, t0.date().isoformat())
    starved = [w for w, bad in (("SearXNG down before the batch", not up_before),
                                ("SearXNG down after the batch", not up_after),
                                (f"{errored} of {asked} news queries errored", errored)) if bad]
    log(f"gather {t0.date()} {names[0]}..{names[-1]} exit {out.returncode} in "
        f"{round((datetime.now(timezone.utc) - t0).total_seconds())}s: {brief}"
        + (f" | FAILED: {'; '.join(starved)}" if starved else f" | news queries {asked}, none errored"))
    return out.returncode or (2 if starved else 0)


def day():
    names, rc = tickers(), 0
    for i in range(0, len(names), BATCH):
        if i:
            time.sleep(PAUSE_S)
        rc = batch(names[i:i + BATCH], wait_s=0 if i else PROBE_WAIT_S) or rc
    log("day done" + (f" - FAILED (exit {rc})" if rc else ""))
    return rc


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup(sys.argv[2])
    else:
        sys.exit(day())

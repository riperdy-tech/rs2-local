"""formation_chain.py - one pass of a month-end formation on the cloud reader, run again and again by a scheduled task until it is done
(README "Monthly formation", steps 1, 2, 3, 4b, 5 and the books file; plan M5). No session has to be open.

    python tools/paper_books/formation_chain.py 2026-11-30 [--dry-run]

RUN IT FROM THE TREE THE SITE WORKER RUNS FROM (formation_run_cloud's rule: the worker's lock is per tree). The steps that write the books
(check_new_runs, formation_decide, formation_packets, formation_freeze, publish_books) are run from the repository's MAIN working tree, the
read from this one. One pass does what is due and exits; `next_steps` says what is due:

  decide   no map yet: fetch the publish clone, check_new_runs, formation_decide. No verified decision run yet is not a failure: the pass
           ends and the next one tries again.
  packets  a name is `to_build`.
  read     a name is `to_run` or `pending`: formation_run_cloud, READ_CHUNK names at a time, so what is due is looked at again every few
           minutes and a long read never carries the pass over the freeze time. The site worker is asked to stand aside for it (cache/gemini_site/
           formation.hold holds this process id; the worker ends its pass at the next name while that process lives).
  freeze   no frozen copy yet, and either no name is left or the fill open is FREEZE_BEFORE or less away (then before the read). Never
           after the fill open:
           then the chain stops and says so (a map frozen after the open is not a record of the state at the open).
  publish  frozen, the engine has marked the fill session, and the books file is not yet published for this formation.

A step that fails writes cache/paper_books/formation/chain_STOP_<T>.flag with the reason and tells Telegram once; the chain stays idle
until a person removes the flag. The freeze tells Telegram the witness line; publishing the witness (a public commit) stays by hand.
The steps that write rs2-state hold cache/rs2_state.lock of the main working tree (state_lock.py), as run_monthly.py does.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "site"))
import book_paths  # noqa: E402
import formation_run as FR  # noqa: E402
import gemini_ondemand as G  # noqa: E402

READ_CHUNK = 5                             # names read between two looks at what is due
PASS_SECONDS = 25 * 60                     # a pass starts no new step after this long; the next pass goes on
FREEZE_BEFORE = timedelta(minutes=60)      # the map is frozen this long before the fill open even if names are still unread
STATE = FR.STATE
LOG = STATE / "chain.log"


def log(msg):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    STATE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def next_steps(m, frozen, now, marked, published):
    """The steps due in this pass, in order, from the map (None: not decided yet), whether the frozen copy exists, the time, whether the
    engine has marked the fill session and whether the books file is published. ["late"] when the fill open passed with no frozen copy."""
    if m is None:
        return ["decide"]
    names = [n["state"] for n in m["names"].values()]
    steps = []
    if "to_build" in names:
        steps.append("packets")
    if "to_build" in names or "to_run" in names or "pending" in names:
        steps.append("read")
    if not frozen:
        fill = datetime.fromisoformat(m["fill_open_utc"].replace("Z", "+00:00"))
        if now >= fill:
            return ["late"]
        if not steps:
            steps.append("freeze")
        elif now >= fill - FREEZE_BEFORE:
            steps.insert(0, "freeze")                       # first: the read of the names still open goes on after the freeze
    elif marked and not published:
        steps.append("publish")
    return steps


def _main_module(name):
    spec = importlib.util.spec_from_file_location(f"main_{name}", G._main_checkout() / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tell(text):
    try:
        return _main_module("ops").notify_telegram(text)
    except Exception as e:  # noqa: BLE001  a message that cannot be sent never stops the formation
        log(f"telegram failed: {type(e).__name__}: {e}")
        return False


def run(script, *args, cwd=None, tree=None):
    """(exit code, output) of one script of tools/paper_books, from the main working tree unless `tree` is given."""
    tree = tree or G._main_checkout()
    p = subprocess.run([sys.executable, "-u", str(tree / "tools" / "paper_books" / script), *args], cwd=cwd or tree, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (p.stdout + p.stderr).strip()
    for line in out.splitlines()[-12:]:
        log(f"[{script}]   {line[:300]}")
    return p.returncode, out


def worker_free(wait_s=2400, poll_s=20):
    """True once the site worker's lock is free (the worker ends its pass after the name it is on while formation.hold stands)."""
    end = time.monotonic() + wait_s
    while True:
        try:
            if not FR.pid_alive(int(G.LOCK.read_text().strip())):
                return True
        except (OSError, ValueError):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(poll_s)


class Stop(Exception):
    pass


def must(code, out, what):
    if code != 0:
        raise Stop(f"{what} exited {code}: {out.splitlines()[-1][:300] if out else ''}")


def one_pass(T, dry=False, now=None):
    books = book_paths.books()
    path = books / "m3o" / "inputs" / f"formation_{T}.json"
    stop, done = STATE / f"chain_STOP_{T}.flag", STATE / f"chain_published_{T}.flag"
    if stop.exists():
        print(f"stopped: {stop.read_text(encoding='utf-8')[:300]} (remove {stop.name} to go on)", flush=True)
        return 1

    def due():
        m = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        marked = bool(m) and (books / "m3o" / "ledger" / "marks" / f"{m['fill_session']}.json").exists()
        return m, next_steps(m, path.with_name(f"formation_{T}.frozen.json").exists(), now or datetime.now(timezone.utc), marked, done.exists())

    m, steps = due()
    if dry:
        print(f"{T}: due now: {steps or 'nothing'}", flush=True)
        return 0
    if not steps:
        return 0
    lock = _main_module("state_lock").rs2_state_lock
    try:
        started = time.monotonic()
        while True:                                         # each step is taken from the map as it now stands
            step = steps[0]
            log(f"{T}: {step}")
            if step == "late":
                raise Stop("the fill open has passed and the map is not frozen")
            if step == "read":
                hold = G.SITE / "formation.hold"
                hold.parent.mkdir(parents=True, exist_ok=True)
                hold.write_text(str(os.getpid()))
                try:
                    if not worker_free():
                        log("the site worker still holds its lock after 40 minutes; the next pass tries again")
                        return 0
                    code, out = run("formation_run_cloud.py", "--map", str(path), "--limit", str(READ_CHUNK), tree=ROOT)
                finally:
                    hold.unlink(missing_ok=True)
                if code not in (0, 3):                      # 3: both allowances under their floors; the next pass goes on
                    must(code, out, "formation_run_cloud")
            elif step == "publish":
                must(*run("publish_books.py", T), "publish_books")
                done.write_text(datetime.now(timezone.utc).isoformat())
                tell(f"Formation {T}: the paper books file is published.")
            else:
                with lock(wait_s=900) as held:
                    if not held:
                        log("cache/rs2_state.lock is still held after 15 minutes; the next pass tries again")
                        return 0
                    if step == "decide":
                        subprocess.run(["git", "-C", str(book_paths.screener_repo()), "fetch", "origin"], capture_output=True, timeout=600)
                        must(*run("check_new_runs.py"), "check_new_runs")
                        code, out = run("formation_decide.py", T)
                        if code != 0 and not path.exists():
                            log(f"{T}: no decision yet; the next pass tries again")
                            return 0
                    elif step == "packets":
                        must(*run("formation_packets.py", T), "formation_packets")
                    elif step == "freeze":
                        code, out = run("formation_freeze.py", T)
                        must(code, out, "formation_freeze")
                        tell(f"Formation {T} frozen before the fill open. Witness line (publish by hand after a scan):\n{out.splitlines()[-1]}")
            before = (steps, sorted(n["state"] for n in m["names"].values()) if m else None)
            m, steps = due()
            if not steps or (steps, sorted(n["state"] for n in m["names"].values()) if m else None) == before                     or time.monotonic() - started > PASS_SECONDS:
                return 0                                    # nothing left, nothing moved (allowance low), or the pass is long enough
    except Stop as e:
        stop.write_text(str(e), encoding="utf-8")
        log(f"{T}: STOPPED: {e}")
        tell(f"Formation {T} chain STOPPED: {e}. It stays idle until {stop.name} is removed.")
        return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("formation_T")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    datetime.strptime(a.formation_T, "%Y-%m-%d")
    return one_pass(a.formation_T, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())

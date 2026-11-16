"""gemini_ondemand.py - the screener list analysed with Gemini answering in Qwen's place (operator 2026-11-16).

    python tools/site/gemini_ondemand.py [--arm gemini|opus] work [--max-names N] [--no-publish]   # one worker per arm, no GPU
    python tools/site/gemini_ondemand.py [--arm gemini|opus] build | publish | status | meter

A name is analysed exactly as qwen_ondemand analyses it (the same packet builder, reading run, family, valuation at seeds
1000 and 3000, value of record and report), with one thing replaced in this process: the function that sends a request to
the model. It sends the same system and user messages to Gemini 4 Hydrogen at high effort through the `agy` command and
hands the reply back in Ollama's shape, so the parsing, the quote check, the valuation checks and the arithmetic are the
same code. No GPU is used. Everything is written under cache/gemini_site, cache/m3m and cache/m3q of THIS checkout.

Pacing: before every name and after any failed call the worker reads the account's own meter (`agy -p /usage`) and waits
for the reset when the five-hour or the weekly allowance left is under its floor. Thinking effort is never lowered.

Two arms share the list for the first fill (operator 2026-11-16: "consider using claude as well for a faster baseline
fill"): `gemini` (Gemini 4 Hydrogen through agy, from the top of the list) and `opus` (Claude Opus 5.5 through the Claude
Code command line on the Claude subscription, from the bottom). Both run at high effort with the same messages; a name is
claimed before it is started so the two never analyse the same one; each report records its model. Each arm paces itself
on its own account's meter. The opus arm leaves a small margin for the coordinating session on the same subscription.

List: research_now then watchlist by rank, operator-excluded names left out, a name re-analysed when its newest Gemini
analysis is older than REFRESH_DAYS (30: the backstop when nothing happened; operator 2026-11-16).

The verdict (verdict()) is a label from the three values and the price, with no constant: BUY below the bear value, WATCH
from the bear to the base value, AVOID above the base value, NO_CALL when the name is not valued. Paper only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import qwen_site  # noqa: E402
from qwen_c import runner  # noqa: E402
from qwen_c.value import run as vrun  # noqa: E402

PY = sys.executable
EFFORT = "high"                       # operator 2026-11-16: thinking effort is not negotiable
# floors: the share of an allowance left under which the arm waits. gemini: about one name's cost (operator 2026-11-16: no
# reserve needed). opus: the operator is not using Claude Code until the first fill is done (2026-11-16), so only what the
# coordinating session needs to keep supervising is left.
ARMS = {"gemini": {"model": "gemini-4-hydrogen-high", "floors": {"gemini-5h": 0.08, "gemini-weekly": 0.025}},
        "opus": {"model": "claude-opus-5-5", "floors": {"claude-5h": 0.10, "claude-weekly": 0.05}}}
ARM = "gemini"
GEM_MODEL = ARMS[ARM]["model"]
SITE = ROOT / "cache" / "gemini_site"
ONDEMAND = SITE / "ondemand"
REPORTS = SITE / "gemini_c_reports"
OVERLAY = SITE / "gemini_c_overlay.json"
CLAIMS = SITE / "claims"
LOCK = SITE / "worker.lock"
LOG = SITE / "worker.log"
USAGE = SITE / "usage.jsonl"
AGY_CWD = SITE / "agy_cwd"
CLAIM_STALE_HOURS = 3
SCHEMA = "gemini_c_site_v1"
REFRESH_DAYS = 30
RETRY_REFUSED_HOURS = 24
FLOORS = ARMS[ARM]["floors"]
SITE_FILES = ("public/data/gemini_c_overlay.json", "public/data/gemini_c_reports")
STATE = {"label": ""}


def agy_exe():
    p = os.environ.get("AGY_EXE") or shutil.which("agy") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")
    if not Path(p).exists():
        raise RuntimeError(f"agy not found (AGY_EXE, PATH, LOCALAPPDATA/agy/bin): {p}")
    return p


def set_arm(arm):
    """Selects the arm for this process: its model, its floors, and (not gemini) its own lock and usage file."""
    global ARM, GEM_MODEL, FLOORS, LOCK, USAGE
    ARM, GEM_MODEL, FLOORS = arm, ARMS[arm]["model"], ARMS[arm]["floors"]
    if arm != "gemini":
        LOCK, USAGE = SITE / f"worker_{arm}.lock", SITE / f"usage_{arm}.jsonl"


def log(msg):
    SITE.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} [{ARM}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _agy(args, stdin=None, timeout=None):
    AGY_CWD.mkdir(parents=True, exist_ok=True)
    return subprocess.run([agy_exe(), *args], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(AGY_CWD), timeout=timeout)


def _claude(args, stdin=None, timeout=None):
    AGY_CWD.mkdir(parents=True, exist_ok=True)
    exe = os.environ.get("CLAUDE_EXE") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
    if not Path(exe).exists():
        raise RuntimeError(f"claude not found (CLAUDE_EXE, PATH, ~/.local/bin): {exe}")
    return subprocess.run([exe, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(AGY_CWD), timeout=timeout)


def meter_claude():
    """The Claude subscription's meter from the command line's own usage report (no tokens), as fractions LEFT."""
    import re
    out = _claude(["-p", "/usage", "--output-format", "json", "--no-session-persistence"], timeout=180).stdout
    text = json.loads(out[out.index("{"):])["result"]
    five = re.search(r"Current session:\s*(\d+)% used", text)
    week = re.search(r"Current week \(all models\):\s*(\d+)% used", text)
    return {"claude-5h": (1 - int(five.group(1)) / 100, None), "claude-weekly": (1 - int(week.group(1)) / 100, None)}


def meter():
    """{bucket id: (fraction of the allowance left, reset time ISO or None)} from the account's own usage report (no tokens)."""
    if ARM == "opus":
        return meter_claude()
    out = _agy(["-p", "/usage", "--output-format", "json"], timeout=180).stdout
    d = json.loads(out[out.index("{"):])
    return {b["id"]: (float(b["remaining_fraction"]), b.get("reset_time"))
            for g in d["command"]["data"]["groups"] for b in g["buckets"]}


def wait_for_quota():
    """Returns the meter once both Gemini allowances are at or above their floors; sleeps to the reset otherwise."""
    while True:
        try:
            m = meter()
            low = [(k, *m[k]) for k in FLOORS if m[k][0] < FLOORS[k]]
        except Exception as e:  # noqa: BLE001  an unreadable meter is never read as "there is room"
            log(f"meter unreadable ({type(e).__name__}: {str(e)[:120]}); waiting 10 minutes")
            time.sleep(600)
            continue
        if not low:
            return m
        k, left, reset = max(low, key=lambda x: x[2] or "")
        secs = 1800.0
        if reset:
            secs = (datetime.fromisoformat(reset.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() + 120
        log(f"quota: {k} has {left:.1%} left (floor {FLOORS[k]:.0%}), resets {reset}; waiting")
        time.sleep(min(max(secs, 120), 3600))


def _ask_gemini(text, timeout):
    """(result or None, detail): result = {status, response, usage{input_tokens, output_tokens, ...}}."""
    line = json.dumps({"event": "user", "message": {"content": text}}, ensure_ascii=False) + "\n"
    res = None
    r = _agy(["--model", GEM_MODEL, "--effort", EFFORT, "--sandbox", "--input-format", "stream-json", "--output-format",
              "stream-json", "-p", ""], stdin=line, timeout=timeout)
    for ln in (r.stdout or "").splitlines():
        if '"event":"result"' in ln:
            try:
                res = json.loads(ln)["result"]
            except ValueError:
                pass
    return res, f"agy: {(res or {}).get('error') or (r.stderr or '')[-300:]}"


def _ask_claude(text, timeout):
    """The same message to Claude Opus through the Claude Code command line: no tools, no settings, no hooks, no session kept."""
    r = _claude(["-p", "--model", GEM_MODEL, "--effort", EFFORT, "--system-prompt",
                 "You are an analyst. Do exactly what the message asks, in one reply.", "--tools", "", "--setting-sources", "",
                 "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence", "--output-format", "json"],
                stdin=text, timeout=timeout)
    try:
        d = json.loads(r.stdout[r.stdout.index("{"):])
    except ValueError:
        return None, f"claude: {(r.stderr or r.stdout or '')[-300:]}"
    u = d.get("usage") or {}
    ok = not d.get("is_error") and d.get("subtype") == "success"
    return ({"status": "SUCCESS" if ok else d.get("subtype") or "error", "response": d.get("result") or "",
             "usage": {"input_tokens": sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                                    "cache_read_input_tokens")),
                       "output_tokens": u.get("output_tokens"),
                       "thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
                       "cache_read_tokens": u.get("cache_read_input_tokens"), "stop_reason": d.get("stop_reason")}},
            f"claude: {d.get('api_error_status') or d.get('subtype')} {str(d.get('result'))[:200]}")


def gemini_call(body, url, timeout):
    """Stands in for runner.call: (kind, response in Ollama's shape, detail). A failed call is retried after the quota check, so
    an exhausted allowance is waited out and never recorded as a failed task."""
    parts = ["Answer in one reply. Do not call any tool, do not search, do not read or write files.\n"]
    for m in body["messages"]:
        parts.append(f"===== {m['role'].upper()} =====\n{m['content']}\n")
    line = "\n".join(parts)
    detail = ""
    for attempt in (1, 2, 3):
        t0 = time.time()
        res = None
        try:
            res, detail = (_ask_claude if ARM == "opus" else _ask_gemini)(line, timeout)
        except subprocess.TimeoutExpired:
            detail = f"{ARM} call timed out"
        u = (res or {}).get("usage") or {}
        with USAGE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": Q.now_z(), "label": STATE["label"], "attempt": attempt, "status": (res or {}).get("status"),
                                "seconds": round(time.time() - t0, 1), "prompt_chars": len(line), **u}) + "\n")
        if res and res.get("status") == "SUCCESS" and (res.get("response") or "").strip():
            return "reply", {"message": {"role": "assistant", "content": res["response"]}, "done": True, "done_reason": "stop",
                             "prompt_eval_count": u.get("input_tokens"), "eval_count": u.get("output_tokens"),
                             "model": GEM_MODEL}, None
        log(f"{STATE['label']} call failed (attempt {attempt}): {detail[:200]}")
        time.sleep(60)
        wait_for_quota()
    return "infra_fatal", None, detail


def swap():
    """Gemini in Qwen's place, in this process only."""
    runner.call = gemini_call
    runner.gpu_preflight = lambda url: []
    via = "the Claude Code command line" if ARM == "opus" else "agy"
    runner.model_show = lambda url: {"swapped_for": f"{GEM_MODEL} via {via}, effort {EFFORT}"}
    runner.ollama_raw.ollama_version = lambda base: f"not used ({ARM})"
    runner.MODEL = f"{GEM_MODEL} via {via}"
    if ARM != "gemini":                       # its own run folders: two processes never append to one run ledger
        runner.M3M_DIR = ROOT / "cache" / f"m3m_{ARM}"


def analyze(t, source):
    """One name end to end, as qwen_ondemand.analyze, in process; writes ondemand/<t>.json; returns its status."""
    import formation_value as FV
    commit, record = Q.verified_commit()
    T = Q.now_z()
    r = subprocess.run([PY, "-m", "qwen_c.packet", "--ticker", t, "--T", T, "--commit", commit, "--verified-record", record,
                        "--screener-repo", str(Q.book_paths.screener_repo()), "--online"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    pk = Q._json_tail(r.stdout)
    if r.returncode or not pk.get("packet"):
        out = (r.stderr or r.stdout).strip()
        return refusal(t, source, T, f"packet refused: {out.splitlines()[-1][:200] if out else r.returncode}")
    packet = pk["packet"]
    t0 = time.time()
    STATE["label"] = f"{t}:q1"
    q1 = runner.run(packet, seed=1000)
    log(f"{t} Q1 {q1.get('status')} {round(time.time() - t0)} s")
    pkj = json.loads(Path(packet).read_text(encoding="utf-8"))
    cik = pkj.get("cik")
    row = FV.stocks_rows(commit).get(t) or {}
    fam = FV.name_family(cik, datetime.fromisoformat(T.replace("Z", "+00:00"))) if cik else {"family": None}
    n = {"packet": packet, "packet_sha256": pk.get("packet_sha256"), "cik": cik, "sector": row.get("sector"),
         "market_cap": row.get("marketCap"), "family": fam.get("family")}
    results = {}
    for seed in Q.SEEDS:
        STATE["label"] = f"{t}:value{seed}"
        res = vrun.value(packet, str(cik), str(n["sector"]), float(n["market_cap"] or 0), family=str(n["family"]), seed=seed,
                         out_root=vrun.RUNS if ARM == "gemini" else ROOT / "cache" / f"m3q_{ARM}" / "runs")
        results[str(seed)] = res
        log(f"{t} value seed {seed} {res.get('status')} {res.get('reason') or ''}")
    rep = Q.report(t, source, T, q1, n, results, commit)
    rep["model"] = GEM_MODEL
    _write_report(rep)
    return "ok"


def refusal(t, source, T, why):
    _write_report({"ticker": t, "date": T, "source": "screener list refresh" if source == "list" else f"on request ({source})",
                   "model": GEM_MODEL, "analysis": "not run", "claims": None, "claims_supported": None, "in_code_book": False,
                   "qwen_book": None, "flags": [], "valued": False, "no_value_reason": why, "family": None, "tasks": {},
                   "valuation": None, "authority": "diagnostic: paper only, not investment advice"})
    log(f"{t} refused: {why}")
    return "refused"


def _write_report(rep):
    ONDEMAND.mkdir(parents=True, exist_ok=True)
    (ONDEMAND / f"{rep['ticker']}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")


def verdict(row):
    """(verdict, reason) from the three values and the price in the quoted unit; no constant. A label, paper only."""
    if not row.get("valued"):
        return "NO_CALL", row.get("no_value_reason") or "not valued"
    bear, base, price = row.get("value_bear"), row.get("value_base"), row.get("price_at_publish")
    if bear is None or base is None or price is None:
        return "NO_CALL", "no quoted price or market cap to compare the value with"
    if not bear <= base:
        return "NO_CALL", "the bear value is above the base value"
    if price < bear:
        return "BUY", "price below the bear value"
    if price <= base:
        return "WATCH", "price between the bear and the base value"
    return "AVOID", "price above the base value"


def build():
    rows = {}
    for p in sorted(ONDEMAND.glob("*.json")) if ONDEMAND.exists() else []:
        rep = json.loads(p.read_text(encoding="utf-8"))
        rows[rep["ticker"]] = ({k: v for k, v in rep.items() if k not in ("tasks", "valuation", "ticker", "authority")}, rep)
    s = json.loads((paths.resolve("screener_data_dir") / "stocks.json").read_text(encoding="utf-8"))
    s = s if isinstance(s, list) else s.get("stocks", s)
    qwen_site.quote_units(rows, {r["symbol"]: r for r in s if isinstance(r, dict) and r.get("symbol")})
    for row, rep in rows.values():
        v, why = verdict(row)
        for d in (row, rep):
            d.update(verdict=v, verdict_reason=why)
    if REPORTS.exists():
        shutil.rmtree(REPORTS)
    REPORTS.mkdir(parents=True)
    for t, (_, rep) in rows.items():
        (REPORTS / f"{t}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")
    counts = {k: sum(r["verdict"] == k for r, _ in rows.values()) for k in ("BUY", "WATCH", "AVOID", "NO_CALL")}
    ov = {"schema": SCHEMA, "generated_at": Q.now_z(), "model": GEM_MODEL, "effort": EFFORT, "count": len(rows),
          "valued_count": sum(bool(r["valued"]) for r, _ in rows.values()), "verdict_counts": counts,
          "verdict_rule": "BUY: price below the bear value. WATCH: from the bear to the base value. AVOID: above the base value. "
                          "NO_CALL: not valued.",
          "note": "Gemini reading of SEC filings in the place of the local model; values per share from code using Gemini's "
                  "choices, where both seeds agree. Paper only, not investment advice.",
          "tickers": {t: r for t, (r, _) in sorted(rows.items())}}
    OVERLAY.write_text(json.dumps(ov, indent=1, sort_keys=True), encoding="utf-8")
    print(f"built {len(rows)} names ({ov['valued_count']} valued) {counts}", flush=True)
    return ov


def _main_checkout():
    """The repository's main working tree: the publish lock is shared with qwen_site and the depth publisher there."""
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                       text=True, check=True)
    return Path(r.stdout.strip()).parent


def publish():
    """The two site files to stock-screener main through the dedicated publish clone, under the shared publish lock."""
    build()
    repo = paths.resolve("screener_publish_repo")
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)  # noqa: E731
    if "stock-screener" not in g("remote", "get-url", "origin").stdout:
        sys.exit("ABORT: the publish clone's origin is not stock-screener")
    qwen_site.LOCK = _main_checkout() / "cache" / "screener_publish.lock"
    if not qwen_site._lock():
        sys.exit("ABORT: screener_publish.lock held")
    try:
        if g("fetch", "origin", "main").returncode:
            sys.exit("ABORT: fetch failed")
        # qwen_site leaves its own files pending in the clone between its publishes; they are its to commit, not ours
        if g("status", "--porcelain", "--", ":!public/data/qwen_overlay.json", ":!public/data/m3o_books.json",
             ":!public/data/qwen_reports", *(f":!{p}" for p in SITE_FILES)).stdout.strip():
            sys.exit("ABORT: the publish clone has unexpected local changes")
        if g("checkout", "-B", "main", "origin/main").returncode:
            sys.exit("ABORT: could not reset the publish clone to origin/main")
        data = repo / "public" / "data"
        shutil.copyfile(OVERLAY, data / "gemini_c_overlay.json")
        if (data / "gemini_c_reports").exists():
            shutil.rmtree(data / "gemini_c_reports")
        shutil.copytree(REPORTS, data / "gemini_c_reports")
        for f in [data / "gemini_c_overlay.json", *sorted((data / "gemini_c_reports").glob("*.json"))]:
            json.loads(f.read_text(encoding="utf-8"))
        g("add", "-A", *SITE_FILES)
        if g("diff", "--cached", "--check").returncode:
            sys.exit("ABORT: conflict markers in staged content")
        if g("diff", "--cached", "--quiet").returncode == 0:
            print("gemini site files unchanged: nothing to push", flush=True)
            return
        if g("-c", "commit.gpgsign=false", "commit", "-m", "gemini analysis: site update").returncode:
            sys.exit("ABORT: commit failed")
        for _ in range(5):
            g("fetch", "origin", "main")
            if g("rebase", "origin/main").returncode:
                g("rebase", "--abort")
                sys.exit("ABORT: rebase conflict against origin/main")
            if g("push", "origin", "main").returncode == 0:
                print("pushed gemini site files", g("rev-parse", "--short", "HEAD").stdout.strip(), flush=True)
                return
            time.sleep(4)
        sys.exit("ABORT: push failed after 5 attempts")
    finally:                                   # none of OUR files is left pending in the clone, whatever happened
        g("reset", "-q", "--", *SITE_FILES)
        g("checkout", "-q", "--", *SITE_FILES)
        g("clean", "-fdq", "--", *SITE_FILES)
        qwen_site.LOCK.unlink(missing_ok=True)


def last_analysed():
    """{ticker: newest Gemini analysis date}; a refusal counts as RETRY_REFUSED_HOURS old-age less (retried the next day)."""
    out = {}
    shift = timedelta(days=REFRESH_DAYS) - timedelta(hours=RETRY_REFUSED_HOURS)
    for p in ONDEMAND.glob("*.json") if ONDEMAND.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        date = d["date"]
        if d.get("analysis") == "not run":
            date = (datetime.fromisoformat(date.replace("Z", "+00:00")) - shift).isoformat()
        out[d["ticker"]] = date
    return out


def claim(t):
    """True when this process now holds name t (an exclusive file; a claim older than CLAIM_STALE_HOURS is a dead worker's)."""
    CLAIMS.mkdir(parents=True, exist_ok=True)
    p = CLAIMS / f"{t}.json"
    if p.exists() and time.time() - p.stat().st_mtime > CLAIM_STALE_HOURS * 3600:
        p.unlink(missing_ok=True)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, json.dumps({"arm": ARM, "pid": os.getpid(), "at": Q.now_z()}).encode())
    os.close(fd)
    return True


def next_name():
    """The next due name, claimed for this arm: gemini from the top of the list, any other arm from the bottom."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).isoformat()
    seen = last_analysed()
    names = Q.list_names()
    for t in names if ARM == "gemini" else reversed(names):
        if seen.get(t, "") < cutoff and claim(t):
            return t
    return None


def take_lock():
    import formation_run as FR
    if LOCK.exists():
        try:
            if FR.pid_alive(int(LOCK.read_text().strip())):
                return False
        except ValueError:
            pass
    SITE.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def work(max_names, do_publish):
    if not take_lock():
        print("another worker holds the lock", flush=True)
        return 0
    try:
        swap()
        done = 0
        while max_names is None or done < max_names:
            t = next_name()
            if t is None:
                log("nothing to analyse")
                break
            before = wait_for_quota()
            log(f"{t} start | left: " + ", ".join(f"{k} {before[k][0]:.1%}" for k in FLOORS))
            try:
                st = analyze(t, "list")
            except Exception as e:  # noqa: BLE001  one name's failure is logged and the worker moves on
                st = refusal(t, "list", Q.now_z(), f"pipeline error: {type(e).__name__}: {str(e)[:160]}")
            (CLAIMS / f"{t}.json").unlink(missing_ok=True)
            done += 1
            log(f"{t} {st}")
            if do_publish:
                try:
                    publish()
                except SystemExit as e:
                    log(f"publish failed: {e}")
        return 0
    finally:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=sorted(ARMS), default="gemini")
    sub = ap.add_subparsers(dest="cmd", required=True)
    wk = sub.add_parser("work")
    wk.add_argument("--max-names", type=int)
    wk.add_argument("--no-publish", action="store_true")
    for c in ("build", "publish", "status", "meter"):
        sub.add_parser(c)
    a = ap.parse_args()
    set_arm(a.arm)
    if a.cmd == "work":
        sys.exit(work(a.max_names, not a.no_publish))
    elif a.cmd == "build":
        build()
    elif a.cmd == "publish":
        publish()
    elif a.cmd == "meter":
        print(json.dumps(meter(), indent=1))
    else:
        seen = last_analysed()
        print("analysed:", len(seen), "| claimed:", len(list(CLAIMS.glob("*.json"))) if CLAIMS.exists() else 0,
              "| lock:", LOCK.read_text().strip() if LOCK.exists() else None)

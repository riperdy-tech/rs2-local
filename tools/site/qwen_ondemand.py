"""qwen_ondemand.py - Qwen analysis of one stock on request, and the rolling refresh of the screener's list (research_now and
watchlist bands), published to the site (operator 2026-11-06).

    python tools/site/qwen_ondemand.py request TICKER [--source web|telegram|operator]   # queue a name (no GPU)
    python tools/site/qwen_ondemand.py work [--max-names N]                               # the worker: one instance, GPU
    python tools/site/qwen_ondemand.py status                                             # queue and last results

A name is analysed exactly as a formation name is, at T = now: a qwen_c packet built from the newest screener run that
check_new_runs verified (PASS, pair PASS) plus the SEC filings fetched now; the Q1 run (all tasks, seed base 1000); the menu
valuation at seeds 1000 and 3000 with the live MRI anchors and reference closure; the two seeds' value of record
(qwen_c.value.consensus, rule (a)). The report goes to cache/site/ondemand/<T>.json and qwen_site.publish() puts it on the site.

The worker takes queued requests first (oldest first), then refreshes list names whose newest Qwen analysis is older than
REFRESH_DAYS (research_now by rank, then watchlist by rank). It stops when the queue and the list are done, at --max-names, or
before a name when the GPU is not ours: cache/site/GPU_HOLD exists (any session may create it to keep the GPU), another Ollama
model is loaded, or the card holds more than FOREIGN_VRAM_MIB with no Ollama model loaded (ComfyUI or another job). It never
touches KIS, DEPTH_PAUSED or any real-money switch; analysis is paper only.
"""
import argparse
import json
import os
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
import book_paths  # noqa: E402
import paths  # noqa: E402
import qwen_site  # noqa: E402

PY = sys.executable
SITE = ROOT / "cache" / "site"
QUEUE = SITE / "queue.jsonl"
DONE = SITE / "done.jsonl"
HOLD = SITE / "GPU_HOLD"
LOCK = SITE / "worker.lock"
LOG = SITE / "worker.log"
REFRESH_DAYS = 14
FOREIGN_VRAM_MIB = 2000
SEEDS = (1000, 3000)
VERIFIER = book_paths.books() / "m3l_verifier" / "out"
VERIFY_EVERY_HOURS = 20
RETRY_REFUSED_HOURS = 24


def log(msg):
    SITE.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def now_z():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def request(ticker, source):
    t = ticker.strip().upper()
    if not t.replace(".", "").replace("-", "").isalnum() or len(t) > 8:
        sys.exit(f"not a ticker: {ticker!r}")
    if any(q["ticker"] == t for q in _jsonl(QUEUE)):
        log(f"request {t} ({source}): already queued")
        return
    SITE.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ticker": t, "source": source, "requested_at": now_z()}) + "\n")
    log(f"request {t} ({source}): queued")


def gpu_ours():
    """(True, None) or (False, why): the GPU may be used by the worker now."""
    if HOLD.exists():
        return False, f"GPU_HOLD: {HOLD.read_text(encoding='utf-8')[:120]}"
    from qwen_c import runner
    try:
        loaded = runner.gpu_preflight(runner.llm_provider.OLLAMA_URL)
    except runner.RunRefused as e:
        return False, str(e)
    if not loaded:
        try:
            used = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True,
                                      text=True, timeout=20).stdout.split()[0])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return False, "nvidia-smi unreadable"
        if used > FOREIGN_VRAM_MIB:
            return False, f"{used} MiB in use with no Ollama model loaded (another job holds the card)"
    return True, None


def verified_commit():
    """(output_commit, record path) of the newest screener run check_new_runs verified with verdict and pair PASS."""
    best = None
    for p in sorted(VERIFIER.glob("check_*.json")):
        for r in json.loads(p.read_text(encoding="utf-8")):
            if r.get("verdict") == "PASS" and r.get("pair") == "PASS" and r.get("output_commit"):
                if best is None or (r.get("run_updated_at") or "") > best[2]:
                    best = (r["output_commit"], str(p), r.get("run_updated_at") or "")
    if best is None:
        raise RuntimeError("no verified screener run (check_new_runs PASS, pair PASS)")
    return best[0], best[1]


def refresh_verification():
    """Verify the screener's newer GitHub runs when the newest verified one is older than VERIFY_EVERY_HOURS, so the list and the
    packets follow the daily screener (the list's new names have no profile at an old commit; HCI etc., 2026-11-06)."""
    newest = ""
    for p in VERIFIER.glob("check_*.json"):
        for r in json.loads(p.read_text(encoding="utf-8")):
            if r.get("verdict") == "PASS" and r.get("pair") == "PASS" and r.get("output_commit"):
                newest = max(newest, r.get("run_updated_at") or "")
    if newest and datetime.fromisoformat(newest.replace("Z", "+00:00")) > datetime.now(timezone.utc) - timedelta(hours=VERIFY_EVERY_HOURS):
        return
    since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo = book_paths.screener_repo()
    subprocess.run(["git", "-C", str(repo), "fetch", "origin", "-q"], capture_output=True, timeout=300)
    r = subprocess.run([PY, str(ROOT / "tools" / "paper_books" / "check_new_runs.py"), "--since", since, "--repo", str(repo)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    log(f"verification refreshed (rc {r.returncode}); newest verified commit now {verified_commit()[0][:10]}")


def _json_tail(out):
    return json.loads(out[out.index("{"):]) if "{" in out else {}


def analyze(t, source):
    """Run one name end to end; write cache/site/ondemand/<t>.json; return its status."""
    import formation_value as FV
    commit, record = verified_commit()
    T = now_z()
    r = subprocess.run([PY, "-m", "qwen_c.packet", "--ticker", t, "--T", T, "--commit", commit, "--verified-record", record,
                        "--screener-repo", str(book_paths.screener_repo()), "--online"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    pk = _json_tail(r.stdout)
    if r.returncode or not pk.get("packet"):
        return _write_refusal(t, source, T, f"packet refused: {(r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else r.returncode}")
    packet = pk["packet"]
    t0 = time.time()
    r = subprocess.run([PY, "-m", "qwen_c.runner", packet, "--seed-base", "1000"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if "gpu_busy" in r.stdout + r.stderr:
        return "gpu_busy"
    q1 = _json_tail(r.stdout)
    log(f"{t} Q1 {q1.get('status')} {round(time.time() - t0)} s")
    pkj = json.loads(Path(packet).read_text(encoding="utf-8"))
    cik = pkj.get("cik")
    row = FV.stocks_rows(commit).get(t) or {}
    fam = FV.name_family(cik, datetime.fromisoformat(T.replace("Z", "+00:00"))) if cik else {"family": None}
    n = {"packet": packet, "packet_sha256": pk.get("packet_sha256"), "cik": cik, "sector": row.get("sector"), "market_cap": row.get("marketCap"),
         "family": fam.get("family")}
    results = {}
    for seed in SEEDS:
        rd, _ = FV.run_dir(n, seed)
        if rd.exists():
            rd.rename(rd.with_name(rd.name + f"_aside{int(time.time())}"))
        r = subprocess.run([PY, "-m", "qwen_c.value.run", packet, "--cik", str(cik), "--sector", str(n["sector"]),
                            "--market-cap", str(n["market_cap"] or 0), "--family", str(n["family"]), "--seed", str(seed)],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if "gpu_busy" in r.stdout + r.stderr:
            return "gpu_busy"
        if (rd / "result.json").exists():
            results[str(seed)] = json.loads((rd / "result.json").read_text(encoding="utf-8"))
        log(f"{t} value seed {seed} {(results.get(str(seed)) or {}).get('status')}")
    rep = report(t, source, T, q1, n, results, commit)
    (SITE / "ondemand").mkdir(parents=True, exist_ok=True)
    (SITE / "ondemand" / f"{t}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")
    return "ok"


def _write_refusal(t, source, T, why):
    rep = {"ticker": t, "date": T, "source": f"on request ({source})", "analysis": "not run", "claims": None, "claims_supported": None,
           "in_code_book": False, "qwen_book": None, "flags": [], "valued": False, "no_value_reason": why, "family": None,
           "tasks": {}, "valuation": None, "authority": "diagnostic: paper only, not investment advice"}
    (SITE / "ondemand").mkdir(parents=True, exist_ok=True)
    (SITE / "ondemand" / f"{t}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")
    log(f"{t} refused: {why}")
    return "refused"


def report(t, source, T, q1, n, results, commit):
    """The site report of one on-demand name, in qwen_site's schema."""
    an = {}
    if q1.get("run_dir") and (Path(q1["run_dir"]) / "analysis.json").exists():
        an = json.loads((Path(q1["run_dir"]) / "analysis.json").read_text(encoding="utf-8"))
    ok = {k: v for k, v in results.items() if str(v.get("status", "")).startswith("ok")}
    valued, v, reason = False, {}, None
    if ok:
        from qwen_c.value import consensus, run, task
        pk = json.loads(Path(n["packet"]).read_text(encoding="utf-8"))
        f, b, bar, record, r, prov, fy_ends = run.prepare(pk, n["cik"], str(n["sector"]), n["market_cap"] or 0, online=False, family=n["family"])
        route = "financial" if n["family"] in run.FINANCIAL else "operating"
        v = consensus.combine(ok, task.evidence_ids(pk, record, b, bar, r, prov), b, bar, r, fy_ends, route)
        valued = str(v.get("status", "")).startswith("ok")
    if not valued:
        codes = sorted({str(x.get("reason")) for x in results.values()}) or ["not_valued"]
        reason = "; ".join(qwen_site.NO_VALUE.get(c, c) for c in codes)
    ss = an.get("support_summary") or {}
    rep = {"ticker": t, "date": T, "source": f"on request ({source})" if source != "list" else "screener list refresh",
           "screener_commit": commit, "model": "qwen", "analysis": an.get("status") or q1.get("status") or "failed",
           "claims": ss.get("claims"), "claims_supported": ss.get("supported"), "in_code_book": False, "qwen_book": None,
           "flags": [c.get("claim") for c in ((an.get("tasks") or {}).get("material_events") or {}).get("claims") or []
                     if c.get("support") == "supported"][:3],
           "valued": valued, "no_value_reason": reason, "family": n["family"],
           "tasks": {k: qwen_site._claims((an.get("tasks") or {}).get(k)) for k in qwen_site.TASKS},
           "valuation": ({k: v.get(k) for k in ("options", "numbers", "neutral", "directions", "departures", "evidence", "annotations",
                                                "reverts", "of_record", "year")} | {"unknowns": (v.get("reply") or {}).get("unknowns")})
           if valued else None,
           "authority": "diagnostic: paper only, not investment advice"}
    if valued:
        seed = next(iter(ok.values()))
        shares = (seed.get("base") or {}).get("shares")
        rep.update(equity_value=v["values"]["base"] * shares if shares else None, filed_shares=shares,
                   value_per_filed_share={k: v["values"][k] for k in ("bear", "base", "bull")},
                   seeds_agree=not any(a.startswith("seeds_disagree") for a in v.get("annotations", [])),
                   seed_base={k: (x.get("values") or {}).get("base") for k, x in results.items()})
    return rep


def list_names():
    """research_now then watchlist, each by screener rank, from factor_scores.json at the verified commit the packets use."""
    commit, _ = verified_commit()
    d = json.loads(subprocess.run(["git", "-C", str(book_paths.screener_repo()), "show", f"{commit}:public/data/factor_scores.json"],
                                  capture_output=True, check=True).stdout.decode("utf-8"))["tickers"]
    excluded = set(book_paths.operator_excluded())
    order = {"research_now": 0, "watchlist": 1}
    rows = [(order[r["fct_band"]], r.get("fct_rank") or 10 ** 6, t) for t, r in d.items() if r.get("fct_band") in order and t not in excluded]
    return [t for *_, t in sorted(rows)]


def last_analysed():
    """{ticker: newest Qwen analysis date (ISO)} across the published formation and on-demand reports. A refusal (analysis not
    run) counts as RETRY_REFUSED_HOURS old-age less, so it is retried the next day, not after REFRESH_DAYS."""
    out = {}
    ov = SITE / "qwen_overlay.json"
    if ov.exists():
        for t, r in json.loads(ov.read_text(encoding="utf-8"))["tickers"].items():
            out[t] = r["date"]
    shift = timedelta(days=REFRESH_DAYS) - timedelta(hours=RETRY_REFUSED_HOURS)
    for p in (SITE / "ondemand").glob("*.json") if (SITE / "ondemand").exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        date = d["date"]
        if d.get("analysis") == "not run":
            date = (datetime.fromisoformat(date.replace("Z", "+00:00")) - shift).isoformat()
        out[d["ticker"]] = max(out.get(d["ticker"], ""), date)
    return out


def next_name():
    """(ticker, source, from_queue) of the next name, or None."""
    q = _jsonl(QUEUE)
    if q:
        return q[0]["ticker"], q[0]["source"], True
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).isoformat()
    seen = last_analysed()
    for t in list_names():
        if seen.get(t, "") < cutoff:
            return t, "list", False
    return None


def pop(t):
    q = [x for x in _jsonl(QUEUE) if x["ticker"] != t]
    tmp = QUEUE.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(x) + "\n" for x in q), encoding="utf-8")
    os.replace(tmp, QUEUE)


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


def work(max_names):
    if not take_lock():
        print("another worker holds the lock", flush=True)
        return 0
    try:
        done = 0
        try:
            refresh_verification()
        except Exception as e:  # noqa: BLE001  the worker goes on with the newest commit already verified
            log(f"verification refresh failed: {type(e).__name__}: {str(e)[:160]}")
        while max_names is None or done < max_names:
            nxt = next_name()
            if nxt is None:
                log("nothing to analyse")
                break
            ours, why = gpu_ours()
            if not ours:
                log(f"GPU not ours: {why}; stopping")
                break
            t, source, queued = nxt
            log(f"{t} start ({source})")
            try:
                st = analyze(t, source)
            except Exception as e:  # noqa: BLE001  one name's failure is logged and the worker moves on
                st = _write_refusal(t, source, now_z(), f"pipeline error: {type(e).__name__}: {str(e)[:160]}")
            if st == "gpu_busy":
                log(f"{t}: GPU taken during the run; left queued")
                break
            if queued:
                pop(t)
            with DONE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ticker": t, "source": source, "status": st, "at": now_z()}) + "\n")
            done += 1
            try:
                qwen_site.publish()
            except SystemExit as e:
                log(f"publish failed: {e}")
        return 0
    finally:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()


def status():
    print("queue:", [q["ticker"] for q in _jsonl(QUEUE)])
    print("hold:", HOLD.exists(), "| GPU:", gpu_ours())
    print("last done:", _jsonl(DONE)[-5:])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rq = sub.add_parser("request")
    rq.add_argument("ticker")
    rq.add_argument("--source", default="operator")
    wk = sub.add_parser("work")
    wk.add_argument("--max-names", type=int)
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "request":
        request(a.ticker, a.source)
    elif a.cmd == "work":
        sys.exit(work(a.max_names))
    else:
        status()

"""runner.py - the gate-2 Muse replay runner (registration section 2).

    python -m rebuild_harness.gate2.runner --mode pilot|full|masked [--state-dir DIR] [--dry-run] [--rehearsal]

For every (company, date) of the sample, in the sample's order (dates ascending, each date in its drawn order):
  1. the inputs of the frozen gate-1 engine at T (`env.RealEnv.company_inputs`): filings known at T only;
  2. `valuation.muse.pipeline.run_company`: the CODE arm (the engine on the prior alone, every input at the prior's P50) and the MUSE arm (pass 1 P1-P5, the price, pass 2 P6,
     the final assembly) on the SAME frozen engine, the same draws, the same share basis;
  3. one record per company-date.

CHECKPOINT AFTER EVERY COMPANY.  `progress.jsonl` (append-only, flushed) gets one line per finished company-date; a restart skips the keys whose latest line is final.  The
run directory of one attempt is `runs/<date>/<date>_<cik>/aNN`; a second attempt (a crash, a transport failure) goes to a NEW attempt folder, nothing is overwritten, moved or
removed.  Every request and response is saved by the pipeline's runner (`NN_<call>_aK_request.json` / `_response.json`, `calls.jsonl`, `run_manifest.json`, `pack.json`, `result.json`);
`job.json` adds the per-company wall time (build and model seconds, calls, tokens, calls cut at the length limit) and the integrity facts of G5.

BETWEEN COMPANIES the runner honours the pause switch (`<state>/PAUSE`, and any `--pause-also FILE`; it never writes or removes `cache/DEPTH_PAUSED`, and reads it only when told to) and
WAITS, never skips, while another program uses the GPU (`gpu.other_gpu_use`).  When it has to wait it STOPS its own server so the card is free, and starts it again (only when the card
is free) before the next company.  A company in progress is finished first (a few minutes): the check is at the boundary.

TRANSPORT FAILURE (no server, timeout, HTTP 5xx): never turned into prior values and never a skip.  The server is stopped, the runner waits for a free card, restarts it and runs the SAME company
again in a new attempt folder.  After MAX_CONSECUTIVE_TRANSPORT_FAILURES in a row the run halts (exit 3); the scheduled task starts a fresh process within 15 minutes, which retries the same company.
Two outcomes are final and recorded, not retried, because retrying cannot help: `context_overflow` (the prompt leaves no room for an answer in the 32768-token window) and
`request_rejected` (HTTP 4xx).  Both count against G5.  A Python exception in one company-date is recorded as status `error` (traceback in job.json) and the run goes on;
`--retry-errors` runs those again after a fix.

SINGLE INSTANCE: `runner.lock` (a second copy exits at once); the scheduled task starts a copy every 15 minutes.

MODES.  `pilot`: the first 10 companies of 2025-10-31 (part of the sample): the report is the TIME per company (and operational counts: calls, tokens, length cuts, failures); the outputs are
SEALED (a manifest of sha256 values is written, nothing is summarised, nothing is read back).  `full`: the rest.  `masked`: the G6 control of 30 company-dates with name and ticker masked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import msvcrt
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from . import config, gpu, guard, integrity
from . import sample as sample_mod


class HaltRun(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


TERMINAL_OK = None          # a record whose status is anything but the transport-failure marker is final


def job_key(job: dict, masked: bool = False) -> str:
    return f"{'M_' if masked else ''}{job['date']}_{str(job['cik']).zfill(10)}"


def acquire_lock(path: Path):
    """The lock handle, or None when another runner holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    return fh


def tree_manifest(root: Path) -> dict:
    """{relative path: sha256} of every file under root (for the pilot seal)."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class Gate2Runner:
    def __init__(self, *, state_dir=None, sample: dict, env, server, probe, client, pause_files: Sequence[Path] = (), clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, poll: float = config.POLL_SECONDS, n_draws: Optional[int] = None, max_tokens: int = config.MAX_TOKENS,
                 freeze_problems: Callable[[], List[str]] = lambda: [], retry_errors: bool = False, now: Callable[[], datetime] = datetime.now,
                 pipeline_run: Optional[Callable] = None, out=print):
        self.paths = config.state_paths(state_dir)
        self.sample, self.env, self.server, self.probe, self.client = sample, env, server, probe, client
        self.pause_files = [Path(p) for p in ([self.paths["pause"]] + list(pause_files))]
        self.clock, self.sleep, self.poll, self.now = clock, sleep, poll, now
        self.n_draws, self.max_tokens, self.retry_errors, self.out = n_draws, max_tokens, retry_errors, out
        self.freeze_problems = freeze_problems
        self._pipeline_run = pipeline_run
        self.transport_retries: Dict[str, int] = {}

    # -- records --
    def _event(self, event: str, **kw) -> None:
        rec = {"ts": self.now().isoformat(timespec="seconds"), "event": event, **kw}
        self.paths["events"].parent.mkdir(parents=True, exist_ok=True)
        with open(self.paths["events"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        self.out(f"{rec['ts']} {event} " + " ".join(f"{k}={v}" for k, v in kw.items()))

    def progress(self) -> Dict[str, dict]:
        """{key: the LATEST progress line of that key}."""
        out: Dict[str, dict] = {}
        p = self.paths["progress"]
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                out[r["key"]] = r
        return out

    def _append_progress(self, rec: dict) -> None:
        self.paths["progress"].parent.mkdir(parents=True, exist_ok=True)
        with open(self.paths["progress"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def done_keys(self, masked: bool) -> set:
        done = set()
        for k, r in self.progress().items():
            if bool(r.get("masked")) != masked:
                continue
            if r.get("status") == "error" and self.retry_errors:
                continue
            done.add(k)
        return done

    # -- waiting --
    def paused(self) -> Optional[str]:
        for p in self.pause_files:
            if p.exists():
                return f"paused ({p} exists)"
        return None

    def _check(self) -> Optional[str]:
        why = self.paused()
        up = self.server.is_up()
        if why is None:
            why = gpu.other_gpu_use(self.probe, ours_pids=self.server.our_pids(), ours_loaded=up, our_mib=self.server.our_vram_mib())
        if why is not None and up:
            ok, detail = self.server.stop()
            self._event("server_stopped", reason=why, ok=ok, detail=detail)
            if not ok:
                raise HaltRun(7, f"our server did not stop: {detail}")
        return why

    def ensure_ready(self) -> None:
        """Wait (never skip) until nothing pauses the run and the card is free, then make sure our server is up."""
        while True:
            gpu.wait_until_free(self._check, sleep=self.sleep, poll=self.poll, on_change=lambda w: self._event("waiting", why=w))
            if self.server.is_up():
                return
            try:
                rec = self.server.ensure_up()
                self._event("server_started", pid=rec.get("pid"), vram_loaded_mib=rec.get("vram_loaded_mib"), window=rec.get("window"))
                return
            except Exception as e:                                         # ServerRefusal and anything the launch raised
                msg = str(e)
                transient = ("card is not free" in msg) or ("not free" in msg) or ("did not answer /health" in msg) or ("exited with code" in msg)
                self._event("server_start_refused", why=msg[:300], transient=transient)
                if not transient:
                    raise HaltRun(6, f"the Muse server cannot be started: {msg[:300]}")
                self.sleep(self.poll)

    # -- one company-date --
    def _next_attempt_dir(self, root: Path, key: str, date: str) -> Path:
        base = root / date / key
        n = 1
        while (base / f"a{n:02d}").exists():
            n += 1
        return base / f"a{n:02d}"

    def _run_pipeline(self, ci, run_dir: Path, timed, **kw) -> dict:
        if self._pipeline_run is not None:
            return self._pipeline_run(ci, run_dir, timed, **kw)
        from valuation.muse.pipeline import run_company
        return run_company(pit=ci.pit, identity=ci.identity, priors=ci.priors, disc_factory=ci.disc_factory, client=timed, run_dir=run_dir, price_info=ci.price_info,
                           documents=ci.documents, quarters=ci.quarters, cik=ci.cik, seed=ci.seed, corr=ci.corr, max_tokens=self.max_tokens, llm_seed=ci.llm_seed,
                           base_url=self.server.endpoint, industry_context=ci.industry_context, **kw)

    def run_job(self, job: dict, masked: bool = False) -> dict:
        """Run one company-date; returns its progress record (status 'transport_failure' means: not final, run it again)."""
        from valuation.common import InputError
        from . import env as env_mod
        key = job_key(job, masked)
        root = self.paths["runs_masked" if masked else "runs"]
        run_dir = self._next_attempt_dir(root, key, job["date"])
        attempt = int(run_dir.name[1:])
        t0 = self.clock()
        rec = {"key": key, "date": job["date"], "cik": str(job["cik"]).zfill(10), "ticker": job.get("ticker"), "family": job.get("family"), "masked": masked, "attempt": attempt,
               "run_dir": run_dir.relative_to(self.paths["root"]).as_posix() if str(run_dir).startswith(str(self.paths["root"])) else str(run_dir)}
        detail: dict = {"key": key, "attempt": attempt, "masked": masked}
        timed = None
        try:
            ci = self.env.company_inputs(job)
            if isinstance(ci, env_mod.Refusal):
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "result.json").write_text(json.dumps({"status": ci.status, "reasons": ci.reasons, "stamps": ci.stamps, "ticker": job.get("ticker"),
                                                                 "asof": job["date"]}, indent=1), encoding="utf-8")
                rec.update(status=ci.status, reasons=ci.reasons[:3])
                detail["refusal"] = {"status": ci.status, "reasons": ci.reasons}
            else:
                if masked:
                    ci = env_mod.masked_inputs(ci)
                rec["family"] = ci.family
                run_dir.mkdir(parents=True, exist_ok=True)
                timed = guard.TimedClient(guard.ContextGuardClient(self.client, log_path=run_dir / "guard.jsonl"), clock=self.clock)
                kw = {} if self.n_draws is None else {"n_draws": self.n_draws}
                t_build = self.clock()
                try:
                    res = self._run_pipeline(ci, run_dir, timed, **kw)
                except InputError as e:
                    if "positive definite" not in str(e) or ci.corr is None:
                        raise
                    ci.corr = None                                         # as gate 1: inputs drawn independently, stamped
                    ci.stamps.append("corr_not_positive_definite: inputs drawn independently")
                    res = self._run_pipeline(ci, run_dir, timed, **kw)
                status = res.get("status")
                reason = str(res.get("reason") or "")
                if status == "model_unavailable":
                    if reason.startswith(guard.OVERFLOW_PREFIX):
                        status = "context_overflow"
                    elif reason.startswith("HTTP 4"):
                        status = "request_rejected"
                    else:
                        status = "transport_failure"
                rec.update(status=status, reason=reason[:300] if status not in ("ok", "pass1_only") else None)
                detail.update(price_info=ci.price_info, stamps=ci.stamps, price_date=ci.extra.get("price_date"), price_quality=ci.extra.get("price_quality"), seed=ci.seed, llm_seed=ci.llm_seed,
                              build_seconds=round(t_build - t0, 2), timing=timed.summary())
                rec.update(build_seconds=detail["build_seconds"], **timed.summary())
        except Exception as e:                                             # a failure is recorded as itself, never papered over
            run_dir.mkdir(parents=True, exist_ok=True)
            rec.update(status="error", reason=f"{type(e).__name__}: {str(e)[:300]}")
            detail["error"] = {"type": type(e).__name__, "message": str(e)[:1000], "trace": traceback.format_exc()[-3000:]}
            if timed is not None:
                rec.update(timed.summary())
        rec["wall_seconds"] = round(self.clock() - t0, 2)
        detail["wall_seconds"] = rec["wall_seconds"]
        if rec["status"] != "transport_failure":
            try:
                if (run_dir / "result.json").exists():
                    detail["integrity"] = integrity.verify_run_dir(run_dir)
                    rec["integrity"] = {k: detail["integrity"][k] for k in ("n_citations", "n_citations_failed", "n_calls", "n_calls_not_ok", "json_rule_violation")}
            except Exception as e:
                detail["integrity_error"] = f"{type(e).__name__}: {e}"
        detail["transport_retries_before"] = self.transport_retries.get(key, 0)
        rec["transport_retries_before"] = detail["transport_retries_before"]
        if run_dir.exists():
            (run_dir / "job.json").write_text(json.dumps(detail, indent=1, default=str), encoding="utf-8")
        rec["finished"] = self.now().isoformat(timespec="seconds")
        return rec

    # -- the loop --
    def run(self, jobs: List[dict], *, masked: bool = False, label: str = "full") -> int:
        lock = acquire_lock(self.paths["lock"])
        if lock is None:
            return 0
        try:
            self.paths["pid"].write_text(str(os.getpid()))
            probs = self.freeze_problems()
            if probs:
                self._event("refused_unfrozen", problems=probs[:5])
                raise HaltRun(5, "the gate-2 freeze does not hold: " + "; ".join(probs[:5]))
            done = self.done_keys(masked)
            todo = [j for j in jobs if job_key(j, masked) not in done]
            self._event("start", label=label, n_jobs=len(jobs), n_todo=len(todo), masked=masked)
            consecutive = 0
            for i, job in enumerate(todo):
                key = job_key(job, masked)
                while True:
                    self.ensure_ready()
                    rec = self.run_job(job, masked)
                    if rec["status"] != "transport_failure":
                        break
                    consecutive += 1
                    self.transport_retries[key] = self.transport_retries.get(key, 0) + 1
                    self._event("transport_failure", key=key, consecutive=consecutive, reason=rec.get("reason"))
                    ok, detail = self.server.stop()
                    self._event("server_stopped", reason="transport failure", ok=ok, detail=detail)
                    if consecutive >= config.MAX_CONSECUTIVE_TRANSPORT_FAILURES:
                        raise HaltRun(3, f"{consecutive} transport failures in a row on {key}: halting; the scheduled task starts a fresh copy, which retries it")
                    self.sleep(self.poll)
                consecutive = 0
                self._append_progress(rec)
                self._event("done", n=f"{len(done) + i + 1}/{len(done) + len(todo)}", key=key, status=rec["status"], seconds=rec["wall_seconds"])
            self._event("finished", label=label)
            return 0
        except HaltRun as h:
            self._event("halt", code=h.code, message=str(h)[:300])
            return h.code
        finally:
            try:
                ok, detail = self.server.stop()
                self._event("server_stopped", reason="run ended", ok=ok, detail=detail)
            except Exception as e:
                self._event("server_stop_failed", error=str(e)[:200])
            lock.close()


# ---- modes -------------------------------------------------------------------------------------------------------------------------------

def all_final(runner: Gate2Runner, jobs: List[dict], masked: bool = False) -> bool:
    done = runner.done_keys(masked)
    return all(job_key(j, masked) in done for j in jobs)


def pilot_report(state_dir=None) -> dict:
    """The pilot's TIME report from progress.jsonl: wall seconds per company and operational counts only (no output is opened); and the seal of the pilot's run folders."""
    paths = config.state_paths(state_dir)
    smp = sample_mod.load_verified(sample_mod.sample_path(state_dir))
    keys = [job_key(j) for j in sample_mod.pilot_jobs(smp)]
    prog = {}
    for line in paths["progress"].read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        prog[r["key"]] = r
    rows = [prog[k] for k in keys if k in prog]
    secs = sorted(r["wall_seconds"] for r in rows)
    model = [r.get("model_seconds") or 0.0 for r in rows]

    def pct(xs, q):
        return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None
    n_ok = len(rows)
    mean = (sum(secs) / n_ok) if n_ok else None
    total_jobs = len(sample_mod.jobs(smp))
    rep = {"n_pilot": len(keys), "n_finished": n_ok, "wall_seconds_per_company": {r["key"]: r["wall_seconds"] for r in rows}, "mean_seconds": mean, "median_seconds": pct(secs, 0.5),
           "p90_seconds": pct(secs, 0.9), "max_seconds": max(secs) if secs else None, "mean_model_seconds": (sum(model) / n_ok) if n_ok else None,
           "mean_calls": (sum(r.get("n_calls") or 0 for r in rows) / n_ok) if n_ok else None,
           "mean_completion_tokens": (sum(r.get("completion_tokens") or 0 for r in rows) / n_ok) if n_ok else None,
           "max_prompt_tokens": max([r.get("max_prompt_tokens") or 0 for r in rows] or [0]), "n_length_cut": sum(r.get("n_length_cut") or 0 for r in rows),
           "technical_outcomes": {s: sum(1 for r in rows if r["status"] == s) for s in ("context_overflow", "request_rejected", "error")},
           "n_pilot_by_completion": {"completed_pipeline": sum(1 for r in rows if r["status"] in ("ok", "pass1_only")), "other_final_status": sum(1 for r in rows if r["status"] not in ("ok", "pass1_only"))},
           "transport_retries": sum(r.get("transport_retries_before") or 0 for r in rows), "sample_company_dates": total_jobs,
           "estimated_gpu_days_for_the_sample": (None if mean is None else round(mean * total_jobs / 86400.0, 2)),
           "estimate_basis": "mean wall seconds per pilot company x the number of company-dates in the sample; statuses and values of the pilot outputs are not summarised"}
    return rep


def seal_pilot(state_dir=None) -> Path:
    """Write reports/PILOT_SEALED.json: the sha256 of every file of the pilot's run folders.  The outputs are not opened for reading beyond hashing, and are not summarised."""
    paths = config.state_paths(state_dir)
    smp = sample_mod.load_verified(sample_mod.sample_path(state_dir))
    entries = {}
    for j in sample_mod.pilot_jobs(smp):
        d = paths["runs"] / j["date"] / job_key(j)
        if d.exists():
            for rel, sha in tree_manifest(d).items():
                entries[f"{j['date']}/{job_key(j)}/{rel}"] = sha
    out = paths["reports"] / "PILOT_SEALED.json"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_sha = hashlib.sha256(json.dumps(entries, sort_keys=True).encode("utf-8")).hexdigest()
    with open(out, "x", encoding="utf-8") as fh:
        fh.write(json.dumps({"sealed": "the pilot's outputs are sealed (registration section 2: not looked at before the end of the replay); this file lists their sha256 values",
                             "sealed_utc": datetime.now().isoformat(timespec="seconds"), "n_files": len(entries), "manifest_sha256": manifest_sha, "files": entries}, indent=1))
    return out


# ---- command line ---------------------------------------------------------------------------------------------------------------------

def build_real(args):
    """The real collaborators for a real run (nothing here is used by the tests)."""
    from . import env as env_mod
    from . import server as server_mod
    from valuation.muse.runner import OpenAICompatClient
    g = env_mod._g1r()
    cfg = server_mod.load_cfg(args.config)
    srv = server_mod.Gate2Server(cfg, args.state_dir)
    ev = env_mod.RealEnv(state_dir=args.state_dir, store=args.store or g.DEFAULT_STORE, id_map=args.id_map or g.DEFAULT_IDMAP,
                         prices_daily=args.prices_daily or (config.WORKSPACE / "data" / "prices_daily"), prices_monthly=args.prices or g.DEFAULT_PRICES,
                         headers=args.headers or g.DEFAULT_HEADERS, crosswalk=args.crosswalk or g.DEFAULT_CROSSWALK, sic=args.sic or g.DEFAULT_SIC, priors_dir=args.priors_dir,
                         strict_classification=args.strict_classification,
                         submissions_zip=config.WORKSPACE / "data" / "sec_bulk" / "submissions.zip", fetch_documents=not args.no_documents_network)
    client = OpenAICompatClient(srv.endpoint, timeout=float(cfg.get("upstream_timeout_s", 3600)))
    return ev, srv, client


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=["pilot", "full", "masked"], required=True)
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--config", type=Path, help="config.json holding the llamacpp pins (default: RS2_CONFIG_PATH, else this repository's)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the readiness checks; start nothing")
    ap.add_argument("--rehearsal", action="store_true", help="run without the freeze file (only with a --state-dir other than the default; its results are never gate-2 results)")
    ap.add_argument("--pause-also", type=Path, action="append", default=[], help="another file whose existence pauses the run (read only), e.g. rs2-local's cache/DEPTH_PAUSED")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--limit", type=int, help="run at most this many company-dates (rehearsal)")
    ap.add_argument("--store", type=Path)
    ap.add_argument("--id-map", type=Path)
    ap.add_argument("--prices-daily", type=Path)
    ap.add_argument("--prices", type=Path)
    ap.add_argument("--headers", type=Path)
    ap.add_argument("--crosswalk", type=Path)
    ap.add_argument("--sic", type=Path)
    ap.add_argument("--priors-dir", type=Path)
    ap.add_argument("--strict-classification", action="store_true", help="refuse any current-dated SIC (the holdout rule); default: stamped, as gate 1's development runs")
    ap.add_argument("--no-documents-network", action="store_true")
    ap.add_argument("--max-tokens", type=int, default=config.MAX_TOKENS)
    a = ap.parse_args(argv)
    state_dir = a.state_dir
    paths = config.state_paths(state_dir)
    if a.rehearsal and (state_dir is None or Path(state_dir).resolve() == config.STATE_DIR.resolve()):
        print("REFUSED: --rehearsal needs a --state-dir other than the real one")
        return 2
    if not a.dry_run and ((a.mode == "full" and paths["finished"].exists()) or (a.mode == "pilot" and paths["pilot_done"].exists())):
        return 0                                          # the scheduled task's repeats exit quietly once the work is finished
    smp = sample_mod.load_verified(sample_mod.sample_path(state_dir))
    jobs = {"pilot": sample_mod.pilot_jobs(smp), "full": sample_mod.jobs(smp), "masked": sample_mod.masked_control(smp)}[a.mode]
    if a.limit:
        jobs = jobs[:a.limit]
    masked = a.mode == "masked"
    from . import env as env_mod
    from . import freeze_content
    rd = env_mod.readiness(state_dir=state_dir, priors_dir=a.priors_dir)
    if a.dry_run:
        done = Gate2Runner(state_dir=state_dir, sample=smp, env=None, server=None, probe=None, client=None).done_keys(masked) if paths["progress"].exists() else set()
        print(json.dumps({"mode": a.mode, "n_jobs": len(jobs), "n_done": sum(1 for j in jobs if job_key(j, masked) in done), "readiness": rd}, indent=1))
        return 0
    if not rd["ok"] and not a.rehearsal:
        print(json.dumps(rd, indent=1))
        print("REFUSED: the preconditions above do not hold")
        return 4
    ev, srv, client = build_real(a)
    runner = Gate2Runner(state_dir=state_dir, sample=smp, env=ev, server=srv, probe=gpu.Probe(), client=client, pause_files=a.pause_also, max_tokens=a.max_tokens,
                         freeze_problems=(lambda: []) if a.rehearsal else (lambda: freeze_content.verify(state_dir)), retry_errors=a.retry_errors)
    code = runner.run(jobs, masked=masked, label=a.mode)
    if code == 0 and all_final(runner, jobs, masked) and not a.limit:
        if a.mode == "pilot":
            seal_pilot(state_dir)
            rep = pilot_report(state_dir)
            paths["reports"].mkdir(parents=True, exist_ok=True)
            (paths["reports"] / "pilot_timing.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
            paths["pilot_done"].write_text(datetime.now().isoformat())
            print(json.dumps(rep, indent=1))
        elif a.mode == "full":
            paths["finished"].write_text(datetime.now().isoformat())
    return code


if __name__ == "__main__":
    sys.exit(main())

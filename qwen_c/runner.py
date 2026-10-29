"""runner.py - one `qwen_c` run over one frozen packet: seven tasks, their errors and their records (SPEC_m3m_qwen_pipeline.md section 6).

    python -m qwen_c.runner <packet.json> [--num-predict N] [--think low|medium|high] [--url ...]

The model is called through ollama_raw.chat directly (config.json `depth_provider` is not read or changed), with our own SYSTEM
message (tasks.SYSTEM) and `think` passed as the pinned template expects (ollama_raw.think_kwargs).

PER TASK (TASK_TIMEOUT_S per call; seed = the run's seed + the task index, 0-based):
    a reply is parsed (parse_reply) and checked (contract.check_task) -> `ok`; a reply that does not parse or has the wrong shape gets
    one retry at seed + RETRY_SEED_OFFSET with tasks.RETRY_LINE appended, then `malformed`;
    a timeout -> `timeout`, no retry;
    HTTP 5xx or a connection error -> ops.wait_unloaded, then one retry (same prompt and seed), else `infra_error` with the cause;
    when wait_unloaded does not confirm the model is unloaded there is no retry (its own contract: never load on top of it);
    an HTTP 4xx, a refusal of ollama_raw other than overflow, or an unreadable response -> `infra_error`, no retry;
    ollama_raw's context_overflow -> `context_overflow`, no retry;
    thesis_change with no prior run -> `not_applicable_no_prior`, not sent.

RUN STATUS: `complete` when every applicable task is `ok`; `failed` when none is; otherwise `analysis_incomplete` with
`incomplete_tasks`. `run()` never raises once the run directory exists: an unexpected error finishes the run as `failed` with the cause.
A precondition that fails before that (an unreadable or wrong packet, a bad option) raises RunRefused and writes nothing. A process
crash leaves `status: "running"` and no `finished_at`; read_ledger reports it as `crashed`.

RECORDS under M3M_DIR (cache/m3m of this repository): runs/<run_id>/ with packet.json, manifest.json, prompts/<task>.txt (and
<task>_retry.txt for a malformed retry), raw/<task>_<attempt>.json (the reply with its thinking, or the error), analysis.json and
turns/ (turn_log, active during every call); ledger.jsonl gets one line per finished run. The thinking is kept only in raw/ and turns/.

KIS_HALT: rs2-local does not resolve KIS_HALT anywhere (it is a GitHub repository variable of stock-screener, read by the KIS sync
workflow), so the manifest records kis_halt = "not_resolvable_in_rs2" and the run proceeds (WO_M3). Nothing is written to rs2-state,
the overlay or any screener file.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "tools" / "audit_202608"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import llm_provider  # noqa: E402
import ollama_raw  # noqa: E402
import ops  # noqa: E402
import turn_log  # noqa: E402

from qwen_c import contract, tasks  # noqa: E402

M3M_DIR = ROOT / "cache" / "m3m"
MODEL = "rs2-analyst-deep-mtp5-v33"          # config.json depth_model at r26-harness 481d0cf: the Qwen v33 tag
PACKET_CONTRACT = "m3m.packet.v1"
NUM_CTX = 65536
NUM_PREDICT = 12288
THINK = "medium"
SEED_BASE = 1000
RETRY_SEED_OFFSET = 50000
TASK_TIMEOUT_S = 1800
KIS_HALT_STATE = "not_resolvable_in_rs2"
STATUSES = ("ok", "malformed", "timeout", "infra_error", "context_overflow", "not_applicable_no_prior")


class RunRefused(Exception):
    """A precondition failed before any record was written."""


# ---------------------------------------------------------------- small helpers

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def canonical_bytes(packet):
    return json.dumps(packet, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_t(s):
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else None


def t_compact(T):
    return re.sub(r"[^0-9TZ]", "", str(T))


def _write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _json_bytes(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8")


def _write_json(path, obj):
    data = _json_bytes(obj)
    _write_bytes(path, data)
    return sha256_bytes(data)


def git_state():
    """(commit, dirty) of this repository's worktree; (None, None) when git cannot say."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        st = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if head.returncode != 0 or st.returncode != 0:
            return None, None
        return head.stdout.strip(), bool(st.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None, None


# ---------------------------------------------------------------- the reply

_FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)```", re.S | re.I)


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")


def _loads(s):
    return json.loads(s, parse_constant=_no_constant)


def parse_reply(content):
    """(object, None) or (None, why). The single fenced json block; with none, the whole content as JSON; anything else is malformed."""
    content = content or ""
    blocks = _FENCE.findall(content)
    if len(blocks) > 1:
        return None, f"{len(blocks)} fenced json blocks, not one"
    if len(blocks) == 1:
        try:
            return _loads(blocks[0]), None
        except ValueError as e:
            return None, f"the fenced json block is not valid JSON: {e}"
    try:
        return _loads(content.strip()), None
    except ValueError as e:
        return None, f"no fenced json block and the content is not JSON: {e}"


# ---------------------------------------------------------------- one call

def _http_body(e):
    try:
        return e.read().decode("utf-8", "replace")[:2000]
    except Exception:  # noqa: BLE001 - the body is only a detail
        return ""


def call(body, url, timeout):
    """(kind, response, detail): kind is reply, timeout, context_overflow, infra_retry (5xx or a connection error) or infra_fatal."""
    try:
        return "reply", ollama_raw.chat(body, timeout, url), None
    except ollama_raw.RawProviderError as e:
        if e.cause == "context_overflow":
            return "context_overflow", None, str(e)
        return "infra_fatal", None, f"RawProviderError {e}"
    except urllib.error.HTTPError as e:
        return ("infra_retry" if e.code >= 500 else "infra_fatal"), None, f"HTTP {e.code}: {_http_body(e)}"
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            return "timeout", None, f"URLError: {e.reason}"
        return "infra_retry", None, f"URLError: {e.reason}"
    except TimeoutError as e:
        return "timeout", None, f"{type(e).__name__}: {e}"
    except (ConnectionError, http.client.HTTPException) as e:
        return "infra_retry", None, f"{type(e).__name__}: {e}"
    except (OSError, ValueError, KeyError, TypeError) as e:
        return "infra_fatal", None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- the prior run (thesis_change)

def _read_jsonl(path):
    rows = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def find_prior(root, ticker, T):
    """(prior, problem). The prior run is the newest finished run (complete or analysis_incomplete) in the ledger for this ticker with a
    decision time before T (the last line wins among equal times); an older run is never used in its place. prior is {run_id,
    decision_time_utc, growth_thesis, risks, tasks_used, manifest_sha256, analysis_sha256} or None. problem is None or {"kind", "detail"}:
    kind "unverifiable" when its records do not recompute or cannot be read (thesis_change becomes infra_error), "no_ok_tasks" when
    neither its growth_thesis nor its risks is ok (thesis_change becomes not_applicable_no_prior)."""
    t = _parse_t(T)
    rows = [(i, r) for i, r in enumerate(_read_jsonl(Path(root) / "ledger.jsonl"))
            if r.get("ticker") == ticker and r.get("status") in ("complete", "analysis_incomplete")
            and _parse_t(r.get("T")) is not None and t is not None and _parse_t(r.get("T")) < t]
    if not rows:
        return None, None
    _, r = max(rows, key=lambda x: (_parse_t(x[1]["T"]), x[0]))
    d = Path(root) / "runs" / r["run_id"]
    try:
        if sha256_file(d / "manifest.json") != r.get("manifest_sha256"):
            return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: manifest.json does not match its ledger sha256"}
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if sha256_file(d / "analysis.json") != man.get("analysis_sha256"):
            return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: analysis.json does not match its manifest sha256"}
        an = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: records unreadable: {type(e).__name__}: {e}"}
    used = [k for k in ("growth_thesis", "risks") if (an.get("tasks") or {}).get(k, {}).get("status") == "ok"]
    if not used:
        return None, {"kind": "no_ok_tasks", "detail": f"prior run {r['run_id']}: neither growth_thesis nor risks is ok"}
    prior = {"run_id": r["run_id"], "decision_time_utc": an.get("decision_time_utc"), "tasks_used": used,
             "manifest_sha256": r["manifest_sha256"], "analysis_sha256": man["analysis_sha256"]}
    for k in ("growth_thesis", "risks"):
        prior[k] = an["tasks"][k]["claims"] if k in used else []
    return prior, None


# ---------------------------------------------------------------- the packet

def load_packet(packet_path):
    """(packet, file bytes); raises RunRefused."""
    try:
        src = Path(packet_path).read_bytes()
        packet = json.loads(src.decode("utf-8"))
    except (OSError, ValueError) as e:
        raise RunRefused(f"packet unreadable: {type(e).__name__}: {e}") from e
    if not isinstance(packet, dict) or packet.get("contract") != PACKET_CONTRACT:
        raise RunRefused(f"packet contract is not {PACKET_CONTRACT}")
    for k in ("ticker", "decision_time_utc"):
        if not isinstance(packet.get(k), str) or not packet[k]:
            raise RunRefused(f"packet has no {k}")
    if _parse_t(packet["decision_time_utc"]) is None:
        raise RunRefused(f"decision_time_utc {packet['decision_time_utc']!r} is not an ISO time with a zone")
    ev = packet.get("evidence")
    if not isinstance(ev, list) or not ev:
        raise RunRefused("packet has no evidence items")
    ids = []
    for e in ev:
        if not isinstance(e, dict) or not isinstance(e.get("fact_id"), str) or not isinstance(e.get("text"), str):
            raise RunRefused("an evidence item has no fact_id or text")
        ids.append(e["fact_id"])
    if len(set(ids)) != len(ids):
        raise RunRefused("evidence fact_ids are not unique")
    return packet, src


def _new_run_dir(root, ticker, T, packet_sha):
    runs = Path(root) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        run_id = f"{ticker}_{t_compact(T)}_{packet_sha[:12]}_{n}"
        try:
            (runs / run_id).mkdir()
            return runs / run_id, run_id
        except FileExistsError:
            n += 1


# ---------------------------------------------------------------- one task

def _run_task(task, idx, packet, prior, opts, url, run_dir, man_prompts):
    """(analysis record, manifest record) of one task."""
    seed0 = opts["seed"] + idx
    attempts, retry, seed = [], False, seed0
    retried_malformed = retried_infra = False
    t_task = time.monotonic()
    last_check = None
    while True:
        n = len(attempts) + 1
        msgs = tasks.messages(task, packet, prior, retry=retry)
        prompt = ollama_raw.render_prompt(ollama_raw.template_messages(msgs), None, opts["think"])
        pname = f"{task}_retry.txt" if retry else f"{task}.txt"
        if pname not in man_prompts:
            man_prompts[pname] = _write_json_text(run_dir / "prompts" / pname, prompt)
        body = {"model": MODEL, "stream": False, "think": opts["think"], "messages": msgs,
                "options": {"num_ctx": opts["num_ctx"], "num_predict": opts["num_predict"], "seed": seed}}
        t0 = time.monotonic()
        with turn_log.logging_to(run_dir / "turns", task):
            kind, resp, detail = call(body, url, TASK_TIMEOUT_S)
        secs = round(time.monotonic() - t0, 3)
        outcome = kind
        if kind == "reply":
            obj, perr = parse_reply(((resp or {}).get("message") or {}).get("content"))
            last_check = contract.check_task(task, obj, packet) if perr is None else None
            if last_check is not None and last_check["status"] == "ok":
                outcome = "ok"
            else:
                outcome = "malformed"
                detail = perr or "; ".join(last_check["shape_errors"])
        raw = {"task": task, "attempt": n, "seed": seed, "retry_line": retry, "prompt_file": f"prompts/{pname}",
               "outcome": outcome, "detail": detail, "seconds": secs, "response": resp}
        raw_name = f"{task}_{n}.json"
        raw_sha = _write_json(run_dir / "raw" / raw_name, raw)
        att = {"attempt": n, "seed": seed, "retry_line": retry, "prompt_file": f"prompts/{pname}", "outcome": outcome,
               "detail": detail, "seconds": secs, "raw_file": f"raw/{raw_name}", "raw_sha256": raw_sha}
        if resp is not None:
            att.update({k: resp.get(k) for k in ("prompt_eval_count", "eval_count", "done_reason")})
        attempts.append(att)
        if outcome == "malformed" and not retried_malformed:
            retried_malformed, retry, seed = True, True, seed0 + RETRY_SEED_OFFSET
            continue
        if kind == "infra_retry" and not retried_infra:
            retried_infra = True
            ok, why = ops.wait_unloaded(url, MODEL)
            att["wait_unloaded"] = {"ok": ok, "detail": why}
            if ok:
                continue
            detail = f"{detail}; wait_unloaded did not confirm the unload: {why}"
        break
    status = {"ok": "ok", "malformed": "malformed", "timeout": "timeout", "context_overflow": "context_overflow"}.get(outcome, "infra_error")
    rec = {"status": status, "attempts": len(attempts)}
    if status == "ok":
        rec.update({k: last_check[k] for k in ("claims", "unknowns", "dropped_fields", "support_counts")})
    else:
        rec.update({"cause": detail, "claims": [], "unknowns": []})
        if status == "malformed" and last_check is not None:
            rec["shape_errors"] = last_check["shape_errors"]
            rec["dropped_fields"] = last_check["dropped_fields"]
    mrec = {"status": status, "seed": seed0, "seconds": round(time.monotonic() - t_task, 3), "attempts": attempts}
    if status != "ok":
        mrec["cause"] = detail
    if rec.get("dropped_fields"):
        mrec["dropped_fields"] = rec["dropped_fields"]
    return rec, mrec


def _write_json_text(path, text):
    data = text.encode("utf-8")
    _write_bytes(path, data)
    return sha256_bytes(data)


# ---------------------------------------------------------------- the run

def _check_opts(num_ctx, num_predict, think, seed):
    for name, v in (("num_ctx", num_ctx), ("num_predict", num_predict), ("seed", seed)):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise RunRefused(f"{name} must be a non-negative integer, got {v!r}")
    if think not in ollama_raw.EFFORTS:
        raise RunRefused(f"think must be one of {ollama_raw.EFFORTS}, got {think!r}")


def run(packet_path, *, url=llm_provider.OLLAMA_URL, num_ctx=NUM_CTX, num_predict=NUM_PREDICT, think=THINK, seed=SEED_BASE):
    """One run over one packet. Returns {run_id, run_dir, status, incomplete_tasks, manifest_sha256}."""
    _check_opts(num_ctx, num_predict, think, seed)
    packet, src = load_packet(packet_path)
    root = Path(M3M_DIR)
    ticker, T = packet["ticker"], packet["decision_time_utc"]
    packet_sha = sha256_bytes(canonical_bytes(packet))
    run_dir, run_id = _new_run_dir(root, ticker, T, packet_sha)
    commit, dirty = git_state()
    opts = {"num_ctx": num_ctx, "num_predict": num_predict, "think": think, "seed": seed}
    defaults = {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "think": THINK, "seed": SEED_BASE}
    man = {
        "contract": contract.CONTRACT, "prompt_version": tasks.PROMPT_VERSION, "packet_contract": packet.get("contract"),
        "builder_version": packet.get("builder_version"), "run_id": run_id, "ticker": ticker, "decision_time_utc": T,
        "packet": {"file": "packet.json", "source_path": str(packet_path), "file_sha256": sha256_bytes(src), "packet_sha256": packet_sha,
                   "file_is_canonical": src == canonical_bytes(packet)},
        "model": {**llm_provider.ollama_serving(MODEL), "provider": "ollama_raw", "tag": MODEL},
        "template_sha256": ollama_raw.TEMPLATE_SHA256, "system_sha256": sha256_bytes(tasks.SYSTEM.encode("utf-8")),
        "options": {**opts, "seeds": {t: seed + i for i, t in enumerate(tasks.TASKS)}, "retry_seed_offset": RETRY_SEED_OFFSET,
                    "task_timeout_s": TASK_TIMEOUT_S, "sampling": "the Modelfile's defaults (not overridden)",
                    "differs_from_defaults": sorted(k for k in opts if opts[k] != defaults[k])},
        "qwen_c": {"git_commit": commit, "dirty": dirty}, "kis_halt": KIS_HALT_STATE,
        "started_at": now_utc(), "status": "running", "prompts": {}, "tasks": {},
    }
    try:
        man["ollama_version"] = ollama_raw.ollama_version(url.rsplit("/api/", 1)[0])
        _write_bytes(run_dir / "packet.json", src)
        back = (run_dir / "packet.json").read_bytes()
        if sha256_bytes(back) != sha256_bytes(src) or sha256_bytes(canonical_bytes(json.loads(back.decode("utf-8")))) != packet_sha:
            raise RuntimeError("packet.json copy does not recompute")
        prior, prior_problem = find_prior(root, ticker, T)
        man["prior_run"] = ({k: prior[k] for k in ("run_id", "decision_time_utc", "tasks_used", "manifest_sha256", "analysis_sha256")}
                            if prior else None)
        if prior_problem:
            man["prior_run_problem"] = prior_problem
        _write_json(run_dir / "manifest.json", man)
        results = {}
        for idx, task in enumerate(tasks.TASKS):
            if task == "thesis_change" and prior is None:
                st = "infra_error" if prior_problem and prior_problem["kind"] == "unverifiable" else "not_applicable_no_prior"
                cause = prior_problem["detail"] if prior_problem else "no prior run for this ticker before T"
                results[task] = ({"status": st, "attempts": 0, "cause": cause, "claims": [], "unknowns": []},
                                 {"status": st, "seed": seed + idx, "seconds": 0.0, "attempts": [], "cause": cause})
                man["tasks"][task] = results[task][1]
                continue
            try:
                results[task] = _run_task(task, idx, packet, prior, opts, url, run_dir, man["prompts"])
            except Exception as e:  # noqa: BLE001 - a task's own failure is a status, never a raise past run()
                cause = f"runner exception: {type(e).__name__}: {e}"
                results[task] = ({"status": "infra_error", "attempts": 0, "cause": cause, "claims": [], "unknowns": []},
                                 {"status": "infra_error", "seed": seed + idx, "seconds": 0.0, "attempts": [], "cause": cause})
            man["tasks"][task] = results[task][1]
            _write_json(run_dir / "manifest.json", man)
        applicable = [t for t in tasks.TASKS if results[t][0]["status"] != "not_applicable_no_prior"]
        not_ok = {t: results[t][0]["status"] for t in applicable if results[t][0]["status"] != "ok"}
        if not not_ok:
            status = "complete"
        elif len(not_ok) == len(applicable):
            status = "failed"
        else:
            status = "analysis_incomplete"
        analysis = {
            "contract": contract.CONTRACT, "prompt_version": tasks.PROMPT_VERSION, "run_id": run_id, "ticker": ticker,
            "decision_time_utc": T, "packet_sha256": packet_sha, "status": status, "incomplete_tasks": not_ok,
            "note": "A claim whose support is not 'supported' is not a verified value; it stays visible with its reason.",
            "tasks": {t: results[t][0] for t in tasks.TASKS},
        }
        man["analysis_sha256"] = _write_json(run_dir / "analysis.json", analysis)
        man["status"], man["incomplete_tasks"] = status, not_ok
    except Exception as e:  # noqa: BLE001 - see the module docstring
        status = man["status"] = "failed"
        man["cause"] = f"runner exception: {type(e).__name__}: {e}"
        man["incomplete_tasks"] = {t: man["tasks"].get(t, {}).get("status", "not_run") for t in tasks.TASKS}
    turns = run_dir / "turns"
    man["turns"] = {p.relative_to(run_dir).as_posix(): sha256_file(p) for p in sorted(turns.glob("*.json"))} if turns.is_dir() else {}
    man["finished_at"] = now_utc()
    man_sha = _write_json(run_dir / "manifest.json", man)
    line = {"run_id": run_id, "ticker": ticker, "T": T, "packet_sha256": packet_sha, "status": status, "manifest_sha256": man_sha}
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "ledger.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return {"run_id": run_id, "run_dir": str(run_dir), "status": status, "incomplete_tasks": man.get("incomplete_tasks", {}),
            "manifest_sha256": man_sha}


# ---------------------------------------------------------------- the ledger reader

def read_ledger(root=None):
    """Every run: the ledger's lines, plus each run directory the ledger does not list, as `crashed` when its manifest is missing,
    unreadable or still `running` with no `finished_at`, else with its manifest status and `ledger_missing: true`."""
    root = Path(root or M3M_DIR)
    rows = _read_jsonl(root / "ledger.jsonl")
    seen = {r.get("run_id") for r in rows}
    out = list(rows)
    runs = root / "runs"
    for d in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
        if d.name in seen:
            continue
        try:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append({"run_id": d.name, "status": "crashed", "cause": "manifest.json missing or unreadable"})
            continue
        base = {"run_id": d.name, "ticker": man.get("ticker"), "T": man.get("decision_time_utc"),
                "packet_sha256": (man.get("packet") or {}).get("packet_sha256")}
        if man.get("status") == "running" and not man.get("finished_at"):
            out.append({**base, "status": "crashed"})
        else:
            out.append({**base, "status": man.get("status"), "ledger_missing": True})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m qwen_c.runner", description="One qwen_c run over one m3m.packet.v1 packet.")
    ap.add_argument("packet")
    ap.add_argument("--num-predict", type=int, default=NUM_PREDICT)
    ap.add_argument("--think", choices=("low", "medium", "high"), default=THINK)
    ap.add_argument("--url", default=llm_provider.OLLAMA_URL)
    a = ap.parse_args(argv)
    try:
        res = run(a.packet, url=a.url, num_predict=a.num_predict, think=a.think)
    except RunRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1))
    return 0 if res["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())

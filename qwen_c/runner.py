"""runner.py - one `qwen_c` run over one frozen packet: its tasks, their errors and their records (SPEC_m3m_qwen_pipeline.md section 6).

    python -m qwen_c.runner <packet.json> [--num-predict N] [--think low|medium|high] [--url ...] [--tasks a,b] [--seed-base N]

The model is called through ollama_raw.chat directly (config.json `depth_provider` is not read or changed), with our own SYSTEM
message (tasks.SYSTEM) and `think` passed as the pinned template expects (ollama_raw.think_kwargs).

TASKS RUN (3N, SPEC_m3n_event_validation.md section 3): all of tasks.TASKS by default, or only the `--tasks` / `task_ids` given (a comma
list; each one of tasks.TASKS, no duplicates), always in tasks.TASKS order. The manifest and analysis.json record `tasks_requested`. The
seed of a task is still the seed base + its index in tasks.TASKS (not in the requested list), so a task has the same seed in a subset
run as in a full run. `thesis_change` is run, or recorded as not applicable, only when it is requested; the prior run is looked up only
then. The run is `complete` when every requested task is ok (`not_applicable_no_prior` aside); a run in which no requested task is
applicable (only thesis_change, with no prior) is `failed`, not complete.

PER TASK (TASK_TIMEOUT_S per call; seed = the run's seed base + the task index in tasks.TASKS, 0-based):
    PREFLIGHT (ruling 4.2): a rendered prompt whose characters / CHARS_PER_TOKEN + num_predict exceed num_ctx is not sent ->
    `context_overflow` (this holds for a malformed-retry prompt too);
    a reply is parsed (parse_reply) and checked (contract.check_task) -> `ok`; a reply that does not parse or has the wrong shape (an
    empty reply, no claims and no unknowns, is one: ruling 4.1) gets one retry at seed + RETRY_SEED_OFFSET with tasks.RETRY_LINE
    appended, then `malformed`; the cause names done_reason "length" (the reply was cut at num_predict; ruling 4.6);
    a timeout -> `timeout`, no retry;
    HTTP 5xx, a connection error, or an HTTP 200 that carries "error" or an empty response with done not true (ruling 4.6) ->
    ops.wait_unloaded, then one retry (same prompt and seed), else `infra_error` with the cause;
    when wait_unloaded does not confirm the model is unloaded there is no retry (its own contract: never load on top of it);
    an HTTP 4xx, a refusal of ollama_raw other than overflow, or an unreadable response -> `infra_error`, no retry;
    ollama_raw's context_overflow, or the POST-CHECK prompt_eval_count + eval_count >= num_ctx - 1 (or a reply without
    prompt_eval_count, which cannot be checked) -> `context_overflow`, no retry;
    thesis_change with no prior run -> `not_applicable_no_prior`, not sent; with a prior run whose records do not recompute ->
    `infra_error`; with a prior run that has neither growth_thesis nor risks ok, or no supported claim in them to compare ->
    `prior_unusable` (ruling 4.4), not sent. Only the prior's supported claims are points (ruling 3.4); a claim naming another point is
    a shape error and the points no claim names are recorded as `points_not_addressed` (ruling 4.3).

RUN STATUS: `complete` when every applicable requested task is `ok`; `failed` when none is; otherwise `analysis_incomplete` with
`incomplete_tasks` (`prior_unusable` is applicable and not ok). analysis.json, the ledger line and the result carry `support_summary`
{claims, supported, unsupported} over every stored claim (ruling 4.1), so a `complete` run whose claims are all unsupported is visible.
`run()` never raises once the run directory exists: an unexpected error finishes the run as `failed` with the cause.
A precondition that fails before that raises RunRefused and writes nothing: an unreadable or wrong packet, a bad option, another model
resident on the Ollama server per /api/ps (`gpu_busy`) or /api/ps unreadable (`gpu_state_unreadable`) (ruling 6.3), or /api/show
not giving the model's parameters (`model_show_failed`), which the manifest records as the sampling in force (ruling 6.4). A process
crash leaves `status: "running"` and no `finished_at`; read_ledger reports it as `crashed`.

THE LEDGER (ruling 4.5). find_prior reads read_ledger, so a finished run whose ledger line is missing (a crash between the manifest and
the ledger) is still found. A torn LAST line of ledger.jsonl (a crashed append) is skipped by the readers and reported by read_ledger
as a `torn_ledger_line` row; a line that does not parse anywhere else raises. While the last line is torn, a run does not append its
line (that would bury the torn line mid-file): the manifest records `ledger_not_appended` and read_ledger lists the run from its
directory.

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
NUM_CTX = 98304                               # ruling 4.2: the value rs2 already runs on this card
CHARS_PER_TOKEN = 2.5                         # ruling 4.2: the preflight's estimate
NUM_PREDICT = 12288
THINK = "medium"
SEED_BASE = 1000
RETRY_SEED_OFFSET = 50000
TASK_TIMEOUT_S = 1800
KIS_HALT_STATE = "not_resolvable_in_rs2"
STATUSES = ("ok", "malformed", "timeout", "infra_error", "context_overflow", "not_applicable_no_prior", "prior_unusable")


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


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def reply_problem(resp, num_ctx):
    """(kind, detail) for a reply that must not be read as the model's answer, else None. In order: an HTTP 200 carrying "error", or
    an empty response with done not true, is infra_retry (ruling 4.6); prompt_eval_count + eval_count >= num_ctx - 1, or no
    prompt_eval_count to check, is context_overflow (ruling 4.2: Ollama cuts the front of the prompt before evaluating it)."""
    resp = resp or {}
    if resp.get("error"):
        return "infra_retry", f"HTTP 200 with an error: {str(resp['error'])[:2000]}"
    msg = resp.get("message") or {}
    if not msg.get("content") and not msg.get("thinking") and not msg.get("tool_calls") and resp.get("done") is not True:
        return "infra_retry", f"HTTP 200 with an empty response and done {resp.get('done')!r}"
    n, g = resp.get("prompt_eval_count"), resp.get("eval_count")
    if not _int(n):
        return "context_overflow", f"post-check: the reply has no prompt_eval_count ({n!r}), so a truncated prompt cannot be ruled out"
    used = n + (g if _int(g) and g > 0 else 0)
    if used >= num_ctx - 1:
        return "context_overflow", (f"post-check: prompt_eval_count {n} + eval_count {g} = {used} >= num_ctx - 1 = {num_ctx - 1}: "
                                    f"the front of the prompt may have been truncated")
    return None


# ---------------------------------------------------------------- the prior run (thesis_change)

def _read_jsonl(path, problems=None):
    """The rows (objects) of a JSON-lines file. A LAST non-blank line that is not a JSON object (a torn append) is skipped and recorded
    in `problems` as {"file", "line", "detail"}; such a line anywhere else raises ValueError."""
    rows = []
    if not Path(path).exists():
        return rows
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    last = max((i for i, s in enumerate(lines) if s.strip()), default=-1)
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {i + 1} is a {type(row).__name__}, not an object")
        except ValueError as e:
            if i != last:
                raise ValueError(f"{path}: line {i + 1} of {len(lines)} is torn or not an object: {e}") from e
            if problems is not None:
                problems.append({"file": str(path), "line": i + 1, "detail": f"torn last line skipped: {line[:200]!r}"})
            continue
        rows.append(row)
    return rows


def _ledger_tail(path):
    """"ok", "needs_newline" (the last line is whole but has no newline) or "torn" (the last line is not a JSON object)."""
    p = Path(path)
    data = p.read_bytes() if p.exists() else b""
    if not data.strip():
        return "ok"
    tail = data.decode("utf-8", "replace").strip().splitlines()[-1]
    try:
        if not isinstance(json.loads(tail), dict):
            return "torn"
    except ValueError:
        return "torn"
    return "ok" if data.endswith(b"\n") else "needs_newline"


def find_prior(root, ticker, T):
    """(prior, problem). The prior run is the newest finished run (complete or analysis_incomplete) in read_ledger (the ledger's lines,
    then the finished runs whose line is missing) for this ticker with a decision time before T (the later row wins among equal
    times); an older run is never used in its place. prior is {run_id, decision_time_utc, growth_thesis, risks, tasks_used,
    tasks_missing, ledger_missing, manifest_sha256, analysis_sha256} or None. problem is None or {"kind", "detail"}: kind
    "unverifiable" when its records do not recompute or cannot be read, or a run without a ledger line has no finished_at
    (thesis_change becomes infra_error), "no_ok_tasks" when neither its growth_thesis nor its risks is ok (thesis_change becomes
    prior_unusable)."""
    t = _parse_t(T)
    rows = [(i, r) for i, r in enumerate(read_ledger(root))
            if r.get("ticker") == ticker and r.get("status") in ("complete", "analysis_incomplete")
            and _parse_t(r.get("T")) is not None and t is not None and _parse_t(r.get("T")) < t]
    if not rows:
        return None, None
    _, r = max(rows, key=lambda x: (_parse_t(x[1]["T"]), x[0]))
    d = Path(root) / "runs" / r["run_id"]
    missing_line = bool(r.get("ledger_missing"))
    try:
        man_bytes = (d / "manifest.json").read_bytes()
        if missing_line:
            man_sha = sha256_bytes(man_bytes)              # no ledger line to check it against: the manifest as found
        elif sha256_bytes(man_bytes) != r.get("manifest_sha256"):
            return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: manifest.json does not match its ledger sha256"}
        else:
            man_sha = r["manifest_sha256"]
        man = json.loads(man_bytes.decode("utf-8"))
        if missing_line and not man.get("finished_at"):
            return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: no ledger line and no finished_at"}
        if sha256_file(d / "analysis.json") != man.get("analysis_sha256"):
            return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: analysis.json does not match its manifest sha256"}
        an = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, {"kind": "unverifiable", "detail": f"prior run {r['run_id']}: records unreadable: {type(e).__name__}: {e}"}
    used = [k for k in ("growth_thesis", "risks") if (an.get("tasks") or {}).get(k, {}).get("status") == "ok"]
    if not used:
        return None, {"kind": "no_ok_tasks", "detail": f"prior run {r['run_id']}: neither growth_thesis nor risks is ok"}
    prior = {"run_id": r["run_id"], "decision_time_utc": an.get("decision_time_utc"), "tasks_used": used,
             "tasks_missing": {k: (an.get("tasks") or {}).get(k, {}).get("status", "absent")
                               for k in ("growth_thesis", "risks") if k not in used},
             "ledger_missing": missing_line, "manifest_sha256": man_sha, "analysis_sha256": man["analysis_sha256"]}
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


# ---------------------------------------------------------------- the server preflights (rulings 6.3 and 6.4)

def gpu_preflight(url):
    """The model names /api/ps lists; raises RunRefused when any model other than MODEL is resident (`gpu_busy`) or the list cannot
    be read (`gpu_state_unreadable`). MODEL itself may be resident."""
    loaded = ops.ollama_loaded(url)
    if loaded is None:
        raise RunRefused("gpu_state_unreadable: /api/ps could not be read, so no other model can be ruled out")
    other = [n for n in loaded if n not in (MODEL, MODEL + ":latest")]
    if other:
        raise RunRefused(f"gpu_busy: another model is loaded on the Ollama server: {', '.join(map(str, other))}")
    return loaded


def model_show(url):
    """{parameters, details, modified_at, show_sha256} of MODEL from /api/show: the Modelfile's parameters (the sampling in force,
    since the runner sets none). Raises RunRefused (`model_show_failed`) when it cannot be read or holds no parameters."""
    req = urllib.request.Request(url.rsplit("/api/", 1)[0] + "/api/show", data=json.dumps({"model": MODEL}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        show = json.loads(data.decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - any failure is the same refusal, with its cause
        raise RunRefused(f"model_show_failed: {type(e).__name__}: {e}") from e
    params = show.get("parameters") if isinstance(show, dict) else None
    if not isinstance(params, str) or not params.strip():
        raise RunRefused("model_show_failed: /api/show gives no parameters, so the sampling in force cannot be recorded")
    return {"parameters": params, "details": show.get("details"), "modified_at": show.get("modified_at"),
            "show_sha256": sha256_bytes(data)}


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

def _run_task(task, idx, packet, prior, opts, url, run_dir, man_prompts, point_ids=None):
    """(analysis record, manifest record) of one task. `point_ids` are the earlier point ids of thesis_change."""
    seed0 = opts["seed"] + idx
    attempts, retry, seed = [], False, seed0
    retried_malformed = retried_infra = False
    t_task = time.monotonic()
    last_check = None
    extra = (point_ids,) if task == "thesis_change" else ()
    while True:
        n = len(attempts) + 1
        msgs = tasks.messages(task, packet, prior, retry=retry)
        prompt = ollama_raw.render_prompt(ollama_raw.template_messages(msgs), None, opts["think"])
        pname = f"{task}_retry.txt" if retry else f"{task}.txt"
        if pname not in man_prompts:
            man_prompts[pname] = _write_json_text(run_dir / "prompts" / pname, prompt)
        body = {"model": MODEL, "stream": False, "think": opts["think"], "messages": msgs,
                "options": {"num_ctx": opts["num_ctx"], "num_predict": opts["num_predict"], "seed": seed}}
        estimate = len(prompt) / CHARS_PER_TOKEN + opts["num_predict"]
        if estimate > opts["num_ctx"]:
            kind, resp, secs = "context_overflow", None, 0.0
            detail = (f"preflight: {len(prompt)} prompt characters / {CHARS_PER_TOKEN} + num_predict {opts['num_predict']} = "
                      f"{estimate:.0f} > num_ctx {opts['num_ctx']}: not sent")
        else:
            t0 = time.monotonic()
            with turn_log.logging_to(run_dir / "turns", task):
                kind, resp, detail = call(body, url, TASK_TIMEOUT_S)
            secs = round(time.monotonic() - t0, 3)
            if kind == "reply":
                kind, detail = reply_problem(resp, opts["num_ctx"]) or (kind, detail)
        outcome = kind
        if kind == "reply":
            obj, perr = parse_reply(((resp or {}).get("message") or {}).get("content"))
            last_check = contract.check_task(task, obj, packet, *extra) if perr is None else None
            if last_check is not None and last_check["status"] == "ok":
                outcome = "ok"
            else:
                outcome = "malformed"
                detail = perr or "; ".join(last_check["shape_errors"])
                if (resp or {}).get("done_reason") == "length":
                    detail += f"; done_reason is length: the reply was cut at num_predict {opts['num_predict']}"
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
        rec.update({k: last_check[k] for k in ("claims", "unknowns", "dropped_fields", "support_counts", "points_not_addressed")
                    if k in last_check})
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
    if "points_not_addressed" in rec:
        mrec["points_not_addressed"] = rec["points_not_addressed"]
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


def _check_tasks(task_ids):
    """The requested tasks as a tuple in tasks.TASKS order (all of them when `task_ids` is None); raises RunRefused for an empty list, a
    task that is not one of tasks.TASKS, or a task named twice."""
    if task_ids is None:
        return tuple(tasks.TASKS)
    if isinstance(task_ids, str) or not isinstance(task_ids, (list, tuple)) or not task_ids:
        raise RunRefused(f"tasks must be a non-empty list of task ids, got {task_ids!r}")
    bad = [t for t in task_ids if t not in tasks.TASKS]
    if bad:
        raise RunRefused(f"unknown task id(s) {bad!r}: each must be one of {', '.join(tasks.TASKS)}")
    if len(set(task_ids)) != len(task_ids):
        raise RunRefused(f"a task is named twice in {list(task_ids)!r}")
    return tuple(t for t in tasks.TASKS if t in task_ids)


def run(packet_path, *, url=llm_provider.OLLAMA_URL, num_ctx=NUM_CTX, num_predict=NUM_PREDICT, think=THINK, seed=SEED_BASE,
        task_ids=None):
    """One run over one packet. `seed` is the seed base (a task's seed is seed + its index in tasks.TASKS); `task_ids` are the tasks to run
    (None: all). Returns {run_id, run_dir, status, incomplete_tasks, support_summary, manifest_sha256, ledger_appended}."""
    _check_opts(num_ctx, num_predict, think, seed)
    requested = _check_tasks(task_ids)
    packet, src = load_packet(packet_path)
    loaded = gpu_preflight(url)
    show = model_show(url)
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
        "model": {**llm_provider.ollama_serving(MODEL), "provider": "ollama_raw", "tag": MODEL, "show": show},
        "gpu_preflight": {"loaded": loaded},
        "template_sha256": ollama_raw.TEMPLATE_SHA256, "system_sha256": sha256_bytes(tasks.SYSTEM.encode("utf-8")),
        "tasks_requested": list(requested),
        "options": {**opts, "seed_base": seed, "seeds": {t: seed + i for i, t in enumerate(tasks.TASKS)}, "retry_seed_offset": RETRY_SEED_OFFSET,
                    "task_timeout_s": TASK_TIMEOUT_S, "chars_per_token": CHARS_PER_TOKEN,
                    "sampling": "the Modelfile's defaults (not overridden): model.show.parameters",
                    "differs_from_defaults": sorted(k for k in opts if opts[k] != defaults[k])},
        "qwen_c": {"git_commit": commit, "dirty": dirty}, "kis_halt": KIS_HALT_STATE,
        "started_at": now_utc(), "status": "running", "prompts": {}, "tasks": {},
    }
    results = {}
    try:
        man["ollama_version"] = ollama_raw.ollama_version(url.rsplit("/api/", 1)[0])
        _write_bytes(run_dir / "packet.json", src)
        back = (run_dir / "packet.json").read_bytes()
        if sha256_bytes(back) != sha256_bytes(src) or sha256_bytes(canonical_bytes(json.loads(back.decode("utf-8")))) != packet_sha:
            raise RuntimeError("packet.json copy does not recompute")
        prior, prior_problem = find_prior(root, ticker, T) if "thesis_change" in requested else (None, None)
        point_ids = [p for p, _ in tasks.prior_points(prior)] if prior else []
        if prior and not point_ids:                     # nothing to compare: the task is not sent and is not ok
            prior_problem = {"kind": "no_supported_points",
                             "detail": f"prior run {prior['run_id']}: no supported growth_thesis or risks claim to compare"}
        man["prior_run"] = ({**{k: prior[k] for k in ("run_id", "decision_time_utc", "tasks_used", "tasks_missing", "ledger_missing",
                                                      "manifest_sha256", "analysis_sha256")},
                             "point_ids": point_ids, "points_left_out": tasks.prior_left_out(prior)} if prior else None)
        if prior_problem:
            man["prior_run_problem"] = prior_problem
        _write_json(run_dir / "manifest.json", man)
        for idx, task in enumerate(tasks.TASKS):
            if task not in requested:
                continue
            if task == "thesis_change" and (prior is None or prior_problem):
                st = {None: "not_applicable_no_prior", "unverifiable": "infra_error"}.get(
                    prior_problem and prior_problem["kind"], "prior_unusable")
                cause = prior_problem["detail"] if prior_problem else "no prior run for this ticker before T"
                results[task] = ({"status": st, "attempts": 0, "cause": cause, "claims": [], "unknowns": []},
                                 {"status": st, "seed": seed + idx, "seconds": 0.0, "attempts": [], "cause": cause})
                man["tasks"][task] = results[task][1]
                continue
            try:
                results[task] = _run_task(task, idx, packet, prior, opts, url, run_dir, man["prompts"], point_ids)
            except Exception as e:  # noqa: BLE001 - a task's own failure is a status, never a raise past run()
                cause = f"runner exception: {type(e).__name__}: {e}"
                results[task] = ({"status": "infra_error", "attempts": 0, "cause": cause, "claims": [], "unknowns": []},
                                 {"status": "infra_error", "seed": seed + idx, "seconds": 0.0, "attempts": [], "cause": cause})
            man["tasks"][task] = results[task][1]
            _write_json(run_dir / "manifest.json", man)
        applicable = [t for t in requested if results[t][0]["status"] != "not_applicable_no_prior"]
        not_ok = {t: results[t][0]["status"] for t in applicable if results[t][0]["status"] != "ok"}
        if not applicable:                              # only thesis_change was requested and there is no prior: nothing was analysed
            status, not_ok = "failed", {t: results[t][0]["status"] for t in requested}
        elif not not_ok:
            status = "complete"
        elif len(not_ok) == len(applicable):
            status = "failed"
        else:
            status = "analysis_incomplete"
        analysis = {
            "contract": contract.CONTRACT, "prompt_version": tasks.PROMPT_VERSION, "run_id": run_id, "ticker": ticker,
            "decision_time_utc": T, "packet_sha256": packet_sha, "tasks_requested": list(requested), "status": status,
            "incomplete_tasks": not_ok,
            "support_summary": support_summary(results),
            "note": "A claim whose support is not 'supported' is not a verified value; it stays visible with its reason.",
            "tasks": {t: results[t][0] for t in requested},
        }
        man["analysis_sha256"] = _write_json(run_dir / "analysis.json", analysis)
        man["status"], man["incomplete_tasks"] = status, not_ok
    except Exception as e:  # noqa: BLE001 - see the module docstring
        status = man["status"] = "failed"
        man["cause"] = f"runner exception: {type(e).__name__}: {e}"
        man["incomplete_tasks"] = {t: man["tasks"].get(t, {}).get("status", "not_run") for t in requested}
    summary = support_summary(results)
    turns = run_dir / "turns"
    man["turns"] = {p.relative_to(run_dir).as_posix(): sha256_file(p) for p in sorted(turns.glob("*.json"))} if turns.is_dir() else {}
    ledger = root / "ledger.jsonl"
    tail = _ledger_tail(ledger)
    if tail == "torn":
        man["ledger_not_appended"] = "the last line of ledger.jsonl is torn: appending would bury it mid-file; repair it by hand"
    man["finished_at"] = now_utc()
    man_sha = _write_json(run_dir / "manifest.json", man)
    line = {"run_id": run_id, "ticker": ticker, "T": T, "packet_sha256": packet_sha, "status": status, "support_summary": summary,
            "manifest_sha256": man_sha}
    if tail != "torn":
        root.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(("\n" if tail == "needs_newline" else "") + json.dumps(line, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return {"run_id": run_id, "run_dir": str(run_dir), "status": status, "incomplete_tasks": man.get("incomplete_tasks", {}),
            "support_summary": summary, "manifest_sha256": man_sha, "ledger_appended": tail != "torn"}


def support_summary(results):
    """{claims, supported, unsupported} over every stored claim of a run's task records (ruling 4.1)."""
    claims = [c for rec, _ in results.values() for c in rec.get("claims") or []]
    ok = sum(1 for c in claims if c.get("support") == contract.SUPPORTED)
    return {"claims": len(claims), "supported": ok, "unsupported": len(claims) - ok}


# ---------------------------------------------------------------- the ledger reader

def read_ledger(root=None):
    """Every run: the ledger's lines, plus each run directory the ledger does not list, as `crashed` when its manifest is missing,
    unreadable or still `running` with no `finished_at`, else with its manifest status and `ledger_missing: true`. A torn last line
    of the ledger is reported as a row {"run_id": None, "status": "torn_ledger_line", "line", "detail"} (ruling 4.5)."""
    root = Path(root or M3M_DIR)
    problems = []
    rows = _read_jsonl(root / "ledger.jsonl", problems)
    seen = {r.get("run_id") for r in rows}
    out = list(rows) + [{"run_id": None, "status": "torn_ledger_line", "line": p["line"], "detail": p["detail"]} for p in problems]
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
    ap.add_argument("--tasks", help="comma list of the tasks to run (default: all of %s), run in that order" % ", ".join(tasks.TASKS))
    ap.add_argument("--seed-base", type=int, default=SEED_BASE, help="a task's seed is this plus its index in the task list")
    a = ap.parse_args(argv)
    try:
        res = run(a.packet, url=a.url, num_predict=a.num_predict, think=a.think, seed=a.seed_base,
                  task_ids=[t.strip() for t in a.tasks.split(",")] if a.tasks is not None else None)
    except RunRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1))
    return 0 if res["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())

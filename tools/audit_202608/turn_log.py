"""turn_log.py - the per-turn log of the ollama_raw provider (SPEC revision 26, section 0). Additive files only; it never changes a request.

A caller that wants its model turns logged wraps the call in `with turn_log.logging_to(directory, stage):`. While that is in force,
ollama_raw.chat() writes, for every turn it makes, `<directory>/<stage>_<n>.json` (n counts from 1 within the directory and stage) with

    prompt_sha256        sha256 of the rendered prompt text exactly as POSTed
    system_sha256        sha256 of the SYSTEM text in force (a system message of the body, else the model tag's SYSTEM layer)
    template_sha256      the pinned chat template's sha256
    completion           the raw completion: the `response` text as returned, with the `thinking` field (when the reply has one) beside it
    prompt_eval_count, eval_count, done_reason, seed, options, model

and, once per directory, `<directory>/run_hashes.json` with the SYSTEM and template sha256 (rewritten only when a value differs, so a
mid-run change of either is visible as the file's `changes` list). Outside `logging_to` nothing is written. A write failure is reported
on stderr and never raised: losing a log must not lose a GPU run.
"""
import contextlib
import hashlib
import json
import sys
from pathlib import Path

_ACTIVE = None          # (Path, stage) while a `logging_to` block is in force


@contextlib.contextmanager
def logging_to(directory, stage):
    global _ACTIVE
    previous = _ACTIVE
    _ACTIVE = (Path(directory), str(stage))
    try:
        yield
    finally:
        _ACTIVE = previous


def active():
    return _ACTIVE


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def next_index(directory, stage):
    d = Path(directory)
    n = 0
    if d.is_dir():
        for p in d.glob(f"{stage}_*.json"):
            tail = p.stem[len(stage) + 1:]
            if tail.isdigit():
                n = max(n, int(tail))
    return n + 1


def log_turn(request, response, system_text, template_sha256, model, options):
    """Write one turn. `request` is the dict POSTed (its `prompt` is hashed), `response` the parsed reply. Never raises."""
    act = _ACTIVE
    if act is None:
        return None
    directory, stage = act
    try:
        directory.mkdir(parents=True, exist_ok=True)
        n = next_index(directory, stage)
        system_sha = sha256_text(system_text)
        rec = {
            "stage": stage, "n": n, "model": model,
            "prompt_sha256": sha256_text(request.get("prompt")),
            "system_sha256": system_sha, "template_sha256": template_sha256,
            "completion": {"response": response.get("response"), **({"thinking": response["thinking"]} if response.get("thinking") else {})},
            "prompt_eval_count": response.get("prompt_eval_count"), "eval_count": response.get("eval_count"),
            "done_reason": response.get("done_reason"),
            "seed": (options or {}).get("seed"), "options": options,
        }
        path = directory / f"{stage}_{n}.json"
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        _note_hashes(directory, system_sha, template_sha256, model)
        return path
    except Exception as e:      # noqa: BLE001 - see the module docstring
        print(f"[turn_log] could not write the turn log under {directory}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None


def _note_hashes(directory, system_sha, template_sha, model):
    p = directory / "run_hashes.json"
    cur = {"system_sha256": system_sha, "template_sha256": template_sha, "model": model}
    if p.exists():
        doc = json.loads(p.read_text(encoding="utf-8"))
        if all(doc.get(k) == v for k, v in cur.items()):
            return
        doc.setdefault("changes", []).append(cur)
    else:
        doc = dict(cur)
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")

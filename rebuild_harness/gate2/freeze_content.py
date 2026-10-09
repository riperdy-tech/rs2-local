"""freeze_content.py - the contents of the gate-2 freeze (registration section 1: "Muse settings, frozen in the gate-2 freeze file").

    python -m rebuild_harness.gate2.freeze_content collect [--no-model-hash] [--state-dir DIR]    print the contents (writes nothing)
    python -m rebuild_harness.gate2.freeze_content verify  [--state-dir DIR]                      the problems between the freeze file and the tree as it is now (empty: it holds)
    python -m rebuild_harness.gate2.freeze_content write --confirm-write-the-freeze               write freeze/gate2_freeze.json ONCE (only when the coordinator says so)

THE CONTENTS.
  engine        the frozen gate-1 engine: commit c7d7a4f, the sha256 of every engine file on disk, and the proof that each equals the file at that commit (the engine is
                imported by this job and never modified);
  muse          the GGUF and the drafter (path, size, sha256), llama.cpp build b11272 (the build folder's manifest sha256), the gate-2 server command line (and the pinned production
                line, with the window as the only difference), the server's pinned sampling flags, the context (32768), the reasoning prefix ("Reasoning strength: xhigh"), the sha256 of the
                system text the runner sends (prefix + prompts/system.txt), the sha256 of every prompt template and of inputs.json, the pack v2 template version, the runner version, the
                request fields (model, messages, stream, max_tokens, seed: no sampling field) and the cap on generated tokens with the context guard's constants;
  code          the sha256 of the Muse layer, the pipeline, the gate-2 harness files, the gate-1 harness and valuation modules it imports, the Stage 2 layer and the forensic analytics;
  stage2        the Stage 2 configuration of Addenda V and W for BOTH arms: V1 (mean), V2 (the survival model: its coefficients and training window for each replay date, the hashes of the
                training data, the file of the company-dates' probabilities), V3 (commodity out of scope);
  inputs        what the runner reads: the point-in-time store, the D5 daily closes and the monthly file behind them, Damodaran's files, the priors vintages of year(T) - 1, the crosswalk, the
                SIC headers and the SEC submissions archive.  FULL content hashes are taken when the freeze is written; `verify` (run at every runner start) re-takes only the cheap
                fingerprint (file count, bytes, newest modification time of a tree; size and modification time of a single file) so a restart does not read 20 GB;
  seeds         the sample seed (20261007) and the draw rule, the engine draw seed rule (`gate1.seed_for`), the model seed rule (the same value per company-date), the bootstrap seeds;
  sample        the sample file and its sha256;
  gate1_freeze  the gate-1 freeze file's sha256, when it exists (it names the store, prices, Damodaran files, priors vintages, crosswalk, headers and engine configuration);
  packages      the Python and package versions.

`collect` hashes the 20 GB model unless told not to (`--no-model-hash` reads the pins record instead).  Nothing here starts a server or reads a price.  The freeze is written
only by `write --confirm-write-the-freeze`, which refuses when the file exists; `verify` is what the runner calls before it runs anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config

ENGINE_COMMIT = "c7d7a4f"
CODE_GLOBS = ("valuation/*.py", "valuation/muse/*.py", "valuation/muse/prompts/*", "rebuild_harness/*.py", "rebuild_harness/gate2/*.py", "rebuild_harness/gate2/*.vbs", "rebuild_harness/gate2/*.ps1",
              "rebuild_harness/stage2/*.py", "rebuild_harness/forensics/*.py")
REQUEST_FIELDS = ["model", "messages", "stream", "max_tokens", "seed", "response_format"]   # response_format: the JSON schema of the answer (Addendum AC 1)


def _git(*args, repo=config.REPO) -> bytes:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def _sha_text_file(p) -> str:
    """sha256 with CRLF read as LF (the holdout lock's rule: a Windows checkout and the git blob of the same text agree)."""
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def engine_files() -> List[Path]:
    from rebuild_harness import gate1_run
    return list(gate1_run.GATE1_FILES)


def engine_section(repo=config.REPO) -> dict:
    commit = _git("rev-parse", ENGINE_COMMIT, repo=repo).decode().strip()
    files, equal, differs = {}, True, []
    for p in engine_files():
        rel = Path(p).resolve().relative_to(Path(repo).resolve()).as_posix()
        on_disk = _sha_text_file(p)
        at_commit = hashlib.sha256(_git("show", f"{commit}:{rel}", repo=repo).replace(b"\r\n", b"\n")).hexdigest()
        files[rel] = on_disk
        if on_disk != at_commit:
            equal = False
            differs.append(rel)
    return {"commit": commit, "files_sha256": files, "every_file_equals_the_file_at_the_commit": equal, "files_that_differ": differs}


def code_section(repo=config.REPO) -> dict:
    out = {}
    for g in CODE_GLOBS:
        for p in sorted(Path(repo).glob(g)):
            if p.is_file() and "__pycache__" not in p.parts:
                out[p.relative_to(repo).as_posix()] = _sha_text_file(p)
    return out


def muse_section(state_dir=None, *, cfg: Optional[dict] = None, hash_model: bool = True, build_cmd=None) -> dict:
    from valuation.muse import prompting, schema
    from valuation.muse.runner import REASONING_PREFIX, RUNNER_VERSION as MUSE_RUNNER_VERSION
    from . import guard, server
    cfg = cfg or server.load_cfg()
    wd = server.window_difference(cfg, build_cmd)
    sysmsg = REASONING_PREFIX + prompting.system_text()
    if hash_model:
        model = {"path": cfg["model_path"], "size": Path(cfg["model_path"]).stat().st_size, "sha256": server.sha256_file(cfg["model_path"])}
        drafter = {"path": cfg["drafter_path"], "size": Path(cfg["drafter_path"]).stat().st_size, "sha256": server.sha256_file(cfg["drafter_path"])}
    else:
        pins = json.loads(server.pins_path(state_dir).read_text(encoding="utf-8"))
        model, drafter = {k: pins["model"][k] for k in ("path", "size", "sha256")}, {k: pins["drafter"][k] for k in ("path", "size", "sha256")}
    return {"model": model, "drafter": drafter, "model_pin_in_config": cfg["model_sha256"], "drafter_pin_in_config": cfg["drafter_sha256"],
            "llama_cpp": {"build": cfg.get("build"), "build_manifest_sha256": cfg["build_manifest_sha256"], "server_exe": cfg["server_exe"]},
            "server": {"pinned_cmdline": wd["pinned_cmdline"], "pinned_cmdline_sha256": wd["pinned_cmdline_sha256"], "gate2_cmdline": wd["gate2_cmdline"],
                       "gate2_cmdline_sha256": wd["gate2_cmdline_sha256"], "pinned_window": config.PINNED_WINDOW, "window": config.CONTEXT,
                       "difference_from_the_pinned_line": "the context window (-c) only",
                       "sampling": "server flags --temp 1.0 --top-p 0.95 --top-k 64 --min-p 0 (never sent per request)"},
            "context": config.CONTEXT, "reasoning_prefix": REASONING_PREFIX, "system_message_sha256": hashlib.sha256(sysmsg.encode("utf-8")).hexdigest(),
            "system_file_sha256": prompting.file_sha256(prompting.PROMPT_DIR / "system.txt") if hasattr(prompting, "PROMPT_DIR") else None,
            "prompt_template_hashes": prompting.prompt_hashes(), "pack_version": schema.PACK_VERSION, "muse_runner_version": MUSE_RUNNER_VERSION,
            "gate2_runner_version": config.RUNNER_VERSION, "request_fields": REQUEST_FIELDS, "max_tokens_cap": config.MAX_TOKENS,
            "context_guard": {"margin_tokens": config.CTX_MARGIN_TOKENS, "floor_tokens": config.CTX_FLOOR_TOKENS, "chars_per_token": config.CHARS_PER_TOKEN},
            "width_factors": schema.WIDTH_FACTORS}


def seeds_section() -> dict:
    from . import sample
    return {"sample_seed": config.SEED, "draw_rule": sample.RULE, "per_date": config.PER_DATE, "dates": list(config.DATES), "pilot": f"the first {config.PILOT_N} of {config.PILOT_DATE}'s drawn order",
            "masked_control": f"{config.MASKED_N} company-dates by random.Random('{config.SEED}:{config.MASKED_SEED_LABEL}')",
            "engine_draw_seed_rule": "valuation.gate1.seed_for(cik, asof) = (int(cik) * 1000003 + asof.toordinal()) % (2**31 - 1): one per company and date, shared by both arms",
            "model_seed_rule": "the same value per company-date (sent as `seed` in every request of the company-date)", "bootstrap_seed": config.BOOT_SEED,
            "bootstrap_draws": config.BOOT_DRAWS}


def packages_section() -> dict:
    out = {"python": platform.python_version()}
    for m in ("numpy", "pandas", "openpyxl"):
        try:
            out[m] = __import__(m).__version__
        except Exception:
            out[m] = None
    return out


def _tree_fp(root, exclude_top_level=()) -> dict:
    """The cheap fingerprint of a folder: file count, bytes, newest modification time (nanoseconds)."""
    n, total, newest = 0, 0, 0
    for dirpath, _d, files in os.walk(root):
        for f in files:
            if Path(dirpath, f).relative_to(root).parts[0] in exclude_top_level:
                continue
            st = os.stat(os.path.join(dirpath, f))
            n, total, newest = n + 1, total + st.st_size, max(newest, st.st_mtime_ns)
    return {"n_files": n, "bytes": total, "newest_mtime_ns": newest}


def _input_paths() -> dict:
    from rebuild_harness import gate1_run as g
    from valuation import discount_rate as vdr
    w = config.WORKSPACE
    return {"store": Path(g.DEFAULT_STORE), "id_map": Path(g.DEFAULT_IDMAP), "prices_daily": w / "data" / "prices_daily", "prices_monthly": Path(g.DEFAULT_PRICES),
            "damodaran": Path(vdr.default_root()), "crosswalk": Path(g.DEFAULT_CROSSWALK), "headers": Path(g.DEFAULT_HEADERS), "priors": w / "data" / "priors_v3",
            "submissions_zip": w / "data" / "sec_bulk" / "submissions.zip"}


def inputs_section(*, full: bool = False, gate1b_freeze: Optional[Path] = None) -> dict:
    """{"fingerprint": {...cheap...}} and, when `full`, {"full": {...content hashes...}, "equal_to_gate1b_freeze": {...}}.  Only the fingerprint is compared by `verify`."""
    from rebuild_harness import holdout
    paths = _input_paths()
    vint = sorted({int(d[:4]) - 1 for d in config.DATES})
    fkeys = ("id_map", "prices_monthly", "crosswalk", "headers", "submissions_zip")
    fp = {"store": _tree_fp(paths["store"]), "prices_daily": _tree_fp(paths["prices_daily"], ("_logs",)), "priors_vintages": {str(v): _tree_fp(paths["priors"] / str(v)) for v in vint},
          "damodaran": _tree_fp(paths["damodaran"]), "files": {k: {"bytes": paths[k].stat().st_size, "mtime_ns": paths[k].stat().st_mtime_ns} for k in fkeys}}
    out = {"paths": {k: str(v) for k, v in paths.items()}, "priors_vintages_used": vint, "fingerprint": fp}
    if full:
        full_h = {"store": holdout.tree_hash(paths["store"]), "prices_daily": holdout._price(paths["prices_daily"]), "damodaran": holdout._damodaran(paths["damodaran"]),
                  "priors_vintages": {str(v): holdout.tree_hash(paths["priors"] / str(v))["tree_sha256"] for v in vint},
                  "files": {k: {"sha256": holdout.file_sha256(paths[k])} for k in fkeys}}
        out["full"] = full_h
        if gate1b_freeze is not None and Path(gate1b_freeze).exists():
            c = json.loads(Path(gate1b_freeze).read_text(encoding="utf-8")).get("contents") or {}
            gp = c.get("price_snapshot") or {}
            out["equal_to_gate1b_freeze"] = {
                "store": (c.get("point_in_time_store") or {}).get("tree_sha256") == full_h["store"]["tree_sha256"],
                "prices_daily": gp.get("tree_sha256") == full_h["prices_daily"]["tree_sha256"],
                "damodaran": c.get("damodaran") == full_h["damodaran"],
                "priors_vintages_used": all((c.get("priors") or {}).get("vintages", {}).get(k) == v for k, v in full_h["priors_vintages"].items()),
                "crosswalk": (c.get("industry_crosswalk") or {}).get("sha256") == full_h["files"]["crosswalk"]["sha256"],
                "headers": (c.get("sic_headers") or {}).get("sha256") == full_h["files"]["headers"]["sha256"],
                "prices_monthly_fallback": (c.get("price_fallback") or {}).get("sha256") == full_h["files"]["prices_monthly"]["sha256"]}
    return out


def stage2_section(state_dir=None) -> dict:
    """The Stage 2 configuration (Addenda V, W): layers, the survival models of every replay date and the files they and the probabilities live in."""
    from . import stage2_layer as sl
    p = sl.stage2_paths(state_dir)
    doc = json.loads(p["models"].read_text(encoding="utf-8")) if p["models"].exists() else None
    return {"layers": sl.LAYERS, "out_of_scope_families": list(config.OUT_OF_SCOPE_FAMILIES),
            "engine_identical_to": "c7d7a4f (git diff c7d7a4f HEAD over valuation/engine_*, common.py, discount_rate.py, priors.py is empty)",
            "survival_models": None if doc is None else {"file": str(p["models"]), "sha256": sl.sha256_file(p["models"]), "settings": doc["settings"], "training_data": doc["training_data"],
                                                         "n_pool": doc["n_pool"], "models": doc["models"]},
            "survival_pfail": None if not p["pfail"].exists() else {"file": str(p["pfail"]), "sha256": sl.sha256_file(p["pfail"])}}


def collect(state_dir=None, *, cfg: Optional[dict] = None, hash_model: bool = True, build_cmd=None, gate1_freeze: Optional[Path] = None, full_inputs: bool = False) -> dict:
    from . import sample
    paths = config.state_paths(state_dir)
    sp = sample.sample_path(state_dir)
    smp = {"file": str(sp), "sha256": sample.sha256_file(sp) if sp.exists() else None}
    g1 = None
    if gate1_freeze is not None and Path(gate1_freeze).exists():
        g1 = {"path": str(gate1_freeze), "sha256": hashlib.sha256(Path(gate1_freeze).read_bytes()).hexdigest()}
    return {"registration": "REGISTRATION_gate2_DRAFT.md (approved 2026-10-07)", "collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "gate2_commit": _git("rev-parse", "HEAD").decode().strip(), "engine": engine_section(), "muse": muse_section(state_dir, cfg=cfg, hash_model=hash_model, build_cmd=build_cmd),
            "code": code_section(), "stage2": stage2_section(state_dir), "inputs": inputs_section(full=full_inputs, gate1b_freeze=gate1_freeze), "seeds": seeds_section(), "sample": smp,
            "gate1_freeze": g1, "packages": packages_section()}


def freeze_path(state_dir=None) -> Path:
    return config.state_paths(state_dir)["freeze"] / "gate2_freeze.json"


def write(state_dir=None, *, confirm: bool = False, **kw) -> dict:
    """Write the freeze, once.  Refuses without the explicit confirmation and when the file exists."""
    if not confirm:
        raise RuntimeError("the freeze is written only when the coordinator says so (--confirm-write-the-freeze)")
    p = freeze_path(state_dir)
    if p.exists():
        raise RuntimeError(f"{p} exists: a freeze is written once")
    doc = collect(state_dir, full_inputs=True, **kw)
    if not doc["engine"]["every_file_equals_the_file_at_the_commit"]:
        raise RuntimeError(f"the engine files differ from commit {ENGINE_COMMIT}: {doc['engine']['files_that_differ']}")
    if doc["sample"]["sha256"] is None:
        raise RuntimeError("no sample file: draw it before the freeze")
    if doc["stage2"]["survival_models"] is None or doc["stage2"]["survival_pfail"] is None:
        raise RuntimeError("no Stage 2 survival models / probabilities: build them (stage2_layer models, stage2_layer pfail) before the freeze")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, indent=1, sort_keys=True))
    return doc


def _walk_diff(a, b, path="") -> List[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}{k}: {'missing in the freeze' if k not in a else 'missing now'}")
            else:
                out += _walk_diff(a[k], b[k], f"{path}{k}.")
        return out
    return [] if a == b else [f"{path[:-1]}: frozen {str(a)[:60]!r}, now {str(b)[:60]!r}"]


def verify(state_dir=None, *, cfg: Optional[dict] = None, build_cmd=None) -> List[str]:
    """The problems between the freeze file and the tree now (empty: the freeze holds).  Cheap: the model's and the drafter's sha256 come from the pins record, whose own
    consistency with the files (size, modification time) the server start checks again."""
    p = freeze_path(state_dir)
    if not p.exists():
        return [f"no freeze file at {p} (the coordinator writes it before the pilot)"]
    frozen = json.loads(p.read_text(encoding="utf-8"))
    try:
        now = collect(state_dir, cfg=cfg, hash_model=False, build_cmd=build_cmd, gate1_freeze=Path(frozen["gate1_freeze"]["path"]) if frozen.get("gate1_freeze") else None)
    except Exception as e:
        return [f"the current contents cannot be collected: {type(e).__name__}: {e}"]
    problems = []
    for k in ("engine", "muse", "code", "stage2", "inputs", "seeds", "sample", "gate1_freeze", "packages"):
        if k == "packages":
            continue                                   # recorded, not enforced: a package patch release does not change a result the pins above did not already fix
        if k == "inputs":                              # only the cheap fingerprint is re-taken at a restart; the full content hashes were taken once, at the write
            problems += [f"inputs.fingerprint.{x}" for x in _walk_diff((frozen.get(k) or {}).get("fingerprint"), (now.get(k) or {}).get("fingerprint"))]
            continue
        problems += [f"{k}.{x}" for x in _walk_diff(frozen.get(k), now.get(k))]
    if not now["engine"]["every_file_equals_the_file_at_the_commit"]:
        problems.append(f"engine files differ from commit {ENGINE_COMMIT}: {now['engine']['files_that_differ']}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["collect", "verify", "write"])
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--no-model-hash", action="store_true")
    ap.add_argument("--confirm-write-the-freeze", action="store_true")
    ap.add_argument("--gate1-freeze", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        print(json.dumps(collect(a.state_dir, hash_model=not a.no_model_hash, gate1_freeze=a.gate1_freeze), indent=1, sort_keys=True))
    elif a.cmd == "verify":
        probs = verify(a.state_dir)
        print("\n".join(probs) if probs else "ok: the freeze holds")
        return 1 if probs else 0
    else:
        write(a.state_dir, confirm=a.confirm_write_the_freeze, hash_model=not a.no_model_hash, gate1_freeze=a.gate1_freeze)
        print(f"written: {freeze_path(a.state_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# RS2 Control Tower Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Model policy (operator preference):** spawn every implementation/review subagent with model `opus`; the Fable main loop only orchestrates and audits.

**Goal:** A remote admin control site ("control tower") inside the stock-screener Vercel app that shows the health of every RS2 rhythm, lets the operator trigger/pause/reroute them from anywhere, and automatically reroutes cloud-runnable rhythms to GitHub Actions when the PC is off — with explicit manual-recovery instructions for everything that cannot be automated.

**Architecture:** Three parts. (A) A PC-side `control_agent.py` in the rs2-local repo pushes a heartbeat + rhythm snapshot to Supabase every 5 minutes, polls a Supabase command queue for remote orders, keeps the Telegram bot alive, backs depth state up to a new private `rs2-state` repo, and fixes the missing SDF self-dispatch scheduled task. (B) A GitHub-OAuth-gated `/admin` page + `/api/admin/*` routes in stock-screener read that heartbeat, the committed freshness stamps, and the GitHub Actions API, and can dispatch whitelisted workflows or enqueue PC commands. (C) A freshness-gated `depth-cloud-backstop.yml` workflow in rs2-local runs the existing DeepSeek api_llm arm on GitHub-hosted runners when the PC misses depth sweeps, using state from `rs2-state`.

**Tech Stack:** Python 3.12 stdlib (PC agent, no new deps), Supabase PostgREST (already used by site), Next.js 14.2.3 App Router + TypeScript + Tailwind (site), GitHub Actions + GitHub REST API, Windows Task Scheduler.

## Global Constraints

- **Real money is live.** GitHub repo var `KIS_LEDGER=equal_llm` must NOT be changed by anything in this plan. The admin site must never offer KIS `env=real` + `execute=true` dispatch; only paper dry-runs and the `KIS_HALT` kill switch.
- **DD ≤ 15% hard constraint** on the KIS engagement — control tower is observability + routing only; it never alters trading logic.
- **Never publish from the shared dev tree** `C:\Users\riper\Downloads\Stock Screener\Stock Screener`. All pushes of depth artifacts go through the dedicated clone at `C:\Users\riper\Downloads\screener-publish` via `publish_overlay()` invariants (reset to origin/main, JSON-validate, abort on conflict, never `-X ours`).
- **No secrets in any repo.** PC secrets live only in `RS2 Local\.secrets.json` (gitignored). Cloud secrets live only as GitHub encrypted secrets / Vercel env vars. New key NAMES used in this plan: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (in `.secrets.json`); `GH_OAUTH_CLIENT_ID`, `GH_OAUTH_CLIENT_SECRET`, `ADMIN_GITHUB_LOGIN`, `ADMIN_SESSION_SECRET` (Vercel); reuse existing `GH_PAT`, `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (Vercel).
- **GitHub-hosted minutes budget:** private-repo free tier is 2000 min/month; every new cloud job must be freshness-gated (skip fast when nothing to do), mirroring the SDF preflight pattern.
- **Timestamp conventions (do not "fix" them):** `paper_ledgers.json.last_updated` and `chain_manifest.json.finished_at` are UTC with `Z`; `depth_overlay.json.generated_at` is NAIVE local Taipei time (UTC+08:00, no suffix). All consumers in this plan must parse naive stamps as `+08:00`.
- **Admin auth:** only GitHub account `riperdy-tech` may pass. Session = HMAC-signed httpOnly cookie, 30 days.
- **PC-side code style:** stdlib-only, mirrors `ops.py` patterns (re-read secrets per call, never raise out of a scheduled entry point, Telegram alert on failure).
- Repos: rs2-local = `riperdy-tech/rs2-local` at `C:\Users\riper\Downloads\RS2 Local`; screener = `riperdy-tech/stock-screener` at `C:\Users\riper\Downloads\Stock Screener\Stock Screener`; new private state repo = `riperdy-tech/rs2-state` at `C:\Users\riper\Downloads\rs2-state`.
- rs2-local has 13 modified tracked files from live work. **Do not `git add -A` in rs2-local.** Stage only the files each task names.

## Background facts the implementer needs (verified 2026-08-30)

- The SDF "PC self-dispatch primary" documented in `schedule-data-fetch.yml:4-8` **does not exist** — no scheduled task runs `gh workflow run`. The cloud backstop cron has silently been the only SDF path since 2026-08-26. Task 5 creates the missing task.
- **2026-08-30 (parallel session, same day):** `telegram_status_bot.py` is now the Supabase `ondemand_queue` bridge for the site's `/ondemand` Analyze button, and scheduled task `RS2-Telegram-Bot` (AtLogOn, auto-restart every 5 min ×999, registered via `register_bot_task.ps1`) keeps it alive. Screener commits `f142269c64` + `df0ab84547` are pushed/deployed (site password rotated `RSYS`→`poe`). Consequences for this plan: the control agent must NOT respawn the bot itself (the task's auto-restart owns that) — it monitors the task and offers a `bot_restart` command that restarts the TASK; and there is NO `ondemand` PC command (the site's `/api/ondemand` → `ondemand_queue` → bot bridge already covers remote on-demand requests end-to-end).
- Scheduled tasks `RS2-Depth-Orchestrator` (02:00 +8, repeat 4h) and `RS2-Orchestrator` (zombie — no-ops on `cache/PAUSED`) run as interactive-logon tasks. New tasks in this plan follow the same pattern (`cmd /c ... >> log 2>&1`, working dir `RS2 Local`).
- `gh` CLI 2.95.0 authenticated as `riperdy-tech` with `repo` + `workflow` scopes at `C:\Program Files\GitHub CLI\gh.exe`. Python 3.12.10 at `C:\Program Files\Python312\python.exe`.
- Site precedents to copy, not reinvent: `app/api/paper-ledgers/route.ts` (force-dynamic runtime JSON), `app/api/refresh-mine/route.ts` (GH_PAT → workflow_dispatch), `lib/supabase.ts` (`supabaseAdmin` service client).
- Supabase project already backs the site (`NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_SERVICE_KEY` exist in Vercel and in GitHub secrets).
- rs2-local currently has **no GitHub Actions workflows** and no tests directory; pytest is available (`.pytest_cache` gitignored). Put new tests in `tests/`.

---

# Phase A — PC side (rs2-local repo)

### Task 1: Supabase control tables

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\docs\control_tower_schema.sql` (reference copy, committed)

**Interfaces:**
- Produces: Supabase tables `control_heartbeat(id text pk, payload jsonb, updated_at timestamptz)` and `control_commands(id identity pk, command text, args jsonb, status text default 'pending', result text, created_at timestamptz default now(), executed_at timestamptz)`. RLS enabled with **no policies** → service-role key only; anon key sees nothing. Consumed by Tasks 2, 4, 9.

- [ ] **Step 1: Write the schema file**

```sql
-- docs/control_tower_schema.sql
-- Control-tower tables. Run once in the Supabase SQL editor (same project the
-- site already uses). RLS on + zero policies = service-role access only.

create table if not exists control_heartbeat (
  id         text primary key,
  payload    jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists control_commands (
  id          bigint generated always as identity primary key,
  command     text not null,
  args        jsonb not null default '{}'::jsonb,
  status      text not null default 'pending',  -- pending | running | done | error
  result      text,
  created_at  timestamptz not null default now(),
  executed_at timestamptz
);

alter table control_heartbeat enable row level security;
alter table control_commands  enable row level security;
```

- [ ] **Step 2 (MANUAL — operator):** Open the Supabase dashboard for the site's project → SQL editor → paste and run the file above. Expected: `Success. No rows returned`.

- [ ] **Step 3: Ensure Supabase creds are in PC secrets**

`C:\Users\riper\Downloads\RS2 Local\.secrets.json` (gitignored) **already contains lowercase `supabase_url` and `supabase_service_key` keys** (verified 2026-08-30). Check they point at the same project the site uses:

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -c "import json; s=json.load(open('.secrets.json')); print(s.get('supabase_url') or s.get('SUPABASE_URL'))"
```

If the printed URL matches the site's `NEXT_PUBLIC_SUPABASE_URL` project, nothing to add — `control_bus.py` (Task 2) accepts both casings. Only if missing/wrong, MANUAL — operator adds (values from Supabase dashboard → Settings → API):

```json
  "SUPABASE_URL": "https://<project-ref>.supabase.co",
  "SUPABASE_SERVICE_KEY": "<service_role key>"
```

- [ ] **Step 4: Verify with curl (service key works, anon blocked)**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && SB_URL=$(python -c "import json;print(json.load(open('.secrets.json'))['SUPABASE_URL'])") && SB_KEY=$(python -c "import json;print(json.load(open('.secrets.json'))['SUPABASE_SERVICE_KEY'])") && curl -s -o /dev/null -w "%{http_code}\n" "$SB_URL/rest/v1/control_heartbeat?select=id" -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY"
```

Expected: `200`. (An anon-key request to the same URL must return an empty array `[]` — RLS hides rows — which is fine; only the service role is used anywhere in this plan.)

- [ ] **Step 5: Commit**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add docs/control_tower_schema.sql && git commit -m "feat(control-tower): supabase control tables schema"
```

---

### Task 2: `control_bus.py` — Supabase client (stdlib)

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\control_bus.py`
- Test: `C:\Users\riper\Downloads\RS2 Local\tests\test_control_bus.py`

**Interfaces:**
- Consumes: `.secrets.json` keys `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (Task 1).
- Produces (used by Task 4 and Phase C):
  - `push_heartbeat(hb_id: str, payload: dict) -> None` — upsert into `control_heartbeat`.
  - `fetch_pending_commands() -> list[dict]` — pending rows, id asc, limit 10.
  - `mark_command(cmd_id: int, status: str, result: str = "") -> None` — status ∈ running/done/error.
  - `fetch_heartbeat(hb_id: str) -> dict | None` — read one row (used by cloud backstop preflight).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_control_bus.py
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_bus  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, reply=b"[]"):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req)
        return FakeResponse(reply)

    monkeypatch.setattr(control_bus.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        control_bus, "_secrets",
        lambda: {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "sk"},
    )
    return calls


def test_push_heartbeat_upserts(monkeypatch):
    calls = _capture(monkeypatch)
    control_bus.push_heartbeat("rs2-pc", {"ts": "2026-08-30T00:00:00+00:00"})
    (req,) = calls
    assert req.full_url == "https://x.supabase.co/rest/v1/control_heartbeat?on_conflict=id"
    assert req.get_method() == "POST"
    assert req.get_header("Prefer") == "resolution=merge-duplicates"
    assert req.get_header("Apikey") == "sk"
    body = json.loads(req.data.decode())
    assert body[0]["id"] == "rs2-pc"
    assert body[0]["payload"]["ts"] == "2026-08-30T00:00:00+00:00"


def test_fetch_pending_commands(monkeypatch):
    calls = _capture(monkeypatch, reply=b'[{"id": 1, "command": "depth_pause"}]')
    rows = control_bus.fetch_pending_commands()
    (req,) = calls
    assert "status=eq.pending" in req.full_url and "order=id.asc" in req.full_url
    assert rows[0]["command"] == "depth_pause"


def test_mark_command(monkeypatch):
    calls = _capture(monkeypatch, reply=b"")
    control_bus.mark_command(7, "done", "ok")
    (req,) = calls
    assert req.full_url.endswith("control_commands?id=eq.7")
    assert req.get_method() == "PATCH"
    body = json.loads(req.data.decode())
    assert body["status"] == "done" and body["result"] == "ok" and body["executed_at"]


def test_fetch_heartbeat_none(monkeypatch):
    _capture(monkeypatch, reply=b"[]")
    assert control_bus.fetch_heartbeat("rs2-pc") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_control_bus.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'control_bus'`.

- [ ] **Step 3: Write the implementation**

```python
# control_bus.py
"""Supabase control bus for the RS2 control tower.

One heartbeat row per machine in control_heartbeat; remote orders arrive as
rows in control_commands (written by the /admin site) and are executed by
control_agent.py. Stdlib-only, secrets re-read per call (same policy as ops.py).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _secrets() -> dict:
    return json.loads((HERE / ".secrets.json").read_text(encoding="utf-8"))


def _sb_creds(s: dict) -> tuple:
    # .secrets.json historically uses lowercase supabase_* keys; accept both.
    url = s.get("SUPABASE_URL") or s.get("supabase_url")
    key = s.get("SUPABASE_SERVICE_KEY") or s.get("supabase_service_key")
    if not url or not key:
        raise KeyError("supabase creds missing from .secrets.json")
    return url, key


def _req(method: str, path: str, body=None, params: str = "", prefer: str | None = None):
    sb_url, sb_key = _sb_creds(_secrets())
    url = sb_url.rstrip("/") + "/rest/v1/" + path + (("?" + params) if params else "")
    headers = {
        "apikey": sb_key,
        "Authorization": "Bearer " + sb_key,
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None


def push_heartbeat(hb_id: str, payload: dict) -> None:
    _req(
        "POST",
        "control_heartbeat",
        body=[{"id": hb_id, "payload": payload,
               "updated_at": datetime.now(timezone.utc).isoformat()}],
        params="on_conflict=id",
        prefer="resolution=merge-duplicates",
    )


def fetch_heartbeat(hb_id: str):
    rows = _req("GET", "control_heartbeat", params=f"id=eq.{hb_id}&select=*") or []
    return rows[0] if rows else None


def fetch_pending_commands() -> list:
    return _req("GET", "control_commands",
                params="status=eq.pending&order=id.asc&limit=10") or []


def mark_command(cmd_id: int, status: str, result: str = "") -> None:
    _req(
        "PATCH",
        "control_commands",
        body={"status": status, "result": result[:2000],
              "executed_at": datetime.now(timezone.utc).isoformat()},
        params=f"id=eq.{cmd_id}",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_control_bus.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Live smoke test (real Supabase)**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -c "import control_bus; from datetime import datetime, timezone; control_bus.push_heartbeat('smoke-test', {'ts': datetime.now(timezone.utc).isoformat()}); print(control_bus.fetch_heartbeat('smoke-test'))"
```

Expected: prints the row just written (id `smoke-test`).

- [ ] **Step 6: Commit**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add control_bus.py tests/test_control_bus.py && git commit -m "feat(control-tower): stdlib supabase control bus"
```

---

### Task 3: `sync_state.py` — depth-state backup to private `rs2-state` repo

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\sync_state.py`
- Test: `C:\Users\riper\Downloads\RS2 Local\tests\test_sync_state.py`

**Interfaces:**
- Consumes: local files under `cache\` (listed in code); git CLI; the `rs2-state` clone at `C:\Users\riper\Downloads\rs2-state`.
- Produces:
  - `main(repo_dir: Path | None = None) -> str` — returns a short status string ("synced <n> files" / "no changes" / "import <n> cloud rows"); called by Task 4's agent and runnable as `python sync_state.py`.
  - **rs2-state repo layout contract** (Phase C's cloud workflow writes `cloud_pending/`; PC is the only writer of `cache/`):
    - `cache/depth_ledger.jsonl`, `cache/depth_ondemand_ledger.jsonl`, `cache/depth_state.json`, `cache/depth_membership.jsonl`, `cache/depth_overlay.json`, `cache/depth_ondemand.jsonl` — PC backups.
    - `cloud_pending/depth_ledger_delta.jsonl` — verdict rows appended by the cloud backstop while the PC was off; the PC imports (appends line-wise, deduped by exact line) into its local `cache\depth_ledger.jsonl`, then truncates the delta file. Mirrors the existing `cache/cloud_pending_reports` staging idea from `publish_overlay()`.
    - `meta/last_pc_sync.json` — `{"ts": "<utc iso>"}`.

- [ ] **Step 1 (MANUAL — operator): create the private state repo and clone it**

```bash
gh repo create riperdy-tech/rs2-state --private --description "RS2 depth-state backup + cloud handoff" && git clone https://github.com/riperdy-tech/rs2-state.git "/c/Users/riper/Downloads/rs2-state" && cd "/c/Users/riper/Downloads/rs2-state" && git commit --allow-empty -m "init" && git push -u origin main
```

Expected: repo exists, clone at `C:\Users\riper\Downloads\rs2-state`, branch `main` pushed.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_sync_state.py
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_state  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "rs2-state"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@test")
    _git(clone, "config", "user.name", "test")
    _git(clone, "commit", "--allow-empty", "-m", "init")
    _git(clone, "push", "-u", "origin", "master")
    return clone


def test_sync_copies_state_and_pushes(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text('{"t": "AAA"}\n', encoding="utf-8")
    (cache / "depth_state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    out = sync_state.main(repo_dir=clone)
    assert "synced" in out
    assert (clone / "cache" / "depth_ledger.jsonl").read_text(encoding="utf-8") == '{"t": "AAA"}\n'
    assert json.loads((clone / "meta" / "last_pc_sync.json").read_text(encoding="utf-8"))["ts"]
    log = subprocess.run(["git", "-C", str(clone), "log", "--oneline"],
                         capture_output=True, text=True, check=True).stdout
    assert "state sync" in log


def test_sync_noop_when_unchanged(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    sync_state.main(repo_dir=clone)
    out = sync_state.main(repo_dir=clone)
    assert out == "no changes"


def test_cloud_delta_imported_and_truncated(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text('{"run": "AAA_1"}\n', encoding="utf-8")
    pending = clone / "cloud_pending"
    pending.mkdir()
    (pending / "depth_ledger_delta.jsonl").write_text(
        '{"run": "AAA_1"}\n{"run": "BBB_2"}\n', encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "cloud delta")
    _git(clone, "push")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    out = sync_state.main(repo_dir=clone)
    local = (cache / "depth_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert local == ['{"run": "AAA_1"}', '{"run": "BBB_2"}']  # deduped append
    assert (pending / "depth_ledger_delta.jsonl").read_text(encoding="utf-8") == ""
    assert "import 1 cloud rows" in out
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_sync_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sync_state'`.

- [ ] **Step 4: Write the implementation**

```python
# sync_state.py
"""Back up local-only depth state to the private rs2-state repo, and import
cloud-backstop ledger deltas back into the local ledger.

cache/ is gitignored in rs2-local; losing it resets the whole depth queue.
The cloud depth backstop (rs2-local .github/workflows/depth-cloud-backstop.yml)
also needs this state to run while the PC is off, and hands its new verdict
rows back via cloud_pending/depth_ledger_delta.jsonl.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
STATE_REPO = Path("C:/Users/riper/Downloads/rs2-state")
STATE_FILES = [
    "depth_ledger.jsonl",
    "depth_ondemand_ledger.jsonl",
    "depth_state.json",
    "depth_membership.jsonl",
    "depth_overlay.json",
    "depth_ondemand.jsonl",
]
DELTA = Path("cloud_pending") / "depth_ledger_delta.jsonl"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=120)


def _import_cloud_delta(repo_dir: Path) -> int:
    """Append cloud-written ledger rows missing locally; truncate the delta."""
    delta_path = repo_dir / DELTA
    if not delta_path.exists():
        return 0
    delta_lines = [ln for ln in delta_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not delta_lines:
        return 0
    ledger = CACHE / "depth_ledger.jsonl"
    have = set()
    if ledger.exists():
        have = {ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()}
    new = [ln for ln in delta_lines if ln not in have]
    if new:
        with ledger.open("a", encoding="utf-8") as f:
            for ln in new:
                f.write(ln + "\n")
    delta_path.write_text("", encoding="utf-8")
    return len(new)


def main(repo_dir: Path | None = None) -> str:
    repo = Path(repo_dir) if repo_dir else STATE_REPO
    if not (repo / ".git").exists():
        return f"error: {repo} is not a git clone"
    pull = _git(repo, "pull", "--ff-only")
    if pull.returncode != 0:
        return "error: pull failed: " + (pull.stderr or pull.stdout).strip()[:300]

    imported = _import_cloud_delta(repo)

    (repo / "cache").mkdir(exist_ok=True)
    (repo / "meta").mkdir(exist_ok=True)
    for name in STATE_FILES:
        src = CACHE / name
        if src.exists():
            shutil.copy2(src, repo / "cache" / name)
    (repo / "meta" / "last_pc_sync.json").write_text(
        json.dumps({"ts": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")

    _git(repo, "add", "-A")
    if not _git(repo, "status", "--porcelain").stdout.strip():
        return "no changes"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    commit = _git(repo, "commit", "-m", f"state sync {ts}")
    if commit.returncode != 0:
        return "error: commit failed: " + (commit.stderr or commit.stdout).strip()[:300]
    push = _git(repo, "push")
    if push.returncode != 0:
        return "error: push failed: " + (push.stderr or push.stdout).strip()[:300]
    n = sum(1 for name in STATE_FILES if (CACHE / name).exists())
    msg = f"synced {n} files"
    if imported:
        msg += f", import {imported} cloud rows"
    return msg


if __name__ == "__main__":
    print(main())
    sys.exit(0)
```

Note for the implementer: the tests always commit meta/last_pc_sync.json (fresh timestamp each run) — the `no changes` branch is reached because the second run within the same second produces an identical file; if the noop test proves flaky on timing, freeze `datetime` via monkeypatch in that test instead of loosening the assertion.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_sync_state.py -v
```

Expected: 3 passed. (If `no changes` flakes because the two runs straddle a second boundary, apply the note in Step 4.)

- [ ] **Step 6: Live run against the real rs2-state clone**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python sync_state.py
```

Expected: `synced 6 files` (first run). Verify on GitHub that `riperdy-tech/rs2-state` now contains `cache/depth_ledger.jsonl` etc.

- [ ] **Step 7: Commit**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add sync_state.py tests/test_sync_state.py && git commit -m "feat(control-tower): depth-state backup + cloud delta import (rs2-state)"
```

---

### Task 4: `control_agent.py` — heartbeat + command executor

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\control_agent.py`
- Test: `C:\Users\riper\Downloads\RS2 Local\tests\test_control_agent.py`

**Interfaces:**
- Consumes: `control_bus.push_heartbeat/fetch_pending_commands/mark_command` (Task 2), `sync_state.main()` (Task 3), `ops.notify_telegram(text)` (existing, `ops.py:33`). The Telegram bot is owned by the `RS2-Telegram-Bot` scheduled task (auto-restart) — the agent only observes it and can restart the TASK on command; it never spawns the bot process itself.
- Produces:
  - `collect_snapshot() -> dict` — heartbeat payload (schema below), pushed as id `rs2-pc`.
  - `run_command(row: dict) -> str` — executes one whitelisted command, returns result text.
  - `main() -> None` — one full pass; scheduled every 5 min by Task 5. Never raises.
  - **Command contract** (the site's `/api/admin/command` route must only ever insert these): `depth_pause`, `depth_resume`, `depth_run_now`, `sdf_dispatch` (args `{"runner": "self-hosted"|"ubuntu-latest"}`), `bot_restart`, `state_sync`. (No `ondemand` command — the site's `/api/ondemand` → Supabase `ondemand_queue` → bot bridge already carries remote on-demand requests.)
  - **Heartbeat payload schema** (the site's status route renders these fields):

```json
{
  "ts": "<utc iso>",
  "host": "<hostname>",
  "depth": {"lock": false, "paused": false, "progress": {}, "ledger_mtime": "<utc iso|null>", "overlay_mtime": "<utc iso|null>"},
  "ondemand": {"queue_lines": 0},
  "bot": {"alive": true, "offset_mtime": "<utc iso|null>"},
  "tasks": {"RS2-Depth-Orchestrator": {"LastRunTime": "...", "LastTaskResult": 0, "NextRunTime": "..."}},
  "sync": {"last_state_sync": "<utc iso|null>", "last_result": "<str|null>"}
}
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_control_agent.py
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_agent  # noqa: E402


def _redirect_cache(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(control_agent, "CACHE", cache)
    return cache


def test_snapshot_reflects_flags(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    (cache / "DEPTH_PAUSED").write_text("x", encoding="utf-8")
    (cache / "depth_progress.json").write_text('{"ticker": "CEG"}', encoding="utf-8")
    (cache / "depth_ondemand.jsonl").write_text("a\nb\n", encoding="utf-8")
    monkeypatch.setattr(control_agent, "_task_info", lambda name: None)
    monkeypatch.setattr(control_agent, "_bot_pids", lambda: [123])
    snap = control_agent.collect_snapshot()
    assert snap["depth"]["paused"] is True
    assert snap["depth"]["lock"] is False
    assert snap["depth"]["progress"]["ticker"] == "CEG"
    assert snap["ondemand"]["queue_lines"] == 2
    assert snap["bot"]["alive"] is True
    assert snap["ts"].endswith("+00:00") or snap["ts"].endswith("Z")


def test_pause_resume_commands(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    out = control_agent.run_command({"id": 1, "command": "depth_pause", "args": {}})
    assert (cache / "DEPTH_PAUSED").exists() and "paused" in out
    out = control_agent.run_command({"id": 2, "command": "depth_resume", "args": {}})
    assert not (cache / "DEPTH_PAUSED").exists() and "resumed" in out


def test_unknown_command_rejected(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    try:
        control_agent.run_command({"id": 3, "command": "rm_rf_everything", "args": {}})
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "unknown command" in str(e)


def test_main_marks_commands_done(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    marked = []
    monkeypatch.setattr(control_agent, "collect_snapshot", lambda: {"ts": "t"})
    monkeypatch.setattr(control_agent.control_bus, "push_heartbeat", lambda *a: None)
    monkeypatch.setattr(control_agent.control_bus, "fetch_pending_commands",
                        lambda: [{"id": 9, "command": "depth_pause", "args": {}}])
    monkeypatch.setattr(control_agent.control_bus, "mark_command",
                        lambda cid, status, result="": marked.append((cid, status)))
    monkeypatch.setattr(control_agent, "maybe_sync_state", lambda: None)
    control_agent.main()
    assert ("9", "running") not in marked  # ids stay ints
    assert (9, "running") in marked and (9, "done") in marked
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_control_agent.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'control_agent'`.

- [ ] **Step 3: Write the implementation**

```python
# control_agent.py
"""RS2 control agent — one pass per invocation, scheduled every 5 minutes.

1. Push a rhythm snapshot to Supabase (control_heartbeat id 'rs2-pc').
2. Execute pending whitelisted commands from control_commands.
3. Hourly, back depth state up to the rs2-state repo via sync_state.main().

The Telegram bot is kept alive by its own scheduled task (RS2-Telegram-Bot,
auto-restart); this agent only reports its state and can restart that task
on command. Never raises out of main(); failures append to
cache/control_agent.log and a Telegram alert fires after 3 consecutive
heartbeat failures (~15 min blind).
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import control_bus
import ops
import sync_state

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
GH = r"C:\Program Files\GitHub CLI\gh.exe"
SCREENER_REPO = "riperdy-tech/stock-screener"
TASK_NAMES = ["RS2-Depth-Orchestrator", "RS2-Control-Agent", "RS2-SDF-Dispatch",
              "RS2-Telegram-Bot"]
SYNC_INTERVAL_S = 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    line = f"{_now()} {msg}\n"
    try:
        with (CACHE / "control_agent.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _mtime_iso(p: Path):
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _task_info(name: str):
    cmd = ["powershell", "-NoProfile", "-Command",
           f"Get-ScheduledTaskInfo -TaskName '{name}' -ErrorAction SilentlyContinue "
           "| Select-Object @{n='LastRunTime';e={$_.LastRunTime.ToString('s')}},"
           "LastTaskResult,@{n='NextRunTime';e={$_.NextRunTime.ToString('s')}} "
           "| ConvertTo-Json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
        return json.loads(out) if out else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _bot_pids() -> list:
    cmd = ["powershell", "-NoProfile", "-Command",
           "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" "
           "| Where-Object { $_.CommandLine -match 'telegram_status_bot' } "
           "| Select-Object -ExpandProperty ProcessId"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
        return [int(x) for x in out.split()]
    except (subprocess.SubprocessError, ValueError, OSError):
        return []


def collect_snapshot() -> dict:
    ondemand = CACHE / "depth_ondemand.jsonl"
    queue_lines = 0
    try:
        queue_lines = sum(1 for ln in ondemand.read_text(encoding="utf-8").splitlines()
                          if ln.strip())
    except OSError:
        pass
    sync_marker = _read_json(CACHE / "state_sync_last.json") or {}
    return {
        "ts": _now(),
        "host": socket.gethostname(),
        "depth": {
            "lock": (CACHE / "orchestrate_depth.lock").exists(),
            "paused": (CACHE / "DEPTH_PAUSED").exists(),
            "progress": _read_json(CACHE / "depth_progress.json"),
            "ledger_mtime": _mtime_iso(CACHE / "depth_ledger.jsonl"),
            "overlay_mtime": _mtime_iso(CACHE / "depth_overlay.json"),
        },
        "ondemand": {"queue_lines": queue_lines},
        "bot": {
            "alive": bool(_bot_pids()),
            "offset_mtime": _mtime_iso(CACHE / "telegram_bot_offset.json"),
        },
        "tasks": {name: _task_info(name) for name in TASK_NAMES},
        "sync": {"last_state_sync": sync_marker.get("ts"),
                 "last_result": sync_marker.get("result")},
    }


# ---- command handlers -------------------------------------------------------

def _cmd_depth_pause(args: dict) -> str:
    (CACHE / "DEPTH_PAUSED").write_text(f"paused via control tower {_now()}", encoding="utf-8")
    return "paused"


def _cmd_depth_resume(args: dict) -> str:
    (CACHE / "DEPTH_PAUSED").unlink(missing_ok=True)
    return "resumed"


def _cmd_depth_run_now(args: dict) -> str:
    r = subprocess.run(["schtasks", "/run", "/tn", "RS2-Depth-Orchestrator"],
                       capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip()


def _cmd_sdf_dispatch(args: dict) -> str:
    runner = (args or {}).get("runner", "self-hosted")
    if runner not in ("self-hosted", "ubuntu-latest"):
        raise ValueError(f"bad runner {runner!r}")
    r = subprocess.run([GH, "workflow", "run", "schedule-data-fetch.yml",
                        "-R", SCREENER_REPO, "-f", f"runner={runner}"],
                       capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip() or f"dispatched runner={runner}"


def _cmd_bot_restart(args: dict) -> str:
    subprocess.run(["schtasks", "/end", "/tn", "RS2-Telegram-Bot"],
                   capture_output=True, text=True, timeout=30)
    for pid in _bot_pids():
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, text=True, timeout=30)
    r = subprocess.run(["schtasks", "/run", "/tn", "RS2-Telegram-Bot"],
                       capture_output=True, text=True, timeout=30)
    return "bot task restarted: " + (r.stdout + r.stderr).strip()[:200]


def _cmd_state_sync(args: dict) -> str:
    result = sync_state.main()
    (CACHE / "state_sync_last.json").write_text(
        json.dumps({"ts": _now(), "result": result}), encoding="utf-8")
    return result


COMMANDS = {
    "depth_pause": _cmd_depth_pause,
    "depth_resume": _cmd_depth_resume,
    "depth_run_now": _cmd_depth_run_now,
    "sdf_dispatch": _cmd_sdf_dispatch,
    "bot_restart": _cmd_bot_restart,
    "state_sync": _cmd_state_sync,
}


def run_command(row: dict) -> str:
    name = row.get("command", "")
    handler = COMMANDS.get(name)
    if handler is None:
        raise ValueError(f"unknown command {name!r}")
    args = row.get("args") or {}
    if isinstance(args, str):
        args = json.loads(args)
    return handler(args)


# ---- periodic sync ----------------------------------------------------------

def maybe_sync_state() -> None:
    marker = _read_json(CACHE / "state_sync_last.json") or {}
    last = marker.get("ts")
    if last:
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(last)).total_seconds()
            if age < SYNC_INTERVAL_S:
                return
        except ValueError:
            pass
    _cmd_state_sync({})


def _heartbeat_with_alert(snapshot: dict) -> None:
    marker = CACHE / "control_agent_hbfail.json"
    try:
        control_bus.push_heartbeat("rs2-pc", snapshot)
        marker.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 — scheduled entry point must not die
        fails = (_read_json(marker) or {}).get("count", 0) + 1
        marker.write_text(json.dumps({"count": fails}), encoding="utf-8")
        _log(f"heartbeat push failed ({fails}): {e}")
        if fails == 3:
            ops.notify_telegram("control_agent: 3 consecutive heartbeat failures — "
                                "control tower is blind to this PC")


def main() -> None:
    try:
        _heartbeat_with_alert(collect_snapshot())
    except Exception as e:  # noqa: BLE001
        _log(f"snapshot failed: {e}")
    try:
        for row in control_bus.fetch_pending_commands():
            cid = row["id"]
            control_bus.mark_command(cid, "running")
            try:
                result = run_command(row)
                control_bus.mark_command(cid, "done", result)
                _log(f"command {cid} {row.get('command')}: done")
            except Exception as e:  # noqa: BLE001
                control_bus.mark_command(cid, "error", str(e))
                _log(f"command {cid} {row.get('command')}: error {e}")
    except Exception as e:  # noqa: BLE001
        _log(f"command poll failed: {e}")
    try:
        maybe_sync_state()
    except Exception as e:  # noqa: BLE001
        _log(f"state sync failed: {e}")


if __name__ == "__main__":
    main()
    sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_control_agent.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Live single pass**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python control_agent.py && python -c "import control_bus, json; print(json.dumps(control_bus.fetch_heartbeat('rs2-pc')['payload'], indent=2)[:800])"
```

Expected: heartbeat row exists with `host`, `depth.paused: false`, `tasks` populated for `RS2-Depth-Orchestrator` and `RS2-Telegram-Bot` (`RS2-Control-Agent`/`RS2-SDF-Dispatch` are `null` until Task 5 registers them), `bot.alive: true`.

- [ ] **Step 6: Live command round-trip**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python - <<'EOF'
import control_bus, control_agent, json
control_bus._req("POST", "control_commands", body=[{"command": "depth_pause", "args": {}}])
control_agent.main()
rows = control_bus._req("GET", "control_commands", params="order=id.desc&limit=1")
print(json.dumps(rows[0], indent=2))
EOF
```

Expected: latest row `status: "done"`, `result: "paused"`, and `cache\DEPTH_PAUSED` exists. **Then undo:**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && rm cache/DEPTH_PAUSED && ls cache | grep -c DEPTH_PAUSED || echo "resumed ok"
```

Expected: `resumed ok`.

- [ ] **Step 7: Commit**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add control_agent.py tests/test_control_agent.py && git commit -m "feat(control-tower): pc control agent (heartbeat + remote commands)"
```

---

### Task 5: Register scheduled tasks — `RS2-Control-Agent` + the missing `RS2-SDF-Dispatch`

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\register_control_tasks.ps1`

**Interfaces:**
- Consumes: `control_agent.py` (Task 4); `gh` CLI at `C:\Program Files\GitHub CLI\gh.exe`.
- Produces: Task Scheduler entries `RS2-Control-Agent` (every 5 min) and `RS2-SDF-Dispatch` (weekdays 22:35, weekends 18:35 local = 14:35/10:35 UTC — the documented-but-never-implemented SDF primary from `schedule-data-fetch.yml:4-8`).

- [ ] **Step 1: Write the registration script**

```powershell
# register_control_tasks.ps1
# Registers the control-tower scheduled tasks. Mirrors register_depth_task.ps1
# conventions: interactive-logon principal, cmd /c with log redirect, WD = repo.
# Timezone note: this PC is UTC+08:00 (no DST). 22:35 local = 14:35 UTC (weekday
# SDF primary target); 18:35 local = 10:35 UTC (weekend target).

$repo = "C:\Users\riper\Downloads\RS2 Local"
$py   = "C:\Program Files\Python312\python.exe"
$gh   = "C:\Program Files\GitHub CLI\gh.exe"

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# --- RS2-Control-Agent: every 5 minutes, forever -----------------------------
$agentAction = New-ScheduledTaskAction -Execute "cmd.exe" `
  -Argument "/c ""$py"" ""$repo\control_agent.py"" >> ""$repo\cache\control_agent_task.log"" 2>&1" `
  -WorkingDirectory $repo
$agentTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration ([TimeSpan]::MaxValue)
Register-ScheduledTask -TaskName "RS2-Control-Agent" -Action $agentAction `
  -Trigger $agentTrigger -Settings $settings -Force

# --- RS2-SDF-Dispatch: the SDF PC self-dispatch primary ----------------------
$sdfArg = "/c ""$gh"" workflow run schedule-data-fetch.yml -R riperdy-tech/stock-screener -f runner=self-hosted >> ""$repo\cache\sdf_dispatch.log"" 2>&1"
$sdfAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $sdfArg -WorkingDirectory $repo
$sdfTriggers = @(
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "22:35"),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday,Sunday -At "18:35")
)
Register-ScheduledTask -TaskName "RS2-SDF-Dispatch" -Action $sdfAction `
  -Trigger $sdfTriggers -Settings $settings -Force

Write-Host "Registered RS2-Control-Agent (q5min) and RS2-SDF-Dispatch (22:35 wd / 18:35 we local)."
```

- [ ] **Step 2: Run it (elevated not required for own-user tasks)**

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\riper\Downloads\RS2 Local\register_control_tasks.ps1"
```

Expected: both `Register-ScheduledTask` outputs show `Ready`.

- [ ] **Step 3: Verify the agent fires within 6 minutes**

```bash
powershell -NoProfile -Command "Start-Sleep 360; Get-ScheduledTaskInfo -TaskName 'RS2-Control-Agent' | Select LastRunTime,LastTaskResult"
```

Expected: `LastTaskResult : 0` with a LastRunTime in the last 6 minutes. Then confirm the heartbeat in Supabase updated (`python -c "import control_bus; print(control_bus.fetch_heartbeat('rs2-pc')['updated_at'])"` — must be < 6 min old).

- [ ] **Step 4: Verify SDF self-dispatch end-to-end (one manual fire)**

```bash
schtasks /run /tn "RS2-SDF-Dispatch"
```

Then:

```bash
sleep 30 && gh run list --workflow schedule-data-fetch.yml -R riperdy-tech/stock-screener --limit 3
```

Expected: newest run has `event=workflow_dispatch`. Watch it: the `preflight` job must resolve `runner=self-hosted` and the `fetch` job must run on the `rs2-pc` runner. This closes the "PC primary never wired" gap — from today, cloud crons only run as backstop when this dispatch is missed.

- [ ] **Step 5: Commit**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add register_control_tasks.ps1 && git commit -m "feat(control-tower): register control-agent + missing SDF self-dispatch tasks"
```

---

# Phase B — Admin site (stock-screener repo)

**Working-tree caution:** the screener dev tree is dirty with ~20 untracked scratch files. Stage only the files each task names. All new code is additive — no existing route or page is modified except where a task explicitly says so.

### Task 6: GitHub OAuth + admin session (`lib/adminAuth.ts`, auth routes)

**Files:**
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\lib\adminAuth.ts`
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\api\auth\github\login\route.ts`
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\api\auth\github\callback\route.ts`

**Interfaces:**
- Consumes: env `GH_OAUTH_CLIENT_ID`, `GH_OAUTH_CLIENT_SECRET`, `ADMIN_GITHUB_LOGIN`, `ADMIN_SESSION_SECRET`, `NEXT_PUBLIC_SITE_URL`.
- Produces (used by Tasks 8-10):
  - `signSession(login: string): string`
  - `verifySession(token: string | undefined): { login: string } | null`
  - `requireAdmin(req: NextRequest): { login: string } | null`
  - `ADMIN_COOKIE = "rs2_admin"` — httpOnly HMAC cookie, 30-day expiry.

- [ ] **Step 1 (MANUAL — operator): create the GitHub OAuth app**

GitHub → Settings → Developer settings → OAuth Apps → New OAuth App:
- Application name: `RS2 Control Tower`
- Homepage URL: the production site URL (the Vercel domain, e.g. `https://<your-app>.vercel.app`)
- Authorization callback URL: `https://<your-app>.vercel.app/api/auth/github/callback`

Copy the Client ID, generate a Client Secret. Then in Vercel → Project → Settings → Environment Variables add (Production + Preview + Development):

| Name | Value |
|---|---|
| `GH_OAUTH_CLIENT_ID` | from OAuth app |
| `GH_OAUTH_CLIENT_SECRET` | from OAuth app |
| `ADMIN_GITHUB_LOGIN` | `riperdy-tech` |
| `ADMIN_SESSION_SECRET` | output of `openssl rand -hex 32` |

For local dev, add the same four to `.env.local` (gitignored) plus `NEXT_PUBLIC_SITE_URL=http://localhost:3000`, and add `http://localhost:3000/api/auth/github/callback` as a second OAuth app **or** temporarily switch the callback while testing locally (GitHub OAuth apps allow one callback URL — a second app named `RS2 Control Tower (dev)` is cleaner).

- [ ] **Step 2: Write `lib/adminAuth.ts`**

```ts
// lib/adminAuth.ts
import crypto from "crypto";
import type { NextRequest } from "next/server";

export const ADMIN_COOKIE = "rs2_admin";
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

function secret(): string {
  const s = process.env.ADMIN_SESSION_SECRET;
  if (!s) throw new Error("ADMIN_SESSION_SECRET not set");
  return s;
}

export function signSession(login: string): string {
  const payload = Buffer.from(
    JSON.stringify({ login, exp: Date.now() + THIRTY_DAYS_MS })
  ).toString("base64url");
  const mac = crypto.createHmac("sha256", secret()).update(payload).digest("base64url");
  return `${payload}.${mac}`;
}

export function verifySession(token: string | undefined): { login: string } | null {
  if (!token) return null;
  const [payload, mac] = token.split(".");
  if (!payload || !mac) return null;
  const expect = crypto.createHmac("sha256", secret()).update(payload).digest("base64url");
  const a = Buffer.from(mac);
  const b = Buffer.from(expect);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString());
    if (typeof data.login !== "string" || typeof data.exp !== "number") return null;
    if (data.exp < Date.now()) return null;
    return { login: data.login };
  } catch {
    return null;
  }
}

export function requireAdmin(req: NextRequest): { login: string } | null {
  return verifySession(req.cookies.get(ADMIN_COOKIE)?.value);
}
```

- [ ] **Step 3: Write the login route**

```ts
// app/api/auth/github/login/route.ts
import { NextResponse } from "next/server";
import crypto from "crypto";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const state = crypto.randomBytes(16).toString("hex");
  const site = process.env.NEXT_PUBLIC_SITE_URL || new URL(request.url).origin;
  const params = new URLSearchParams({
    client_id: process.env.GH_OAUTH_CLIENT_ID || "",
    redirect_uri: `${site}/api/auth/github/callback`,
    state,
  });
  const res = NextResponse.redirect(
    `https://github.com/login/oauth/authorize?${params.toString()}`
  );
  res.cookies.set("gh_oauth_state", state, {
    httpOnly: true,
    secure: site.startsWith("https"),
    sameSite: "lax",
    maxAge: 600,
    path: "/",
  });
  return res;
}
```

- [ ] **Step 4: Write the callback route**

```ts
// app/api/auth/github/callback/route.ts
import { NextRequest, NextResponse } from "next/server";
import { ADMIN_COOKIE, signSession } from "../../../../../lib/adminAuth";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code");
  const state = req.nextUrl.searchParams.get("state");
  const saved = req.cookies.get("gh_oauth_state")?.value;
  if (!code || !state || !saved || state !== saved) {
    return new NextResponse("Bad OAuth state", { status: 400 });
  }

  const tokenRes = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      client_id: process.env.GH_OAUTH_CLIENT_ID,
      client_secret: process.env.GH_OAUTH_CLIENT_SECRET,
      code,
    }),
  });
  const { access_token: accessToken } = await tokenRes.json();
  if (!accessToken) return new NextResponse("OAuth exchange failed", { status: 400 });

  const userRes = await fetch("https://api.github.com/user", {
    headers: { Authorization: `Bearer ${accessToken}`, "User-Agent": "rs2-control-tower" },
  });
  const user = await userRes.json();
  const allowed = (process.env.ADMIN_GITHUB_LOGIN || "").toLowerCase();
  if (!user?.login || user.login.toLowerCase() !== allowed) {
    return new NextResponse("Not authorized for this control tower", { status: 403 });
  }

  const res = NextResponse.redirect(new URL("/admin", req.url));
  res.cookies.set(ADMIN_COOKIE, signSession(user.login), {
    httpOnly: true,
    secure: req.nextUrl.protocol === "https:",
    sameSite: "lax",
    maxAge: 30 * 24 * 60 * 60,
    path: "/",
  });
  res.cookies.delete("gh_oauth_state");
  return res;
}
```

- [ ] **Step 5: Verify locally**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && npx tsc --noEmit
```

Expected: no new type errors (pre-existing errors in untouched files are acceptable — compare against `npx tsc --noEmit` on HEAD if unsure).

Then `npm run dev`, browse `http://localhost:3000/api/auth/github/login` → GitHub authorize → redirected to `/admin` (404 until Task 10 — the `rs2_admin` cookie in devtools is the pass criterion). A second browser (not signed in as riperdy-tech) must get 403.

- [ ] **Step 6: Commit**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && git add lib/adminAuth.ts app/api/auth && git commit -m "feat(admin): github oauth gate for control tower"
```

---

### Task 7: Rhythm registry (`lib/controlTower.ts`)

**Files:**
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\lib\controlTower.ts`

**Interfaces:**
- Consumes: nothing (pure data + pure functions).
- Produces (used by Tasks 8-10):
  - `RHYTHMS: Rhythm[]`, `type RhythmState = "ok" | "stale" | "dead" | "unknown"`
  - `parseStamp(s: string | undefined, naiveTz?: string): Date | null`
  - `classify(ageMin: number | null, r: Rhythm): RhythmState`
  - `DISPATCHABLE` — the workflow-dispatch whitelist.
  - `PC_COMMANDS` — the PC command whitelist (must exactly match Task 4's `COMMANDS` keys).

- [ ] **Step 1: Write the module**

```ts
// lib/controlTower.ts
// Single source of truth for what the control tower watches and may trigger.

export type RhythmState = "ok" | "stale" | "dead" | "unknown";

export interface Rhythm {
  key: string;
  label: string;
  kind: "file" | "heartbeat" | "workflow";
  /** for kind=file: path under public/data on raw.githubusercontent */
  file?: string;
  /** dot-free top-level field holding the timestamp */
  field?: string;
  /** timezone suffix to append when the stamp is naive (depth_overlay quirk) */
  naiveTz?: string;
  /** for kind=workflow: workflow file name in stock-screener */
  workflowFile?: string;
  staleAfterMin: number;
  deadAfterMin: number;
  manualRecovery: string;
}

export const RHYTHMS: Rhythm[] = [
  {
    key: "pc",
    label: "RS2 PC (control agent)",
    kind: "heartbeat",
    staleAfterMin: 15,
    deadAfterMin: 60,
    manualRecovery:
      "PC is offline or the RS2-Control-Agent task stopped. If you can power the PC on, do that — the agent self-heals on boot+logon. If you cannot: depth sweeps fall to the Depth cloud backstop (auto, daily) and SDF falls to the GitHub cron backstop (auto). Nothing else needs you.",
  },
  {
    key: "sdf",
    label: "Scheduled Data Fetch (ledgers)",
    kind: "file",
    file: "paper_ledgers.json",
    field: "last_updated",
    staleAfterMin: 26 * 60,
    deadAfterMin: 50 * 60,
    manualRecovery:
      "Dispatch 'Data fetch (cloud)' below, or from any terminal: gh workflow run schedule-data-fetch.yml -R riperdy-tech/stock-screener -f runner=ubuntu-latest",
  },
  {
    key: "depth",
    label: "Depth overlay (RS2 sweep)",
    kind: "file",
    file: "depth_overlay.json",
    field: "generated_at",
    naiveTz: "+08:00",
    staleAfterMin: 8 * 60,
    deadAfterMin: 36 * 60,
    manualRecovery:
      "If the PC is on: send PC command 'depth_run_now' below. If the PC is off: dispatch 'Depth cloud backstop' below (runs the DeepSeek arm from rs2-state), or from a terminal: gh workflow run depth-cloud-backstop.yml -R riperdy-tech/rs2-local",
  },
  {
    key: "chain",
    label: "Score chain (chain_manifest)",
    kind: "file",
    file: "chain_manifest.json",
    field: "finished_at",
    staleAfterMin: 26 * 60,
    deadAfterMin: 50 * 60,
    manualRecovery:
      "run_chain is executed by SDF and price-refresh. Dispatch 'Post-close price refresh' below to force a re-score.",
  },
  {
    key: "kis",
    label: "KIS Portfolio Sync",
    kind: "workflow",
    workflowFile: "kis-sync.yml",
    staleAfterMin: 30 * 60,
    deadAfterMin: 55 * 60,
    manualRecovery:
      "KIS sync is cloud-native (ubuntu-latest) — a missed run is a GitHub cron delay or a red run. Check the run log first. NEVER dispatch with env=real from here; if trading must stop, flip KIS_HALT below.",
  },
  {
    key: "price",
    label: "Post-Close Price Refresh",
    kind: "workflow",
    workflowFile: "price-refresh.yml",
    staleAfterMin: 30 * 60,
    deadAfterMin: 55 * 60,
    manualRecovery: "Dispatch 'Post-close price refresh' below.",
  },
  {
    key: "weekly",
    label: "Paradigm Weekly Analyst",
    kind: "workflow",
    workflowFile: "paradigm-weekly-analyst.yml",
    staleAfterMin: 8 * 24 * 60,
    deadAfterMin: 15 * 24 * 60,
    manualRecovery: "Dispatch 'Weekly analyst refresh' below.",
  },
];

export function parseStamp(s: string | undefined, naiveTz?: string): Date | null {
  if (!s) return null;
  const hasTz = /Z$|[+-]\d\d:?\d\d$/.test(s);
  const d = new Date(hasTz ? s : s + (naiveTz || "Z"));
  return isNaN(d.getTime()) ? null : d;
}

export function classify(ageMin: number | null, r: Rhythm): RhythmState {
  if (ageMin === null) return "unknown";
  if (ageMin >= r.deadAfterMin) return "dead";
  if (ageMin >= r.staleAfterMin) return "stale";
  return "ok";
}

export interface Dispatchable {
  repo: string;
  file: string;
  inputs?: Record<string, string>;
  label: string;
  danger?: boolean;
}

export const DISPATCHABLE: Record<string, Dispatchable> = {
  "sdf-cloud": {
    repo: "riperdy-tech/stock-screener",
    file: "schedule-data-fetch.yml",
    inputs: { runner: "ubuntu-latest" },
    label: "Data fetch (cloud)",
  },
  "sdf-self": {
    repo: "riperdy-tech/stock-screener",
    file: "schedule-data-fetch.yml",
    inputs: { runner: "self-hosted" },
    label: "Data fetch (PC runner)",
  },
  "price-refresh": {
    repo: "riperdy-tech/stock-screener",
    file: "price-refresh.yml",
    label: "Post-close price refresh",
  },
  "kis-dry-run": {
    repo: "riperdy-tech/stock-screener",
    file: "kis-sync.yml",
    inputs: { env: "paper", execute: "false" },
    label: "KIS sync dry-run (paper)",
  },
  "overlay-watchdog": {
    repo: "riperdy-tech/stock-screener",
    file: "overlay-freshness-watchdog.yml",
    label: "Overlay freshness check",
  },
  "weekly-analyst": {
    repo: "riperdy-tech/stock-screener",
    file: "paradigm-weekly-analyst.yml",
    label: "Weekly analyst refresh",
  },
  "depth-cloud-backstop": {
    repo: "riperdy-tech/rs2-local",
    file: "depth-cloud-backstop.yml",
    label: "Depth cloud backstop",
    danger: true,
  },
};

// Must exactly match COMMANDS in RS2 Local\control_agent.py.
// (No "ondemand" — the site's /api/ondemand -> ondemand_queue -> bot bridge
// already carries remote on-demand analysis requests.)
export const PC_COMMANDS = new Set([
  "depth_pause",
  "depth_resume",
  "depth_run_now",
  "sdf_dispatch",
  "bot_restart",
  "state_sync",
]);
```

- [ ] **Step 2: Type-check**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && npx tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && git add lib/controlTower.ts && git commit -m "feat(admin): rhythm registry + dispatch/command whitelists"
```

---

### Task 8: `/api/admin/status` aggregator

**Files:**
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\api\admin\status\route.ts`

**Interfaces:**
- Consumes: `requireAdmin` (Task 6); `RHYTHMS/parseStamp/classify` (Task 7); `supabaseAdmin` from existing `lib/supabase.ts`; env `GH_PAT` (falls back to `GITHUB_TOKEN`, same as `app/api/refresh-mine/route.ts`).
- Produces: `GET → 401 | { generatedAt, rhythms: Array<Rhythm & { lastStamp: string | null; ageMin: number | null; state: RhythmState }>, pc: { payload: any; updated_at: string } | null, workflows: Array<{ name, event, status, conclusion, created_at, html_url }>, kisVars: Record<string, string>, commands: any[] }` — consumed by Task 10's dashboard.

- [ ] **Step 1: Write the route**

```ts
// app/api/admin/status/route.ts
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "../../../../lib/adminAuth";
import { RHYTHMS, classify, parseStamp } from "../../../../lib/controlTower";
import { supabaseAdmin } from "../../../../lib/supabase";

export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

const RAW = "https://raw.githubusercontent.com/riperdy-tech/stock-screener/main/public/data";
const API = "https://api.github.com";
const REPO = "riperdy-tech/stock-screener";

function ghHeaders() {
  const token = process.env.GH_PAT || process.env.GITHUB_TOKEN || "";
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "rs2-control-tower",
  };
}

async function fetchJson(url: string, headers?: Record<string, string>) {
  try {
    const r = await fetch(url, { headers, cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function GET(req: NextRequest) {
  if (!requireAdmin(req)) return new NextResponse("Unauthorized", { status: 401 });

  const fileKeys = RHYTHMS.filter((r) => r.kind === "file");
  const [files, runsRaw, varsRaw, hb, cmds] = await Promise.all([
    Promise.all(fileKeys.map((r) => fetchJson(`${RAW}/${r.file}`))),
    fetchJson(`${API}/repos/${REPO}/actions/runs?per_page=30`, ghHeaders()),
    fetchJson(`${API}/repos/${REPO}/actions/variables?per_page=30`, ghHeaders()),
    supabaseAdmin.from("control_heartbeat").select("*").eq("id", "rs2-pc").maybeSingle(),
    supabaseAdmin.from("control_commands").select("*").order("id", { ascending: false }).limit(15),
  ]);

  const now = Date.now();
  const fileStamp = new Map<string, string | null>();
  fileKeys.forEach((r, i) => {
    const doc = files[i] as Record<string, unknown> | null;
    fileStamp.set(r.key, doc ? (doc[r.field as string] as string) ?? null : null);
  });

  const runs: any[] = runsRaw?.workflow_runs ?? [];
  const latestByFile = new Map<string, any>();
  for (const run of runs) {
    const file = String(run.path || "").split("/").pop() || "";
    if (!latestByFile.has(file)) latestByFile.set(file, run);
  }

  const hbRow = hb?.data ?? null;

  const rhythms = RHYTHMS.map((r) => {
    let lastStamp: string | null = null;
    if (r.kind === "file") lastStamp = fileStamp.get(r.key) ?? null;
    if (r.kind === "heartbeat") lastStamp = hbRow?.updated_at ?? null;
    if (r.kind === "workflow") {
      const run = latestByFile.get(r.workflowFile || "");
      lastStamp = run?.created_at ?? null;
    }
    const parsed = parseStamp(lastStamp ?? undefined, r.naiveTz);
    const ageMin = parsed ? Math.round((now - parsed.getTime()) / 60000) : null;
    return { ...r, lastStamp, ageMin, state: classify(ageMin, r) };
  });

  const workflows = runs.slice(0, 15).map((run) => ({
    name: run.name,
    event: run.event,
    status: run.status,
    conclusion: run.conclusion,
    created_at: run.created_at,
    html_url: run.html_url,
  }));

  const kisVars: Record<string, string> = {};
  for (const v of varsRaw?.variables ?? []) {
    if (String(v.name).startsWith("KIS_")) kisVars[v.name] = v.value;
  }

  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    rhythms,
    pc: hbRow,
    workflows,
    kisVars,
    commands: cmds?.data ?? [],
  });
}
```

- [ ] **Step 2: Verify unauthenticated is rejected**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/api/admin/status
```

Expected: `401`. (Dev server running, `.env.local` populated per Task 6.)

- [ ] **Step 3: Verify authenticated response**

In the browser (signed in from Task 6), open `http://localhost:3000/api/admin/status`. Expected JSON: 7 rhythms each with `state` ∈ ok/stale/dead/unknown; `pc.payload.host` present (Task 4 agent is live); `kisVars.KIS_LEDGER` = `equal_llm`; `workflows` non-empty. `depth` rhythm's `ageMin` must be plausible (< 600 — proves the +08:00 naive-stamp parse; a value ~480 too high means the suffix was not applied).

- [ ] **Step 4: Commit**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && git add app/api/admin/status && git commit -m "feat(admin): status aggregator (files + actions + heartbeat + kis vars)"
```

---

### Task 9: Control routes — dispatch, PC commands, KIS halt

**Files:**
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\api\admin\dispatch\route.ts`
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\api\admin\command\route.ts`
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\api\admin\kis\route.ts`

**Interfaces:**
- Consumes: `requireAdmin` (Task 6), `DISPATCHABLE`/`PC_COMMANDS` (Task 7), `supabaseAdmin`, env `GH_PAT`.
- Produces:
  - `POST /api/admin/dispatch {action: keyof DISPATCHABLE} → {ok, label}` — fires workflow_dispatch.
  - `POST /api/admin/command {command, args?} → {ok, id}` — inserts a `control_commands` row for the PC agent.
  - `GET /api/admin/kis → {vars}` / `POST /api/admin/kis {halt: boolean} → {ok, value}` — flips repo var `KIS_HALT` only.

- [ ] **Step 1: Write the dispatch route**

```ts
// app/api/admin/dispatch/route.ts
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "../../../../lib/adminAuth";
import { DISPATCHABLE } from "../../../../lib/controlTower";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  if (!requireAdmin(req)) return new NextResponse("Unauthorized", { status: 401 });
  const { action } = await req.json();
  const entry = DISPATCHABLE[action as string];
  if (!entry) return NextResponse.json({ error: "unknown action" }, { status: 400 });

  const token = process.env.GH_PAT || process.env.GITHUB_TOKEN;
  const r = await fetch(
    `https://api.github.com/repos/${entry.repo}/actions/workflows/${entry.file}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "rs2-control-tower",
      },
      body: JSON.stringify({ ref: "main", ...(entry.inputs ? { inputs: entry.inputs } : {}) }),
    }
  );
  if (r.status !== 204) {
    const text = await r.text();
    return NextResponse.json({ error: `github ${r.status}: ${text}` }, { status: 502 });
  }
  return NextResponse.json({ ok: true, label: entry.label });
}
```

- [ ] **Step 2: Write the command route**

```ts
// app/api/admin/command/route.ts
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "../../../../lib/adminAuth";
import { PC_COMMANDS } from "../../../../lib/controlTower";
import { supabaseAdmin } from "../../../../lib/supabase";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  if (!requireAdmin(req)) return new NextResponse("Unauthorized", { status: 401 });
  const { command, args } = await req.json();
  if (!PC_COMMANDS.has(command)) {
    return NextResponse.json({ error: "unknown command" }, { status: 400 });
  }
  if (command === "sdf_dispatch" &&
      !["self-hosted", "ubuntu-latest", undefined].includes(args?.runner)) {
    return NextResponse.json({ error: "bad runner" }, { status: 400 });
  }
  const { data, error } = await supabaseAdmin
    .from("control_commands")
    .insert({ command, args: args ?? {} })
    .select("id")
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true, id: data.id });
}
```

- [ ] **Step 3: Write the KIS route**

```ts
// app/api/admin/kis/route.ts
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "../../../../lib/adminAuth";

export const dynamic = "force-dynamic";

const REPO = "riperdy-tech/stock-screener";

function ghHeaders() {
  return {
    Authorization: `Bearer ${process.env.GH_PAT || process.env.GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "rs2-control-tower",
    "Content-Type": "application/json",
  };
}

export async function GET(req: NextRequest) {
  if (!requireAdmin(req)) return new NextResponse("Unauthorized", { status: 401 });
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/variables?per_page=30`, {
    headers: ghHeaders(),
    cache: "no-store",
  });
  const data = await r.json();
  const vars: Record<string, string> = {};
  for (const v of data?.variables ?? []) {
    if (String(v.name).startsWith("KIS_")) vars[v.name] = v.value;
  }
  return NextResponse.json({ vars });
}

// The ONLY mutable var from the control tower is KIS_HALT (kill switch).
// KIS_LEDGER / KIS_ENV / KIS_AUTO_EXECUTE are money-critical and read-only here.
export async function POST(req: NextRequest) {
  if (!requireAdmin(req)) return new NextResponse("Unauthorized", { status: 401 });
  const { halt } = await req.json();
  if (typeof halt !== "boolean") {
    return NextResponse.json({ error: "halt must be boolean" }, { status: 400 });
  }
  const value = halt ? "true" : "false";
  const patch = await fetch(
    `https://api.github.com/repos/${REPO}/actions/variables/KIS_HALT`,
    { method: "PATCH", headers: ghHeaders(), body: JSON.stringify({ name: "KIS_HALT", value }) }
  );
  if (patch.status === 404) {
    const create = await fetch(`https://api.github.com/repos/${REPO}/actions/variables`, {
      method: "POST",
      headers: ghHeaders(),
      body: JSON.stringify({ name: "KIS_HALT", value }),
    });
    if (create.status !== 201) {
      return NextResponse.json({ error: `github ${create.status}` }, { status: 502 });
    }
  } else if (patch.status !== 204) {
    return NextResponse.json({ error: `github ${patch.status}` }, { status: 502 });
  }
  return NextResponse.json({ ok: true, value });
}
```

- [ ] **Step 4: Verify auth + validation with curl**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:3000/api/admin/dispatch -H "Content-Type: application/json" -d "{\"action\": \"sdf-cloud\"}"
```

Expected: `401` (no cookie). Then in the signed-in browser console:

```js
// unknown action rejected
await fetch("/api/admin/dispatch", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "nope"})}).then(r => r.status)  // → 400
// unknown PC command rejected
await fetch("/api/admin/command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({command: "ondemand", args: {ticker: "CEG"}})}).then(r => r.status)  // → 400 (ondemand goes through /api/ondemand, not the control bus)
// real command lands in supabase and the PC executes it within 5 min
await fetch("/api/admin/command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({command: "state_sync"})}).then(r => r.json())  // → {ok: true, id: N}
```

After ≤5 min, `/api/admin/status` `commands[0]` shows that id with `status: "done"` and a `result` like `no changes`/`synced 6 files`.

- [ ] **Step 5: Verify one real dispatch (cheap)**

In the signed-in browser console:

```js
await fetch("/api/admin/dispatch", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: "overlay-watchdog"})}).then(r => r.json())
```

Expected `{ok: true, ...}` and `gh run list --workflow overlay-freshness-watchdog.yml -R riperdy-tech/stock-screener --limit 1` shows a fresh `workflow_dispatch` run (5-min timeout job, negligible minutes).

**Do NOT test the KIS halt POST against the real repo unless the operator explicitly wants a halt drill.** The GET is safe to verify (`vars.KIS_LEDGER === "equal_llm"`).

- [ ] **Step 6: Commit**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && git add app/api/admin/dispatch app/api/admin/command app/api/admin/kis && git commit -m "feat(admin): dispatch, pc-command, and kis-halt routes"
```

---

### Task 10: `/admin` dashboard page

**Files:**
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\app\admin\page.tsx`
- Create: `C:\Users\riper\Downloads\Stock Screener\Stock Screener\components\AdminDashboard.tsx`

**Interfaces:**
- Consumes: `verifySession`/`ADMIN_COOKIE` (Task 6); `GET /api/admin/status` (Task 8); `POST /api/admin/dispatch|command|kis` (Task 9); `DISPATCHABLE` (Task 7).
- Produces: the operator UI. No other code consumes it.

- [ ] **Step 1: Write the page (server component gate)**

```tsx
// app/admin/page.tsx
import { cookies } from "next/headers";
import { ADMIN_COOKIE, verifySession } from "../../lib/adminAuth";
import AdminDashboard from "../../components/AdminDashboard";

export const dynamic = "force-dynamic";

export default function AdminPage() {
  const session = verifySession(cookies().get(ADMIN_COOKIE)?.value);
  if (!session) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gray-950 text-gray-100">
        <a
          href="/api/auth/github/login"
          className="rounded-lg border border-gray-700 px-6 py-3 text-lg hover:bg-gray-800"
        >
          Sign in with GitHub to open the control tower
        </a>
      </main>
    );
  }
  return <AdminDashboard login={session.login} />;
}
```

- [ ] **Step 2: Write the dashboard component**

```tsx
// components/AdminDashboard.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { DISPATCHABLE } from "../lib/controlTower";

const STATE_STYLE: Record<string, string> = {
  ok: "bg-emerald-900/40 border-emerald-600 text-emerald-300",
  stale: "bg-amber-900/40 border-amber-600 text-amber-300",
  dead: "bg-red-900/40 border-red-600 text-red-300",
  unknown: "bg-gray-800 border-gray-600 text-gray-400",
};

function ageLabel(ageMin: number | null): string {
  if (ageMin === null) return "no data";
  if (ageMin < 60) return `${ageMin}m ago`;
  if (ageMin < 48 * 60) return `${Math.round(ageMin / 60)}h ago`;
  return `${Math.round(ageMin / (24 * 60))}d ago`;
}

export default function AdminDashboard({ login }: { login: string }) {
  const [status, setStatus] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/admin/status", { cache: "no-store" });
      if (r.ok) setStatus(await r.json());
    } catch {
      /* keep last snapshot */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000);
    return () => clearInterval(t);
  }, [refresh]);

  async function post(url: string, body: unknown, label: string, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(label);
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      setToast(r.ok ? `✓ ${label}` : `✗ ${label}: ${data.error || r.status}`);
    } catch (e: any) {
      setToast(`✗ ${label}: ${e?.message || "network error"}`);
    } finally {
      setBusy(null);
      setTimeout(refresh, 1500);
      setTimeout(() => setToast(null), 6000);
    }
  }

  const halted = status?.kisVars?.KIS_HALT === "true";

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-6 space-y-8">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">RS2 Control Tower</h1>
        <div className="text-sm text-gray-400">
          {login} · {status ? new Date(status.generatedAt).toLocaleTimeString() : "loading…"}
        </div>
      </header>

      {toast && (
        <div className="rounded border border-gray-600 bg-gray-800 px-4 py-2">{toast}</div>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Rhythms</h2>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {(status?.rhythms ?? []).map((r: any) => (
            <div key={r.key} className={`rounded-lg border p-4 ${STATE_STYLE[r.state]}`}>
              <div className="flex items-center justify-between">
                <span className="font-medium">{r.label}</span>
                <span className="text-xs uppercase">{r.state}</span>
              </div>
              <div className="mt-1 text-sm">{ageLabel(r.ageMin)}</div>
              {(r.state === "stale" || r.state === "dead") && (
                <p className="mt-2 text-xs leading-relaxed opacity-90">{r.manualRecovery}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Cloud dispatch</h2>
        <div className="flex flex-wrap gap-2">
          {Object.entries(DISPATCHABLE).map(([key, d]) => (
            <button
              key={key}
              disabled={busy !== null}
              onClick={() =>
                post("/api/admin/dispatch", { action: key }, d.label,
                  d.danger ? `Dispatch "${d.label}"? This runs a billable cloud job.` : undefined)
              }
              className="rounded border border-gray-600 px-3 py-2 text-sm hover:bg-gray-800 disabled:opacity-50"
            >
              {d.label}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">
          PC commands{" "}
          <span className="text-sm font-normal text-gray-400">
            (executed by the agent within ~5 min while the PC is on)
          </span>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {["depth_pause", "depth_resume", "depth_run_now", "sdf_dispatch", "bot_restart", "state_sync"].map(
            (c) => (
              <button
                key={c}
                disabled={busy !== null}
                onClick={() => post("/api/admin/command", { command: c }, c)}
                className="rounded border border-gray-600 px-3 py-2 text-sm hover:bg-gray-800 disabled:opacity-50"
              >
                {c}
              </button>
            )
          )}
          <a href="/ondemand" className="ml-2 text-sm text-gray-400 underline">
            on-demand /analyze lives on /ondemand
          </a>
        </div>
        <div className="mt-3 max-h-48 overflow-y-auto rounded border border-gray-800">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-900 text-gray-400">
              <tr>
                <th className="px-2 py-1">id</th>
                <th className="px-2 py-1">command</th>
                <th className="px-2 py-1">status</th>
                <th className="px-2 py-1">result</th>
              </tr>
            </thead>
            <tbody>
              {(status?.commands ?? []).map((c: any) => (
                <tr key={c.id} className="border-t border-gray-800">
                  <td className="px-2 py-1">{c.id}</td>
                  <td className="px-2 py-1">{c.command}</td>
                  <td className="px-2 py-1">{c.status}</td>
                  <td className="max-w-md truncate px-2 py-1">{c.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">KIS (real money)</h2>
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-700 p-4">
          <div className="text-sm">
            {Object.entries(status?.kisVars ?? {}).map(([k, v]) => (
              <div key={k}>
                <span className="text-gray-400">{k}:</span> {String(v)}
              </div>
            ))}
          </div>
          <button
            disabled={busy !== null}
            onClick={() =>
              post("/api/admin/kis", { halt: !halted }, halted ? "resume KIS" : "HALT KIS",
                halted
                  ? "Clear KIS_HALT and let the next scheduled sync trade again?"
                  : "Set KIS_HALT=true — the next KIS syncs will refuse to trade. Confirm?")
            }
            className={`rounded px-4 py-2 font-semibold ${
              halted
                ? "border border-emerald-600 text-emerald-300 hover:bg-emerald-900/30"
                : "border border-red-600 text-red-300 hover:bg-red-900/30"
            } disabled:opacity-50`}
          >
            {halted ? "Resume KIS trading" : "HALT KIS trading"}
          </button>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Recent workflow runs</h2>
        <div className="max-h-64 overflow-y-auto rounded border border-gray-800">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-900 text-gray-400">
              <tr>
                <th className="px-2 py-1">workflow</th>
                <th className="px-2 py-1">event</th>
                <th className="px-2 py-1">result</th>
                <th className="px-2 py-1">when</th>
              </tr>
            </thead>
            <tbody>
              {(status?.workflows ?? []).map((w: any, i: number) => (
                <tr key={i} className="border-t border-gray-800">
                  <td className="px-2 py-1">
                    <a href={w.html_url} target="_blank" rel="noreferrer" className="underline">
                      {w.name}
                    </a>
                  </td>
                  <td className="px-2 py-1">{w.event}</td>
                  <td className="px-2 py-1">{w.conclusion ?? w.status}</td>
                  <td className="px-2 py-1">{new Date(w.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Type-check + visual verify**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && npx tsc --noEmit
```

Expected: no new errors. Then in the signed-in browser open `http://localhost:3000/admin`: 7 rhythm cards with sensible states (depth ok/stale per its real age, pc ok while the agent runs); `KIS_LEDGER: equal_llm` visible; command buttons enqueue rows that flip to `done` within 5 min; incognito window shows only the sign-in button.

- [ ] **Step 4: Commit**

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && git add app/admin components/AdminDashboard.tsx && git commit -m "feat(admin): control tower dashboard"
```

- [ ] **Step 5 (MANUAL — operator): deploy + production smoke**

Push to `main` (Vercel auto-deploys). Confirm the four OAuth env vars exist in Vercel first. Then from a phone (not on home network): sign in at `https://<site>/admin`, confirm rhythm cards render and a `state_sync` command round-trips. This is the "control it from remote" acceptance test.

```bash
cd "/c/Users/riper/Downloads/Stock Screener/Stock Screener" && git push origin main
```

---

# Phase C — Depth cloud backstop (rs2-local repo)

**What this is:** when the PC is off and the depth overlay goes stale (>30h) and the PC heartbeat is dead (>90 min), a daily GitHub Actions workflow runs the existing DeepSeek arm (`api_llm/deep_api_run.py --fresh`) on the N most-overdue live-book tickers, publishes through the same `publish_overlay()` engine, and hands the new ledger rows back to the PC via `rs2-state/cloud_pending/`.

**Degraded-mode caveats (deliberate, accepted):** cloud verdicts have no local research brief (`research_brief_age_days: None`, published via `--include-no-brief`), best-effort SearXNG-in-CI web research, and no `sec_facts` share verification. Every row is stamped `arm: cloud_api` and the name returns to the local arm on the usual triggers (8-K, 10-Q/K, 8% move, pack revision, 90d rotation). Cost ~$0.11 and ~20 min per ticker; a 6-ticker run ≈ $0.70 / ~2h, and it only fires when the PC has been dead >30h.

**Safety invariants (from the api_llm investigation):**
1. `rebuild_overlay()` regenerates the overlay from the ENTIRE ledger — running with a partial ledger would wipe the ~182 published tickers. The workflow refuses to run unless `rs2-state/cache/depth_ledger.jsonl` exists (Task 3 syncs it hourly), and the driver aborts if the rebuilt overlay has fewer tickers than the published one.
2. `publish_overlay()`'s local file lock cannot serialize against the PC; a same-minute PC publish surfaces as a rebase abort + Telegram alert, not corruption — and the preflight only runs when the PC heartbeat is dead anyway.
3. `protected_local()` already prevents cloud rows from shadowing newer local verdicts.

### Task 11: Commit the untracked modules the cloud arm needs

**Files:**
- Commit (already exist, untracked): `C:\Users\riper\Downloads\RS2 Local\depth_ondemand.py`, `C:\Users\riper\Downloads\RS2 Local\api_llm\rederive_cloud.py`

**Interfaces:**
- Produces: a clean `git clone` of rs2-local that can `import orchestrate_depth` (its line 36 does a module-level `import depth_ondemand`, which is currently untracked — a fresh clone dies with `ModuleNotFoundError`). Required by Task 13's workflow.

- [ ] **Step 1: Commit exactly these two files (repo has 13 unrelated dirty files — do not stage anything else)**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add depth_ondemand.py api_llm/rederive_cloud.py && git commit -m "feat(cloud-arm): track depth_ondemand + rederive_cloud (clean-clone import fix)" && git status --short | head -20
```

Expected: commit created; status still shows the 13 modified files unstaged (untouched).

- [ ] **Step 2: Push (the cloud workflow clones origin)**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git push origin main
```

- [ ] **Step 3: Prove a clean clone imports**

```bash
cd "$(mktemp -d)" && git clone --depth 1 https://github.com/riperdy-tech/rs2-local.git && cd rs2-local && mkdir -p cache && python -c "import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'api_llm'); import orchestrate_depth; import publish_cloud_verdicts; print('imports ok')"
```

Expected: `imports ok`. (Root `config.json` is tracked with real Windows paths, which exist on this PC; the cloud workflow patches them — Task 13.) If an import still fails on another untracked module, commit that module the same way and note it in the task journal.

**NOTE for the operator (out of plan scope):** the 13 dirty tracked files mean the cloud runs origin's slightly older code than the PC runs locally. Recommend reviewing/committing that live work separately soon.

---

### Task 12: `api_llm/cloud_backstop.py` driver

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\api_llm\cloud_backstop.py`
- Test: `C:\Users\riper\Downloads\RS2 Local\tests\test_cloud_backstop.py`

**Interfaces:**
- Consumes: `orchestrate_depth.live_book()` / `rebuild-overlay` side effects via `publish_cloud_verdicts.py` subprocess; `orchestrate_depth.publish_overlay()`; `orchestrate_depth.CONFIG["screener_publish_repo"]`; `ops.notify_telegram`; env `RS2_STATE_DIR` (path to the rs2-state checkout), `BACKSTOP_MAX_TICKERS` (default 6); the rs2-state `cloud_pending/depth_ledger_delta.jsonl` contract from Task 3.
- Produces: `select_due(book: set, rows: list, n: int) -> list`, `newest_dates(rows: list) -> dict`, `compute_delta(before_lines: list, after_lines: list) -> list` (pure, tested); `main() -> int` (exit code) — invoked by Task 13's workflow. Heavy imports happen lazily inside `main()` so tests stay hermetic.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cloud_backstop.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_llm"))
import cloud_backstop  # noqa: E402


def test_newest_dates_takes_max():
    rows = [
        {"ticker": "AAA", "date": "2026-08-01"},
        {"ticker": "AAA", "date": "2026-08-20"},
        {"ticker": "BBB", "date": "2026-07-15"},
    ]
    assert cloud_backstop.newest_dates(rows) == {"AAA": "2026-08-20", "BBB": "2026-07-15"}


def test_select_due_oldest_first_never_ledgered_wins():
    book = {"AAA", "BBB", "CCC", "DDD"}
    rows = [
        {"ticker": "AAA", "date": "2026-08-20"},
        {"ticker": "BBB", "date": "2026-06-01"},
        {"ticker": "CCC", "date": "2026-07-01"},
    ]
    # DDD has no verdict at all -> first; then oldest dates ascending
    assert cloud_backstop.select_due(book, rows, 3) == ["DDD", "BBB", "CCC"]


def test_select_due_respects_n():
    book = {"AAA", "BBB"}
    assert len(cloud_backstop.select_due(book, [], 1)) == 1


def test_compute_delta_only_new_lines():
    before = ['{"run": 1}', '{"run": 2}']
    after = ['{"run": 1}', '{"run": 2}', '{"run": 3}']
    assert cloud_backstop.compute_delta(before, after) == ['{"run": 3}']
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_cloud_backstop.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cloud_backstop'`.

- [ ] **Step 3: Write the implementation**

```python
# api_llm/cloud_backstop.py
"""Depth cloud backstop driver — run by .github/workflows/depth-cloud-backstop.yml
on ubuntu-latest when the PC has missed depth sweeps (see the workflow preflight).

Degraded mode by design: no local research brief (published with
--include-no-brief), CI SearXNG only, no sec_facts verification. Rows are
stamped arm=cloud_api and return to the local arm on the usual triggers.

Flow:
  1. snapshot the ledger line-set (seeded from rs2-state by the workflow)
  2. pick the N live_book tickers with the oldest newest-verdict
  3. run deep_api_run.py T --fresh sequentially
  4. publish_cloud_verdicts.py --include-no-brief (no --push):
     ledger append + pending bundles + overlay rebuild
  5. overlay-count guard: rebuilt overlay must not shrink vs the published one
  6. orchestrate_depth.publish_overlay()  (same engine + invariants as the PC)
  7. append new ledger lines to $RS2_STATE_DIR/cloud_pending/depth_ledger_delta.jsonl,
     commit + push rs2-state (the PC imports + truncates via sync_state.py)
  8. Telegram summary
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
ROOT = API_DIR.parent
sys.path.insert(0, str(ROOT))

LEDGER = ROOT / "cache" / "depth_ledger.jsonl"
OVERLAY = ROOT / "cache" / "depth_overlay.json"
PER_TICKER_TIMEOUT_S = 3600


def _read_lines(p: Path) -> list:
    try:
        return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []


def newest_dates(rows: list) -> dict:
    out = {}
    for r in rows:
        t = r.get("ticker")
        d = str(r.get("date") or "")
        if t and d >= out.get(t, ""):
            out[t] = d
    return out


def select_due(book: set, rows: list, n: int) -> list:
    """Oldest newest-verdict first; never-ledgered names sort before everything."""
    newest = newest_dates(rows)
    return sorted(book, key=lambda t: (newest.get(t, ""), t))[:n]


def compute_delta(before_lines: list, after_lines: list) -> list:
    before = set(before_lines)
    return [ln for ln in after_lines if ln not in before]


def _overlay_count(path: Path) -> int:
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("tickers", {}))
    except (OSError, ValueError):
        return 0


def _synced_with_remote(repo: Path) -> bool:
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "-C", str(repo), "ls-remote", "origin",
                             "-h", "refs/heads/main"],
                            capture_output=True, text=True).stdout.split()
    return bool(head) and bool(remote) and remote[0] == head


def main() -> int:
    max_tickers = int(os.environ.get("BACKSTOP_MAX_TICKERS", "6"))
    state_dir = Path(os.environ["RS2_STATE_DIR"])

    import ops  # noqa: E402  (lazy: keeps unit tests hermetic)
    import orchestrate_depth as od  # noqa: E402

    before = _read_lines(LEDGER)
    if not before:
        ops.notify_telegram("depth backstop ABORT: seeded ledger is empty — "
                            "publishing would wipe the live overlay")
        return 1
    rows = []
    for ln in before:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            pass

    due = select_due(set(od.live_book()), rows, max_tickers)
    if not due:
        print("nothing due")
        return 0
    print(f"backstop running {len(due)} tickers: {due}")

    ran, failed = [], []
    for t in due:
        r = subprocess.run(
            [sys.executable, str(API_DIR / "deep_api_run.py"), t, "--fresh"],
            cwd=str(ROOT), timeout=PER_TICKER_TIMEOUT_S)
        (ran if r.returncode == 0 else failed).append(t)

    if not ran:
        ops.notify_telegram(f"depth backstop: all {len(failed)} runs failed "
                            f"({failed}) — nothing to publish")
        return 1

    pub = subprocess.run(
        [sys.executable, str(API_DIR / "publish_cloud_verdicts.py"), "--include-no-brief"],
        cwd=str(ROOT), timeout=600)
    if pub.returncode != 0:
        ops.notify_telegram("depth backstop ABORT: publish_cloud_verdicts failed "
                            f"(rc={pub.returncode})")
        return 1

    published_overlay = (Path(od.CONFIG["screener_publish_repo"])
                         / "public" / "data" / "depth_overlay.json")
    old_count = _overlay_count(published_overlay)
    new_count = _overlay_count(OVERLAY)
    if new_count < old_count:
        ops.notify_telegram(f"depth backstop ABORT: rebuilt overlay {new_count} "
                            f"tickers < published {old_count} — ledger seed "
                            "incomplete, NOT publishing")
        return 1

    od.publish_overlay()
    pushed = _synced_with_remote(Path(od.CONFIG["screener_publish_repo"]))

    after = _read_lines(LEDGER)
    delta = compute_delta(before, after)
    if delta:
        pending = state_dir / "cloud_pending"
        pending.mkdir(exist_ok=True)
        with (pending / "depth_ledger_delta.jsonl").open("a", encoding="utf-8") as f:
            for ln in delta:
                f.write(ln + "\n")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        for args in (["add", "-A"], ["commit", "-m", f"cloud backstop delta {ts}"],
                     ["pull", "--rebase"], ["push"]):
            subprocess.run(["git", "-C", str(state_dir), *args],
                           capture_output=True, text=True, timeout=120)

    ops.notify_telegram(
        f"depth cloud backstop: ran {ran}, failed {failed}, "
        f"push {'ok' if pushed else 'ABORTED (see prior alert)'}, "
        f"{len(delta)} delta rows to rs2-state")
    return 0 if pushed else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python -m pytest tests/test_cloud_backstop.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit + push**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add api_llm/cloud_backstop.py tests/test_cloud_backstop.py && git commit -m "feat(cloud-arm): backstop driver (due selection, count guard, state delta)" && git push origin main
```

---

### Task 13: `depth-cloud-backstop.yml` workflow + secrets

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\.github\workflows\depth-cloud-backstop.yml` (rs2-local's first workflow)

**Interfaces:**
- Consumes: `api_llm/cloud_backstop.py` (Task 12); rs2-state repo (Task 3); Supabase heartbeat (Tasks 1-5); GitHub secrets created in Step 1; the admin dashboard's `depth-cloud-backstop` dispatch button (Phase B, already whitelisted in `DISPATCHABLE`).
- Produces: daily freshness-gated cron `5 3 * * *` UTC + `workflow_dispatch` with inputs `force` (boolean) and `max_tickers` (string, default "6").

- [ ] **Step 1 (MANUAL — operator): create rs2-local repo secrets**

`CROSS_REPO_PAT` = a GitHub PAT (classic, `repo` scope) that can push to `riperdy-tech/stock-screener` and `riperdy-tech/rs2-state` — the same PAT already stored as `GH_PAT` in Vercel works. `RS2_LLM_API_KEY` = the DeepSeek key (the `LLM_API_KEY` value from `.secrets.json`). Telegram + Supabase values as already used elsewhere.

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && gh secret set CROSS_REPO_PAT -R riperdy-tech/rs2-local && gh secret set RS2_LLM_API_KEY -R riperdy-tech/rs2-local && gh secret set RS2_TG_BOT_TOKEN -R riperdy-tech/rs2-local && gh secret set RS2_TG_CHAT_ID -R riperdy-tech/rs2-local && gh secret set RS2_SUPABASE_URL -R riperdy-tech/rs2-local && gh secret set RS2_SUPABASE_SERVICE_KEY -R riperdy-tech/rs2-local
```

(Each command prompts for the value; paste from the respective source. Never echo values into the shell history.)

- [ ] **Step 2: Write the workflow**

```yaml
# .github/workflows/depth-cloud-backstop.yml
# Depth cloud backstop: keeps the depth overlay moving when the PC is off.
# Primary = the PC's RS2-Depth-Orchestrator task. This fires only when the
# overlay is >30h stale AND the PC heartbeat is >90min dead (or on force).
name: Depth Cloud Backstop

on:
  schedule:
    - cron: "5 3 * * *"   # daily 03:05 UTC = 11:05 Taipei
  workflow_dispatch:
    inputs:
      force:
        description: "Skip freshness + PC-alive gates"
        type: boolean
        default: false
      max_tickers:
        description: "Max tickers this run"
        default: "6"

concurrency:
  group: depth-backstop
  cancel-in-progress: false

jobs:
  preflight:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    outputs:
      run: ${{ steps.gate.outputs.run }}
    steps:
      - name: Gate on overlay freshness + PC heartbeat
        id: gate
        env:
          SB_URL: ${{ secrets.RS2_SUPABASE_URL }}
          SB_KEY: ${{ secrets.RS2_SUPABASE_SERVICE_KEY }}
          TG_TOKEN: ${{ secrets.RS2_TG_BOT_TOKEN }}
          TG_CHAT: ${{ secrets.RS2_TG_CHAT_ID }}
          FORCE: ${{ inputs.force }}
        run: |
          python3 - <<'EOF'
          import json, os, urllib.request
          from datetime import datetime, timezone, timedelta

          def out(run, why):
              with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                  f.write(f"run={'true' if run else 'false'}\n")
              print(f"backstop gate: {why}")

          if os.environ.get("FORCE") == "true":
              out(True, "forced by operator"); raise SystemExit

          overlay_h = 9999.0  # fail-open, same policy as the SDF preflight
          try:
              raw = ("https://raw.githubusercontent.com/riperdy-tech/"
                     "stock-screener/main/public/data/depth_overlay.json")
              with urllib.request.urlopen(raw, timeout=30) as r:
                  gen = json.load(r)["generated_at"]
              # generated_at is NAIVE Taipei local time (+08:00), no suffix
              ts = datetime.fromisoformat(gen).replace(
                  tzinfo=timezone(timedelta(hours=8)))
              overlay_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
          except Exception as e:
              print(f"overlay read failed ({e}) -> treating as stale")

          hb_min = 9999.0
          try:
              url = (os.environ["SB_URL"].rstrip("/")
                     + "/rest/v1/control_heartbeat?id=eq.rs2-pc&select=updated_at")
              req = urllib.request.Request(url, headers={
                  "apikey": os.environ["SB_KEY"],
                  "Authorization": "Bearer " + os.environ["SB_KEY"]})
              with urllib.request.urlopen(req, timeout=30) as r:
                  rows = json.load(r)
              if rows:
                  hb = datetime.fromisoformat(
                      rows[0]["updated_at"].replace("Z", "+00:00"))
                  hb_min = (datetime.now(timezone.utc) - hb).total_seconds() / 60
          except Exception as e:
              print(f"heartbeat read failed ({e}) -> treating PC as dead")

          if overlay_h <= 30:
              out(False, f"overlay fresh ({overlay_h:.1f}h)"); raise SystemExit
          if hb_min <= 90:
              out(False, f"overlay stale ({overlay_h:.1f}h) but PC alive "
                         f"({hb_min:.0f}m) — alerting, not running")
              try:
                  tok = os.environ.get("TG_TOKEN"); chat = os.environ.get("TG_CHAT")
                  if tok and chat:
                      body = json.dumps({"chat_id": chat, "text":
                          f"[control-tower] depth overlay stale {overlay_h:.1f}h "
                          "but the PC heartbeat is LIVE — check the orchestrator "
                          "locally (status.py). Cloud backstop NOT run."}).encode()
                      urllib.request.urlopen(urllib.request.Request(
                          f"https://api.telegram.org/bot{tok}/sendMessage",
                          data=body, headers={"Content-Type": "application/json"}),
                          timeout=15)
              except Exception:
                  pass
              raise SystemExit
          out(True, f"overlay {overlay_h:.1f}h stale, PC dead {hb_min:.0f}m")
          EOF

  backstop:
    needs: preflight
    if: needs.preflight.outputs.run == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 340
    steps:
      - name: Checkout rs2-local
        uses: actions/checkout@v4
        with:
          path: rs2-local

      - name: Checkout screener data (read)
        uses: actions/checkout@v4
        with:
          repository: riperdy-tech/stock-screener
          token: ${{ secrets.CROSS_REPO_PAT }}
          path: screener
          fetch-depth: 1

      - name: Checkout screener publish clone (write)
        uses: actions/checkout@v4
        with:
          repository: riperdy-tech/stock-screener
          token: ${{ secrets.CROSS_REPO_PAT }}
          path: screener-publish
          fetch-depth: 1

      - name: Checkout rs2-state
        uses: actions/checkout@v4
        with:
          repository: riperdy-tech/rs2-state
          token: ${{ secrets.CROSS_REPO_PAT }}
          path: rs2-state
          fetch-depth: 1

      - name: Seed local state from rs2-state (refuse if ledger missing)
        working-directory: rs2-local
        run: |
          mkdir -p cache
          if [ ! -s ../rs2-state/cache/depth_ledger.jsonl ]; then
            echo "::error::rs2-state has no depth_ledger.jsonl — refusing (a partial ledger would wipe the published overlay)"
            exit 1
          fi
          cp ../rs2-state/cache/depth_ledger.jsonl cache/
          cp ../rs2-state/cache/depth_ondemand_ledger.jsonl cache/ 2>/dev/null || true
          cp ../rs2-state/cache/depth_ondemand.jsonl cache/ 2>/dev/null || true

      - name: Point config at runner paths
        working-directory: rs2-local
        run: |
          python3 - <<'EOF'
          import json, os
          from pathlib import Path
          p = Path("config.json")
          cfg = json.loads(p.read_text(encoding="utf-8"))
          ws = os.environ["GITHUB_WORKSPACE"]
          cfg["screener_data_dir"] = f"{ws}/screener/public/data"
          cfg["screener_publish_repo"] = f"{ws}/screener-publish"
          p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
          print("patched screener_data_dir + screener_publish_repo")
          EOF

      - name: Write .secrets.json
        working-directory: rs2-local
        env:
          LLM: ${{ secrets.RS2_LLM_API_KEY }}
          TG_TOKEN: ${{ secrets.RS2_TG_BOT_TOKEN }}
          TG_CHAT: ${{ secrets.RS2_TG_CHAT_ID }}
        run: |
          python3 - <<'EOF'
          import json, os
          json.dump({"LLM_API_KEY": os.environ["LLM"],
                     "telegram_bot_token": os.environ.get("TG_TOKEN", ""),
                     "telegram_chat_id": os.environ.get("TG_CHAT", "")},
                    open(".secrets.json", "w"))
          EOF

      - name: Git identity for publish + state push
        run: |
          git config --global user.name "riperdy-tech"
          git config --global user.email "riperdy@gmail.com"

      - name: Start SearXNG (best effort — runs degrade soft without it)
        continue-on-error: true
        working-directory: rs2-local
        run: |
          mkdir -p /tmp/searxng
          cp searxng/settings.yml.example /tmp/searxng/settings.yml
          KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
          sed -i "s/secret_key:.*/secret_key: \"$KEY\"/" /tmp/searxng/settings.yml
          docker run -d --name searxng -p 8888:8080 -v /tmp/searxng:/etc/searxng searxng/searxng
          sleep 15
          curl -s -o /dev/null -w "searxng probe: %{http_code}\n" "http://localhost:8888/search?q=test&format=json" || true

      - name: Run backstop driver
        working-directory: rs2-local
        env:
          RS2_STATE_DIR: ${{ github.workspace }}/rs2-state
          BACKSTOP_MAX_TICKERS: ${{ inputs.max_tickers || '6' }}
        run: python3 api_llm/cloud_backstop.py
```

Implementer notes: (a) the `sed` on `settings.yml.example` assumes a `secret_key:` line exists — check the tracked example and adjust the pattern if its shape differs; the whole step is `continue-on-error`, and a dead SearXNG only means `searxng_up: false` on the verdicts. (b) `inputs.max_tickers` is empty on `schedule` events — the `|| '6'` fallback covers it.

- [ ] **Step 3: Commit + push**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add .github/workflows/depth-cloud-backstop.yml && git commit -m "feat(cloud-arm): freshness-gated depth cloud backstop workflow" && git push origin main
```

- [ ] **Step 4: Verify the gate skips when healthy**

```bash
gh workflow run depth-cloud-backstop.yml -R riperdy-tech/rs2-local && sleep 40 && gh run list --workflow depth-cloud-backstop.yml -R riperdy-tech/rs2-local --limit 1
```

Expected: run completes green in ~1 min; preflight log says either `overlay fresh` or `PC alive` and the `backstop` job shows as skipped. (Dispatch without `-f force=true` uses the real gates.)

- [ ] **Step 5: One forced end-to-end run (cheap: 1 ticker ≈ $0.11, ~25 min)**

Precondition: Task 3's live sync has pushed a current `cache/depth_ledger.jsonl` to rs2-state (`python sync_state.py` on the PC to be sure).

```bash
gh workflow run depth-cloud-backstop.yml -R riperdy-tech/rs2-local -f force=true -f max_tickers=1 && gh run watch -R riperdy-tech/rs2-local
```

Expected, in order: run green; Telegram summary `depth cloud backstop: ran ['<T>'] ... push ok, 1 delta rows`; `riperdy-tech/stock-screener` main has a fresh `depth_overlay.json: sweep update (band_direction_v1)` commit whose overlay ticker count is ≥ the previous count; `riperdy-tech/rs2-state` has a `cloud backstop delta` commit with one row in `cloud_pending/depth_ledger_delta.jsonl`.

- [ ] **Step 6: Verify the PC imports the delta**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && python sync_state.py
```

Expected: output contains `import 1 cloud rows`; the last line of `cache\depth_ledger.jsonl` is the cloud row (`"arm": "cloud_api"`, `"published_by"` set); rs2-state's delta file is empty again after the sync's push.

---

### Task 14: Failover drill + operator runbook

**Files:**
- Create: `C:\Users\riper\Downloads\RS2 Local\docs\CONTROL_TOWER.md`

**Interfaces:**
- Consumes: everything above. Produces: the acceptance proof + the "tell me what to do" document.

- [ ] **Step 1: Write the runbook**

```markdown
# RS2 Control Tower — Operator Runbook

Admin site: https://<your-vercel-domain>/admin (GitHub sign-in, riperdy-tech only)

## Architecture (one paragraph)
The PC pushes a heartbeat + rhythm snapshot to Supabase every 5 min
(RS2-Control-Agent -> control_agent.py) and backs depth state up to the private
rs2-state repo hourly (sync_state.py). The /admin site reads the heartbeat, the
committed freshness stamps, and the GitHub Actions API; its buttons either
dispatch whitelisted workflows (GH_PAT) or enqueue PC commands in Supabase,
which the agent executes within ~5 min. When the PC is off: SDF falls back to
the GitHub cron backstop (existing), and the depth sweep falls back to
depth-cloud-backstop.yml in rs2-local (DeepSeek arm, state from rs2-state,
gated on overlay >30h stale + heartbeat >90min dead).

## PC-off playbook (PC won't power on)
1. Open /admin. Expect: "RS2 PC" card dead; depth going stale over the day.
2. Do nothing for SDF/KIS/price/weekly — they are cloud-native or auto-backstopped.
3. Depth: wait for the daily 03:05 UTC backstop, or press "Depth cloud backstop"
   (confirm dialog) to run it now. Cost ~$0.70/run of 6 names, degraded research.
4. On-demand /analyze executes on the PC only: /ondemand requests keep queueing
   in Supabase ondemand_queue and drain when the PC (bot bridge) returns. The
   Telegram bot is down too; alerts still arrive from cloud workflows.
5. KIS emergency: the "HALT KIS trading" button sets repo var KIS_HALT=true.

## PC-return playbook
1. Power on + log in (tasks are interactive-logon). Agent resumes within 5 min;
   /admin "RS2 PC" goes green.
2. The next agent pass (or `python sync_state.py`) imports any cloud
   `cloud_pending/depth_ledger_delta.jsonl` rows into the local ledger and
   truncates the delta. Verify: tail cache/depth_ledger.jsonl for arm=cloud_api.
3. Nothing else to reconcile: cloud verdicts return to the local arm on the
   usual triggers (8-K, filings, 8% move, pack revision, 90d rotation).

## Manual command equivalents (no admin site needed)
- Data fetch (cloud):  gh workflow run schedule-data-fetch.yml -R riperdy-tech/stock-screener -f runner=ubuntu-latest
- Depth backstop:      gh workflow run depth-cloud-backstop.yml -R riperdy-tech/rs2-local -f force=true
- Halt KIS:            gh variable set KIS_HALT -R riperdy-tech/stock-screener -b true
- PC depth pause/run:  create/delete cache\DEPTH_PAUSED, or schtasks /run /tn RS2-Depth-Orchestrator

## Known limits
- Scheduled tasks are interactive-logon: a powered-on but logged-out PC counts
  as "off" to the tower.
- Cloud depth verdicts carry no research brief and no sec_facts verification
  (stamped research_brief_age_days: null, searxng best-effort).
- One operator account (riperdy-tech) is the only admin.
```

Replace `<your-vercel-domain>` with the real domain before committing.

- [ ] **Step 2: Drill — simulate PC death**

```bash
schtasks /change /tn "RS2-Control-Agent" /disable
```

Wait ~20 min. Expected: /admin "RS2 PC" card turns `stale` (threshold 15 min) and shows its manualRecovery text. (Full `dead` takes 60 min — stale is sufficient proof of detection.)

- [ ] **Step 3: Drill — remote reroute**

From /admin (ideally from a phone off the home network): press "Depth cloud backstop". Expected: toast `✓ Depth cloud backstop`; a `workflow_dispatch` run appears in the Recent workflow runs table; preflight gates it correctly (skips as "PC alive" only if the heartbeat is <90 min old — with the agent disabled >90 min it proceeds; for a fast drill, dispatch with force from the button and accept one 6-name run, or wait out the 90 min for full fidelity).

- [ ] **Step 4: Drill — recovery**

```bash
schtasks /change /tn "RS2-Control-Agent" /enable && schtasks /run /tn "RS2-Control-Agent"
```

Expected: within 2 min /admin "RS2 PC" is `ok` again; any backstop delta rows import on the next hourly sync (or run `python sync_state.py` now).

- [ ] **Step 5: Commit**

```bash
cd "/c/Users/riper/Downloads/RS2 Local" && git add docs/CONTROL_TOWER.md && git commit -m "docs(control-tower): operator runbook + drill results" && git push origin main
```

---

# Out of scope, flagged for separate work

- `app/api/refresh-mine/route.ts` dispatches a workflow with **no auth at all**, and `app/api/analysis/route.ts` accepts the hardcoded password `"RSYS"` (also present client-side in `components/StockDetailModal.tsx:32`). Public-user features — gating them behind the admin session would break site users, so they need their own fix (rate-limit / separate secret). Not touched by this plan.
- The 13 uncommitted modified tracked files in rs2-local (live pipeline code) predate this plan; commit them in a separate reviewed change.
- `zombie task RS2-Orchestrator` (fires daily + logon, no-ops on `cache/PAUSED`) — deregister in separate cleanup if desired.

# Execution order & independence

- Phase A (Tasks 1-5) and Phase B Tasks 6-7 can run in parallel. Task 8 needs 4+7; Task 9 needs 6+7 (and 1 for commands to land); Task 10 needs 8+9. Phase C needs Tasks 3, 11, 12 before 13; Task 14 last.
- Each phase delivers standalone value: A alone = heartbeat + SDF primary fix + state backup; A+B = full remote control tower with manual reroutes; C adds the automatic depth failover.


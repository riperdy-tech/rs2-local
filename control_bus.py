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

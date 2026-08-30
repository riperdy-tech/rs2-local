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


def _sync_fail_alert(result) -> None:
    """3-strike alarm on state-sync rot (mirrors _heartbeat_with_alert).
    `result` is None when the sync raised. Never raises.

    A silently rotting rs2-state backup is invisible until the cloud backstop
    seeds from it — at which point it publishes an overlay built on stale state.
    """
    marker = CACHE / "state_sync_fail.json"
    if not (result is None or str(result).startswith("error")):
        try:
            marker.unlink(missing_ok=True)
        except OSError as unlink_err:
            _log(f"sync fail marker clear failed: {unlink_err}")
        return
    fails = (_read_json(marker) or {}).get("count", 0) + 1
    _log(f"state sync failed ({fails}): {result}")
    if fails == 3:
        try:
            ops.notify_telegram(
                "control_agent: 3 consecutive state-sync failures — rs2-state "
                "backup is rotting; cloud backstop would seed stale data")
        except Exception as alert_err:  # noqa: BLE001
            _log(f"sync alert send failed: {alert_err}")
            fails = 2  # hold below the threshold so the alert retries
    try:
        marker.write_text(json.dumps({"count": fails}), encoding="utf-8")
    except OSError as write_err:
        _log(f"sync fail marker write failed: {write_err}")


def _cmd_state_sync(args: dict) -> str:
    # Marker written in finally: a raising sync must still stamp the attempt,
    # or maybe_sync_state's hourly gate re-runs a broken sync every 5 minutes.
    result = None
    try:
        result = sync_state.main()
        return result
    finally:
        (CACHE / "state_sync_last.json").write_text(
            json.dumps({"ts": _now(), "result": result if result is not None else "raised"}),
            encoding="utf-8")
        _sync_fail_alert(result)


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
    """Push the heartbeat; alert on the 3rd consecutive failure. Never raises."""
    marker = CACHE / "control_agent_hbfail.json"
    try:
        control_bus.push_heartbeat("rs2-pc", snapshot)
        marker.unlink(missing_ok=True)
        return
    except Exception as e:  # noqa: BLE001 — scheduled entry point must not die
        fails = (_read_json(marker) or {}).get("count", 0) + 1
        _log(f"heartbeat push failed ({fails}): {e}")
        if fails == 3:
            try:
                ops.notify_telegram("control_agent: 3 consecutive heartbeat failures — "
                                    "control tower is blind to this PC")
            except Exception as alert_err:  # noqa: BLE001
                _log(f"alert send failed: {alert_err}")
                fails = 2  # keep the counter below the threshold so the alert retries
        try:
            marker.write_text(json.dumps({"count": fails}), encoding="utf-8")
        except OSError as write_err:
            _log(f"hbfail marker write failed: {write_err}")


def main() -> None:
    # The heartbeat must go out even when snapshot collection breaks — a
    # degraded payload still proves the PC is alive, and the push failure
    # counter (the blindness alert) must keep running either way.
    try:
        snapshot = collect_snapshot()
    except Exception as e:  # noqa: BLE001
        _log(f"snapshot failed: {e}")
        try:
            host = socket.gethostname()
        except OSError:
            host = ""
        snapshot = {"ts": _now(), "host": host, "snapshot_error": str(e)[:300]}
    _heartbeat_with_alert(snapshot)
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

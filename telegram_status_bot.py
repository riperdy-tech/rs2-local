"""telegram_status_bot.py — on-demand /status replies for the RS2 bot (operator order
2026-08-09).

Long-polls Telegram getUpdates and answers "/status" (or any message containing "status")
with the live picture: orchestrator state (current ticker, sweep progress, per-name pace,
sweep ETA from cache/orchestrate_progress.json), baseline campaign count
(cache/baseline_campaign.json), and the last heartbeat. Read-only over the same files
status.py reads — it never touches the pipeline.

SECURITY: replies ONLY to the configured telegram_chat_id from .secrets.json; every other
chat is ignored silently (the bot token is long-lived — anyone discovering the bot must
get nothing).

Run:  python telegram_status_bot.py            (foreground)
It is safe to kill and restart at any time; offset state is kept in
cache/telegram_bot_offset.json so old messages are not replayed.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OFFSET = CACHE / "telegram_bot_offset.json"


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _cfg():
    sec = _load(HERE / ".secrets.json") or {}
    return sec.get("telegram_bot_token"), str(sec.get("telegram_chat_id") or "")


def _api(tok, method, params=None, timeout=60):
    url = f"https://api.telegram.org/bot{tok}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read().decode())


def _lock_alive():
    # the lock is PLAIN TEXT: "<pid> <iso-timestamp>" — not JSON
    try:
        raw = (CACHE / "orchestrate.lock").read_text(encoding="utf-8-sig").split()
        pid = int(raw[0])
    except Exception:
        return None
    try:
        import psutil  # optional
        return pid if psutil.pid_exists(pid) else False
    except Exception:
        # fallback: os.kill probe is unix-ish; on Windows use tasklist presence
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True,
                             text=True).stdout
        return pid if str(pid) in out else False


def compose_status():
    lines = [f"📊 RS2 status @ {datetime.now().strftime('%H:%M:%S')}"]
    prog = _load(CACHE / "orchestrate_progress.json")
    alive = _lock_alive()
    if prog and not prog.get("finished") and alive:
        cur = prog.get("current")
        lines.append(f"▶ running: {cur or '?'} ({prog.get('reason', '')})")
        lines.append(f"   sweep: {prog.get('done_this_run', 0)} done, "
                     f"{prog.get('failed_this_run', 0)} failed attempts, "
                     f"{max((prog.get('queue_total') or 0) - (prog.get('idx') or 0), 0)} queued")
        if prog.get("avg_sec_per_ticker"):
            lines.append(f"   pace: ~{round(prog['avg_sec_per_ticker']/60, 1)} min/attempt"
                         + (f" | sweep ETA {prog.get('eta_finish')}" if prog.get("eta_finish")
                            else ""))
    elif prog and prog.get("finished"):
        lines.append(f"⏸ no sweep running (last sweep: {prog.get('done_this_run')} attempts, "
                     f"{prog.get('failed_this_run')} failed; updated {prog.get('updated')})")
    else:
        lines.append("⏸ orchestrator idle (no live lock)")
    camp = _load(CACHE / "baseline_campaign.json")
    if camp:
        done_n = len(camp.get("done", []))
        total = 172
        rem = total - done_n
        # measured campaign pace: ~16 min per resolved name incl. retries (batches 5-6)
        eta_h = round(rem * 16 / 60, 1)
        lines.append(f"🎯 baseline: {done_n}/{total} clean | ~{rem} to go "
                     f"(~{eta_h}h at measured pace)")
        if camp.get("freeze"):
            lines.append("🧊 rule freeze active")
    hb = _load(CACHE / "heartbeat.json")
    if hb:
        lines.append(f"💓 last heartbeat: {hb.get('status')} (ran {hb.get('ran')}, "
                     f"failed {hb.get('failed')}) @ {hb.get('ts', '')[:19]}")
    return "\n".join(lines)


def main():
    tok, chat = _cfg()
    if not (tok and chat):
        print("no telegram_bot_token/telegram_chat_id in .secrets.json — exiting")
        return
    me = _api(tok, "getMe", timeout=20)
    print(f"listening as @{me.get('result', {}).get('username')} for chat {chat}")
    off = (_load(OFFSET) or {}).get("offset", 0)
    while True:
        try:
            upd = _api(tok, "getUpdates", {"timeout": 50, "offset": off + 1}, timeout=70)
            for u in upd.get("result", []):
                off = max(off, u.get("update_id", 0))
                OFFSET.write_text(json.dumps({"offset": off}), encoding="utf-8")
                msg = u.get("message") or {}
                if str((msg.get("chat") or {}).get("id")) != chat:
                    continue          # not the operator — ignore silently
                text = (msg.get("text") or "").lower()
                if "status" in text:
                    _api(tok, "sendMessage", {"chat_id": chat, "text": compose_status()},
                         timeout=20)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"poll error (retrying in 15s): {str(e)[:120]}")
            time.sleep(15)


if __name__ == "__main__":
    main()

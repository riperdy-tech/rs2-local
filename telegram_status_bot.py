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
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OFFSET = CACHE / "telegram_bot_offset.json"

sys.path.insert(0, str(HERE))
import depth_ondemand   # noqa: E402  ("/analyze TICKER" — stdlib-only import chain)


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


# ── web request bridge (Supabase ondemand_queue) ──────────────────────────────
# The site's /ondemand "Analyze" button inserts rows into the Supabase table
# ondemand_queue (via the password-gated /api/ondemand route). This PC has no
# inbound connectivity, so this bot — the machine's one always-on poller — drains
# that table once per loop and hands each ticker to depth_ondemand.request(),
# exactly like a Telegram /analyze. Missing supabase keys => the bridge is off
# and the bot serves Telegram only.

def _sb_cfg():
    sec = _load(HERE / ".secrets.json") or {}
    return sec.get("supabase_url"), sec.get("supabase_service_key")


def _sb(method, path, body=None, prefer=None, timeout=15):
    """One PostgREST call, stdlib only. Returns parsed JSON or None on any failure.
    urllib needs the explicit method= kwarg — it will not infer PATCH."""
    url, key = _sb_cfg()
    if not (url and key):
        return None
    try:
        headers = {"apikey": key, "Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(
            f"{url.rstrip('/')}/rest/v1/{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else []
    except Exception:
        return None


def _sanitize(msg):
    """depth_ondemand replies can carry local filesystem paths (the precheck names the
    financials file). The message column is publicly readable via the site's GET route,
    so strip anything path-shaped before it leaves this machine. Local paths here
    contain SPACES ("Stock Screener"), so a \\S-bounded match leaks the tail — consume
    to the closing paren / end of line instead; over-redaction is the safe direction."""
    return re.sub(r"[A-Za-z]:[\\/][^)\n]*", "<local path>", msg)[:400]


def _drain_web_queue(tok, chat):
    url, key = _sb_cfg()
    if not (url and key):
        return
    rows = _sb("GET", "ondemand_queue?status=eq.pending&order=requested_at.asc"
                      "&limit=5&select=id,ticker") or []
    for row in rows:
        # CLAIM BEFORE RUN (depth_ondemand's own contract): the conditional PATCH is
        # the claim. If it comes back empty the row was taken or the PATCH failed —
        # skip; re-running request() after a successful run would burn ~2h of GPU on
        # a duplicate. A crash after the claim loses the request (visible on the
        # page as a stuck 'claimed' row; re-submission is allowed) — no reaper.
        claimed = _sb("PATCH", f"ondemand_queue?id=eq.{row['id']}&status=eq.pending",
                      {"status": "claimed"}, prefer="return=representation")
        if not claimed:
            continue
        ok = True
        try:
            reply = depth_ondemand.request(str(row["ticker"]).upper(), source="web")
            ok = not reply.startswith("REFUSED")
        except Exception as e:
            reply, ok = f"analyze failed: {str(e)[:120]}", False
        _sb("PATCH", f"ondemand_queue?id=eq.{row['id']}",
            {"status": "handled" if ok else "failed",
             "message": _sanitize(reply) + " · verdict also lands on /ondemand after the next publish.",
             "handled_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=minimal")
        _api(tok, "sendMessage", {"chat_id": chat, "text": f"[web] {reply}"}, timeout=20)


def compose_status():
    """DEPTH-pipeline status (repointed 2026-08-30). The original read the RETIRED
    orchestrator's files (orchestrate_progress.json / orchestrate.lock, frozen 2026-08-19),
    so it answered "no sweep running" while a depth sweep was hours into the GPU. Sources now
    match status.py: depth lock via depth_ondemand._lock_alive, cache/depth_progress.json,
    DEPTH_PAUSED, the on-demand queue, cache/jobs/* side jobs, and the depth ledger."""
    lines = [f"📊 RS2 depth status @ {datetime.now().strftime('%H:%M:%S')}"]
    pid = depth_ondemand._lock_alive()
    prog = _load(CACHE / "depth_progress.json") or {}
    if (CACHE / "DEPTH_PAUSED").exists():
        lines.append("⏸ PAUSED (red button set — resume: python status.py resume)")
    if pid:
        cur = prog.get("current") or "?"
        idx, total = prog.get("idx") or 0, prog.get("total") or 0
        q = [e.get("t") for e in (prog.get("queue") or [])][idx:]
        lines.append(f"▶ sweep running (pid {pid}): {cur} [{idx}/{total}]")
        if q:
            lines.append(f"   pending: {', '.join(q[:8])}" + ("..." if len(q) > 8 else ""))
    else:
        lines.append(f"💤 no sweep running (last progress update {prog.get('updated', '—')[:19]})")
    reqs = depth_ondemand.pending()
    if reqs:
        lines.append("🎯 on-demand queued: " + ", ".join(r.get("ticker", "?") for r in reqs))
    web = _sb("GET", "ondemand_queue?status=eq.pending&select=id")
    if web:
        lines.append(f"🌐 web requests pending: {len(web)}")
    jobs = []
    for jf in (CACHE / "jobs").glob("*.json") if (CACHE / "jobs").exists() else []:
        j = _load(jf) or {}
        jobs.append(f"{j.get('name', jf.stem)}: {str(j.get('progress', ''))[:60]}")
    if jobs:
        lines.append("🛠 side jobs: " + " | ".join(jobs))
    led = CACHE / "depth_ledger.jsonl"
    if led.exists():
        tail = led.read_text(encoding="utf-8").splitlines()[-3:]
        for line in tail:
            try:
                v = json.loads(line)
                lines.append(f"   {v['ticker']} {v.get('direction')} "
                             f"band {v.get('iv_band_low')}-{v.get('iv_band_high')} "
                             f"vs {v.get('price')} ({v.get('date', '')[:16]})")
            except Exception:
                continue
    return "\n".join(lines)


def main():
    tok, chat = _cfg()
    if not (tok and chat):
        print("no telegram_bot_token/telegram_chat_id in .secrets.json — exiting")
        return
    me = _api(tok, "getMe", timeout=20)
    print(f"listening as @{me.get('result', {}).get('username')} for chat {chat}"
          + (" | web queue: on" if _sb_cfg()[0] else " | web queue: off (no supabase keys)"))
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
                # /analyze TICKER — on-demand depth analysis (operator chat only; the chat-id
                # gate above already dropped everyone else). request() precheck-refuses
                # off-universe names and returns one human line either way.
                m = re.match(r"^/?analyze[\s_]+([a-z0-9.\-]{1,10})\s*$", text)
                if m:
                    try:
                        reply = depth_ondemand.request(m.group(1).upper(), source="telegram")
                    except Exception as e:
                        reply = f"analyze failed: {str(e)[:120]}"
                    _api(tok, "sendMessage", {"chat_id": chat, "text": reply}, timeout=20)
                    continue
                if "status" in text:
                    _api(tok, "sendMessage", {"chat_id": chat, "text": compose_status()},
                         timeout=20)
            # Web bridge poll — its OWN except: a Supabase blip must not be
            # mislabelled a Telegram failure or trigger the 15s backoff below.
            try:
                _drain_web_queue(tok, chat)
            except Exception as e:
                print(f"web-queue poll error (ignored): {str(e)[:120]}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"poll error (retrying in 15s): {str(e)[:120]}")
            time.sleep(15)


if __name__ == "__main__":
    main()

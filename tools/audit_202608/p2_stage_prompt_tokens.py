#!/usr/bin/env python3
"""P2 — how many TOKENS is a real production stage prompt, and does it fit stage_ctx?

Estimating from characters is not good enough: measured chars-per-token on this corpus ranges
3.3-1.6 depending on how numeric the text is, and the conclusion flips across that range. So ask
the server. Ollama logs `task.n_tokens` for every request; we send one real, production-shaped
LATE-stage prompt (fed data + 4 prior stages at the carry cap + the stage task, against the
production model whose 35,654-char SYSTEM is baked in) and read the number back out of the log.

Sends ONE token of generation (num_predict=1) — this measures the prompt, not the answer, so it
costs seconds and cannot disturb anything.

Reports, per ticker: prompt tokens vs stage_ctx (24576), headroom, and whether the input alone
overflows. Overflow matters beyond truncation: the server runs with n_keep=4, so when the window
is exceeded the eviction starts at the beginning of the prompt — which is where the RS2 framework
lives.

  python tools/audit_202608/p2_stage_prompt_tokens.py [TICKER ...]
"""
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import common  # noqa: E402
common.enable_json_cache()
import rs2_data  # noqa: E402
import run_rs2  # noqa: E402
import valuation_backbone as vb  # noqa: E402

LOG = Path(os.environ["LOCALAPPDATA"]) / "Ollama" / "server.log"
OUT = HERE / "audit" / "C_experiments" / "p2_stage_prompt_tokens.json"


def log_len():
    try:
        return LOG.stat().st_size
    except Exception:
        return 0


def tokens_since(offset):
    """newest task.n_tokens appearing in the log after `offset`."""
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            tail = f.read()
    except Exception:
        return None
    hits = re.findall(r"task\.n_tokens\s*=\s*(\d+)", tail)
    return int(hits[-1]) if hits else None


def main():
    tickers = [a.upper() for a in sys.argv[1:]] or ["GOOG", "NVDA", "AAPL", "CAH"]
    stage_ctx = int(rs2_data.CONFIG.get("stage_ctx", 24576))
    cap = int(rs2_data.CONFIG.get("stage_carry_char_cap", 4500))
    # a LATE stage (S6) sees fed data + every prior stage truncated to the carry cap
    late_task = run_rs2.STAGES[-1][2]
    rows = []
    for t in tickers:
        try:
            bb = vb.backbone(t)
            fed = rs2_data.build_data_context(t, bb)
        except Exception as e:
            print(f"{t}: skip ({str(e)[:60]})")
            continue
        accum = "".join(f"\n\n----- prior stage -----\n{'x' * cap}" for _ in range(4))
        content = run_rs2.stage_prompt(fed, accum, late_task)
        off = log_len()
        body = json.dumps({"model": rs2_data.CONFIG["model"], "stream": False, "think": False,
                           "messages": [{"role": "user", "content": content}],
                           "options": {"num_ctx": stage_ctx, "num_predict": 1}}).encode()
        req = urllib.request.Request(rs2_data.CONFIG["ollama_endpoint"], data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                r.read()
        except Exception as e:
            print(f"{t}: request failed ({str(e)[:80]})")
        time.sleep(1)
        n = tokens_since(off)
        rows.append({"ticker": t, "prompt_chars": len(content), "prompt_tokens": n,
                     "stage_ctx": stage_ctx,
                     "headroom_tokens": (stage_ctx - n) if n else None,
                     "overflows": bool(n and n >= stage_ctx),
                     "chars_per_token": round(len(content) / n, 2) if n else None})
        print(f"{t}: {len(content):,} chars -> {n if n else '?'} tokens | "
              f"headroom {stage_ctx - n if n else '?'} of {stage_ctx}"
              + ("  *** INPUT ALONE OVERFLOWS ***" if n and n >= stage_ctx else ""), flush=True)

    meas = [r for r in rows if r["prompt_tokens"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "probe": "P2 production stage prompt token budget",
        "stage_ctx": stage_ctx, "carry_cap_chars": cap,
        "n_overflowing": sum(1 for r in meas if r["overflows"]),
        "n_measured": len(meas),
        "median_headroom": sorted(r["headroom_tokens"] for r in meas)[len(meas)//2] if meas else None,
        "rows": rows}, indent=2), encoding="utf-8")
    print(f"\n[p2] {sum(1 for r in meas if r['overflows'])}/{len(meas)} overflow before generating "
          f"a single token -> {OUT}")


if __name__ == "__main__":
    main()

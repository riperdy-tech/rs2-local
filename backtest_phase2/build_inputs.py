"""Step 5 (first half): the point-in-time inputs of every valuation date.  OFFLINE: sockets blocked; every file the process
opens for reading is logged (registration C1, "log every file read").

  python -m backtest_phase2.build_inputs --bt-root <SP\\backtest> --tree <rs2 tree> [--years 2016 ...]

Writes <bt-root>/out/inputs/inputs_<Y>.pkl, aggregate_<Y>.json, summary_<Y>.json and files_read_inputs.txt.
No return is read: the only price after T that is touched is a presence test at T+36 months.
"""
import argparse
import os
import socket
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True


class _Blocked(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("Socket access blocked in this step")


def _no_net(*a, **k):
    raise RuntimeError("Network access blocked in this step")


socket.socket = _Blocked
socket.getaddrinfo = _no_net
socket.create_connection = _no_net

_TRACE = set()
_SKIP = (sys.prefix.lower(), sys.base_prefix.lower())


def _hook(event, args):
    if event == "open":
        p, mode = args[0], (args[1] if len(args) > 1 else None)
        if isinstance(p, (str, bytes, os.PathLike)) and (mode is None or "r" in str(mode)) and "w" not in str(mode):
            s = os.fsdecode(p)
            if not s.lower().startswith(_SKIP) and "__pycache__" not in s:
                _TRACE.add(s)


sys.addaudithook(_hook)

from backtest_phase2 import pit_data  # noqa: E402
from backtest_phase2.common import DATES  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt-root", required=True, type=Path)
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--years", nargs="*", default=list(DATES))
    ap.add_argument("--no-share-guard", action="store_true", help="the literal cap(T): no check of the cover count against the filed diluted count")
    ap.add_argument("--out-name", default="inputs", help="output folder under <bt-root>/out")
    a = ap.parse_args(argv)
    ctx = pit_data.Context(a.bt_root, a.tree, share_guard=not a.no_share_guard)
    out = a.bt_root / "out" / a.out_name
    for y in a.years:
        t0 = time.time()
        res = pit_data.build_date(ctx, y)
        pit_data.save_date(out, res)
        print(f"{y}: pop {len(res['pop'])}, aggregate constituents {res['agg_stats']['constituents']}, "
              f"U {res['universe'].get('U', 0)}, {time.time() - t0:.0f}s", flush=True)
    (out / "files_read_inputs.txt").write_text("\n".join(sorted(_TRACE)), encoding="utf-8")
    print("files read:", len(_TRACE))


if __name__ == "__main__":
    main()

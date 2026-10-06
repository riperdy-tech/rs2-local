"""Backtest registration section 4.1: run the stock-screener extractor, unchanged, on a point-in-time cut of the zip.

The extractor file is copied byte for byte (its sha256 is checked against the registered value) and imported as a
module; this wrapper only sets the extractor's own path constants (the registration allows an input-path and an
output-path argument and nothing else), blocks every socket, and calls the extractor's own main().  No extractor
line is edited.

  python run_extractor.py --extractor build_fundamentals_history.py --cut-zip cut_2016-06-30.zip
         --stocks stocks.json --cik-map cik_map.json --out-dir <dir>
"""
import argparse
import hashlib
import importlib.util
import socket
import sys
from pathlib import Path

REGISTERED_SHA256_PREFIX = "aa9493a4"


class _Blocked(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("Socket access blocked in this step")


def _no_net(*a, **k):
    raise RuntimeError("Network access blocked in this step")


socket.socket = _Blocked
socket.getaddrinfo = _no_net
socket.create_connection = _no_net


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", required=True, type=Path)
    ap.add_argument("--cut-zip", required=True, type=Path)
    ap.add_argument("--stocks", required=True, type=Path)
    ap.add_argument("--cik-map", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    a = ap.parse_args()
    digest = hashlib.sha256(a.extractor.read_bytes()).hexdigest()
    if not digest.startswith(REGISTERED_SHA256_PREFIX):
        raise SystemExit(f"extractor sha256 {digest} does not start with the registered {REGISTERED_SHA256_PREFIX}")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("bfh_registered", a.extractor)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bfh_registered"] = mod
    spec.loader.exec_module(mod)
    mod.ZIP_PATH = a.cut_zip
    mod.STOCKS_JSON = a.stocks
    mod.CIK_MAP_JSON = a.cik_map
    mod.HISTORY_JSON = a.out_dir / "fundamentals_history.json"
    mod.BATTERY_JSON = a.out_dir / "fundamentals_battery.json"
    mod.TTM_JSON = a.out_dir / "fundamentals_ttm.json"
    mod.QTR_JSON = a.out_dir / "fundamentals_quarterly.json"
    # The value-trap battery is not an input of the backtest (only the history rows are).  On a cut archive the
    # extractor's compute_battery divides by a zero total_assets for some company-years and would abort the whole run,
    # so the battery alone is guarded: an exception there yields no battery for that company and is counted.  The
    # history rows are produced before the battery call by unchanged extractor code.
    orig_battery, failures = mod.compute_battery, []

    def guarded_battery(history):
        try:
            return orig_battery(history)
        except ZeroDivisionError as exc:
            failures.append(str(exc))
            return None

    mod.compute_battery = guarded_battery
    sys.argv = [str(a.extractor)]
    mod.main()
    print("battery computations that raised ZeroDivisionError (battery set to None, history unaffected):", len(failures))
    print("extractor sha256", digest)


if __name__ == "__main__":
    main()

"""Shared helpers for the 2026-08 valuation-methodology audit experiments.

Read-only against the pipeline: memoizes rs2_data.load_json in-process (backbone() otherwise
re-parses the 28MB fundamentals_history.json on every call), never writes any pipeline file.
Results go to audit/C_experiments/.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import rs2_data  # noqa: E402

RESULTS = ROOT / "audit" / "C_experiments"
SD = Path(rs2_data.CONFIG["screener_data_dir"])

_JSON_CACHE = {}
_orig_load_json = rs2_data.load_json


def _cached_load_json(path):
    key = str(path)
    if key not in _JSON_CACHE:
        _JSON_CACHE[key] = _orig_load_json(path)
    return _JSON_CACHE[key]


def enable_json_cache():
    rs2_data.load_json = _cached_load_json


def book_tickers():
    """Active tickers from cache/analysis_state.json."""
    st = _orig_load_json(ROOT / "cache" / "analysis_state.json") or {}
    return sorted(t for t, v in st.items() if isinstance(v, dict) and v.get("status") == "active")


def overlay():
    """ticker -> latest audit-clean verdict row from the published overlay."""
    ov = _orig_load_json(SD / "llm_overlay.json") or {}
    return ov.get("tickers") or {}


# mirror of run_rs2._action_family (order-sensitive; HOLD before BULL is load-bearing)
def action_family(action):
    a = (action or "").upper()
    if any(k in a for k in ("AVOID", "REDUCE", "SELL", "TRIM", "EXIT", "UNDERWEIGHT")):
        return "BEAR"
    if any(k in a for k in ("HOLD", "WAIT", "WATCHLIST", "MONITOR", "DO NOT CHASE")):
        return "HOLD"
    if any(k in a for k in ("BUY", "ACCUMULAT", "SCALE", "ADD", "OVERWEIGHT", "STARTER",
                            "INITIAT", "ENTER")):
        return "BULL"
    return "?"


def spearman(xs, ys):
    """Spearman rank correlation (average-rank ties), None if n < 8."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 8:
        return None, n

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx = ranks([p[0] for p in pairs])
    ry = ranks([p[1] for p in pairs])
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None, n
    return round(num / (dx * dy), 3), n


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * p / 100))]


def save(name, obj):
    RESULTS.mkdir(parents=True, exist_ok=True)
    obj = {"generated_at": datetime.now(timezone.utc).isoformat(), **obj}
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    print(f"saved {path}")
    return path

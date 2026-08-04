#!/usr/bin/env python3
"""Quota + secrets helper — keep us under free-API limits (Tavily 1k/mo, FMP ~250/day).
State in cache/quota.json with calendar-period resets. Stdlib only."""
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# tolerant: a missing or BOM'd .secrets.json must not crash `import quota` — that silently killed
# deep_research.py and openbb_data.py outright. key() returning "" degrades those paths gracefully
# (SearXNG-only research, no FMP) instead of no research at all.
try:
    SECRETS = json.loads((HERE / ".secrets.json").read_text(encoding="utf-8-sig"))
except Exception:
    SECRETS = {}
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
QF = CACHE / "quota.json"

# Conservative caps (leave headroom under the real free limits)
TAVILY_MONTHLY_CAP = 900     # real 1000/mo
FMP_DAILY_CAP = 200          # real ~250/day


def _load():
    try:
        return json.loads(QF.read_text(encoding="utf-8-sig"))   # utf-8-sig: BOM must not reset the ledger
    except Exception:
        return {}


def _save(d):
    # atomic: a torn quota.json would silently reset the API-usage ledger to zero on next _load
    tmp = QF.with_name(QF.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(QF)


def _periods():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")


def remaining(api):
    """How many calls left this period for 'tavily' or 'fmp'."""
    mon, day = _periods()
    d = _load()
    if api == "tavily":
        used = d.get("tavily", {}).get(mon, 0)
        return max(0, TAVILY_MONTHLY_CAP - used)
    if api == "fmp":
        used = d.get("fmp", {}).get(day, 0)
        return max(0, FMP_DAILY_CAP - used)
    return 0


def bump(api, n=1):
    """Record n calls against the current period."""
    mon, day = _periods()
    d = _load()
    if api == "tavily":
        d.setdefault("tavily", {})[mon] = d.get("tavily", {}).get(mon, 0) + n
    elif api == "fmp":
        d.setdefault("fmp", {})[day] = d.get("fmp", {}).get(day, 0) + n
    _save(d)


def key(name):
    return SECRETS.get(name, "") or ""


if __name__ == "__main__":
    print("Tavily remaining (mo):", remaining("tavily"), "| FMP remaining (day):", remaining("fmp"))
    print("Tavily key set:", bool(key("TAVILY_API_KEY")), "| FMP key set:", bool(key("FMP_API_KEY")))

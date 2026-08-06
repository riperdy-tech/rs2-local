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

# Conservative caps (leave headroom under the real free limits). Held ~5% under the true limit
# so a miscount or a retry storm cannot overrun and start returning 4xx mid-brief.
MONTHLY_CAPS = {
    "tavily": 900,     # real 1000/mo, genuinely recurring
    # Brave KILLED its free 2000/mo tier in Feb 2026. New accounts get $5/month of METERED
    # credits (~1000 queries at $0.003-0.005 each), card required and NO SPENDING CAP -- so an
    # overrun BILLS rather than erroring. This ledger is the only thing standing between a retry
    # storm and a surprise invoice; keep it well under and never raise it casually.
    "brave": 900,
}
DAILY_CAPS = {
    "fmp": 200,        # real ~250/day
}
# ONE-TIME grants that NEVER reset. Serper sells prepaid credits, not subscriptions: the 2500
# free credits are a signup grant, full stop. Metering it monthly would refill a bucket that does
# not refill -- the ledger would report ~2400 remaining every month while the account sat empty,
# and every research fallback to serper would fail for a reason nothing on this box could explain.
# (Purchased Serper credits also expire 6 months after purchase, which this does NOT model; if
# you ever buy a pack, note the expiry somewhere a human will read.)
TOTAL_CAPS = {
    "serper": 2400,    # real 2500, one-time
}
TAVILY_MONTHLY_CAP = MONTHLY_CAPS["tavily"]   # kept: referenced elsewhere
FMP_DAILY_CAP = DAILY_CAPS["fmp"]


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
    """How many calls left this period for any capped API (monthly or daily)."""
    mon, day = _periods()
    d = _load()
    if api in MONTHLY_CAPS:
        return max(0, MONTHLY_CAPS[api] - d.get(api, {}).get(mon, 0))
    if api in DAILY_CAPS:
        return max(0, DAILY_CAPS[api] - d.get(api, {}).get(day, 0))
    if api in TOTAL_CAPS:
        return max(0, TOTAL_CAPS[api] - d.get(api, {}).get("total", 0))
    return 0


def _period_for(api):
    mon, day = _periods()
    if api in MONTHLY_CAPS:
        return mon
    if api in DAILY_CAPS:
        return day
    if api in TOTAL_CAPS:
        return "total"      # never rolls over — a one-time grant must not reset
    return None


def bump(api, n=1):
    """Record n calls against the current period (or against the lifetime total)."""
    d = _load()
    period = _period_for(api)
    if period is None:
        return
    d.setdefault(api, {})[period] = d.get(api, {}).get(period, 0) + n
    _save(d)


def key(name):
    return SECRETS.get(name, "") or ""


if __name__ == "__main__":
    print("Tavily remaining (mo):", remaining("tavily"), "| FMP remaining (day):", remaining("fmp"))
    print("Tavily key set:", bool(key("TAVILY_API_KEY")), "| FMP key set:", bool(key("FMP_API_KEY")))

"""DeepSeek billing window — the ONE definition every caller shares.

Published at api-docs.deepseek.com/quick_start/pricing (read 2026-08-24): peak is
01:00-04:00 and 06:00-10:00 UTC, Monday-Friday; everything else is off-peak at half
the peak rate. deep_api_run.py meters cost with it; cloud_backstop.py and the
depth-cloud-backstop workflow refuse to START a billable ticker unless the whole
ticker fits inside off-peak (operator decision 2026-09-07: never pay peak rates).

Stdlib only, no side effects at import: the workflow preflight imports this from a
bare checkout before anything else is installed.
"""
from __future__ import annotations

from datetime import datetime, timedelta

PEAK_HOURS_UTC = ((1, 4), (6, 10))   # [start, end) hour pairs, weekdays only


def off_peak(dt: datetime) -> bool:
    """True when `dt` (UTC) is outside every peak window."""
    return not (dt.weekday() < 5 and any(a <= dt.hour < b for a, b in PEAK_HOURS_UTC))


def run_window_ok(now: datetime, horizon_s: float) -> bool:
    """True when a job starting at `now` and lasting up to `horizon_s` seconds stays
    off-peak throughout. Peak windows begin on the hour, so checking `now`, the end,
    and every top-of-hour in between is exhaustive."""
    end = now + timedelta(seconds=horizon_s)
    if not (off_peak(now) and off_peak(end)):
        return False
    t = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t < end:
        if not off_peak(t):
            return False
        t += timedelta(hours=1)
    return True

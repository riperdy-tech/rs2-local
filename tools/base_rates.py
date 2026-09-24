"""base_rates.py — Phase 4 D11 / amendment E2: measured revenue-growth base rates by starting
revenue size, from our OWN `fundamentals_history.json` corpus (about 6,900 current listings).

Source and caveats are exactly the ones the orchestrator measured and published in
`PHASE_4_AMENDMENTS.md` E2:
  - SURVIVORSHIP: the sample holds only companies that still exist — delisted names are absent —
    so every rate here is biased upward.
  - The window is one decade (fiscal years roughly 2014-2025), which includes the AI build-out.

`capability_test.build_pack`'s GROWTH BASE RATES block is the only caller. It also prints the
conditional "given the growth just delivered" table, which is `tools/growth_persistence.py`
logic (imported there directly, not duplicated here).
"""
import hashlib
from pathlib import Path

import rs2_data

SIZE_BUCKETS = (
    (0.0, 1e9, "< $1B"),
    (1e9, 10e9, "$1-10B"),
    (10e9, 50e9, "$10-50B"),
    (50e9, float("inf"), "> $50B"),
)
HORIZONS = (5, 10)

# {file_sha256: {size_label: {horizon: {...}}}} — measured once per data-file content WITHIN
# THE RUN (this process), per the operator's caching instruction. Keyed on the file's own bytes
# (not mtime) so a rebuilt file with unchanged content is not needlessly re-measured, and a
# changed file under an unchanged mtime (a same-second rewrite) is never served stale.
_CACHE = {}


def _size_bucket(revenue):
    if not isinstance(revenue, (int, float)) or revenue <= 0:
        return None
    for lo, hi, label in SIZE_BUCKETS:
        if lo <= revenue < hi:
            return label
    return None


def _history_path(sd=None):
    """`sd` lets a caller that resolves its own (test-patchable) screener-data directory — as
    `capability_test.py`'s module-level `SD` does — pass it straight through, instead of this
    module re-resolving `rs2_data.CONFIG["screener_data_dir"]` on its own. Re-resolving would
    read the REAL screener directory even when the caller's own directory is monkeypatched for a
    test, exactly the machine-dependent-test defect `conftest.py`'s `screener_data_stub` fixture
    exists to prevent."""
    base = Path(sd) if sd is not None else Path(rs2_data.CONFIG["screener_data_dir"])
    return base / "fundamentals_history.json"


def _file_sha(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _quantile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, int(len(sorted_vals) * p)))
    return sorted_vals[idx]


def _compute_table(path, max_fiscal_year=None):
    """{size_label: {horizon: {n, share_ge_10, share_ge_20, share_ge_30, p50, p90}}}, measured
    fresh from `fundamentals_history.json` at `path`: for every (ticker, start-year) with revenue
    at the start year and `horizon` years later, the realized CAGR, bucketed by the start-year's
    size.

    `max_fiscal_year`: point-in-time restriction (Phase 4 E4.3) — fiscal years after this one are
    excluded from EVERY ticker's series before any (start-year, horizon) pair is formed, so a
    trial pack's base-rate corpus cannot see a year that would not yet have been filed as of the
    trial's `asof` date. None (the default) computes the full corpus, unchanged behaviour.
    """
    hist = (rs2_data.load_json(path) or {}).get("tickers", {})
    buckets = {}   # (size_label, horizon) -> [cagr, ...]
    for t, yd in (hist or {}).items():
        if not isinstance(yd, dict):
            continue
        ys = sorted(int(y) for y in yd if str(y).isdigit()
                    and (max_fiscal_year is None or int(y) <= max_fiscal_year))
        revs = {}
        for y in ys:
            r = (yd.get(str(y)) or {}).get("revenue")
            if isinstance(r, (int, float)) and r > 0:
                revs[y] = r
        for y in ys:
            if y not in revs:
                continue
            size_label = _size_bucket(revs[y])
            if size_label is None:
                continue
            for h in HORIZONS:
                if (y + h) not in revs:
                    continue
                cagr = (revs[y + h] / revs[y]) ** (1.0 / h) - 1
                if not (-0.99 < cagr < 10):     # exclude arithmetic-impossible / corrupt rows
                    continue
                buckets.setdefault((size_label, h), []).append(cagr)
    out = {}
    for (size_label, h), vals in buckets.items():
        vs = sorted(vals)
        n = len(vs)
        out.setdefault(size_label, {})[h] = {
            "n": n,
            "share_ge_10": round(sum(1 for v in vs if v >= 0.10) / n * 100, 1) if n else None,
            "share_ge_20": round(sum(1 for v in vs if v >= 0.20) / n * 100, 1) if n else None,
            "share_ge_30": round(sum(1 for v in vs if v >= 0.30) / n * 100, 1) if n else None,
            "p50": round(_quantile(vs, 0.50) * 100, 1) if n else None,
            "p90": round(_quantile(vs, 0.90) * 100, 1) if n else None,
        }
    return out


def base_rate_table(revenue, sd=None, max_fiscal_year=None):
    """(size_label, {5: {...}, 10: {...}}) for the size bucket containing `revenue`.

    `sd`: the screener-data directory to read from, or None to resolve it here (see
    `_history_path`'s docstring — a caller with its own resolved/patchable directory should
    always pass it).

    `max_fiscal_year`: point-in-time restriction (Phase 4 E4.3), threaded straight to
    `_compute_table`. None computes the full corpus, unchanged behaviour.

    (None, {}) when `revenue` is absent/non-positive (no size to bucket by) or the corpus data
    file cannot be read. Cached per (data-file sha256, max_fiscal_year) within this process — a
    batch of pack builds at the same as-of date measures the corpus once, not once per ticker.
    """
    path = _history_path(sd)
    sha = _file_sha(path)
    if sha is None:
        return None, {}
    cache_key = (sha, max_fiscal_year)
    if cache_key not in _CACHE:
        _CACHE[cache_key] = _compute_table(path, max_fiscal_year=max_fiscal_year)
    size_label = _size_bucket(revenue)
    if size_label is None:
        return None, {}
    return size_label, _CACHE[cache_key].get(size_label, {})

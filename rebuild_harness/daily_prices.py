"""D5 daily raw closes as a PriceSource for the HOLDOUT (Addendum L4): a memory-safe lazy loader over `data/prices_daily/<TICKER>.csv.gz`.

THE FILES.  One gzip CSV per ticker (Yahoo, `auto_adjust=False`): `Date, Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits`.  `Close` and `Open` are split-adjusted to
today, NOT dividend-adjusted; `Adj Close` is split- and dividend-adjusted; `Stock Splits` carries the ratio on the exact ex-date (4.0 = 4-for-1).  `manifest.csv` lists the tickers
(`ticker, rows, first_date, last_date, status`; `status` ok or empty).

THE TRADED UNADJUSTED CLOSE of a session = `Close` x the product of the split ratios whose ex-date is strictly AFTER that session AND by which Yahoo adjusted the history (a split on the
session's own date is already in that day's Close, because Yahoo's Close of the ex-date is post-split).  Verified on a known case: AAPL 2020-08-28, Close 124.8075 x the 4-for-1 of 2020-08-31 =
499.23, the traded close.

YAHOO DOES NOT ALWAYS ADJUST.  Measured over all 5,038 split events of the folder (`scratch/rev23/gate1_dev/round5/d5_split_basis_probe.txt`): 4,609 are continuous across the ex-date (Close adjusted),
355 have a ratio within 5% of 1 (stock dividends; undecidable and immaterial), and 44 are RAW by the simple rule: the Close of the bars before the ex-date was never adjusted (it jumps by 1/ratio across the ex-date;
15 of them are reverse splits of September 2026, downloaded before Yahoo had propagated them, e.g. a 1-for-50 whose pre-split closes are the traded prices).  Multiplying such a Close by the
ratio would divide a traded price by 50.  So each event is classified by the continuity of the Close across its ex-date: RAW when the price jump across the ex-date is DECISIVELY closer to 1/ratio than to 1 (the log error of
the raw reading under half that of the adjusted reading, `RAW_DECISIVE`) AND the ratio is at least 1.5-fold either way (`RAW_MIN_LOG_RATIO`); anything else is taken as adjusted (the default, and the
rule for ratios near 1 and for a jump that either reading could explain: of the 44 candidates by the simple closer-to-1/ratio rule, 40 are decisive and 4 are marginal and stay adjusted;
`scratch/rev23/gate1_dev/round5/d5_split_basis_probe2.txt`).  A raw event is not applied to the traded close; the event stays in
`splits()` (a real share-count change), and `raw_split_events(key)` lists them for the audit.

SEMANTICS (identical to `pit_data.DailyPriceSource`, so the engine sees the same contract as in its tests):
  * `close_unadjusted` / `adj_close` of `asof`: the bar of `asof` itself (VERIFIED), else the latest EARLIER bar within `max_gap_days` (UNVERIFIED, flagged `stale_bar`), else None;
    a bar whose value is not a positive number is None (the previous bar is never substituted);
  * `splits`: exact ex-dates, so the share basis is determined to the day;
  * `entry_point` (REGISTRATION v2, section 2): the position decided at 16:00 ET on `asof` is entered at the NEXT session's OPEN, total-return adjusted: `Open x (Adj Close / Close)` of
    that bar (the adjustment factor of the bar converts the open to the adjusted basis); the next bar must lie within `max_gap_days`.  `entry_field="adj_close"` gives the older
    next-session adjusted-close convention of `DailyPriceSource` (kept for comparison only: the registered rule is the open);
  * `last_date`: the last bar of the file.

MEMORY.  A ticker's file is parsed on demand into five numpy arrays (about 20 bytes a bar, about 100 KB a ticker) and kept in an LRU of `max_cached` tickers (default 256, about 25 MB):
the whole folder (9,738 tickers, 400 MB gzipped) is never in memory, and a worker process holds only the LRU.  `drop_cache()` empties it.  Nothing is written, nothing is downloaded.

REFUSALS (`DataNotPresent`): a missing folder; a file whose dates are not strictly increasing; a header without the required columns.  A ticker that is not in the folder is simply not a key
(`has_key` False), exactly like a ticker the monthly file does not hold.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import io
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from valuation.common import DataNotPresent
from valuation.pit_data import PricePoint, PriceSource, QUALITY_UNVERIFIED, QUALITY_VERIFIED, to_date

COLUMNS = ("Date", "Open", "Close", "Adj Close", "Stock Splits")
RAW_MIN_LOG_RATIO = float(np.log(1.5))        # a split event is judged adjusted-or-raw only when the ratio is at least 1.5-fold either way
RAW_DECISIVE = 0.5                            # ... and RAW only when the "raw" reading explains the jump with less than half the error of the "adjusted" reading
SUFFIX = ".csv.gz"
EPOCH = np.datetime64("1970-01-01", "D")


class _Series:
    """One ticker, as arrays sorted by date."""
    __slots__ = ("days", "close_unadj", "adj", "open_adj", "splits", "last_iso", "raw_events")

    def __init__(self, days, close_unadj, adj, open_adj, splits, last_iso, raw_events=()):
        self.days, self.close_unadj, self.adj, self.open_adj, self.splits, self.last_iso = days, close_unadj, adj, open_adj, splits, last_iso
        self.raw_events = list(raw_events)


def parse_file(path) -> _Series:
    """Parse one ticker file into a `_Series` (see the module docstring for the arithmetic)."""
    path = Path(path)
    with gzip.open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    rd = csv.reader(io.StringIO(text))
    try:
        hdr = next(rd)
    except StopIteration:
        raise DataNotPresent(f"{path}: empty file")
    idx = {c: i for i, c in enumerate(hdr)}
    miss = [c for c in COLUMNS if c not in idx]
    if miss:
        raise DataNotPresent(f"{path}: no column(s) {miss} (found {hdr})")
    iD, iO, iC, iA, iS = (idx[c] for c in COLUMNS)

    def num(x):
        try:
            v = float(x)
        except (TypeError, ValueError):
            return float("nan")
        return v

    dates, op, cl, ad, sp = [], [], [], [], []
    for r in rd:
        if not r or not r[iD]:
            continue
        dates.append(r[iD][:10])
        op.append(num(r[iO]))
        cl.append(num(r[iC]))
        ad.append(num(r[iA]))
        sp.append(num(r[iS]) if r[iS] not in ("", None) else 0.0)
    if not dates:
        raise DataNotPresent(f"{path}: no bars")
    days = np.array(dates, dtype="datetime64[D]").astype(np.int64)
    if len(days) > 1 and not np.all(np.diff(days) > 0):
        raise DataNotPresent(f"{path}: the dates are not strictly increasing (a duplicate or out-of-order bar)")
    op, cl, ad, sp = (np.array(a, dtype=np.float64) for a in (op, cl, ad, sp))
    ratio = np.where((sp != 0.0) & np.isfinite(sp), sp, 1.0)
    # an event is applied to the traded close only where Yahoo adjusted the Close's history for it (see the module docstring)
    applied = ratio.copy()
    raw_events = []
    valid = np.nonzero(np.isfinite(cl) & (cl > 0))[0]
    for i in np.nonzero(ratio != 1.0)[0]:
        if abs(np.log(ratio[i])) < RAW_MIN_LOG_RATIO:
            continue
        k = int(np.searchsorted(valid, i))                      # valid[k - 1]: the last priced bar before the ex-date bar; valid[k]: the first priced bar on or after it
        if k == 0 or k >= len(valid):
            continue
        jump = cl[valid[k]] / cl[valid[k - 1]]                  # (the ex-date bar itself may have no price: a halt or a missing row)
        if abs(np.log(jump * ratio[i])) < RAW_DECISIVE * abs(np.log(jump)):     # the price moved like 1/ratio across the ex-date: the earlier closes are the traded prices
            applied[i] = 1.0
            raw_events.append((dates[i], float(ratio[i])))
    # suffix[i] = product of the applied ratios of the bars STRICTLY AFTER bar i
    after = np.ones_like(applied)
    if len(applied) > 1:
        after[:-1] = np.cumprod(applied[:0:-1])[::-1]
    close_unadj = cl * after
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = np.where((cl > 0) & np.isfinite(cl) & (ad > 0) & np.isfinite(ad), ad / cl, np.nan)
    open_adj = op * factor
    ev = [(dates[i], float(ratio[i])) for i in np.nonzero(ratio != 1.0)[0]]
    return _Series(days, close_unadj, ad, open_adj, ev, dates[-1], raw_events)


def _day(x) -> int:
    return int((np.datetime64(to_date(x).isoformat(), "D") - EPOCH).astype(np.int64))


def _pos(v) -> bool:
    return bool(np.isfinite(v) and v > 0)


class LazyDailyPriceSource(PriceSource):
    """See the module docstring."""
    basis = "traded_unadjusted"

    def __init__(self, folder, max_cached: int = 256, max_gap_days: int = 5, delistings=None, entry_field: str = "open"):
        self.folder = Path(folder)
        if not self.folder.is_dir():
            raise DataNotPresent(f"the daily price folder {self.folder} does not exist")
        if entry_field not in ("open", "adj_close"):
            raise ValueError("entry_field is 'open' (registered) or 'adj_close'")
        self.max_cached, self.max_gap, self.entry_field = int(max_cached), int(max_gap_days), entry_field
        self.delistings = delistings
        self._keys = None
        self._lru: "OrderedDict[str, Optional[_Series]]" = OrderedDict()

    # ---- the folder ---------------------------------------------------------------------------------------------------------------
    def keys(self) -> set:
        if self._keys is None:
            self._keys = {p.name[:-len(SUFFIX)] for p in self.folder.iterdir() if p.is_file() and p.name.endswith(SUFFIX)}
        return self._keys

    def has_key(self, key) -> bool:
        return key in self.keys()

    def _series(self, key) -> Optional[_Series]:
        if key in self._lru:
            self._lru.move_to_end(key)
            return self._lru[key]
        if not self.has_key(key):
            return None
        s = parse_file(self.folder / (key + SUFFIX))
        self._lru[key] = s
        while len(self._lru) > self.max_cached:
            self._lru.popitem(last=False)
        return s

    def drop_cache(self):
        self._lru.clear()

    def cached(self) -> int:
        return len(self._lru)

    # ---- lookups ------------------------------------------------------------------------------------------------------------------
    def _find(self, key, asof) -> Tuple[Optional[_Series], Optional[int], Optional[int]]:
        """(series, index of the bar, gap in days) of the latest bar on or before `asof` within the gap, else (series or None, None, None)."""
        s = self._series(key)
        if s is None:
            return None, None, None
        d = _day(asof)
        i = int(np.searchsorted(s.days, d, side="right")) - 1
        if i < 0:
            return s, None, None
        gap = d - int(s.days[i])
        if gap > self.max_gap:
            return s, None, None
        return s, i, gap

    def close_unadjusted(self, key, asof):
        s, i, gap = self._find(key, asof)
        if i is None or not _pos(s.close_unadj[i]):
            return None
        flags = [] if gap == 0 else ["stale_bar"]
        return PricePoint(float(s.close_unadj[i]), _iso(s.days[i]), flags, QUALITY_VERIFIED if not flags else QUALITY_UNVERIFIED)

    def adj_close(self, key, asof):
        s, i, _gap = self._find(key, asof)
        if i is None or not _pos(s.adj[i]):
            return None
        return PricePoint(float(s.adj[i]), _iso(s.days[i]))

    def entry_point(self, key, asof):
        """The NEXT session strictly after `asof` (within the gap): its total-return-adjusted open (registered) or adjusted close."""
        s = self._series(key)
        if s is None:
            return None
        d = _day(asof)
        i = int(np.searchsorted(s.days, d, side="right"))
        if i >= len(s.days) or int(s.days[i]) - d > self.max_gap:
            return None
        v = s.open_adj[i] if self.entry_field == "open" else s.adj[i]
        if not _pos(v):
            return None
        return PricePoint(float(v), _iso(s.days[i]))

    def splits(self, key):
        s = self._series(key)
        return None if s is None else list(s.splits)

    def last_date(self, key):
        s = self._series(key)
        return None if s is None else s.last_iso

    def first_date(self, key):
        """The first bar of the ticker's file (iso date), or None when the ticker is not in the folder."""
        s = self._series(key)
        return None if s is None else _iso(s.days[0])

    def raw_split_events(self, key):
        """[(ex-date, ratio)] of the split events whose pre-split Close was found NOT adjusted (the traded close is the Close there); None when the ticker is not in the folder."""
        s = self._series(key)
        return None if s is None else list(s.raw_events)


def _iso(day) -> str:
    return str(EPOCH + np.timedelta64(int(day), "D"))


# ---- M6: the monthly file as the fallback for a ticker whose D5 history starts late ------------------------------------------------------------------

FALLBACK_FLAG = "price_monthly_fallback"


class FallbackPriceSource(PriceSource):
    """A D5 daily source with the operator-approved monthly raw file behind it, for the tickers whose D5 history STARTS AFTER the date asked for (Addendum M6: QRVO and 16 others; 521 ticker-dates
    over the 36 development month-ends, `scratch/rev23/gate1_dev/round5/price_crosscheck_monthly_vs_daily.txt`).

    * the valuation price of such a ticker at a month-end date is the monthly file's traded close (`MonthlyRawPriceSource.close_unadjusted`), flagged `price_monthly_fallback` and UNVERIFIED (a month-end bar
      stands for the last session);
    * outcomes use the daily data where it exists and the monthly data where it does not: `adj_close` and `entry_point` read the daily bar when the ticker has one at the date and the monthly bar when its
      daily history has not started, each flagged `price_monthly_fallback`; `entry_point` of a monthly bar is the decision bar itself (no next session), as the monthly source says;
    * the fallback applies ONLY to the late-start case: a ticker that D5 does not hold at all is not a key; a ticker whose daily history ended, or whose bar is missing within the gap, has no price (a gap
      is never filled from a month-end bar);
    * `splits` is the daily exact-date events plus the monthly (month-dated) events of the months BEFORE the daily history starts, so that a share count at a date in the fallback stretch is put on the traded basis.
    Everything else is the daily source's."""
    basis = "traded_unadjusted"

    def __init__(self, daily: LazyDailyPriceSource, monthly, delistings=None):
        self.daily, self.monthly = daily, monthly
        self._splits = {}
        self.delistings = delistings
        if delistings is not None:
            daily.delistings = delistings

    # the delisting events live on the daily source (outcomes read them through this object)
    def delisting(self, key):
        return (self.delistings or self.daily.delistings or {}).get(key)

    def has_key(self, key):
        return self.daily.has_key(key)

    def late(self, key, asof) -> bool:
        """True when the ticker is in D5, its first bar lies after `asof`, and the monthly file holds it."""
        first = self.daily.first_date(key)
        return first is not None and first > to_date(asof).isoformat() and self.monthly.has_key(key)

    def _tag(self, p):
        return None if p is None else PricePoint(p.price, p.bar, tuple(p.flags) + (FALLBACK_FLAG,), QUALITY_UNVERIFIED)

    def close_unadjusted(self, key, asof):
        p = self.daily.close_unadjusted(key, asof)
        if p is None and self.late(key, asof):
            return self._tag(self.monthly.close_unadjusted(key, asof))
        return p

    def adj_close(self, key, asof):
        p = self.daily.adj_close(key, asof)
        if p is None and self.late(key, asof):
            return self._tag(self.monthly.adj_close(key, asof))
        return p

    def entry_point(self, key, asof):
        p = self.daily.entry_point(key, asof)
        if p is None and self.late(key, asof):
            return self._tag(self.monthly.entry_point(key, asof))
        return p

    def splits(self, key):
        if key not in self._splits:
            ev = self.daily.splits(key)
            if ev is None:
                self._splits[key] = None
            else:
                first = self.daily.first_date(key)
                early = [(m, r) for m, r in (self.monthly.splits(key) if self.monthly.has_key(key) else []) if m < first[:7]]
                self._splits[key] = sorted(early) + list(ev)
        return self._splits[key]

    def last_date(self, key):
        return self.daily.last_date(key)

    def target_date(self, asof, months):
        return self.daily.target_date(asof, months)

    def drop_cache(self):
        self.daily.drop_cache()


# ---- a scan of the whole folder (a one-off check, not part of a run) -------------------------------------------------------------------------

def validate_folder(folder, only: Optional[List[str]] = None) -> dict:
    """Parse every ticker file once and report what a loader must know: the file count, files that do not parse (with the reason), the manifest's row counts against the parsed rows,
    bars whose Close is not positive, and the splits seen.  Reads every file, one at a time (memory stays one file)."""
    folder = Path(folder)
    man = {}
    mp = folder / "manifest.csv"
    if mp.is_file():
        with open(mp, "r", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                man[r["ticker"]] = r
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.name.endswith(SUFFIX))
    if only is not None:
        keep = set(only)
        files = [p for p in files if p.name[:-len(SUFFIX)] in keep]
    out = {"files": len(files), "unparseable": [], "rows_mismatch": [], "nonpositive_close_bars": 0, "files_with_nonpositive_close": 0, "bars": 0, "splits": 0,
           "not_in_manifest": [], "manifest_ok_without_file": [], "raw_split_events": 0, "files_with_raw_split_events": 0}
    for p in files:
        k = p.name[:-len(SUFFIX)]
        try:
            s = parse_file(p)
        except DataNotPresent as e:
            out["unparseable"].append([k, str(e)[-160:]])
            continue
        out["bars"] += len(s.days)
        out["splits"] += len(s.splits)
        if s.raw_events:
            out["raw_split_events"] += len(s.raw_events)
            out["files_with_raw_split_events"] += 1
        bad = int(np.sum(~np.isfinite(s.close_unadj) | (s.close_unadj <= 0)))
        if bad:
            out["nonpositive_close_bars"] += bad
            out["files_with_nonpositive_close"] += 1
        m = man.get(k)
        if m is None:
            out["not_in_manifest"].append(k)
        elif str(m.get("rows", "")).isdigit() and int(m["rows"]) != len(s.days):
            out["rows_mismatch"].append([k, int(m["rows"]), len(s.days)])
    present = {p.name[:-len(SUFFIX)] for p in files}
    if only is None:
        out["manifest_ok_without_file"] = sorted(k for k, r in man.items() if (r.get("status") or "").strip() == "ok" and k not in present)
    return out

"""Backtest registration (registration_LOCKED_d09bb4a4.md): the small pure helpers every part of the harness shares.

Dates, months, split arithmetic (section 4.3), the price book, and a numeric test that treats 0.0 as a value.  Nothing
here imports a revision of the reference code, reads a return, or touches the network.
"""
import calendar
import json
import math
from datetime import date

REGISTRATION_SHA256 = "d09bb4a49ff6293eafb5453b17ed1920fc3e5f58a3d8c93e52db52eef181d0fa"
DATES = ("2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023")      # valuation years; T is the last trading day of June
DESIGN_YEARS = ("2016", "2017", "2018")
VALIDATION_YEARS = ("2019", "2020", "2021", "2022", "2023")


def is_num(v):
    """True for a real finite number, 0.0 included; False for None, bool, NaN and +/-inf."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_num_or_inf(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(v)


def parse_date(s):
    return date.fromisoformat(s)


def add_months(d, n):
    """d moved by n calendar months, the day clipped to the target month's length."""
    idx = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(idx, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1]))


def ym(d):
    """'YYYY-MM' of a date or an ISO date string."""
    if isinstance(d, str):
        return d[:7]
    return f"{d.year:04d}-{d.month:02d}"


def month_index(s):
    """Month number of a 'YYYY-MM' key (comparable, subtractable)."""
    return int(s[:4]) * 12 + int(s[5:7]) - 1


def ym_add(s, n):
    idx = month_index(s) + n
    y, m0 = divmod(idx, 12)
    return f"{y:04d}-{m0 + 1:02d}"


# ---- split arithmetic (registration 4.3) --------------------------------------------------------------------------
# The price file carries a split ratio per monthly bar ("Stock Splits": 2.0 = a 2-for-1, 0.1 = a 1-for-10) and no ex-date.
# A split is therefore dated by its month.  "After date d" means a month strictly later than d's month; a split in d's
# own month cannot be placed before or after d and is counted (`same_month`) so the reviewer sees how often it arises.

def split_events(series):
    """[(ym, ratio)] for the bars of one ticker's {ym: [close, adj, div, split]} that carry a split (ratio not None, not 0)."""
    out = []
    for key in sorted(series):
        v = series[key]
        r = v[3] if len(v) > 3 else None
        if is_num(r) and r != 0:
            out.append((key, float(r)))
    return out


def split_product(events, after_ym, upto_ym=None):
    """Product of the ratios whose month is later than `after_ym` and, when given, not later than `upto_ym`."""
    p = 1.0
    for key, r in events:
        if month_index(key) > month_index(after_ym) and (upto_ym is None or month_index(key) <= month_index(upto_ym)):
            p *= r
    return p


def split_in_month(events, month):
    return any(key == month for key, _ in events)


class PriceBook:
    """The approved monthly price download (Close split-adjusted, Adj Close, Dividends, Stock Splits), read-only.

    Pre-outcome code may call `close_at`, `has_bar` (a presence test only), `events` and `price_at_T`.  `adj_close`
    is the only accessor of the total-return series and is used by the metrics code, which the look gate guards."""

    def __init__(self, doc):
        self.meta = doc.get("meta", {})
        self.prices = doc["prices"]
        self.empty = set(doc.get("empty_tickers", []))
        self._ev = {}

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def has_ticker(self, t):
        return t in self.prices

    def has_bar(self, t, month):
        """True when the ticker has a bar for the month with a real Close and Adj Close (presence only; no value is read out)."""
        v = (self.prices.get(t) or {}).get(month)
        return v is not None and is_num(v[0]) and is_num(v[1]) and v[0] > 0

    def close_at(self, t, month):
        v = (self.prices.get(t) or {}).get(month)
        return float(v[0]) if v is not None and is_num(v[0]) and v[0] > 0 else None

    def adj_close(self, t, month):
        v = (self.prices.get(t) or {}).get(month)
        return float(v[1]) if v is not None and is_num(v[1]) and v[1] > 0 else None

    def events(self, t):
        if t not in self._ev:
            self._ev[t] = split_events(self.prices.get(t) or {})
        return self._ev[t]

    def price_at_T(self, t, year):
        """P(T) = Close(Y-06) x the product of the split ratios with ex-dates after T (months later than Y-06).  None without a bar."""
        close = self.close_at(t, f"{year}-06")
        if close is None:
            return None
        return close * split_product(self.events(t), f"{year}-06")

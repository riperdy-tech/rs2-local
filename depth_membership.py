#!/usr/bin/env python3
"""depth_membership.py — daily RN+WL membership snapshot + dwell computation.

The boundary-crossing triggers (re-entry, exit-review) and the retire/held-exempt book rules
(DEPTH_ORCHESTRATOR_CADENCE_20260825.md §3-4) all key on how long a name has been continuously
IN or OUT of the analyse boundary (research_now ∪ watchlist). That history does not exist in any
existing feed — factor_signal_log.jsonl is the SCREENER's and only lists in-band names, so a name
that leaves it simply vanishes and "days out" cannot be read from it. So we accumulate our own
append-only daily record here, forward from first run.

DETERMINISTIC AND ADDITIVE: this module only READS factor_scores.json and WRITES its own log
under cache/. It renders no opinion and touches no verdict, overlay, or Modelfile.

  snapshot()        record today's RN+WL set (idempotent per UTC-local calendar day)
  dwell_in(t)       consecutive days t has been IN, counting back from the newest snapshot
  dwell_out(t)      consecutive days t has been OUT, counting back from the newest snapshot
  held_names()      union of open positions across all paper_ledgers scopes
"""
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402
sys.path.insert(0, str(HERE))
import rs2_data  # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
LOG = HERE / "cache" / "depth_membership.jsonl"
IN_BANDS = ("research_now", "watchlist")


def _current_book():
    """Today's RN+WL set from the screener's factor_scores.json (uppercased)."""
    fs = (rs2_data.load_json(SD / "factor_scores.json") or {}).get("tickers", {})
    return sorted({t.upper() for t, e in fs.items()
                   if (e or {}).get("fct_band") in IN_BANDS})


def _read():
    """[(date_str, set_of_tickers)] oldest→newest. Missing/empty log → []."""
    out = []
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                out.append((d["date"], set(d.get("in", []))))
            except Exception:
                continue
    return out


def snapshot(today=None):
    """Append today's RN+WL membership. Idempotent: at most one row per calendar day — a second
    call on the same date OVERWRITES that day's row (a re-run mid-day sees the latest bands),
    never appends a duplicate that would corrupt the consecutive-day dwell counts.

    `today` is injectable for tests only; production passes None (Date.now is fine here — this is
    not a workflow script). Returns (date, n_in)."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    book = _current_book()
    rows = _read()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # rewrite, replacing any existing row for `today`, preserving order
    kept = [(d, s) for d, s in rows if d != today]
    kept.append((today, set(book)))
    kept.sort(key=lambda x: x[0])
    LOG.write_text(
        "\n".join(json.dumps({"date": d, "in": sorted(s)}) for d, s in kept) + "\n",
        encoding="utf-8")
    return today, len(book)


def _tail_streak(t, want_in):
    """Consecutive newest snapshots in which (t ∈ set) == want_in. 0 if the newest snapshot does
    not match want_in, or if there is no history."""
    rows = _read()
    n = 0
    for _, s in reversed(rows):
        if (t in s) == want_in:
            n += 1
        else:
            break
    return n


def dwell_in(t):
    """Consecutive days t has been IN the boundary, counting back from the newest snapshot."""
    return _tail_streak(t.upper(), True)


def dwell_out(t):
    """Consecutive days t has been OUT of the boundary, counting back from the newest snapshot.
    A name never yet seen in any snapshot returns the full snapshot count (it has been 'out' for
    the whole record) — callers that care about 'was ever in' should check history separately."""
    return _tail_streak(t.upper(), False)


def snapshots_recorded():
    """How many daily rows exist — the warm-up gauge for the dwell triggers."""
    return len(_read())


def held_names():
    """Union of currently-held tickers across every paper_ledgers scope (state.holdings keys).
    Empty set on any read failure — a held-name we cannot read must degrade to 'not exempt from
    the normal rules', never crash the sweep."""
    held = set()
    try:
        lg = (rs2_data.load_json(SD / "paper_ledgers.json") or {}).get("ledgers", {})
        for scope in lg.values():
            for tk in ((scope or {}).get("state", {}) or {}).get("holdings", {}) or {}:
                held.add(tk.upper())
    except Exception:
        return set()
    return held


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    d, n = snapshot()
    print(f"snapshot {d}: {n} names in RN+WL | {snapshots_recorded()} daily rows on record")
    print(f"held (exempt from retire): {sorted(held_names())}")

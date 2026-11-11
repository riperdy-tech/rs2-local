"""dropped_readout.py - the names the Qwen book (FQ) drops, tracked against the names it keeps (WO_DR1). A measurement; it changes no book.

    python dropped_readout.py

Reads <books>/m3o/ledger/actions.jsonl. Per formation T, the last FQ fill-open or pending-resolution line of each ticker decides its
group: kept, flagged_held (a flagged name already held is not sold), dropped_code (B1 only), dropped_qwen (Q1 only), dropped_both, or
other (listed, in no return). Every name is measured from the open of the formation's fill session to the close of the k-th session
after it (k = 20, 60, 120, 250 where reached) and to the last completed session, next to SPY. One price fetch per run.
Writes <books>/m3o/readout/dropped_<last completed session>.json and prints it. Descriptive only: no test, no verdict.
"""
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths  # noqa: E402

HORIZONS = (20, 60, 120, 250)
GROUPS = ("kept", "flagged_held", "dropped_code", "dropped_qwen", "dropped_both")
DROPPED = ("dropped_qwen", "dropped_code", "dropped_both")
KINDS = ("at_fill_open", "pending_resolution")
YARDSTICK = "SPY"
NOTE = "descriptive; a handful of dropped names per formation"


def group_of(line):
    """The group of one action line (see the module docstring)."""
    action, causes = line.get("action"), set(line.get("causes") or [])
    if action in ("enter", "hold", "enter_after_pending") and not causes:
        return "kept"
    if action == "hold":
        return "flagged_held"
    if action == "new_entry_restricted":
        if causes == {"B1"}:
            return "dropped_code"
        if causes == {"Q1"} or (not causes and line.get("rule") == "Q1"):
            return "dropped_qwen"
        if {"B1", "Q1"} <= causes:
            return "dropped_both"
    return "other"


def formations(lines):
    """{T: {"fill_session": iso, "names": {ticker: (group, action)}}} from the last FQ line of each ticker per formation."""
    out = {}
    for l in lines:
        if l.get("arm") != "FQ" or l.get("kind") not in KINDS:
            continue
        f = out.setdefault(l["formation_T"], {"fill_session": l["fill_session"], "names": {}})
        f["names"][l["ticker"]] = (group_of(l), l["action"])
    return out


def yf_fetch(tickers, start, end):
    """(source label, {ticker: {iso date: (adjusted open, adjusted close)}}), forward_ledger.fetch_prices parameters; writes nothing."""
    import yfinance as yf
    df = yf.download(sorted(tickers), start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                     auto_adjust=True, actions=False, progress=False, group_by="ticker", threads=False)
    px = {}
    for t in sorted(tickers):
        try:
            sub = df[t] if len(tickers) > 1 else df
        except KeyError:
            continue
        for idx, rec in sub.iterrows():
            o, c = rec.get("Open"), rec.get("Close")
            if o == o and c == c and o is not None and c is not None and idx.date() <= end:
                px.setdefault(t, {})[idx.date().isoformat()] = (float(o), float(c))
    return f"yfinance {yf.__version__} download auto_adjust=True", px


def measure(bars, base_date, horizon_dates):
    """({horizon: return}, {horizon: date of the bar used when the horizon date had none}); (None, None) when the name has no
    priced return. bars: {iso date: (open, close)}. horizon_dates: {horizon: iso date}."""
    if base_date not in bars or not any(d > base_date for d in bars):
        return None, None
    base = bars[base_date][0]
    if base == 0:
        return None, None
    rets, stale = {}, {}
    for h, d in horizon_dates.items():
        use = max(x for x in bars if x <= d)
        if use <= base_date:
            continue
        rets[h] = bars[use][1] / base - 1.0
        if use != d:
            stale[h] = use
    return rets, stale


def mean_median(xs):
    return (round(statistics.fmean(xs), 6), round(statistics.median(xs), 6)) if xs else (None, None)


def group_stats(rows, horizons):
    """rows: priced names {"returns", "spy"}. Per horizon: n_priced, mean and median return, and the same minus SPY."""
    out = {}
    for h in horizons:
        r = [x["returns"][h] for x in rows if h in x["returns"]]
        ex = [x["returns"][h] - x["spy"][h] for x in rows if h in x["returns"]]
        (m, md), (me, mde) = mean_median(r), mean_median(ex)
        out[h] = {"n_priced": len(r), "mean": m, "median": md, "mean_minus_spy": me, "median_minus_spy": mde}
    return out


def minus_kept(stats, horizons):
    """Mean return of each dropped group minus the mean of kept, per horizon; null when a side has no priced name."""
    return {g: {h: None if stats[g][h]["mean"] is None or stats["kept"][h]["mean"] is None
                else round(stats[g][h]["mean"] - stats["kept"][h]["mean"], 6) for h in horizons} for g in DROPPED}


def readout(lines, fetch, today=None):
    """The whole readout dict. fetch(tickers, start, end) -> (source, {ticker: {iso date: (open, close)}})."""
    forms = formations(lines)
    if not forms:
        raise SystemExit("STOP: no FQ at_fill_open / pending_resolution lines in the action ledger")
    tickers = {t for f in forms.values() for t in f["names"]} | {YARDSTICK}
    first = min(date.fromisoformat(f["fill_session"]) for f in forms.values())
    end = (today or datetime.now(timezone.utc).date()) - timedelta(days=1)
    fetched_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source, px = fetch(tickers, first, end)
    sessions = sorted(d for d in px.get(YARDSTICK, {}) if first.isoformat() <= d <= end.isoformat())
    if not sessions:
        raise SystemExit(f"STOP: no {YARDSTICK} bars between {first} and {end}")
    last = sessions[-1]
    out = {"source": source, "fetched_utc": fetched_utc, "last_completed_session": last, "note": NOTE, "fill_sessions": {}, "formations": {}}
    pool = {h: {g: {"n": 0, "rows": []} for g in GROUPS} for h in HORIZONS}      # each name once per formation
    for T, f in sorted(forms.items()):
        fs = f["fill_session"]
        out["fill_sessions"][T] = fs
        if fs not in sessions:
            raise SystemExit(f"STOP: formation {T} fill session {fs} is not a {YARDSTICK} session up to {last}")
        i = sessions.index(fs)
        hd = {h: sessions[i + h] for h in HORIZONS if i + h < len(sessions)}
        hd["to_date"] = last
        spy, _ = measure({d: v for d, v in px[YARDSTICK].items() if d <= last}, fs, hd)
        names, other = {g: [] for g in GROUPS}, []
        for t, (g, action) in sorted(f["names"].items()):
            if g == "other":
                other.append({"ticker": t, "action": action})
                continue
            rets, stale = measure({d: v for d, v in px.get(t, {}).items() if d <= last}, fs, hd)
            row = {"ticker": t, "no_price": True} if rets is None else {"ticker": t, "returns": rets, "spy": spy}
            if stale:
                row["stale_bar"] = stale
            names[g].append(row)
            for h in hd:
                if h != "to_date":
                    pool[h][g]["n"] += 1
                    if rets is not None and h in rets:
                        pool[h][g]["rows"].append(row)
        stats = {g: group_stats([x for x in names[g] if "returns" in x], list(hd)) for g in GROUPS}
        out["formations"][T] = {
            "fill_session": fs, "spy": spy, "other": other,
            "groups": {g: {"n": len(names[g]), "n_priced": sum(1 for x in names[g] if "returns" in x),
                           "no_price": sum(1 for x in names[g] if "returns" not in x), "names": names[g], "stats": stats[g]}
                       for g in GROUPS},
            "minus_kept": minus_kept(stats, list(hd))}
    pstats = {h: {g: {"n": pool[h][g]["n"], **group_stats(pool[h][g]["rows"], [h])[h]} for g in GROUPS} for h in HORIZONS}
    out["pooled"] = {"note": "each name counted once per formation; fixed horizons only; n counts the formations that reach the horizon",
                     "groups": pstats, "minus_kept": minus_kept({g: {h: pstats[h][g] for h in HORIZONS} for g in GROUPS}, HORIZONS)}
    return out


def main(fetch=yf_fetch, today=None, out_dir=None):
    ledger = book_paths.books() / "m3o" / "ledger" / "actions.jsonl"
    lines = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    res = readout(lines, fetch, today)
    d = Path(out_dir) if out_dir else book_paths.books() / "m3o" / "readout"
    d.mkdir(parents=True, exist_ok=True)
    text = json.dumps(res, indent=1)
    (d / f"dropped_{res['last_completed_session']}.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

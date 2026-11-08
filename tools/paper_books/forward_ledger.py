"""WO_L7: append-only forward A0 ledger from GitHub runs that pass the WO_L3 verifier.

Usage: python forward_ledger.py [--asof YYYY-MM-DD]
Reads the witness archive (paths.py gh_witness_dir) and git blobs (paths.py screener_publish_repo); fetches adjusted prices from
Yahoo (yfinance). Writes, in <rs2_state_dir>/paper_books/m3l_forward/: formations.jsonl (append-only), prices/<fetch>.csv + receipt,
mtm_<asof>.json. The operator exclusions are read from <rs2_state_dir>/paper_books/operator_excluded.json.
"""
import argparse, csv, hashlib, io, json, subprocess, sys, zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths  # noqa: E402

HERE = book_paths.books() / "m3l_forward"     # the books (data), not this file's folder
ARCHIVE = book_paths.witness_archive()
REPO = book_paths.screener_repo()
NY = ZoneInfo("America/New_York")
FIRST_T = date(2026, 9, 30)  # first month-end with the dual-door engine live (first run 2026-09-22)
NYSE_HOLIDAYS = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
                 date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
                 date(2027, 1, 1)}
OPERATOR_EXCLUDED = book_paths.operator_excluded()
COSTS_BP = (0, 20, 60)

import m3l_gh_run_witness as W  # noqa: E402


def fd_candidates():
    """Tickers of the m3o formation maps' "candidates" lists (paper book FD, PREREG_m3o_bookD): priced with the books so the m3o
    engine can mark a replacement. Only the fetch grows; no A0 arithmetic reads them."""
    import re
    out = set()
    for p in (book_paths.books() / "m3o" / "inputs").glob("formation_*.json"):
        if re.fullmatch(r"formation_\d{4}-\d{2}-\d{2}\.json", p.name):
            out |= {c["ticker"] for c in json.loads(p.read_text(encoding="utf-8")).get("candidates") or []}
    return out


def session(d):
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def next_session(d):
    d += timedelta(days=1)
    while not session(d):
        d += timedelta(days=1)
    return d


def month_end_sessions(start, until):
    out, d = [], start
    while d <= until:
        month_end = date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)
        last = month_end
        while not session(last):
            last -= timedelta(days=1)
        if start <= last <= until:
            out.append(last)
        d = month_end + timedelta(days=1)  # the next calendar month (last + 1 loops when a month ends on a weekend)
    return out


def last_completed_session():
    """The latest session whose 16:00 New York close has passed; an open session's prices are still moving."""
    now = datetime.now(NY)
    d = now.date()
    while not session(d) or (d == now.date() and now.time() < time(16, 15)):
        d -= timedelta(days=1)
    return d


def open_utc(d):
    return datetime.combine(d, time(9, 30), NY).astimezone(timezone.utc)


def scoring_runs():
    rows = list(csv.DictReader(open(ARCHIVE / "index.csv", encoding="utf-8")))
    out = []
    for r in rows:
        if r["logs_status"] != "SAVED" or r["conclusion"] != "success":
            continue
        with zipfile.ZipFile(ARCHIVE / r["run_id"] / "logs.zip") as z:
            if any(b"STEP DONE: score_factors_dual_door rc=0" in z.read(n) for n in z.namelist()):
                out.append(r)
    return sorted(out, key=lambda r: r["updated_at"])


def decision_for(T, runs):
    F = next_session(T)
    cutoff = open_utc(F)
    cands = [r for r in runs if W.parse_ts(r["updated_at"]) < cutoff]
    if not cands:
        return None, F, "no scoring run before the fill open"
    r = cands[-1]
    res = W.verify(r["run_id"], ARCHIVE, REPO)
    if res["verdict"] != "PASS":
        return None, F, f"latest run {r['run_id']} fails the verifier: {res['checks']}"
    return res, F, None


def book(res):
    fs = json.loads(W.Git(REPO).show(res["output_commit"], "public/data/factor_scores.json"))
    T = fs["tickers"]
    names = sorted(t for t, v in T.items() if v.get("fct_band") == "research_now")
    flags = {}
    for t in names:
        f = []
        detail = json.dumps(T[t].get("fct_flags") or []) + json.dumps(T[t].get("fct_flag_detail") or {})
        if "non_common" in detail or "preferred" in detail.lower():
            f.append("non_common_flagged_by_screener")
        if t in OPERATOR_EXCLUDED:
            f.append("operator_excluded")
        if f:
            flags[t] = f
    return names, flags


def load_ledger():
    p = HERE / "formations.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def fetch_prices(tickers, start, end):
    import yfinance as yf
    fetched_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    df = yf.download(sorted(tickers), start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                     auto_adjust=True, actions=False, progress=False, group_by="ticker", threads=False)
    rows = []
    for t in sorted(tickers):
        try:
            sub = df[t] if len(tickers) > 1 else df
        except KeyError:
            continue
        for idx, rec in sub.iterrows():
            o, c = rec.get("Open"), rec.get("Close")
            if o == o and c == c and o is not None and c is not None and idx.date() <= end:  # drop NaN, keep <= asof
                rows.append((t, idx.date().isoformat(), float(o), float(c)))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["ticker", "date", "adj_open", "adj_close"])
    w.writerows(rows)
    raw = buf.getvalue().encode("utf-8")
    pdir = HERE / "prices"
    pdir.mkdir(exist_ok=True)
    stem = fetched_utc.replace(":", "")
    (pdir / f"{stem}.csv").write_bytes(raw)
    receipt = {"fetched_utc_local_clock": fetched_utc, "source": f"yfinance {yf.__version__} download auto_adjust=True",
               "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(rows), "tickers_requested": len(tickers),
               "window": [start.isoformat(), end.isoformat()],
               "note": "acquisition receipt only; Yahoo publication times are not observed"}
    (pdir / f"{stem}.receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    px = {}
    for t, d, o, c in rows:
        px.setdefault(t, {})[d] = (o, c)
    return px, receipt


def period_return(names, px, F, exit_F, last_day):
    log, rets = [], {}
    for t in names:
        s = px.get(t, {})
        if F.isoformat() not in s:
            rets[t] = 0.0
            log.append({"ticker": t, "event": "missing_entry_bar_held_as_cash"})
            continue
        entry = s[F.isoformat()][0]
        if exit_F is not None and exit_F.isoformat() in s:
            ex, how = s[exit_F.isoformat()][0], "exit_open"
        else:
            days = sorted(d for d in s if d <= (exit_F or last_day).isoformat())
            ex, how = s[days[-1]][1], ("mtm_last_close" if exit_F is None else "missing_exit_bar_last_close")
            if exit_F is not None:
                log.append({"ticker": t, "event": how, "date": days[-1]})
        rets[t] = ex / entry - 1.0
    return rets, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=None, help="last price date to use (default: today, New York)")
    a = ap.parse_args()
    asof = date.fromisoformat(a.asof) if a.asof else last_completed_session()
    runs = scoring_runs()
    ledger = load_ledger()
    known = {r["formation_T"]: r for r in ledger}
    formations = []
    for T in month_end_sessions(FIRST_T, asof):
        F = next_session(T)
        if open_utc(F) > datetime.now(timezone.utc):
            break  # its fill has not happened yet
        res, F, err = decision_for(T, runs)
        if err:
            print(f"STOP at {T}: {err}")
            break
        names, flags = book(res)
        rec = {"formation_T": T.isoformat(), "fill_session": F.isoformat(), "run_id": res["run_id"],
               "workflow": res["workflow"], "decision_time_utc": res["decision_time_utc"],
               "output_commit": res["output_commit"], "scoring_base": res["scoring_base"],
               "verifier": {"verdict": res["verdict"], "checks": res["checks"],
                            "input_issues": [i["path"] for i in res.get("input_issues", [])],
                            "mri": res.get("mri")},
               "book_size": len(names), "book": names, "flags": flags}
        if T.isoformat() in known:
            old = known[T.isoformat()]
            same = {k: old[k] for k in ("run_id", "output_commit", "book")} == {k: rec[k] for k in ("run_id", "output_commit", "book")}
            if not same:
                sys.exit(f"STOP: stored formation {T} differs from a recomputation; the ledger is append-only")
        else:
            with open(HERE / "formations.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
            print(f"appended formation {T}: run {res['run_id']} book {len(names)}")
        formations.append(rec)
    if not formations:
        print("no formation with a completed fill yet")
        return
    universe = set().union(*(set(r["book"]) for r in formations)) | {"SPY"} | fd_candidates()
    first_F = date.fromisoformat(formations[0]["fill_session"])
    px, receipt = fetch_prices(universe, first_F - timedelta(days=3), asof)
    last_day = max(d for s in px.values() for d in s)
    periods, prev_w = [], {}
    for i, rec in enumerate(formations):
        F = date.fromisoformat(rec["fill_session"])
        exit_F = date.fromisoformat(formations[i + 1]["fill_session"]) if i + 1 < len(formations) else None
        out = {"formation_T": rec["formation_T"], "fill": rec["fill_session"],
               "exit": exit_F.isoformat() if exit_F else f"OPEN (marked {last_day})"}
        for series, names in (("A0", rec["book"]),
                              ("A0_ex_operator", [t for t in rec["book"] if t not in OPERATOR_EXCLUDED])):
            rets, log = period_return(names, px, F, exit_F, date.fromisoformat(last_day))
            target = {t: 1.0 / len(names) for t in names}
            drifted = prev_w.get(series, {})
            to = 0.5 * sum(abs(target.get(t, 0.0) - drifted.get(t, 0.0)) for t in set(target) | set(drifted))
            gross = sum(rets.values()) / len(names)
            # drifted weights at the end of the period, for the next turnover
            tot = sum(target[t] * (1 + rets[t]) for t in names)
            prev_w[series] = {t: target[t] * (1 + rets[t]) / tot for t in names}
            out[series] = {"n": len(names), "gross": gross, "turnover_one_way": to,
                           **{f"net_{c}bp": gross - to * c / 1e4 for c in COSTS_BP}, "events": log,
                           "best": max(rets, key=rets.get), "worst": min(rets, key=rets.get)}
        spy, _ = period_return(["SPY"], px, F, exit_F, date.fromisoformat(last_day))
        out["SPY"] = spy["SPY"]
        periods.append(out)
    snap = {"asof_price_date": last_day, "computed_utc_local_clock": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price_receipt": receipt, "periods": periods,
            "caveat": "paper only; prices are Yahoo adjusted; no universe benchmark; formations before 2026-09-30 are "
                      "not A0 (old engine)"}
    (HERE / f"mtm_{last_day}.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
    for p in periods:
        print(p["formation_T"], p["fill"], p["exit"], "SPY", round(p["SPY"], 4),
              {s: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p[s].items() if k in ("n", "gross", "net_20bp", "turnover_one_way")}
               for s in ("A0", "A0_ex_operator")})


if __name__ == "__main__":
    main()

"""WO_S1: the equal-weight universe benchmark (SPEC_m3s_paper_trial.md section 0, item 3). Paper only.

The universe at a formation T is the screener's investable universe as published at the formation's output_commit:
  the rows of public/data/stocks.json (read through `git show`) that the scorer found eligible, i.e. whose entry in
  public/data/factor_scores.json at the same commit has `fct_veto` null (score_factors_dual_door.py: not NOT_TRADABLE, a Tier 1 hygiene
  survivor, market cap >= 300M, price >= 3, ADV >= 250K, no shell/forensic/insolvency/no-history veto; equals the file's scored_count).
  stocks.json itself carries no investability flag (its Pass/Fail `status` is the legacy Tier 1 screen). No filter is invented.
  The operator's exclusions (forward_ledger.OPERATOR_EXCLUDED, a data file in rs2-state) are removed afterwards and counted.

Usage:  python universe.py fetch <formation_T> [--forward-dir DIR] [--out-dir DIR] [--asof YYYY-MM-DD]
  builds universe_<T>.json (the ticker list, the field used and the counts; written once, never changed) and downloads adjusted open and
  close (yfinance, in chunks, forward_ledger's parameters) from three days before the fill session to the last completed session into
  universe_<T>_<fetch>.csv + .receipt.json. The ONLY network use; the tests never call it. m3o_engine.py reads these files for the marks.
"""
import argparse, csv, hashlib, io, json, subprocess, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forward_ledger as fl  # noqa: E402  (OPERATOR_EXCLUDED, last_completed_session, REPO; unchanged)

SCHEMA = "m3o.universe.v1"
FIELD = "factor_scores.json tickers[*].fct_veto is null (the scorer's eligibility), joined to the symbols of stocks.json"
CHUNK = 200
EXCLUDED = fl.OPERATOR_EXCLUDED


class UniverseError(Exception):
    """A universe record or price file is missing, inconsistent or would be overwritten."""


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def git_blob(commit, relpath):
    return subprocess.run(["git", "-C", str(fl.REPO), "show", f"{commit}:{relpath}"], capture_output=True, check=True).stdout


def stock_symbols(raw):
    """The symbols of the rows of stocks.json (a list of rows with `symbol`, or a dict keyed by symbol)."""
    d = json.loads(raw)
    if isinstance(d, dict):
        syms = set(d)
    else:
        syms = {r["symbol"] for r in d if isinstance(r, dict) and r.get("symbol")}
    if not syms:
        raise UniverseError("stocks.json has no rows with a symbol")
    return syms


def build_record(formation, stocks_raw, factor_raw):
    """The universe record of a formation (a formations.jsonl line), from the two file contents at its output_commit."""
    rows = stock_symbols(stocks_raw)
    tick = json.loads(factor_raw)["tickers"]
    eligible = {t for t, v in tick.items() if "fct_veto" in v and v["fct_veto"] is None}
    in_both = rows & eligible
    dropped = sorted(in_both & EXCLUDED)
    names = sorted(in_both - EXCLUDED)
    return {"schema": SCHEMA, "formation_T": formation["formation_T"], "fill_session": formation["fill_session"],
            "output_commit": formation["output_commit"], "field": FIELD,
            "stocks_json_sha256": sha256_bytes(stocks_raw), "factor_scores_sha256": sha256_bytes(factor_raw),
            "n_stocks_rows": len(rows), "n_eligible_in_factor_scores": len(eligible),
            "n_eligible_not_in_stocks_rows": len(eligible - rows), "n_eligible_and_in_stocks_rows": len(in_both),
            "excluded_operator": {"tickers": dropped, "count": len(dropped)}, "n_universe": len(names), "tickers": names}


def record_path(out_dir, T):
    return Path(out_dir) / f"universe_{T}.json"


def write_record(out_dir, rec):
    """Write universe_<T>.json once. An existing file must be byte-identical (the universe at a commit does not change)."""
    p = record_path(out_dir, rec["formation_T"])
    raw = json.dumps(rec, indent=1, sort_keys=True).encode("utf-8")
    if p.exists():
        if p.read_bytes() != raw:
            raise UniverseError(f"{p.name} exists and differs from its recomputation; it is never overwritten")
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return p


def load_record(out_dir, T):
    """(record, sha256 of the file) or (None, None)."""
    p = record_path(out_dir, T)
    if not p.exists():
        return None, None
    raw = p.read_bytes()
    rec = json.loads(raw)
    if rec.get("formation_T") != T:
        raise UniverseError(f"{p.name} is for formation {rec.get('formation_T')}")
    return rec, sha256_bytes(raw)


def load_prices(out_dir, T):
    """The latest fetch of formation T: ({ticker: {date: (adj_open, adj_close)}}, receipt), or (None, None). The csv must hash to its receipt."""
    receipts = sorted(Path(out_dir).glob(f"universe_{T}_*.receipt.json"))
    if not receipts:
        return None, None
    rp = receipts[-1]
    receipt = json.loads(rp.read_text(encoding="utf-8"))
    raw = rp.with_name(rp.name.replace(".receipt.json", ".csv")).read_bytes()
    if sha256_bytes(raw) != receipt["sha256"]:
        raise UniverseError(f"{rp.name}: the csv does not hash to its receipt")
    px = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        px.setdefault(r["ticker"], {})[r["date"]] = (float(r["adj_open"]), float(r["adj_close"]))
    return px, receipt


# ---------------------------------------------------------------- the one network call

def yf_download(chunk, start, end):
    """([(ticker, date, adj_open, adj_close)], source label) for one chunk; forward_ledger.fetch_prices' parameters."""
    import yfinance as yf
    df = yf.download(sorted(chunk), start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                     auto_adjust=True, actions=False, progress=False, group_by="ticker", threads=False)
    rows = []
    for t in sorted(chunk):
        try:
            sub = df[t] if len(chunk) > 1 else df
        except KeyError:
            continue
        for idx, rec in sub.iterrows():
            o, c = rec.get("Open"), rec.get("Close")
            if o == o and c == c and o is not None and c is not None and idx.date() <= end:
                rows.append((t, idx.date().isoformat(), float(o), float(c)))
    return rows, f"yfinance {yf.__version__} download auto_adjust=True"


def fetch_prices(tickers, start, end, download=None, chunk=CHUNK):
    """(rows, source label, number of chunks), in chunks of `chunk` tickers. `download` is injectable for tests."""
    download = download or yf_download
    tickers, rows, src, n = sorted(tickers), [], None, 0
    for i in range(0, len(tickers), chunk):
        got, src = download(tickers[i:i + chunk], start, end)
        rows += got
        n += 1
    return rows, src, n


def write_prices(out_dir, rec, rows, src, n_chunks, fetched_utc, start, end):
    out_dir = Path(out_dir)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["ticker", "date", "adj_open", "adj_close"])
    w.writerows(rows)
    raw = buf.getvalue().encode("utf-8")
    stem = f"universe_{rec['formation_T']}_{fetched_utc.replace(':', '')}"
    with_bars = sorted({r[0] for r in rows})
    receipt = {"formation_T": rec["formation_T"], "fetched_utc_local_clock": fetched_utc, "source": src,
               "sha256": sha256_bytes(raw), "rows": len(rows), "tickers_requested": rec["n_universe"],
               "tickers_with_bars": len(with_bars), "tickers_without_bars": sorted(set(rec["tickers"]) - set(with_bars)),
               "chunks": n_chunks, "chunk_size": CHUNK, "window": [start.isoformat(), end.isoformat()],
               "universe_sha256": sha256_bytes(json.dumps(rec, indent=1, sort_keys=True).encode("utf-8")),
               "note": "acquisition receipt only; Yahoo publication times are not observed; a name with no bar is held as cash at 0%"}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.csv").write_bytes(raw)
    (out_dir / f"{stem}.receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    return receipt


def formation_line(forward_dir, T):
    for ln in (Path(forward_dir) / "formations.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip() and json.loads(ln)["formation_T"] == T:
            return json.loads(ln)
    raise UniverseError(f"formation {T} is not in {Path(forward_dir) / 'formations.jsonl'}")


def cmd_fetch(T, forward_dir, out_dir, asof=None, download=None):
    rec = formation_line(forward_dir, T)
    universe = build_record(rec, git_blob(rec["output_commit"], "public/data/stocks.json"),
                            git_blob(rec["output_commit"], "public/data/factor_scores.json"))
    write_record(out_dir, universe)
    F = date.fromisoformat(universe["fill_session"])
    end = asof or fl.last_completed_session()
    if end < F:
        raise UniverseError(f"no completed session on or after the fill session {F}")
    start = F - timedelta(days=3)
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, src, n = fetch_prices(universe["tickers"], start, end, download)
    receipt = write_prices(out_dir, universe, rows, src, n, fetched, start, end)
    return universe, receipt


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("formation_T")
    f.add_argument("--forward-dir", default=str(fl.HERE))
    f.add_argument("--out-dir", default=str(fl.book_paths.books() / "m3o" / "universe_prices"))
    f.add_argument("--asof", default=None, help="last price date (default: the last completed session, New York)")
    a = ap.parse_args()
    try:
        u, r = cmd_fetch(a.formation_T, a.forward_dir, a.out_dir, date.fromisoformat(a.asof) if a.asof else None)
    except UniverseError as e:
        sys.exit(f"STOP: {e}")
    print(f"formation {u['formation_T']} commit {u['output_commit'][:10]}")
    print(f"universe field: {u['field']}")
    print(f"stocks.json rows {u['n_stocks_rows']}; eligible (fct_veto null) {u['n_eligible_in_factor_scores']}; "
          f"operator-excluded {u['excluded_operator']['count']} {u['excluded_operator']['tickers']}; universe {u['n_universe']}")
    print(f"prices: {r['rows']} rows, {r['tickers_with_bars']}/{r['tickers_requested']} names with bars, "
          f"{len(r['tickers_without_bars'])} without (held as cash), window {r['window']}, sha256 {r['sha256'][:12]}")


if __name__ == "__main__":
    main()

"""decided_shadow.py - WO_NC7: the decided valuation on the names already read, unpublished, into folders of its own.

    python tools/site/decided_shadow.py --arm sonnet|opus|gemini --store <cache dir of the stored reads> [--out DIR] [--raw DIR]
                                        [--tickers A,B] [--max-names N] [--dry-run]

For every stored report of the store (<store>/gemini_site/ondemand/<TICKER>.json) whose family is routed (operating, commodity) and whose stored
read exists (the Q1 run's packet.json and analysis.json under <store>/m3m*/runs), it runs decided_value.value at the two seeds from that packet
and read: no reading task, the arm's model through the worker's own swapped call, today's cost of equity, the base re-prepared from the stored
SEC documents (--raw, default this checkout's store, offline). A name code refuses before any call (prepare) is in the table with its reason.

Writes ONLY under --out (default cache/decided_shadow/<arm> of this checkout): runs/<run>/result.json and raw/attempt_<n>.json per run, site/
(the call log and usage of the swapped call), and one table, shadow_table.json and shadow_table.md: old value, new bear/base/bull, the gap
between the two runs, the verdict old and new (the same rule, the same price), the flags. Nothing is published, nothing under <store> is written.
Resumable (a run whose result.json is on disk is not run again), one call at a time, and it stops (exit 3) when the arm's meter is under its
floor before a run. Exit 4: a call failed after the worker's own retries (the run is left for the next invocation).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
sys.path.insert(0, str(HERE))
import decided_financial as DF  # noqa: E402
import decided_value as D  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import qwen_site  # noqa: E402
from qwen_c import runner  # noqa: E402

DROP = ("tasks", "valuation", "ticker", "authority")      # as gemini_ondemand.build: the overlay row of a report
_ROWS = {}


def stored_names(store):
    """[(report, run dir of the stored Q1 run)] of every stored report with a routed family and a stored read, by ticker."""
    out = []
    for p in sorted((store / "gemini_site" / "ondemand").glob("*.json")):
        rep = json.loads(p.read_text(encoding="utf-8"))
        if rep.get("analysis") == "not run" or rep.get("family") not in D.FAMILIES + DF.FAMILIES:
            continue
        stem = f"{rep['ticker']}_{runner.t_compact(rep['date'])}_"
        dirs = sorted(d for m in sorted(store.glob("m3m*")) for d in (m / "runs").glob(stem + "*_1") if (d / "packet.json").exists() and (d / "analysis.json").exists())
        if dirs:
            out.append((rep, dirs[0]))
    return out


def stored_meta(store, rep):
    """(required return, probabilities) of the name's stored menu result (gemini_ondemand.value_meta, on the store)."""
    stem = f"{rep['ticker']}_{runner.t_compact(rep['date'])}_"
    for root in sorted(store.glob("m3q*")):
        for d in sorted((root / "runs").glob(stem + "*")):
            if (d / "result.json").exists():
                r = json.loads((d / "result.json").read_text(encoding="utf-8"))
                prob = (r.get("checks") or {}).get("prob")
                if str(r.get("status", "")).startswith("ok") and r.get("cost_of_equity") is not None and prob:
                    return r["cost_of_equity"], prob
    return None, None


def screener_row(commit, ticker):
    import formation_value as FV
    if commit not in _ROWS:
        _ROWS[commit] = FV.stocks_rows(commit)
    return _ROWS[commit].get(ticker) or {}


def quoted(rep, stock):
    """(overlay row, report) of rep with its values in the unit that trades, as gemini_ondemand.build makes them."""
    row, rp = {k: v for k, v in rep.items() if k not in DROP}, dict(rep)
    qwen_site.quote_units({rep["ticker"]: (row, rp)}, {rep["ticker"]: stock})
    return row


def table_row(rep, stock, store, results):
    """One line of the table from the stored report and the two runs' results."""
    old, (ke_old, prob_old) = quoted(rep, stock), stored_meta(store, rep)
    line = {"ticker": rep["ticker"], "family": rep["family"], "price": stock.get("price"),
            "old": {k: old.get(f"value_{k}") for k in ("bear", "base", "bull")}, "old_verdict": G.verdict(old, ke_old, prob_old)[0]}
    n = {"packet": None, "cik": None, "sector": None, "market_cap": None, "family": rep["family"]}
    new = Q.report(rep["ticker"], "list", rep["date"], {}, n, results, rep.get("screener_commit"))
    line["valued"] = new["valued"]
    if not new["valued"]:
        return dict(line, new=None, new_verdict=None, reason=new["no_value_reason"], run_gap=None, flags=[])
    nrow = quoted(new, stock)
    ke_new = next(iter(results.values()))["cost_of_equity"]
    d = new["decided"]
    return dict(line, new={k: nrow.get(f"value_{k}") for k in ("bear", "base", "bull")}, new_verdict=G.verdict(nrow, ke_new, D.checks.PROB)[0],
                reason=None, run_gap=d["run_gap"], flags=d["flags"], value_at_old_defaults=(nrow["decided"] or {}).get("value_at_old_defaults_quoted"),
                ke_old=ke_old, ke_new=ke_new)


def write_table(out, rows):
    """shadow_table.json and .md: one line per name whose two runs are on disk, by ticker."""
    rows = [rows[t] for t in sorted(rows)]
    (out / "shadow_table.json").write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")
    f = lambda x: "-" if x is None else f"{x:,.2f}"  # noqa: E731
    lines = ["| ticker | price | old bear/base/bull | new bear/base/bull | at old defaults | run gap | verdict old > new | flags |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        new = r["new"] and "/".join(f(r["new"][k]) for k in ("bear", "base", "bull"))
        lines.append(f"| {r['ticker']} | {f(r['price'])} | " + "/".join(f(r["old"][k]) for k in ("bear", "base", "bull"))
                     + f" | {new or 'not valued: ' + str(r['reason'])} | {f(r.get('value_at_old_defaults'))} | "
                     + ("-" if r["run_gap"] is None else f"{r['run_gap']:.1%}") + f" | {r['old_verdict']} > {r['new_verdict'] or '-'} | {'; '.join(r['flags'])} |")
    (out / "shadow_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=sorted(G.ARMS), required=True)
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--raw", type=Path, help="the SEC store root (default: this checkout's cache/m3m/raw)")
    ap.add_argument("--tickers")
    ap.add_argument("--max-names", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    out = a.out or ROOT / "cache" / "decided_shadow" / a.arm
    stored = stored_names(a.store)
    names = [(rep, d) for rep, d in stored if not a.tickers or rep["ticker"] in a.tickers.split(",")]
    runs = out / "runs"
    on_disk = lambda rep, seed: list(runs.glob(f"{rep['ticker']}_{runner.t_compact(rep['date'])}_*_decided_{seed}/result.json"))  # noqa: E731
    done = lambda rep: all(on_disk(rep, s) for s in Q.SEEDS)  # noqa: E731
    if a.dry_run:
        for rep, d in names:
            print(rep["ticker"], rep["family"], "done" if done(rep) else "to run", d.name)
        return 0
    (out / "site").mkdir(parents=True, exist_ok=True)
    G.SITE, G.LOG, G.AGY_CWD = out / "site", out / "site" / "worker.log", out / "site" / "agy_cwd"      # the swapped call writes only here
    G.set_arm(a.arm)
    G.USAGE, G.LOCK = out / "site" / f"usage_{a.arm}.jsonl", out / "shadow.lock"
    if not G.take_lock():
        print("another shadow run holds the lock", flush=True)
        return 0
    rows = {}

    def refresh(rep):
        """The table line of a name whose two runs are on disk: the table is every such name of the store, whatever this invocation's scope."""
        if done(rep):
            rows[rep["ticker"]] = table_row(rep, screener_row(rep.get("screener_commit"), rep["ticker"]), a.store,
                                            {str(s): json.loads(on_disk(rep, s)[0].read_text(encoding="utf-8")) for s in Q.SEEDS})
    try:
        G.swap()
        for rep, _ in stored:
            refresh(rep)
        write_table(out, rows)
        started = 0
        for rep, d in names:
            if done(rep) or (a.max_names is not None and started >= a.max_names):
                continue
            started += 1
            t, pk = rep["ticker"], d / "packet.json"
            stock = screener_row(rep.get("screener_commit"), t)
            cik = json.loads(pk.read_text(encoding="utf-8")).get("cik")
            for seed in Q.SEEDS:
                if on_disk(rep, seed):
                    continue
                m = G.meter()
                low = [k for k in G.FLOORS if m[k][0] < G.FLOORS[k]]
                if low:
                    print(f"stopped before {t} seed {seed}: {', '.join(f'{k} {m[k][0]:.1%} left (floor {G.FLOORS[k]:.0%})' for k in low)}", flush=True)
                    return 3
                G.STATE["label"] = f"{t}:decided{seed}"
                try:
                    res = (DF if rep["family"] in DF.FAMILIES else D).value(pk, str(cik), str(stock.get("sector")), float(stock.get("marketCap") or 0), family=rep["family"],
                                  analysis=json.loads((d / "analysis.json").read_text(encoding="utf-8")), seed=seed, out_root=runs,
                                  online=False, root=a.raw, allow_after_T=True)
                except RuntimeError as e:
                    print(f"{t} seed {seed}: {e}", flush=True)
                    return 4
                print(f"{t} seed {seed}: {res.get('status')} {res.get('reason') or ''}", flush=True)
            refresh(rep)
            write_table(out, rows)
        return 0
    finally:
        G.LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

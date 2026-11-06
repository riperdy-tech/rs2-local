"""qwen_site.py - Qwen's per-stock analysis for the site (stockpeak.net): build the bundle, publish it through screener-publish.

    python tools/site/qwen_site.py build      # writes cache/site/qwen_overlay.json and cache/site/qwen_reports/<T>.json
    python tools/site/qwen_site.py publish    # build, then commit and push them into the screener-publish clone

Sources (rs2-state paper_books, read only): the newest formation map (m3o/inputs/formation_<T>.json; each name's Q1 run directory
with analysis.json), the engine ledger (m3o/ledger/actions.jsonl: what the code book and Qwen's book did with the name), and, when the
formation was valued, consensus_<T>.json (the value of record, design revision 2 rule (a)) with the per-seed results it was built from.
On-demand runs (qwen_ondemand.py) are read from cache/site/ondemand/<T>.json and win over the formation when newer.
Operator-excluded names are never published.

Publish follows orchestrate_depth.publish_overlay's invariants: the dedicated screener-publish clone only (origin must be
stock-screener), the shared lock cache/screener_publish.lock, reset to origin/main, every file parsed before staging, no conflict
markers, rebase-and-push that never drops a remote commit, loud on every abort.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
import book_paths  # noqa: E402
import paths  # noqa: E402

SCHEMA = "qwen_site_v1"
OUT = ROOT / "cache" / "site"
ONDEMAND = OUT / "ondemand"
LOCK = ROOT / "cache" / "screener_publish.lock"
M3O = book_paths.books() / "m3o"
TASKS = ("business_model", "financial_health", "competitive_position", "growth_thesis", "risks", "thesis_change",
         "unresolved_questions", "material_events")
# plain words for the reasons a value is not computed (the desk's refusal codes)
NO_VALUE = {
    "history_short": "too little filed history (fewer than 3 fiscal years, or no revenue in SEC's company facts)",
    "family_not_routed": "no valuation route for this kind of company yet (real estate, pre-profit biotech)",
    "tax_unavailable": "no usable tax rate in the filings",
    "input_missing": "a required figure is not filed (capex or working capital)",
    "shares_unavailable": "diluted share count not filed",
    "shares_scale_unverified": "share count does not reconcile with filed EPS",
    "kd_out_of_band": "implied borrowing cost outside the allowed range",
    "e0_not_positive": "no positive earnings base",
    "preferred_dividends_unavailable": "preferred stock filed without its dividends",
    "facts_stale": "some filed figures are years older than the latest annual report",
    "base_year_not_latest_annual": "the latest annual report's figures are not in SEC's company facts yet",
    "profitloss_basis_unverified": "net income basis does not reconcile with filed EPS",
    "nci_dominant": "minority interests take too large a share of income",
    "coe_unavailable": "cost of equity unavailable for the sector",
    "bridge_unavailable": "operating income for the latest year is not filed under a standard tag",
    "base_year_too_old": "the latest annual report is more than two years old",
    "record_neutral_unavailable": "no usable growth anchor for this company",
}
FQ_ACTION = {"enter": "held", "enter_after_pending": "held (entered after its analysis finished)", "new_entry_restricted":
             "not bought: Qwen flagged a material event", "escalation": "held, with a material event flagged for review",
             "analysis_pending": "cash: analysis not finished at the fill", "operator_excluded": "excluded by the operator"}


def _jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _claims(task):
    return [{"claim": c.get("claim"), "support": c.get("support"), "facts": c.get("fact_ids"), "quotes": c.get("quotes"),
             "basis": c.get("confidence_basis")} for c in (task or {}).get("claims") or []]


def formation_rows(T):
    """{ticker: (overlay row, report)} for one formation."""
    m = json.loads((M3O / "inputs" / f"formation_{T}.json").read_text(encoding="utf-8"))
    excluded = set(book_paths.operator_excluded())
    cons_p = M3O / "value" / f"consensus_{T}.json"
    cons = json.loads(cons_p.read_text(encoding="utf-8"))["names"] if cons_p.exists() else {}
    idx_p = M3O / "value" / f"formation_{T}.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8"))["names"] if idx_p.exists() else {}
    acts = {}
    for a in _jsonl(M3O / "ledger" / "actions.jsonl"):
        if a.get("formation_T") == T and a.get("arm") in ("F", "FQ"):
            acts.setdefault(a["ticker"], {}).setdefault(a["arm"], []).append(a)
    out = {}
    for t, n in sorted(m["names"].items()):
        if t in excluded or n.get("state") == "operator_excluded":
            continue
        an = {}
        if n.get("run_dir") and (Path(n["run_dir"]) / "analysis.json").exists():
            an = json.loads((Path(n["run_dir"]) / "analysis.json").read_text(encoding="utf-8"))
        fq = [a["action"] for a in acts.get(t, {}).get("FQ", [])]
        flags = [c.get("claim") for a in acts.get(t, {}).get("FQ", []) for c in a.get("claims") or [] if c.get("acts") or c.get("escalation")]
        v = cons.get(t) or {}
        valued = str(v.get("status", "")).startswith("ok")
        reason = None
        if not valued:
            codes = sorted({str(s.get("reason")) for s in (idx.get(t) or {}).get("slots", {}).values()}) or ["not_valued"]
            reason = "; ".join(NO_VALUE.get(c, c) for c in codes)
        ss = an.get("support_summary") or {}
        row = {"date": m["decision_time_utc"], "source": f"formation {T}", "model": (an.get("model") or "qwen"), "analysis":
               an.get("status") or "pending", "claims": ss.get("claims"), "claims_supported": ss.get("supported"),
               "in_code_book": bool(acts.get(t, {}).get("F")), "qwen_book": FQ_ACTION.get(fq[-1], fq[-1]) if fq else None,
               "flags": flags[:3], "valued": valued, "no_value_reason": reason, "family": (idx.get(t) or {}).get("family")}
        if valued:
            vals = v["values"]
            seed = next((s for s in (idx.get(t) or {}).get("slots", {}).values() if s.get("result")), None)
            shares = (json.loads(Path(seed["result"]).read_text(encoding="utf-8")).get("base") or {}).get("shares") if seed else None
            row.update(equity_value=vals["base"] * shares if shares else None, filed_shares=shares,
                       value_per_filed_share={k: vals[k] for k in ("bear", "base", "bull")},
                       seeds_agree=not any(a.startswith("seeds_disagree") for a in v.get("annotations", [])),
                       seed_base=v.get("seed_base"))
        rep = dict(row, ticker=t, tasks={k: _claims((an.get("tasks") or {}).get(k)) for k in TASKS},
                   valuation=({k: v.get(k) for k in ("options", "numbers", "neutral", "directions", "departures", "evidence",
                                                     "annotations", "reverts", "of_record", "year", "unknowns")} if valued else None),
                   authority="diagnostic: paper only, not investment advice")
        out[t] = (row, rep)
    return out


def quote_units(rows, stocks):
    """Values in the unit that trades: equity value / (market cap / price). A depositary share (ADS) can be a fraction or a multiple of
    the filed ordinary share, so a value per filed share is never compared with the quoted price directly."""
    for t, (row, rep) in rows.items():
        q = stocks.get(t) or {}
        price, mcap = q.get("price"), q.get("marketCap")
        if not row.get("equity_value") or not price or not mcap or not row.get("filed_shares"):
            continue
        quoted = mcap / price
        k = row["filed_shares"] / quoted
        k = 1.0 if 2 / 3 <= k <= 1.5 else k          # only a unit mismatch (an ADS ratio) rescales; buybacks and dilution do not
        vals = {n: x * k for n, x in row["value_per_filed_share"].items()}
        upd = dict(value_base=vals["base"], value_bear=vals["bear"], value_bull=vals["bull"], price_at_publish=price,
                   market_cap_at_publish=mcap, upside=row["equity_value"] / mcap - 1,
                   share_unit_note=(f"filed shares {row['filed_shares']:,.0f} against {quoted:,.0f} quoted (x{1 / k:.3g}); values are per "
                                    f"quoted share") if k != 1.0 else None,
                   far_from_price=not 0.5 <= row["equity_value"] / mcap <= 2.0)
        row.update(upd)
        rep.update(upd)


def books(T):
    """m3o_books.json: the code book (engine series F) and Qwen's book (FQ) of formation T as equal-weight targets in percent, for the
    screener's daily ledgers code_book and qwen_book (and the KIS mirror). Every non-excluded book name is one slot of 100/n; Qwen's
    book holds the names whose last FQ action is enter or enter_after_pending, the rest of its slots are cash (as the engine)."""
    excluded = set(book_paths.operator_excluded())
    seq = {}
    for a in _jsonl(M3O / "ledger" / "actions.jsonl"):
        if a.get("formation_T") == T and a.get("arm") in ("F", "FQ") and a["ticker"] not in excluded:
            seq.setdefault(a["arm"], {}).setdefault(a["ticker"], []).append(a["action"])
    slots = sorted(t for t, v in seq.get("F", {}).items() if "enter" in v)
    w = round(100.0 / len(slots), 6) if slots else 0.0
    qwen = sorted(t for t, v in seq.get("FQ", {}).items() if t in slots and v[-1] in ("enter", "enter_after_pending"))
    m = json.loads((M3O / "inputs" / f"formation_{T}.json").read_text(encoding="utf-8"))
    return {"schema": "m3o_books_v1", "formation": T, "decision_time_utc": m["decision_time_utc"], "slots": len(slots),
            "generated_at": m["decision_time_utc"],   # the targets' age for the KIS freshness guard (G4) is the formation's decision time
            "note": "Monthly books: code_book = the screener's code-only A0 book; qwen_book = the same slots after Qwen's filing check "
                    "(a name with a material event is held as cash). Equal weight per slot. Paper only.",
            "books": {"code_book": {t: w for t in slots}, "qwen_book": {t: w for t in qwen}}}


def latest_formation():
    maps = sorted(p.stem.split("_", 1)[1] for p in (M3O / "inputs").glob("formation_????-??-??.json"))
    return maps[-1]


def build():
    T = latest_formation()
    rows = formation_rows(T)
    for p in sorted(ONDEMAND.glob("*.json")) if ONDEMAND.exists() else []:   # on-demand runs win when newer
        rep = json.loads(p.read_text(encoding="utf-8"))
        t = rep["ticker"]
        if t not in rows or rep["date"] > rows[t][0]["date"]:
            rows[t] = ({k: v for k, v in rep.items() if k not in ("tasks", "valuation", "ticker", "authority")}, rep)
    s = json.loads((paths.resolve("screener_data_dir") / "stocks.json").read_text(encoding="utf-8"))
    s = s if isinstance(s, list) else s.get("stocks", s)
    quote_units(rows, {r["symbol"]: r for r in s if isinstance(r, dict) and r.get("symbol")})
    rep_dir = OUT / "qwen_reports"
    if rep_dir.exists():
        shutil.rmtree(rep_dir)
    rep_dir.mkdir(parents=True)
    for t, (_, rep) in rows.items():
        (rep_dir / f"{t}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")
    ov = {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "formation": T,
          "count": len(rows), "valued_count": sum(r["valued"] for r, _ in rows.values()),
          "note": "Qwen (local model) reading of SEC filings; values per share from code using Qwen's choices, where both seeds agree. "
                  "Paper only.", "tickers": {t: r for t, (r, _) in sorted(rows.items())}}
    (OUT / "qwen_overlay.json").write_text(json.dumps(ov, indent=1, sort_keys=True), encoding="utf-8")
    (OUT / "m3o_books.json").write_text(json.dumps(books(T), indent=1, sort_keys=True), encoding="utf-8")
    print(f"built {len(rows)} names ({ov['valued_count']} valued) from formation {T}", flush=True)
    return ov


def _lock(timeout=200):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} qwen_site".encode())
            os.close(fd)
            return True
        except FileExistsError:
            if time.time() - LOCK.stat().st_mtime > timeout:
                LOCK.unlink(missing_ok=True)
                continue
            time.sleep(2)
    return False


def publish():
    build()
    repo = paths.resolve("screener_publish_repo")
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)  # noqa: E731
    if "stock-screener" not in g("remote", "get-url", "origin").stdout:
        sys.exit("ABORT: the publish clone's origin is not stock-screener")
    if not _lock():
        sys.exit("ABORT: screener_publish.lock held")
    try:
        if g("fetch", "origin", "main").returncode:
            sys.exit("ABORT: fetch failed")
        if g("status", "--porcelain", "--", ":!public/data/qwen_overlay.json", ":!public/data/m3o_books.json", ":!public/data/qwen_reports").stdout.strip():
            sys.exit("ABORT: the publish clone has unexpected local changes")
        if g("checkout", "-B", "main", "origin/main").returncode:
            sys.exit("ABORT: could not reset the publish clone to origin/main")
        data = repo / "public" / "data"
        shutil.copyfile(OUT / "qwen_overlay.json", data / "qwen_overlay.json")
        shutil.copyfile(OUT / "m3o_books.json", data / "m3o_books.json")
        if (data / "qwen_reports").exists():
            shutil.rmtree(data / "qwen_reports")
        shutil.copytree(OUT / "qwen_reports", data / "qwen_reports")
        for f in [data / "qwen_overlay.json", data / "m3o_books.json", *sorted((data / "qwen_reports").glob("*.json"))]:
            json.loads(f.read_text(encoding="utf-8"))
        g("add", "-A", "public/data/qwen_overlay.json", "public/data/m3o_books.json", "public/data/qwen_reports")
        if g("diff", "--cached", "--check").returncode:
            sys.exit("ABORT: conflict markers in staged content")
        if g("diff", "--cached", "--quiet").returncode == 0:
            print("qwen site files unchanged: nothing to push", flush=True)
            return
        if g("-c", "commit.gpgsign=false", "commit", "-m", "qwen analysis: site update").returncode:
            sys.exit("ABORT: commit failed")
        for attempt in range(5):
            g("fetch", "origin", "main")
            if g("rebase", "origin/main").returncode:
                g("rebase", "--abort")
                sys.exit("ABORT: rebase conflict against origin/main")
            if g("push", "origin", "main").returncode == 0:
                print("pushed qwen site files", g("rev-parse", "--short", "HEAD").stdout.strip(), flush=True)
                return
            time.sleep(4)
        sys.exit("ABORT: push failed after 5 attempts")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    {"build": build, "publish": publish}[sys.argv[1]]()

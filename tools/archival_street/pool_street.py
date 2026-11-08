"""pool_street.py - S1-2 (WO_street_S1_build deliverable 3): the census pool of the Qwen-versus-analysts test at T = 2026-06-15T21:00:00Z.

    python tools/archival_street/pool_street.py --screener-repo <stock-screener development checkout> [--target 100] [--offline]
                                                [--limit N] [--coe-dir DIR]

Writes <rs2_state_dir>/paper_books/m3o/value/archival_2026-06-15/pool.json (names, CIKs, S0 rows and the Street's fields are data: they
stay in the private rs2-state, never in this public repository; never overwritten) and prints the counts and the file's sha256.
`--limit N` processes the first N drawn names and writes nothing (a smoke). No forecast-test exclusion is applied: no realised year, no
release rule, no base-year window.

STAGES (a name leaves at the first it fails, with its reason):
 frame   the Street snapshot public/data/analyst_coverage.json at screener commit STREET_COMMIT (2026-06-14 14:25 UTC), read through git:
         analyst_count an integer >= MIN_ANALYSTS and target_mean_delta_pct a finite number, else leaves (few_analysts / no_target).
 cik     SEC company_tickers.json through qwen_c.sec_store (J2's ticker_map; today's copy: survivor-only, recorded): the ticker as
         written, else with '.' as '-'; unmapped leaves (no_cik); several snapshot tickers of one CIK make one company (the first ticker
         in sorted order), the others leave as duplicate_company.
 draw    sha256(DRAW_KEY + CIK) order; names are processed until TARGET pass every stage (a census of that prefix).
 sec_documents  companyfacts and submissions at T (J2's get_doc into the store, facts.fetch).
 price   the Yahoo close of SESSION, split-unadjusted with Yahoo's split record after T (K2's closes_at_T, the session a parameter).
 shares  the latest dei:EntityCommonStockSharesOutstanding filed by SESSION (K2's rule, the session a parameter); none: leaves.
 cap     close x shares >= MIN_CAP.
 sector  sector, industry and country of the row in public/data/stocks.json at FRAME_COMMIT (2026-06-15 17:33 UTC, the last commit
         before T: point in time); no row or no sector: leaves.
 family  value_family.family at T, kept as tools/paper_books/formation_value.py keeps it: the census's family is recorded for every name
         and passed to run.prepare unchanged; prepare itself refuses a family outside run.ROUTED + run.FINANCIAL (family_not_routed), so
         the financial route is valued as in a live formation and every other family leaves at prepare with that code.
 prepare qwen_c.value.run.prepare at T, offline on the stored documents, with the census family, the cap above, and the pinned cost of
         equity (RS2_ARCHIVAL_COE_DIR = --coe-dir, default archival_2026-06-15/coe_pinned): a DeskRefusal leaves with its code. A
         result without the stamps coe_archival_pinned and coe_external_premium stops the build (the pinned set was not in effect).
 pool    the rest. Each pool name carries the S0 row K2 writes (symbol, name, sector, industry, country, price, marketCap,
         Last_Updated) and the snapshot's fields for the name (`street`).
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "tools" / "archival_j2"), str(ROOT / "tools" / "archival_k2"), str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import pool as P  # noqa: E402  J2's pool: get_doc, ticker_map, default_store, code_state
import pool_k2 as K  # noqa: E402  K2's closes_at_T and shares_at_T, given this session
import value_family  # noqa: E402
from qwen_c import sec_store  # noqa: E402
from qwen_c.value import coe, desk, facts, run  # noqa: E402

POOL_VERSION = "s1.pool.v1"
T_STR = "2026-06-15T21:00:00Z"
T = datetime(2026, 6, 15, 21, 0, 0, tzinfo=timezone.utc)
SESSION = "2026-06-15"                          # T is 17:00 ET: the close of 2026-06-15 is known at T
STREET_COMMIT = "b2df4ec923d"
STREET_PATH = "public/data/analyst_coverage.json"
FRAME_COMMIT = "9bed48e32cf"
STOCKS_PATH = "public/data/stocks.json"
MIN_ANALYSTS = 3
MIN_CAP = 300e6
DRAW_KEY = "S1:2026-06-15:"
PRICE_START = "2026-06-08"
OUT = book_paths.books() / "m3o" / "value" / "archival_2026-06-15"


def git_blob(repo, commit, path):
    """(parsed JSON, full commit, blob sha) of path at commit, read through git (never the working tree)."""
    full = P.git_out(repo, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    blob = P.git_out(repo, "rev-parse", f"{full}:{path}").decode().strip()
    return json.loads(P.git_out(repo, "show", f"{full}:{path}").decode("utf-8-sig")), full, blob


def frame_stage(snapshot):
    """([(ticker, record)] kept, [left record]) of the Street snapshot {ticker: record}: analyst_count an int >= MIN_ANALYSTS (a bool is not
    a count) and target_mean_delta_pct a finite number (0.0 is a value)."""
    kept, left = [], []
    for t in sorted(snapshot):
        r = snapshot[t] if isinstance(snapshot[t], dict) else {}
        n, tgt = r.get("analyst_count"), r.get("target_mean_delta_pct")
        if not (isinstance(n, int) and not isinstance(n, bool) and n >= MIN_ANALYSTS):
            left.append({"ticker": t, "stage": "frame", "reason": "few_analysts", "detail": {"analyst_count": n}})
        elif not (isinstance(tgt, (int, float)) and not isinstance(tgt, bool) and math.isfinite(tgt)):
            left.append({"ticker": t, "stage": "frame", "reason": "no_target", "detail": {"target_mean_delta_pct": tgt}})
        else:
            kept.append((t, r))
    return kept, left


def cik_stage(kept, tmap):
    """([company], [left record]): a company per CIK, the first snapshot ticker in sorted order; '.' tried as '-' when unmapped."""
    companies, left, by_cik = [], [], {}
    for t, r in sorted(kept, key=lambda x: x[0]):
        hit = tmap.get(t.upper()) or tmap.get(t.upper().replace(".", "-"))
        if not hit:
            left.append({"ticker": t, "stage": "cik", "reason": "no_cik", "detail": "not in SEC company_tickers.json", "street": r})
            continue
        if hit[0] in by_cik:
            by_cik[hit[0]]["other_tickers"].append(t)
            left.append({"ticker": t, "cik": hit[0], "stage": "duplicate_company", "reason": "duplicate_company",
                         "detail": f"CIK of {by_cik[hit[0]]['ticker']}", "street": r})
            continue
        by_cik[hit[0]] = {"ticker": t, "cik": hit[0], "sec_title": hit[1], "street": r, "other_tickers": []}
        companies.append(by_cik[hit[0]])
    return companies, left


def draw_order(companies):
    return sorted(companies, key=lambda c: hashlib.sha256((DRAW_KEY + c["cik"]).encode()).hexdigest())


def s0_row(ticker, sec_name, row, close, cap):
    """K2's S0 row (packet.S0_FIELDS keys), sector/industry/country from the point-in-time stocks.json row."""
    return {"symbol": ticker, "name": sec_name, "sector": row.get("sector"), "industry": row.get("industry"), "country": row.get("country"),
            "price": round(close, 4), "marketCap": round(cap), "Last_Updated": SESSION}


def prepare_at_T(cik, sector, cap, family, store, coe_dir):
    """("ok", None, coe provenance) when run.prepare succeeds at T with the pinned cost of equity, else ("refused", "code: detail", None)."""
    old = os.environ.get(coe.ARCHIVAL_ENV)
    os.environ[coe.ARCHIVAL_ENV] = str(coe_dir)
    try:
        out = run.prepare({"decision_time_utc": T_STR}, cik, sector, cap, online=False, family=family, root=store)
    except desk.DeskRefusal as e:
        return "refused", f"{e.code}: {e}"[:400], None
    finally:
        if old is None:
            os.environ.pop(coe.ARCHIVAL_ENV, None)
        else:
            os.environ[coe.ARCHIVAL_ENV] = old
    r, prov = out[4], out[5]
    if not {coe.ARCHIVAL_STAMP, coe.EXTERNAL_STAMP} <= set(prov.get("stamps") or []):
        raise SystemExit(f"STOP: run.prepare's cost of equity lacks the pinned/external stamps: {prov.get('stamps')}")
    return "ok", None, {"r": r, "rf": prov["rf"], "g_anchor": prov["g_anchor"], "loading_adjusted": prov["loading_adjusted"],
                        "premium": prov["closure_erp"], "stamps": prov["stamps"], "manifest_sha256": prov["archival"]["manifest_sha256"]}


def one(c, store, offline, px, px_why, stocks, coe_dir):
    """The record of one drawn company (stages sec_documents .. prepare)."""
    out = dict(c)
    t, cik = c["ticker"], c["cik"]
    try:
        for url in (facts.companyfacts_url(cik), facts.submissions_url(cik)):
            P.get_doc(url, store, offline)
        cf, subs, prov = facts.fetch(cik, T, online=False, root=store)
    except (sec_store.StoreError, ValueError) as e:
        return dict(out, stage="sec_documents", reason=type(e).__name__, detail=str(e)[:300])
    out["sec_documents"] = {k: {"sha256": v["sha256"], "fetched_at": v["fetched_at"]} for k, v in prov.items()}
    out["sec_name"] = subs.get("name")
    if t not in px:
        return dict(out, stage="price", reason=px_why.get(t, "no_close"))
    close, factor = px[t]
    sh = K.shares_at_T(cf, session=SESSION)
    if not sh:
        return dict(out, stage="shares", reason="no_shares_filed_by_T", detail={"close": close})
    out["shares_at_T"] = {"value": sh[0], "end": sh[1], "filed": sh[2]}
    cap = close * sh[0]
    if cap < MIN_CAP:
        return dict(out, stage="cap", reason="below_min_cap", detail={"close": close, "shares": sh[0], "cap": cap})
    row = stocks.get(t) or {}
    if not row.get("sector"):
        return dict(out, stage="sector", reason="no_frame_row" if not row else "no_sector", detail=FRAME_COMMIT)
    sector = row["sector"]
    s0 = s0_row(t, subs.get("name") or c.get("sec_title"), row, close, cap)
    out.update(sector=sector, market_cap=cap, s0_row=s0,
               s0_stamps=["sector_point_in_time_frame"] + ([f"price_split_unadjusted_x{factor:g}"] if factor != 1 else []))
    fam = value_family.family(cf, subs, facts.annual_facts(cf, subs, T), T)
    out.update(family=fam["family"], family_reason=fam["reason"], sic=fam["sic"], family_version=fam["version"])
    status, why, cprov = prepare_at_T(cik, sector, cap, fam["family"], store, coe_dir)
    if status != "ok":
        return dict(out, stage="prepare", reason=why.split(":")[0], detail=why)
    return dict(out, coe_at_prepare=cprov, stage=None, reason=None, detail=None)


def counts(names, frame_left, cik_left, snapshot_n):
    st = Counter(n.get("stage") or "pool" for n in names)
    return {"snapshot_rows": snapshot_n, "frame_left": dict(Counter(n["reason"] for n in frame_left)),
            "cik_left": dict(Counter(n["reason"] for n in cik_left)), "drawn": len(names), "stages": dict(st),
            "prepare_refusals": dict(Counter(n["reason"] for n in names if n.get("stage") == "prepare")),
            "pool_by_family": dict(Counter(n["family"] for n in names if n.get("stage") is None))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--screener-repo", help="a screener clone holding both commits (default: paths.py screener_publish_repo)")
    ap.add_argument("--store", help="the qwen_c.sec_store root (default: J2's, <main checkout>/cache/archival_j2/sec_raw)")
    ap.add_argument("--coe-dir", help="the pinned cost-of-equity set (default: archival_2026-06-15/coe_pinned)")
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--limit", type=int, help="the first N drawn names only (a smoke; nothing is written)")
    a = ap.parse_args(argv)
    repo = Path(a.screener_repo) if a.screener_repo else book_paths.screener_repo()
    store = Path(a.store) if a.store else P.default_store()
    coe_dir = Path(a.coe_dir) if a.coe_dir else OUT / "coe_pinned"
    if not (coe_dir / "manifest.json").exists():
        sys.exit(f"STOP: no pinned cost-of-equity set at {coe_dir} (tools/archival_street/pin_coe.py)")
    out_path = OUT / "pool.json"
    if not a.limit and out_path.exists():
        sys.exit(f"STOP: {out_path} exists; a pool is never overwritten")
    snapshot, s_full, s_blob = git_blob(repo, STREET_COMMIT, STREET_PATH)
    stocks_raw, f_full, f_blob = git_blob(repo, FRAME_COMMIT, STOCKS_PATH)
    rows = stocks_raw if isinstance(stocks_raw, list) else stocks_raw.get("stocks", [])
    stocks = {r["symbol"]: r for r in rows if isinstance(r, dict) and r.get("symbol")}
    kept, frame_left = frame_stage(snapshot)
    tmap, tick_rec = P.ticker_map(store, a.offline)
    companies, cik_left = cik_stage(kept, tmap)
    drawn = draw_order(companies)
    if a.limit:
        drawn = drawn[: a.limit]
    px, px_why = K.closes_at_T(sorted(c["ticker"] for c in drawn), session=SESSION, start=PRICE_START,
                               end=(datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat())   # every split after T to today
    names, passed = [], 0
    for c in drawn:
        if passed >= a.target:
            break
        rec = one(c, store, a.offline, px, px_why, stocks, coe_dir)
        names.append(rec)
        if rec.get("stage") is None:
            passed += 1
        print(rec["ticker"], rec.get("stage") or "POOL", rec.get("reason") or "", f"({passed}/{a.target})", flush=True)
    c = counts(names, frame_left, cik_left, len(snapshot))
    c["reached_target"] = passed >= a.target
    print(json.dumps(c, indent=1, default=str))
    if a.limit:
        print("--limit: a smoke, nothing written")
        return 0
    manifest = json.loads((coe_dir / "manifest.json").read_bytes())
    body = {"version": POOL_VERSION, "T": T_STR, "session": SESSION, "target": a.target, "min_cap": MIN_CAP, "min_analysts": MIN_ANALYSTS,
            "draw_key": DRAW_KEY, "street": {"commit": s_full, "path": STREET_PATH, "blob": s_blob},
            "frame": {"commit": f_full, "path": STOCKS_PATH, "blob": f_blob}, "tickers": tick_rec, "store": str(store),
            "coe_pinned": {"dir": str(coe_dir), "manifest_sha256": hashlib.sha256((coe_dir / "manifest.json").read_bytes()).hexdigest(),
                           "premium": manifest.get("premium")},
            "code": dict(P.code_state(), pool=POOL_VERSION, facts=facts.FACTS_VERSION, inputs=run.inputs.INPUTS_VERSION,
                         family=value_family.FAMILY_VERSION, coe=coe.ARCHIVAL_VERSION),
            "counts": c, "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "survivorship": "SEC company_tickers.json of the build date: companies delisted since T are absent (cik stage)",
            "names": names, "frame_left": frame_left, "cik_left": cik_left}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(body, indent=1, sort_keys=True, default=str).encode("utf-8")
    tmp = out_path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, out_path)
    print(f"wrote {out_path} sha256 {hashlib.sha256(data).hexdigest()}")
    if not c["reached_target"]:
        print(f"STOP: the pool reached {passed} of {a.target} names")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

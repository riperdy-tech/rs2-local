"""pool_k2.py - K2-0: the census pool of the K2 year-1 forecast holdout at T = 2025-10-01T21:00:00Z (K2 v0.2 section 8, ruling 1-8).

    python tools/archival_k2/pool_k2.py [--target 140] [--offline]

Writes <rs2_state_dir>/paper_books/m3o/value/archival_2025-10-01/pool.json (names, CIKs and S0 rows are data: they stay in the private
rs2-state, never in this public repository) and prints the counts and the file's sha256. Reads no forecast; the realised year 1 is read
only by J2's exclusions (tools/archival_j2/pool.py `one`), which this tool reuses unchanged with its T set to K2's.

STAGES (a name leaves at the first it fails, with its reason):
 U1 tickers: SEC company_tickers.json (today's copy: survivor-only, disclosed); one company per CIK (the first ticker in sorted order).
 U2 j2: every CIK in J2's two pools (archival_2025-12-31, archival_2025-12-31_nd) leaves before the draw (ruling 5).
 U3 frames: dei:EntityCommonStockSharesOutstanding at CY2025Q2I and an annual revenue fact for CY2024 (Revenues or
    RevenueFromContractWithCustomerExcludingAssessedTax), one SEC frames call each: a company in neither leaves.
 U4 price: the Yahoo close of the last NYSE session at or before T (the 2025-10-01 close; T is 17:00 ET), split-unadjusted with
    Yahoo's split record after T; frames shares x that close >= MIN_CAP, else leaves (a prefilter only).
 draw: sha256("K2:2025-10-01:" + CIK) order, processed until TARGET names pass every stage (a census of that prefix).
 S0: market cap = the close x the latest dei:EntityCommonStockSharesOutstanding filed at or before T (companyfacts); >= MIN_CAP else
    leaves (stage cap_at_T); sector and industry from the Yahoo profile (today's, stamped sector_not_point_in_time); country = the
    frames `loc`.
 then J2's `one` (stages 3-8: documents, family, base-year window, prepare, run rate, exclusions) with the window FY0_WINDOW.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "tools" / "archival_j2"), str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import pool as P  # noqa: E402  J2's pool: its stage functions read the module's T
from qwen_c import sec_store  # noqa: E402
from qwen_c.value import facts  # noqa: E402

POOL_VERSION = "k2.pool.v1"
T_STR = "2025-10-01T21:00:00Z"
T = datetime(2025, 10, 1, 21, 0, 0, tzinfo=timezone.utc)
SESSION = "2025-10-01"
FY0_WINDOW = ("2024-10-02", "2025-06-30")      # ruling 4: year 1 (the fiscal year containing T) ends 2025-10-01 .. 2026-06-30
MIN_CAP = 300e6
DRAW_KEY = "K2:2025-10-01:"
FRAMES = {"shares": "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY2025Q2I.json",
          "rev_a": "https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2024.json",
          "rev_b": "https://data.sec.gov/api/xbrl/frames/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/USD/CY2024.json"}
J2_POOLS = ("archival_2025-12-31", "archival_2025-12-31_nd")
OUT = book_paths.books() / "m3o" / "value" / "archival_2025-10-01"
P.T, P.T_STR = T, T_STR                         # J2's stages at K2's T


def frame(url, store, offline):
    return json.loads(P.get_doc(url, store, offline))["data"]


def j2_ciks():
    out = set()
    for d in J2_POOLS:
        pool = json.loads((book_paths.books() / "m3o" / "value" / d / "pool.json").read_text(encoding="utf-8"))
        out |= {str(n["cik"]).zfill(10) for n in pool["pool"]}
    return out


def closes_at_T(tickers, rounds=4):
    """({ticker: (raw close of SESSION, split factor after T)}, {ticker: why}) from Yahoo: Close is split-adjusted, so a split after T is
    undone. A ticker with no row is retried (smaller chunks, a pause between rounds: Yahoo rate-limits); after `rounds` it is reported
    with why, never dropped silently: `no_session_row` when Yahoo returned the ticker's history without the 2025-10-01 session."""
    import time
    out, why, todo = {}, {}, list(tickers)
    for k in range(rounds):
        if not todo:
            break
        if k:
            time.sleep(30 * k)
        got = _closes(todo, 200 if k == 0 else 25, why)
        out.update(got)
        todo = [t for t in todo if t not in got and why.get(t) != "no_session_row"]
    for t in todo:
        why[t] = why.get(t) or "yahoo_no_data_after_retries"
    return out, why


def _closes(tickers, size, why):
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), size):
        chunk = tickers[i:i + size]
        df = yf.download(chunk, start="2025-09-24", end="2026-11-08", auto_adjust=False, actions=True, progress=False,
                         group_by="ticker", threads=True)
        for t in chunk:
            try:
                sub = df[t] if len(chunk) > 1 else df
                c = sub["Close"].dropna()
                if c.empty:
                    continue                                              # no data at all: retried
                c = c[c.index.strftime("%Y-%m-%d") <= SESSION]
                if c.empty or c.index[-1].strftime("%Y-%m-%d") != SESSION:
                    why[t] = "no_session_row"
                    continue
                splits = sub.get("Stock Splits")
                factor = 1.0
                if splits is not None:
                    for d, s in splits.items():
                        if d.strftime("%Y-%m-%d") > SESSION and s and s > 0:
                            factor *= float(s)
                out[t] = (float(c.iloc[-1]) * factor, factor)
            except (KeyError, IndexError, TypeError):
                continue
    return out


def shares_at_T(cf):
    """(value, end, filed) of the latest dei:EntityCommonStockSharesOutstanding filed at or before T, summed over share classes of one
    filing and date; None when none is filed."""
    rows = [r for u in ((cf.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).values()
            for r in u if r.get("filed") and r["filed"] <= SESSION]
    if not rows:
        return None
    last = max(rows, key=lambda r: (r["filed"], r["end"]))
    tot = sum(r["val"] for r in rows if r.get("accn") == last.get("accn") and r["end"] == last["end"])
    return tot, last["end"], last["filed"]


def screener_sectors():
    """{ticker: (sector, industry)} from the screener's current stocks.json (screener-publish HEAD): the taxonomy the cost-of-equity
    anchors use. Today's, not point in time (stamped)."""
    import subprocess
    repo = book_paths.screener_repo()
    raw = subprocess.run(["git", "-C", str(repo), "show", "HEAD:public/data/stocks.json"], capture_output=True, check=True).stdout
    return {r["symbol"]: (r.get("sector"), r.get("industry")) for r in json.loads(raw.decode("utf-8-sig")) if isinstance(r, dict)
            and r.get("symbol") and r.get("sector")}


def profile(ticker, tries=4):
    """(sector, industry) from the Yahoo profile, retried with a pause (rate limits); (None, None) after the last try."""
    import time
    import yfinance as yf
    for k in range(tries):
        try:
            i = yf.Ticker(ticker).info or {}
            if i.get("sector"):
                return i.get("sector"), i.get("industry")
        except Exception:  # noqa: BLE001  rate limit or network: retried
            pass
        time.sleep(10 * (k + 1))
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=int, default=140)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    store = P.default_store()
    tmap, tick_rec = P.ticker_map(store, a.offline)
    by_cik = {}
    for t in sorted(tmap):
        cik, title = tmap[t]
        by_cik.setdefault(cik, (t, title))
    left = Counter()
    j2 = j2_ciks()
    fr = {k: frame(u, store, a.offline) for k, u in FRAMES.items()}
    shares = {str(d["cik"]).zfill(10): d for d in fr["shares"]}
    has_rev = {str(d["cik"]).zfill(10) for k in ("rev_a", "rev_b") for d in fr[k]}
    cands = []
    for cik, (t, title) in by_cik.items():
        if cik in j2:
            left["U2_j2_pool"] += 1
        elif cik not in shares or cik not in has_rev:
            left["U3_frames"] += 1
        else:
            cands.append((cik, t, title))
    px, px_why = closes_at_T(sorted(t for _, t, _ in cands))
    pre = []
    for cik, t, title in cands:
        if t not in px:
            left[f"U4_{px_why.get(t, 'no_close')}"] += 1
        elif px[t][0] * shares[cik]["val"] < MIN_CAP:
            left["U4_cap_prefilter"] += 1
        else:
            pre.append((cik, t, title))
    pre.sort(key=lambda x: hashlib.sha256((DRAW_KEY + x[0]).encode()).hexdigest())
    names, passed = [], 0
    sectors = screener_sectors()
    for cik, t, title in pre:
        if passed >= a.target:
            break
        try:
            cf, subs, _ = facts.fetch(int(cik), T, online=not a.offline, root=store)
        except (sec_store.StoreError, ValueError) as e:
            names.append({"ticker": t, "cik": cik, "stage": "sec_documents", "reason": type(e).__name__}); continue
        sh = shares_at_T(cf)
        close, factor = px[t]
        cap = close * sh[0] if sh else None
        if not cap or cap < MIN_CAP:
            names.append({"ticker": t, "cik": cik, "stage": "cap_at_T", "reason": "below_min_cap" if sh else "no_shares_filed_by_T",
                          "detail": {"close": close, "shares": sh}}); continue
        if t in sectors:
            (sector, industry), sec_src = sectors[t], "sector_from_screener_today"
        else:
            (sector, industry), sec_src = profile(t), "sector_from_yahoo_today"
        if not sector:
            names.append({"ticker": t, "cik": cik, "stage": "s0_profile", "reason": "no_sector_from_yahoo"}); continue
        s0 = {"symbol": t, "name": subs.get("name") or title, "sector": sector, "industry": industry,
              "country": shares[cik].get("loc"), "price": round(close, 4), "marketCap": round(cap), "Last_Updated": SESSION}
        rec = P.one({"ticker": t, "cik": cik, "frame_name": title, "sector": sector, "market_cap": cap}, store, a.offline, window=FY0_WINDOW)
        rec.update(s0_row=s0, s0_stamps=["sector_not_point_in_time", sec_src] + ([f"price_split_unadjusted_x{factor:g}"] if factor != 1 else []),
                   shares_at_T={"value": sh[0], "end": sh[1], "filed": sh[2]})
        names.append(rec)
        if rec.get("stage") is None:
            passed += 1
        print(t, rec.get("stage") or "POOL", rec.get("reason") or "", f"({passed}/{a.target})", flush=True)
    st = Counter(n.get("stage") or "pool" for n in names)
    body = {"version": POOL_VERSION, "T": T_STR, "fy0_window": FY0_WINDOW, "min_cap": MIN_CAP, "draw_key": DRAW_KEY, "target": a.target,
            "tickers": tick_rec, "frames": {k: {"url": u, "sha256": sec_store.latest_receipt(u, root=store)["sha256"]} for k, u in FRAMES.items()},
            "universe_left": dict(left), "prefilter_kept": len(pre), "drawn": len(names), "stages": dict(st),
            "code": P.code_state(), "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "survivorship": "SEC company_tickers.json of the build date: companies delisted since T are absent", "names": names}
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps(body, indent=1, sort_keys=True, default=str).encode("utf-8")
    (OUT / "pool.json").write_bytes(data)
    print(json.dumps({"universe_left": dict(left), "prefilter_kept": len(pre), "drawn": len(names), "stages": dict(st)}),
          "sha256", hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()

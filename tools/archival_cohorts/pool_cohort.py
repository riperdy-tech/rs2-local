"""pool_cohort.py - the survivor-free census pool of one next-quarter cohort at T (PREREG_cohorts_nextq v0.1 section 2 "Pool" and "Draw",
section 5 item 2).

    python tools/archival_cohorts/pool_cohort.py --t 2025-10-01 [--target 125] [--offline]

Writes <rs2_state_dir>/paper_books/m3o/value/archival_cohort_<T>/pool.json in pool_k2's schema (body["names"]; the census is the names
with stage None, each with cik, sector, market_cap, family and the S0 row), so k2_run.census/packets and J2's runner read it unchanged.
Names, CIKs and S0 rows are data: they stay in the private rs2-state, never in this public repository. Prints the counts per stage and the
file's sha256. T is 21:00Z of the date given. Every universe CIK appears in names exactly once, with the stage where it stopped.

UNIVERSE (survivor-free; pre-draw stages run over every CIK):
 U1 universe   every CIK with a 10-Q or 10-K (originals) filed in the WINDOW_DAYS before T (filing date T-200d .. T's date), read from
               EDGAR's quarterly full-index form.idx through qwen_c.sec_store (each file pinned by sha256). Not today's ticker list: a
               company delisted after T stays in. A CIK with a 20-F, 40-F or 6-K and no 10-Q/10-K in the window is segment "foreign"
               (reported outside the primary, never dropped); the rest are segment "primary".
 ticker        today's ticker: SEC company_tickers.json (J2's ticker_map; one ticker per CIK, the first in sorted order, K2's rule); a CIK
               absent from it is looked up in its submissions JSON's `tickers` (first in sorted order). Neither: ticker null, stamped
               no_ticker_today, kept. A submissions document that cannot be had leaves at stage `ticker` with the error.
 no_price_at_T the Yahoo close of SESSION (the last NYSE session at or before T), split-unadjusted (pool_k2.closes_at_T). No ticker or no
               close: stage no_price_at_T with the reason (no_ticker_today, no_session_row, yahoo_no_data_after_retries). The count is
               the survivor gap measured, not hidden.
 below_min_cap the prefilter cap: the close x dei:EntityCommonStockSharesOutstanding in the SEC frame CY<q>I, q the last calendar
               quarter ending 45 days or more before T (K2's CY2025Q2I at 2025-10-01); < MIN_CAP leaves. Where the frame has no row
               the cap is measured in the walk (below).
DRAW (cells sector x cap tercile; quotas from the 10-30 book):
 book          <books>/m3o/value/formation_2026-10-30.json, its names in the valued routes (run.ROUTED), their sector and market_cap (stocks.json at the formation's output
               commit). Tercile cutoffs: the largest book cap of each of the book's first two thirds by rank. Cell quotas: target x the
               book's cell share, largest remainder (ties by cell name), summing to target.
 walk          the names left, in ascending sha256(f"{ticker or CIK}|{T date}") order. Without a frame cap: close x pool_k2.shares_at_T
               of the companyfacts (no shares filed: stage no_cap_at_T; < MIN_CAP: below_min_cap). Tercile by the cutoffs. Sector:
               stocks.json at the last screener commit before T (point in time; none when the clone's history
               starts after T), else today's screener (pool_k2.screener_sectors), else
               the Yahoo profile today (pool_k2.profile); none: stage no_sector. A cell with no quota, or one already full, gives stage
               not_drawn (cell_quota_zero, cell_full); once every cell is full the rest are not_drawn (draw_complete).
 census        a drawn name: companyfacts and submissions at T (stage sec_documents); market cap = the close x shares_at_T (K2's S0;
               < MIN_CAP or none: stage cap_at_T); then J2's `one` unchanged (family, base-year window, prepare, run rate,
               exclusions) with J2's T set to T and the window FY0_WINDOW: K2's rule shifted, the base fiscal year ending T - 1 year + 1 day
               .. T - 3 months - 1 day, so that year 1 is the fiscal year containing T. Only a primary name that passes fills its cell's
               quota; a foreign name is censused and reported, outside the quota.
"""
import argparse
import calendar
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "tools" / "archival_j2"), str(ROOT / "tools" / "archival_k2"), str(ROOT / "tools" / "archival_street"),
          str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import pool as P  # noqa: E402  J2's pool: get_doc, ticker_map, default_store, code_state, one (its stages read the module's T)
import pool_k2 as K  # noqa: E402  closes_at_T, shares_at_T, screener_sectors, profile, MIN_CAP
import pool_street as S  # noqa: E402  git_blob
from qwen_c import packet, sec_store  # noqa: E402
from qwen_c.value import facts, run  # noqa: E402

POOL_VERSION = "cohort.pool.v1"
WINDOW_DAYS = 200
PRIMARY_FORMS = ("10-Q", "10-K")
FOREIGN_FORMS = ("20-F", "40-F", "6-K")
INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx"
FRAME_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{y}Q{q}I.json"
FRAME_LAG_DAYS = 45
MIN_CAP = K.MIN_CAP
BOOK_T = "2026-10-30"
STOCKS_PATH = "public/data/stocks.json"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- dates

def at(t):
    """(T, T_STR) of the date string t: 21:00Z of that date."""
    d = date.fromisoformat(t)
    T = datetime(d.year, d.month, d.day, 21, 0, 0, tzinfo=timezone.utc)
    return T, T.strftime("%Y-%m-%dT%H:%M:%SZ")


def _months_back(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def fy0_window(t):
    """K2's FY0_WINDOW shifted to T: the base fiscal year ends T - 1 year + 1 day .. T - 3 months - 1 day (year 1 contains T)."""
    d = date.fromisoformat(t)
    return ((_months_back(d, 12) + timedelta(days=1)).isoformat(), (_months_back(d, 3) - timedelta(days=1)).isoformat())


def session_at(t):
    """The last NYSE session at or before T's date (T is 21:00Z, at or after the close)."""
    d = date.fromisoformat(t)
    s = packet._calendar().sessions_in_range((d - timedelta(days=10)).isoformat(), d.isoformat())
    return s[-1].strftime("%Y-%m-%d")


def quarters(start, end):
    """[(year, quarter)] of the calendar quarters touching start .. end (dates)."""
    out, y, q = [], start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def frame_quarter(t):
    """The last calendar quarter whose end is FRAME_LAG_DAYS or more before T's date."""
    d = date.fromisoformat(t)
    y, q = d.year, (d.month - 1) // 3 + 1
    while True:
        end = date(y, 3 * q, calendar.monthrange(y, 3 * q)[1])
        if end + timedelta(days=FRAME_LAG_DAYS) <= d:
            return y, q
        y, q = (y - 1, 4) if q == 1 else (y, q - 1)


# ---------------------------------------------------------------- U1: the universe

def parse_form_idx(text):
    """[(form, company, cik10, date filed)] of an EDGAR form.idx, for the forms this pool reads (none of which holds a space). Columns
    are read from the right (file, date, CIK); the form is the first token; the company is what lies between."""
    out = []
    for line in text.splitlines():
        tok = line.split()
        if len(tok) < 4 or tok[0] not in PRIMARY_FORMS + FOREIGN_FORMS:
            continue
        form, cik, filed, path = tok[0], tok[-3], tok[-2], tok[-1]
        if not (cik.isdigit() and _DATE.match(filed) and path.startswith("edgar/")):
            continue
        out.append((form, " ".join(tok[1:-3]), cik.zfill(10), filed))
    return out


def universe(rows, t):
    """{cik: {cik, name, forms, segment}} of the filers with a form of this pool filed T - WINDOW_DAYS .. T's date; segment primary when
    a 10-Q or 10-K is among them, else foreign. The name is the one of the latest filing."""
    d = date.fromisoformat(t)
    lo, hi = (d - timedelta(days=WINDOW_DAYS)).isoformat(), d.isoformat()
    u = {}
    for form, name, cik, filed in sorted(rows, key=lambda r: r[3]):
        if lo <= filed <= hi:
            r = u.setdefault(cik, {"cik": cik, "forms": set()})
            r["forms"].add(form)
            r["name"] = name
    for r in u.values():
        r["segment"] = "primary" if r["forms"] & set(PRIMARY_FORMS) else "foreign"
        r["forms"] = sorted(r["forms"])
    return u


def index_files(t, store, offline):
    """(rows, [{url, sha256}]) of the form.idx files of the quarters the window touches."""
    d = date.fromisoformat(t)
    rows, rec = [], []
    for y, q in quarters(d - timedelta(days=WINDOW_DAYS), d):
        url = INDEX_URL.format(y=y, q=q)
        rows += parse_form_idx(P.get_doc(url, store, offline).decode("latin-1"))
        rec.append({"url": url, "sha256": sec_store.latest_receipt(url, root=store)["sha256"]})
    return rows, rec


# ---------------------------------------------------------------- the ticker

def by_cik(tmap):
    """{cik: ticker} of J2's ticker_map {ticker: (cik, title)}: the first ticker in sorted order (K2's rule)."""
    out = {}
    for t in sorted(tmap):
        out.setdefault(tmap[t][0], t)
    return out


def ticker_of(cik, tickers, subs_of):
    """(ticker or None, source): company_tickers.json first, else the submissions JSON's tickers (first in sorted order)."""
    if cik in tickers:
        return tickers[cik], "company_tickers"
    got = sorted(str(x).upper() for x in (subs_of(cik).get("tickers") or []) if x)
    return (got[0], "submissions") if got else (None, "submissions")


# ---------------------------------------------------------------- the book's cells

def book_cells(names):
    """(cutoffs, {cell: count}) of the book's names in the valued routes {ticker: {sector, market_cap, family}}: only a family in
    qwen_c.value.run.ROUTED can enter the cohort (J2's `one` stops the rest at stage family), so a quota on the others could never fill;
    the tercile cutoffs are the largest cap of each of the first two thirds by rank, over those names."""
    names = {t: n for t, n in names.items() if n.get("family") in run.ROUTED}
    caps = sorted(n["market_cap"] for n in names.values())
    k = len(caps)
    cut = (max(c for i, c in enumerate(caps) if i * 3 // k == 0), max(c for i, c in enumerate(caps) if i * 3 // k == 1))
    return cut, dict(Counter(cell(n["sector"], tercile(n["market_cap"], cut)) for n in names.values()))


def tercile(cap, cut):
    return 1 if cap <= cut[0] else 2 if cap <= cut[1] else 3


def cell(sector, terc):
    return f"{sector}|T{terc}"


def quotas(counts, target):
    """{cell: quota}: target x the cell's share, floored, the remainder to the largest fractions (ties by cell name); sums to target."""
    n = sum(counts.values())
    raw = {c: target * k / n for c, k in counts.items()}
    q = {c: int(v) for c, v in raw.items()}
    for c in sorted(raw, key=lambda c: (-(raw[c] - q[c]), c))[: target - sum(q.values())]:
        q[c] += 1
    return q


def draw_key(rec, t):
    return hashlib.sha256(f"{rec['ticker'] or rec['cik']}|{t}".encode()).hexdigest()


# ---------------------------------------------------------------- the walk

def walk(cands, quota, cut, cap_of, sector_of, census):
    """(names, fill) of the walk over cands (in draw order): cap_of(rec) -> (cap or None, detail) for a name without a prefilter cap;
    sector_of(rec) -> (sector or None, industry, source); census(rec) -> the record with its stage (None: passed)."""
    fill = {c: 0 for c in quota}
    out = []
    for rec in cands:
        if all(fill[c] >= q for c, q in quota.items()):
            out.append(dict(rec, stage="not_drawn", reason="draw_complete"))
            continue
        if rec.get("cap_prefilter") is None:
            cap, detail = cap_of(rec)
            if cap is None:
                out.append(dict(rec, stage="no_cap_at_T", reason="no_shares_filed_by_T", detail=detail))
                continue
            rec = dict(rec, cap_prefilter=cap, cap_source="companyfacts")
            if cap < MIN_CAP:
                out.append(dict(rec, stage="below_min_cap", reason="below_min_cap"))
                continue
        terc = tercile(rec["cap_prefilter"], cut)
        rec = dict(rec, cap_tercile=terc)
        if not any(fill[c] < q for c, q in quota.items() if c.endswith(f"|T{terc}")):
            out.append(dict(rec, stage="not_drawn", reason="cell_full"))
            continue
        sector, industry, src = sector_of(rec)
        if not sector:
            out.append(dict(rec, stage="no_sector", reason="no_sector", detail=src))
            continue
        c = cell(sector, terc)
        rec = dict(rec, cell=c, sector=sector, industry=industry, sector_source=src)
        if not quota.get(c):
            out.append(dict(rec, stage="not_drawn", reason="cell_quota_zero"))
            continue
        if fill[c] >= quota[c]:
            out.append(dict(rec, stage="not_drawn", reason="cell_full"))
            continue
        r = census(rec)
        out.append(r)
        if r.get("stage") is None and rec["segment"] == "primary":
            fill[c] += 1
        print(rec["ticker"], r.get("stage") or "POOL", r.get("reason") or "", c, f"({fill[c]}/{quota[c]})", flush=True)
    return out, fill


# ---------------------------------------------------------------- the census of a drawn name (K2's S0, then J2's one)

def census(rec, store, offline, T, session, window):
    cik, t = rec["cik"], rec["ticker"]
    try:
        for url in (facts.companyfacts_url(cik), facts.submissions_url(cik)):
            P.get_doc(url, store, offline)
        cf, subs, _ = facts.fetch(cik, T, online=False, root=store)
    except (sec_store.StoreError, ValueError) as e:
        return dict(rec, stage="sec_documents", reason=type(e).__name__, detail=str(e)[:300])
    sh = K.shares_at_T(cf, session=session)
    close, factor = rec["close"], rec["split_factor"]
    cap = close * sh[0] if sh else None
    if not cap or cap < MIN_CAP:
        return dict(rec, stage="cap_at_T", reason="below_min_cap" if sh else "no_shares_filed_by_T", detail={"close": close, "shares": sh})
    s0 = {"symbol": t, "name": subs.get("name") or rec["name"], "sector": rec["sector"], "industry": rec["industry"],
          "country": rec.get("loc"), "price": round(close, 4), "marketCap": round(cap), "Last_Updated": session}
    out = P.one(dict(rec, frame_name=rec["name"], market_cap=cap), store, offline, window=window)
    stamps = ([] if rec["sector_source"] == "sector_screener_at_T" else ["sector_not_point_in_time"]) + [rec["sector_source"]]
    out.update(s0_row=s0, s0_stamps=stamps + ([f"price_split_unadjusted_x{factor:g}"] if factor != 1 else []),
               shares_at_T={"value": sh[0], "end": sh[1], "filed": sh[2]})
    return out


def sectors_at(repo, T_STR):
    """({ticker: row} of stocks.json at the last screener commit before T, that commit, its blob); ({}, None, None) when the clone holds
    no commit before T (every sector then comes from today's sources, stamped sector_not_point_in_time)."""
    commit = P.git_out(repo, "log", "-1", f"--before={T_STR}", "--format=%H", "--", STOCKS_PATH).decode().strip()
    if not commit:
        print(f"no screener commit of {STOCKS_PATH} before {T_STR} in {repo}: sectors from today's screener, then Yahoo", flush=True)
        return {}, None, None
    raw, full, blob = S.git_blob(repo, commit, STOCKS_PATH)
    rows = raw if isinstance(raw, list) else raw.get("stocks", [])
    return {r["symbol"]: r for r in rows if isinstance(r, dict) and r.get("symbol")}, full, blob


def counts(names, target, fill, quota):
    st = Counter(n.get("stage") or "pool" for n in names)
    pool = [n for n in names if n.get("stage") is None]
    return {"universe": len(names), "segment": dict(Counter(n["segment"] for n in names)),
            "no_ticker_today": sum("no_ticker_today" in n["stamps"] for n in names), "stages": dict(st),
            "reasons": {s: dict(Counter(str(n.get("reason")) for n in names if n.get("stage") == s)) for s in st if s != "pool"},
            "passed": len(pool), "passed_primary": sum(n["segment"] == "primary" for n in pool),
            "pool_by_family": dict(Counter(n.get("family") for n in pool)), "reached_target": sum(fill.values()) >= target,
            "fill": fill, "quota": quota}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--t", required=True, help="the decision date (T is 21:00Z of it)")
    ap.add_argument("--target", type=int, default=125)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    t = date.fromisoformat(a.t).isoformat()
    T, T_STR = at(t)
    P.T, P.T_STR = T, T_STR                     # J2's stages at this T (set here, not at import)
    session, window = session_at(t), fy0_window(t)
    store = P.default_store()
    out_dir = book_paths.books() / "m3o" / "value" / f"archival_cohort_{t}"
    # the book's cells and quotas
    book_path = book_paths.books() / "m3o" / "value" / f"formation_{BOOK_T}.json"
    book_raw = book_path.read_bytes()
    cut, book_counts = book_cells(json.loads(book_raw)["names"])
    quota = quotas(book_counts, a.target)
    at_T, s_commit, s_blob = sectors_at(book_paths.screener_repo(), T_STR)
    today = K.screener_sectors()
    # U1 and the ticker
    rows, idx_rec = index_files(t, store, a.offline)
    uni = universe(rows, t)
    tmap, tick_rec = P.ticker_map(store, a.offline)
    tickers = by_cik(tmap)
    recs, left = [], []
    for cik in sorted(uni):
        r = dict(uni[cik], stamps=[])
        try:
            r["ticker"], r["ticker_source"] = ticker_of(cik, tickers, lambda c: json.loads(P.get_doc(facts.submissions_url(c), store, a.offline)))
        except (sec_store.StoreError, ValueError) as e:
            left.append(dict(r, ticker=None, stage="ticker", reason=type(e).__name__, detail=str(e)[:300]))
            continue
        if r["ticker"] is None:
            r["stamps"].append("no_ticker_today")
        recs.append(r)
    print(f"universe {len(uni)} ({Counter(r['segment'] for r in uni.values())}); ticker {sum(r['ticker'] is not None for r in recs)}",
          flush=True)
    # price at T
    px, px_why = K.closes_at_T(sorted({r["ticker"] for r in recs if r["ticker"]}), session=session,
                               start=(date.fromisoformat(session) - timedelta(days=10)).isoformat(),
                               end=(datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat())
    fy, fq = frame_quarter(t)
    frame_url = FRAME_URL.format(y=fy, q=fq)
    frame = {str(d["cik"]).zfill(10): d for d in json.loads(P.get_doc(frame_url, store, a.offline))["data"]}
    cands = []
    for r in recs:
        if not r["ticker"] or r["ticker"] not in px:
            left.append(dict(r, stage="no_price_at_T", reason="no_ticker_today" if not r["ticker"] else px_why.get(r["ticker"], "no_close")))
            continue
        close, factor = px[r["ticker"]]
        fr = frame.get(r["cik"])
        r.update(close=close, split_factor=factor, loc=(fr or {}).get("loc"),
                 cap_prefilter=close * fr["val"] if fr else None, cap_source=f"frame CY{fy}Q{fq}I" if fr else None)
        if fr and r["cap_prefilter"] < MIN_CAP:
            left.append(dict(r, stage="below_min_cap", reason="below_min_cap"))
            continue
        cands.append(r)
    cands.sort(key=lambda r: draw_key(r, t))
    print("before the draw", json.dumps({s: dict(Counter(str(n.get("reason")) for n in left if n["stage"] == s))
                                         for s in sorted({n["stage"] for n in left})}), "walk", len(cands), flush=True)

    def cap_of(r):
        try:
            sh = K.shares_at_T(json.loads(P.get_doc(facts.companyfacts_url(r["cik"]), store, a.offline)), session=session)
        except (sec_store.StoreError, ValueError) as e:
            return None, f"{type(e).__name__}: {str(e)[:200]}"
        return (r["close"] * sh[0], None) if sh else (None, "no dei:EntityCommonStockSharesOutstanding filed by the session")

    def sector_of(r):
        row = at_T.get(r["ticker"]) or at_T.get(r["ticker"].replace("-", ".")) or {}
        if row.get("sector"):
            return row["sector"], row.get("industry"), "sector_screener_at_T"
        if r["ticker"] in today:
            return (*today[r["ticker"]], "sector_from_screener_today")
        s, i = K.profile(r["ticker"])
        return s, i, "sector_from_yahoo_today" if s else "no_sector_at_T_screener_today_or_yahoo"

    walked, fill = walk(cands, quota, cut, cap_of, sector_of, lambda r: census(r, store, a.offline, T, session, window))
    names = walked + sorted(left, key=lambda n: n["cik"])      # the walk in draw order, then the pre-draw leavers
    c = counts(names, a.target, fill, quota)
    body = {"version": POOL_VERSION, "T": T_STR, "session": session, "fy0_window": window, "min_cap": MIN_CAP, "target": a.target,
            "draw_key": "sha256(f'{ticker or cik}|{T date}')", "t": t,
            "universe": {"window_days": WINDOW_DAYS, "primary_forms": PRIMARY_FORMS, "foreign_forms": FOREIGN_FORMS, "index": idx_rec},
            "tickers": tick_rec, "frame": {"url": frame_url, "sha256": sec_store.latest_receipt(frame_url, root=store)["sha256"]},
            "sector_frame": {"commit": s_commit, "path": STOCKS_PATH, "blob": s_blob},
            "book": {"path": str(book_path), "sha256": hashlib.sha256(book_raw).hexdigest(), "names": sum(book_counts.values()),
                     "tercile_cutoffs": cut, "cells": book_counts},
            "quota": quota, "fill": fill, "counts": c, "store": str(store),
            "code": dict(P.code_state(), pool=POOL_VERSION, facts=facts.FACTS_VERSION),
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "survivorship": "universe from EDGAR full-index filings before T; today's tickers only name the price lookup (no_ticker_today, "
                            "no_price_at_T count what that misses)",
            "names": names}
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(body, indent=1, sort_keys=True, default=str).encode("utf-8")
    (out_dir / "pool.json").write_bytes(data)
    print(json.dumps(c, indent=1, default=str))
    print("wrote", out_dir / "pool.json", "sha256", hashlib.sha256(data).hexdigest())
    return 0 if c["reached_target"] else 2


if __name__ == "__main__":
    sys.exit(main())

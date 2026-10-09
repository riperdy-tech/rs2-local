"""What a HOLDOUT run must read (Addenda L3 and L4), and the refusals that keep it from reading anything else.  The development rounds are NOT bound by this module.

  L4  PRICES      the D5 daily raw closes (`rebuild_harness.daily_prices.LazyDailyPriceSource`, a folder), for the valuation price and the daily outcomes: the monthly file is refused.
                  Outcomes: the 12-month horizon, entered at the next session's open (registration v2, section 2).
  L4  DELISTINGS  the D1 event index and the D3 documents through the strict readers (`rebuild_harness.delisting_inputs`).  Addendum P5: a D3 accession that is not on disk leaves its event UNRESOLVED
                  (it stays under the three bounds), counted by `delisting_inputs.missing_document_events` in the configuration check and the readiness report; it does NOT block a run or a freeze.
  M   SURVIVORSHIP  the cover index (`rebuild_harness.survivorship`: public float and share counts of the cover pages, Addendum M1-M2) for the missing-name census, and the monthly raw price file behind a D5 ticker
                  whose history starts late (M6): both are required, so that the three bounds are not identical for want of the companies that left.  `--erp-basis` must be the registered `engine_consistent` (Addenda L1, M).
  L3  CLASSIFICATION  the SIC AS FILED at T from the D2 headers, for every holdout date.  `StrictSicResolver` NEVER falls back to the current-dated `sic_by_cik.json`: a company with no header
                  accepted by T has no SIC and is refused (`industry_unmapped`), and a date the headers file does not yet cover refuses the whole run, naming the date and the file's coverage.

`require_holdout_configuration` is called by `gate1_run.main` right after the freeze lock; every refusal is a `HoldoutRefused`.  Nothing here opens a price, an outcome or a filing of a holdout
date: it reads the headers file's own coverage statistics and the D3 manifest.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from valuation import sic_crosswalk as sx
from . import holdout
from .holdout import HoldoutRefused

HOLDOUT_OUTCOMES_END = date(2025, 12, 31)        # 12 months after the last holdout date 2024-12-31
HOLDOUT_RETURN_DATES_END = "2024-12-31"
HOLDOUT_HORIZONS = (12,)                         # the registered outcome; no other horizon is formed on the holdout
HOLDOUT_STAMP = "raw_daily_D5_survivors"


def month_end(y, m) -> str:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()


def holdout_dates() -> List[str]:
    """The 24 holdout month-ends, 2023-01-31 .. 2024-12-31 (registration v2, section 2)."""
    return [month_end(y, m) for y in (2023, 2024) for m in range(1, 13)]


class StrictSicResolver:
    """`sic_source` AND `sic_history` for `PitData` in a holdout run (Addendum L3).  Wraps a `sic_crosswalk.SicResolver` built with a headers file and a crosswalk and exposes ONLY its as-filed
    path: `__call__(cik, asof)` returns the header SIC accepted by `asof`, or None.  There is no current-dated fallback: a call for a date the headers file does not cover raises
    `HoldoutRefused` (the run-level check `require_headers_cover` makes that unreachable), and `industry_for` of a missing SIC is `industry_unmapped`, which the engine turns into a refusal."""

    def __init__(self, resolver: sx.SicResolver):
        if resolver.headers is None or resolver.crosswalk is None:
            raise HoldoutRefused("a holdout classification needs the EDGAR headers (SIC as filed) and the crosswalk: the current-dated record is not allowed (Addendum L3)")
        self._r = resolver
        self.meta = {"strict": True, "headers": resolver.headers.info()}

    def __call__(self, cik, asof=None):
        if asof is None:
            raise HoldoutRefused("a holdout SIC is read at a date (the SIC as filed at T): no dateless, current-dated read")
        if not self._r.headers.covers(asof):
            raise HoldoutRefused(f"the headers file covers filings through {self._r.headers.coverage_through}, not {asof}: no current-dated substitute in the holdout (Addendum L3)")
        r = self._r.headers.headers._latest(str(cik).zfill(10), asof, "sic")
        if r is None:
            return None
        from valuation import pit_data as pdm
        return pdm.SicRecord(r["sic"], r.get("sic_description") or "", f"EDGAR filing header {r['accession']} (as filed at the date)", True)

    def industry(self, cik) -> Optional[str]:
        return None                                   # the current-dated industry does not exist here

    def industry_for(self, cik, sic_record):
        if sic_record is None:
            return None, "industry_unmapped: no SIC as filed by the date in the EDGAR headers (the holdout refuses a current-dated classification, Addendum L3)", None
        return self._r.industry_for(cik, sic_record)

    def sector_of(self, industry):
        return self._r.sector_of(industry)


def require_headers_cover(headers: "sx.HeadersFile", dates) -> dict:
    """Refuse unless the headers file covers every date (its newest filing minus the margin is on or after the date).  Returns the file's info."""
    miss = sorted(d for d in dates if not headers.covers(d))
    if miss:
        raise HoldoutRefused(f"the D2 headers file covers filings through {headers.coverage_through} (newest filing {headers.newest_filed}, margin {sx.COVERAGE_MARGIN_DAYS} days): it does not cover "
                             f"{len(miss)} of the holdout dates, from {miss[0]}; the SIC as filed at T is required for every holdout date (Addendum L3).  Wait for the download.")
    return headers.info()


def require_holdout_configuration(dates, a, headers: Optional["sx.HeadersFile"] = None) -> dict:
    """The holdout run's input rules, called with the parsed arguments `a` (attributes: `prices_daily`, `prices`, `delisting_index`, `delisting_docs`, `headers`, `crosswalk`).  Raises
    HoldoutRefused naming the first rule broken; returns what it checked.  Mixed windows are refused: a run is development or holdout, never both."""
    dates = [str(d)[:10] for d in dates]
    wins = {d: holdout.classify(d) for d in dates}
    if any(w != "holdout" for w in wins.values()):
        raise HoldoutRefused("a run that touches the holdout may hold only holdout dates: " + str({d: w for d, w in wins.items() if w != "holdout"}))
    if getattr(a, "prices_daily", None) is None:
        raise HoldoutRefused("the holdout is priced on the D5 daily raw closes (--prices-daily): the monthly survivor file is not allowed (Addendum L4)")
    if not Path(a.prices_daily).is_dir():
        raise HoldoutRefused(f"the D5 daily price folder {a.prices_daily} does not exist")
    for name in ("delisting_index", "delisting_docs"):
        v = getattr(a, name, None)
        if v is None or not Path(v).is_dir():
            raise HoldoutRefused(f"the holdout needs the D1 event index and the D3 documents (--{name.replace('_', '-')}): {v} is not a folder (Addendum L4)")
    if getattr(a, "erp_basis", "engine_consistent") != "engine_consistent":
        raise HoldoutRefused(f"the holdout runs the registered equity risk premium, the engine-consistent one (Addenda L1, M), not {a.erp_basis!r}: Damodaran's own is a development sensitivity")
    cover = getattr(a, "survivorship_cover", None)
    if cover is None or not (Path(cover) / "cover.jsonl.gz").is_file():
        raise HoldoutRefused(f"the holdout needs the survivorship cover index (--survivorship-cover; rebuild_harness.survivorship.build_cover_index): no cover.jsonl.gz under {cover} (Addendum M1)")
    if getattr(a, "no_prices_fallback", False) or getattr(a, "prices", None) is None or not Path(a.prices).is_file():
        raise HoldoutRefused(f"the holdout puts the monthly raw price file behind a D5 ticker whose history starts late (Addendum M6): no such file at {getattr(a, 'prices', None)} or the fallback was switched off")
    if getattr(a, "headers", None) is None or not Path(a.headers).is_file():
        raise HoldoutRefused("the holdout needs the D2 EDGAR headers file (--headers): the SIC as filed at T (Addendum L3)")
    if getattr(a, "crosswalk", None) is None or not Path(a.crosswalk).is_file():
        raise HoldoutRefused("the holdout needs the SIC -> Damodaran industry crosswalk (--crosswalk)")
    hdr = headers if headers is not None else sx.HeadersFile(a.headers)
    out = {"headers": require_headers_cover(hdr, dates)}
    from . import delisting_inputs as di
    idx, docs = di.EventIndex(a.delisting_index), di.DelistingDocs(a.delisting_docs)
    comp = di.completeness(idx, docs, since="2023-01-01")
    out["delisting_docs"] = dict(comp, blocking=False)                       # Addendum P5: counted, never blocking
    out["delisting_events_unresolved_missing_document"] = di.missing_document_events(idx, docs, since="2023-01-01")
    return out


# ---- readiness: what stands between now and a freeze (reads statistics only; writes nothing) ---------------------------------------------------

def readiness(prices_daily, delisting_index, delisting_docs, headers, crosswalk, dates=None, survivorship_cover=None, prices_fallback=None) -> dict:
    """{"ready": bool, "blockers": [...], "checks": {...}}: whether the holdout's inputs are in place.  Each check is its own entry; none of them hashes the big folders (the freeze does) and none
    opens a price, an outcome or a filing of a holdout date.  A blocker is a sentence naming what is missing and what it waits for."""
    from . import delisting_inputs as di
    dates = list(dates or holdout_dates())
    checks, blockers, notes = {}, [], []

    def need(ok, name, info, why):
        checks[name] = dict(ok=bool(ok), **info)
        if not ok:
            blockers.append(f"{name}: {why}")
    p = Path(prices_daily)
    man = p / "manifest.csv"
    n_files = sum(1 for x in p.iterdir() if x.name.endswith(".csv.gz")) if p.is_dir() else 0
    need(p.is_dir() and man.is_file() and n_files > 0, "D5_daily_prices", {"folder": str(p), "ticker_files": n_files}, f"no daily price folder with a manifest at {p}")
    try:
        idx = di.EventIndex(delisting_index)
        need(True, "D1_event_index", idx.info(), "")
        try:
            docs = di.DelistingDocs(delisting_docs)
            comp = di.completeness(idx, docs, since="2023-01-01")
            miss = di.missing_document_events(idx, docs, since="2023-01-01")
            need(True, "D3_delisting_docs", dict({k: comp[k] for k in ("accessions_wanted", "with_document", "fetch_failed", "not_downloaded")},
                                                 events_with_a_reader=miss["events_with_a_reader"], events_unresolved_missing_document=miss["unresolved_missing_document"], blocking=False), "")
            if comp["not_downloaded"] or miss["unresolved_missing_document"]:     # Addendum P5
                notes.append(f"D3_delisting_docs: {comp['not_downloaded']} of {comp['accessions_wanted']} accessions are not downloaded; {miss['unresolved_missing_document']} of "
                             f"{miss['events_with_a_reader']} events with a reader stay unresolved (counted; Addendum P5: not blocking)")
        except Exception as e:
            need(False, "D3_delisting_docs", {}, f"{type(e).__name__}: {e}")
    except Exception as e:
        need(False, "D1_event_index", {}, f"{type(e).__name__}: {e}")
    try:
        h = sx.HeadersFile(headers)
        miss = [d for d in dates if not h.covers(d)]
        need(not miss, "D2_headers_sic_as_filed", {"newest_filed": h.newest_filed, "coverage_through": None if h.coverage_through is None else h.coverage_through.isoformat(),
                                                    "rows": h.n_rows, "rows_with_sic": h.n_with_sic, "uncovered_holdout_dates": len(miss)},
             f"the headers cover filings through {h.coverage_through}, so {len(miss)} of {len(dates)} holdout dates are not covered" + (f" (from {min(miss)})" if miss else "") + "; wait for the download")
    except Exception as e:
        need(False, "D2_headers_sic_as_filed", {}, f"{type(e).__name__}: {e}")
    need(Path(crosswalk).is_file(), "industry_crosswalk", {"path": str(crosswalk)}, f"no crosswalk at {crosswalk}")
    if survivorship_cover is not None:
        cp = Path(survivorship_cover) / "cover.jsonl.gz"
        need(cp.is_file(), "survivorship_cover_index", {"path": str(survivorship_cover), "bytes": cp.stat().st_size if cp.is_file() else None},
             f"no cover index at {cp}; build it with rebuild_harness.survivorship.build_cover_index (Addendum M1)")
    if prices_fallback is not None:
        need(Path(prices_fallback).is_file(), "price_fallback_monthly_file", {"path": str(prices_fallback)}, f"no monthly raw price file at {prices_fallback} (Addendum M6)")
    return {"ready": not blockers, "blockers": blockers, "notes": notes, "checks": checks, "holdout_dates": [dates[0], dates[-1], len(dates)]}


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Which holdout inputs are in place (reads statistics only; writes no freeze file).")
    root = Path(__file__).resolve().parents[2]
    ws = Path(__import__("os").environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks")) / "stocks-workspace" / "data"
    ap.add_argument("--prices-daily", type=Path, default=ws / "prices_daily")
    ap.add_argument("--delisting-index", type=Path, default=ws / "sec_bulk" / "index_P4b")
    ap.add_argument("--delisting-docs", type=Path, default=ws / "sec_bulk" / "delisting_docs")
    ap.add_argument("--headers", type=Path, default=ws / "sec_bulk" / "headers" / "headers.csv.gz")
    ap.add_argument("--crosswalk", type=Path, default=ws / "crosswalk" / "sic_to_damodaran_industry_v1.json")
    ap.add_argument("--survivorship-cover", type=Path, default=ws / "survivorship_cover")
    ap.add_argument("--prices-fallback", type=Path, default=ws / "priors" / "_inputs" / "prices_monthly_raw.json")
    a = ap.parse_args(argv)
    r = readiness(a.prices_daily, a.delisting_index, a.delisting_docs, a.headers, a.crosswalk, survivorship_cover=a.survivorship_cover, prices_fallback=a.prices_fallback)
    print(json.dumps(r, indent=1))
    return 0 if r["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

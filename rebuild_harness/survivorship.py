"""The survivorship machinery of the holdout (Addenda M, N): the companies that left between T and the outcome date and so have no price in D5.

THE GAP.  D5 (`data/prices_daily`) holds today's listings only and the id map is today's tickers: SIVB, FRC, TWTR, ATVI are not in it.  A company that was delisted after T drops out of the holdout universe
at T, the registered three bounds would be identical, and the bias (failed companies often look cheap to a value engine) could flatter B2.  So, set before any holdout figure (the bars are unchanged):

  M1 CENSUS     per date T: every company with an annual report known at T, NO price at T in the price source, a delisting event in D1 dated after T, and a public float of at least $300M on its latest
                cover page filed before T (`dei:EntityPublicFloat`).  Counted by event class.  (N2: the class `exit_record_still_reporting` is not in it: by the classifier's own rule it is not a delisting
                of the common stock.)
  M2 PROXY      the price of such a company at T is its public float divided by its shares outstanding: `price_proxy_public_float`.  (N4: the share count is the latest
                `dei:EntityCommonStockSharesOutstanding` on ANY 10-K or 10-Q cover filed before T, not only the 10-K that states the float.)  The share count is the cover's, on the cover's own basis (a split
                after the cover cannot be known for a company with no price history), so the proxy price and the per-share value are on one basis; the market capitalisation is the public float itself
                (which leaves out affiliates' shares: stamped).  The engine values it as every other name, so it can be placed in a quintile.
  M3 OUTCOME    bankruptcy (an 8-K Item 1.03 with the equity cancelled, or any strict-reader resolution of it) INSIDE THE HORIZON is -100%; an acquisition INSIDE THE HORIZON whose cash consideration a strict
                reader resolves gets the deal value against the proxy price (consideration / proxy price - 1); everything else is UNOBSERVABLE.
  N6 THE LINE   the dividing line of the horizon is the D1 event date (the delisting or the merger close) against the horizon date the outcome itself is measured at (`PriceSource.target_date`):
                one rule, used by the census flag and by the outcome.  An event dated after that date means the company still traded at the horizon and D5 merely lacks it: not a death.
  M4/N1 BOUNDS  the three bounds, keyed as everywhere else (`excluded`, `minus100`, `last_close`) so the registered pass / fail / not-decided rule applies over them as written:
                * P1: an event INSIDE the horizon of class bankruptcy, `bankruptcy_no_exit_record`, `delisted_other` or `deregistered_other` that no reader resolves: excluded, -100% (`minus100`), the proxy
                  price held (`last_close`, a 0% return).  An exchange delisting or a deregistration without an acquisition is usually distress, and a pessimistic bound treats it as one;
                * every other unobservable name (an event after the horizon, or an acquisition inside it that no reader resolves: acquisitions are usually at a premium): excluded, the date's
                  cross-sectional 10th-percentile excess return of the same horizon (in the `minus100` slot: pessimistic but possible; Addendum N1), the proxy price held (`last_close`).
                `bounds_basis` records which basis fills the pessimistic slot (`MINUS100_BASIS` or `P10_BASIS`).
                The 10th percentile is over the date's names with a measured excess return in the gate universe (market cap at least $300M, not census names: P2); it needs the whole date, so it is filled
                after the date's pass 1 (`fill_cross_section_bounds`).

P4 (fixes N3).  D1's `events.json` holds ONE event per company: its first Form 25 (or Form 15).  A company that delisted one security first (notes, preferred shares, a move between exchanges) and its
common stock later was dated at the first event: before T that hid a later delisting from the census.  Given an index with `events_all.json` (`rebuild_harness.event_index`: every exit event of every company,
exit records within 30 days of each other one event), the census takes, for each company, the FIRST QUALIFYING EVENT DATED AFTER T (class not `exit_record_still_reporting`), not the first event overall.
Without it (an index of one event per company) the census is as it was and, given `exit_records`, still counts the detectable misses (`limitation_*`, N3); with it those counters are not produced (the
cases are in the census).  Whatever the submissions do not show remains unknown.

P5.  A D3 document that is not on disk leaves the event unresolved (no text is never read as "no cash"); the census counts such events (`census_event_unresolved_missing_document`) and the run's
configuration check reports them; they never block a freeze or a run.

THE COVER INDEX.  `dei:EntityPublicFloat` and `dei:EntityCommonStockSharesOutstanding` are not in the point-in-time store (it keeps the share count only).  `build_cover_index` reads them once from the
local companyfacts archive into a new folder (`cover.jsonl.gz`, one line per company that has a public float; `manifest.json` names the archive's size and sha256): nothing is downloaded.  The cover
page counts as known at T when its filing date is strictly before T (the layer's rule when no acceptance timestamp is held).

Nothing here is read by an engine.  A holdout run reads it through `gate1_run` (`--survivorship-cover`); the development rounds read only the census counts.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from collections import Counter
from datetime import date
from multiprocessing import Pool
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

from valuation.common import DataNotPresent
from valuation.pit_data import is_num, to_date
from . import delisting_inputs as di
from . import delistings, outcomes

COVER_FILE = "cover.jsonl.gz"
MANIFEST_FILE = "manifest.json"
FLOAT_FLOOR = 300e6                                  # the gate's market-capitalisation floor, applied to the public float (M1)
PROXY_STAMP = "price_proxy_public_float"
FLOAT_TAG, SHARES_TAG = "EntityPublicFloat", "EntityCommonStockSharesOutstanding"
FIXED_BOUND_KEYS = ("excluded", "minus100", "last_close")
NOT_A_DELISTING_OF_THE_COMMON = ("exit_record_still_reporting",)      # Addendum N2: dropped from the census
MINUS100_CLASSES = ("bankruptcy", "bankruptcy_no_exit_record", "delisted_other", "deregistered_other")      # Addendum P1: the classes whose unresolved event INSIDE the horizon is bounded at -100%
P10_BASIS = "cross_section_p10"
MINUS100_BASIS = "minus100_event_class_inside_horizon"
MISSING_DOCUMENT_REASONS = ("accession_not_in_d3_manifest", "no_document_downloaded_ok", "document_file_missing_on_disk")
COVER_FORMS = ("10-K", "10-Q")                                        # Addendum N4: the covers whose share count is read (amendments and transition reports included)
EXIT_FORMS = delistings.EXCHANGE_FORMS + delistings.DEREG_FORMS
GAP_DAYS = 30                                                         # the LIMITATION counters are split at this gap; nothing is gated on it


# ---- the cover index ----------------------------------------------------------------------------------------------------------------------

def _rows(facts, tag, unit):
    out = []
    for r in (((facts.get("dei") or {}).get(tag) or {}).get("units") or {}).get(unit) or []:
        if r.get("filed") and r.get("accn") and is_num(r.get("val")):
            out.append([r.get("end"), r["val"], r["accn"], r["filed"], r.get("form")])
    return out


def _extract(args):
    zip_path, names = args
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for n in names:
            doc = json.loads(z.read(n))
            facts = doc.get("facts") or {}
            pf = _rows(facts, FLOAT_TAG, "USD")
            if not pf:
                continue
            out.append({"cik": str(doc.get("cik", n[3:13])).zfill(10), "name": doc.get("entityName"), "pf": pf, "sh": _rows(facts, SHARES_TAG, "shares")})
    return out


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def build_cover_index(zip_path, out_dir, workers: int = 4) -> dict:
    """Write the cover index of every company in the companyfacts archive that has a public float into `out_dir` (a NEW folder: an existing non-empty one is refused, nothing is overwritten or deleted)."""
    zip_path, out_dir = Path(zip_path), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise DataNotPresent(f"{out_dir} exists and is not empty: the cover index goes into a new folder")
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(i.filename for i in z.infolist() if i.filename.endswith(".json"))
    chunks = [names[i::workers * 8] for i in range(workers * 8)]
    recs = []
    with Pool(workers) as pool:
        for part in pool.imap_unordered(_extract, [(str(zip_path), c) for c in chunks if c]):
            recs += part
    recs.sort(key=lambda r: r["cik"])
    with gzip.open(out_dir / COVER_FILE, "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    man = {"source_zip": str(zip_path), "source_zip_bytes": zip_path.stat().st_size, "source_zip_sha256": _sha256(zip_path), "n_archive_members": len(names), "n_companies_with_public_float": len(recs),
           "tags": [FLOAT_TAG, SHARES_TAG], "schema": "one JSON object per line: cik, name, pf = [[end, val USD, accession, filed, form]...], sh = [[end, val shares, accession, filed, form]...]"}
    (out_dir / MANIFEST_FILE).write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


class CoverIndex:
    """The cover pages of the companies with a public float: `latest(cik, asof)` is the newest cover filed strictly before `asof` with its price proxy."""

    def __init__(self, folder):
        self.dir = Path(folder)
        p = self.dir / COVER_FILE
        if not p.is_file():
            raise DataNotPresent(f"the survivorship cover index is not at {p} (build it with rebuild_harness.survivorship.build_cover_index)")
        self.manifest = json.loads((self.dir / MANIFEST_FILE).read_text(encoding="utf-8")) if (self.dir / MANIFEST_FILE).is_file() else {}
        self.by_cik: Dict[str, dict] = {}
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    self.by_cik[r["cik"]] = r

    def latest(self, cik, asof) -> Optional[dict]:
        """{"public_float", "shares", "price_proxy", "accession", "filed", "end", "form", "name", "n_share_entries", "shares_accession", "shares_filed", "shares_end", "shares_form"} for the cover with the newest
        filing date strictly before `asof` among those that state a public float, or None.  Addendum N4: `shares` is the share count of the newest 10-K or 10-Q cover filed strictly before `asof` that
        states one - not necessarily the cover of the float - summing the share-count entries of that accession on its cover date (classes summed, as the layer's `cover_shares`); `price_proxy` is
        the float over it, None when no such cover states a share count (M2 then cannot price the company: the name stays in the census, counted)."""
        r = self.by_cik.get(str(cik).zfill(10))
        if r is None:
            return None
        asof_iso = to_date(asof).isoformat()
        c = [x for x in r["pf"] if x[3] < asof_iso and x[1] > 0]
        if not c:
            return None
        last = max(c, key=lambda x: (x[3], x[0] or ""))
        accn = last[2]
        pf = float(last[1])
        cand = [x for x in r["sh"] if x[3] < asof_iso and x[1] > 0 and str(x[4] or "").startswith(COVER_FORMS)]
        shares, n, sh_meta = None, 0, {"shares_accession": None, "shares_filed": None, "shares_end": None, "shares_form": None}
        if cand:
            newest = max(cand, key=lambda x: (x[3], x[0] or ""))
            same = [x for x in cand if x[2] == newest[2]]
            end = max((x[0] or "" for x in same))
            uniq = {(x[0], x[1]) for x in same if (x[0] or "") == end}
            shares, n = float(sum(v for _e, v in uniq)), len(uniq)
            sh_meta = {"shares_accession": newest[2], "shares_filed": newest[3], "shares_end": end or None, "shares_form": newest[4]}
        return dict({"public_float": pf, "shares": shares, "price_proxy": (pf / shares) if shares else None, "accession": accn, "filed": last[3], "end": last[0], "form": last[4], "name": r.get("name"),
                     "n_share_entries": n}, **sh_meta)


def _anchor(ev) -> str:
    """The accession of the event's anchor record (its first evidence entry: the Form 25 / Form 15 or the Item 1.03 8-K): one per event of a company."""
    return str((ev.get("evidence") or [{}])[0].get("accession") or "")


# ---- the census (M1) ----------------------------------------------------------------------------------------------------------------------------

def event_after_horizon(event_date, horizon_date) -> bool:
    """Addendum N6: the one dividing line.  An event (the D1 date: the delisting or the merger close) is AFTER the horizon when it is dated later than the date the outcome is measured at."""
    return to_date(event_date) > to_date(horizon_date)


def build_exit_records(submissions_zip, ciks) -> Dict[str, dict]:
    """{cik: {"exit": sorted dates of every Form 25 / 25-NSE / Form 15 family filing, "periodic": sorted dates of every 10-K / 10-Q / 20-F / 40-F family filing}} for the `ciks` that have an exit record, read
    from the local SEC submissions archive (`CIK##########.json` plus its `-submissions-NNN.json` pages).  This is what the LIMITATION counters need that D1 does not keep (D1 holds the first exit record
    only, and no periodic dates).  Reads the archive; writes nothing and downloads nothing."""
    want = {str(c).zfill(10) for c in ciks}
    out: Dict[str, dict] = {}
    with zipfile.ZipFile(submissions_zip) as z:
        pages: Dict[str, List[str]] = {}
        for n in z.namelist():
            if n.startswith("CIK") and n.endswith(".json") and n[3:13] in want:
                pages.setdefault(n[3:13], []).append(n)
        for cik, files in pages.items():
            blocks = [json.loads(z.read(n)) for n in sorted(files)]
            filings = delistings.filings_of(blocks)
            exits = sorted({f[1] for f in filings if f[0] in EXIT_FORMS})
            if exits:
                out[cik] = {"exit": exits, "periodic": sorted({f[1] for f in filings if f[0] in delistings.PERIODIC})}
    return out


class Survivorship:
    """M1-M4 over a cover index, the D1 event index, the D3 documents (optional: without them every event is unresolved), the id map's tickers and a price source.  `exit_records` (optional,
    `build_exit_records`) lets the census count the cases of the one-event-per-company limitation that the submissions show (Addendum N3)."""

    def __init__(self, cover: CoverIndex, index: di.EventIndex, docs: Optional[di.DelistingDocs], tickers_for: Callable[[str], Iterable[str]], price_source, floor: float = FLOAT_FLOOR,
                 exit_records: Optional[Dict[str, dict]] = None):
        self.cover, self.index, self.docs, self.tickers_for, self.src, self.floor = cover, index, docs, tickers_for, price_source, floor
        self.exit_records = exit_records
        self._events = sorted(index.all_events, key=lambda e: e["date"])                      # Addendum P4: every exit event of a company when the index has them, else the one D1 holds
        self._event_of = {e["cik"]: e for e in index.events}                                  # the first event per company (the fallback of an item without an `event_accession`)
        self._event_by_key = {(e["cik"], _anchor(e)): e for e in index.all_events}
        self._census_cache: Dict[tuple, dict] = {}
        self._price_events: Dict[str, dict] = {}

    # -- M1 --
    def has_price(self, cik, asof) -> bool:
        for t in self.tickers_for(cik):
            if self.src.has_key(t) and self.src.close_unadjusted(t, asof) is not None:
                return True
        return False

    def _screen(self, cik, k, pit):
        """(cover, reason): the M1 tests of a company on date `k` that do not concern its event: a cover with a public float before T, the float floor, no price at T and (with `pit`) an annual
        report known at T.  `reason` is None for a company that passes, else the first test it fails."""
        cov = self.cover.latest(cik, k)
        if cov is None:
            return None, "no_public_float_cover_before_T"
        if cov["public_float"] < self.floor:
            return cov, "public_float_below_floor"
        if self.has_price(cik, k):
            return cov, "has_price_at_T"
        if pit is not None:
            snap = pit.snapshot(cik, k)
            if snap is None or not snap.years:
                return cov, "no_annual_report_at_T"
        return cov, None

    def horizon_date(self, asof, horizon_months: int = 12) -> str:
        """The date the outcome is measured at (Addendum N6): the price source's own `target_date`."""
        return to_date(self.src.target_date(asof, horizon_months)).isoformat()

    def census(self, asof, pit=None, horizon_months: int = 12) -> dict:
        """{"items": [..], "counts": {...}} for the date.  An item is a company that fits M1; `pit` (a PitData) confirms the annual report known at T (None: the check is skipped and the counts say so)."""
        k = to_date(asof).isoformat()
        ck = (k, horizon_months, pit is not None)
        if ck in self._census_cache:
            return self._census_cache[ck]
        horizon_end = self.horizon_date(asof, horizon_months)
        c = Counter()
        items = []
        first_after, picked = {}, {}
        for e in self._events:                                                     # sorted by date: the first met is the earliest
            if e["date"] <= k:
                continue
            first_after.setdefault(e["cik"], e)
            if e["class"] not in NOT_A_DELISTING_OF_THE_COMMON:                    # Addendum N2
                picked.setdefault(e["cik"], e)                                     # Addendum P4: the first qualifying event dated after T
        c["events_after_T"] = len(first_after)                                     # companies with an exit event after T (one per company when the index holds one event each)
        for cik, e0 in first_after.items():
            if cik not in picked:
                c["dropped_class:" + e0["class"]] += 1
        for e in sorted(picked.values(), key=lambda e: (e["date"], e["cik"])):
            cov, why = self._screen(e["cik"], k, pit)
            if why in ("no_public_float_cover_before_T", "public_float_below_floor"):
                c[why] += 1
                continue
            c["float_at_or_above_floor"] += 1
            if why == "has_price_at_T":
                c["has_price_at_T"] += 1
                continue
            c["no_price_at_T"] += 1
            if why == "no_annual_report_at_T":
                c[why] += 1
                continue
            item = {"cik": e["cik"], "name": cov["name"], "class": e["class"], "event_date": e["date"], "event_accession": _anchor(e), "public_float": cov["public_float"], "shares": cov["shares"],
                    "price_proxy": cov["price_proxy"], "cover_accession": cov["accession"], "cover_filed": cov["filed"], "cover_end": cov["end"],
                    "shares_accession": cov["shares_accession"], "shares_form": cov["shares_form"], "shares_filed": cov["shares_filed"], "shares_end": cov["shares_end"],
                    "within_horizon": not event_after_horizon(e["date"], horizon_end)}
            items.append(item)
            c["census"] += 1
            c["census_class:" + e["class"]] += 1
            if not item["within_horizon"]:
                c["census_event_after_horizon"] += 1
            if item["price_proxy"] is None:
                c["census_no_shares_on_cover"] += 1
            else:
                c["census_with_price_proxy"] += 1
            if self.docs is not None and e["class"] in di.ITEM_FOR_CLASS:           # Addendum P5: an event whose document is not on disk is unresolved, counted, never blocking
                _pe, text_why = self.price_event(item)
                if text_why is not None:
                    c["census_event_unresolved_no_text"] += 1
                    if text_why in MISSING_DOCUMENT_REASONS:
                        c["census_event_unresolved_missing_document"] += 1
        if self.exit_records is not None and not self.index.has_all_events:
            c.update(self._limitation(k, pit, horizon_end, items))
        out = {"asof": k, "items": items, "counts": dict(c), "annual_report_checked": pit is not None, "horizon_end": horizon_end}
        self._census_cache[ck] = out
        return out

    def _limitation(self, k, pit, horizon_end, items) -> Counter:
        """Addendum N3: the detectable cases of the one-event-per-company limitation (D1 holds a company's FIRST exit record only), from the submissions' exit records.  Counted, never corrected:
          limitation_census_later_exit_record      a census company with an exit record dated after its D1 event (split: the latest such record more than `GAP_DAYS` after it, probably the end of
                                                   the common stock; or within `GAP_DAYS`, a Form 15 that follows its Form 25);
          limitation_missed_event_before_T         a company that passes the M1 tests but is absent because its D1 event is dated on or before T, that filed a periodic report after that event and
                                                   before T (so it was still alive at T: the first event was for another security) and has an exit record dated after T; split by whether the next
                                                   exit record after T falls inside the horizon;
          limitation_dropped_class_later_exit      a company whose D1 event is after T but of a class N2 drops, with a later exit record (split by the gap as the first)."""
        c = Counter()

        def gap_key(ev_date, last):
            return "gap_gt_30d" if (to_date(last) - to_date(ev_date)).days > GAP_DAYS else "gap_le_30d"

        for i in items:
            later = [d for d in (self.exit_records.get(i["cik"]) or {}).get("exit", []) if d > i["event_date"]]
            if later:
                c["limitation_census_later_exit_record"] += 1
                c["limitation_census_later_exit_record:" + gap_key(i["event_date"], later[-1])] += 1
        for cik, rec in self.exit_records.items():
            e = self._event_of.get(cik)
            if e is None:
                continue
            exits = rec["exit"]
            if e["date"] <= k:
                after_T = [d for d in exits if d > k]
                if after_T and any(e["date"] < p < k for p in rec["periodic"]):
                    _cov, why = self._screen(cik, k, pit)
                    if why is None:
                        c["limitation_missed_event_before_T"] += 1
                        c["limitation_missed_event_before_T:next_exit_record_" + ("within" if after_T[0] <= horizon_end else "after") + "_horizon"] += 1
            elif e["class"] in NOT_A_DELISTING_OF_THE_COMMON:
                later = [d for d in exits if d > e["date"]]
                if later:
                    _cov, why = self._screen(cik, k, pit)
                    if why is None:
                        c["limitation_dropped_class_later_exit"] += 1
                        c["limitation_dropped_class_later_exit:" + gap_key(e["date"], later[-1])] += 1
        return c

    def items_by_cik(self, asof, pit=None, horizon_months: int = 12) -> Dict[str, dict]:
        return {i["cik"]: i for i in self.census(asof, pit, horizon_months)["items"]}

    # -- M3 --
    def price_event(self, item) -> tuple:
        """(price event, reason) of the census company's D1 event through the strict readers (D3 documents).  An event whose documents cannot be read stays unresolved."""
        key = (item["cik"], item.get("event_accession"))
        if key not in self._price_events:
            ev = self._event_by_key.get(key) if item.get("event_accession") is not None else self._event_of.get(item["cik"])
            if ev is None:
                self._price_events[key] = (None, "no_d1_event")
            elif self.docs is None:
                self._price_events[key] = (delistings.price_event(ev, None), "no_documents_folder")
            else:
                text, why = di.event_text(ev, self.index, self.docs)
                self._price_events[key] = (delistings.price_event(ev, text), why)
        return self._price_events[key]

    def outcome(self, item, src, asof, months: int, benchmark: str = outcomes.BENCHMARK) -> dict:
        """The horizon outcome of a census company (the shape of `outcomes.horizon_outcome`): resolved by M3 where a strict reader resolves its event INSIDE the horizon (N6: the D1 event date against
        the horizon date), else UNOBSERVABLE with the three bounds (module docstring, M4/N1/P1): `excluded` None; `minus100` the -100% bound for an event of a MINUS100_CLASSES class inside the horizon
        (`bounds_basis` {"minus100": MINUS100_BASIS}), otherwise None with `bounds_basis` {"minus100": "cross_section_p10"} for `fill_cross_section_bounds` to fill; `last_close` the proxy price held, a 0% return."""
        out = {"status": outcomes.UNOBSERVABLE, "available": False, "ret": None, "bench": None, "excess": None, "flags": [PROXY_STAMP], "bounds": {k: None for k in FIXED_BOUND_KEYS}}
        proxy = item.get("price_proxy")
        d1 = src.target_date(asof, months)
        b0 = src.entry_point(benchmark, asof) if src.has_key(benchmark) else None
        b1 = src.adj_close(benchmark, d1) if src.has_key(benchmark) else None
        if proxy is None or not proxy > 0:
            out["flags"].append("no_price_proxy")
            return out
        if b0 is None:
            out["flags"].append("no_benchmark_entry")
            return out
        if b1 is None:
            out["status"] = outcomes.BEYOND
            return out
        bench = b1.price / b0.price - 1.0
        ev, why = self.price_event(item)
        after = event_after_horizon(item["event_date"], d1)
        if after:
            out["flags"].append("event_after_horizon")
        resolved = ev is not None and ev.get("type") in ("bankruptcy", "acquisition") and not after
        if resolved:
            if ev["type"] == "bankruptcy":
                ret, flags = -1.0, ["delisting_bankruptcy_minus_100pct"]
            else:
                ret, flags = ev["cash_per_share"] / proxy - 1.0, ["delisting_acquisition_consideration", "deal_value_against_the_proxy_price", "proceeds_held_as_cash"]
            out.update(status=outcomes.BANKRUPT if ev["type"] == "bankruptcy" else outcomes.ACQUIRED, available=True, ret=ret, bench=bench, excess=ret - bench)
            out["flags"] += flags
            out["bounds"] = {k: ret - bench for k in FIXED_BOUND_KEYS}
            return out
        out["flags"].append("unobservable_delisting:" + str((ev or {}).get("type") or why))
        if item.get("class") in MINUS100_CLASSES and not after:                          # Addendum P1: an exit of distress class inside the horizon
            out["bounds"] = {"excluded": None, "minus100": -1.0 - bench, "last_close": 0.0 - bench}
            out["bounds_basis"] = {"minus100": MINUS100_BASIS}
        else:
            out["bounds"] = {"excluded": None, "minus100": None, "last_close": 0.0 - bench}
            out["bounds_basis"] = {"minus100": P10_BASIS}
        return out


def fill_cross_section_bounds(recs: List[dict]) -> Dict[int, dict]:
    """Addendum N1: set the pessimistic bound of every census record whose outcome says `bounds_basis` `cross_section_p10` to the date's cross-sectional 10th-percentile excess return of the same horizon
    (linear interpolation, `numpy.percentile`), over the date's records in the gate universe (`mcap_group` >= 300M) that have a measured excess return and are not census names.  `recs` are ONE date's
    records.  Returns {horizon: {"p10", "n"}}; the value and n are also kept on each filled record as `bound_p10`.  A horizon with no measured excess leaves the bound None."""
    hs = sorted({h for r in recs for h in (r.get("bounds") or {})})
    stats: Dict[int, dict] = {}
    for h in hs:
        xs = [r["excess"][h] for r in recs if not r.get("survivorship") and r.get("mcap_group") == ">=300M" and is_num((r.get("excess") or {}).get(h))]
        stats[h] = {"p10": float(np.percentile(xs, 10)) if xs else None, "n": len(xs)}
    for r in recs:
        for h, basis in (r.get("bounds_basis") or {}).items():
            for key, what in basis.items():
                if what == P10_BASIS and (r.get("bounds") or {}).get(h) is not None:
                    r["bounds"][h][key] = stats[h]["p10"]
                    r.setdefault("bound_p10", {})[h] = stats[h]
    return stats


def dev_census_counts(surv: Survivorship, dates: List[str], pit=None, universe_counts: Optional[Dict[str, int]] = None) -> dict:
    """{date: counts} for a list of dates (the development run's counts-only census), with the number of valued names at or above the floor beside it where `universe_counts` gives it."""
    out = {}
    for d in dates:
        c = surv.census(d, pit)["counts"]
        out[d] = dict(c, valued_names_at_or_above_floor=(universe_counts or {}).get(d))
    return out

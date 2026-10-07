"""The survivorship machinery of the holdout (Addendum M, M1-M4): the companies that left between T and the outcome date and so have no price in D5.

THE GAP.  D5 (`data/prices_daily`) holds today's listings only and the id map is today's tickers: SIVB, FRC, TWTR, ATVI are not in it.  A company that was delisted after T drops out of the holdout universe
at T, the registered three bounds would be identical, and the bias (failed companies often look cheap to a value engine) could flatter B2.  So, set before any holdout figure (the bars are unchanged):

  M1 CENSUS     per date T: every company with an annual report known at T, NO price at T in the price source, a delisting event in D1 dated after T, and a public float of at least $300M on its latest
                cover page filed before T (`dei:EntityPublicFloat`).  Counted by event class.
  M2 PROXY      the price of such a company at T is its public float divided by its shares outstanding, from the same cover (the latest filed before T): `price_proxy_public_float`.  The share count is
                the cover's, on the cover's own basis (a split after the cover cannot be known for a company with no price history), so the proxy price and the per-share value are on one basis;
                the market capitalisation is the public float itself (which leaves out affiliates' shares: stamped).  The engine values it as every other name, so it can be placed in a quintile.
  M3 OUTCOME    bankruptcy (an 8-K Item 1.03 with the equity cancelled, or any strict-reader resolution of it) is -100%; an acquisition whose cash consideration a strict reader resolves gets the deal
                value against the proxy price (consideration / proxy price - 1); everything else is UNOBSERVABLE.  An event dated after the horizon's end is unobservable too (flagged
                `event_after_horizon`: the company still traded at the horizon and D5 holds no price for it).  After the event the proceeds are held as cash; the benchmark runs to the horizon.
  M4 BOUNDS     the three bounds include these names: an unobservable outcome is excluded, set at -100%, or at 0% (the proxy price held; stored under the bound key `last_close`, which for a name with
                no price history is the proxy price).  The registered pass / fail / not-decided rule applies over the bounds as written.

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

from valuation.common import DataNotPresent
from valuation.pit_data import add_months, is_num, to_date
from . import delisting_inputs as di
from . import delistings, outcomes

COVER_FILE = "cover.jsonl.gz"
MANIFEST_FILE = "manifest.json"
FLOAT_FLOOR = 300e6                                  # the gate's market-capitalisation floor, applied to the public float (M1)
PROXY_STAMP = "price_proxy_public_float"
FLOAT_TAG, SHARES_TAG = "EntityPublicFloat", "EntityCommonStockSharesOutstanding"
FIXED_BOUND_KEYS = ("excluded", "minus100", "last_close")


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
        """{"public_float", "shares", "price_proxy", "accession", "filed", "end", "form", "name", "n_share_entries"} for the cover with the newest filing date strictly before `asof` among those that
        state a public float, or None.  `shares` sums the share-count entries of the SAME accession on the cover date (classes summed, as the layer's `cover_shares`); `price_proxy` is None when that
        accession states no share count (M2 then cannot price the company: the name stays in the census, counted)."""
        r = self.by_cik.get(str(cik).zfill(10))
        if r is None:
            return None
        asof_iso = to_date(asof).isoformat()
        c = [x for x in r["pf"] if x[3] < asof_iso and x[1] > 0]
        if not c:
            return None
        last = max(c, key=lambda x: (x[3], x[0] or ""))
        accn = last[2]
        sh = [x for x in r["sh"] if x[2] == accn and x[1] > 0]
        shares, n = None, 0
        if sh:
            end = max((x[0] or "" for x in sh))
            uniq = {(x[0], x[1]) for x in sh if (x[0] or "") == end}
            shares, n = float(sum(v for _e, v in uniq)), len(uniq)
        pf = float(last[1])
        return {"public_float": pf, "shares": shares, "price_proxy": (pf / shares) if shares else None, "accession": accn, "filed": last[3], "end": last[0], "form": last[4], "name": r.get("name"),
                "n_share_entries": n}


# ---- the census (M1) ----------------------------------------------------------------------------------------------------------------------------

class Survivorship:
    """M1-M4 over a cover index, the D1 event index, the D3 documents (optional: without them every event is unresolved), the id map's tickers and a price source."""

    def __init__(self, cover: CoverIndex, index: di.EventIndex, docs: Optional[di.DelistingDocs], tickers_for: Callable[[str], Iterable[str]], price_source, floor: float = FLOAT_FLOOR):
        self.cover, self.index, self.docs, self.tickers_for, self.src, self.floor = cover, index, docs, tickers_for, price_source, floor
        self._events = sorted(index.events, key=lambda e: e["date"])
        self._census_cache: Dict[tuple, dict] = {}
        self._price_events: Dict[str, dict] = {}

    # -- M1 --
    def has_price(self, cik, asof) -> bool:
        for t in self.tickers_for(cik):
            if self.src.has_key(t) and self.src.close_unadjusted(t, asof) is not None:
                return True
        return False

    def census(self, asof, pit=None, horizon_months: int = 12) -> dict:
        """{"items": [..], "counts": {...}} for the date.  An item is a company that fits M1; `pit` (a PitData) confirms the annual report known at T (None: the check is skipped and the counts say so)."""
        k = to_date(asof).isoformat()
        ck = (k, horizon_months, pit is not None)
        if ck in self._census_cache:
            return self._census_cache[ck]
        horizon_end = add_months(to_date(asof), horizon_months).isoformat()
        c = Counter()
        items = []
        for e in self._events:
            if e["date"] <= k:
                continue
            c["events_after_T"] += 1
            cov = self.cover.latest(e["cik"], k)
            if cov is None:
                c["no_public_float_cover_before_T"] += 1
                continue
            if cov["public_float"] < self.floor:
                c["public_float_below_floor"] += 1
                continue
            c["float_at_or_above_floor"] += 1
            if self.has_price(e["cik"], k):
                c["has_price_at_T"] += 1
                continue
            c["no_price_at_T"] += 1
            if pit is not None:
                snap = pit.snapshot(e["cik"], k)
                if snap is None or not snap.years:
                    c["no_annual_report_at_T"] += 1
                    continue
            item = {"cik": e["cik"], "name": cov["name"], "class": e["class"], "event_date": e["date"], "public_float": cov["public_float"], "shares": cov["shares"],
                    "price_proxy": cov["price_proxy"], "cover_accession": cov["accession"], "cover_filed": cov["filed"], "cover_end": cov["end"],
                    "within_horizon": e["date"] <= horizon_end}
            items.append(item)
            c["census"] += 1
            c["census_class:" + e["class"]] += 1
            if not item["within_horizon"]:
                c["census_event_after_horizon"] += 1
            if item["price_proxy"] is None:
                c["census_no_shares_on_cover"] += 1
        out = {"asof": k, "items": items, "counts": dict(c), "annual_report_checked": pit is not None, "horizon_end": horizon_end}
        self._census_cache[ck] = out
        return out

    def items_by_cik(self, asof, pit=None, horizon_months: int = 12) -> Dict[str, dict]:
        return {i["cik"]: i for i in self.census(asof, pit, horizon_months)["items"]}

    # -- M3 --
    def price_event(self, item) -> tuple:
        """(price event, reason) of the census company's D1 event through the strict readers (D3 documents).  An event whose documents cannot be read stays unresolved."""
        key = item["cik"]
        if key not in self._price_events:
            ev = next((e for e in self.index.events if e["cik"] == key), None)
            if ev is None:
                self._price_events[key] = (None, "no_d1_event")
            elif self.docs is None:
                self._price_events[key] = (delistings.price_event(ev, None), "no_documents_folder")
            else:
                text, why = di.event_text(ev, self.index, self.docs)
                self._price_events[key] = (delistings.price_event(ev, text), why)
        return self._price_events[key]

    def outcome(self, item, src, asof, months: int, benchmark: str = outcomes.BENCHMARK) -> dict:
        """The horizon outcome of a census company (the shape of `outcomes.horizon_outcome`): resolved by M3 where a strict reader resolves its event inside the horizon, else UNOBSERVABLE with the
        three bounds of M4 (`excluded` None, `minus100`, `last_close` = the proxy price held, a 0% return)."""
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
        after = to_date(item["event_date"]) > d1
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
        out["bounds"] = {"excluded": None, "minus100": -1.0 - bench, "last_close": 0.0 - bench}
        return out


def dev_census_counts(surv: Survivorship, dates: List[str], pit=None, universe_counts: Optional[Dict[str, int]] = None) -> dict:
    """{date: counts} for a list of dates (the development run's counts-only census), with the number of valued names at or above the floor beside it where `universe_counts` gives it."""
    out = {}
    for d in dates:
        c = surv.census(d, pit)["counts"]
        out[d] = dict(c, valued_names_at_or_above_floor=(universe_counts or {}).get(d))
    return out

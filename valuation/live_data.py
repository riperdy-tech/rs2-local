"""live_data.py - the live data layer's first slice (plan D3; recovery plan S9.1; operator O5: standing approval for SEC daily, Yahoo daily closes,
Damodaran monthly).

  refresh_companies   for the book's companies, SEC's companyfacts JSON (data.sec.gov/api/xbrl/companyfacts) -> `pit_data.compact_company` (the same
                      compaction the replay store was built with) -> one gz file per company in the live store, written atomically; the manifest records
                      each fetch (UTC time, sha256 of the bytes received, the latest filing date in the facts).  A failed fetch keeps the previous file and
                      is recorded as an error: the staleness rule then refuses the company; nothing is ever filled in.
  stale_reasons       the `stale_inputs` reasons of verdict contract v4 (SPEC_verdict_contract_v4 section 8) for one company at `asof`: facts never fetched
                      or older than the limit; SEC listing a 10-Q / 10-K filed after the store's latest filing (the store is behind); and, for the date,
                      the price series and the Damodaran inputs older than their limits.
Network: only sec.gov / data.sec.gov through `sec_primary._http_get` (rs2's User-Agent, throttle and retries).  Prices and Damodaran are read here, not
fetched: their fetchers are an S9 decision (the screener's daily job already fetches prices).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from .pit_data import compact_company

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FACTS_MAX_AGE_DAYS = 2
PRICE_MAX_TRADING_DAYS = 3
DAMODARAN_MAX_DAYS = 45
PERIODIC_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")


def _default_get(url: str) -> bytes:
    import sec_primary                                           # rs2's guarded sec.gov fetch (User-Agent, throttle, retries)
    return sec_primary._http_get(url)


def latest_filed(doc: Mapping) -> Optional[str]:
    """The latest `filed` date anywhere in a companyfacts document."""
    best = None
    for tax in (doc.get("facts") or {}).values():
        for concept in tax.values():
            for unit in (concept.get("units") or {}).values():
                for f in unit:
                    d = f.get("filed")
                    if d and (best is None or d > best):
                        best = d
    return best


def refresh_companies(ciks: Iterable[str], store_dir, manifest_path, get: Callable[[str], bytes] = None, now: Callable[[], datetime] = None) -> Dict[str, dict]:
    """Fetch and compact each company; returns this refresh's manifest entries (also merged into `manifest_path`)."""
    get = get or _default_get
    now = now or (lambda: datetime.now(timezone.utc))
    store_dir, manifest_path = Path(store_dir), Path(manifest_path)
    store_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    out = {}
    for cik in ciks:
        cik = str(cik).zfill(10)
        stamp = now().isoformat()
        try:
            raw = get(COMPANYFACTS_URL.format(cik=cik))
            doc = json.loads(raw)
            compact = compact_company(doc)
            tmp = store_dir / f"{cik}.json.gz.tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(compact, f, separators=(",", ":"))
            os.replace(tmp, store_dir / f"{cik}.json.gz")
            entry = {"fetched_utc": stamp, "sha256": hashlib.sha256(raw).hexdigest(), "latest_filed": latest_filed(doc), "error": None}
        except Exception as e:                                    # recorded as itself; the previous file (if any) stays and the staleness rule judges it
            prev = manifest.get(cik) or {}
            entry = dict(prev, last_error_utc=stamp, error=f"{type(e).__name__}: {str(e)[:160]}")
        manifest[cik] = entry
        out[cik] = entry
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, manifest_path)
    return out


def stale_reasons(cik: str, asof, manifest: Mapping, submissions: Optional[Mapping] = None, *, spy_last: Optional[str] = None,
                  trading_days_since_spy: Optional[int] = None, damodaran_asof: Optional[str] = None, priors_vintage: Optional[int] = None) -> List[str]:
    """Every applicable `stale_inputs` reason (empty = fresh)."""
    a = asof if isinstance(asof, date) else date.fromisoformat(str(asof)[:10])
    cik = str(cik).zfill(10)
    m = manifest.get(cik)
    out = []
    if not m or not m.get("fetched_utc"):
        out.append("company facts never fetched")
    else:
        age = (a - date.fromisoformat(m["fetched_utc"][:10])).days
        if age > FACTS_MAX_AGE_DAYS:
            out.append(f"company facts fetched {age} days before {a.isoformat()} (limit {FACTS_MAX_AGE_DAYS})")
        if m.get("error"):
            out.append(f"the latest facts refresh failed: {m['error']}")
        rec = ((submissions or {}).get("filings") or {}).get("recent") or {}
        forms, dates = rec.get("form") or [], rec.get("filingDate") or []
        newer = [d for f, d in zip(forms, dates) if f in PERIODIC_FORMS and m.get("latest_filed") and m["latest_filed"] < d <= a.isoformat()]
        if newer:
            out.append(f"SEC lists a periodic report filed {max(newer)} after the store's latest filing {m.get('latest_filed')}: the store is behind")
    if trading_days_since_spy is not None and trading_days_since_spy > PRICE_MAX_TRADING_DAYS:
        out.append(f"prices end {spy_last}: {trading_days_since_spy} trading days old (limit {PRICE_MAX_TRADING_DAYS})")
    if damodaran_asof is not None and (a - date.fromisoformat(damodaran_asof[:10])).days > DAMODARAN_MAX_DAYS:
        out.append(f"Damodaran inputs dated {damodaran_asof[:10]} (limit {DAMODARAN_MAX_DAYS} days)")
    if priors_vintage is not None and priors_vintage != a.year - 1:
        out.append(f"priors vintage {priors_vintage} is not year(asof) - 1 = {a.year - 1}")
    return out

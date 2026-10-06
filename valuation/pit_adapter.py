"""pit_adapter.py - the adapter from the shared point-in-time layer (valuation/pit_data.py `PitData`) to the engines' `common.CompanyPIT`.

It replaces the engines' interim `pit_companyfacts.py` source (kept for its own tests only).  What it adds on top of `PitData.company_pit`:

  * THE DECISION TIME.  Every accession behind a value (annual reports, cells, concepts, the cover-page share count) is re-checked against the 16:00 ET
    rule of `CompanyPit.eligibility`: accepted at or before 16:00 ET on the valuation date when an acceptance timestamp is held, else filed on an earlier
    date.  A filing that the rule calls PIT_INVALID (accepted after the decision time) or AMBIGUOUS (filed on the date with no timestamp) REFUSES the
    company: nothing is substituted.  (`company_pit` already builds from eligible facts only, so a hit here is a defect of the layer or the store, and
    the refusal says so.)
  * PROVENANCE.  Each cell's state is PIT_VALID or RESTATED (the value known at T differs from the first-filed value; allowed, it is what was known); a cell
    that is not filed is MISSING (None).  The counts ride on the result.
  * INDUSTRY AS FILED AT T.  The SIC of `pit.sic(cik, asof)`: the EDGAR filing header as filed at the date when the layer holds a header history, else the
    CURRENT assignment from `CurrentSicFile`, which is stamped `sic_current_dated` (a look-ahead label, said so on every result).  No header history exists in
    this build (no header download was approved), so every SIC and Damodaran industry here is current-dated.
  * CURRENCY.  A filer with no dollar facts is carried by the layer in its own units; the adapter refuses it (`reporting_currency_not_usd`): Addendum G 8, no
    FX source, counted by the caller.

`adapt()` never raises for a data reason: it returns an `AdaptResult` whose `company` is None and whose `refusals` name the reasons.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

from . import pit_data as pd_
from .common import PITViolation
from .pit_data import PIT_VALID, RESTATED, AMBIGUOUS, PIT_INVALID, SicRecord

CURRENT_SIC_SOURCE = "Damodaran indname 2026-01 via current ticker (current-dated, not the SIC as filed at T)"


class CurrentSicFile:
    """`sic_source` for PitData: the SIC and the Damodaran industry of a CIK from the priors build's `sic_by_cik.json` ({"map": {cik: {"sic", "industry"}}}).
    Both labels are January-2026 data through today's tickers: `point_in_time` is False and the adapter stamps it.  A company the file does not list has
    no SIC here (None), and is classified by the balance sheet alone."""

    def __init__(self, path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        self.map = doc["map"]
        self.meta = doc.get("meta", {})

    def __call__(self, cik):
        r = self.map.get(str(cik).zfill(10))
        if r is None:
            return None
        return SicRecord(str(r["sic"]), str(r.get("industry") or ""), CURRENT_SIC_SOURCE, False)

    def industry(self, cik) -> Optional[str]:
        r = self.map.get(str(cik).zfill(10))
        return None if r is None else (str(r.get("industry") or "") or None)


@dataclass
class AdaptResult:
    cik: str
    asof: str
    company: object = None                      # common.CompanyPIT, or None when refused
    refusals: List[str] = field(default_factory=list)
    stamps: List[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)      # {"PIT_VALID": n, "RESTATED": n, "cells": n}
    industry: Optional[str] = None              # the Damodaran industry label (current-dated), when the SIC source holds one
    currency: str = "USD"

    @property
    def ok(self) -> bool:
        return self.company is not None and not self.refusals


def _eligibility_hits(c, asof_iso, pit) -> dict:
    """{state: [(what, accession, filed)]} for every accession the CompanyPIT rests on that the 16:00 ET rule does not call ok."""
    elig = c.eligibility(asof_iso)
    bad = {PIT_INVALID: [], AMBIGUOUS: []}
    state_of = {"invalid": PIT_INVALID, "ambiguous": AMBIGUOUS}

    def check(what, accn, filed):
        e = elig(accn, filed)
        if e != "ok":
            bad[state_of[e]].append((what, accn, filed))
    for ar in pit.annual_reports:
        check("annual_report:" + ar[0], ar[2], ar[1])
    for tab in (pit.series, pit.concepts):
        for name, per in tab.items():
            for pe, f in per.items():
                check(f"{name}:{pe}", f.accession, f.filed)
    so = pit.shares_outstanding
    if so is not None:
        check("shares_outstanding", so.accession, so.filed)
    return {k: v for k, v in bad.items() if v}


def adapt(data: "pd_.PitData", cik, asof, ticker=None) -> AdaptResult:
    """The engines' CompanyPIT for one company at one valuation date, or a named refusal."""
    cik = str(cik).zfill(10)
    asof_d = pd_.to_date(asof)
    res = AdaptResult(cik=cik, asof=asof_d.isoformat())
    c = data.company(cik)
    if c is None:
        res.refusals.append("not_in_archive")
        return res
    try:
        obj = data.company_pit(cik, asof_d, ticker)
    except PITViolation as e:                         # the engines' own construction check: a value filed on or after the date reached the layer's output
        res.refusals.append(f"PIT_INVALID: {str(e)[:200]}")
        return res
    if obj is None:
        res.refusals.append("not_in_archive")
        return res
    if not obj.periods():
        res.refusals.append("no_annual_report_at_decision_time")
        return res
    cur = [n for n in obj.notes if str(n).startswith("reporting_currency:")]
    if cur:
        res.currency = cur[0].split(":", 1)[1]
        res.refusals.append("reporting_currency_not_usd")
        res.stamps.append(cur[0])
        return res
    hits = _eligibility_hits(c, asof_d.isoformat(), obj)
    for state, items in hits.items():
        res.refusals.append(f"{state}: {len(items)} accession(s) behind the company's inputs fail the 16:00 ET rule, e.g. {items[0]}")
    prov = getattr(obj, "provenance", {}) or {}
    n_restated = sum(1 for v in prov.values() if v == RESTATED)
    res.provenance = {PIT_VALID: sum(1 for v in prov.values() if v == PIT_VALID), RESTATED: n_restated, "cells": len(prov)}
    if obj.sic is None:
        res.stamps.append("sic_missing")
    elif not obj.sic.point_in_time:
        res.stamps.append("sic_current_dated")
    else:
        res.stamps.append("sic_as_filed_at_T")
    src = data.sic_source
    res.industry = src.industry(cik) if hasattr(src, "industry") else None
    if res.industry is not None and (obj.sic is None or not obj.sic.point_in_time):
        res.stamps.append("industry_current_dated")
    if any("from_amendment" in str(n) for n in obj.notes):
        res.stamps.append("amendment_in_inputs")
    if hasattr(obj, "check"):
        try:
            obj.check()
        except Exception as e:                       # a PITViolation of the engines' own check: a refusal, never a pass-through
            res.refusals.append(f"PIT_INVALID: {type(e).__name__}: {str(e)[:160]}")
    if not res.refusals:
        res.company = obj
    return res

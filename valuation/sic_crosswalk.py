"""sic_crosswalk.py - Addendum J11: the point-in-time classification of a company at a valuation date.

THE RULE.  The family and the Damodaran industry of a company at date T come from the SIC code AS FILED at T (the EDGAR filing header of the latest annual report accepted at or
before 16:00 ET on T), through a SIC -> Damodaran-industry CROSSWALK built from Damodaran's `indname` (January 2026):

  * the crosswalk maps a 4-digit SIC code to the MODAL Damodaran industry among the UNITED STATES companies of `indname` that carry that SIC (Country == "United States"; the
    count, the modal share and the runner-up are recorded).  A tie is broken by the industry name in ascending order (a stated, arbitrary, deterministic rule, recorded as
    `tie`).  The company's own January-2026 industry row is NOT used for a company whose SIC is known as filed: it is a 2026 label;
  * a SIC code that no US company carries falls back to the modal industry of its 3-digit prefix, then of its 2-digit prefix (each over the US companies; the level is recorded and
    stamped on the company), and refuses (the industry is unmapped) when even the 2-digit prefix is empty;
  * the crosswalk also holds the Damodaran SECTOR of every industry (the sheet's "Primary Sector"), for the sector-neutral variants of the gate bars.

WHERE THE HEADERS ARE MISSING.  `SicResolver` uses the header SIC when the headers file COVERS the date and holds a header of the company accepted by then; otherwise it falls back
to the current-dated SIC and industry of `pit_adapter.CurrentSicFile` and the adapter stamps `sic_current_dated` / `industry_current_dated` (a look-ahead label, said so).  The headers
download is chronological, so a headers file is taken to cover a date only up to `coverage_through` = the newest filing date in it minus 31 days (the frontier of an unfinished download
is not trusted); a header older than that frontier of a company that was later re-classified is what the company filed, and is used.

Nothing here downloads anything.
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import pit_data as pdm
from .common import DataNotPresent, sha256_file

COUNTRY = "United States"
COVERAGE_MARGIN_DAYS = 31
CROSSWALK_VERSION = "1"


# ---- the crosswalk ---------------------------------------------------------------------------------------------------------------------

def _modal(counter: Counter) -> Tuple[Optional[str], int, int, Optional[str], bool]:
    """(industry, n at the mode, n total, runner-up, tie): the mode of a counter of industry names; a tie goes to the name that sorts first."""
    if not counter:
        return None, 0, 0, None, False
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ranked[0]
    tie = len(ranked) > 1 and ranked[1][1] == top[1]
    return top[0], top[1], sum(counter.values()), (ranked[1][0] if len(ranked) > 1 else None), tie


def build_crosswalk(rows: Iterable[dict], country: str = COUNTRY) -> dict:
    """rows: dicts with `sic`, `industry`, `sector`, `country`.  Returns {"by_sic4", "by_sic3", "by_sic2", "industry_sector", "meta"} (JSON-able)."""
    by = {4: defaultdict(Counter), 3: defaultdict(Counter), 2: defaultdict(Counter)}
    sectors: Dict[str, Counter] = defaultdict(Counter)
    n_rows = n_us = n_bad = 0
    for r in rows:
        n_rows += 1
        sic = str(r.get("sic") or "").strip()
        ind = str(r.get("industry") or "").strip()
        if r.get("sector") and ind:
            sectors[ind][str(r["sector"]).strip()] += 1          # every country: a sector is a property of the industry
        if str(r.get("country") or "").strip() != country:
            continue
        n_us += 1
        if not (sic.isdigit() and len(sic) == 4) or not ind:
            n_bad += 1
            continue
        for k in (4, 3, 2):
            by[k][sic[:k]][ind] += 1
    out = {}
    for k in (4, 3, 2):
        tab = {}
        for code, c in sorted(by[k].items()):
            ind, n, tot, runner, tie = _modal(c)
            tab[code] = {"industry": ind, "n": n, "n_total": tot, "share": n / tot, "runner_up": runner, "tie": tie}
        out[f"by_sic{k}"] = tab
    out["industry_sector"] = {ind: _modal(c)[0] for ind, c in sorted(sectors.items())}
    out["meta"] = {"version": CROSSWALK_VERSION, "country": country, "rows": n_rows, "us_rows": n_us, "us_rows_without_a_4_digit_sic_or_industry": n_bad,
                   "n_sic4": len(out["by_sic4"]), "n_sic3": len(out["by_sic3"]), "n_sic2": len(out["by_sic2"]),
                   "rule": "modal Damodaran industry among the US companies of indname per SIC; ties to the name that sorts first; 4 -> 3 -> 2 digit fallback"}
    return out


class Crosswalk:
    def __init__(self, doc: dict):
        self.doc = doc
        self.meta = doc.get("meta", {})
        self.industry_sector = doc.get("industry_sector", {})

    @classmethod
    def load(cls, path) -> "Crosswalk":
        p = Path(path)
        if not p.exists():
            raise DataNotPresent(f"the SIC -> industry crosswalk is not at {p}")
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def industry(self, sic) -> Optional[dict]:
        """{"industry", "level" (4, 3 or 2), "n", "share", "tie"} for a SIC code, or None when no US company carries its 2-digit prefix."""
        s = str(sic or "").strip()
        if not (s.isdigit() and len(s) == 4):
            return None
        for k in (4, 3, 2):
            e = self.doc[f"by_sic{k}"].get(s[:k])
            if e is not None:
                return {"industry": e["industry"], "level": k, "n": e["n"], "n_total": e["n_total"], "share": e["share"], "tie": e["tie"]}
        return None

    def sector(self, industry) -> Optional[str]:
        return self.industry_sector.get(industry) if industry else None


def read_indname(damodaran_root) -> Tuple[List[dict], dict]:
    """The rows of indname's "By industry" sheet (the Excel CSV conversion in the approved Damodaran folder) and the provenance (the .xls sha256 from the manifest, the csv sha256)."""
    root = Path(damodaran_root)
    man = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    spec = (man.get("files") or {}).get("datasets_indname.xls")
    if spec is None:
        raise DataNotPresent("datasets_indname.xls is not in the Damodaran manifest")
    xls = root / "datasets_indname.xls"
    if not xls.exists() or sha256_file(xls) != spec["sha256"]:
        raise DataNotPresent(f"{xls} is missing or its hash differs from the manifest")
    cand = sorted((root / "csv").glob("datasets_indname__*By_industry*.csv"))
    if not cand:
        raise DataNotPresent(f"no 'By industry' csv of indname under {root / 'csv'}")
    raw = cand[0].read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    rows = [{"sic": r.get("SIC Code"), "industry": r.get("Industry Group"), "sector": r.get("Primary Sector"), "country": r.get("Country"), "ticker": r.get("Exchange:Ticker")}
            for r in csv.DictReader(text.splitlines())]
    return rows, {"indname_xls_sha256": spec["sha256"], "csv": cand[0].name, "csv_sha256": sha256_file(cand[0])}


def build_file(damodaran_root, out_path) -> dict:
    """Builds the crosswalk from the approved indname and writes it to `out_path` (a NEW file: an existing one is never overwritten)."""
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError(f"{out_path} exists: never overwritten; give a new path")
    rows, prov = read_indname(damodaran_root)
    doc = build_crosswalk(rows)
    doc["meta"].update(prov, built=datetime.now().isoformat(timespec="seconds"), source="Damodaran datasets/indname.xls, January 2026 (current-dated; a mapping, not a 2026 label on a company)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


# ---- the EDGAR headers: the SIC as filed ------------------------------------------------------------------------------------------------

class HeadersFile:
    """The SIC (and name) as filed, from the headers download's CSV (`cik, accession, form, filed, accepted_index, accepted_header, sic, name, status, source`): a `HeaderSic` over the
    rows that read ok and carry a SIC, with the coverage frontier of the file.  `.gz` is read too."""

    def __init__(self, path):
        self.path = Path(path)
        recs, n_rows, newest = [], 0, None
        opener = gzip.open if self.path.suffix == ".gz" else open
        with opener(self.path, "rt", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                n_rows += 1
                f = (r.get("filed") or "").strip()
                if f and (newest is None or f > newest):
                    newest = f
                sic = (r.get("sic") or "").strip()
                if (r.get("status") or "ok").strip() != "ok" or not sic.isdigit():
                    continue
                acc = pdm.parse_accepted(r.get("accepted_index")) or pdm.parse_accepted(r.get("accepted_header"))
                if acc is None:
                    continue
                recs.append({"cik": str(r["cik"]).zfill(10), "accession": r.get("accession"), "form": r.get("form"), "filed": f, "accepted_at": acc, "sic": sic,
                             "sic_description": "", "name": r.get("name")})
        self.n_rows, self.n_with_sic = n_rows, len(recs)
        self.newest_filed = newest
        self.sha256 = sha256_file(self.path)
        self.headers = pdm.HeaderSic(recs)
        self.coverage_through = (date.fromisoformat(newest) - timedelta(days=COVERAGE_MARGIN_DAYS)) if newest else None

    def covers(self, asof) -> bool:
        return self.coverage_through is not None and pdm.to_date(asof) <= self.coverage_through

    def info(self) -> dict:
        return {"path": str(self.path), "sha256": self.sha256, "rows": self.n_rows, "rows_with_sic": self.n_with_sic, "newest_filed": self.newest_filed,
                "coverage_through": None if self.coverage_through is None else self.coverage_through.isoformat(), "coverage_margin_days": COVERAGE_MARGIN_DAYS}


class SicResolver:
    """`sic_source` AND `sic_history` for `PitData`: the SIC as filed at the date from the headers when the file covers the date and holds a header of the company accepted by then
    (point_in_time True), else the current-dated record of `current` (a `pit_adapter.CurrentSicFile`; point_in_time False, stamped by the adapter).  The Damodaran industry: through the
    crosswalk when the SIC is as filed, else the current-dated industry of `current`."""

    def __init__(self, current, headers: Optional[HeadersFile] = None, crosswalk: Optional[Crosswalk] = None):
        self.current, self.headers, self.crosswalk = current, headers, crosswalk
        self.meta = getattr(current, "meta", {})

    def __call__(self, cik, asof=None):
        cik = str(cik).zfill(10)
        if asof is not None and self.headers is not None and self.headers.covers(asof):
            r = self.headers.headers._latest(cik, asof, "sic")
            if r is not None:
                return pdm.SicRecord(r["sic"], r.get("sic_description") or "", f"EDGAR filing header {r['accession']} (as filed at the date)", True)
        return self.current(cik)

    def industry(self, cik) -> Optional[str]:
        """The CURRENT-dated industry (January 2026) of a company: used only where the SIC is not as filed."""
        return self.current.industry(cik)

    def industry_for(self, cik, sic_record) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
        """(industry, stamp, detail) of a company whose SIC record is `sic_record`."""
        if sic_record is not None and sic_record.point_in_time:
            if self.crosswalk is None:
                return None, "industry_unmapped: SIC as filed but no crosswalk was supplied", None
            e = self.crosswalk.industry(sic_record.code)
            if e is None:
                return None, f"industry_unmapped: no US company of indname carries SIC {sic_record.code} or its 2-digit prefix", None
            stamp = f"industry_from_sic_crosswalk: SIC {sic_record.code} -> {e['industry']} (level {e['level']}-digit, n={e['n']}/{e['n_total']}{', tie' if e['tie'] else ''})"
            return e["industry"], stamp, e
        return self.current.industry(cik), "industry_current_dated", None

    def sector_of(self, industry) -> Optional[str]:
        return None if self.crosswalk is None else self.crosswalk.sector(industry)

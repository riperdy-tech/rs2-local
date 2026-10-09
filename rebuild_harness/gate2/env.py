"""env.py - the real-data side of the gate-2 replay: what the CODE and MUSE arms read for one company at one replay date.

The CODE arm is the FROZEN gate-1 engine (c7d7a4f), so this module builds its inputs with the gate-1 harness's own functions (`rebuild_harness.gate1_run`: the layer, the
price source, the priors, the rates; `valuation.gate1`: prepare, DateContext, make_discount, seed_for; `valuation.erp_consistent` through `l1_date`).  Nothing here changes an
engine file.  What it adds:

  prepare_dates(dates)   CPU only, one date per worker (network blocked in the workers, as gate 1): every company of the id map is adapted and classified at T, the date's
                         population context (book D/E, spreads, industry returns) and its engine-consistent ERP (Addenda L1, M) are measured, and two files are written to ctx/:
                         `universe_<date>.json` (the gate universe: market cap of at least $300M at T, a built family, an annual report in the layer at T) and `context_<date>.pkl`.
                         It reads no outcome and no return: the gate-1 `prepare_date` also attaches outcomes and yardsticks, which a replay does not want, so the loop is repeated
                         here without them (the per-company steps are the same calls).
  RealEnv.company_inputs the inputs of `valuation.muse.pipeline.run_company` for one company-date: the CompanyPIT, the name as of T, the priors, the discount-rate factory
                         over the date's context, the price and market cap at T (used by the pipeline only after pass 1), the industry return, the filings-only document and
                         quarter sources, the seeds.

SHARE BASIS.  The gate-1 harness divides equity by `mc["shares"]` (the share count on the traded basis of the unadjusted close), while the engines' per-share outputs divide
by the filed cover count.  The two differ only when a split falls between the cover date and T.  So that every per-share number of BOTH arms is on the traded basis, the
CompanyPIT handed to the pipeline carries the traded-basis count in `shares_outstanding` (same accession and filing date, only the value; stamped `shares_traded_basis`).

NETWORK.  The runner process needs sockets (the Muse server on localhost, SEC filings for section D), so `RealEnv` initialises the gate-1 layer with its network block switched
off; `prepare_dates` workers keep the block.  Section D reads SEC filings through the repository's `sec_primary` helpers (the User-Agent and the delay are theirs); every
fetched filing is cached under the gate-2 state folder.  The submissions JSON each name needs (acceptance timestamps, former names) comes from the SEC bulk
`submissions.zip` already on disk, extracted per company into `submissions/` (nothing is downloaded for it).

PRECONDITIONS for the real run, checked by `readiness()`: the priors vintage of year(T)-1 for every date (the repository holds vintages only up to those it was asked to
build), the Damodaran files, the price folder with the dates, the sample file, the freeze, the pins.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pickle
import re
import sys
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from . import config


# ---- the inputs of one company-date -------------------------------------------------------------------------------------------------------

@dataclass
class CompanyInputs:
    cik: str
    ticker: str
    date: str
    family: str
    pit: object
    identity: dict
    priors: object
    disc_factory: Callable
    price_info: dict
    industry_context: dict
    documents: object
    quarters: object
    seed: int
    llm_seed: int
    corr: object = None                       # the priors' input correlation, as gate1.value_company passes it to the engine
    stamps: List[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class Refusal:
    """The company-date cannot be valued at all (before any model call).  A final, recorded status, never a skip."""
    status: str
    reasons: List[str]
    stamps: List[str] = field(default_factory=list)


# ---- masking (G6) ---------------------------------------------------------------------------------------------------------------------

_SUFFIX = re.compile(r"[,\s]+(inc\.?|incorporated|corp\.?|corporation|co\.?|company|ltd\.?|limited|plc|llc|l\.l\.c\.|n\.v\.|s\.a\.|ag|se|holdings?|group)\s*$", re.I)
MASK_NAME, MASK_TICKER = "Company X", "XXXX"


def name_variants(name: str, ticker: str) -> List[str]:
    """The strings the name mask replaces: the full name, the name without trailing legal suffixes (applied repeatedly), the ticker as a word."""
    out = []
    n = (name or "").strip()
    while n:
        out.append(n)
        m = _SUFFIX.sub("", n).strip(" ,.")
        if m == n:
            break
        n = m
    if (ticker or "").strip():
        out.append(ticker.strip())
    seen, res = set(), []
    for v in sorted(out, key=len, reverse=True):
        if len(v) >= 2 and v.lower() not in seen:
            seen.add(v.lower())
            res.append(v)
    return res


def mask_text(text: str, variants: List[str]) -> str:
    """Replace each variant (case-insensitive, whole words) by the mask; the ticker variant by the ticker mask.  A stated limitation: product and brand names stay."""
    out = text
    for v in variants:
        rep = MASK_TICKER if (len(v) <= 5 and v.isupper()) else MASK_NAME
        out = re.sub(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", rep, out, flags=re.I if len(v) > 5 else 0)
    return out


class MaskedDocuments:
    """A DocumentSource whose items have the company's name and ticker replaced (title and text)."""

    def __init__(self, inner, variants):
        self.inner, self.variants = inner, variants

    def items(self, cik, asof):
        items, notes = self.inner.items(cik, asof)
        return [dataclasses.replace(i, title=mask_text(i.title, self.variants), text=mask_text(i.text, self.variants)) for i in items], list(notes)


def masked_inputs(ci: CompanyInputs) -> CompanyInputs:
    """The same inputs with the identity and the document text masked (the control of registration G6).  F, Q, S and R hold no name."""
    variants = name_variants(ci.identity.get("name"), ci.identity.get("ticker"))
    ident = dict(ci.identity, name=MASK_NAME, ticker=MASK_TICKER, name_source="as_of_T", ticker_source="as_of_T")
    docs = MaskedDocuments(ci.documents, variants) if ci.documents is not None else None
    return dataclasses.replace(ci, identity=ident, documents=docs, stamps=list(ci.stamps) + ["name_and_ticker_masked"])


# ---- the date population (CPU; workers) -----------------------------------------------------------------------------------------------

def _g1r():
    from rebuild_harness import gate1_run
    return gate1_run


def _cfg(*, state_dir, store, id_map, prices_daily, prices_monthly, headers, crosswalk, sic, priors_dir, rf, strict_classification, n_draws):
    paths = config.state_paths(state_dir)
    g = _g1r()
    return {"store": str(store), "id_map": str(id_map), "prices": str(prices_monthly), "sic": str(sic), "rf": rf, "ciks": None, "n_draws": n_draws,
            "prices_daily": str(prices_daily) if prices_daily else None, "price_stamp": g.DAILY_PRICE_STAMP if prices_daily else g.PRICE_STAMP,
            "strict_classification": bool(strict_classification), "max_cached_tickers": 256, "price_events": None, "horizons": [], "outcomes_end": None, "return_dates_end": None,
            "out_dir": str(paths["ctx"]), "priors_dir": str(priors_dir) if priors_dir else None, "invalid_draw_max": None,
            "headers": str(headers) if headers else None, "crosswalk": str(crosswalk) if crosswalk else None, "erp_shifts": [], "erp_basis": g.ERP_BASIS,
            "prices_fallback": str(prices_monthly) if prices_daily else None, "survivorship_cover": None, "delisting_index": None, "delisting_docs": None}


def _worker_init(cfg):
    _g1r()._init(cfg)                        # blocks the network in this worker, as gate 1


def prepare_universe(d: str, ciks: List[str]) -> dict:
    """One date: adapt and classify every company, measure the population context and the engine-consistent ERP.  Returns {"universe": [...], "counts": {...},
    "context": {...}}.  The per-company steps are those of `gate1_run.prepare_date` without the yardsticks, the outcomes and the survivorship census."""
    from valuation import gate1, pit_adapter
    from valuation import pit_data as pdm
    g = _g1r()
    pit, priors, rates, cfg = g._ENV["pit"], g._ENV["priors"], g._ENV["rates"], g._ENV["cfg"]
    rf = rates.rf(d)[0]
    recs: List[dict] = []
    preps: Dict[str, dict] = {}
    prev = None
    counts = Counter()
    for cik in ciks:
        if prev is not None:
            pit.evict(prev)
        prev = cik
        rec = {"cik": cik, "ticker": None, "family": None, "industry": None, "status": None, "reasons": [], "market_cap": None}
        snap = pit.snapshot(cik, d)
        if snap is None or not snap.years:
            rec["status"], rec["reasons"] = "refused", ["no_annual_report_at_decision_time"]
        else:
            key, mc, _dup = g._best_ticker(pit, cik, d)
            rec["ticker"], rec["market_cap"] = key, mc["market_cap"]
            if mc["price"] is None:
                rec["status"], rec["reasons"] = "refused", ["no_price: " + str(mc["reason"])]
            elif mc["market_cap"] is None:
                rec["status"], rec["reasons"] = "refused", ["market_cap_unavailable: " + str(mc["reason"])]
            else:
                ar = pit_adapter.adapt(pit, cik, d, ticker=key)
                prep = gate1.prepare(ar)
                rec["industry"], rec["family"] = ar.industry, prep["family"]
                if prep["status"] != "prepared":
                    rec["status"], rec["reasons"] = prep["status"], list(prep["reasons"])
                else:
                    rec["status"] = "prepared"
                    preps[cik] = prep
        counts[rec["status"]] += 1
        recs.append(rec)
    if prev is not None:
        pit.evict(prev)
    ctx = gate1.DateContext.build(d, rf, list(preps.values()))
    # the preps' records for l1_date need the keys it reads: status, market_cap, cik, family
    ce, uni = g.l1_date(d, recs, preps, ctx, priors, rates, rf)
    universe = [{"cik": r["cik"], "ticker": r["ticker"], "family": r["family"], "industry": r["industry"], "market_cap": r["market_cap"]}
                for r in recs if r["status"] == "prepared" and r["market_cap"] is not None and r["market_cap"] >= gate1.MCAP_FLOOR]
    below = sum(1 for r in recs if r["status"] == "prepared" and r["market_cap"] is not None and r["market_cap"] < gate1.MCAP_FLOOR)
    refusals = Counter((r["reasons"][0].split(":")[0] if r["reasons"] else "?") for r in recs if r["status"] != "prepared")
    pit.drop_cache()
    return {"universe": universe, "counts": dict(counts), "below_floor": below, "refused_by_reason": dict(refusals),
            "context": {"ctx": ctx, "ce": ce, "uni": uni, "rf": rf, "asof": d}}


def _prepare_worker(d: str) -> dict:
    try:
        g = _g1r()
        out = prepare_universe(d, g._ENV["cfg"]["ciks"])
        ctx_dir = Path(g._ENV["cfg"]["out_dir"])
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / f"universe_{d}.json").write_text(json.dumps({"date": d, "rule": "market cap >= $300M at T, a built family, an annual report in the layer at T",
                                                                "counts": out["counts"], "below_floor": out["below_floor"], "refused_by_reason": out["refused_by_reason"],
                                                                "companies": out["universe"]}, indent=1), encoding="utf-8")
        tmp = ctx_dir / f"context_{d}.pkl.tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(out["context"], fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, ctx_dir / f"context_{d}.pkl")                       # the pickle is the marker that the date is done, so it is written last
        return {"date": d, "n_universe": len(out["universe"]), "counts": out["counts"], "below_floor": out["below_floor"]}
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def prepare_dates(dates, *, state_dir=None, workers: int = 4, limit_ciks: Optional[int] = None, **cfg_kw) -> List[dict]:
    """Write ctx/universe_<d>.json and ctx/context_<d>.pkl for every date (CPU only; at most `workers` processes, one date each).  A date whose files exist is skipped
    and said so (never overwritten)."""
    from multiprocessing import Pool
    paths = config.state_paths(state_dir)
    paths["ctx"].mkdir(parents=True, exist_ok=True)
    todo = [d for d in dates if not (paths["ctx"] / f"context_{d}.pkl").exists()]
    skipped = [d for d in dates if d not in todo]
    idm = json.loads(Path(cfg_kw["id_map"]).read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if limit_ciks:
        ciks = ciks[:limit_ciks]
    from valuation.discount_rate import MriRiskFree
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in todo}
    cfg = _cfg(state_dir=state_dir, rf=rf, n_draws=_g1r().gate1.N_DRAWS, **cfg_kw)
    cfg["ciks"] = ciks
    cfg["state_dir"] = str(state_dir) if state_dir else None
    results = [{"date": d, "skipped": "context file exists"} for d in skipped]
    if todo:
        with Pool(min(workers, len(todo)), initializer=_worker_init, initargs=(cfg,)) as pool:
            for r in pool.imap_unordered(_prepare_worker, todo):
                print(time.strftime("%H:%M"), json.dumps(r)[:300], flush=True)
                results.append(r)
    return results


# ---- the submissions folder (acceptance timestamps, former names) ------------------------------------------------------------------------

def materialise_submissions(ciks, zip_path, dest) -> dict:
    """Copy `CIK##########.json` (and its overflow pages) of each cik from the SEC bulk submissions.zip into `dest` (written once per file; an existing file is kept).
    {"copied": n, "kept": n, "missing": [cik...]}."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = {"copied": 0, "kept": 0, "missing": []}
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for cik in ciks:
            c = str(cik).zfill(10)
            main = f"CIK{c}.json"
            if main not in names:
                out["missing"].append(c)
                continue
            for n in [main] + sorted(x for x in names if x.startswith(f"CIK{c}-submissions-")):
                p = dest / n
                if p.exists():
                    out["kept"] += 1
                    continue
                p.write_bytes(z.read(n))
                out["copied"] += 1
    return out


def name_asof(subs: dict, asof) -> tuple:
    """(name, source): the company name in force at `asof` from the submissions' former-name history; `current_record` when the history does not settle it."""
    asof_s = str(asof)[:10]
    cur = subs.get("name")
    best = None
    for fn in subs.get("formerNames") or []:
        f, t = str(fn.get("from") or "")[:10], str(fn.get("to") or "")[:10]
        if f and t and f <= asof_s <= t:
            best = fn.get("name")
    if best is not None:
        return best, "as_of_T"
    last_to = max([str(fn.get("to") or "")[:10] for fn in subs.get("formerNames") or []] or [""])
    if last_to and last_to < asof_s:
        return cur, "as_of_T"
    if not (subs.get("formerNames") or []):
        return cur, "as_of_T"
    return cur, "current_record"


# ---- the real environment ---------------------------------------------------------------------------------------------------------------

class RealEnv:
    """`company_inputs(job)` for the runner, over the gate-1 layer.  Needs `prepare_dates` to have been run for the job's date."""

    def __init__(self, *, state_dir=None, store, id_map, prices_daily, prices_monthly, headers, crosswalk, sic, priors_dir=None, strict_classification=False,
                 submissions_zip=None, dates=config.DATES, fetch_documents: bool = True):
        from valuation.discount_rate import MriRiskFree
        self.paths = config.state_paths(state_dir)
        self.state_dir = state_dir
        self.fetch_documents = fetch_documents
        self.submissions_zip = submissions_zip
        rf_src = MriRiskFree()
        rf = {d: rf_src(d) for d in dates}
        cfg = _cfg(state_dir=state_dir, rf=rf, n_draws=_g1r().gate1.N_DRAWS, store=store, id_map=id_map, prices_daily=prices_daily, prices_monthly=prices_monthly, headers=headers,
                   crosswalk=crosswalk, sic=sic, priors_dir=priors_dir, strict_classification=strict_classification)
        from rebuild_harness import run_harness
        g = _g1r()
        saved = run_harness.block_network
        run_harness.block_network = lambda: None                     # this process needs sockets (localhost server, SEC)
        try:
            g._init(cfg)
        finally:
            run_harness.block_network = saved
        self.g = g
        self._ctx: Dict[str, dict] = {}
        self._docs: Dict[str, object] = {}
        self._quarters = None

    def context(self, d: str) -> dict:
        if d not in self._ctx:
            p = self.paths["ctx"] / f"context_{d}.pkl"
            if not p.exists():
                raise FileNotFoundError(f"{p} is missing: run prepare_dates for {d} first")
            with open(p, "rb") as fh:
                self._ctx[d] = pickle.load(fh)
            self.g._ENV["rates"].set_consistent_erp(d, self._ctx[d]["ce"])
        return self._ctx[d]

    def _submissions(self, cik: str) -> Optional[dict]:
        sub_dir = self.paths["submissions"]
        p = sub_dir / f"CIK{cik}.json"
        if not p.exists() and self.submissions_zip:
            materialise_submissions([cik], self.submissions_zip, sub_dir)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _documents(self):
        if "src" not in self._docs:
            from valuation.muse import documents as docs
            self.paths["doc_cache"].mkdir(parents=True, exist_ok=True)
            kw = {} if self.fetch_documents else {"fetch_8k": lambda c, a: None, "fetch_periodic": lambda c, a: None, "fetch_annual": lambda c, a: None}
            if self.fetch_documents:
                import sec_primary as sp
                sp.CACHE = self.paths["doc_cache"] / "sec_primary"
            self._docs["src"] = docs.AcceptanceBoundedDocuments(self.paths["submissions"], annual_cache_dir=self.paths["doc_cache"] / "annual", **kw)
        return self._docs["src"]

    def _quarter_source(self):
        if self._quarters is None:
            from valuation.muse import documents as docs
            self._quarters = docs.layer_quarters(self.g._ENV["pit"])
        return self._quarters

    def company_inputs(self, job: Mapping):
        """`CompanyInputs`, or a `Refusal` (a final recorded status) when the company-date cannot reach the pipeline."""
        from valuation import classification as cls_mod
        from valuation import gate1, pit_adapter
        from valuation.common import DataNotPresent, InputError, build_state
        from valuation.discount_rate import discount_rate_for_state
        g = self.g
        cik, d = str(job["cik"]).zfill(10), job["date"]
        pit, priors, rates = g._ENV["pit"], g._ENV["priors"], g._ENV["rates"]
        ctx = self.context(d)["ctx"]
        try:
            key, mc, _dup = g._best_ticker(pit, cik, d)
            if mc["price"] is None or mc["market_cap"] is None:
                return Refusal("refused", ["no_price_or_market_cap: " + str(mc["reason"])])
            ar = pit_adapter.adapt(pit, cik, d, ticker=key)
            if not ar.ok:
                return Refusal("refused", list(ar.refusals), list(ar.stamps))
            prep = gate1.prepare(ar)
            if prep["status"] != "prepared":
                return Refusal(prep["status"], list(prep["reasons"]), list(ar.stamps))
            family, industry = prep["family"], ar.industry
            pc = ar.company
            stamps = list(prep["stamps"]) + [f for f in mc["flags"]]
            sh = mc.get("shares")
            if pc.shares_outstanding is not None and sh and abs(sh - pc.shares_outstanding.value) > 1e-9 * max(1.0, abs(sh)):
                pc = dataclasses.replace(pc, shares_outstanding=dataclasses.replace(pc.shares_outstanding, value=float(sh)))
                stamps.append("shares_traded_basis: the cover count is on the traded basis of the unadjusted close (a split lies between the cover date and T)")
            st = build_state(pc)
            ir = ctx.industry_return(industry, family)
            industry_context = {} if ir is None else {("industry_rote" if family == "financial" else "industry_roic"): ir}
            subs = self._submissions(cik)
            if subs is not None:
                name, name_src = name_asof(subs, d)
            else:
                name, name_src = (g._ENV["pit"].company(cik).name if g._ENV["pit"].company(cik) else None), "current_record"
            sic_pit = "sic_as_filed_at_T" in ar.stamps
            identity = {"name": name, "ticker": key, "industry": industry, "name_source": name_src, "ticker_source": "current_record",
                        "industry_source": "as_of_T" if sic_pit else "current_record"}
        except (DataNotPresent, InputError, KeyError, ValueError, ArithmeticError) as e:
            return Refusal("refused", [f"inputs: {type(e).__name__}: {str(e)[:200]}"])

        def disc_factory(state, de_ratio=None, de_basis="book"):
            if de_ratio is None:
                disc, _s = gate1.make_discount(state, d, family, industry, ctx, rates)
                return disc
            st2 = dict(state)
            if st2.get("kd_effective") is None and de_ratio > 0:
                sp, _n, _how = ctx.kd_spread(industry)
                if sp is not None:
                    st2["kd_effective"] = ctx.rf + sp
            fin = family == "financial"
            return discount_rate_for_state(st2, d, industry=industry, rf_provider=rates.rf, beta_provider=rates.levered_beta if fin else rates.beta, erp_provider=rates.erp,
                                           de_ratio=de_ratio, de_basis=de_basis, levered_beta=fin)

        seed = gate1.seed_for(pc.cik or cik, d)
        try:
            ps = priors.for_company(family, dict(st, **industry_context), pc.asof)
        except (DataNotPresent, InputError, KeyError, ValueError, ArithmeticError) as e:
            return Refusal("refused", [f"priors: {type(e).__name__}: {str(e)[:200]}"], stamps)
        if ps.source == "UNAVAILABLE":
            return Refusal("refused", ["priors_unavailable: " + "; ".join(ps.meta.get("unavailable", []))[:200]], stamps)
        return CompanyInputs(cik=cik, ticker=key, date=d, family=family, pit=pc, identity=identity, priors=gate1.PreBuiltPriors(ps),
                             disc_factory=disc_factory, price_info={"price": mc["price"], "market_cap": mc["market_cap"], "currency": "USD"}, industry_context=industry_context,
                             documents=self._documents(), quarters=self._quarter_source(), seed=seed, llm_seed=seed, corr=ps.meta.get("corr") or None,
                             stamps=stamps, extra={"price_date": mc.get("price_date"), "price_quality": mc.get("price_quality"), "shares_traded_basis": sh})


def readiness(*, dates=config.DATES, state_dir=None, priors_dir=None, damodaran_dir=None) -> dict:
    """What the real run still needs that this module can see: {"ok": bool, "checks": [{name, ok, detail}]}.  Reads no value."""
    from valuation.priors_build import config as pc
    from valuation.priors import PopulationPriors
    paths = config.state_paths(state_dir)
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    pri = PopulationPriors(priors_dir)
    have = set(pri.vintages_available())
    for d in dates:
        v = pri.vintage_for(d)
        add(f"priors vintage {v} for {d}", v in have, f"built vintages in {pri.data_dir}: {sorted(have)}")
    for d in dates:
        add(f"context_{d}.pkl", (paths["ctx"] / f"context_{d}.pkl").exists(), str(paths["ctx"]))
    from . import sample as sm
    add("sample file", sm.sample_path(state_dir).exists(), str(sm.sample_path(state_dir)))
    from . import stage2_layer as sl
    sp = sl.stage2_paths(state_dir)
    add("stage2 survival models (V2)", sp["models"].exists(), str(sp["models"]))
    add("stage2 survival probabilities (V2)", sp["pfail"].exists(), str(sp["pfail"]))
    add("freeze file", (paths["freeze"] / "gate2_freeze.json").exists(), str(paths["freeze"]))
    add("server pins record", (paths["server"] / "pins.json").exists(), str(paths["server"]))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}

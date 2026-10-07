"""The gate-1 run on the DEVELOPMENT dates (registration REGISTRATION_gate1_DRAFT.md; brief T-integrate).  Code only: no GPU, no model, no server, no network.

    python -m rebuild_harness.gate1_run --out-dir OUT [--dates 2020-01-31 2021-06-30] [--workers 8] [--limit-ciks N] [--headers CSV] [--crosswalk JSON] [--no-erp-shifts]

For each valuation date (default: the 36 MONTH-ENDS 2020-01-31 .. 2022-12-31, registration v2: Addendum H6's development window on monthly dates) and each company in the id map it writes one record: the status of the
company (valued, or the named reason it was not), the engine's value per share with its P10..P90, the secondary and the disagreement, the discount rate and
its sources, the inputs at the prior's quantiles, the price and market cap, the five yardsticks, the outcomes and the fundamental outcomes.  A date is two
passes (see valuation/gate1.py): prepare every company, measure the population context, value every company.

THE HOLDOUT LOCK comes first: `holdout.enforce` runs before any data is opened and refuses any 2023-2024 date unless a freeze file names this engine.  No
freeze file exists or is created here.

PRICES (Addendum H9).  The development price source is the operator-approved raw monthly pull of 2026-10-01 (`data/priors/_inputs/prices_monthly_raw.json`:
Yahoo month-end bars with `auto_adjust=False`: the split-adjusted Close, Adj Close, dividends and the split events; today's listings only).  The traded unadjusted
close is rebuilt as Close x the product of the splits dated later (MonthlyRawPriceSource).  Month-end, survivors only, spin-off adjustments (Yahoo folds them into
Close) are not undone, quality UNVERIFIED: every record is stamped `raw_monthly_2026-10-01_survivors` (PRICE_STAMP, with the file's sha256 in run_meta.json) and every
B1-B4 figure computed on it is PROVISIONAL.  (Addendum G's premise that only an adjusted file existed was wrong.)  The holdout needs raw daily closes (D5).
Valuation dates are calendar month-ends and the price of a date is its month's closing bar (the last weekday of the month).

CLASSIFICATION (Addendum J11).  The SIC and the Damodaran industry of a company at a date come from the EDGAR filing headers (`--headers`: the SIC as filed at the date, the industry
through the SIC -> industry crosswalk, `--crosswalk`) where the headers file covers the date and holds a header of the company; elsewhere the current-dated SIC and industry of
`sic_by_cik.json`, stamped.  The headers file is copied into the output folder first (a download in progress changes under a run): every worker reads the copy.

DIAGNOSTIC SCORES (registration v2 B5, reported only).  On the return dates each valued name is valued again with the equity risk premium shifted by +1 pp and by -1 pp
(`score_alt`: IV / price at the median, None when that run refuses the name); every other input is the run's.

The 16:00 ET acceptance rule is applied through the layer: with no acceptance timestamp in this build, a filing is eligible when filed on an earlier date
(a filing on the date itself is AMBIGUOUS and unused).
"""
import argparse
import gzip
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from multiprocessing import Pool
from pathlib import Path

from valuation import common as vcommon
from valuation import discount_rate as vdr
from valuation import erp_consistent, gate1, pit_adapter
from valuation.priors_build import config as priors_config
from valuation import sic_crosswalk as sx
from valuation import pit_data as pdm
from valuation.common import sha256_file
from valuation.discount_rate import DamodaranStore, MriRiskFree
from valuation.priors import PopulationPriors
from . import engines as eng_mod
from . import daily_prices, delisting_inputs, fundamentals, holdout, holdout_inputs, outcomes, survivorship

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
STOCKS = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks"))
WORKSPACE = STOCKS / "stocks-workspace"
SMOKE = WORKSPACE / "scratch" / "rev23" / "harness_smoke"
INPUTS = WORKSPACE / "data" / "priors" / "_inputs"
DEFAULT_STORE = SMOKE / "store_all"
DEFAULT_IDMAP = SMOKE / "sample_id_map.json"
DEFAULT_PRICES = INPUTS / "prices_monthly_raw.json"
DEFAULT_SIC = INPUTS / "sic_by_cik.json"
HORIZONS = (3, 6, 12, 24, 36)
KS = (1, 2, 3)
PRICE_STAMP = "raw_monthly_2026-10-01_survivors"
DAILY_PRICE_STAMP = holdout_inputs.HOLDOUT_STAMP            # the D5 daily raw closes (Addendum L4): survivors only, today's listings
DAILY_ENTRY_FIELD = "open"                                    # registration v2, section 2: the return starts at the NEXT session's open

GATE1_FILES = [REPO / "valuation" / n for n in ("common.py", "classification.py", "discount_rate.py", "engine_operating.py", "engine_financial.py",
                                                  "engine_commodity.py", "priors.py", "priors_interface.py", "pit_adapter.py", "gate1.py", "variants.py", "sic_crosswalk.py", "erp_consistent.py")]


@eng_mod.engine("gate1_engine", kind="value", files=GATE1_FILES)
def gate1_engine(ticker, asof, data_root):
    """Registered so the holdout lock has an identity to freeze.  The engine values a whole date (it needs the date's population context): use `run_date`."""
    raise RuntimeError("gate1_engine values a whole valuation date; run rebuild_harness.gate1_run")


DEV_FIRST_YEAR, DEV_LAST_YEAR = 2020, 2022
OUTCOMES_END = date(2022, 12, 31)       # Addendum H6: no price outcome is formed past this date, so none reaches the 2023-2024 holdout years
RETURN_DATES_END = "2021-12-31"         # the last development date whose 12-month outcome ends by 2022-12-31 (B1, B2, B3 use the dates to here; B4 every date)
ERP_SHIFTS = (0.01, -0.01)
ERP_BASIS = "engine_consistent"          # Addenda L1, M: the registered premium; Damodaran's own is a sensitivity (`score_alt["erp_damodaran"]`)
DAMODARAN_LABEL = "erp_damodaran"
ERP_BASES = gate1.Rates.ERP_BASES
DEFAULT_HEADERS = WORKSPACE / "data" / "sec_bulk" / "headers" / "headers_raw.csv"
DEFAULT_CROSSWALK = WORKSPACE / "data" / "crosswalk" / "sic_to_damodaran_industry_v1.json"
REGISTERED_INVALID_DRAW_MAX = gate1.INVALID_DRAW_MAX      # read at import: a diagnostic --invalid-draw-max does not change what a freeze records


def frozen_config(price_stamp=PRICE_STAMP):
    """The engine configuration a freeze names (Addendum J10): the module constants of the gate-1 engine, as they stand."""
    return {"gate1_version": gate1.GATE1_VERSION, "n_draws": gate1.N_DRAWS, "mcap_floor": gate1.MCAP_FLOOR, "de_min_n": gate1.DE_MIN_N, "de_percentile": gate1.DE_PERCENTILE,
            "return_min_n": gate1.RETURN_MIN_N, "spread_min_n": gate1.SPREAD_MIN_N, "invalid_draw_max": REGISTERED_INVALID_DRAW_MAX, "terminal_g_anchor": vcommon.TERMINAL_G_ANCHOR,
            "max_horizon": vcommon.MAX_HORIZON, "level_ref_year": vcommon.LEVEL_REF_YEAR, "priors_min_n": priors_config.MIN_N, "priors_version": priors_config.PRIORS_VERSION,
            "erp_basis": ERP_BASIS, "erp_model_years": erp_consistent.MODEL_YEARS, "erp_monthly_max_age_days": vdr.MONTHLY_MAX_AGE_DAYS, "erp_publication_lag_days": vdr.PUBLICATION_LAG_DAYS, "headers_coverage_margin_days": sx.COVERAGE_MARGIN_DAYS,
            "crosswalk_version": sx.CROSSWALK_VERSION, "price_stamp": price_stamp, "horizons": list(HORIZONS), "fundamental_ks": list(KS), "return_dates_end": RETURN_DATES_END,
            "holdout_horizons": list(holdout_inputs.HOLDOUT_HORIZONS), "holdout_outcomes_end": holdout_inputs.HOLDOUT_OUTCOMES_END.isoformat(),
            "holdout_return_dates_end": holdout_inputs.HOLDOUT_RETURN_DATES_END, "daily_entry_field": DAILY_ENTRY_FIELD, "daily_max_gap_days": 5}


def frozen_seeds():
    from . import gate1_v2, metrics as hm
    return {"draw_seed_rule": "seed_for(cik, asof) = (int(cik) * 1000003 + asof.toordinal()) % (2**31 - 1): one per company and date", "wild_cluster_bootstrap_seed": gate1_v2.BOOT_SEED,
            "wild_cluster_bootstrap_draws": gate1_v2.N_BOOT, "date_bootstrap_seed": hm.SEED, "date_bootstrap_resamples": hm.N_RESAMPLES}


def freeze_inputs(a):
    """What this run reads, for the holdout lock to hash against the freeze (Addendum J10)."""
    daily = getattr(a, "prices_daily", None)
    return {"store": a.store, "prices": daily or a.prices, "damodaran": vdr.default_root(), "priors": a.priors_dir or priors_config.DATA_DIR, "crosswalk": a.crosswalk, "headers": a.headers,
            "delisting_index": getattr(a, "delisting_index", None), "delisting_docs": getattr(a, "delisting_docs", None),
            "price_fallback": a.prices if (daily and not getattr(a, "no_prices_fallback", False)) else None, "survivorship_cover": getattr(a, "survivorship_cover", None),
            "config": frozen_config(DAILY_PRICE_STAMP if daily else PRICE_STAMP), "seeds": frozen_seeds()}


def month_end(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()


def dev_dates():
    """The 36 month-ends from 2020-01-31 to 2022-12-31 (registration v2): 2020-01-31 .. 2021-12-31 (24 dates) serve the return metrics, 2022 (12 dates) forecast quality (B4) only.
    History starts with fiscal year 2009 and the priors need years behind and ahead, so 2019 and earlier hold nothing to value (round 3: the 2018 vintage has margin residual n = 9)."""
    return [month_end(y, m) for y in range(DEV_FIRST_YEAR, DEV_LAST_YEAR + 1) for m in range(1, 13)]


class ShiftedErp:
    """DIAGNOSTIC (registration v2 B5): a `Rates` whose equity risk premium is the real one plus `delta` (a fraction); everything else delegates."""

    def __init__(self, base, delta):
        self._base, self.delta = base, delta

    def __getattr__(self, name):
        return getattr(self._base, name)

    def erp(self, asof):
        v, label, meta = self._base.erp(asof)
        return v + self.delta, label + f" {self.delta * 1e4:+.0f} bp (diagnostic shift)", dict(meta or {}, erp_shift=self.delta)


class DamodaranErp:
    """DIAGNOSTIC (Addendum M): a `Rates` whose equity risk premium is Damodaran's own (the sensitivity); everything else delegates."""

    def __init__(self, base):
        self._base = base

    def __getattr__(self, name):
        return getattr(self._base, name)

    def erp(self, asof):
        return self._base.erp_damodaran(asof)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


# ---- the worker ----------------------------------------------------------------------------------------------------------------------

_ENV = {}


def _init(cfg):
    from . import run_harness
    run_harness.block_network()
    idm = json.loads(Path(cfg["id_map"]).read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    hdr = sx.HeadersFile(cfg["headers"]) if cfg.get("headers") else None
    cw = sx.Crosswalk.load(cfg["crosswalk"]) if cfg.get("crosswalk") else None
    if cfg.get("strict_classification"):                     # Addendum L3 (the holdout): the SIC as filed at T and nothing else; the current-dated file is not even opened
        sic = holdout_inputs.StrictSicResolver(sx.SicResolver(None, hdr, cw))
    else:
        cur = pit_adapter.CurrentSicFile(cfg["sic"])
        sic = sx.SicResolver(cur, hdr, cw)                   # Addendum J11: the SIC as filed where the headers cover the date, else the current-dated record (stamped)
    delist = json.loads(Path(cfg["price_events"]).read_text(encoding="utf-8")) if cfg.get("price_events") else None
    if cfg.get("prices_daily"):                              # Addendum L4: the D5 daily raw closes, read lazily (an LRU of tickers, never the whole folder)
        src = daily_prices.LazyDailyPriceSource(cfg["prices_daily"], max_cached=cfg.get("max_cached_tickers", 256), delistings=delist, entry_field=DAILY_ENTRY_FIELD)
        if cfg.get("prices_fallback"):                       # Addendum M6: the monthly raw file behind a ticker whose D5 history starts late
            src = daily_prices.FallbackPriceSource(src, pdm.MonthlyRawPriceSource.load(cfg["prices_fallback"]), delistings=delist)
    else:
        src = pdm.MonthlyRawPriceSource.load(cfg["prices"])
        src.delistings = delist
    _ENV["pit"] = pdm.PitData(cfg["store"], price_source=src, id_map=idm, sic_source=sic, sic_history=sic)
    _ENV["surv"] = None
    if cfg.get("survivorship_cover"):                        # Addendum M (M1-M4): the companies that left after T, priced by their public float
        tk_of = {}
        for t, c in idm.items():
            tk_of.setdefault(str(c).zfill(10), []).append(t)
        _ENV["surv"] = survivorship.Survivorship(survivorship.CoverIndex(cfg["survivorship_cover"]), delisting_inputs.EventIndex(cfg["delisting_index"]),
                                                 delisting_inputs.DelistingDocs(cfg["delisting_docs"]) if cfg.get("delisting_docs") else None, lambda c: tk_of.get(str(c).zfill(10), []), src)
    _ENV["priors"] = PopulationPriors(cfg.get("priors_dir"))
    _ENV["rates"] = gate1.Rates(DamodaranStore(), cfg["rf"], erp_basis=cfg.get("erp_basis", "damodaran"))     # the diagnostic scripts of rounds 3b and 4 build their own cfg: Damodaran's, as then
    _ENV["cfg"] = cfg
    if cfg.get("invalid_draw_max") is not None:
        gate1.INVALID_DRAW_MAX = cfg["invalid_draw_max"]      # a DIAGNOSTIC variant only (never the registered rule 0.05): see --invalid-draw-max


def _best_ticker(pit, cik, d):
    """Of a company's tickers (share classes), the one with the largest market cap on the date (any with a price when none has a determinable cap)."""
    cands = pit.tickers_for(cik) or [None]
    mcs = [(t, pit.market_cap(cik, d, t)) for t in cands]
    mcs.sort(key=lambda x: (x[1]["market_cap"] is not None, x[1]["market_cap"] or 0.0, x[1]["price"] is not None), reverse=True)
    return mcs[0][0], mcs[0][1], len(cands) - 1


def months_after(d, h):
    y, m = divmod(pdm.to_date(d).month - 1 + h, 12)
    y += pdm.to_date(d).year
    return date(y, m + 1, 1)


def _attach_outcomes(rec, pit, cik, key, d, snap, horizons=HORIZONS, outcomes_end=OUTCOMES_END, survivor=None):
    hz = tuple(h for h in horizons if months_after(d, h) <= outcomes_end)            # only horizons that end inside the window (development: Addendum H6; holdout: the registered 12 months)
    if survivor is not None:                                                          # Addendum M3, M4: a name with no price history is resolved from its event or left unobservable with the three bounds
        ho = {h: _ENV["surv"].outcome(survivor, pit.price_source, d, h) for h in hz}
    else:
        ho = outcomes.horizon_outcomes(pit, key, d, hz) if (key and hz) else {h: {"available": False, "status": outcomes.UNOBSERVABLE} for h in hz}
    rec["excess"], rec["ret"], rec["bounds"], rec["outcome_status"] = {}, {}, {}, {}
    for h, o in ho.items():
        rec["excess"][h], rec["ret"][h], rec["bounds"][h] = o.get("excess"), o.get("ret"), o.get("bounds")
        rec["outcome_status"][h] = o["status"]
    row = snap.row_L()
    yrs = snap.rows()
    prev = yrs.get(max((y for y in yrs if y < snap.L), default=-1))
    dct = snap.years[snap.L_fye].cells.get("debt_current")
    rec["base"] = fundamentals.measures(row, prev, dct.tag if dct is not None else None)
    fo = outcomes.fundamental_outcomes(pit, cik, snap.L_fye, KS)
    rec["out"] = {k: (v["measures"] if v else None) for k, v in fo.items()}


def prepare_date(d, ciks=None):
    """Pass 1 of one valuation date: prepare every company and measure the population context.  Returns (records, preps, context, t0, t1); the records of the
    companies that were prepared are waiting for pass 2 (status "prepared")."""
    t0 = time.time()
    pit, priors, rates, cfg = _ENV["pit"], _ENV["priors"], _ENV["rates"], _ENV["cfg"]
    ciks = ciks if ciks is not None else cfg["ciks"]
    rf = rates.rf(d)[0]
    recs, preps = [], {}
    prev = None
    surv = _ENV.get("surv")
    census = surv.items_by_cik(d, pit, cfg.get("survivorship_horizon_months", 12)) if surv is not None else {}
    if census:
        have = set(ciks)
        ciks = list(ciks) + sorted(c for c in census if c not in have)            # the census companies are in no id map: they join the date's companies
    for cik in ciks:
        if prev is not None:
            pit.evict(prev)
        prev = cik
        snap = pit.snapshot(cik, d)
        rec = {"date": d, "cik": cik, "ticker": None, "industry": None, "sector": None, "family": None, "status": None, "reasons": [], "stamps": [],
               "price_stamp": cfg.get("price_stamp", PRICE_STAMP), "price": None, "price_adj": None, "market_cap": None, "shares": None, "mcap_group": None,
               "price_quality": None, "price_flags": [], "base_fye": None, "base_age_months": None, "score": {}, "val": None}
        if snap is None or not snap.years:
            rec["status"], rec["reasons"] = "refused", ["no_annual_report_at_decision_time"]
            recs.append(rec)
            continue
        key, mc, n_dup = _best_ticker(pit, cik, d)
        rec["ticker"] = key
        comp = pit.company(cik)
        rec["name_current_dated"] = None if comp is None else comp.name         # the store's name is today's EDGAR name: for reading the diagnostics only
        rec["share_class_duplicates"] = n_dup
        rec["base_fye"] = snap.L_fye
        rec["base_age_months"] = (pdm.to_date(d) - pdm.to_date(snap.L_fye)).days / 30.4375
        rec["price"], rec["price_flags"], rec["price_quality"] = mc["price"], list(mc["flags"]), mc.get("price_quality")
        rec["market_cap"], rec["shares"] = mc["market_cap"], mc["shares"]
        item = census.get(cik)
        if mc["price"] is None and item is not None:                                   # Addendum M2: the price proxy, public float / shares outstanding of the latest cover before T
            if item["price_proxy"] is None:
                rec["status"], rec["reasons"] = "refused", ["no_price_proxy: the latest cover page states no share count"]
                rec["survivorship"] = dict(item, stamp=survivorship.PROXY_STAMP)
                recs.append(rec)
                continue
            mc = dict(mc, price=item["price_proxy"], market_cap=item["public_float"], shares=item["shares"], flags=[survivorship.PROXY_STAMP], price_quality="proxy", reason=None)
            rec["price_stamp"] = survivorship.PROXY_STAMP
            rec["market_cap"], rec["shares"], rec["price"], rec["price_flags"], rec["price_quality"] = mc["market_cap"], mc["shares"], mc["price"], list(mc["flags"]), "proxy"
            rec["survivorship"] = dict(item, stamp=survivorship.PROXY_STAMP)
        if mc["price"] is None:
            rec["status"], rec["reasons"] = "refused", ["no_price: " + str(mc["reason"])]
            recs.append(rec)
            continue
        adj = pit.price_source.adj_close(key, d) if key else None
        rec["price_adj"] = None if adj is None else adj.price
        if mc["market_cap"] is None:
            rec["status"], rec["reasons"] = "refused", ["market_cap_unavailable: " + str(mc["reason"])]
            recs.append(rec)
            continue
        rec["mcap_group"] = ">=300M" if mc["market_cap"] >= gate1.MCAP_FLOOR else "<300M"
        ar = pit_adapter.adapt(pit, cik, d, ticker=key)
        prep = gate1.prepare(ar)
        rec["industry"], rec["sector"] = ar.industry, ar.sector
        rec["family"] = prep["family"]
        rec["stamps"] = list(prep["stamps"]) + ([survivorship.PROXY_STAMP] if item is not None and rec.get("survivorship") else []) + (["price_monthly_fallback"] if "price_monthly_fallback" in rec["price_flags"] else [])
        rec["provenance"] = prep["provenance"]
        rec["family_reason"], rec["conflicts"], rec["sic"] = prep.get("family_reason"), prep.get("conflicts"), prep.get("sic")
        rec["classification_tests"] = prep.get("classification_tests")
        if prep["status"] != "prepared":
            rec["status"], rec["reasons"] = prep["status"], list(prep["reasons"])
            recs.append(rec)
            continue
        # yardsticks and outcomes need the company's layer objects: now, while it is loaded
        for name in eng_mod.YARDSTICKS:
            r = eng_mod.REGISTRY[name](key or f"CIK{cik}", d, pit)
            rec["score"][name] = r.get("score")
        _attach_outcomes(rec, pit, cik, key, d, snap, cfg.get("horizons", HORIZONS), pdm.to_date(cfg["outcomes_end"]) if cfg.get("outcomes_end") else OUTCOMES_END,
                         survivor=item if rec.get("survivorship") else None)
        rec["status"] = "prepared"
        preps[cik] = prep
        recs.append(rec)
    if prev is not None:
        pit.evict(prev)
    ctx = gate1.DateContext.build(d, rf, [p for p in preps.values()])
    return recs, preps, ctx, t0, time.time()


def l1_date(d, recs, preps, ctx, priors, rates, rf):
    """Addenda L1, M: the engine-consistent premium of the date, from Damodaran's monthly model row and the engine's cap-weighted P50 growth over the gate universe at T (the prepared companies
    of the date with a market capitalisation of at least `gate1.MCAP_FLOOR` and priors that supply a growth path; ERP-independent).  Sets it on `rates`, stamps `engine_growth_p50_mean_y1_5` on each
    record that entered the universe, and returns (ConsistentErp, universe report)."""
    items, skipped, by_family = [], Counter(), {}
    for rec in recs:
        if rec["status"] != "prepared" or rec["market_cap"] is None or rec["market_cap"] < gate1.MCAP_FLOOR:
            continue
        g = gate1.engine_growth_p50(preps[rec["cik"]], ctx, priors, rf)
        if g["status"] != "ok":
            skipped[g["reason"]] += 1
            continue
        rec["engine_growth_p50_mean_y1_5"] = g["mean"]
        items.append((rec["market_cap"], g["mean"]))
        by_family.setdefault(rec["family"], []).append((rec["market_cap"], g["mean"]))
    agg = erp_consistent.cap_weighted(items)
    fam = {}
    for f, xs in sorted(by_family.items()):
        a = erp_consistent.cap_weighted(xs)
        fam[f] = {"n": a["n"], "total_cap": a["total_cap"], "cap_weighted_growth": a["value"]}
    ex_fin = [x for f, xs in by_family.items() if f != "financial" for x in xs]
    uni = {"n": agg["n"], "total_cap": agg["total_cap"], "skipped_no_growth_path": dict(skipped), "by_family": fam,
           "cap_weighted_growth_ex_financial": (erp_consistent.cap_weighted(ex_fin)["value"] if ex_fin else None),
           "rule": "prepared, market cap >= gate1.MCAP_FLOOR at T, priors supply g1 and growth_decay (valuation status not consulted)"}
    ce = erp_consistent.consistent_erp(d, rates.store.monthly_model_row(d), agg["value"], uni)
    rates.set_consistent_erp(d, ce)
    return ce, uni


def run_date(d, ciks=None):
    """One valuation date: prepare, measure the population, value.  Returns (records, context summary)."""
    pit, priors, rates, cfg = _ENV["pit"], _ENV["priors"], _ENV["rates"], _ENV["cfg"]
    ciks = ciks if ciks is not None else cfg["ciks"]
    rf = rates.rf(d)[0]
    counts = Counter()
    recs, preps, ctx, t0, t1 = prepare_date(d, ciks)
    ce = None
    if rates.erp_basis == "engine_consistent":
        ce, _uni = l1_date(d, recs, preps, ctx, priors, rates, rf)          # one premium per date; a date that cannot have one is a stated worker failure, not a Damodaran fallback
    t1b = time.time()
    for rec in recs:
        if rec["status"] != "prepared":
            continue
        prep = preps[rec["cik"]]
        v = gate1.value_company(prep, ctx, priors, rates, rec["shares"], n_draws=cfg.get("n_draws", gate1.N_DRAWS))
        rec["val"] = v
        rec["stamps"] = sorted(set(rec["stamps"]) | set(v.get("stamps", [])))
        if v["status"] == "ok":
            rec["status"] = "valued"
            p50 = v["iv_ps"]["p50"]
            rec["score"]["gate1_engine"] = p50 / rec["price"]
        else:
            rec["status"], rec["reasons"] = "refused", list(v["reasons"])
    t_alt = time.time()
    if cfg.get("erp_shifts") and d <= cfg.get("return_dates_end", RETURN_DATES_END):                  # registration v2 B5, reported: the same names with the premium shifted
        variants = [(f"erp{delta * 1e4:+.0f}bp", ShiftedErp(rates, delta)) for delta in cfg["erp_shifts"]]
        if rates.erp_basis == "engine_consistent":
            variants.append((DAMODARAN_LABEL, DamodaranErp(rates)))                                   # Addendum M: Damodaran's own premium, reported as the sensitivity
        for lab, sr in variants:
            for rec in recs:
                if rec["status"] != "valued":
                    continue
                va = gate1.value_company(preps[rec["cik"]], ctx, priors, sr, rec["shares"], n_draws=cfg.get("n_draws", gate1.N_DRAWS))
                rec.setdefault("score_alt", {})[lab] = (va["iv_ps"]["p50"] / rec["price"]) if va["status"] == "ok" else None
    for rec in recs:
        counts[rec["status"]] += 1
    summary = {"date": d, "rf": rf, "n_companies": len(ciks), "status": dict(counts), "seconds_pass1": t1 - t0, "seconds_erp": t1b - t1, "seconds_pass2": t_alt - t1b,
               "seconds_erp_shifts": time.time() - t_alt, "erp_basis": rates.erp_basis, "erp": (None if ce is None else ce.as_dict()),
               "de_p95_pooled": ctx.de_p95_pooled, "spread_pooled": ctx.spread_pooled, "n_industries_de": len(ctx.de_p95), "n_industries_spread": len(ctx.spread)}
    out_dir = Path(cfg["out_dir"])
    with gzip.open(out_dir / f"records_{d}.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(_clean(r)) + "\n")
    (out_dir / f"context_{d}.json").write_text(json.dumps(_clean(summary), indent=1), encoding="utf-8")
    pit.drop_cache()
    return summary


def _work(d):
    try:
        return run_date(d)
    except Exception as e:                     # a worker failure is stated, never papered over
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit-ciks", type=int)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--id-map", type=Path, default=DEFAULT_IDMAP)
    ap.add_argument("--prices", type=Path, default=DEFAULT_PRICES)
    ap.add_argument("--sic", type=Path, default=DEFAULT_SIC)
    ap.add_argument("--n-draws", type=int, default=gate1.N_DRAWS)
    ap.add_argument("--invalid-draw-max", type=float, default=None,
                    help="DIAGNOSTIC variant only: the share of invalid draws above which a name is refused (the registered rule, Addendum H5, is %s; 1.0 shows what the engine "
                         "does with no refusal)" % gate1.INVALID_DRAW_MAX)
    ap.add_argument("--priors-dir", type=Path, help="the priors vintages folder (default: valuation.priors_build.config.DATA_DIR)")
    ap.add_argument("--headers", type=Path, default=DEFAULT_HEADERS if DEFAULT_HEADERS.exists() else None, help="the EDGAR headers CSV (the SIC as filed; Addendum J11)")
    ap.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK if DEFAULT_CROSSWALK.exists() else None, help="the SIC -> Damodaran industry crosswalk (Addendum J11)")
    ap.add_argument("--prices-daily", type=Path, help="the D5 daily raw closes folder (data/prices_daily): valuation prices and daily outcomes (Addendum L4); REQUIRED for a holdout run")
    ap.add_argument("--delisting-index", type=Path, help="the D1 event index folder (data/sec_bulk/index): delisting events (Addendum L4); required for a holdout run")
    ap.add_argument("--delisting-docs", type=Path, help="the D3 delisting documents folder (data/sec_bulk/delisting_docs), read through the strict readers; required for a holdout run")
    ap.add_argument("--survivorship-cover", type=Path, help="the cover index folder (rebuild_harness.survivorship.build_cover_index): the missing-name census, the price proxy and their outcomes "
                    "(Addendum M1-M4); REQUIRED for a holdout run; needs --delisting-index")
    ap.add_argument("--no-prices-fallback", action="store_true", help="with --prices-daily: do NOT put the monthly raw file (--prices) behind a ticker whose D5 history starts late (Addendum M6; refused in a holdout run)")
    ap.add_argument("--max-cached-tickers", type=int, default=256, help="the lazy daily loader's LRU size per worker")
    ap.add_argument("--erp-basis", choices=ERP_BASES, default=ERP_BASIS,
                    help="the equity risk premium: engine_consistent (the registered default, Addenda L1/M) or damodaran (his own; a DIAGNOSTIC comparison, refused in a holdout run)")
    ap.add_argument("--no-erp-shifts", action="store_true", help="skip the +-1 pp equity-premium diagnostic scores (registration v2 B5)")
    ap.add_argument("--freeze", type=Path)
    a = ap.parse_args(argv)
    if a.survivorship_cover is not None and (a.delisting_index is None or a.prices_daily is None):
        ap.error("--survivorship-cover needs --delisting-index (the D1 events of the census) and --prices-daily (the price source that says who has no price at T)")
    dates = a.dates or dev_dates()
    lock = holdout.enforce(dates, [gate1_engine], a.freeze, inputs=freeze_inputs(a))       # FIRST: before any data is opened
    is_holdout = bool(lock["holdout_dates"])
    hold_check = holdout_inputs.require_holdout_configuration(dates, a) if is_holdout else None      # Addenda L3, L4: daily prices, D1 + D3, the SIC as filed for every date
    a.out_dir.mkdir(parents=True, exist_ok=True)
    idm = json.loads(a.id_map.read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if a.limit_ciks:
        ciks = ciks[:a.limit_ciks]
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in dates}                              # the dated FRED series, read once in the parent
    headers_copy = None
    if a.headers is not None:                                       # the headers download is still growing: a run reads one frozen copy of it
        headers_copy = a.out_dir / "headers_snapshot.csv"
        shutil.copyfile(a.headers, headers_copy)
    price_stamp = DAILY_PRICE_STAMP if a.prices_daily else PRICE_STAMP
    horizons = holdout_inputs.HOLDOUT_HORIZONS if is_holdout else HORIZONS
    outcomes_end = holdout_inputs.HOLDOUT_OUTCOMES_END if is_holdout else OUTCOMES_END
    return_end = holdout_inputs.HOLDOUT_RETURN_DATES_END if is_holdout else RETURN_DATES_END
    price_events, delist_report, delist_info = None, None, None
    if a.delisting_index is not None:                        # D1 + D3 through the strict readers: written once, read by every worker
        idx = delisting_inputs.EventIndex(a.delisting_index)
        docs = delisting_inputs.DelistingDocs(a.delisting_docs) if a.delisting_docs is not None else None
        tk_of = {}
        for t, c in idm.items():
            tk_of.setdefault(str(c).zfill(10), []).append(t)
        price_events, delist_report = delisting_inputs.build_price_events(idx, docs, lambda c: tk_of.get(str(c).zfill(10), []), since=min(dates))
        (a.out_dir / "price_events.json").write_text(json.dumps(price_events), encoding="utf-8")
        delist_info = {"index": idx.info(), "build_report": delist_report, "docs_completeness": None if docs is None else delisting_inputs.completeness(idx, docs, since=min(dates))}
    cfg = {"store": str(a.store), "id_map": str(a.id_map), "prices": str(a.prices), "sic": str(a.sic), "rf": rf, "ciks": ciks, "n_draws": a.n_draws,
           "prices_daily": str(a.prices_daily) if a.prices_daily else None, "price_stamp": price_stamp, "strict_classification": is_holdout, "max_cached_tickers": a.max_cached_tickers,
           "price_events": str(a.out_dir / "price_events.json") if price_events is not None else None, "horizons": list(horizons), "outcomes_end": outcomes_end.isoformat(),
           "return_dates_end": return_end,
           "out_dir": str(a.out_dir), "priors_dir": str(a.priors_dir) if a.priors_dir else None,
           "invalid_draw_max": a.invalid_draw_max, "headers": str(headers_copy) if headers_copy else None, "crosswalk": str(a.crosswalk) if a.crosswalk else None,
           "erp_shifts": [] if a.no_erp_shifts else list(ERP_SHIFTS), "erp_basis": a.erp_basis,
           "prices_fallback": str(a.prices) if (a.prices_daily and not a.no_prices_fallback) else None,
           "survivorship_cover": str(a.survivorship_cover) if a.survivorship_cover else None, "delisting_index": str(a.delisting_index) if a.delisting_index else None,
           "delisting_docs": str(a.delisting_docs) if a.delisting_docs else None}
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "dates": dates, "lock": lock, "n_ciks": len(ciks), "workers": a.workers,
            "n_draws": a.n_draws, "gate1_version": gate1.GATE1_VERSION, "price_stamp": price_stamp,
            "price_file": None if a.prices_daily else str(a.prices), "price_file_sha256": sha256_file(a.prices_daily / "manifest.csv") if a.prices_daily else sha256_file(a.prices),
            "price_file_meta": ({"source": "D5 daily raw closes (Yahoo, auto_adjust=False)", "folder": str(a.prices_daily), "entry": DAILY_ENTRY_FIELD, "file_sha256_is_the_manifest": True} if a.prices_daily else json.loads(a.prices.read_text(encoding="utf-8")).get("meta")),
            "mode": "holdout" if is_holdout else "development", "strict_classification": is_holdout, "holdout_configuration": hold_check, "delisting_inputs": delist_info,
            "horizons": list(horizons), "outcomes_end": outcomes_end.isoformat(),
            "priors_dir": str(a.priors_dir) if a.priors_dir else None, "invalid_draw_max": a.invalid_draw_max if a.invalid_draw_max is not None else gate1.INVALID_DRAW_MAX,
            "invalid_draw_max_is_the_registered_rule": a.invalid_draw_max is None,
            "git_head": holdout._git(REPO, "rev-parse", "HEAD").decode().strip(), "rf": {k: v[0] for k, v in rf.items()},
            "engine_files_sha256": {p.relative_to(REPO).as_posix(): holdout.sha256_file(p) for p in GATE1_FILES},
            "headers": sx.HeadersFile(headers_copy).info() if headers_copy else None,
            "crosswalk": ({"path": str(a.crosswalk), "sha256": sha256_file(a.crosswalk), "meta": sx.Crosswalk.load(a.crosswalk).meta} if a.crosswalk else None),
            "erp_shifts": cfg["erp_shifts"], "erp_basis": a.erp_basis, "return_dates_end": return_end}
    (a.out_dir / "run_meta.json").write_text(json.dumps(_clean(meta), indent=1), encoding="utf-8")
    t0 = time.time()
    with Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, dates):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(_clean(s))[:400], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

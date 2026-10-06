"""gate1.py - the gate-1 engine: one company, one valuation date, code only (no AI, no model, no network).

Per stock and date (registration `REGISTRATION_gate1_DRAFT.md` section 1):
  1. the engines' CompanyPIT from `pit_adapter.adapt` (inputs as known at T under the 16:00 ET rule, provenance refusals, industry stamped);
  2. classification (`classification.classification`) -> family;
  3. the population priors at T (`PopulationPriors`, vintage year(T)-1; the margin level five years on is drawn directly, Addendum H1);
  4. the discount rate at T: Damodaran files dated before T (beta, implied ERP), risk-free from the dated FRED series, Hamada relevering with the BOOK D/E
     (Addendum B 3), the cost of debt of Addendum B 5;
  5. the family engine with every judgment input at the prior's quantile function (the distribution's median is the value: the prior's P50 for every input,
     the engine's own mechanical inputs for everything else), and the P10..P90 of the value over the prior;
  6. the output: median value per share, P10..P90, the secondary cross-check, model disagreement, the terminal-value share, family and stamps.

The value is PER SHARE at T on the share basis of the unadjusted close: equity value / the share count the layer puts on the price's split basis.

POPULATION CONTEXT.  Two rules of Addendum B need a population measured at the same date, so a date is run in two passes: (1) every company is prepared
(adapter, classification, state); (2) the context is measured from that cross-section and every company is valued.
  * Book D/E: when parent equity is not positive, or the company's book D/E exceeds the 95th percentile of the book D/E of the companies of its Damodaran
    industry on the date (at least `DE_MIN_N` of them; else the pooled cross-section, stamped), Damodaran's industry D/E of the betas file in force is used
    instead, stamped.
  * Cost of debt: a company with debt and no clean interest line (interest / average debt not measurable) gets risk-free + the median spread
    (interest / average debt - risk-free) measured on the same industry's companies on the date (at least `SPREAD_MIN_N`; else pooled), stamped.
    "Same year" is read as the same cross-section: every base fiscal year here is the latest annual report filed before the date.
Nothing is silently dropped: every company ends in a record with a status and reasons.
"""
from __future__ import annotations

import math
import pickle
import statistics
import zlib
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from . import classification, common, engine_commodity, engine_financial, engine_operating
from .common import DataNotPresent, InputError, build_state, parse_date
from .discount_rate import DamodaranStore, discount_rate_for_state, parse_betas_rows
from .priors_interface import PriorSet, Priors

GATE1_VERSION = "1"
N_DRAWS = 2000
MCAP_FLOOR = 300e6
DE_MIN_N = 20
SPREAD_MIN_N = 10
DE_PERCENTILE = 0.95
FAMILY_ENGINES = {"operating": engine_operating, "commodity": engine_commodity, "financial": engine_financial}


def seed_for(cik, asof) -> int:
    """A deterministic seed per company and date (no two companies share a draw sequence)."""
    return (int(str(cik)) * 1000003 + parse_date(asof).toordinal()) % (2 ** 31 - 1)


def pack(obj) -> bytes:
    return zlib.compress(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL), 3)


def unpack(blob: bytes):
    return pickle.loads(zlib.decompress(blob))


# ---- the rates of a date ----------------------------------------------------------------------------------------------------------

class Rates:
    """Risk-free (a dated value handed in), Damodaran beta and implied ERP (`DamodaranStore`, no look-ahead, hashes recorded), and the industry row of
    the betas file in force (unlevered beta corrected for cash and the industry's D/E)."""

    def __init__(self, store: DamodaranStore, rf_by_date: Dict[str, tuple]):
        self.store = store
        self.rf_by_date = {str(k)[:10]: v for k, v in rf_by_date.items()}
        self._beta = store.beta_provider()
        self._erp = store.erp_provider()
        self._tables = {}
        self._erp_cache = {}

    def rf(self, asof):
        k = parse_date(asof).isoformat()
        if k not in self.rf_by_date:
            raise DataNotPresent(f"no risk-free rate prepared for {k}")
        return self.rf_by_date[k]

    def erp(self, asof):
        k = parse_date(asof).isoformat()
        if k not in self._erp_cache:
            self._erp_cache[k] = self._erp(k)
        return self._erp_cache[k]

    def beta(self, asof, industry):
        return self._beta(asof, industry)

    def industry_row(self, asof, industry) -> dict:
        """The industry's row of the newest betas file dated before `asof`: {"beta_unlevered", "de_ratio", "tax", "firms", "file"}."""
        asof_d = parse_date(asof)
        ok = [e for e in self.store.beta_snapshots() if e["date"] < asof_d]
        if not ok:
            raise DataNotPresent(f"no betas file dated before {asof_d}")
        e = ok[-1]
        if e["file"] not in self._tables:
            self._tables[e["file"]] = parse_betas_rows(e["_rows"])
        t = self._tables[e["file"]]
        if industry not in t:
            raise DataNotPresent(f"industry {industry!r} is not in {e['file']}")
        return dict(t[industry], file=e["file"])


# ---- the population of a date ----------------------------------------------------------------------------------------------------------

def _pctl(xs: List[float], p: float) -> float:
    return common.quantile_of(xs, p)


@dataclass
class DateContext:
    asof: str
    rf: float
    de_p95: Dict[str, tuple] = field(default_factory=dict)       # industry -> (value, n)
    de_p95_pooled: Optional[tuple] = None
    spread: Dict[str, tuple] = field(default_factory=dict)       # industry -> (median spread, n)
    spread_pooled: Optional[tuple] = None

    @classmethod
    def build(cls, asof, rf: float, rows: List[dict]) -> "DateContext":
        """rows: one dict per prepared company with `industry`, `de_book` (None when not measurable) and `kd_effective` (None when not measurable)."""
        ctx = cls(parse_date(asof).isoformat(), rf)
        by_ind_de: Dict[str, List[float]] = {}
        by_ind_sp: Dict[str, List[float]] = {}
        all_de, all_sp = [], []
        for r in rows:
            ind = r.get("industry")
            de, kd = r.get("de_book"), r.get("kd_effective")
            if de is not None and math.isfinite(de) and de >= 0:
                all_de.append(de)
                if ind:
                    by_ind_de.setdefault(ind, []).append(de)
            if kd is not None and math.isfinite(kd) and kd > 0:
                all_sp.append(kd - rf)
                if ind:
                    by_ind_sp.setdefault(ind, []).append(kd - rf)
        for ind, xs in by_ind_de.items():
            ctx.de_p95[ind] = (_pctl(xs, DE_PERCENTILE), len(xs))
        for ind, xs in by_ind_sp.items():
            ctx.spread[ind] = (statistics.median(xs), len(xs))
        if all_de:
            ctx.de_p95_pooled = (_pctl(all_de, DE_PERCENTILE), len(all_de))
        if all_sp:
            ctx.spread_pooled = (statistics.median(all_sp), len(all_sp))
        return ctx

    def de_threshold(self, industry):
        """(P95 of the industry's book D/E, n, "industry"|"pooled") or (None, 0, None)."""
        v = self.de_p95.get(industry)
        if v is not None and v[1] >= DE_MIN_N:
            return v[0], v[1], "industry"
        if self.de_p95_pooled is not None:
            return self.de_p95_pooled[0], self.de_p95_pooled[1], "pooled"
        return None, 0, None

    def kd_spread(self, industry):
        v = self.spread.get(industry)
        if v is not None and v[1] >= SPREAD_MIN_N:
            return v[0], v[1], "industry"
        if self.spread_pooled is not None:
            return self.spread_pooled[0], self.spread_pooled[1], "pooled"
        return None, 0, None


# ---- the discount rate of a company -------------------------------------------------------------------------------------------------------

def make_discount(st: dict, asof, family: str, industry: Optional[str], ctx: DateContext, rates: Rates):
    """(DiscountRate, stamps).  DataNotPresent when it cannot be measured: a refusal with its reason, never a default."""
    stamps: List[str] = []
    if not industry:
        raise DataNotPresent("industry_unmapped: no Damodaran industry for the company (the current-dated industry file does not list it)")
    row = rates.industry_row(asof, industry)
    de_book = st.get("de_book")
    if de_book is not None and de_book < 0:
        raise DataNotPresent(f"book D/E is negative ({de_book:.3g}): the filed debt measures as negative")
    de_used, basis = de_book, "book"
    thr, n_thr, how = ctx.de_threshold(industry)
    if de_book is None:
        eq = st.get("equity")
        stamps.append("de_industry: parent equity not positive" if (eq is not None and eq <= 0) else "de_industry: book D/E not measurable (parent equity not filed)")
        de_used, basis = row["de_ratio"], "industry_damodaran"
    elif thr is not None and de_book > thr:
        stamps.append(f"de_industry: book D/E {de_book:.2f} above the {DE_PERCENTILE:.0%} of its {how} cross-section {thr:.2f} (n={n_thr})")
        de_used, basis = row["de_ratio"], "industry_damodaran"
    if de_used is None:
        raise DataNotPresent("the industry's D/E is not in the Damodaran betas file")
    st2 = dict(st)
    rf = ctx.rf
    if st.get("kd_effective") is None and de_used > 0:
        sp, n_sp, how_sp = ctx.kd_spread(industry)
        if sp is not None:
            st2["kd_effective"] = rf + sp
            st2["kd_basis"] = f"risk-free + median population spread ({how_sp}, n={n_sp})"
            stamps.append(f"kd_population_spread: {how_sp}, n={n_sp}, spread={sp:.4f}")
        elif family == "financial":
            st2["kd_effective"] = rf
            stamps.append("kd_not_used_by_the_financial_engine: set to the risk-free rate only so that WACC (unused) is defined")
    disc = discount_rate_for_state(st2, asof, industry=industry, rf_provider=rates.rf, beta_provider=rates.beta, erp_provider=rates.erp,
                                   de_ratio=de_used, de_basis=basis)
    return disc, stamps


# ---- pre-built priors ----------------------------------------------------------------------------------------------------------------------

class PreBuiltPriors(Priors):
    def __init__(self, ps: PriorSet):
        self._ps = ps

    def for_company(self, family, state, asof):
        return self._ps


# ---- pass 1: prepare ------------------------------------------------------------------------------------------------------------------------

def prepare(adapt_result) -> dict:
    """Classification and the state of one adapted company: the compact fields the population context needs, and the packed CompanyPIT for pass 2.
    {"status": "prepared" | "refused" | "family_not_built" | "unclassifiable", "reasons": [...], "family", ...}"""
    out = {"cik": adapt_result.cik, "status": None, "reasons": [], "family": None, "family_reason": None, "conflicts": [], "industry": adapt_result.industry,
           "stamps": list(adapt_result.stamps), "provenance": adapt_result.provenance, "de_book": None, "kd_effective": None, "blob": None}
    if not adapt_result.ok:
        out["status"], out["reasons"] = "refused", list(adapt_result.refusals)
        return out
    pit = adapt_result.company
    cl = classification.classification(pit.ticker, pit.asof, pit)
    out["family"], out["family_reason"], out["conflicts"] = cl["family"], cl["reason"], cl["conflicts"]
    out["sic"] = (cl.get("sic") or {}).get("code")
    out["classification_tests"] = {k: cl["tests"].get(k) for k in ("insurance_reserve_share", "lending_book_share", "insurance_test", "lending_test")}
    fam = cl["family"]
    if fam is None:
        out["status"], out["reasons"] = "unclassifiable", [cl["reason"]]
        return out
    if fam == "family_not_built":
        out["status"], out["reasons"] = "family_not_built", [cl["reason"]]
        return out
    st = build_state(pit)
    out["de_book"], out["kd_effective"] = st.get("de_book"), st.get("kd_effective")
    out["status"] = "prepared"
    out["blob"] = pack(pit)
    return out


# ---- pass 2: value ---------------------------------------------------------------------------------------------------------------------------

def _per_share(summary: Optional[dict], shares: float, keys=("p10", "p25", "p50", "p75", "p90")) -> Optional[dict]:
    if summary is None:
        return None
    return {k: summary[k] / shares for k in keys}


def value_company(prep: dict, ctx: DateContext, priors, rates: Rates, shares: Optional[float], n_draws: int = N_DRAWS) -> dict:
    """Value one prepared company.  Returns a dict with `status` "ok" or "refused" (reasons named) and, when ok, every output of the registration."""
    out = {"status": None, "reasons": [], "stamps": list(prep["stamps"])}
    pit = unpack(prep["blob"])
    asof = pit.asof
    family = prep["family"]
    st = build_state(pit)
    if st.get("read_as_none"):
        out["read_as_none"] = list(st["read_as_none"])
    try:
        disc, dstamps = make_discount(st, asof, family, prep["industry"], ctx, rates)
    except (DataNotPresent, InputError) as e:
        out["status"], out["reasons"] = "refused", [f"discount_rate: {str(e)[:200]}"]
        return out
    out["stamps"] += dstamps
    ps = priors.for_company(family, st, asof)
    out["prior_source"] = ps.source
    if ps.source == "UNAVAILABLE":
        out["status"], out["reasons"] = "refused", ["priors_unavailable: " + "; ".join(ps.meta.get("unavailable", []))[:200]]
        return out
    corr = ps.meta.get("corr") or None
    seed = seed_for(pit.cik or prep["cik"], asof)
    mod = FAMILY_ENGINES[family]
    kwargs = dict(n_draws=n_draws, seed=seed, corr=corr)
    if family == "operating":
        kwargs["state"] = st
    fixed = PreBuiltPriors(ps)
    def run_engine(kw):
        return mod.run(pit, fixed, disc, **kw)
    try:
        try:
            res = run_engine(kwargs)
        except InputError as e:
            if corr is None or "positive definite" not in str(e):
                raise
            out["stamps"].append("corr_not_positive_definite: inputs drawn independently")
            kwargs["corr"] = None
            res = run_engine(kwargs)
    except InputError as e:
        out["status"], out["reasons"] = "refused", [f"engine_input_error: {str(e)[:160]}"]
        return out
    except (KeyError, ZeroDivisionError, ValueError, ArithmeticError, DataNotPresent) as e:   # an unexpected engine failure is a named refusal, never a lost date
        out["status"], out["reasons"] = "refused", [f"engine_exception: {type(e).__name__}: {str(e)[:160]}"]
        return out
    if res.get("status") != "ok":
        out["status"], out["reasons"] = "refused", list(res.get("reasons", ["engine refused"]))
        miss = ps.meta.get("unavailable") or []
        if miss and any("priors do not supply" in r for r in out["reasons"]):
            out["reasons"].append("prior unavailable: " + "; ".join(miss)[:200])
        return out
    dist = res["distribution"]
    if dist["equity"] is None or not shares or shares <= 0:
        out["status"] = "refused"
        out["reasons"] = ["all_draws_invalid: " + "; ".join(f"{k} x{v}" for k, v in (dist.get("invalid_reasons") or {}).items())[:200]] if dist["equity"] is None else ["shares_unavailable"]
        return out
    iv = _per_share(dist["equity"], shares)
    sec_eq = None
    sec_kind = None
    if family == "commodity":
        sec = res.get("secondary") or {}
        sec_eq, sec_kind = sec.get("equity"), sec.get("kind")
        sec_ps = None if sec_eq is None else sec_eq / shares
    elif dist.get("secondary_equity") is not None:
        sec_ps = dist["secondary_equity"]["p50"] / shares
        sec_kind = "population_ev_fcf_multiple" if family == "operating" else "population_price_to_tangible_book"
    else:
        sec_ps = None
    at = res.get("at_median_inputs") or {}
    point_ps = (at["equity"] / shares) if "equity" in at else None
    first = (at.get("years") or [None])[0]
    meta = ps.meta
    inputs_summary = {k: {"p10": v["p10"], "p50": v["p50"], "p90": v["p90"]} for k, v in res.get("inputs", {}).items()}
    out.update({
        "status": "ok", "family": family, "base_period": res["base_period"], "base_filed": res["base_filed"], "base_accession": res["base_accession"],
        "iv_ps": iv, "iv_point_p50_inputs_ps": point_ps, "secondary_ps": sec_ps, "secondary_kind": sec_kind,
        "model_disagreement": res.get("model_disagreement"), "model_disagreement_note": res.get("model_disagreement_note"),
        "tv_share_p50": (dist["tv_share"]["p50"] if dist.get("tv_share") else None),
        "tv_share_p50_point": at.get("tv_share"),
        "n_draws": dist["n_draws"], "n_valid": dist["n_valid"], "invalid_reasons": dist.get("invalid_reasons") or {},
        "share_negative_equity": dist.get("share_negative_equity"),
        "inputs": inputs_summary,
        "forecast": {"g1_p50": res["inputs"]["g1"]["p50"] if "g1" in res.get("inputs", {}) else None,
                     "year1_growth_point": (first or {}).get("growth"), "year1_margin_point": (first or {}).get("margin") if family != "financial" else None,
                     "year1_rote_point": (first or {}).get("rote") if family == "financial" else None},
        "terminal_year": ({"margin": at["years"][-1]["margin"], "growth": at["years"][-1]["growth"]} if at.get("years") and family != "financial" else None),
        "margin_path": at.get("margin_path"),
        "terminal_growth": {"base": (res.get("terminal_growth") or {}).get("base"), "at_p50_inputs": at.get("terminal_growth")},
        "discount": {k: getattr(disc, k) for k in ("rf", "erp", "beta_unlevered", "beta_levered", "de_ratio", "de_basis", "tax", "kd_pretax", "coe", "wacc")},
        "discount_sources": {"beta": disc.sources.get("beta"), "beta_file_sha256": (disc.sources.get("beta_meta") or {}).get("file_sha256"),
                             "erp": disc.sources.get("erp"), "erp_file_sha256": (disc.sources.get("erp_meta") or {}).get("file_sha256"),
                             "rf": disc.sources.get("rf")},
        "prior_meta": {"vintage": meta.get("vintage"), "fallbacks": list(meta.get("fallbacks", [])), "unavailable": list(meta.get("unavailable", [])),
                       "flags_n": len(meta.get("flags", [])), "margin_target": (meta.get("cells") or {}).get("margin_target"),
                       "cyc_score": meta.get("cyc_score"), "mechanical_baseline_g1": (meta.get("mechanical_baseline") or {}).get("g1"),
                       "corr_used": bool(kwargs["corr"])},
        "state": {"revenue": st.get("revenue"), "op_margin": st.get("op_margin"), "op_margin_median": st.get("op_margin_median"),
                  "growth_latest": st.get("growth_latest"), "tax_rate": st.get("tax_rate"), "de_book": st.get("de_book"), "kd_effective": st.get("kd_effective"),
                  "tbv": st.get("tbv"), "rote_latest": st.get("rote_latest"), "rote_median": st.get("rote_median"), "cyclicality": (st.get("cyclicality") or {}).get("score"),
                  "years_held": st.get("years_held"), "maint_gap_ratio": st.get("maint_gap_ratio"), "nwc_ratio": st.get("nwc_ratio")},
        "notes": list(res.get("notes", [])),
    })
    if res.get("normalization"):
        out["normalization"] = res["normalization"]
    if res.get("consistency"):
        out["consistency"] = res["consistency"]
    return out

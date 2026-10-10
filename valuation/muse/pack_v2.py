"""pack_v2.py - the pack, version 2: five sections built only from the point-in-time layer at T (SPEC_muse_passes section 1).

HEADER      Analysis date: <T>, the company name and ticker as of T, the family and the industry. NOTHING else about dates or data availability.
F           filed annual figures, up to 10 fiscal years known at T (from `CompanyPIT`, i.e. valuation/pit_data.py: first filed, strictly before T, own annual
            report). Each cell's provenance (tag, form, accession, filed) is in `Pack.provenance` / the manifest, an appendix that no prompt shows.
Q           the latest quarters known at T (a `QuarterSource`; the shared layer stores no quarterly facts, so none is built without one: the section is then
            absent and the manifest says so; no prompt says anything about it).
D           verbatim excerpts of the company's own documents (a `DocumentSource`; every item is re-checked here against the 16:00 ET acceptance cutoff,
            whatever its source claims; an item that fails is dropped and recorded).
S           the company's state, from `common.build_state`: size, growth delivered, margin and its deviation from the 8-year median, cyclicality score,
            return on capital (and, for financials, return on tangible equity).
R           for each judgment input, the population prior P5..P95 from the priors object (conditioned on S) and the company's mechanical baseline
            (growth year 1 by the trailing 3-year CAGR, margin held, return on tangible equity held).

Nothing here takes a price, a market cap, a return, a target, consensus, a valuation or a news item: the builder has no argument that could carry one.
The manifest (never shown to a model) records the identity sources, every document item with its accession and acceptance timestamp, the prior's
source label and placeholder flag, and the stamps (for example a SIC code that is today's, not the one filed at T).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from valuation import pit_data as pdm
from valuation.common import CompanyPIT, FIELDS, QuantileDist, build_state
from valuation.priors_interface import PriorSet

from .documents import DocItem, DocumentSource, QuarterSource, eligibility
from .mapping import percentile_of
from .schema import PACK_VERSION, PROMPT_SECTIONS, muse_inputs, prior_distribution

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
F_YEARS = 10

FIELD_LABELS = (
    ("revenue", "Revenue"), ("operating_income", "Operating income"), ("pretax_income", "Pre-tax income"), ("tax_provision", "Income tax expense"),
    ("net_income", "Net income"), ("da", "Depreciation and amortization"), ("amortization_intangibles", "Amortization of intangibles"),
    ("interest_expense", "Interest expense"), ("capex", "Capital expenditure"), ("ocf", "Operating cash flow"), ("cash", "Cash"),
    ("st_investments", "Short-term investments"), ("lt_investments", "Long-term investments"), ("current_assets", "Current assets"),
    ("current_liabilities", "Current liabilities"), ("ppe_net", "Property, plant and equipment (net)"), ("goodwill", "Goodwill"),
    ("intangibles_ex_goodwill", "Intangibles excluding goodwill"), ("total_assets", "Total assets"), ("total_liabilities", "Total liabilities"),
    ("debt_current", "Current debt"), ("short_term_borrowings_separate", "Short-term borrowings"), ("debt_lt_noncurrent", "Long-term debt"),
    ("finance_lease_liability", "Finance lease liability"), ("operating_lease_liability", "Operating lease liability"),
    ("equity", "Parent equity"), ("equity_incl_nci", "Equity including noncontrolling interest"), ("preferred_equity", "Preferred equity"),
    ("insurance_reserves", "Insurance reserves"))
assert {f for f, _ in FIELD_LABELS} == set(FIELDS)

LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def input_texts() -> dict:
    return json.loads((PROMPT_DIR / "inputs.json").read_text(encoding="utf-8"))


def pct(x: Optional[float], digits: int = 1, sign: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def amount(v: Optional[float], unit: float) -> str:
    return "n/a" if v is None else f"{v / unit:,.1f}"


def cagr(series: Mapping[str, float], n: int) -> Optional[float]:
    ps = sorted(series)
    if len(ps) < n + 1:
        return None
    a, b = series[ps[-1 - n]], series[ps[-1]]
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return (b / a) ** (1.0 / n) - 1.0


@dataclass
class Pack:
    asof: str
    family: str
    header: str
    sections: Dict[str, str]
    r: Dict[str, str]
    provenance: List[dict]
    manifest: dict

    def sections_for(self, prompt: str, inputs: Optional[Sequence[str]] = None) -> Dict[str, str]:
        """The section texts a prompt shows, by section letter. R holds only `inputs` (all of the pack's R when None)."""
        out: Dict[str, str] = {}
        for s in PROMPT_SECTIONS[prompt]:
            if s == "R":
                names = list(self.r) if inputs is None else [i for i in inputs if i in self.r]
                if names:
                    out["R"] = "\n\n".join(self.r[n] for n in names)
            elif s in self.sections:
                out[s] = self.sections[s]
        return out


# ---- F -----------------------------------------------------------------------------------------------------------------------------

def _currency(pit: CompanyPIT) -> str:
    for n in pit.notes:
        if str(n).startswith("reporting_currency:"):
            return str(n).split(":", 1)[1]
    return "USD"


def build_f(pit: CompanyPIT, years: int = F_YEARS):
    periods = pit.periods()[-years:]
    rows = pit.rows()
    big = max([abs(v) for p in periods for v in rows[p].values() if v is not None] or [0.0])
    unit = 1e6 if big >= 1e7 else 1.0
    ccy = _currency(pit)
    lines = [f"Annual figures as filed, {ccy} {'millions' if unit == 1e6 else 'units'}; one column per fiscal year, headed by the period end date.",
             "Item | " + " | ".join(periods)]
    prov = []
    for fld, label in FIELD_LABELS:
        vals = [rows[p][fld] for p in periods]
        if all(v is None for v in vals):
            continue
        lines.append(f"{label} | " + " | ".join(amount(v, unit) for v in vals))
        for p in periods:
            tr = pit.filing_trail(fld, p)
            if tr is not None:
                prov.append({"field": fld, "period_end": p, "value": tr.value, "tag": tr.tag, "form": tr.form, "filed": tr.filed,
                             "accession": tr.accession})
    return "\n".join(lines), prov, unit


# ---- Q -----------------------------------------------------------------------------------------------------------------------------

def build_q(rows: Sequence[dict], asof, unit: float, ccy: str):
    kept, dropped = [], []
    for r in rows:
        (kept if eligibility(r.get("accepted_at"), r["filed"], asof) == "ok" else dropped).append(r)
    if not kept:
        return None, kept, dropped
    lines = [f"Latest quarters as filed (three months ended), {ccy} {'millions' if unit == 1e6 else 'units'}; the same quarter a year earlier is the "
             f"comparative column of the same filing.",
             "Quarter end | Revenue | Revenue, year earlier | Operating income | Operating income, year earlier | Net income | Net income, year earlier"]
    for r in kept:
        v, p = r["values"], r.get("prior_year") or {}
        lines.append(f"{r['period_end']} | " + " | ".join(amount(x, unit) for x in (
            v.get("revenue"), p.get("revenue"), v.get("operating_income"), p.get("operating_income"), v.get("net_income"), p.get("net_income"))))
    return "\n".join(lines), kept, dropped


# ---- D -----------------------------------------------------------------------------------------------------------------------------

def build_d(items: Sequence[DocItem], asof):
    kept, dropped = [], []
    for it in items:
        (kept if eligibility(it.accepted_at, it.filed, asof) == "ok" else dropped).append(it)
    if not kept:
        return None, kept, dropped
    parts = []
    for n, it in enumerate(kept, 1):
        per = f", {it.period}" if it.period else ""
        parts.append(f"[D{n}] {it.title}, filed {it.filed}{per}\n{it.text}")
    return "\n\n".join(parts), kept, dropped


# ---- S -----------------------------------------------------------------------------------------------------------------------------

def build_s(st: dict, family: str, unit: float):
    lines = [f"Size: revenue {amount(st.get('revenue'), unit)}; total assets {amount(st.get('total_assets'), unit)} (latest fiscal year, same units as the "
             f"annual figures)."]
    rev = st.get("revenue_series") or {}
    lines.append(f"Growth delivered: revenue growth in the latest fiscal year {pct(st.get('growth_latest'), sign=True)}; 3-year compound growth "
                 f"{pct(cagr(rev, 3), sign=True)}; 5-year compound growth {pct(cagr(rev, 5), sign=True)}.")
    m, med = st.get("op_margin"), st.get("op_margin_median")
    dev = None if (m is None or med is None) else (m - med)
    lines.append(f"Operating margin: latest fiscal year {pct(m)}; median of the last {st.get('op_margin_years')} years {pct(med)}; deviation of the latest "
                 f"year from that median {'n/a' if dev is None else f'{dev * 100:+.1f} points'}.")
    cyc = st.get("cyclicality")
    if cyc is not None:
        c = cyc["components"]
        lines.append(f"Cyclicality score: {cyc['score']:.2f} on a 0 to 1 scale (higher means more cyclical); components: margin volatility "
                     f"{c['margin_volatility']:.2f}, margin reversal frequency {c['reversal_frequency']:.2f}, margin autocorrelation "
                     f"{c['autocorrelation']:.2f}, revenue cyclicality {c['revenue_cyclicality']:.2f}.")
    else:
        lines.append("Cyclicality score: not computable (too few annual years).")
    if family == "financial":
        lines.append(f"Return on tangible equity: latest fiscal year {pct(st.get('rote_latest'))}; median of the held years {pct(st.get('rote_median'))}.")
    else:
        oi, tax = st.get("operating_income"), st.get("tax_rate")
        eq, debt, cash = st.get("equity"), st.get("debt"), st.get("cash")
        ic = None
        if None not in (eq, debt, cash):
            sti = st.get("st_investments")
            ic = eq + (st.get("nci") or 0.0) + debt - cash - (0.0 if sti is None else sti)
        roic = None
        if oi is not None and tax is not None and ic is not None and ic > 0:
            roic = (oi - tax * max(oi, 0.0)) / ic
        lines.append(f"Return on capital: after-tax operating profit divided by year-end invested capital (equity plus debt less cash and short-term "
                     f"investments) {pct(roic)}.")
    lines.append(f"Years of annual history held: {st.get('years_held')}.")
    return "\n".join(lines)


# ---- R -----------------------------------------------------------------------------------------------------------------------------

def mechanical_baseline(name: str, st: dict) -> Optional[float]:
    """The company's own mechanical baseline for an input (growth year 1 = trailing 3-year CAGR, margin held, return on tangible equity held, a gap
    that never closes); None where the module has no such baseline."""
    if name == "g1":
        return cagr(st.get("revenue_series") or {}, 3)
    if name == "margin_target":
        return st.get("op_margin")
    if name == "rote_target":
        return st.get("rote_latest")
    if name in ("margin_retention", "rote_retention"):
        return 1.0
    return None


def build_r(name: str, dist: QuantileDist, st: dict) -> str:
    texts = input_texts()[name]
    given = {round(p, 6) for p, _ in dist.q}
    cells = []
    for lv in LEVELS:
        mark = "" if round(lv, 6) in given else "~"
        cells.append(f"P{lv * 100:g} {pct(dist.ppf(lv))}{mark}")
    lines = [f"[R {name}] {texts['label']} ({texts['unit']}); companies in a similar state:", "  " + " | ".join(cells)]
    if any(round(lv, 6) not in given for lv in LEVELS):
        lines.append("  (~ interpolated or extrapolated between the quantiles measured)")
    base = mechanical_baseline(name, st)
    if base is not None:
        what = {"g1": "trailing 3-year compound growth", "margin_target": "today's margin held", "rote_target": "today's return held",
                "margin_retention": "the gap never closes", "rote_retention": "the gap never closes"}[name]
        lines.append(f"  Mechanical baseline ({what}): {pct(base)}, which sits at about P{percentile_of(dist, base) * 100:.0f} of this distribution.")
    return "\n".join(lines)


# ---- the pack ------------------------------------------------------------------------------------------------------------------------

def header_text(asof, identity: Mapping, family: str) -> str:
    who = identity.get("name") if identity.get("ticker") is None else f"{identity.get('name')} ({identity.get('ticker')})"
    return (f"Analysis date: {pdm.to_date(asof).isoformat()}\nCompany: {who}\n"
            f"Family: {family}\nIndustry: {identity.get('industry') or 'not classified'}")


def ticker_as_of_t(identity: Mapping, d_text: Optional[str]) -> dict:
    """Addendum AD.10: a ticker that is not stamped as of T is shown only when it appears in a document accepted before T (section D, whose items pass the
    16:00 ET acceptance check); otherwise it is withheld. Today's ticker can carry a later corporate change (Ambac shown as OSG and OPENLANE as OPLN in
    gate-2 run 1)."""
    ident = dict(identity)
    t = ident.get("ticker")
    if ident.get("ticker_source") == "as_of_T" or t is None:
        return ident
    if d_text and re.search(r"(?<![A-Za-z])" + re.escape(str(t)) + r"(?![A-Za-z])", d_text):
        ident["ticker_source"] = "verified_in_filing"
    else:
        ident["ticker"], ident["ticker_source"], ident["ticker_withheld"] = None, "withheld", t
    return ident


def build_pack(pit: CompanyPIT, family: str, identity: Mapping, prior_set: PriorSet, *, state: Optional[dict] = None,
               documents: Optional[DocumentSource] = None, quarters: Optional[QuarterSource] = None, cik: Optional[str] = None) -> Pack:
    """The pack at `pit.asof`. `identity` = {name, ticker, industry, name_source, ticker_source, industry_source}; the name and ticker are those AS OF T
    (the caller takes them from the layer's header history), never today's record; the sources are recorded in the manifest."""
    pit.check()
    asof = pit.asof.isoformat()
    st = state if state is not None else build_state(pit)
    stamps: List[str] = []
    sections: Dict[str, str] = {}
    f_text, prov, unit = build_f(pit)
    sections["F"] = f_text
    ccy = _currency(pit)
    mf: dict = {"pack_version": PACK_VERSION, "asof": asof, "family": family, "identity": dict(identity), "stamps": stamps,
                "prior_source": prior_set.source, "prior_placeholder": bool(prior_set.placeholder), "pit_notes": list(pit.notes),
                "state_missing": list(st.get("missing", [])), "unit": "millions" if unit == 1e6 else "units"}
    if pit.sic is not None and not pit.sic.point_in_time:
        stamps.append("SIC is the current SEC assignment, not the one filed at T (industry label is today's)")
    if str(identity.get("name_source")) != "as_of_T":
        stamps.append(f"company name is not stamped as of T (source: {identity.get('name_source')})")
    # Q
    q_rows = quarters.quarters(cik or pit.cik, pit.asof) if quarters is not None else []
    q_text, q_kept, q_dropped = build_q(q_rows, pit.asof, unit, ccy) if q_rows else (None, [], [])
    if q_text is not None:
        sections["Q"] = q_text
    mf["quarters"] = {"source": type(quarters).__name__ if quarters is not None else None, "used": [(r["period_end"], r["accession"]) for r in q_kept],
                      "dropped_after_cutoff": [(r["period_end"], r["accession"]) for r in q_dropped]}
    if q_text is None:
        stamps.append("section Q absent: no quarterly source" if quarters is None else "section Q absent: no quarter known at T")
    # D
    d_items, d_notes = (documents.items(cik or pit.cik, pit.asof) if documents is not None else ([], ["no document source"]))
    d_text, d_kept, d_dropped = build_d(d_items, pit.asof)
    if d_text is not None:
        sections["D"] = d_text
    mf["documents"] = {"source": type(documents).__name__ if documents is not None else None, "used": [i.as_manifest() for i in d_kept],
                       "dropped_after_cutoff": [i.as_manifest() for i in d_dropped], "notes": list(d_notes)}
    if d_text is None:
        stamps.append("section D absent: " + ("no document source" if documents is None else "no document accepted before the cutoff"))
    identity = ticker_as_of_t(identity, d_text)                      # Addendum AD.10: shown only when a document accepted before T names it
    mf["identity"] = dict(identity)
    if identity.get("ticker_source") == "withheld":
        stamps.append(f"ticker withheld: {identity.get('ticker_withheld')} is not found in any document accepted before T")
    sections["S"] = build_s(st, family, unit)
    # R
    r: Dict[str, str] = {}
    for name in muse_inputs(family):
        dist = prior_distribution(prior_set, name, st)
        if dist is None:
            stamps.append(f"input {name}: the priors supply no distribution; not asked of Muse (the engine keeps the prior's own value or curve)")
            continue
        r[name] = build_r(name, dist, st)
    header = header_text(asof, identity, family)
    for k, v in sections.items():
        mf.setdefault("sections", {})[k] = {"chars": len(v), "sha256": sha256_text(v)}
    mf["r_inputs"] = list(r)
    mf["header_sha256"] = sha256_text(header)
    return Pack(asof, family, header, sections, r, prov, mf)

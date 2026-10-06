"""Test fixtures for valuation.muse: a synthetic company, PLACEHOLDER priors, and a scripted mock model.

EVERYTHING HERE IS TEST-ONLY. The priors are `PlaceholderPriors` round numbers (flagged placeholder=True, source PLACEHOLDER_NOT_A_MEASUREMENT) plus
arbitrary curve-position distributions; the discount rates are `PlaceholderRates`; the company is synthetic; the "model" is a mock that builds its answers from
the very prompt it receives. No value produced from these is a valuation.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from valuation.common import CompanyPIT, Filed, QuantileDist, SicInfo
from valuation.discount_rate import PlaceholderRates, discount_rate_for_state
from valuation.muse.documents import DocItem, StaticDocuments, StaticQuarters
from valuation.priors_interface import PLACEHOLDER_LABEL, PlaceholderPriors

ASOF = "2026-04-15"
PRICE_SENTINEL = 8731.43
MCAP_SENTINEL = 873143000.0


def make_pit(asof=ASOF, first=2016, years=10, sic="3674", ticker="SYN", shares=100.0, growth=0.06, margin=0.15, debt=300.0, drop=()):
    """A synthetic CompanyPIT: one annual report per year, each filed 60 days after its year end; `drop` = fields never filed."""
    series: Dict[str, Dict[str, Filed]] = {}
    reports = []
    last_pe = last_filed = None
    for i, y in enumerate(range(first, first + years)):
        pe = f"{y}-12-31"
        filed = (date.fromisoformat(pe) + timedelta(days=60)).isoformat()
        if date.fromisoformat(filed) >= date.fromisoformat(str(asof)[:10]):
            break
        rev = 1000.0 * (1 + growth) ** i * (1 + 0.03 * math.sin(i))
        oi = rev * (margin + 0.02 * math.cos(1.3 * i))
        pretax = oi - 10.0
        vals = {"revenue": rev, "operating_income": oi, "pretax_income": pretax, "tax_provision": 0.25 * pretax, "net_income": 0.75 * pretax,
                "da": 0.04 * rev, "capex": 0.06 * rev, "ppe_net": 0.5 * rev, "cash": 200.0, "current_assets": 0.5 * rev,
                "current_liabilities": 0.25 * rev, "debt_lt_noncurrent": debt, "debt_current": 20.0, "equity": 0.8 * rev, "equity_incl_nci": 0.8 * rev,
                "total_assets": 1.6 * rev, "total_liabilities": 0.8 * rev, "interest_expense": 15.0, "goodwill": 50.0}
        for k, v in ((k, v) for k, v in vals.items() if k not in drop):
            series.setdefault(k, {})[pe] = Filed(float(v), pe, filed, f"ACC-{pe}", "10-K", k)
        reports.append((pe, filed, f"ACC-{pe}", "10-K"))
        last_pe, last_filed = pe, filed
    sh = Filed(shares, last_pe, last_filed, "ACC-cover", "10-K", "EntityCommonStockSharesOutstanding")
    return CompanyPIT(ticker, asof, series=series, annual_reports=reports, sic=SicInfo(sic, "Test industry", "test", True), cik="0000000001",
                      shares_outstanding=sh)


IDENTITY = {"name": "Synthetic Co", "ticker": "SYN", "industry": "Test industry", "name_source": "as_of_T", "ticker_source": "as_of_T",
            "industry_source": "as_of_T"}


class LabeledPlaceholderPriors(PlaceholderPriors):
    """PLACEHOLDER priors with an arbitrary curve-position distribution (so the curve inputs can be placed in tests)."""

    def __init__(self):
        super().__init__(True)

    def for_company(self, family, state, asof):
        ps = super().for_company(family, state, asof)
        def curve_position(name, st=None):
            # arbitrary spread around the measured curve's own value at year 5 (a real prior's median is that value)
            m = ps.curves[{"growth_persistence": "growth_decay"}.get(name, name)].at(5)
            return QuantileDist({0.10: m - 0.25, 0.25: m - 0.12, 0.50: m, 0.75: m + 0.12, 0.90: m + 0.25}, PLACEHOLDER_LABEL)
        ps.refs["curve_position"] = curve_position
        return ps


def disc_factory(st, de_ratio=None, de_basis="book"):
    r = PlaceholderRates(True)
    return discount_rate_for_state(st, st["asof"], industry="placeholder", rf_provider=r.rf, beta_provider=r.beta, erp_provider=r.erp,
                                   de_ratio=de_ratio, de_basis=de_basis, placeholder=True)


D_BUSINESS = "The company designs and sells widgets to industrial customers through direct sales and distributors."
D_MDNA = ("Management expects capital expenditure to remain near current levels. The company has a signed supply agreement for 12 GW of capacity and a "
          "backlog of $4.2 billion that supports growth in the coming year. We expect demand for our products to remain strong.")
D_RELEASE = "Revenue for the fourth quarter was $1,234.5 million, up 8.1% compared with the prior year."


def docs(filed_after=False):
    items = [DocItem("annual_business", "Annual report (Form 10-K): business description", "10-K", "ACC-2025", "2026-02-28", D_BUSINESS,
                     accepted_at="2026-02-28T21:30:00.000Z", period="fiscal year ended 2025-12-31"),
             DocItem("annual_mdna_outlook", "Annual report (Form 10-K): management's discussion, outlook and key paragraphs", "10-K", "ACC-2025",
                     "2026-02-28", D_MDNA, accepted_at="2026-02-28T21:30:00.000Z", period="fiscal year ended 2025-12-31"),
             DocItem("earnings_release", "8-K Item 2.02 earnings release", "8-K", "ACC-8K", "2026-02-20", D_RELEASE, accepted_at="2026-02-20T21:05:00.000Z",
                     period="Q4 2025")]
    if filed_after:
        items.append(DocItem("earnings_release", "8-K Item 2.02 earnings release", "8-K", "ACC-8K-LATE", "2026-04-15", "Late release text for the test.",
                             accepted_at="2026-04-15T21:30:00.000Z"))
    return StaticDocuments(items)


def quarters():
    return StaticQuarters([{"period_end": "2025-09-30", "filed": "2025-11-05", "accession": "ACC-10Q", "accepted_at": "2025-11-05T21:10:00.000Z",
                            "values": {"revenue": 410.0, "operating_income": 61.0, "net_income": 44.0},
                            "prior_year": {"revenue": 380.0, "operating_income": 55.0, "net_income": 40.0}}])


# ---- the scripted mock model -----------------------------------------------------------------------------------------------------------------

def section_text(user: str, letter: str) -> Optional[str]:
    m = re.search(r"(?m)^=== SECTION %s:[^\n]*\n" % letter, user)
    if not m:
        return None
    rest = user[m.end():]
    end = re.search(r"\n\n(?:=== SECTION |ANSWER with|If you need|The sections you asked)", rest)
    return rest[:end.start()] if end else rest


def identify(user: str) -> str:
    for key, name in (("Challenge your own placements", "P6"), ("Earlier analyses placed", "P5"), ("its revenue runway", "P1"), ("its profitability", "P2"),
                      ("return on new invested capital: what one dollar", "P3"), ("its long-run growth, the growth it can sustain", "P4")):
        if key in user:
            return name
    raise AssertionError("unrecognised prompt")


def line_with(text: str, needle: str, n: int = 70) -> str:
    for ln in text.split("\n"):
        if needle in ln:
            return ln.strip()[:n] if n else ln.strip()
    raise AssertionError(f"{needle!r} not found")


class ScriptedMuse:
    """chat(request) -> an OpenAI-shaped response whose content is built from the prompt: every input at `plan[name] = (percentile, width)` (default 50,
    normal) with S and R quotes (and a D quote when the percentile is outside 10..90). `hooks[prompt](user, attempt, request)` replaces the answer of a prompt
    (a dict or a str). `p5` = {name: (percentile, width)} makes P5 move those inputs; `p6` = {name: dict(...)} drives the red team (see answer_p6)."""

    def __init__(self, plan=None, hooks=None, p5=None, p6=None, finish_reason="stop"):
        self.requests: List[dict] = []
        self.plan, self.hooks, self.p5, self.p6, self.finish_reason = plan or {}, hooks or {}, p5 or {}, p6 or {}, finish_reason

    def chat(self, request):
        self.requests.append(request)
        user = request["messages"][1]["content"]
        kind = identify(user)
        attempt = 1 if len(request["messages"]) == 2 else 2
        hook = self.hooks.get(kind)
        out = hook(user, attempt, request) if hook else self.answer(kind, user)
        content = out if isinstance(out, str) else json.dumps(out)
        return {"choices": [{"message": {"role": "assistant", "content": content, "reasoning_content": "(mock reasoning)"},
                             "finish_reason": self.finish_reason}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    # -- answers --
    def answer(self, kind, user):
        return {"P1": self.pass1, "P2": self.pass1, "P3": self.pass1, "P4": self.pass1, "P5": self.answer_p5, "P6": self.answer_p6}[kind](user, kind)

    def names(self, user):
        blk = user.split("INPUTS TO PLACE\n")[1].split("\n\n")[0]
        return re.findall(r"(?m)^- (\w+) \(", blk)

    def cits(self, user, name, pct, with_d_hard=False):
        S, R = section_text(user, "S"), section_text(user, "R")
        c = [{"section": "S", "quote": S.split("\n")[0][:50]}, {"section": "R", "quote": line_with(R, f"[R {name}]", 45)}]
        if (pct < 10 or pct > 90 or with_d_hard) and section_text(user, "D") is not None:
            c.append({"section": "D", "quote": line_with(section_text(user, "D"), "supply agreement", 0)})
        return c

    def entry(self, user, name, plan):
        pct, width = plan.get(name, (50, "normal"))
        return {"percentile": pct, "width": width, "reasons": [f"mock reason for {name}"], "citations": self.cits(user, name, pct)}

    def pass1(self, user, kind):
        S = section_text(user, "S")
        cit = {"section": "S", "quote": S.split("\n")[0][:50]}
        out = {"inputs": {n: self.entry(user, n, self.plan) for n in self.names(user)}}
        if kind == "P1":
            out["bull_case"] = {"text": "Backlog supports growth.", "citation": cit}
            out["bear_case"] = {"text": "Demand could soften.", "citation": cit}
        if kind == "P2":
            out["character"] = {"value": "structural", "reasons": "durable product",
                                "citations": [{"section": "D", "quote": line_with(section_text(user, "D"), "designs and sells widgets", 0)[:80]}]}
        if kind == "P4":
            out["risks"] = [{"risk": f"Risk {k}.", "input": "g1", "citation": cit} for k in (1, 2, 3)]
        return out

    def answer_p5(self, user, kind):
        names = re.search(r"for every input \(([^)]*)\)", user).group(1).split(", ")
        plan = dict(self.plan)
        plan.update(self.p5)
        inputs = {}
        for n in names:
            e = self.entry(user, n, plan)
            pct = plan.get(n, (50, "normal"))[0]
            if pct < 10 or pct > 90:                         # re-cite a D quote that an earlier analysis cited (the pool)
                m = re.search(r'cited \[D\]: "([^"]+)"', user)
                e["citations"].append({"section": "D", "quote": m.group(1)})
            inputs[n] = e
        return {"inputs": inputs, "changes": [{"input": n, "reason": "mock change"} for n in self.p5], "coherence": "mock coherence check"}

    def answer_p6(self, user, kind):
        names = re.findall(r"(?m)^(\w+): (?:position P|no usable placement)", user)
        inputs = {}
        for n in names:
            spec = self.p6.get(n)
            e = {"market_case": "the strongest case for the market's value is mock evidence", "decision": "keep"}
            if spec:
                if spec.get("needs_d") and section_text(user, "D") is None:
                    return {"request_sections": ["D"]}
                e = {"market_case": "the strongest case for the market's value is mock evidence", "decision": "revise", "percentile": spec["percentile"],
                     "width": spec.get("width", "normal"), "reasons": ["mock revised reason"],
                     "citations": [{"section": "S", "quote": section_text(user, "S").split("\n")[0][:50]}],
                     "new_quote": None, "named_error": None}
                if spec.get("new_quote"):
                    D = section_text(user, "D")
                    e["new_quote"] = {"section": "D", "quote": line_with(D, spec["new_quote"], 0)}
                    e["citations"].append(e["new_quote"])
                if spec.get("named_error"):
                    e["named_error"] = {"reason_index": 1, "why_wrong": "the earlier reason ignored the stated capacity"}
            inputs[n] = e
        return {"inputs": inputs}

"""decided_real_estate.py - WO_NC9c: real estate (REITs) on the decided method (operator 2026-11-18, ruling 1 of the no-call rulings; WO_NC4, WO_NC9 part C).

A variant of decided_value for the family `real_estate`, reached only through decided_value.VARIANTS (this module registers itself there) and only by the
cloud arms with VALUE_METHOD "decided". The menu path, Qwen and tools/paper_books/value_family.py are not touched: a name whose SIC is real estate is
`family_not_built` for the formation; gemini_ondemand.analyze (decided only) routes it here when the family record's route is not a mortgage REIT's.

    code pins the facts   run.prepare(real_estate=True): the operating base, with two data rules replaced and stamped (inputs.base): an unclassified balance
                          sheet gives working capital 0, a stale operating-income tag gives pretax income plus interest. Nothing else is relaxed.
    the read decides      the standard inputs of decided_value, and: whether the company owns property or lends against it (a lender stays refused here),
                          what the capital spending is (upkeep, redevelopment, acquisitions; with a quote), and the FFO the company reports (a figure with a quote)
    code checks           the standard checks; the reported figure's digits are in a quote found word for word
    code compares         derived FFO (net income + D&A - gains on property sales + impairments, less preferred dividends) with the reported figure and
                          stamps `ffo_derived_vs_reported: +x%`, or `ffo_not_reported_or_not_found`. A flag, never a gate; no number the read gave changes.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import decided_value as D  # noqa: E402
from interest_from_filing import SCALES, _printed, digits_in_quote  # noqa: E402

FAMILY = "real_estate"
KEY = "real_estate"                        # the key of the result's `decided` that carries this variant's record
VERSION = "decided.real_estate.v2 2026-11-19"   # v2: the desk keeps depreciation above upkeep for equity, every year and in the terminal (desk.py, real estate only)   # v1 WO_NC9c
PREPARE = {"real_estate": True}            # extra keyword arguments of run.prepare
SIC_RANGES = ((6500, 6599), (6798, 6798))
BUSINESS = ("owns_or_operates", "lends", "unclear")
PER = ("total", "per_share")
LENDER_REFUSAL = "mortgage_reit_not_routed"
SPENDING_WORDS = re.compile(r"upkeep|maintenance|recurring|renewal|replacement|renovat|refurbish|redevelop|acquisition|acquire|development|improvement|tenant|leasing|reserve|FF&E", re.I)

PARAGRAPH = """REAL ESTATE. This company is a real-estate company. Funds from operations (FFO) is net income plus depreciation and amortization of real estate, less gains on sales of property, plus impairments of property; the FILED RECORD shows, for each filed fiscal year, net income, depreciation and amortization, gains on property sales, impairments and code's derived FFO, and says where an item is not filed. Where the record's operating margin is (pretax income + interest expense) / revenue it includes gains on property sales and income from joint ventures: set op_margin for years 1 to 5 and long_run_op_margin on what the properties earn, not on a year that holds a gain or a loss on a sale.
Capital spending. capex_to_revenue is the capital spending the properties need to keep earning: recurring capital expenditure, tenant improvements and leasing costs, the hotel renewal and replacement reserve. It is NOT acquisitions or development of new properties; the capital expenditure / revenue of the FILED RECORD is as filed and may include them, so do not copy it. In the reason for capex_to_revenue say what the spending is (upkeep, redevelopment, acquisitions) and quote the line of the filing that gives the amount or the policy. Where the filings state no figure for upkeep, say so and give your best estimate.
situation.property_business: "owns_or_operates" if the company earns rent or operating income from property it owns or operates (hotels, offices, shops, storage, towers, billboards, land); "lends" if its income is interest on loans or securities secured by property; "unclear" otherwise.
reported_ffo: the funds from operations the company reports for the base year, as it names them (its FFO, not an adjusted, core or AFFO version, and the line after preferred dividends where it shows both), if the filings state it; null if they do not, or if it is not above zero. {"value": <the number exactly as printed, digits only>, "scale": "units" or "thousands" or "millions" or "billions" (the unit the filing states it in), "per": "total" or "per_share" (give the total where the filing states it), "what": "<the name the company gives it, and what it is after>", "quotes": [{"id": "<evidence id>", "quote": "<exact text containing the number>"}]}. Code compares it with its own derived FFO and notes the gap; it does not change your inputs."""

SITUATION_FIELD = '"debt_level_representative": {"answer": "yes|no|unclear", "why": "<one sentence>"}}'
CONFIDENCE_FIELD = '"confidence": "low|medium|high"}'
_HEAD, _SEP, _TAIL = D.TASK.partition("\nSchema:\n")
assert _SEP and _TAIL.count(SITUATION_FIELD) == 1 and _TAIL.count(CONFIDENCE_FIELD) == 1, "decided_value.TASK changed: re-anchor the real-estate task text"
TASK = (_HEAD + "\n" + PARAGRAPH + _SEP
        + _TAIL.replace(SITUATION_FIELD, '"debt_level_representative": {"answer": "yes|no|unclear", "why": "<one sentence>"}, "property_business": "owns_or_operates|lends|unclear"}')
        .replace(CONFIDENCE_FIELD, '"reported_ffo": {"value": x, "scale": "units|thousands|millions|billions", "per": "total|per_share", "what": "...", "quotes": [{"id": "...", "quote": "..."}]} or null,\n "confidence": "low|medium|high"}'))


def routes(fam):
    """True when the family record of value_family (family_not_built, a real-estate SIC) is a name this variant values: not a mortgage REIT by the
    balance-sheet route test, which stays refused."""
    sic = str(fam.get("sic") or "").strip()
    code = int(sic) if sic.isdigit() else None
    return (fam.get("family") == "family_not_built" and code is not None and any(a <= code <= b for a, b in SIC_RANGES) and fam.get("route") != "financial")


# ---------------------------------------------------------------- derived FFO
def _series(f, concept):
    return {v["end"]: v for v in (f.get(concept) or {}).get("values", [])}


def derived_ffo(f, end):
    """The derived FFO of one fiscal year from tags: {"net_income", "net_income_tag", "da", "gain", "impairment", "preferred", "before_preferred",
    "after_preferred", "not_filed": [what was taken as 0]}, or None where net income or D&A is not filed. D1 = net income (consolidated ProfitLoss where filed,
    else net income) + D&A - gains on property sales + impairments; after preferred = D1 less the preferred dividends. A gain, impairment or preferred
    dividend that is not filed is 0 and named in not_filed."""
    pl, ni, da = _series(f, "profit_loss_consolidated"), _series(f, "net_income"), _series(f, "da")
    n = pl.get(end) or ni.get(end)
    if n is None or end not in da:
        return None
    out = {"net_income": n["value"], "net_income_tag": n["tag"], "da": da[end]["value"], "not_filed": []}
    for key, concept, label in (("gain", "re_gain_on_sales", "gains"), ("impairment", "re_impairment", "impairments"), ("preferred", "preferred_dividends", "preferred_dividends")):
        v = _series(f, concept).get(end)
        out[key] = None if v is None else v["value"]
        if v is None:
            out["not_filed"].append(label)
    out["before_preferred"] = out["net_income"] + out["da"] - (out["gain"] if out["gain"] is not None else 0.0) + (out["impairment"] if out["impairment"] is not None else 0.0)
    out["after_preferred"] = out["before_preferred"] - (out["preferred"] if out["preferred"] is not None else 0.0)
    return out


def _m(x):
    return "n/f" if x is None else f"{x / 1e6:,.1f}"


def real_estate_block(f, b):
    """The text added to the record: derived FFO by fiscal year (USD millions), what is not filed, how working capital was taken."""
    rev = _series(f, "revenue")
    lines = ["REAL ESTATE RECORD (computed by code from the filings; facts). USD millions as filed; n/f = not filed for that fiscal year. Fiscal years, oldest first.",
             "fiscal year end | net income (tag) | depreciation and amortization | gains on property sales (gain positive) | impairments | preferred dividends | "
             "derived FFO before preferred dividends | derived FFO after preferred dividends"]
    for e in sorted(rev):
        d = derived_ffo(f, e)
        if d is None:
            lines.append(f"{e} | net income or depreciation and amortization not filed | | | | | |")
        else:
            lines.append(f"{e} | {_m(d['net_income'])} ({d['net_income_tag']}) | {_m(d['da'])} | {_m(d['gain'])} | {_m(d['impairment'])} | {_m(d['preferred'])} | "
                         f"{_m(d['before_preferred'])} | {_m(d['after_preferred'])}")
    lines.append("Derived FFO = net income + depreciation and amortization - gains on property sales + impairments; after preferred dividends = less the preferred dividends. "
                 "A gain, impairment or dividend that is not filed counts as 0. It is code's derivation from tags, not the company's own FFO: adjustments for joint ventures "
                 "and partnership interests, and depreciation of non-real-estate assets, are in no tag.")
    if "nwc_not_classified_taken_as_0" in b["stamps"]:
        lines.append("The balance sheet is not classified: no current assets or current liabilities are filed, so working capital is taken as 0.")
    if "operating_income_tag_stale_not_used" in b["stamps"]:
        lines.append("The operating income tag has not been filed for the latest fiscal year: operating income is pretax income plus interest expense in every year.")
    return "\n".join(lines)


def record_text(f, f_all, b, r, prov):
    """decided_value.record_text on the operating income the base used, plus the real-estate block."""
    stale = "operating_income_tag_stale_not_used" in b["stamps"]
    text, rec = D.record_text(f, {k: v for k, v in f_all.items() if k != "operating_income"} if stale else f_all, b, r, prov,
                              no_oi="the operating income tag not being filed for the latest fiscal year" if stale else "no operating income being filed")
    return text + "\n" + real_estate_block(f, b), rec


# ---------------------------------------------------------------- the checks
def shape_problems(obj):
    """What is wrong with the real-estate fields' form, or []."""
    p = []
    sit = obj.get("situation") or {}
    if sit.get("property_business") not in BUSINESS:
        p.append(f"situation.property_business must be one of {', '.join(BUSINESS)}")
    if "reported_ffo" not in obj:
        return p + ["reported_ffo is missing (an object, or null where the filings do not state it)"]
    rf = obj["reported_ffo"]
    if rf is None:
        return p
    if not isinstance(rf, dict):
        return p + ["reported_ffo must be an object or null"]
    if rf.get("scale") not in SCALES:
        p.append(f"reported_ffo.scale must be one of {', '.join(SCALES)}")
    if rf.get("per") not in PER:
        p.append(f"reported_ffo.per must be one of {', '.join(PER)}")
    if not (isinstance(rf.get("what"), str) and rf["what"].strip()):
        p.append("reported_ffo.what is missing")
    if not isinstance(rf.get("quotes"), list):
        p.append("reported_ffo.quotes must be a list")
    v = _printed(rf.get("value"))
    if v is None or not v.is_finite() or not v > 0:
        p.append(f"reported_ffo.value {rf.get('value')!r} is not a number above 0 (use null where the filings do not state it)")
    return p


def refusal(obj):
    """(reason, detail) when the read says the company lends against property (a mortgage REIT: not valued here), else None."""
    if obj["situation"]["property_business"] == "lends":
        return LENDER_REFUSAL, "the read says the company lends against property; mortgage REITs are not valued by the real-estate route"
    return None


def _verified_ffo(rf, texts):
    """(the reported FFO with its verified quotes, or None; the problems). The digits of the figure must be in a quote found word for word in the item it cites."""
    kept = [{"id": q["id"], "quote": q["quote"]} for q in rf["quotes"] if isinstance(q, dict) and isinstance(q.get("id"), str) and isinstance(q.get("quote"), str)
            and q["id"] in texts and D.contract.quote_found(q["quote"], [texts[q["id"]]])]
    v = _printed(rf["value"])
    if not kept:
        return None, ["reported_ffo has no quote found word for word in the item it cites"]
    carrying = [k for k in kept if digits_in_quote(v, [k["quote"]])]
    if not carrying:
        return None, [f"reported_ffo.value {rf['value']!r} does not appear in any quote that was found word for word"]
    return {"value": float(v * SCALES[rf["scale"]]) if rf["per"] == "total" else float(v), "printed": rf["value"], "scale": rf["scale"], "per": rf["per"],
            "what": rf["what"].strip(), "quotes": carrying + [k for k in kept if k not in carrying]}, []


def _pct(x):
    return f"{x * 100:+.1f}%"


def ffo_check(rep, d, shares):
    """(the comparison record, the stamps): derived FFO of the base year against the reported figure. The stamp compares with the derived FFO after
    preferred dividends (the comparable the measured companies print); the one before preferred dividends is kept in the record."""
    if rep is None:
        return {"status": "not_reported_or_not_found"}, ["ffo_not_reported_or_not_found"]
    if d is None:
        return {"status": "not_derivable", "reported": rep}, ["ffo_not_derivable: net income or depreciation and amortization not filed for the base year"]
    per_share = rep["per"] == "per_share"
    div = shares if per_share else 1.0
    after, before = d["after_preferred"] / div, d["before_preferred"] / div
    gap, gap_before = after / rep["value"] - 1, before / rep["value"] - 1
    stamps = [f"ffo_derived_vs_reported: {_pct(gap)}"]
    if per_share:
        stamps.append("ffo_compared_per_share_on_the_base_years_diluted_shares")
    stamps += [f"ffo_derived_{x}_taken_as_0" for x in d["not_filed"]]
    return {"status": "compared", "reported": rep, "derived_after_preferred": d["after_preferred"], "derived_before_preferred": d["before_preferred"],
            "per_share_divisor": shares if per_share else None, "gap_after_preferred": gap, "gap_before_preferred": gap_before, "not_filed": d["not_filed"]}, stamps


def check(obj, texts, f, b):
    """(problems, extra): the problems of the real-estate fields (they go to the repair turn with the standard ones), and extra = {"flags": [...], "record": {...}}
    that decided_value keeps beside the run's `decided`. Quote and digits checks as interest_from_filing's."""
    problems, rep = [], None
    if obj.get("reported_ffo") is not None:
        rep, problems = _verified_ffo(obj["reported_ffo"], texts)
    d = derived_ffo(f, b["fy0"])
    cmp_, stamps = ffo_check(rep, d, b["shares"])
    flags = list(stamps)
    if obj["situation"]["property_business"] == "unclear":
        flags.append("property_business_unclear")
    why = obj["reasons"]["capex_to_revenue"]["why"]
    if not SPENDING_WORDS.search(why):
        flags.append("capex_reason_does_not_name_the_spending")
    return problems, {"flags": flags, "record": {"version": VERSION, "property_business": obj["situation"]["property_business"], "ffo": cmp_}}


D.VARIANTS[FAMILY] = sys.modules[__name__]

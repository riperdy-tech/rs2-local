"""checks.py - the checks V1-V11 on one valuation_inputs output (SPEC_m3q §4; WO_Q5 §2; CROSS_CHECK_Q_RULINGS batch A).

check(out, items, ticker, statements, b, bar, r, fy_ends) returns
  {"status": "ok" | "valuation_incomplete" | "invalid", "unsupported": {input: [reason]}, "annotations": [...], "labels": {...},
   "stamps": [...], "values": {scenario: per-share value}, "results": {scenario: desk result}, "refused_reasons": [index]}
- "invalid": the output fails V1's shape rules (Base and every scenario, every field). Nothing is computed. check() never raises on model
  content: any malformed content is "invalid" with the reason (ruling 22).
- "valuation_incomplete": some judgment input is unsupported under the contract rules. Values are still computed and reported.
- A reason counts only if contract.check_claim says supported AND it carries at least one quote (every quote verified by the contract),
  AND it addresses its input (a lexical keyword class: ruling 12, partial by design), AND its claim text is not reused for another input.
- V3's span comes from filed items OTHER than the code-built [Y] record, from >= 2 distinct fiscal years (an item's period maps to the
  fiscal year containing it). Not built (stated limit): proof that the quoted evidence reaches the premium level.
No input is ever replaced by a code value.
"""
import math
import re

from qwen_c import contract
from qwen_c.value import desk, forecast, forecast_fin

CHECKS_VERSION = "m3q.checks.v5"   # v5 2026-10-31 CROSS_CHECK_Q3: V3 every typed year (both routes), the financial fixes, CROSS_CHECK_Q3b N1-N9   # v4 2026-10-30 WO_Q6: the financial route (route="financial"); v3 2026-10-30 CROSS_CHECK_Q2
FILED_KINDS = ("statement", "annual_section", "quarterly_section")          # [Y] filed_record items cannot carry V3's span
V4_KINDS = FILED_KINDS + ("filed_record",)
MARGIN_SOURCES = ("record", "pricing_or_mix", "investment_in_explicit_years", "investment_after_year5", "decline")
JUDGMENT = ("rev_growth", "op_margin", "normalized", "fade_years", "long_run_op_margin", "terminal_ronic", "terminal_g", "margin_source")
MARGIN_INPUTS = ("op_margin", "normalized", "long_run_op_margin", "investment_path")
CAPEX_INPUTS = ("capex_path",)
REPLACEABLE = ("rev_growth", "op_margin", "normalized", "transition", "transition_year", "fade_years", "long_run_op_margin",
               "terminal_ronic", "terminal_g")
ORDERED = ("rev_growth", "op_margin", "normalized", "long_run_op_margin", "terminal_ronic", "terminal_g")   # V9: Bear <= Base <= Bull
SEAM_BAND = (0.67, 1.5)
V11_TOL = 0.0005                                                            # N17
SPREAD_MIN = 0.02                                                           # N7 (annotation)
ALWAYS_STAMPS = ["v5_withdrawn_status_unenforced"]                          # ruling 15
_KEYWORDS = {                                                               # ruling 12: the reason must address its input
    "rev_growth": r"growth|grow|revenue|sales|demand|volume|price|backlog|order",
    "op_margin": r"margin|operating income|profit|cost|expense|pricing",
    "normalized": r"margin|operating income|profit|cost|expense|pricing|cycle|normal",
    "long_run_op_margin": r"margin|operating income|profit|cost|pricing|competit|durab",
    "fade_years": r"year|fade|durab|compet|moat|advantage|cycle|contract|patent|licen",
    "terminal_ronic": r"return|capital|invest|reinvest|roic|roe|asset",
    "terminal_g": r"growth|grow|inflation|gdp|market|declin|shrink|mature|population",
    "margin_source": r"margin|pricing|price|mix|invest|capital|cost|program|declin",
    "investment_path": r"capital|capex|invest|expansion|plant|capacity|program|project|build",
    "capex_path": r"capital|capex|invest|expansion|plant|capacity|program|project|build|spend",
    "transition": r"margin|growth|year|normal|recover|transition",
    "transition_year": r"margin|growth|year|normal|recover|transition",
}
_UP = r"above|higher than|exceeds?|greater than|more than"
_DOWN = r"below|lower than|under|beneath|less than"
_REF = (r"(?:the\s+)?(?:company'?s\s+|its\s+)?(?:filed\s+|historical\s+|\d+[- ]year\s+|(?:three|four|five|six|seven|eight|nine|ten)[- ]year\s+)?"
        r"(?:record\s+)?(median|average|mean|maximum|max|high|minimum|min|low|record|last year|latest year)")
_RETURN_TO_GROWTH = re.compile(r"\b(grow|grows|growing|recover|recovers|recovery|rebound|return to growth|returns to growth|expand|expands|expansion)\b", re.I)
_GREW = re.compile(r"(?<!not )(?<!no )\b(grew|grow|grows|growing|growth|increase[sd]?|rose|rise[sn]?|expand(?:s|ed|ing)?)\b", re.I)
_YEAR_NAMED = re.compile(r"\b(?:19|20)\d{2}\b")
_DIRECTION = re.compile(r"(\b(?:not|no|never)\b\s+(?:\w+\s+){0,2}?)?\b(" + _UP + "|" + _DOWN + r")\s+" + _REF, re.I)


class Invalid(ValueError):
    pass


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _list2(v, lo=None):
    return isinstance(v, list) and len(v) == 2 and all(_num(x) and (lo is None or x > lo) for x in v)


def _field(k, v, r):
    """None if field k's value v is valid, else why."""
    if k == "rev_growth":
        return None if _list2(v, -1.0) else "two finite growth rates above -100%"
    if k == "op_margin":
        return None if _list2(v) and all(-1 < x < 1 for x in v) else "two finite margins in (-1, 1)"
    if k == "normalized":
        ok = (isinstance(v, dict) and v.get("baseline") in forecast.BASELINES and v.get("year") in (3, 4, 5) and _num(v.get("delta_pts"))
              and _num(v.get("rev_growth")) and v["rev_growth"] > -1)
        return None if ok else "year 3..5, a baseline, finite delta_pts and rev_growth above -100%"
    if k == "transition":
        return None if v in forecast.TRANSITIONS else f"one of {forecast.TRANSITIONS}"
    if k == "transition_year":
        return None if v is None or (isinstance(v, int) and not isinstance(v, bool) and 3 <= v <= 5) else "null or 3..5"
    if k == "fade_years":
        return None if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 30 else "an integer 1..30"
    if k == "long_run_op_margin":
        return None if _num(v) and -1 < v < 1 else "a finite margin in (-1, 1)"
    if k == "terminal_ronic":
        return None if v == "unlimited" or (_num(v) and v > 0) else "> 0 or 'unlimited'"
    if k == "terminal_g":
        return None if _num(v) and v < r and v > -1 else f"finite, above -100% and below the cost of equity {r:.4f}"
    if k == "margin_source":
        return None if v in MARGIN_SOURCES else f"one of {MARGIN_SOURCES}"
    if k == "capex_path":                                                  # O7 (ruling 4): mode 1 five ratios, mode 2 a year-5 target
        if v is None:
            return None
        if isinstance(v, list) and len(v) == 5 and all(_num(x) and 0 <= x < 1 for x in v):
            return None
        if isinstance(v, dict) and set(v) == {"year5"} and _num(v["year5"]) and 0 <= v["year5"] < 1:
            return None
        return "null, five capex/revenue ratios in [0, 1), or {\"year5\": a ratio in [0, 1)}"
    if k == "investment_path":
        if v is None:
            return None
        if not (isinstance(v, list) and 1 <= len(v) <= 25):
            return "null or a list of 1..25 years"
        for j, yr in enumerate(v):
            if not (isinstance(yr, dict) and yr.get("year") == 6 + j and _num(yr.get("capex_over_revenue")) and yr["capex_over_revenue"] >= 0
                    and _num(yr.get("revenue_growth")) and yr["revenue_growth"] > -1 and _num(yr.get("op_margin")) and -1 < yr["op_margin"] < 1):
                return f"entry {j}: year {6 + j}, capex_over_revenue >= 0, revenue_growth above -100%, op_margin in (-1, 1)"
        return None
    return f"unknown field {k!r}"


def _scenario(sc, name, r):
    f = [f"{name}.{k}: {why}" for k in sc for why in [_field(k, sc[k], r)] if why]
    if sc.get("transition") in ("step_at_year", "hold_then_linear"):
        ty, ny = sc.get("transition_year"), (sc.get("normalized") or {}).get("year")
        if not (isinstance(ty, int) and isinstance(ny, int) and 3 <= ty <= ny):
            f.append(f"{name}.transition_year: {sc.get('transition')} needs transition_year in 3..normalized.year")
    return f


def shape(out, r):
    """V1 shape on Base, both scenarios (merged onto Base), the probabilities and the reasons. [failure] (empty when valid)."""
    if not isinstance(out, dict):
        return ["the reply is not an object"]
    base = out.get("base")
    if not isinstance(base, dict):
        return ["base missing"]
    f = [f"base.{k} missing" for k in JUDGMENT + ("transition",) if k not in base]
    if f:
        return f
    f += _scenario(base, "base", r)
    for name in ("bear", "bull"):
        sc = out.get(name, {})
        if not isinstance(sc, dict):
            f.append(f"{name} must be an object")
            continue
        extra = [k for k in sc if k not in REPLACEABLE]
        f += [f"{name}.{k}: not replaceable in a scenario" for k in extra]
        if not extra:
            f += _scenario(merged(out, name), name, r)
    return f + _prob_reasons(out)


def _prob_reasons(out):
    """V1 on the probabilities and the reasons (the same on both routes)."""
    f = []
    p = out.get("prob")
    if not (isinstance(p, dict) and all(_num(p.get(k)) and p[k] >= 0 for k in ("bear", "base", "bull"))
            and abs(sum(p[k] for k in ("bear", "base", "bull")) - 1) <= 0.01):
        f.append("prob: bear, base, bull >= 0 summing to 1 +- 0.01")
    rz = out.get("reasons")
    if not isinstance(rz, list):
        f.append("reasons must be a list")
    else:
        for i, x in enumerate(rz):
            if not (isinstance(x, dict) and isinstance(x.get("input"), str) and isinstance(x.get("claim"), str)
                    and isinstance(x.get("fact_ids"), list) and all(isinstance(a, str) for a in x["fact_ids"])
                    and isinstance(x.get("quotes"), list) and all(isinstance(a, str) for a in x["quotes"])
                    and isinstance(x.get("numbers", []), list)):
                f.append(f"reasons[{i}]: input, claim (strings), fact_ids and quotes (lists of strings), numbers (a list)")
    return f


def merged(out, name):
    sc = dict(out["base"])
    if name != "base":
        rep = dict(out.get(name) or {})
        if "normalized" in rep and isinstance(rep["normalized"], dict):
            rep["normalized"] = {**out["base"]["normalized"], **rep["normalized"]}      # a partial normalized replaces only its keys
        sc.update(rep)
    return sc


def _key(path):
    parts = path.split(".")
    return (parts[0], parts[1]) if len(parts) >= 2 else (parts[0], "")


def fiscal_year_of(period, fy_ends):
    """The fiscal-year end (from the facts) whose year contains `period` (a date string). A period after the last filed fiscal year (the
    10-Q filed after FY0's annual report) belongs to the next fiscal year, FY0 + one year (CROSS_CHECK_Q2 N1). None if undated or more
    than a year past FY0."""
    p = str(period or "")[:10]
    ends = sorted(fy_ends)
    if len(p) != 10 or not ends:
        return None
    later = [e for e in ends if e >= p]
    if later:
        return later[0]
    nxt = f"{int(ends[-1][:4]) + 1}{ends[-1][4:]}"
    return nxt if p <= nxt else None


def reasons_by_input(out, items, ticker, statements, fy_ends=(), route="operating"):
    """{(scenario, input): [{"i", "reason", "support", "ok", "why", "kinds", "span_years"}]}. ok = the reason counts (see module doc).
    `route` picks the keyword classes and the input's own printed value (CROSS_CHECK_Q3 9)."""
    keywords = _FIN_KEYWORDS if route == "financial" else _KEYWORDS
    texts = {k: _sq(v["text"]) for k, v in items.items()}                   # smoke 2: " and ' match alike (local to valuation)
    got, seen_claims = {}, {}
    for i, rz in enumerate(out.get("reasons") or []):
        key = _key(rz.get("input", ""))
        claim = {"claim": rz.get("claim", ""), "fact_ids": rz.get("fact_ids") or [], "quotes": [_sq(q) for q in rz.get("quotes") or []],
                 "numbers": rz.get("numbers") or []}
        # smoke 1: the reason may state its own input's value; that figure is supplied as a cited text, never as evidence for spans
        own = input_value_text(out, key, route)
        chk = contract.check_claim(dict(claim, fact_ids=claim["fact_ids"] + ["_OWN"]) if own else claim,
                                   dict(texts, _OWN=own) if own else texts, ticker, statements)
        cited = [items[a] for a in claim["fact_ids"] if a in items]
        why = None
        if chk["support"] != contract.SUPPORTED:
            why = f"contract: {chk['support']}"
        elif not claim["quotes"]:
            why = "no quote: a reason must quote the evidence it rests on"
        elif key[1] in keywords and not re.search(keywords[key[1]], claim["claim"], re.I):
            why = f"does not address {key[1]}"
        norm = " ".join(claim["claim"].lower().split())
        if why is None and norm in seen_claims and seen_claims[norm] != key:
            why = f"the same claim already serves {'.'.join(seen_claims[norm])}"
        seen_claims.setdefault(norm, key)
        # N2: the span counts only the filed (non-[Y]) items a verified quote of this reason comes from
        quoted = [c for c in cited if any(contract.quote_found(q, [_sq(c["text"])]) for q in claim["quotes"])]
        span = {fiscal_year_of(c.get("period"), fy_ends) for c in quoted if c["kind"] in FILED_KINDS} - {None}
        got.setdefault(key, []).append({"i": i, "reason": rz, "support": chk["support"], "ok": why is None, "why": why,
                                        "kinds": {c["kind"] for c in cited}, "span_years": span})
    return got


def _sq(s):
    return (s or "").replace('"', "'")


def input_value_text(out, key, route="operating"):
    """The printed forms of the input `key` = (scenario, input) value, so a reason can state the value it argues for: each number as a
    fraction and as a percentage (one decimal and none). '' when the input is not numeric."""
    sc = merged(out, key[0]) if key[0] in ("base", "bear", "bull") and isinstance(out.get("base"), dict) else {}
    v = sc.get(key[1])
    if isinstance(v, dict):
        v = [v.get("delta_pts"), v.get("book_growth" if route == "financial" else "rev_growth")]      # CROSS_CHECK_Q3 9: by route
    vals = [x for x in (v if isinstance(v, list) else [v]) if _num(x)]
    forms = []
    for x in vals:
        forms += [f"{x}", f"{x:.2f}", f"{x:.4f}", f"{100 * x:.1f}%", f"{100 * x:.0f}%", f"{x:.1f}", f"{x:.0f}"]
    return " ".join(forms)


def _ok(rs):
    return [x for x in rs if x["ok"]]


def _direction_contradiction(claim, value, bar):
    for sentence in re.split(r"(?<=[.;])\s+", claim or ""):
        if _YEAR_NAMED.search(sentence):                                   # N5: about one named year's margin, not the input
            continue
        why = _direction_one(sentence, value, bar)
        if why:
            return why
    return None


def _direction_one(claim, value, bar):
    for neg, word, ref in _DIRECTION.findall(claim):
        ref = ref.lower()
        up = re.fullmatch(_UP, word, re.I) is not None
        if ref in ("median", "average", "mean"):
            ref_v = bar["median"]
        elif ref in ("last year", "latest year"):
            ref_v = bar["last"]
        elif ref in ("minimum", "min", "low"):
            ref_v = bar["min"]
        elif ref in ("maximum", "max", "high"):
            ref_v = bar["max"]
        else:                                                              # "record" alone: the record's top when above, bottom when below
            ref_v = bar["max"] if up else bar["min"]
        if neg:
            bad = (up and value > ref_v) or (not up and value < ref_v)
        else:
            bad = (up and not value > ref_v) or (not up and not value < ref_v)
        if bad:
            return f"says {(neg or '').strip()} {word} the {ref} ({ref_v:.4f}) but the input is {value:.4f}".replace("  ", " ")
    return None


def check(out, items, ticker, statements, b, bar, r, fy_ends=(), route="operating"):
    """`route` is "operating" or "financial" (WO_Q6: the ROE-path task, `bar` then the filed ROE record's statistics)."""
    if route not in ("operating", "financial"):
        raise ValueError(f"route {route!r}")
    res = {"version": CHECKS_VERSION, "route": route, "status": "ok", "unsupported": {}, "annotations": [], "labels": {}, "values": {},
           "results": {}, "stamps": list(ALWAYS_STAMPS) + (list(FIN_STAMPS) if route == "financial" else []), "refused_reasons": []}
    try:
        bad = shape(out, r) if route == "operating" else shape_fin(out, r)
        if bad:
            return dict(res, status="invalid", failures=bad)
        if route == "financial":
            return _check_fin(out, items, ticker, statements, b, bar, r, fy_ends, res)
        return _check(out, items, ticker, statements, b, bar, r, fy_ends, res)
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, OverflowError) as e:
        return dict(res, status="invalid", failures=[f"{type(e).__name__}: {e}"])


# ------------------------------------------------------------------ the financial route (WO_Q6; O3 retained equity)
FIN_JUDGMENT = ("book_growth", "roe", "normalized", "fade_years", "long_run_roe", "terminal_g")
FIN_ROE_INPUTS = ("roe", "normalized", "long_run_roe")
FIN_REPLACEABLE = FIN_JUDGMENT + ("transition", "transition_year")
FIN_ORDERED = ("book_growth", "roe", "normalized", "long_run_roe", "terminal_g")
FIN_STAMPS = ["capital_constraint_not_modeled"]
RELEASE_SHARE = 0.25          # Q3b N2: a cumulative release of more than a quarter of book over years 1-5 is annotated
PEAK_QUANTILE = "p75"         # Q3b N3: a normalized or long-run value at or above the record's p75 is annotated                                   # WO_Q6 §4
_FIN_KEYWORDS = {
    "book_growth": r"growth|grow|book|equity|capital|retain|loan|deposit|premium|asset|balance sheet|dividend|buyback|repurchase",
    "roe": r"return|roe|earn|profit|income|margin|spread|interest|credit|loss|underwrit|combined ratio",
    "normalized": r"return|roe|earn|profit|income|spread|interest|credit|loss|underwrit|cycle|normal",
    "long_run_roe": r"return|roe|earn|profit|compet|durab|capital|spread|underwrit",
    "fade_years": _KEYWORDS["fade_years"],
    "terminal_g": _KEYWORDS["terminal_g"] + r"|book|equity|capital|retain",
    "transition": r"return|roe|growth|year|normal|recover|transition",
    "transition_year": r"return|roe|growth|year|normal|recover|transition",
}


def _field_fin(k, v, r):
    if k == "book_growth":
        return None if _list2(v, -1.0) else "two finite book-equity growth rates above -100%"
    if k == "roe":
        return None if _list2(v) and all(-1 < x < 1 for x in v) else "two finite ROEs in (-1, 1)"
    if k == "normalized":
        ok = (isinstance(v, dict) and v.get("baseline") in forecast.BASELINES and v.get("year") in (3, 4, 5) and _num(v.get("delta_pts"))
              and _num(v.get("book_growth")) and v["book_growth"] > -1)
        return None if ok else "year 3..5, a baseline, finite delta_pts and book_growth above -100%"
    if k == "long_run_roe":
        return None if _num(v) and 0 < v < 1 else "a finite ROE in (0, 1)"
    if k in ("transition", "transition_year", "fade_years", "terminal_g"):
        return _field(k, v, r)
    return f"unknown field {k!r}"


def _scenario_fin(sc, name, r):
    f = [f"{name}.{k}: {why}" for k in sc for why in [_field_fin(k, sc[k], r)] if why]
    if sc.get("transition") in ("step_at_year", "hold_then_linear"):
        ty, ny = sc.get("transition_year"), (sc.get("normalized") or {}).get("year")
        if not (isinstance(ty, int) and isinstance(ny, int) and 3 <= ty <= ny):
            f.append(f"{name}.transition_year: {sc.get('transition')} needs transition_year in 3..normalized.year")
    return f


def shape_fin(out, r):
    """V1 shape for the financial task: shape()'s rules on the financial fields."""
    if not isinstance(out, dict):
        return ["the reply is not an object"]
    base = out.get("base")
    if not isinstance(base, dict):
        return ["base missing"]
    f = [f"base.{k} missing" for k in FIN_JUDGMENT + ("transition",) if k not in base]
    if f:
        return f
    f += _scenario_fin(base, "base", r)
    for name in ("bear", "bull"):
        sc = out.get(name, {})
        if not isinstance(sc, dict):
            f.append(f"{name} must be an object")
            continue
        extra = [k for k in sc if k not in FIN_REPLACEABLE]
        f += [f"{name}.{k}: not replaceable in a scenario" for k in extra]
        if not extra:
            f += _scenario_fin(merged(out, name), name, r)
    return f + _prob_reasons(out)


def _check_fin(out, items, ticker, statements, b, bar, r, fy_ends, res):
    by = reasons_by_input(out, items, ticker, statements, fy_ends, route="financial")
    res["refused_reasons"] = sorted(x["i"] for rs in by.values() for x in rs if not x["ok"])

    def unsupported(key, why):
        res["unsupported"].setdefault(f"{key[0]}.{key[1]}", []).append(why)

    def span_ok(name, k):
        return any(len(x["span_years"]) >= 2 for x in _ok(by.get((name, k), [])))

    base = out["base"]
    for k in FIN_JUDGMENT:
        ok = _ok(by.get(("base", k), []))
        if not ok:
            rs = by.get(("base", k), [])
            unsupported(("base", k), "no supported reason" + (f" ({'; '.join(x['why'] for x in rs)})" if rs else ""))
        elif k in FIN_ROE_INPUTS and not any(x["kinds"] & set(V4_KINDS) for x in ok):
            unsupported(("base", k), "V4: no supported reason cites a filed statement, section or record year")
    for name in ("bear", "bull"):
        for k in out.get(name) or {}:
            if k not in ("transition_year",) and not _ok(by.get((name, k), [])):
                unsupported((name, k), "no supported reason for the scenario's own input")
    path, roe_n = forecast_fin.build_path(base, bar)
    # V3 (ROE outside the filed ROE record), V4 on scenario ROE inputs, V10 (a reason contradicting its ROE)
    for name in ("base", "bear", "bull"):
        keys = None if name == "base" else set(out.get(name) or {})
        sc = merged(out, name)
        _, rn_s = forecast_fin.build_path(sc, bar)
        vals = {"normalized": rn_s, "long_run_roe": float(sc["long_run_roe"]), "roe": sum(sc["roe"]) / 2}
        roes = [(k, v) for k, v in vals.items() if k != "roe"] + [("roe", float(x)) for x in sc["roe"]]    # CROSS_CHECK_Q3 1
        for k, v in roes:
            if (keys is None or k in keys) and not bar["min"] <= v <= bar["max"] and not span_ok(name, k):
                unsupported((name, k), f"V3 unsupported_premium: ROE {v:.4f} outside the filed record [{bar['min']:.4f}, {bar['max']:.4f}] "
                                       f"with no supported reason quoting filed items of two fiscal years")
        if keys is not None:
            for k in FIN_ROE_INPUTS:
                ok = _ok(by.get((name, k), []))
                if k in keys and ok and not any(x["kinds"] & set(V4_KINDS) for x in ok):
                    unsupported((name, k), "V4: no supported reason cites a filed statement, section or record year")
        for k, v in vals.items():
            if keys is not None and k not in keys:
                continue
            for x in by.get((name, k), []):
                why = _direction_contradiction(x["reason"].get("claim"), v, bar)
                if why:
                    unsupported((name, k), f"V10 reason contradicts its input: {why}")
                    res["refused_reasons"] = sorted(set(res["refused_reasons"]) | {x["i"]})
        # ronic_not_above_growth: a long-run ROE at or below terminal growth makes retention destroy value
        if float(sc["long_run_roe"]) <= float(sc["terminal_g"]):
            unsupported((name, "long_run_roe"), f"long_run_roe {float(sc['long_run_roe']):.4f} is not above terminal_g {float(sc['terminal_g']):.4f}")
        # CROSS_CHECK_Q3 2: book growth above the same year's ROE is new capital (issuance): it needs a two-fiscal-year span
        growths = [("book_growth", float(g), float(m)) for g, m in zip(sc["book_growth"], sc["roe"])] +                   [("normalized", float(sc["normalized"]["book_growth"]), rn_s)]
        for k, g, m in growths:
            if (keys is None or k in keys) and g > m and not span_ok(name, k):
                unsupported((name, k), f"implied issuance: book growth {g:.4f} above the year's ROE {m:.4f} with no supported reason "
                                       f"quoting filed items of two fiscal years")
        # CROSS_CHECK_Q3 4: book growth below the filed record's lowest, and a negative terminal growth, release book: a two-year span
        gmin = (b.get("record") or {}).get("book_growth_min")
        gmin = None if gmin is None else min(gmin, 0.0)                       # Q3b N7: a slowdown is not a release
        for k, g, _ in growths:
            if (keys is None or k in keys) and gmin is not None and g < gmin and not span_ok(name, k):
                unsupported((name, k), f"V3g book growth {g:.4f} below the filed record's lowest {gmin:.4f} with no supported reason "
                                       f"quoting filed items of two fiscal years")
        path_s, _ = forecast_fin.build_path(sc, bar)
        kept = 1.0
        for y in path_s:
            kept *= 1 + y["book_growth"]
        if kept < 1 - RELEASE_SHARE and min(y["roe"] for y in path_s) < r:      # Q3b N2
            res["annotations"].append(f"book_release_cumulative: {name} keeps {kept:.3f} of book over years 1-5 with an ROE below r")
        g_t = float(sc["terminal_g"])
        if (keys is None or "terminal_g" in keys) and g_t < 0 and not span_ok(name, "terminal_g"):
            unsupported((name, "terminal_g"), f"terminal_g {g_t:.4f} below zero with no supported reason quoting filed items of two fiscal years")
        if g_t < 0 and float(sc["long_run_roe"]) < r:
            res["annotations"].append(f"book_release_terminal: {name} terminal_g {g_t:.4f} with long_run_roe {float(sc['long_run_roe']):.4f} below r")
        # V10 on growth reasons: a reason saying the book grew cannot support a shrinking input
        for k, v in [("book_growth", min(float(x) for x in sc["book_growth"])), ("normalized", float(sc["normalized"]["book_growth"])),
                     ("terminal_g", g_t)]:
            if (keys is not None and k not in keys) or v >= 0:
                continue
            for x in by.get((name, k), []):
                claim = x["reason"].get("claim") or ""
                if _GREW.search(claim) and (k != "normalized" or re.search(r"book|equity", claim, re.I)):
                    unsupported((name, k), f"V10 reason contradicts its input: says the book grows but the input is {v:.4f}")
                    res["refused_reasons"] = sorted(set(res["refused_reasons"]) | {x["i"]})
    # V7: shrinking book equity with positive terminal growth needs a supported return-to-growth reason on terminal_g
    shrink = sum(1 for g in (path[0]["book_growth"], path[1]["book_growth"], float(base["normalized"]["book_growth"])) if g < 0)
    if shrink >= 2 and base["terminal_g"] > 0 and not any(_RETURN_TO_GROWTH.search(x["reason"]["claim"])
                                                          for x in _ok(by.get(("base", "terminal_g"), []))):
        unsupported(("base", "terminal_g"), "V7: Base book equity shrinks yet terminal_g > 0 without a supported reason for a return to growth")
    # V9: scenario order on replaced inputs, unless the scenario's own reason is supported
    for name, sign in (("bear", -1), ("bull", 1)):
        for k, v in (out.get(name) or {}).items():
            if k not in FIN_ORDERED:
                continue
            if k == "normalized":
                pairs = [(forecast_fin.build_path(merged(out, name), bar)[1], roe_n)]
            else:
                bv = base.get(k)
                pairs = list(zip(v, bv)) if isinstance(v, list) else [(v, bv)]
            if any(sign * (a - c) < 0 for a, c in pairs) and not _ok(by.get((name, k), [])):
                unsupported((name, k), f"V9: {name} {k} on the wrong side of Base without a supported reason")
    # V6 labels by code
    rec = sorted((b.get("record") or {}).get("roe", {}).values())
    pct = sum(1 for m in rec if m < roe_n) / len(rec) if rec else 0.5
    roe_l = float(base["long_run_roe"])
    res["labels"] = {"cycle_position": "trough" if pct < 1 / 3 else ("mid" if pct <= 2 / 3 else "peak"),
                     "roe_persistence": "above_median" if roe_l > bar["median"] else ("below_median" if roe_l < bar["median"] else "at_median"),
                     "growth_trajectory": "shrinking" if shrink >= 2 else "growing"}
    for k, v in (out.get("labels") or {}).items():
        res["labels"][f"{k}_submitted"] = v
        if k in res["labels"] and res["labels"][k] != v:
            res["annotations"].append(f"V6 label_mismatch: {k} submitted {v!r}, code {res['labels'][k]!r}")
    d = abs(float(base["normalized"]["delta_pts"]))
    if 0 < d < 0.05 or d > 50:
        res["annotations"].append(f"delta_pts_scale_suspect: {base['normalized']['delta_pts']}")
    # V3g: terminal growth above the long-run anchor, and book growth above the filed record's maximum, need a two-fiscal-year span
    g_anchor = b.get("g_anchor")
    if g_anchor is None:
        res["annotations"].append("g_anchor_missing: terminal growth not checked against the long-run anchor")
    gmax = (b.get("record") or {}).get("book_growth_max")
    for name in ("base", "bear", "bull"):
        keys = None if name == "base" else set(out.get(name) or {})
        sc = merged(out, name)
        g = float(sc["terminal_g"])
        if (keys is None or "terminal_g" in keys) and g_anchor is not None and g > g_anchor and not span_ok(name, "terminal_g"):
            unsupported((name, "terminal_g"), f"V3g terminal_g {g:.4f} above the long-run growth anchor {g_anchor:.4f} with no supported "
                                              f"reason quoting filed items of two fiscal years")
        if r - g < SPREAD_MIN:
            res["annotations"].append(f"terminal_spread_thin: {name} r - g_T = {r - g:.4f}")
        if gmax is not None:
            for k, x in [("book_growth", x) for x in sc["book_growth"]] + [("normalized", float(sc["normalized"]["book_growth"]))]:
                if (keys is None or k in keys) and x > gmax and not span_ok(name, k):
                    unsupported((name, k), f"V3g book growth {x:.4f} above the filed record's maximum {gmax:.4f} with no supported "
                                           f"reason quoting filed items of two fiscal years")
    # compute every scenario; V1 recompute; V2 seam; V9 monotone values
    for name in ("bear", "base", "bull"):
        try:
            inp = forecast_fin.assemble(merged(out, name), b, bar, r=r)
            v = forecast_fin.value(inp)
        except desk.DeskRefusal as e:
            res["unsupported"].setdefault(f"{name}.desk", []).append(f"desk refusal {e.code}: {e}")
            continue
        _recompute_fin(inp, v, b)
        res["results"][name] = v
        res["values"][name] = v["value_per_share"]
        if name == "base":
            # CROSS_CHECK_Q3 2: the terminal value's share and the implied P/B, against the P/B of a perpetuity at the record's highest ROE
            # (B13 ruling 2026-10-30: annotated; a bound is decided on E3's evidence)
            g_t = float(inp["g_T"])
            pb = v["value_per_share"] / (b["R1"] / b["shares"])
            pb_ref = (bar["median"] - g_t) / (r - g_t)
            res["diagnostics"] = {"tv_share": v["tv_pv"] / v["equity_value"] if v["equity_value"] else None, "implied_pb": pb,
                                  "pb_record_median_perpetuity": pb_ref}
            if pb > pb_ref:
                res["annotations"].append(f"implied_pb_above_record_median_perpetuity: {pb:.2f} against {pb_ref:.2f}")
            for k, x in (("normalized", roe_n), ("long_run_roe", float(base["long_run_roe"]))):
                if x >= bar[PEAK_QUANTILE]:
                    res["annotations"].append(f"roe_at_record_peak: {k} {x:.4f} at or above the record's {PEAK_QUANTILE} {bar[PEAK_QUANTILE]:.4f}")
        if name == "base" and v["seam_ratio"] is not None and not SEAM_BAND[0] <= v["seam_ratio"] <= SEAM_BAND[1]:
            res["annotations"].append(f"V2 flow_seam_out_of_band: {v['seam_ratio']:.3f}")
    vv = res["values"]
    for name, v in vv.items():
        if not v > 0:
            res["annotations"].append(f"value_not_positive: {name} {v:.4f}")
    if len(vv) == 3 and not vv["bear"] <= vv["base"] <= vv["bull"]:
        unsupported(("scenarios", "values"), f"V9: values not monotone {vv}")
    if res["unsupported"]:
        res["status"] = "valuation_incomplete"
    return res


def _recompute_fin(inp, v, b=None):
    """V1 for the financial route (CROSS_CHECK_Q3 8): every flow, the terminal value and the equity value recomputed from the inputs, on
    the prompt's definitions (g_t the book growth during year t, faded from g5 to g_T over years 6..5+F; the ROE faded from year 5's to
    long_run_roe over the same years), independently of desk.value_financial; then value per share."""
    F, r, g_t, roe_l = int(inp["F"]), float(inp["r"]), float(inp["g_T"]), float(inp["m_long"])
    n = 5 + F
    # N9: the explicit years from the reply's path and the filed R_1, not from assemble's revenue list
    path = inp["_path"]
    book = {1: float(b["R1"] if b is not None else inp["revenue"][1])}
    for t in range(2, 6):
        book[t] = book[t - 1] * (1 + float(path[t - 2]["book_growth"]))
    roe = {t: float(path[t - 1]["roe"]) for t in range(1, 6)}
    g5 = float(path[4]["book_growth"])
    growth = {5: g5}
    for t in range(6, n + 2):
        k = min(1.0, (t - 5) / F)
        growth[t] = g5 + (g_t - g5) * k
        roe[t] = roe[5] + (roe_l - roe[5]) * k
    for t in range(6, n + 3):
        book[t] = book[t - 1] * (1 + growth[t - 1])
    scale = max(book.values())                                            # N1: a flow is a difference of book-sized numbers

    def same(a, c):
        return abs(a - c) <= 1e-9 * max(1.0, abs(a), abs(c), scale)
    flows = [book[t] * roe[t] - (book[t + 1] - book[t]) for t in range(1, n + 1)]
    for t, (a, c) in enumerate(zip(flows, v["flows_all"]), 1):
        if not same(a, c):
            raise AssertionError(f"V1: the year-{t} financial flow {c} != {a} recomputed")
    tv = book[n + 1] * (roe[n + 1] - g_t) / (r - g_t)
    eq = sum(f / (1 + r) ** t for t, f in enumerate(flows, 1)) + tv / (1 + r) ** n
    if not (same(tv, v["tv"]) and same(eq, v["equity_value"])):
        raise AssertionError(f"V1: the financial equity value {v['equity_value']} != {eq} recomputed")
    if not same(v["value_per_share"], (v["equity_value"] * v["rollforward_factor"] + inp["excess_cash"]) / inp["shares"]):
        raise AssertionError("V1: value per share")


def _check(out, items, ticker, statements, b, bar, r, fy_ends, res):
    by = reasons_by_input(out, items, ticker, statements, fy_ends)
    res["refused_reasons"] = sorted(x["i"] for rs in by.values() for x in rs if not x["ok"])

    def unsupported(key, why):
        res["unsupported"].setdefault(f"{key[0]}.{key[1]}", []).append(why)

    base = out["base"]
    ip = base.get("investment_path")
    judged = JUDGMENT + (("investment_path",) if ip else ()) + (("capex_path",) if base.get("capex_path") else ())
    for k in judged:
        rs = by.get(("base", k), [])
        ok = _ok(rs)
        if not ok:
            unsupported(("base", k), "no supported reason" + (f" ({'; '.join(x['why'] for x in rs)})" if rs else ""))
        elif k in MARGIN_INPUTS and not any(x["kinds"] & set(V4_KINDS) for x in ok):
            unsupported(("base", k), "V4: no supported reason cites a filed statement, section or record year")
    # every scenario replacement needs its own supported reason (ruling 11)
    for name in ("bear", "bull"):
        for k in out.get(name) or {}:
            if k not in ("transition_year",) and not _ok(by.get((name, k), [])):
                unsupported((name, k), "no supported reason for the scenario's own input")
    path, m_n = forecast.build_path(base, bar, b["R0"])
    m_l = float(base["long_run_op_margin"])

    def span_ok(name, k):
        return any(len(x["span_years"]) >= 2 for x in _ok(by.get((name, k), [])))

    # V3, V4 and V10 on Base and on every scenario's own margin inputs (N4, N5)
    for name in ("base", "bear", "bull"):
        keys = None if name == "base" else set(out.get(name) or {})
        sc = merged(out, name)
        _, mn_s = forecast.build_path(sc, bar, b["R0"])
        vals = {"normalized": mn_s, "long_run_op_margin": float(sc["long_run_op_margin"]), "op_margin": sum(sc["op_margin"]) / 2}
        # CROSS_CHECK_Q3 1 (operating twin): each typed explicit-year margin, not only the normalized and long-run ones (a hold or step
        # transition carries the year-2 value to year 4)
        margins = [(k, v) for k, v in vals.items() if k != "op_margin"] + [("op_margin", float(x)) for x in sc["op_margin"]]
        if name == "base":
            margins += [("investment_path", yr["op_margin"]) for yr in (ip or [])]
        for k, v in margins:                                                 # V3: outside the record needs a two-fiscal-year span
            if (keys is None or k in keys) and not bar["min"] <= v <= bar["max"] and not span_ok(name, k):
                unsupported((name, k), f"V3 unsupported_premium: {v:.4f} outside the filed record [{bar['min']:.4f}, {bar['max']:.4f}] "
                                       f"with no supported reason quoting filed items of two fiscal years")
        if keys is not None:
            for k in ("op_margin", "normalized", "long_run_op_margin"):    # V4 on scenario margin inputs
                ok = _ok(by.get((name, k), []))
                if k in keys and ok and not any(x["kinds"] & set(V4_KINDS) for x in ok):
                    unsupported((name, k), "V4: no supported reason cites a filed statement, section or record year")
        for k, v in vals.items():                                            # V10 over every margin reason
            if keys is not None and k not in keys:
                continue
            for x in by.get((name, k), []):
                why = _direction_contradiction(x["reason"].get("claim"), v, bar)
                if why:
                    unsupported((name, k), f"V10 reason contradicts its input: {why}")
                    res["refused_reasons"] = sorted(set(res["refused_reasons"]) | {x["i"]})
    # N6: a capex path outside the filed record of capex/revenue needs a two-fiscal-year span, like V3
    cp = base.get("capex_path")
    if cp:
        ratios = [cp["year5"]] if isinstance(cp, dict) else list(cp)
        crec = list((b.get("record") or {}).get("capex_ratio", {}).values())
        if crec and any(not min(crec) <= c <= max(crec) for c in ratios) and not span_ok("base", "capex_path"):
            unsupported(("base", "capex_path"), f"capex/revenue {ratios} outside the filed record [{min(crec):.4f}, {max(crec):.4f}] with no "
                                                f"supported reason quoting filed items of two fiscal years")
    # V7: a shrinking Base with positive terminal growth needs a supported, growth-addressing reason on terminal_g (the keyword rule)
    shrink = sum(1 for g in (path[0]["rev_growth"], path[1]["rev_growth"], float(base["normalized"]["rev_growth"])) if g < 0)
    if shrink >= 2 and base["terminal_g"] > 0 and not any(_RETURN_TO_GROWTH.search(x["reason"]["claim"])
                                                          for x in _ok(by.get(("base", "terminal_g"), []))):
        unsupported(("base", "terminal_g"), "V7: Base revenue shrinks yet terminal_g > 0 without a supported reason for a return to growth")
    # V11 and the investment path (rulings 2, 4)
    src = base["margin_source"]
    if src == "investment_after_year5" and not ip:
        unsupported(("base", "margin_source"), "V11: investment_after_year5 needs investment_path (O2c)")
    if ip and src != "investment_after_year5":
        unsupported(("base", "investment_path"), "an investment_path needs margin_source investment_after_year5")
    for yr in ip or []:
        if not yr["capex_over_revenue"] > b["c_ratio"]:
            unsupported(("base", "investment_path"), f"year {yr['year']}: capex/revenue {yr['capex_over_revenue']:.4f} is not above the pooled "
                                                     f"{b['c_ratio']:.4f}: not an investment programme")
    last = (ip[-1]["op_margin"] if ip else path[4]["op_margin"])
    if src in ("record", "decline") and m_l > last + V11_TOL:
        unsupported(("base", "margin_source"), f"V11: margin_source {src!r} with a long-run margin above the last explicit year's")
    if src == "investment_in_explicit_years" and not base.get("capex_path"):
        unsupported(("base", "margin_source"), "investment_in_explicit_years needs a capex_path (O7)")
    # V9: scenario order on replaced inputs, unless the scenario's own reason is supported
    for name, sign in (("bear", -1), ("bull", 1)):
        for k, v in (out.get(name) or {}).items():
            if k not in ORDERED:
                continue
            bv = base.get(k)
            if k == "normalized":
                pairs = [(forecast.build_path(merged(out, name), bar, b["R0"])[1], m_n)]
            else:
                pairs = list(zip(v, bv)) if isinstance(v, list) else [(v, bv)]
            pairs = [(math.inf if a == "unlimited" else a, math.inf if c == "unlimited" else c) for a, c in pairs]
            if any(sign * (a - c) < 0 for a, c in pairs) and not _ok(by.get((name, k), [])):
                unsupported((name, k), f"V9: {name} {k} on the wrong side of Base without a supported reason")
    # V6: labels by code, from the true percentile of the filed record
    rec = sorted((b.get("record") or {}).get("op_margin", {}).values())
    pct = sum(1 for m in rec if m < m_n) / len(rec) if rec else 0.5
    res["labels"] = {"cycle_position": "trough" if pct < 1 / 3 else ("mid" if pct <= 2 / 3 else "peak"),
                     "margin_persistence": "above_median" if m_l > bar["median"] else ("below_median" if m_l < bar["median"] else "at_median"),
                     "growth_trajectory": "shrinking" if shrink >= 2 else "growing"}
    for k, v in (out.get("labels") or {}).items():
        res["labels"][f"{k}_submitted"] = v
        if k in res["labels"] and res["labels"][k] != v:
            res["annotations"].append(f"V6 label_mismatch: {k} submitted {v!r}, code {res['labels'][k]!r}")
    d = abs(float(base["normalized"]["delta_pts"]))
    if 0 < d < 0.05 or d > 50:
        res["annotations"].append(f"delta_pts_scale_suspect: {base['normalized']['delta_pts']}")
    for k, x in (("normalized", m_n), ("long_run_op_margin", m_l)):           # Q3b N3: the operating analogue of roe_at_record_peak
        if x >= bar[PEAK_QUANTILE]:
            res["annotations"].append(f"margin_at_record_peak: {k} {x:.4f} at or above the record's {PEAK_QUANTILE} {bar[PEAK_QUANTILE]:.4f}")
    # V3g (the CROSS_CHECK_Q2 re-run): revenue growth above the filed record's maximum, and terminal growth above the MRI long-run growth
    # anchor, need a supported reason quoting filed items of two fiscal years, as a margin outside the record does
    g_anchor = b.get("g_anchor")
    if g_anchor is None:
        res["annotations"].append("g_anchor_missing: terminal growth not checked against the long-run anchor")
    gmax = (b.get("record") or {}).get("rev_growth_max")
    for name in ("base", "bear", "bull"):
        keys = None if name == "base" else set(out.get(name) or {})
        sc = merged(out, name)
        g = float(sc["terminal_g"])
        if (keys is None or "terminal_g" in keys) and g_anchor is not None and g > g_anchor and not span_ok(name, "terminal_g"):
            unsupported((name, "terminal_g"), f"V3g terminal_g {g:.4f} above the long-run growth anchor {g_anchor:.4f} with no supported "
                                              f"reason quoting filed items of two fiscal years")
        if r - g < SPREAD_MIN:
            res["annotations"].append(f"terminal_spread_thin: {name} r - g_T = {r - g:.4f}")
        if gmax is not None:
            growths = [("rev_growth", x) for x in sc["rev_growth"]] + [("normalized", float(sc["normalized"]["rev_growth"]))]
            if name == "base":
                growths += [("investment_path", yr["revenue_growth"]) for yr in (ip or [])]
            for k, x in growths:
                if (keys is None or k in keys) and x > gmax and not span_ok(name, k):
                    unsupported((name, k), f"V3g revenue growth {x:.4f} above the filed record's maximum {gmax:.4f} with no supported "
                                           f"reason quoting filed items of two fiscal years")
    # compute every scenario; V1 recompute; V2 seam; V9 monotone values
    for name in ("bear", "base", "bull"):
        try:
            inp = forecast.assemble(merged(out, name), b, bar, r=r)
            v = desk.value_operating(inp)
        except desk.DeskRefusal as e:
            res["unsupported"].setdefault(f"{name}.desk", []).append(f"desk refusal {e.code}: {e}")
            continue
        _recompute(inp, v)
        res["results"][name] = v
        res["values"][name] = v["value_per_share"]
        if name == "base" and not inp["H"] and v["seam_ratio"] is not None and not SEAM_BAND[0] <= v["seam_ratio"] <= SEAM_BAND[1]:
            res["annotations"].append(f"V2 flow_seam_out_of_band: {v['seam_ratio']:.3f}")
    # B12b: the value at O5's market-weight delta, as a sensitivity on every levered result (annotation, never a gate)
    if res["results"].get("base") and b.get("delta", 0) > 0 and b.get("delta_market") is not None:
        try:
            alt = desk.value_operating(forecast.assemble(merged(out, "base"), dict(b, delta=b["delta_market"]), bar, r=r))
            res["sensitivity"] = {"value_at_delta_market": alt["value_per_share"], "delta_book": b["delta"], "delta_market": b["delta_market"]}
        except desk.DeskRefusal as e:
            res["sensitivity"] = {"value_at_delta_market": None, "refused": e.code}
    vv = res["values"]
    for name, v in vv.items():
        if not v > 0:
            res["annotations"].append(f"value_not_positive: {name} {v:.4f}")
    if len(vv) == 3 and not vv["bear"] <= vv["base"] <= vv["bull"]:
        unsupported(("scenarios", "values"), f"V9: values not monotone {vv}")
    if res["unsupported"]:
        res["status"] = "valuation_incomplete"
    return res


def _recompute(inp, v):
    """V1: the levels flows recomputed independently of desk.d2_flow, the equity sum, and value per share (ruling 16)."""
    def same(a, c):
        return abs(a - c) <= 1e-9 * max(1.0, abs(a), abs(c))
    rev, cx, n = inp["revenue"], inp["capex"], v["levels_years"]
    for t in range(1, n + 1):
        x = rev[t] * inp["margin"][t - 1]
        da = v["da_path"][t - 1]
        nwc = inp["w"] * (rev[t] - rev[t - 1])
        reinvest = cx[t - 1] - da + nwc
        lease = (inp["p_ratio"] - inp["rou_ratio"]) * rev[t]
        flow = x - reinvest + inp["delta"] * reinvest - lease + inp["tau"] * v["amort_path"][t - 1]
        if not same(flow, v["flows_all"][t - 1]):
            raise AssertionError(f"V1: the year-{t} levels flow {v['flows_all'][t - 1]} != {flow} recomputed")
    if not same(v["pv_levels"] + v["pv_flows"] + v["tv_pv"] + v["shield_after_n_pv"], v["equity_value"]):
        raise AssertionError("V1: the equity sum")
    if not same(v["value_per_share"], (v["equity_value"] * v.get("rollforward_factor", 1.0) + inp["excess_cash"]) / inp["shares"]):
        raise AssertionError("V1: value per share")

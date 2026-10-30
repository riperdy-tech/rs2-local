"""checks.py - the checks V1-V11 on one valuation_inputs output (SPEC_m3q §4; WO_Q5 §2).

check(out, items, ticker, statements, b, bar, r) returns
  {"status": "ok" | "valuation_incomplete" | "invalid", "unsupported": {input: [reason]}, "annotations": [...], "labels": {...},
   "values": {scenario: per-share value}, "results": {scenario: desk result}}
- "invalid": the output's shape fails V1 (nothing is computed; the task's repair turn gets the failures).
- "valuation_incomplete": some judgment input is unsupported after the contract rules (V3, V4, V7, V9, V10, V11, or no supported reason).
  The values are still computed and reported (a measurement is never deleted), but the result is marked incomplete.
- Annotations (V2, V6 mismatches) gate nothing.
No input is ever replaced by a code value.
"""
import math
import re

from qwen_c import contract
from qwen_c.value import desk, forecast

CHECKS_VERSION = "m3q.checks.v1"
FILED_KINDS = ("filed_record", "statement", "annual_section", "quarterly_section")
REQUIRED = ("rev_growth", "op_margin", "normalized", "transition", "fade_years", "long_run_op_margin", "terminal_ronic", "terminal_g",
            "margin_source")
JUDGMENT = ("rev_growth", "op_margin", "normalized", "fade_years", "long_run_op_margin", "terminal_ronic", "terminal_g", "margin_source")
MARGIN_INPUTS = ("op_margin", "normalized", "long_run_op_margin")
MARGIN_SOURCES = ("record", "pricing_or_mix", "investment_in_explicit_years", "investment_after_year5", "decline")
ORDERED = ("rev_growth", "op_margin", "normalized", "long_run_op_margin", "terminal_ronic", "terminal_g")   # V9: Bear <= Base <= Bull
SEAM_BAND = (0.67, 1.5)
_DIRECTION = re.compile(r"\b(above|higher than|exceeds?|over|below|lower than|under|beneath)\s+(?:the\s+)?(?:filed\s+)?"
                        r"(median|record maximum|record high|record low|record minimum|record|last year|latest year|year-?2)", re.I)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def shape(out, r):
    """V1, shape and finiteness. [failure] (empty when valid)."""
    f = []
    sc = out.get("base")
    if not isinstance(sc, dict):
        return ["base missing"]
    for k in REQUIRED:
        if k not in sc:
            f.append(f"base.{k} missing")
    if f:
        return f
    for k in ("rev_growth", "op_margin"):
        if not (isinstance(sc[k], list) and len(sc[k]) == 2 and all(_num(v) for v in sc[k])):
            f.append(f"base.{k} must be two finite numbers")
    nm = sc["normalized"]
    if not (isinstance(nm, dict) and nm.get("baseline") in forecast.BASELINES and nm.get("year") in (3, 4, 5)
            and _num(nm.get("delta_pts")) and _num(nm.get("rev_growth"))):
        f.append("base.normalized needs year 3..5, a baseline, finite delta_pts and rev_growth")
    if sc["transition"] not in forecast.TRANSITIONS:
        f.append("base.transition unknown")
    if not (isinstance(sc["fade_years"], int) and 1 <= sc["fade_years"] <= 30):
        f.append("base.fade_years must be an integer 1..30")
    if not (sc["terminal_ronic"] == "unlimited" or (_num(sc["terminal_ronic"]) and sc["terminal_ronic"] > 0)):
        f.append("base.terminal_ronic must be > 0 or 'unlimited'")
    if not (_num(sc["terminal_g"]) and sc["terminal_g"] < r):
        f.append(f"base.terminal_g must be finite and below the cost of equity {r}")
    if not _num(sc["long_run_op_margin"]):
        f.append("base.long_run_op_margin must be finite")
    if sc["margin_source"] not in MARGIN_SOURCES:
        f.append("base.margin_source unknown")
    p = out.get("prob") or {}
    if not (all(_num(p.get(k)) and p[k] >= 0 for k in ("bear", "base", "bull")) and abs(sum(p[k] for k in ("bear", "base", "bull")) - 1) <= 0.01):
        f.append("prob: bear, base, bull >= 0 summing to 1 +- 0.01")
    if not isinstance(out.get("reasons"), list):
        f.append("reasons must be a list")
    return f


def merged(out, name):
    sc = dict(out["base"])
    sc.update(out.get(name) or {})
    return sc


def _key(path):
    """'base.normalized.delta_pts' -> ('base', 'normalized')."""
    parts = path.split(".")
    return (parts[0], parts[1]) if len(parts) >= 2 else (parts[0], "")


def reasons_by_input(out, items, ticker, statements):
    """{(scenario, input): [{"reason", "support", "kinds", "periods"}]}, every reason checked by contract.check_claim."""
    texts = {k: v["text"] for k, v in items.items()}
    got = {}
    for rz in out.get("reasons") or []:
        claim = {"claim": rz.get("claim", ""), "fact_ids": rz.get("fact_ids") or [], "quotes": rz.get("quotes") or [],
                 "numbers": rz.get("numbers") or []}
        chk = contract.check_claim(claim, texts, ticker, statements)
        cited = [items[i] for i in claim["fact_ids"] if i in items]
        got.setdefault(_key(rz.get("input", "")), []).append(
            {"reason": rz, "support": chk["support"], "failures": chk.get("support_failures"),
             "kinds": {c["kind"] for c in cited}, "periods": {str(c.get("period"))[:4] for c in cited if c["kind"] in FILED_KINDS}})
    return got


def _supported(rs):
    return [x for x in rs if x["support"] == contract.SUPPORTED]


def _direction_contradiction(claim, value, bar):
    for word, ref in _DIRECTION.findall(claim or ""):
        ref = ref.lower()
        ref_v = {"median": bar["median"], "last year": bar["last"], "latest year": bar["last"], "year-2": None, "year2": None}.get(ref)
        if ref.startswith("record"):
            ref_v = bar["min"] if ("low" in ref or "minimum" in ref) else bar["max"]
        if ref_v is None:
            continue
        up = word.lower() in ("above", "higher than", "exceeds", "exceed", "over")
        if (up and not value > ref_v) or (not up and not value < ref_v):
            return f"says {word} the {ref} ({ref_v:.4f}) but the input is {value:.4f}"
    return None


def check(out, items, ticker, statements, b, bar, r):
    res = {"version": CHECKS_VERSION, "status": "ok", "unsupported": {}, "annotations": [], "labels": {}, "values": {}, "results": {}}
    bad = shape(out, r)
    if bad:
        return dict(res, status="invalid", failures=bad)
    by = reasons_by_input(out, items, ticker, statements)

    def unsupported(key, why):
        res["unsupported"].setdefault(f"{key[0]}.{key[1]}", []).append(why)

    base = out["base"]
    # every judgment input needs a supported reason; V4: margin inputs need one citing a filed item
    for k in JUDGMENT:
        sup = _supported(by.get(("base", k), []))
        if not sup:
            unsupported(("base", k), "no supported reason")
        elif k in MARGIN_INPUTS and not any(x["kinds"] & set(FILED_KINDS) for x in sup):
            unsupported(("base", k), "V4: no supported reason cites a filed statement, section or record year")
    path, m_n = forecast.build_path(base, bar, b["R0"])
    m_l = float(base["long_run_op_margin"])
    # V3: a margin outside the filed record needs a supported reason spanning >= 2 filed fiscal years
    for k, v in (("normalized", m_n), ("long_run_op_margin", m_l)):
        if not bar["min"] <= v <= bar["max"]:
            span = [x for x in _supported(by.get(("base", k), [])) if len(x["periods"]) >= 2]
            if not span:
                unsupported(("base", k), f"V3 unsupported_premium: {v:.4f} outside the filed record [{bar['min']:.4f}, {bar['max']:.4f}] "
                                         f"with no supported reason spanning two filed fiscal years")
    # V10: a reason's stated direction must agree with the input
    for k, v in (("normalized", m_n), ("long_run_op_margin", m_l)):
        for x in by.get(("base", k), []):
            why = _direction_contradiction(x["reason"].get("claim"), v, bar)
            if why:
                unsupported(("base", k), f"V10 reason contradicts its input: {why}")
    # V7: a shrinking Base with positive terminal growth needs a supported reason on terminal_g (already required above, so the
    # rule is that the reason must exist AND be supported; recorded as its own failure for the report)
    shrink = sum(1 for g in (path[0]["rev_growth"], path[1]["rev_growth"], float(base["normalized"]["rev_growth"])) if g < 0)
    if shrink >= 2 and base["terminal_g"] > 0 and not _supported(by.get(("base", "terminal_g"), [])):
        unsupported(("base", "terminal_g"), "V7: Base revenue shrinks yet terminal_g > 0 without a supported reason")
    # V11: a margin bought after year 5 enters through the O2c investment path
    src, ip = base["margin_source"], base.get("investment_path")
    if src == "investment_after_year5" and not ip:
        unsupported(("base", "margin_source"), "V11: investment_after_year5 needs investment_path (O2c)")
    if src in ("record", "decline") and m_l > path[4]["op_margin"] + 1e-12:
        unsupported(("base", "margin_source"), f"V11: margin_source {src!r} with a long-run margin above year 5's")
    # V9: scenario order on replaced inputs, unless the scenario's own reason on that input is supported
    for name, sign in (("bear", -1), ("bull", 1)):
        for k, v in (out.get(name) or {}).items():
            if k not in ORDERED:
                continue
            bv = base.get(k)
            pairs = list(zip(v, bv)) if isinstance(v, list) and isinstance(bv, list) else [(v, bv)]
            if k == "normalized":
                pairs = [(forecast.build_path(merged(out, name), bar, b["R0"])[1], m_n)]
            if k == "terminal_ronic":
                pairs = [(math.inf if a == "unlimited" else a, math.inf if c == "unlimited" else c) for a, c in pairs]
            if all(_num(a) or a == math.inf for a, _ in pairs) and any(sign * (a - c) < 0 for a, c in pairs if _num(c) or c == math.inf):
                if not _supported(by.get((name, k), [])):
                    unsupported((name, k), f"V9: {name} {k} on the wrong side of Base without a supported reason")
    # V6: labels by code
    pct = (m_n - bar["min"]) / (bar["max"] - bar["min"]) if bar["max"] > bar["min"] else 0.5
    res["labels"] = {"cycle_position": "trough" if pct < 1 / 3 else ("mid" if pct <= 2 / 3 else "peak"),
                     "margin_persistence": "above_median" if m_l > bar["median"] else ("below_median" if m_l < bar["median"] else "at_median"),
                     "growth_trajectory": "shrinking" if shrink >= 2 else "growing"}
    for k, v in (out.get("labels") or {}).items():
        res["labels"][f"{k}_submitted"] = v
        if k in res["labels"] and res["labels"][k] != v:
            res["annotations"].append(f"V6 label_mismatch: {k} submitted {v!r}, code {res['labels'][k]!r}")
    # compute every scenario; V1 recompute; V2 seam; V9 monotone values
    for name in ("bear", "base", "bull"):
        try:
            inp = forecast.assemble(merged(out, name), b, bar, r=r)
            v = desk.value_operating(inp)
        except desk.DeskRefusal as e:
            res["unsupported"].setdefault(f"{name}.desk", []).append(f"V1 desk refusal {e.code}: {e}")
            continue
        _recompute(inp, v)
        res["results"][name] = v
        res["values"][name] = v["value_per_share"]
        if name == "base" and not inp["H"] and v["seam_ratio"] is not None and not SEAM_BAND[0] <= v["seam_ratio"] <= SEAM_BAND[1]:
            res["annotations"].append(f"V2 flow_seam_out_of_band: {v['seam_ratio']:.3f}")
    vv = res["values"]
    if len(vv) == 3 and not vv["bear"] <= vv["base"] <= vv["bull"]:
        unsupported(("scenarios", "values"), f"V9: values not monotone {vv}")
    if res["unsupported"]:
        res["status"] = "valuation_incomplete"
    return res


def _recompute(inp, v):
    """V1: X = R m per explicit year; the equity sum; value per share. A failure is an engine defect: raised, never annotated."""
    def same(a, c):
        return abs(a - c) <= 1e-9 * max(1.0, abs(a), abs(c))
    for t, x in enumerate(v["x_all"][:v["levels_years"]], 1):
        if not same(x, inp["revenue"][t] * inp["margin"][t - 1]):
            raise AssertionError(f"V1: X != R m in year {t}")
    if not same(v["pv_levels"] + v["pv_flows"] + v["tv_pv"] + v["shield_after_n_pv"], v["equity_value"]):
        raise AssertionError("V1: the equity sum")
    if not same(v["value_per_share"], (v["equity_value"] + inp["excess_cash"]) / inp["shares"]):
        raise AssertionError("V1: value per share")

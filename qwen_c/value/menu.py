"""menu.py - the valuation menus of prompt v8 (F_SPEC_valuation_menu §2, §3, §5): every option the model may choose, resolved to a
number by code.

menus(b, bar, r, route): the offered options of each input with their numbers (None prints "not available").
read_guidance: the number a `guidance` option takes from its one cited sentence (§2.2), or why it cannot be read.
resolve: {departure key: number} of a reply's options; capex is its five yearly ratios. scenario: those numbers in the shape
forecast.assemble (forecast_fin.assemble) takes. departed: whether a key's number differs from the record-neutral reply's (§3).
neighbours / pick: the per-key Bear and Bull settings of the uncertain keys (§5).
The model never types a number: a menu value, a grid step or a figure read from a cited sentence is all it can reach.
"""
import statistics

from qwen_c import contract
from qwen_c.value import forecast

MENU_VERSION = "m3q.menu.v1"
STEPS = (-3, -2, -1, -0.5, 0, 0.5, 1, 2, 3)            # points added to an anchor
YEARS = (3, 4, 5)
FADES = (10, 5, 15, 20)
ANCHORS = ("median", "p25", "p75", "last")
DRIVERS = ("pricing", "volume", "mix", "cost_program", "capex_program", "guidance", "backlog", "cycle_recovery", "cycle_downturn",
           "competition", "regulation", "secular_decline", "return_to_growth", "record_persistence")
SIGNS = ("as_printed", "negative")
TOL, TOL_RONIC = 0.001, 0.001                          # §3: 0.1 point for margins and growth, 0.1% relative for RONIC
NEIGHBOUR_GROWTH = 0.02                                # §5: +-2 points where no offered growth value lies beyond Base
CLIP = 0.03                                            # §5: margin neighbours stay inside [p25 - 3 points, p75 + 3 points]
MIN_GROWTH_YEARS = 3                                   # ruling 10: record_median and last need 3 yearly growths
# departure key -> kind, by route
KEYS = {"operating": {"rev_growth.y1": "growth", "rev_growth.y2": "growth", "op_margin.y1": "margin", "op_margin.y2": "margin",
                      "normalized.margin": "norm", "normalized.rev_growth": "growth", "long_run_op_margin": "long",
                      "fade_years": "fade", "terminal_ronic": "ronic", "terminal_g": "tg", "capex": "capex"},
        "financial": {"book_growth.y1": "growth", "book_growth.y2": "growth", "roe.y1": "margin", "roe.y2": "margin",
                      "normalized.roe": "norm", "normalized.book_growth": "growth", "long_run_roe": "long", "fade_years": "fade",
                      "terminal_g": "tg"}}
NEUTRAL = {"operating": {"rev_growth.y1": "anchor", "rev_growth.y2": "anchor", "op_margin.y1": "median", "op_margin.y2": "median",
                         "normalized.margin": ("median", 0), "normalized.rev_growth": "anchor", "long_run_op_margin": ("normalized", 0),
                         "fade_years": 10, "terminal_ronic": "no_growth_value", "terminal_g": "anchor", "capex": "pooled"},
           "financial": {"book_growth.y1": "neutral", "book_growth.y2": "neutral", "roe.y1": "median", "roe.y2": "median",
                         "normalized.roe": ("median", 0), "normalized.book_growth": "neutral", "long_run_roe": ("normalized", 0),
                         "fade_years": 10, "terminal_g": "neutral"}}
NEUTRAL_YEAR = 3
# where a reverted key is pinned: its neutral option, except a long run anchored on normalized, which takes the neutral NUMBER (median)
# so that it stays reverted while normalized departs (BUILD_NOTES)
REVERT = {"long_run_op_margin": ("median", 0), "long_run_roe": ("median", 0)}
# guidance metrics a key takes, and the unit of each metric
METRICS = {"rev_growth.y1": ("revenue_level", "revenue_growth"), "rev_growth.y2": ("revenue_level", "revenue_growth"),
           "normalized.rev_growth": ("revenue_level", "revenue_growth"), "op_margin.y1": ("op_margin",), "op_margin.y2": ("op_margin",),
           "capex": ("capex_level",), "book_growth.y1": ("book_growth",), "book_growth.y2": ("book_growth",),
           "normalized.book_growth": ("book_growth",), "roe.y1": ("roe",), "roe.y2": ("roe",)}
LEVELS = ("revenue_level", "capex_level")
SCALE = {"": 1.0, "k": 1e3, "m": 1e6, "bn": 1e9, "tn": 1e12}


def _record_growth(rec):
    vals = [rec[e] for e in sorted(rec)]
    return (statistics.median(vals), vals[-1]) if len(vals) >= MIN_GROWTH_YEARS else (None, None)


def _ok(x, lo=-1.0, hi=1.0):
    return x if x is not None and lo < x < hi else None


def neutral_ronic(b, r):
    """The record-neutral terminal RONIC: the return on capital whose O5 equity return is r (Q3e-1), so growth adds nothing."""
    d = float(b.get("delta") or 0.0)
    return r if not d else (1.0 - d) * r + d * float(b["kd"]) * (1.0 - float(b["tau"]))


def menus(b, bar, r, route):
    """{"growth", "margin", "anchor", "terminal_g", ("ronic", "capex")}: {option: number or None}, the record-neutral option first;
    plus the context the resolution needs. `b` carries g_anchor."""
    ga, rec = b.get("g_anchor"), b.get("record") or {}
    med_g, last_g = _record_growth(rec.get("rev_growth" if route == "operating" else "book_growth") or {})
    m = {"route": route, "bar": bar, "r": r, "R0": b.get("R0"), "ga": ga,
         "margin": {k: _ok(bar[k]) for k in ANCHORS}, "anchor": {k: bar[k] for k in ANCHORS}}
    tg = {"anchor": ga, "half_anchor": None if ga is None else ga / 2, "zero": 0.0, "decline": med_g if med_g is not None and med_g < 0 else None}
    if route == "operating":
        m["growth"] = {"anchor": ga, "record_median": med_g, "last": last_g, "zero": 0.0}
        n, r0 = neutral_ronic(b, r), b.get("ronic0")
        up = r0 is not None and r0 > n * (1 + TOL_RONIC)
        m["ronic"] = {"no_growth_value": n, **{k: (1.0 / (1.0 / n + (1.0 / r0 - 1.0 / n) * f) if up else None)
                                               for k, f in (("quarter", 0.25), ("half", 0.5), ("three_quarters", 0.75))},
                      "ronic0": r0 if up else None}
        cr = rec.get("capex_ratio") or {}
        m["capex"] = {"pooled": (b["c_ratio"],) * 5, "record_last": (cr[max(cr)],) * 5 if cr else None,
                      "record_max": (max(cr.values()),) * 5 if cr else None}
        m.update(c_ratio=b.get("c_ratio"), capex_record=cr, growth_max=rec.get("rev_growth_max"), growth_min=None)
    else:
        neutral_g = None if ga is None or not bar["median"] > 0 else min(ga, 0.5 * bar["median"])
        m["growth"] = {"neutral": neutral_g, "record_median": med_g, "last": last_g, "anchor": ga}
        tg = {"neutral": neutral_g, **tg}
        m.update(growth_max=rec.get("book_growth_max"), growth_min=rec.get("book_growth_min"))
    m["terminal_g"] = {k: (v if v is not None and v < r else None) for k, v in tg.items()}
    return m


def offered(m, kind):
    """{option: number or None} of a kind other than norm and long (an anchor plus a grid step)."""
    if kind == "fade":
        return {f: f for f in FADES}
    return m[{"tg": "terminal_g"}.get(kind, kind)]


def option(base, key):
    """The reply's option for a departure key: (anchor, step) for the normalized margin and the long run."""
    if key.startswith("normalized."):
        nm = base["normalized"]
        return (nm["anchor"], nm["step"]) if key in ("normalized.margin", "normalized.roe") else nm[key.split(".")[1]]
    if key.startswith("long_run"):
        return base[key]["anchor"], base[key]["step"]
    head, _, tail = key.partition(".")
    return base[head][tail] if tail else base[key]


def set_option(base, key, value):
    """A copy of the base options with one key's option replaced."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    if key in ("normalized.margin", "normalized.roe"):
        out["normalized"].update(anchor=value[0], step=value[1])
    elif key.startswith("normalized."):
        out["normalized"][key.split(".")[1]] = value
    elif key.startswith("long_run"):
        out[key] = {"anchor": value[0], "step": value[1]}
    elif "." in key:
        head, tail = key.split(".")
        out[head][tail] = value
    else:
        out[key] = value
    return out


def neutral_base(route):
    """The record-neutral reply's base options."""
    g, mg, lr = ("rev_growth", "op_margin", "long_run_op_margin") if route == "operating" else ("book_growth", "roe", "long_run_roe")
    base = {g: {}, mg: {}, "normalized": {"year": NEUTRAL_YEAR}, lr: {}}
    for key, opt in NEUTRAL[route].items():
        base = set_option(base, key, opt)
    return base


def _figures(text, unit):
    """[(value, start, end)] of the sentence's figures in the unit ("%" or "$"), years (1990-2099, no unit) skipped; and the text."""
    s = contract.norm_figure_text(text)
    out = []
    for v, cur, u, core, _, a, z in contract.read_figures(text):
        if not cur and not u and core.isdigit() and 1990 <= int(core) <= 2099:
            continue
        if (unit == "%" and u == "%") or (unit == "$" and cur == "$" and u in SCALE):
            out.append((float(v) * (0.01 if unit == "%" else SCALE[u]), a, z))
    return out, s


def read_figure(text, metric, ordinal):
    """(number, None) or (None, why): the `ordinal`-th figure of the metric's unit; a range (two adjacent figures joined by "to" or a
    dash) is read at its midpoint, named by its first figure."""
    figs, s = _figures(text, "$" if metric in LEVELS else "%")
    if not 1 <= ordinal <= len(figs):
        return None, f"ordinal {ordinal} of {len(figs)} figures in the unit"
    def joined(i):
        return i + 1 < len(figs) and contract._RANGE_GAP.fullmatch(s[figs[i][2]:figs[i + 1][1]]) is not None
    k = ordinal - 1
    if k > 0 and joined(k - 1):
        return None, f"ordinal {ordinal} names the second figure of a range"
    return ((figs[k][0] + figs[k + 1][0]) / 2 if joined(k) else figs[k][0]), None


def read_guidance(entry, key, ids, g1, m, fy0, fy_of):
    """(number, None) or (None, why) for one guidance entry (§2.2). `g1` the resolved year-1 growth (a level's year-1 revenue);
    `fy_of(period)` the fiscal year of a period."""
    ev = ids[entry["evidence"]]
    fy = fy_of(ev.get("period"))
    if not ev.get("sentence") or not ((fy is not None and fy >= fy0) or str(ev.get("period") or "")[:10] > fy0):
        return None, "the evidence is not a sentence of a filing or 8-K item dated in or after the base fiscal year"
    x, why = read_figure(ev["text"], entry["metric"], entry["ordinal"])
    if why:
        return None, why
    if entry["sign"] == "negative":
        if entry["metric"] in LEVELS:
            return None, "a level is never negative"
        x = -abs(x)
    if entry["metric"] == "capex_level":
        return x / (m["R0"] * (1 + g1)), None
    if entry["metric"] == "revenue_level":
        if key == "rev_growth.y1":
            return x / m["R0"] - 1, None
        if key == "rev_growth.y2":
            return x / (m["R0"] * (1 + g1)) - 1, None
        return None, "a revenue level converts for years 1 and 2 only"
    return x, None


def resolve(base, guided, m, overrides=None):
    """{key: number} of the options `base` ({key: number} of the read guidance in `guided`); `overrides` replace keys' numbers (a
    scenario neighbour), and a long run anchored on normalized follows the normalized number unless it is itself overridden."""
    o, out = overrides or {}, {}
    for key, kind in KEYS[m["route"]].items():
        if key in o:
            out[key] = o[key]
            continue
        opt = option(base, key)
        if opt == "guidance":
            out[key] = guided[key] if kind != "capex" else capex_path(guided[key], m)
        elif kind in ("norm", "long"):
            a, step = opt
            out[key] = (out[NORM[m["route"]]] if a == "normalized" else m["anchor"][a]) + float(step) * 0.01
        else:
            out[key] = offered(m, kind)[opt]
    return out


NORM = {"operating": "normalized.margin", "financial": "normalized.roe"}


def capex_path(c1, m):
    """§2.1: the guidance option's five ratios, the year-1 ratio moving linearly to the pooled ratio by year 5 (forecast's own rule)."""
    return tuple(forecast.capex_ratios({"year1": c1}, m["c_ratio"]))


def scenario(base, nums, m):
    """The numbers as forecast.assemble's (forecast_fin.assemble's) scenario, on a linear transition. The normalized margin goes as its
    anchor plus delta_pts: the step itself unless a neighbour moved the number, so the neutral is bar[median] + 0.0 exactly, as
    checks._neutral_op always computed it."""
    nm, bar, nk = base["normalized"], m["bar"], NORM[m["route"]]
    delta = float(nm["step"])
    if nums[nk] != bar[nm["anchor"]] + delta * 0.01:
        delta = (nums[nk] - bar[nm["anchor"]]) * 100
    norm = {"year": nm["year"], "baseline": nm["anchor"], "delta_pts": delta}
    common = {"transition": "linear", "transition_year": None, "fade_years": nums["fade_years"], "terminal_g": nums["terminal_g"]}
    if m["route"] == "financial":
        return dict(common, book_growth=[nums["book_growth.y1"], nums["book_growth.y2"]], roe=[nums["roe.y1"], nums["roe.y2"]],
                    normalized=dict(norm, book_growth=nums["normalized.book_growth"]), long_run_roe=nums["long_run_roe"])
    cp = nums["capex"]
    cp = None if cp == m["capex"]["pooled"] else ({"year1": cp[0]} if cp == capex_path(cp[0], m) else list(cp))
    return dict(common, rev_growth=[nums["rev_growth.y1"], nums["rev_growth.y2"]], op_margin=[nums["op_margin.y1"], nums["op_margin.y2"]],
                normalized=dict(norm, rev_growth=nums["normalized.rev_growth"]), long_run_op_margin=nums["long_run_op_margin"],
                terminal_ronic=nums["terminal_ronic"], capex_path=cp, investment_path=None)


def departed(key, nums, neutral, m):
    a, c = nums[key], neutral[key]
    kind = KEYS[m["route"]][key]
    if kind in ("fade", "capex"):
        return a != c
    if kind == "ronic":
        return abs(a - c) > TOL_RONIC * abs(c)
    return abs(a - c) > TOL


def direction(key, nums, neutral, m):
    """up, down or none: the departure's direction, by code (the capex path by its mean ratio)."""
    a, c = nums[key], neutral[key]
    if KEYS[m["route"]][key] == "capex":
        a, c = sum(a) / 5, sum(c) / 5
    return "none" if not departed(key, nums, neutral, m) else ("up" if a > c else "down")


def neighbours(key, base, nums, m, guided):
    """(down, up): the numbers of a key's Bear-side and Bull-side neighbours of Base (§5), None where there is none."""
    kind, v, bar = KEYS[m["route"]][key], nums[key], m["bar"]
    if kind in ("margin", "norm", "long"):
        step = 0 if kind == "margin" else float(option(base, key)[1])
        root = v - step * 0.01
        lo, hi = bar["p25"] - CLIP, bar["p75"] + CLIP
        def first(cands):
            return next((x for x in (min(hi, max(lo, root + c * 0.01)) for c in cands) if abs(x - v) > TOL), None)
        grid = [s for s in STEPS if not (step == 0 and abs(s) == 0.5)]
        return first(sorted((s for s in grid if s < step), reverse=True)), first(sorted(s for s in grid if s > step))
    if kind == "fade":
        f = sorted(FADES)
        i = f.index(v)
        return (f[i - 1] if i else None), (f[i + 1] if i + 1 < len(f) else None)
    pts = [x for x in offered(m, kind).values() if x is not None] + ([guided[key]] if key in guided and kind != "capex" else [])
    if kind == "capex":
        pts += [capex_path(guided[key], m)] if key in guided else []
        mean = sum(v) / 5
        down = max((p for p in pts if sum(p) / 5 < mean), key=sum, default=None)
        return down, min((p for p in pts if sum(p) / 5 > mean), key=sum, default=None)
    tol = TOL_RONIC * v if kind == "ronic" else TOL
    down = max((p for p in pts if p < v - tol), default=None)
    up = min((p for p in pts if p > v + tol), default=None)
    if kind == "growth":
        down, up = (v - NEIGHBOUR_GROWTH if down is None else down), (v + NEIGHBOUR_GROWTH if up is None else up)
    return down, up


def pick(value_base, value_down, value_up, down, up):
    """§5: Bear and Bull settings of one key are the arg-min and arg-max of {down, Base, up} by value (None: Base); a neighbour the
    desk refused (value None) is not a candidate. Returns (bear number or None, bull number or None)."""
    cands = [(value_base, None)] + [(v, x) for v, x in ((value_down, down), (value_up, up)) if x is not None and v is not None]
    return min(cands, key=lambda c: c[0])[1], max(cands, key=lambda c: c[0])[1]

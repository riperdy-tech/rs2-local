"""checks.py - the checks on one valuation_inputs reply of prompt v8 (F_SPEC_valuation_menu §3-§5; checks v11).

check(reply, ids, b, bar, r, fy_ends, route) returns
  {"status": "ok" | "ok_with_reverts" | "reply_invalid" | "no_call", "errors": {key: [why]}, "options", "numbers", "neutral",
   "departures", "reverts", "stamps", "annotations", "evidence", "scenarios", "values", "results", "diagnostics", ...}
- Reply errors (§4: shape and enums, an option not available, a departed key without its entry, evidence IDs that do not exist or only
  [V0], an incomplete guidance entry) go back to the model in the one repair turn; nothing is valued. check() never raises on model
  content (ruling 22).
- Every number is code's (menu.py). A departure is a key whose number differs from the record-neutral reply's. Its entry's evidence
  IDs must pass the key's set rules (V3, V3g, V4, V13, N6; issuance and release on the financial route), or the key reverts to neutral,
  stamped `departure_reverted: <key> <rule>`, and every rule runs again until nothing changes (at most one round per key). A guidance
  option whose sentence cannot be read reverts the same way, stamped `guidance_unreadable`.
- Code builds Bear and Bull from the uncertain keys' neighbours (§5); the probabilities are fixed. V1 recomputes every valued scenario.
  Past the reply rules a crash is the code's: raised as an engine defect, never "reply_invalid".
"""
import math

from qwen_c.value import desk, forecast, forecast_fin, menu

CHECKS_VERSION = "m3q.checks.v11"   # v11 2026-11-03 F_SPEC_valuation_menu: menus, typed departures, reverts to a fixed point   # v10 RR_Q7: V12   # v9 CROSS_CHECK_Q3e   # v8..v3 2026-10-30/31 (see git)
FILED_KINDS = ("statement", "annual_section", "quarterly_section")          # [Y] filed_record items cannot carry V3's span
V4_KINDS = FILED_KINDS + ("filed_record",)
PROB = {"bear": 0.25, "base": 0.5, "bull": 0.25}                           # §5: fixed
SEAM_BAND = (0.67, 1.5)
SPREAD_MIN = 0.02                                                           # N7 (annotation)
ALWAYS_STAMPS = ["v5_withdrawn_status_unenforced"]                          # ruling 15
FIN_STAMPS = ["capital_constraint_not_modeled"]
RELEASE_SHARE = 0.25          # Q3b N2: a cumulative release of more than a quarter of book over years 1-5 is annotated
PEAK_QUANTILE = "p75"         # Q3b N3: a normalized or long-run value at or above the record's p75 is annotated
NEUTRAL_BAND = (0.5, 2.0)     # Q3c 1-4 (B13): a scenario valued outside 0.5x-2x the record-neutral reply is annotated
NEUTRAL_FADE = 10                                   # WO_Q6 §4
GROWTH_DRIVERS = ("return_to_growth", "cycle_recovery")                     # V7
OBJECTS = {"operating": ("rev_growth", "op_margin", "normalized", "long_run_op_margin"),
           "financial": ("book_growth", "roe", "normalized", "long_run_roe")}
SCALARS = {"operating": ("fade_years", "terminal_ronic", "terminal_g", "capex"), "financial": ("fade_years", "terminal_g")}


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


# ------------------------------------------------------------------ reply errors (§4)
def _choice_error(key, kind, opt, m):
    """None if the option of `key` is on its menu and available, else why."""
    if kind in ("norm", "long"):
        if not (isinstance(opt, tuple) and len(opt) == 2):
            return "{anchor, step}"
        a, step = opt
        anchors = menu.ANCHORS + (("normalized",) if kind == "long" else ())
        if a not in anchors or isinstance(step, bool) or step not in menu.STEPS:
            return f"anchor one of {anchors}, step one of {menu.STEPS}"
        return None
    menu_ = menu.offered(m, kind)
    if opt == "guidance" and key in menu.METRICS:
        return None
    if isinstance(opt, bool) or not isinstance(opt, (str, int)) or opt not in menu_:
        return f"one of {list(menu_) + (['guidance'] if key in menu.METRICS else [])}"
    return None if menu_[opt] is not None else f"{opt} is not available"


def _shape(reply, ids, m):
    """({key: [why]}, base options) on the reply's form; the base is None when it cannot be read."""
    route, err = m["route"], {}
    def add(k, why):
        err.setdefault(k, []).append(why)
    if not isinstance(reply, dict) or not isinstance(reply.get("base"), dict):
        return {"reply": ["an object with a base object"]}, None
    base = reply["base"]
    for f in OBJECTS[route] + SCALARS[route]:
        if f not in base or (f in OBJECTS[route] and not isinstance(base[f], dict)):
            add(f, "missing" if f not in base else "an object")
    if err:
        return err, None
    if base["normalized"].get("year") not in menu.YEARS or isinstance(base["normalized"].get("year"), bool):
        add("normalized.year", f"one of {menu.YEARS}")
    guid = reply.get("guidance", {})
    if not isinstance(guid, dict):
        add("guidance", "an object keyed by input")
        guid = {}
    for key, kind in menu.KEYS[route].items():
        try:
            opt = menu.option(base, key)
            why = _choice_error(key, kind, opt, m) or (None if opt != "guidance" or key in guid else "guidance needs an entry under \"guidance\"")
        except (KeyError, TypeError):
            why = "missing"
        if why:
            add(key, why)
    for key, e in guid.items():
        if not (isinstance(e, dict) and e.get("evidence") in ids and e.get("metric") in menu.METRICS.get(key, ()) and e.get("sign") in menu.SIGNS
                and isinstance(e.get("ordinal"), int) and not isinstance(e.get("ordinal"), bool) and e["ordinal"] >= 1):
            add(f"guidance.{key}", f"an entry {{evidence: an existing ID, metric: one of {menu.METRICS.get(key, ())}, sign: one of "
                                   f"{menu.SIGNS}, ordinal: 1, 2, ...}}")
    deps = reply.get("departures", [])
    if not isinstance(deps, list):
        add("departures", "a list")
        deps = []
    seen = set()
    for i, d in enumerate(deps):
        ev = d.get("evidence") if isinstance(d, dict) else None
        if not (isinstance(d, dict) and d.get("input") in menu.KEYS[route] and d.get("driver") in menu.DRIVERS and isinstance(ev, list)
                and 1 <= len(ev) <= 4 and all(isinstance(x, str) for x in ev)):
            add(f"departures[{i}]", f"{{input: a departure key, driver: one of {menu.DRIVERS}, evidence: 1 to 4 IDs}}")
            continue
        if d["input"] in seen:
            add(d["input"], "one departures entry at most")
        seen.add(d["input"])
        bad = [x for x in ev if x not in ids]
        if bad or all(x == "V0" for x in ev):
            add(d["input"], f"evidence IDs that do not exist: {bad}" if bad else "evidence needs an ID other than V0")
    unc = reply.get("uncertain")
    if not (isinstance(unc, list) and 1 <= len(unc) <= 3 and len(set(map(str, unc))) == len(unc) and all(u in menu.KEYS[route] for u in unc)):
        add("uncertain", f"1 to 3 distinct departure keys of {list(menu.KEYS[route])}")
    return err, (None if err else base)


def _domain(nums, m):
    """Reply errors on resolved numbers: a margin or ROE outside (-1, 1), a long-run ROE not positive."""
    lo = {k: 0.0 if k == "long_run_roe" else -1.0 for k in menu.KEYS[m["route"]]}
    return {k: [f"resolves to {nums[k]:.4f}, outside ({lo[k]:g}, 1): not available"] for k, kind in menu.KEYS[m["route"]].items()
            if kind in ("margin", "norm", "long") and not lo[k] < nums[k] < 1}


# ------------------------------------------------------------------ evidence rules on departed keys (§4)
def _rule(key, entry, nums, neutral, m, ids, fy_ends):
    """The first evidence rule a departed key fails, or None."""
    kind, x, bar = menu.KEYS[m["route"]][key], nums[key], m["bar"]
    cited = [ids[i] for i in entry["evidence"]]
    filed = [c for c in cited if c["kind"] in FILED_KINDS]
    two = len({fiscal_year_of(c.get("period"), fy_ends) for c in filed} - {None}) >= 2
    if kind in ("margin", "norm", "long"):
        if not any(c["kind"] in V4_KINDS for c in cited):
            return "V4"
        if not bar["min"] <= x <= bar["max"] and not two:
            return "V3"
    if kind == "growth":
        if m["growth_max"] is not None and x > m["growth_max"] and not two:
            return "V3g"
        if m["route"] == "financial":
            roe = nums[{"book_growth.y1": "roe.y1", "book_growth.y2": "roe.y2"}.get(key, "normalized.roe")]
            if x > roe and not two:
                return "issuance"
            if m["growth_min"] is not None and x < min(m["growth_min"], 0.0) and not two:
                return "release"
    if kind == "tg":
        if m["ga"] is not None and x > m["ga"] and not two:
            return "V3g"
        if m["route"] == "financial" and x < 0 and not two:
            return "release"
    if (kind in ("ronic", "fade", "long") and menu.direction(key, nums, neutral, m) == "up") and not filed:
        return "V13"
    if kind == "capex":
        rec = list(m["capex_record"].values())
        if rec and any(not min(rec) <= c <= max(rec) for c in x) and not two:
            return "N6"
    return None


def _numeric(nums, dep, m):
    """{key: rule} of the numeric rules on departed keys: a long-run ROE at or below terminal growth (ronic_not_above_growth)."""
    if m["route"] == "financial" and nums["long_run_roe"] <= nums["terminal_g"]:
        return {k: "ronic_not_above_growth" for k in ("long_run_roe", "terminal_g") if k in dep}
    return {}


# ------------------------------------------------------------------ the check
def check(reply, ids, b, bar, r, fy_ends=(), route="operating"):
    """`ids` is sentences.index over the packet, the [Y] record items and [V0]."""
    if route not in ("operating", "financial"):
        raise ValueError(f"route {route!r}")
    res = {"version": CHECKS_VERSION, "menu": menu.MENU_VERSION, "route": route, "status": "ok", "errors": {}, "annotations": [],
           "reverts": [], "values": {}, "results": {}, "prob": dict(PROB),
           "stamps": list(ALWAYS_STAMPS) + (list(FIN_STAMPS) if route == "financial" else [])}
    try:
        m = menu.menus(b, bar, r, route)
        neutral = menu.resolve(menu.neutral_base(route), {}, m)
        if any(v is None for v in neutral.values()):                      # no growth anchor, or the anchor not below r
            return dict(res, status="no_call", reason="record_neutral_unavailable", detail=str(neutral))
        try:
            err, base = _shape(reply, ids, m)
        except (KeyError, TypeError, ValueError, AttributeError) as e:    # model content only: never raises (ruling 22)
            err, base = {"reply": [f"{type(e).__name__}: {e}"]}, None
        if err:
            return dict(res, status="reply_invalid", errors=err)
        return _check(reply, base, ids, b, bar, r, fy_ends, m, neutral, res)
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, OverflowError) as e:
        # review 2026-11-03: past the reply rules a crash is the code's, not the model's; run.py records it as engine_defect
        raise AssertionError(f"engine defect in checks: {type(e).__name__}: {e}") from e


def _check(reply, base, ids, b, bar, r, fy_ends, m, neutral, res):
    route, keys = m["route"], menu.KEYS[m["route"]]
    entries = {d["input"]: d for d in reply.get("departures") or []}
    guidance, fy0 = reply.get("guidance") or {}, b["fy0"]
    unread, pins, first = {}, {}, True               # key -> why its guidance cannot be read; key -> the rule that reverted it
    while True:
        opts = base
        for k in list(unread) + list(pins):
            opts = menu.set_option(opts, k, menu.REVERT.get(k, menu.NEUTRAL[route][k]))
        guided, bad = _read_guidance(opts, guidance, ids, m, fy0, fy_ends)
        if bad:
            unread.update(bad)
            continue
        nums = menu.resolve(opts, guided, m)
        dep = {k for k in keys if menu.departed(k, nums, neutral, m)}
        if first:
            err = _domain(nums, m)
            err.update({k: [f"departs ({_n(nums[k])} against the neutral {_n(neutral[k])}) and needs a departures entry"]
                        for k in keys if k in dep and k not in entries})
            if err:
                return dict(res, status="reply_invalid", errors=err)
            res["annotations"] += [f"departure_superfluous: {k}" for k in entries if k not in dep]
            first = False
        fails = {k: (_rule(k, entries[k], nums, neutral, m, ids, fy_ends) if k in entries else "no_entry_after_revert") for k in dep}
        fails = {k: v for k, v in {**fails, **_numeric(nums, dep, m)}.items() if v and k not in pins}
        if not fails:
            break
        pins.update(fails)
    res["reverts"] = ([f"guidance_unreadable: {k} {why}" for k, why in unread.items()]
                      + [f"departure_reverted: {k} {rule}" for k, rule in pins.items()])
    res["stamps"] += res["reverts"]
    if res["reverts"]:
        res["status"] = "ok_with_reverts"
    surviving = [entries[k] for k in keys if k in dep and k in entries]
    res.update(options={k: menu.option(opts, k) for k in keys}, year=opts["normalized"]["year"], numbers=nums, neutral=neutral,
               guided=guided, departures=surviving, directions={k: menu.direction(k, nums, neutral, m) for k in keys})
    cited = {i for d in surviving for i in d["evidence"]} | {guidance[k]["evidence"] for k in guided}
    res["evidence"] = {i: {"text": ids[i]["text"], "kind": ids[i]["kind"], "period": ids[i].get("period")} for i in sorted(cited)}
    return _valuate(opts, nums, guided, reply, b, bar, r, m, neutral, res)


def _read_guidance(opts, guidance, ids, m, fy0, fy_ends):
    """({key: number}, {key: why} of the first unreadable entry): in key order, so year 1's growth is known before a level's year 2."""
    keys, guided = menu.KEYS[m["route"]], {}
    y1 = next(iter(keys))
    for k in keys:
        if menu.option(opts, k) == "guidance":
            g1 = guided[y1] if y1 in guided else menu.offered(m, "growth").get(menu.option(opts, y1))
            x, why = menu.read_guidance(guidance[k], k, ids, g1, m, fy0, lambda p: fiscal_year_of(p, fy_ends))
            if why:
                return guided, {k: why}
            guided[k] = x
    return guided, {}


def _n(x):
    return f"{x:.4f}" if isinstance(x, float) else str(x)


def _value(sc, b, bar, r, route):
    """(desk input, desk result) of one scenario; V1 recomputed."""
    if route == "financial":
        inp = forecast_fin.assemble(sc, b, bar, r=r)
        v = forecast_fin.value(inp)
        _recompute_fin(inp, v, b)
    else:
        inp = forecast.assemble(sc, b, bar, r=r)
        v = desk.value_operating(inp)
        _recompute(inp, v)
    return inp, v


def _valuate(opts, nums, guided, reply, b, bar, r, m, neutral, res):
    route, sc = m["route"], menu.scenario(opts, nums, m)
    try:
        inp, base_v = _value(sc, b, bar, r, route)
    except desk.DeskRefusal as e:                                         # menus keep r > g and RONIC >= neutral: a data refusal
        return dict(res, status="no_call", reason=e.code, detail=str(e))
    res["results"]["base"], res["values"]["base"] = base_v, base_v["value_per_share"]

    def run(over):
        try:
            return _value(menu.scenario(opts, menu.resolve(opts, guided, m, over), m), b, bar, r, route)[1]["value_per_share"]
        except desk.DeskRefusal as e:
            res["annotations"].append(f"scenario_desk_refusal: {e.code} at {over}")
            return None
    bear, bull, log = {}, {}, {}
    for k in reply["uncertain"]:                                          # §5: per key, the arg-min and arg-max of {down, Base, up}
        down, up = menu.neighbours(k, opts, nums, m, guided)
        vd, vu = (None if x is None else run({k: x}) for x in (down, up))
        lo, hi = menu.pick(base_v["value_per_share"], vd, vu, down, up)
        log[k] = {"down": down, "up": up, "value_down": vd, "value_up": vu, "bear": lo, "bull": hi}
        bear.update({k: lo} if lo is not None else {})
        bull.update({k: hi} if hi is not None else {})
    res["scenarios"] = {"keys": log, "bear": bear, "bull": bull}
    for name, over in (("bear", bear), ("bull", bull)):
        v = run(over)
        if v is not None:
            res["values"][name] = v
    _annotate(sc, nums, inp, base_v, b, bar, r, m, res)
    _annotate_neutral(res, _neutral_fin(b, bar, r) if route == "financial" else _neutral_op(b, bar, r))
    vv = res["values"]
    res["annotations"] += [f"value_not_positive: {k} {v:.4f}" for k, v in vv.items() if not v > 0]
    if len(vv) == 3 and not vv["bear"] <= vv["base"] <= vv["bull"]:
        res["annotations"].append(f"scenario_order_not_monotone: {vv}")
    return res


def _annotate(sc, nums, inp, base_v, b, bar, r, m, res):
    """Annotations, never gates: V7, the seam, the record peak, the terminal spread, the book release, the market-delta sensitivity."""
    fin = m["route"] == "financial"
    g = ("book_growth.y1", "book_growth.y2", "normalized.book_growth") if fin else ("rev_growth.y1", "rev_growth.y2", "normalized.rev_growth")
    if sum(1 for k in g if nums[k] < 0) >= 2 and nums["terminal_g"] > 0 and not any(d["driver"] in GROWTH_DRIVERS for d in res["departures"]):
        res["annotations"].append("V7 shrinking_base_positive_terminal_growth: no return_to_growth or cycle_recovery departure")
    if (fin or not inp["H"]) and base_v["seam_ratio"] is not None and not SEAM_BAND[0] <= base_v["seam_ratio"] <= SEAM_BAND[1]:
        res["annotations"].append(f"V2 flow_seam_out_of_band: {base_v['seam_ratio']:.3f}")
    for k in (("normalized.roe", "long_run_roe") if fin else ("normalized.margin", "long_run_op_margin")):    # Q3b N3
        if nums[k] >= bar[PEAK_QUANTILE]:
            res["annotations"].append(f"{'roe' if fin else 'margin'}_at_record_peak: {k} {nums[k]:.4f} at or above the record's "
                                      f"{PEAK_QUANTILE} {bar[PEAK_QUANTILE]:.4f}")
    if r - nums["terminal_g"] < SPREAD_MIN:
        res["annotations"].append(f"terminal_spread_thin: r - g_T = {r - nums['terminal_g']:.4f}")
    if fin:
        kept = math.prod(1 + y["book_growth"] for y in inp["_path"])
        if kept < 1 - RELEASE_SHARE and min(y["roe"] for y in inp["_path"]) < r:      # Q3b N2
            res["annotations"].append(f"book_release_cumulative: keeps {kept:.3f} of book over years 1-5 with an ROE below r")
        if nums["terminal_g"] < 0 and nums["long_run_roe"] < r:
            res["annotations"].append(f"book_release_terminal: terminal_g {nums['terminal_g']:.4f} with long_run_roe below r")
        res["diagnostics"] = {"tv_share": base_v["tv_pv"] / base_v["equity_value"] if base_v["equity_value"] else None,
                              "implied_pb": base_v["value_per_share"] / (b["R1"] / b["shares"])}
    elif b.get("delta", 0) > 0 and b.get("delta_market") is not None:     # B12b: a sensitivity on every levered result
        try:
            alt = desk.value_operating(forecast.assemble(sc, dict(b, delta=b["delta_market"]), bar, r=r))
            res["sensitivity"] = {"value_at_delta_market": alt["value_per_share"], "delta_book": b["delta"], "delta_market": b["delta_market"]}
        except desk.DeskRefusal as e:
            res["sensitivity"] = {"value_at_delta_market": None, "refused": e.code}


# ------------------------------------------------------------------ the record-neutral reference and V1 (unchanged numbers)
def _neutral(b, bar, r, route, how):
    """(value, how) of the record-neutral reply (menu.NEUTRAL); `how(sc)` describes its scenario. None when it cannot be valued."""
    m = menu.menus(b, bar, r, route)
    nb = menu.neutral_base(route)
    nums = menu.resolve(nb, {}, m)
    if any(v is None for v in nums.values()):
        return None, "record_neutral_unavailable: rate_not_above_terminal_growth"
    sc = menu.scenario(nb, nums, m)
    try:
        return _value(sc, b, bar, r, route)[1]["value_per_share"], how(sc)
    except desk.DeskRefusal as e:
        return None, f"record_neutral_unavailable: {e.code}"


def _neutral_fin(b, bar, r):
    """The record-neutral financial reply: ROE at the record median throughout, book growth and terminal growth at the long-run anchor
    (at most half the median ROE), a ten-year fade."""
    if b.get("g_anchor") is None or not bar["median"] > 0:
        return None, "record_neutral_unavailable: no growth anchor or a median ROE <= 0"
    return _neutral(b, bar, r, "financial", lambda sc: f"roe {bar['median']:.4f}, growth {sc['terminal_g']:.4f}, r {r:.4f}, F {NEUTRAL_FADE}")


def _neutral_op(b, bar, r):
    """The record-neutral operating reply: margins at the record median throughout, revenue and terminal growth at the long-run anchor,
    the no-growth-value RONIC (equity return r) as terminal RONIC, a ten-year fade, the pooled capex."""
    if b.get("g_anchor") is None:
        return None, "record_neutral_unavailable: no growth anchor"
    return _neutral(b, bar, r, "operating", lambda sc: f"margin {bar['median']:.4f}, growth {b['g_anchor']:.4f}, terminal RONIC "
                                                       f"{sc['terminal_ronic']:.4f} (equity return r {r:.4f}), F {NEUTRAL_FADE}")


def _annotate_neutral(res, neutral):
    """Q3c 1-4 (B13): every scenario's value against the record-neutral reply's, annotated outside NEUTRAL_BAND. Never a gate."""
    value, how = neutral
    res.setdefault("diagnostics", {})["record_neutral"] = {"value": value, "inputs": how}
    if value is None:
        res["annotations"].append(how)
        return
    if not value > 0:                                                     # Q3d-1: one annotation; the ratio means nothing
        res["annotations"].append(f"record_neutral_not_positive: {value:.4f} ({how}); the scenarios are not compared")
        return
    for name, v in res["values"].items():
        ratio = v / value if value > 0 else None
        res["diagnostics"].setdefault("value_over_record_neutral", {})[name] = ratio
        if ratio is None or not NEUTRAL_BAND[0] <= ratio <= NEUTRAL_BAND[1]:
            res["annotations"].append(f"value_far_from_record_neutral: {name} {v:.4f} against {value:.4f}"
                                      + (f" ({ratio:.2f}x)" if ratio is not None else " (neutral not positive)"))


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
    if not abs(v["rollforward_factor"] - (1 + r) ** (float(inp["stub_days"]) / 365.0)) <= 1e-12:     # Q3d-3
        raise AssertionError("V1: the roll-forward factor")
    vps = (v["equity_value"] * v["rollforward_factor"] + inp["excess_cash"]) / inp["shares"]
    if not abs(v["value_per_share"] - vps) <= 1e-9 * max(1.0, abs(vps)):     # Q3c-5: per share, not book-scaled
        raise AssertionError("V1: value per share")

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
    if not abs(v["rollforward_factor"] - (1 + inp["r"]) ** (float(inp["stub_days"]) / 365.0)) <= 1e-12:     # Q3d-3
        raise AssertionError("V1: the roll-forward factor")
    if not same(v["value_per_share"], (v["equity_value"] * v["rollforward_factor"] + inp["excess_cash"]) / inp["shares"]):
        raise AssertionError("V1: value per share")

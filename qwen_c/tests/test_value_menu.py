"""F_SPEC_valuation_menu §2, §3, §5 (F3): menu.py. Every option resolves to its number; guidance is read from the E3 sentences (IRWD,
TASK, RNG, MATX) and the signed and range cases; departures by tolerance; the neighbours; a property test of the per-key scenario
rule; and the record-neutral functions pinned to the numbers they returned before the menu existed."""
import copy
import json
import random
from pathlib import Path

import pytest

from qwen_c.value import checks, desk, forecast, forecast_fin, inputs, menu, sentences
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests import test_value_fin as FIN

M = 1e6
FIX = {k: v for k, v in sentences.index(json.loads((Path(__file__).resolve().parent / "fixtures_value" / "sentences_packet.json")
                                                     .read_text(encoding="utf-8"))["evidence"]).items()}


def op(ga=0.03, **over):
    b = dict(inputs.base(OP.facts(), market_cap=180 * M, bill_rate=0.04), stub_days=0, g_anchor=ga, **over)
    bar = forecast.record_bar(b["record"]["op_margin"])
    return b, bar, menu.menus(b, bar, OP.R, "operating")


def fin(ga=0.04, r=FIN.R):
    b = dict(inputs.base_financial(FIN.bank_facts()), stub_days=0, g_anchor=ga)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    return b, bar, menu.menus(b, bar, r, "financial")


# ------------------------------------------------------------------ the record-neutral functions keep their numbers
# menu v6 (2026-11-10): the operating neutral margin is persist = median + 0.5 x (last - median), 0.1578 here (median 0.1556,
# last 0.1600); the numbers below are v6's. The financial route is unchanged.
@pytest.mark.parametrize("ga,lev,value,how", [
    (0.03, False, 14.094998206395346, "margin 0.1578 (persist), growth 0.0300, terminal RONIC 0.0790 (equity return r 0.0900), F 10"),
    (0.03, True, 14.108350914931089, "margin 0.1578 (persist), growth 0.0300, terminal RONIC 0.0730 (equity return r 0.0900), F 10"),
    (0.0375, False, 14.92204931325863, "margin 0.1578 (persist), growth 0.0375, terminal RONIC 0.0790 (equity return r 0.0900), F 10"),
    (0.0375, True, 14.945123860662177, "margin 0.1578 (persist), growth 0.0375, terminal RONIC 0.0730 (equity return r 0.0900), F 10"),
])
def test_neutral_op_returns_the_numbers_it_returned_before_the_menu(ga, lev, value, how):
    b, bar, _ = op(ga)
    if lev:
        b = dict(b, delta=0.4, kd=0.06, tau=0.21)
    assert checks._neutral_op(b, bar, OP.R) == (value, how)


@pytest.mark.parametrize("r,value", [(FIN.R, 13.535632183908033), (0.06, 40.60689655172413)])
def test_neutral_fin_returns_the_numbers_it_returned_before_the_menu(r, value):
    b, bar, _ = fin()
    assert checks._neutral_fin(b, bar, r) == (value, f"roe 0.1034, growth 0.0400, r {r:.4f}, F 10")


# ------------------------------------------------------------------ every option resolves to its number
def test_operating_options_resolve():
    b, bar, m = op()
    g = b["record"]["rev_growth"]
    assert len(g) == 4 and m["growth"] == {"anchor": 0.03, "record_median": pytest.approx((g["2023-12-31"] + g["2024-12-31"]) / 2),
                                           "last": g["2025-12-31"], "zero": 0.0}
    assert m["margin"] == {k: bar[k] for k in menu.anchors("operating")} and m["terminal_g"] == {"anchor": 0.03, "half_anchor": 0.015, "zero": 0.0,
                                                                                    "decline": None}
    n, r0 = menu.neutral_ronic(b, OP.R), b["ronic0"]
    for name, f in (("quarter", 0.25), ("half", 0.5), ("three_quarters", 0.75)):
        assert 1 / m["ronic"][name] == pytest.approx(1 / n + (1 / r0 - 1 / n) * f)        # on desk.ronic_at's scale, 1/RONIC
    assert m["ronic"]["no_growth_value"] == n and m["ronic"]["ronic0"] == r0
    assert desk.equity_ronic(n, b["delta"], b["kd"], b["tau"]) == pytest.approx(OP.R)
    cr = b["record"]["capex_ratio"]
    assert m["capex"] == {"pooled": (b["c_ratio"],) * 5, "record_last": (cr["2025-12-31"],) * 5, "record_max": (max(cr.values()),) * 5}
    base = menu.neutral_base("operating")
    base = menu.set_option(base, "normalized.margin", ("p75", -0.5))
    base = menu.set_option(base, "long_run_op_margin", ("normalized", 1))
    nums = menu.resolve(base, {}, m)
    assert nums["normalized.margin"] == pytest.approx(bar["p75"] - 0.005) and nums["long_run_op_margin"] == pytest.approx(bar["p75"] + 0.005)
    sc = menu.scenario(base, nums, m)
    assert forecast.build_path(sc, bar, b["R0"])[1] == pytest.approx(bar["p75"] - 0.005) and sc["capex_path"] is None


def test_options_not_available():
    b, bar, m = op(ronic0=0.05)                                           # ronic0 below the neutral: only no_growth_value
    assert [k for k, v in m["ronic"].items() if v is not None] == ["no_growth_value"]
    b2 = copy.deepcopy(b)
    b2["record"]["rev_growth"] = {"2024-12-31": -0.10, "2025-12-31": -0.05}                    # fewer than 3 yearly growths
    m2 = menu.menus(b2, bar, OP.R, "operating")
    assert m2["growth"]["record_median"] is None and m2["growth"]["last"] is None and m2["terminal_g"]["decline"] is None
    b2["record"]["rev_growth"]["2023-12-31"] = -0.02
    assert menu.menus(b2, bar, OP.R, "operating")["terminal_g"]["decline"] == pytest.approx(-0.05)      # a negative record median
    assert menu.menus(dict(b, g_anchor=0.095), bar, OP.R, "operating")["terminal_g"]["anchor"] is None    # not below r


def test_financial_options_resolve():
    b, bar, m = fin()
    assert m["growth"]["neutral"] == min(0.04, 0.5 * bar["median"]) and m["terminal_g"]["neutral"] == m["growth"]["neutral"]
    assert list(m["growth"]) == ["neutral", "record_median", "last", "anchor"] and "ronic" not in m and "capex" not in m
    nums = menu.resolve(menu.neutral_base("financial"), {}, m)
    assert nums["long_run_roe"] == bar["median"] and nums["roe.y1"] == bar["median"]


def test_capex_guidance_moves_from_year_one_to_pooled_by_year_five():
    b, bar, m = op()
    path = menu.capex_path(0.09, m)
    assert path[0] == 0.09 and path[-1] == pytest.approx(b["c_ratio"]) and path == tuple(forecast.capex_ratios({"year1": 0.09}, b["c_ratio"]))
    base = menu.set_option(menu.neutral_base("operating"), "capex", "guidance")
    sc = menu.scenario(base, menu.resolve(base, {"capex": 0.09}, m), m)
    assert sc["capex_path"] == {"year1": 0.09}


# ------------------------------------------------------------------ guidance (§2.2) on the E3 sentences
FY0 = "2025-12-31"


def guide(sid, metric, ordinal, sign="as_printed", key="rev_growth.y1", g1=0.03, ids=FIX, m=None):
    m = m or {"R0": 400e6}
    return menu.read_guidance({"evidence": sid, "metric": metric, "sign": sign, "ordinal": ordinal}, key, ids, g1, m, FY0,
                              lambda p: checks.fiscal_year_of(p, OP.ENDS))


def test_irwd_dollar_range_is_read_at_its_midpoint_and_converted_to_growth():
    assert guide("IRWD_P6.s5", "revenue_level", 3) == (pytest.approx(472.5e6 / 400e6 - 1), None)    # $460 - $485 million
    assert guide("IRWD_P6.s5", "revenue_level", 1, m={"R0": 1e9}) == (pytest.approx(1.175 - 1), None)   # $1.15 - $1.20 billion
    x, why = guide("IRWD_P6.s5", "revenue_level", 4)
    assert x is None and "second figure of a range" in why
    assert guide("IRWD_P6.s5", "revenue_level", 3, key="rev_growth.y2", g1=0.1) == (pytest.approx(472.5e6 / 440e6 - 1), None)


def test_task_revenue_range_and_the_stated_limit_on_adjusted_margins():
    assert guide("TASK_P6.s15", "revenue_level", 2, m={"R0": 1.2e9}) == (pytest.approx(1.23e9 / 1.2e9 - 1), None)
    assert guide("TASK_P6.s15", "op_margin", 1, key="op_margin.y1") == (pytest.approx(0.19), None)    # an adjusted EBITDA margin (§2.2)


def test_rng_percent_and_matx_capex_level():
    assert guide("RNG_P7.s3", "revenue_growth", 1) == (pytest.approx(0.06), None)
    x, _ = guide("MATX_P4.s14", "capex_level", 1, key="capex", g1=0.05, m={"R0": 3.4e9})
    assert x == pytest.approx(160e6 / (3.4e9 * 1.05))


@pytest.mark.parametrize("text,metric,sign,ordinal,want", [
    ("Revenue is expected to decline 3% to 5% in 2026.", "revenue_growth", "negative", 1, -0.04),
    ("Revenue is expected to decline 3% to 5% in 2026.", "revenue_growth", "as_printed", 1, 0.04),
    ("In fiscal 2026 revenue grows 4% and 2027 more.", "revenue_growth", "as_printed", 1, 0.04),     # years are not figures
    ("Sales of $1.2 billion rose 7%; margin 12.5%.", "revenue_growth", "as_printed", 2, 0.125),       # percent figures only
    ("Sales of $1.2 billion rose 7%; margin 12.5%.", "revenue_level", "as_printed", 1, 1.2e9 / 400e6 - 1),
])
def test_signed_range_year_and_unit_cases(text, metric, sign, ordinal, want):
    ids = {"P1.s1": {"text": text, "kind": "release", "period": "2026-02-01", "sentence": True}}
    assert guide("P1.s1", metric, ordinal, sign=sign, ids=ids) == (pytest.approx(want), None)


@pytest.mark.parametrize("item,metric,why", [
    ({"text": "Revenue will grow strongly.", "kind": "release", "period": "2026-02-01", "sentence": True}, "revenue_growth", "ordinal 1 of 0"),
    ({"text": "Revenue grew 4%.", "kind": "annual_section", "period": "2024-12-31", "sentence": True}, "revenue_growth", "base fiscal year"),
    ({"text": "Revenue | 4%", "kind": "statement", "period": "2026-03-31", "sentence": False}, "revenue_growth", "not a sentence"),
])
def test_unreadable_guidance_says_why(item, metric, why):
    x, got = guide("P1.s1", metric, 1, ids={"P1.s1": item})
    assert x is None and why in got
    ids = {"P1.s1": {"text": "Revenue of $500 million.", "kind": "release", "period": "2026-02-01", "sentence": True}}
    assert "years 1 and 2 only" in guide("P1.s1", "revenue_level", 1, key="normalized.rev_growth", ids=ids)[1]
    assert "never negative" in guide("P1.s1", "revenue_level", 1, sign="negative", ids=ids)[1]          # F_SPEC v1.2


# ------------------------------------------------------------------ departures and neighbours
def test_departure_tolerance_and_direction():
    b, bar, m = op()
    neutral = menu.resolve(menu.neutral_base("operating"), {}, m)
    nums = dict(neutral, **{"op_margin.y1": neutral["op_margin.y1"] + 0.0009, "op_margin.y2": neutral["op_margin.y2"] - 0.0011,
                            "terminal_ronic": neutral["terminal_ronic"] * 1.0009, "fade_years": 15})
    assert not menu.departed("op_margin.y1", nums, neutral, m) and menu.departed("op_margin.y2", nums, neutral, m)
    assert not menu.departed("terminal_ronic", nums, neutral, m) and menu.departed("fade_years", nums, neutral, m)
    assert menu.direction("op_margin.y2", nums, neutral, m) == "down" and menu.direction("fade_years", nums, neutral, m) == "up"
    assert menu.direction("op_margin.y1", nums, neutral, m) == "none"


def test_neighbours():
    b, bar, m = op()
    base = menu.neutral_base("operating")
    nums = menu.resolve(base, {}, m)
    down, up = menu.neighbours("normalized.margin", base, nums, m, {})                  # step 0: +-1 point, never +-0.5
    assert (down, up) == (pytest.approx(bar["persist"] - 0.01), pytest.approx(bar["persist"] + 0.01))   # v6: the neutral anchor is persist
    b5 = menu.set_option(base, "normalized.margin", ("median", 0.5))
    assert menu.neighbours("normalized.margin", b5, menu.resolve(b5, {}, m), m, {}) == (pytest.approx(bar["median"]),
                                                                                        pytest.approx(bar["median"] + 0.01))
    b3 = menu.set_option(base, "normalized.margin", ("p75", 3))                         # p75 + 3 is the clip: the up side has none
    assert menu.neighbours("normalized.margin", b3, menu.resolve(b3, {}, m), m, {})[1] is None
    g = menu.neighbours("rev_growth.y1", base, nums, m, {})                              # anchor 0.03: zero below, last above
    assert g == (0.0, m["growth"]["last"])
    bz = menu.set_option(base, "rev_growth.y1", "zero")
    assert menu.neighbours("rev_growth.y1", bz, menu.resolve(bz, {}, m), m, {})[0] == pytest.approx(-0.02)    # +-2 points where none
    assert menu.neighbours("terminal_ronic", base, nums, m, {}) == (None, m["ronic"]["quarter"])          # never below no_growth_value
    assert menu.neighbours("terminal_g", base, nums, m, {}) == (0.015, None)
    assert menu.neighbours("fade_years", base, nums, m, {}) == (5, 15)
    assert menu.neighbours("capex", base, nums, m, {}) == (m["capex"]["record_last"], m["capex"]["record_max"])


def test_pick_is_the_argmin_and_argmax_of_down_base_up():
    assert menu.pick(10.0, 8.0, 12.0, "d", "u") == ("d", "u")
    assert menu.pick(10.0, 12.0, 8.0, "d", "u") == ("u", "d")
    assert menu.pick(10.0, 11.0, 12.0, "d", "u") == (None, "u")          # both above Base: Bear is Base
    assert menu.pick(10.0, None, 12.0, "d", "u") == (None, "u")          # a refused neighbour is not a candidate


def test_property_per_key_bear_base_bull_order():
    """§5 on random option sets of the canned company: for every key, Base valued with that key at its Bear setting is not above Base,
    and at its Bull setting not below."""
    b, bar, m = op()
    rnd = random.Random(20261103)

    def value(base, over):
        sc = menu.scenario(base, menu.resolve(base, {}, m, over), m)
        return desk.value_operating(forecast.assemble(sc, b, bar, r=OP.R))["value_per_share"]
    for _ in range(12):
        base = menu.neutral_base("operating")
        for key, kind in menu.KEYS["operating"].items():
            if kind in ("norm", "long"):
                opt = (rnd.choice(menu.ANCHORS + (("normalized",) if kind == "long" else ())), rnd.choice(menu.STEPS))
            else:
                opt = rnd.choice([k for k, v in menu.offered(m, kind).items() if v is not None])
            base = menu.set_option(base, key, opt)
        base["normalized"]["year"] = rnd.choice(menu.YEARS)
        nums = menu.resolve(base, {}, m)
        v0 = value(base, {})
        for key in menu.KEYS["operating"]:
            down, up = menu.neighbours(key, base, nums, m, {})
            vd, vu = (None if x is None else value(base, {key: x}) for x in (down, up))
            lo, hi = menu.pick(v0, vd, vu, down, up)
            vlo = v0 if lo is None else value(base, {key: lo})
            vhi = v0 if hi is None else value(base, {key: hi})
            assert vlo <= v0 <= vhi, (key, base)

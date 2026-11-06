"""Design revision 2, rule (a): qwen_c/value/consensus.py - a departure is valued only when both seeds make it in the same direction."""
import copy

import pytest

from qwen_c.tests import test_value_checks as C
from qwen_c.value import consensus, menu


@pytest.fixture(scope="module")
def ctx():
    return C.ctx_of()


def seed(ctx, reply):
    res = C.run(ctx, copy.deepcopy(reply))
    return {"status": res["status"], "inputs": reply, "checks": res, "values": res["values"]}


def agree(ctx, a, b=None):
    bb, bar, ids = ctx
    results = {"1000": seed(ctx, a)} | ({"3000": seed(ctx, b)} if b is not None else {})
    return consensus.combine(results, ids, bb, bar, C.R, C.ENDS, "operating")


def ronic(out=None):
    return C.depart(out or C.clean(), "terminal_ronic", "half", "competition", ["A1.s2"])


def test_both_seeds_departing_alike_keep_the_departure(ctx):
    res = agree(ctx, ronic(), ronic())
    one = C.run(ctx, ronic())
    assert res["status"] == "ok" and res["options"]["terminal_ronic"] == "half" and res["values"] == one["values"]
    assert not [a for a in res["annotations"] if a.startswith("seeds_disagree")]


def test_a_departure_one_seed_makes_is_neutral_and_annotated(ctx):
    res = agree(ctx, ronic(), C.clean())
    assert res["options"]["terminal_ronic"] == "no_growth_value" and res["values"] == C.run(ctx, C.clean())["values"]
    assert "seeds_disagree: terminal_ronic (1000 up, 3000 none)" in res["annotations"]


def test_opposite_directions_are_neutral(ctx):
    up = C.depart(C.clean(), "long_run_op_margin", ("p75", 0), "pricing", ["A2.s1"])
    down = C.depart(C.clean(), "long_run_op_margin", ("p25", 0), "pricing", [C.Y25])
    res = agree(ctx, up, down)
    assert tuple(res["options"]["long_run_op_margin"]) == ("normalized", 0)
    assert any(a.startswith("seeds_disagree: long_run_op_margin") for a in res["annotations"])


def test_the_seed_nearer_the_neutral_gives_the_option(ctx):
    far = C.depart(C.clean(), "long_run_op_margin", ("median", -0.5), "pricing", [C.Y25])      # 0.1506 against the neutral 0.1556
    near = C.depart(C.clean(), "long_run_op_margin", ("p25", 0), "pricing", [C.Y25])            # 0.1529
    res = agree(ctx, far, near)
    assert tuple(res["options"]["long_run_op_margin"]) == ("p25", 0)
    assert res["departures"] == [{"input": "long_run_op_margin", "driver": "pricing", "evidence": [C.Y25]}]


def test_one_seed_only_is_neutral_everywhere(ctx):
    res = agree(ctx, ronic())
    assert res["options"]["terminal_ronic"] == "no_growth_value" and "one_seed_only: ['1000']" in res["annotations"]


def test_the_years_to_normalized_follow_the_same_rule(ctx):
    a, b = C.clean(), C.clean()
    a["base"]["normalized"]["year"], b["base"]["normalized"]["year"] = 5, 5
    assert agree(ctx, a, b)["year"] == 5
    b["base"]["normalized"]["year"] = 4
    res = agree(ctx, a, b)
    assert res["year"] == menu.NEUTRAL_YEAR and "seeds_disagree: normalized.year (1000 5, 3000 4)" in res["annotations"]


def test_no_checked_seed_is_a_no_call(ctx):
    bb, bar, ids = ctx
    res = consensus.combine({"1000": {"status": "reply_invalid"}}, ids, bb, bar, C.R, C.ENDS, "operating")
    assert res["status"] == "no_call" and res["reason"] == "no_checked_seed"

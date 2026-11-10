"""v13_score: the pick classes and the registered reading, on synthetic rows (no store, no ticker of any real company)."""
import math

import v13_score as V


def r(option, ann=()):
    return {"checks": {"options": {"rev_growth.y1": option}, "annotations": list(ann)}}


def test_pick_classes():
    assert V.pick(r("guidance")) == "read"
    assert V.pick(r("ytd")) == "pace"
    assert V.pick(r("ytd", ["guidance_unreadable: rev_growth.y1 the sentence guides a quarter, not a fiscal year"])) == "unreadable"
    assert V.pick(r("ytd", ["guidance_unreadable: op_margin.y1 x"])) == "pace"
    assert V.pick({"checks": None}) is None and V.pick({}) is None


def test_reading_pass_and_fail():
    rows = {"ZA": {"v12": ("read", 0.10), "v13": ("read", 0.05), "realised": 0.04},
            "ZB": {"v12": ("unreadable", None), "v13": ("read", 0.02), "realised": None},
            "ZC": {"v12": ("pace", -0.01), "v13": ("pace", -0.01), "realised": None},
            "ZD": {"v12": (None, None), "v13": ("unreadable", None), "realised": None}}
    out = V.reading(rows)
    assert out["v12"]["picks"] == 2 and out["v12"]["share"] == 0.5
    assert out["v13"]["picks"] == 3 and math.isclose(out["v13"]["share"], 1 / 3)
    assert out["both_read_with_realised"] == 1
    assert math.isclose(out["v13"]["median_error"], abs(math.log(1.05 / 1.04)))
    assert out["check1"] and out["check2"] and out["verdict"] == "PASS"
    rows["ZA"]["v13"] = ("read", 0.20)
    assert V.reading(rows)["verdict"] == "FAIL"


def test_equal_is_not_above():
    rows = {"ZA": {"v12": ("read", 0.10), "v13": ("read", 0.10), "realised": 0.0}}
    out = V.reading(rows)
    assert out["v12"]["share"] == out["v13"]["share"] == 0.0 and out["verdict"] == "PASS"

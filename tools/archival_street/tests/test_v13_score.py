"""v13_score: the pick classes, the registered reading and the paired reading, on synthetic rows (no store, no ticker of any real
company)."""
import math

import v13_score as V

QUARTER = "guidance_unreadable: rev_growth.y1 the sentence guides a quarter, not a fiscal year"


def r(option, reverts=(), annotations=()):
    return {"checks": {"options": {"rev_growth.y1": option}, "reverts": list(reverts), "annotations": list(annotations)}}


def test_pick_classes():
    assert V.pick(r("guidance")) == "read"
    assert V.pick(r("ytd")) == "pace"
    assert V.pick(r("ytd", [QUARTER])) == "unreadable"
    assert V.pick(r("ytd", ["guidance_unreadable: op_margin.y1 x"])) == "pace"
    assert V.pick({"checks": None}) is None and V.pick({}) is None


def test_unreadable_is_read_from_reverts_as_checks_writes_it():
    """checks.py: res["reverts"] = [f"guidance_unreadable: {k} {why}" ...]; the annotations never carry it."""
    assert V.unreadable_why(r("ytd", [QUARTER])) == "the sentence guides a quarter, not a fiscal year"
    assert V.unreadable_why(r("ytd", annotations=[QUARTER])) is None and V.pick(r("ytd", annotations=[QUARTER])) == "pace"
    assert V.unreadable_why(r("ytd", [QUARTER])).startswith(V.PERIOD_WHY)


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


def test_sign_p():
    assert V.sign_p(5, 5) == 1 / 32 and V.sign_p(4, 5) == 6 / 32 and V.sign_p(0, 3) == 1.0 and V.sign_p(0, 0) is None


def pairs(n_b, n_c, n_worse=0, n_better=0):
    rows = {}
    for i in range(n_b):
        rows[f"ZB{i}"] = {"v12": ("read", 0.1), "v13": ("unreadable", None), "realised": None}
    for i in range(n_c):
        rows[f"ZC{i}"] = {"v12": ("unreadable", None), "v13": ("read", 0.1), "realised": None}
    for i in range(n_worse):
        rows[f"ZW{i}"] = {"v12": ("read", 0.05), "v13": ("read", 0.20), "realised": 0.05}
    for i in range(n_better):
        rows[f"ZG{i}"] = {"v12": ("read", 0.20), "v13": ("read", 0.05), "realised": 0.05}
    return rows


def test_paired_fails_only_where_v13_is_clearly_worse():
    assert V.paired(pairs(4, 1))["verdict"] == "PASS"                     # p = 6/32
    out = V.paired(pairs(5, 0))
    assert out["fail1"] and out["verdict"] == "FAIL" and out["p1"] == 1 / 32
    assert V.paired(pairs(0, 5))["verdict"] == "PASS"
    assert V.paired(pairs(0, 0))["verdict"] == "PASS"                     # nothing discordant
    out = V.paired(pairs(0, 0, n_worse=6, n_better=1))
    assert out["fail2"] and out["verdict"] == "FAIL" and (out["worse"], out["better"]) == (6, 1)
    assert V.paired(pairs(0, 0, n_worse=3, n_better=2))["verdict"] == "PASS"


def test_paired_takes_a_ruled_period_catch_out_of_b_and_drops_ties():
    rows = pairs(5, 0)
    assert V.paired(rows, {"ZB0", "ZB1"})["verdict"] == "PASS"            # 3 of 3: p = 1/8
    rows["ZT"] = {"v12": ("read", 0.10), "v13": ("read", 0.10), "realised": 0.0}
    rows["ZP"] = {"v12": ("pace", 0.0), "v13": ("read", 0.3), "realised": None}
    out = V.paired(rows)
    assert out["ties"] == 1 and out["pairs"] == 6 and out["pick_under_one_prompt_only"] == {"v12": [], "v13": ["ZP"]}

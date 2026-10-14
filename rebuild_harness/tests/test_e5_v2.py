"""E5, engine v2's oracle (SPEC_rebuild Addendum AL.24): parity of the point value with the engine's own, the one information set (k <= 3, the year-5
margin rule) for both engines, and refusals."""
import math
from types import SimpleNamespace

from rebuild_harness.forensics import e5_v2 as E5
from valuation import engine_financial_v2 as f2, engine_operating_v2 as o2
from valuation.muse.tests import fixtures as fx
from valuation.tests.test_engine_v2 import setup, table

SHARES = 1.0e8


def chain_out(n=5, g=0.07, m=0.16, rote=0.12, rev0=1.0e9, tbv0=5.0e8, override=None):
    years, rev, tbv = [], rev0, tbv0
    for k in range(1, n + 1):
        gk = (override or {}).get(("g", k), g)
        rev, tbv = rev * (1 + gk), tbv * 1.05
        years.append({"k": k, "fye": f"{2020 + k}-12-31", "filed": f"{2021 + k}-02-15", "revenue": rev, "operating_margin": (override or {}).get(("m", k), m),
                      "rote": (override or {}).get(("r", k), rote), "tbv": tbv, "net_income": 1.0})
    return {"base": {"fye": "2020-12-31", "revenue": rev0, "tbv": tbv0, "operating_margin": m}, "years": years}


def cap(family, sic):
    pit, st, ps, disc = setup(family, sic)
    return SimpleNamespace(family=family, st=st, ps=ps, disc=disc), pit


def test_v2s_point_value_without_override_is_the_engines_own_at_median_value():
    for family, sic, mod in (("operating", "3674", o2), ("financial", "6021", f2)):
        c, pit = cap(family, sic)
        t = table()
        r = mod.run(pit, fx.LabeledPlaceholderPriors(), c.disc, t, n_draws=50, seed=1, state=c.st)
        p = E5.v2_point(family, c.st, c.ps, c.disc, t, SHARES)
        assert p["reason"] is None
        assert math.isclose(p["ps"], r["at_median_inputs"]["equity"] / SHARES, rel_tol=1e-12)


def test_both_engines_see_only_years_1_to_3_and_a_later_year_moves_neither():
    c, _ = cap("operating", "3674")
    a = E5.values(c, {"fx_out": chain_out(n=5)}, SHARES, table())
    b = E5.values(c, {"fx_out": chain_out(n=5, override={("g", 4): 0.50})}, SHARES, table())           # year 4 differs: outside the information set
    d = E5.values(c, {"fx_out": chain_out(n=5, override={("g", 2): 0.30})}, SHARES, table())           # year 2 differs: inside it
    assert a["v2"] is not None and a["v1_same"] is not None
    assert a["v2"] == b["v2"] and a["v1_same"] == b["v1_same"]
    assert d["v2"] != a["v2"] and d["v1_same"] != a["v1_same"]


def test_the_long_run_margin_is_the_realised_year_5_margin_only_when_year_5_is_realised():
    c, _ = cap("operating", "3674")
    k4 = E5.values(c, {"fx_out": chain_out(n=4)}, SHARES, table())
    k5 = E5.values(c, {"fx_out": chain_out(n=5, override={("m", 5): 0.40})}, SHARES, table())
    k5b = E5.values(c, {"fx_out": chain_out(n=5, override={("m", 5): 0.10})}, SHARES, table())
    assert k5["v2"] > k5b["v2"] and k5["v1_same"] > k5b["v1_same"]                                    # the realised m5 is the long-run margin
    assert E5.realised({"fx_out": chain_out(n=4)}, "operating")["m5"] is None and k4["v2"] is not None


def test_the_financial_oracle_sets_rote_of_years_1_to_3_and_keeps_tangible_book_growth():
    c, _ = cap("financial", "6021")
    lo = E5.values(c, {"fx_out": chain_out(n=3, rote=0.05)}, SHARES, table())
    hi = E5.values(c, {"fx_out": chain_out(n=3, rote=0.20)}, SHARES, table())
    assert hi["v2"] > lo["v2"] and hi["v1_same"] > lo["v1_same"]


def test_refusals_are_recorded_never_filled():
    c, _ = cap("operating", "3674")
    none = E5.values(c, {"fx_out": None}, SHARES, table())
    assert none["v2"] is None and none["v1_same"] is None and "no realised year 1" in none["v2_reason"]
    small = E5.values(c, {"fx_out": chain_out(n=3)}, SHARES, table(n=10))                                # pools under MIN_N: v2 refuses, named
    assert small["v2"] is None and small["v2_p50"] is None and small["v2_reason"]
    out = E5.values(c, {"fx_out": chain_out(n=3)}, SHARES, None)
    assert out["v2_reason"] == "no near-term table for the vintage" and "v2" not in out
    crash = E5.values(c, {"fx_out": chain_out(n=3, override={("g", 1): -1.5})}, SHARES, table())         # a realised fall below -100% is not an input
    assert crash["v2"] is None
    assert E5.values(SimpleNamespace(family="commodity", st={}, ps=None, disc=None), {}, SHARES, table())["skipped"]


def test_ak51_item3_the_matched_financial_oracle_uses_realised_tbv_growth_and_rote_in_both_engines():
    c, _ = cap("financial", "6021")
    base = chain_out(n=3, rote=0.12)
    lo, hi = dict(base), dict(base)
    lo["years"] = [dict(y, tbv=y["tbv"]) for y in base["years"]]
    hi["years"] = [dict(y, tbv=y["tbv"] * (1.30 ** y["k"])) for y in base["years"]]                 # same ROTE, faster realised tangible-book growth
    a, b = E5.values(c, {"fx_out": lo}, SHARES, table()), E5.values(c, {"fx_out": hi}, SHARES, table())
    assert b["v2"] != a["v2"] and b["v1_same"] != a["v1_same"]                                          # the matched reading sees tbv growth
    assert b["v2_rote_only"] == a["v2_rote_only"] and b["v1_same_rote_only"] == a["v1_same_rote_only"]  # the labelled ROTE-only sensitivity does not


def test_v21_the_oracle_and_the_distribution_read_the_measured_continuation_only_when_given_the_tables():
    import dataclasses
    for family, sic in (("operating", "3674"), ("financial", "6021")):
        pit, st, ps, disc = setup(family, sic)
        ps = dataclasses.replace(ps, meta={"vintage": 2024, "features": {"g3": 0.07, "tg3": 0.07}})
        zero = SimpleNamespace(tables=lambda v: {"edges": {"growth": [-0.10, 0.0, 0.05, 0.10, 0.20, 0.40]},
                                                 "continuation": {family: {"buckets": [{"bucket": [0, 6], "lambda": [0.0] * 7}]}}})
        c = SimpleNamespace(family=family, st=st, ps=ps, disc=disc, pit=pit)
        k = E5.v2_point(family, st, ps, disc, table(), SHARES)
        m = E5.v2_point(family, st, ps, disc, table(), SHARES, priors=zero)
        assert k["reason"] is None and m["reason"] is None and k["ps"] != m["ps"]
        dk = E5.v2_distribution(c, table(), SHARES, n_draws=50)
        dm = E5.v2_distribution(c, table(), SHARES, n_draws=50, priors=zero)
        assert dk["continuation"].startswith("K:") and "continuation (measured" in dm["continuation"] and dm["engine_version"] == "v2.1"

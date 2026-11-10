"""F_SPEC_valuation_menu v1.3 (F11): year 1's `ytd` option. facts.ytd reads the year-to-date pair of the latest 10-Q effective at T from
synthetic companyfacts (Q1, H1 and nine-month durations, a 10-Q effective after T, a 20-F filer, a missing comparable, 52/53-week years);
menu, checks, the record-neutral diagnostics, the [V0] MENU and the memo use the same neutral numbers."""
import copy
from datetime import datetime, timezone

import pytest

from qwen_c.value import checks, facts, forecast, inputs, memo, menu, task
from qwen_c.tests import test_value_checks as OP

T = datetime(2025, 11, 4, 13, 0, tzinfo=timezone.utc)      # before the open of 2025-11-04: a 10-Q accepted on 11-03 is effective after T
K24, Q1, Q2, Q3 = "0009-25-000001", "0009-25-000002", "0009-25-000003", "0009-25-000004"
FILINGS = {K24: ("10-K", "2025-02-20", "2025-02-20T15:00:00.000Z"), Q1: ("10-Q", "2025-05-05", "2025-05-05T15:00:00.000Z"),
           Q2: ("10-Q", "2025-08-05", "2025-08-05T15:00:00.000Z"), Q3: ("10-Q", "2025-10-30", "2025-10-30T15:00:00.000Z")}


def subs(filings=FILINGS):
    rows = [(a, *v) for a, v in filings.items()]
    cols = list(zip(*rows))
    return {"filings": {"recent": {"accessionNumber": list(cols[0]), "form": list(cols[1]), "filingDate": list(cols[2]),
                                   "acceptanceDateTime": list(cols[3])}}}


def fact(start, end, val, accn, filings=FILINGS):
    form, filed, _ = filings[accn]
    return {"start": start, "end": end, "val": val, "accn": accn, "form": form, "filed": filed, "fp": "FY" if form in ("10-K", "20-F") else "Q"}


def quarters(rev=True):
    """Revenue (or operating income at a tenth) of three 10-Qs of 2025, each with its 2024 comparative and its own three-month periods."""
    k = 1.0 if rev else 0.1
    return [fact("2025-01-01", "2025-03-31", 110 * k, Q1), fact("2024-01-01", "2024-03-31", 100 * k, Q1),
            fact("2025-01-01", "2025-06-30", 230 * k, Q2), fact("2024-01-01", "2024-06-30", 200 * k, Q2),
            fact("2025-04-01", "2025-06-30", 120 * k, Q2), fact("2024-04-01", "2024-06-30", 100 * k, Q2),
            fact("2025-01-01", "2025-09-30", 360 * k, Q3), fact("2024-01-01", "2024-09-30", 300 * k, Q3),
            fact("2025-07-01", "2025-09-30", 130 * k, Q3), fact("2024-07-01", "2024-09-30", 100 * k, Q3)]


def annual():
    return [fact("2023-01-01", "2023-12-31", 380.0, K24), fact("2024-01-01", "2024-12-31", 400.0, K24)]


def cf(rev_rows, oi_rows=None, tag="Revenues"):
    g = {tag: {"units": {"USD": rev_rows}}}
    if oi_rows is not None:
        g["OperatingIncomeLoss"] = {"units": {"USD": oi_rows}}
    return {"facts": {"us-gaap": g}}


def ytd_of(c, s=None, at=T):
    return facts.annual_facts(c, s or subs(), at)["_ytd"]


# ------------------------------------------------------------------ facts.ytd
def test_the_latest_10q_effective_at_T_gives_the_pair_and_a_later_one_is_not_used():
    y = ytd_of(cf(annual() + quarters(), quarters(rev=False)))
    # Q3 was accepted 2025-10-30: effective 10-31, before T. The nine-month pair, both legs from that one filing
    assert (y["quarter"], y["start"], y["end"], y["accn"], y["prior_start"], y["prior_end"]) == (3, "2025-01-01", "2025-09-30", Q3,
                                                                                               "2024-01-01", "2024-09-30")
    assert y["rev_growth"] == 360 / 300 - 1 and y["op_margin"] == 36.0 / 360 and y["absent"] is None and y["fy0"] == "2024-12-31"
    late = dict(FILINGS, **{Q3: ("10-Q", "2025-11-03", "2025-11-03T21:00:00.000Z")})     # accepted 16:00 ET 11-03: effective 11-04 open, after T
    y2 = ytd_of(cf(annual() + quarters(), quarters(rev=False)), subs(late))
    assert (y2["quarter"], y2["accn"], y2["rev_growth"]) == (2, Q2, 230 / 200 - 1)


@pytest.mark.parametrize("at,quarter,growth", [(datetime(2025, 6, 1, tzinfo=timezone.utc), 1, 0.1),
                                                (datetime(2025, 9, 1, tzinfo=timezone.utc), 2, 0.15),
                                                (datetime(2025, 12, 1, tzinfo=timezone.utc), 3, 0.2)])
def test_q1_h1_and_nine_months(at, quarter, growth):
    y = ytd_of(cf(annual() + quarters()), at=at)
    assert y["quarter"] == quarter and y["rev_growth"] == pytest.approx(growth, abs=1e-12)
    assert y["op_margin"] is None and y["op_margin_absent"].startswith("no year-to-date operating income")


def test_before_any_10q_of_year_1_and_a_20f_filer_are_not_available():
    y = ytd_of(cf(annual() + quarters()), at=datetime(2025, 3, 1, tzinfo=timezone.utc))
    assert y["rev_growth"] is None and y["absent"] == "no 10-Q of year 1 effective at T"
    f20 = {K24: ("20-F", "2025-04-20", "2025-04-20T15:00:00.000Z")}
    rows = [fact("2023-01-01", "2023-12-31", 380.0, K24, f20), fact("2024-01-01", "2024-12-31", 400.0, K24, f20)]
    y = ytd_of(cf(rows), subs(f20))
    assert y["rev_growth"] is None and y["absent"] == "no 10-Q of year 1 effective at T"


def test_a_missing_comparable_in_the_latest_filing_is_not_available_never_an_earlier_filing():
    rows = [r for r in annual() + quarters() if not (r["accn"] == Q3 and r["start"] == "2024-01-01")]
    y = ytd_of(cf(rows))
    assert y["rev_growth"] is None and y["accn"] == Q3 and y["absent"].startswith("no prior-year comparable of the 272-day")


def test_a_comparable_under_another_tag_is_not_like_for_like():
    rows = [r for r in annual() + quarters() if not (r["accn"] == Q3 and r["start"] == "2024-01-01")]
    other = [fact("2024-01-01", "2024-09-30", 300.0, Q3)]
    c = cf(rows)
    c["facts"]["us-gaap"]["SalesRevenueNet"] = {"units": {"USD": other}}
    assert ytd_of(c)["rev_growth"] is None


def test_the_largest_revenue_tag_with_both_legs_wins_and_is_stamped():
    c = cf(annual() + quarters())
    c["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [
        fact("2025-01-01", "2025-09-30", 340.0, Q3), fact("2024-01-01", "2024-09-30", 290.0, Q3)]}}
    y = ytd_of(c)
    assert y["revenue_tag"] == "Revenues" and y["rev_growth"] == 360 / 300 - 1 and "ytd_revenue_largest_of_tags" in y["stamp"]


def test_revenue_not_positive_is_named_and_zero_is_kept_as_a_value():
    rows = [r if not (r["accn"] == Q3 and r["start"] == "2024-01-01" and r["end"] == "2024-09-30") else dict(r, val=0.0)
            for r in annual() + quarters()]
    y = ytd_of(cf(rows))
    assert y["rev_growth"] is None and y["absent"].startswith("year-to-date revenue not positive")


def test_53_week_years_by_start_dates():
    # 52/53-week calendar: the base year 2023-12-31 .. 2025-01-04 is 371 days (a 53-week year); year 1 starts 2025-01-05
    k = {K24: ("10-K", "2025-02-20", "2025-02-20T15:00:00.000Z"), Q1: ("10-Q", "2025-05-05", "2025-05-05T15:00:00.000Z")}
    rows = [fact("2023-01-01", "2023-12-30", 380.0, K24, k), fact("2023-12-31", "2025-01-04", 400.0, K24, k),
            fact("2025-01-05", "2025-04-05", 110.0, Q1, k), fact("2023-12-31", "2024-03-30", 100.0, Q1, k)]
    y = ytd_of(cf(rows), subs(k), at=datetime(2025, 6, 1, tzinfo=timezone.utc))
    assert (y["quarter"], y["start"], y["prior_start"], y["rev_growth"]) == (1, "2025-01-05", "2023-12-31", pytest.approx(0.1)) and y["stamp"] is None
    # the extra week fell in the base year's first quarter: 97 against 90 days, kept like for like as filed, stamped
    rows[-1] = fact("2023-12-31", "2024-04-06", 107.0, Q1, k)
    y = ytd_of(cf(rows), subs(k), at=datetime(2025, 6, 1, tzinfo=timezone.utc))
    assert y["rev_growth"] == pytest.approx(110 / 107 - 1) and y["stamp"] == "ytd_lengths_differ: 90 against 97 days"
    # a quarter starting on any other day is not year 1's
    rows[-2] = fact("2025-01-01", "2025-04-05", 110.0, Q1, k)
    assert ytd_of(cf(rows), subs(k), at=datetime(2025, 6, 1, tzinfo=timezone.utc))["absent"] == "no 10-Q of year 1 effective at T"


def test_inputs_carries_the_pair_only_against_its_own_base_year():
    f = OP.facts()
    assert inputs.base(f, market_cap=180e6, bill_rate=0.04)["ytd"]["absent"] == "no year-to-date record in the facts"
    f["_ytd"] = {"rev_growth": 0.1, "op_margin": 0.2, "fy0": "2024-12-31", "absent": None}
    y = inputs.base(f, market_cap=180e6, bill_rate=0.04)["ytd"]
    assert y["rev_growth"] is None and y["op_margin"] is None and "the base year is 2025-12-31" in y["absent"]


# ------------------------------------------------------------------ menu, checks, neutral, prompt, memo
YTD = {"rev_growth": 0.12, "op_margin": 0.18, "absent": None, "op_margin_absent": None, "fy0": "2025-12-31", "quarter": 3,
       "start": "2026-01-01", "end": "2026-09-30", "prior_start": "2025-01-01", "prior_end": "2025-09-30", "accn": "0009-26-000004",
       "form": "10-Q", "filed": "2026-10-30", "revenue": 84e6, "revenue_prior": 75e6, "operating_income": 15.12e6, "stamp": None}


def ctx_ytd(y=YTD):
    b, bar, ids = OP.ctx_of()
    return dict(b, ytd=y), bar, ids


def neutral_reply(b, bar):
    m = menu.menus(b, bar, OP.R, "operating")
    return {"task": "valuation_inputs", "base": menu.neutral_base("operating", m), "guidance": {}, "departures": [],
            "uncertain": ["rev_growth.y1"], "unknowns": []}


def test_ytd_leads_year_1_and_is_its_neutral_while_year_2_stays():
    b, bar, _ = ctx_ytd()
    m = menu.menus(b, bar, OP.R, "operating")
    assert list(m["growth_y1"])[0] == "ytd" and m["growth_y1"]["ytd"] == 0.12 and list(m["margin_y1"])[0] == "ytd"
    assert "ytd" not in m["growth"] and "ytd" not in m["margin"]
    nb = menu.neutral_base("operating", m)
    assert menu.option(nb, "rev_growth.y1") == "ytd" and menu.option(nb, "op_margin.y1") == "ytd"
    assert menu.option(nb, "rev_growth.y2") == "anchor" and menu.option(nb, "op_margin.y2") == "persist"   # menu v6
    assert menu.option(nb, "normalized.rev_growth") == "anchor"
    nums = menu.resolve(nb, {}, m)
    assert nums["rev_growth.y1"] == 0.12 and nums["op_margin.y1"] == 0.18 and nums["rev_growth.y2"] == 0.03


@pytest.mark.parametrize("y,growth,margin", [(None, "anchor", "persist"),   # menu v6: the operating neutral margin anchor is persist
                                             (dict(YTD, rev_growth=None, op_margin=None, absent="no 10-Q of year 1 effective at T"), "anchor", "persist"),
                                             (dict(YTD, op_margin=-1.4), "ytd", "persist"),          # a margin outside (-1, 1): not offered
                                             (dict(YTD, op_margin=None, op_margin_absent="none"), "ytd", "persist")])
def test_not_available_keeps_todays_neutral_and_ytd_trails_the_line(y, growth, margin):
    b, bar, ids = ctx_ytd(y)
    m = menu.menus(b, bar, OP.R, "operating")
    nb = menu.neutral_base("operating", m)
    assert (menu.option(nb, "rev_growth.y1"), menu.option(nb, "op_margin.y1")) == (growth, margin)
    for key, d in (("growth_y1", growth), ("margin_y1", margin)):
        assert list(m[key])[0] == ("ytd" if d == "ytd" else d)
        if d != "ytd":
            assert list(m[key])[-1] == "ytd" and m[key]["ytd"] is None
    if growth == "anchor":                                                # choosing it is a reply error, never a no-call
        r = neutral_reply(b, bar)
        r["base"] = menu.set_option(r["base"], "rev_growth.y1", "ytd")
        res = checks.check(r, ids, b, bar, OP.R, OP.ENDS)
        assert res["status"] == "reply_invalid" and res["errors"]["rev_growth.y1"] == ["ytd is not available"]


def test_the_neutral_reply_is_ok_and_the_record_neutral_diagnostic_uses_the_same_numbers():
    b, bar, ids = ctx_ytd()
    res = checks.check(neutral_reply(b, bar), ids, b, bar, OP.R, OP.ENDS)
    assert res["status"] == "ok" and res["departures"] == [] and res["neutral"]["rev_growth.y1"] == 0.12
    assert res["neutral"]["op_margin.y1"] == 0.18 and res["directions"]["rev_growth.y1"] == "none"
    # v1.3 audit: a ytd neutral outside the record is annotated, never gated (the record's max growth 6.25%, margin max 0.1600)
    assert {"ytd_outside_record: rev_growth.y1 0.1200", "ytd_outside_record: op_margin.y1 0.1800"} <= set(res["annotations"])
    rn = res["diagnostics"]["record_neutral"]
    assert rn["value"] == res["values"]["base"] and res["diagnostics"]["value_over_record_neutral"]["base"] == 1.0
    assert rn["inputs"].startswith("year 1 growth 0.1200 and margin 0.1800, margin ")
    assert checks._neutral_op(b, bar, OP.R)[0] == res["values"]["base"]
    # and without a ytd pair, both stay exactly where they were (test_value_menu pins those numbers)
    b0, bar0, _ = OP.ctx_of()
    assert checks._neutral_op(b0, bar0, OP.R)[0] != rn["value"]


def test_the_anchor_on_year_1_is_now_a_departure_and_a_failed_departure_reverts_to_ytd():
    b, bar, ids = ctx_ytd()
    r = neutral_reply(b, bar)
    r["base"] = menu.set_option(r["base"], "rev_growth.y1", "anchor")
    res = checks.check(copy.deepcopy(r), ids, b, bar, OP.R, OP.ENDS)
    assert res["status"] == "reply_invalid" and "needs a departures entry" in res["errors"]["rev_growth.y1"][0]
    r = neutral_reply(b, bar)
    r["base"] = menu.set_option(r["base"], "op_margin.y1", "p75")
    r["departures"] = [{"input": "op_margin.y1", "driver": "pricing", "evidence": ["G1.s1"]}]   # a release only: V4 fails
    res = checks.check(r, ids, b, bar, OP.R, OP.ENDS)
    assert res["status"] == "ok_with_reverts" and res["reverts"] == ["departure_reverted: op_margin.y1 V4"], res.get("errors")
    assert res["options"]["op_margin.y1"] == "ytd" and res["numbers"]["op_margin.y1"] == 0.18


def test_ytd_is_another_offered_point_for_the_year_1_neighbours():
    b, bar, _ = ctx_ytd(dict(YTD, rev_growth=0.035))
    m = menu.menus(b, bar, OP.R, "operating")
    base = menu.set_option(menu.neutral_base("operating", m), "rev_growth.y1", "anchor")
    nums = menu.resolve(base, {}, m)
    down, up = menu.neighbours("rev_growth.y1", base, nums, m, {})
    assert up == 0.035 and down == max(v for v in m["growth"].values() if v is not None and v < 0.03 - menu.TOL)
    base2 = menu.set_option(menu.neutral_base("operating", m), "rev_growth.y2", "anchor")
    assert menu.neighbours("rev_growth.y2", base2, menu.resolve(base2, {}, m), m, {})[1] != 0.035


def test_the_menu_and_the_base_print_ytd_and_its_period():
    b, bar, _ = ctx_ytd()
    prov = dict(OP.PROV)
    text = task.render_base(b, bar, OP.R, prov)
    assert "\nrev_growth.y1: ytd 0.1200; anchor 0.0300; " in text and "\nrev_growth.y2, normalized.rev_growth: anchor 0.0300; " in text
    assert "\nop_margin.y1: ytd 0.1800; persist " in text and "\nop_margin.y2: persist " in text   # menu v6
    assert ("Year 1 to date (10-Q 0009-26-000004, filed 2026-10-30): revenue 84,000,000 from 2026-01-01 to 2026-09-30 against "
            "75,000,000 from 2025-01-01 to 2025-09-30, growth 0.1200; operating income 15,120,000, margin 0.1800.") in text
    b2 = dict(b, ytd=dict(YTD, rev_growth=None, absent="no 10-Q of year 1 effective at T"))
    t2 = task.render_base(b2, bar, OP.R, prov)
    assert "Year 1 to date: not available (no 10-Q of year 1 effective at T)." in t2 and "; ytd not available; guidance" in t2


def test_the_memo_prints_the_ytd_period():
    b, bar, ids = ctx_ytd()
    res = checks.check(neutral_reply(b, bar), ids, b, bar, OP.R, OP.ENDS)
    result = {"ticker": "T", "T": "2026-11-01T00:00:00Z", "status": "ok", "base": b, "cost_of_equity": OP.R, "stamps": [],
              "checks": {k: v for k, v in res.items() if k != "results"}, "values": res["values"], "inputs": neutral_reply(b, bar)}
    text = memo.render(result)
    assert ("- **rev_growth.y1**: ytd, 0.1200 (record-neutral 0.1200), none; year to date 2026-01-01 to 2026-09-30 against 2025-01-01 "
            "to 2025-09-30, 10-Q 0009-26-000004 filed 2026-10-30") in text


# ------------------------------------------------------------------ menu v4 / checks v15 (J2 revision 1): year 1 partly reported
def ctx_rest():
    b, bar, ids = ctx_ytd(dict(YTD, year1_start="2026-01-01"))
    return b, bar, ids, menu.menus(b, bar, OP.R, "operating")


def test_year_1_options_keep_the_reported_quarters_and_set_only_the_rest():
    b, bar, _, m = ctx_rest()
    r0, rest_prior = b["R0"], b["R0"] - 75e6
    assert m["growth_y1"]["ytd"] == 0.12                                          # the neutral is unchanged
    assert m["growth_y1"]["zero"] == pytest.approx((84e6 + rest_prior) / r0 - 1)   # zero growth on the rest of the year only
    a = m["growth"]["anchor"]
    assert m["growth_y1"]["anchor"] == pytest.approx((84e6 + rest_prior * (1 + a)) / r0 - 1) and m["growth"]["anchor"] == a
    q4 = rest_prior * 1.12
    p75 = m["margin"]["p75"]
    assert m["margin_y1"]["p75"] == pytest.approx((15.12e6 + q4 * p75) / (84e6 + q4)) and m["margin_y1"]["ytd"] == 0.18
    assert m["ytd_floor"] == pytest.approx(84e6 / r0 - 1)
    assert "\nrev_growth.y1: ytd 0.1200; anchor " + f"{m['growth_y1']['anchor']:.4f}" in task.render_base(b, bar, OP.R, dict(OP.PROV))


@pytest.mark.parametrize("y", [YTD, dict(YTD, year1_start="2026-01-01", quarter=4), dict(YTD, year1_start="2025-12-28")])
def test_without_a_year_1_pair_that_leaves_part_of_the_year_the_menu_is_as_before(y):
    b, bar, _ = ctx_ytd(y)
    m = menu.menus(b, bar, OP.R, "operating")
    assert m["growth_y1"]["anchor"] == m["growth"]["anchor"] and "ytd_floor" not in m


def test_a_year_1_revenue_below_what_the_year_has_reported_reverts():
    b, bar, ids, m = ctx_rest()
    r = neutral_reply(b, bar)
    r["base"] = menu.set_option(r["base"], "rev_growth.y1", "guidance")
    r["guidance"] = {"rev_growth.y1": {"evidence": "P1.s1", "metric": "revenue_growth", "sign": "negative", "ordinal": 1}}
    r["departures"] = [{"input": "rev_growth.y1", "driver": "guidance", "evidence": ["P1.s1"]}]
    ids = dict(ids, **{"P1.s1": {"kind": "release", "period": "2026-10-30", "sentence": True,
                                 "text": "The company now expects full-year revenue to decline 60%."}})
    res = checks.check(r, ids, b, bar, OP.R, OP.ENDS)
    assert res["status"] == "ok_with_reverts" and res["reverts"] == ["departure_reverted: rev_growth.y1 below_ytd_reported"], res.get("errors")
    assert res["numbers"]["rev_growth.y1"] == 0.12


def _level_reply(text):
    b, bar, ids, m = ctx_rest()
    r = neutral_reply(b, bar)
    r["base"] = menu.set_option(r["base"], "rev_growth.y1", "guidance")
    r["guidance"] = {"rev_growth.y1": {"evidence": "P1.s1", "metric": "revenue_level", "sign": "as_printed", "ordinal": 1}}
    r["departures"] = [{"input": "rev_growth.y1", "driver": "guidance", "evidence": ["P1.s1"]}]
    ids = dict(ids, **{"P1.s1": {"kind": "release", "period": "2026-10-30", "sentence": True, "text": text}})
    return checks.check(r, ids, b, bar, OP.R, OP.ENDS)


def test_a_revenue_level_that_reads_as_one_quarter_is_unreadable_and_valued_at_neutral():
    res = _level_reply("Revenue | $30 million plus or minus $1 million")         # design revision 2: a next-quarter guide
    assert res["status"] == "ok_with_reverts" and res["numbers"]["rev_growth.y1"] == 0.12
    assert res["reverts"][0].startswith("guidance_unreadable: rev_growth.y1 a revenue level of 30,000,000 leaves")
    assert "it is not the year's revenue (one quarter's guidance" in res["reverts"][0]


def test_a_table_figure_in_unstated_millions_is_unreadable():
    res = _level_reply("Revenue | $ 112 | $ 100")                                     # "in millions" only in the table header
    assert res["status"] == "ok_with_reverts" and "a revenue level of 112 leaves" in res["reverts"][0]


def test_a_full_year_revenue_level_still_reads():
    res = _level_reply("The company now expects full-year revenue of $115 million.")
    assert not res["reverts"] and res["guided"]["rev_growth.y1"] == pytest.approx(0.15)


# ------------------------------------------------------------------ checks v16 / memo v7: PREREG amendment 2's safe default
def test_a_departed_year_1_key_is_annotated_and_valued_at_the_record_neutral():
    b, bar, ids, m = ctx_rest()
    r = neutral_reply(b, bar)
    r["base"] = menu.set_option(r["base"], "rev_growth.y1", "guidance")
    r["guidance"] = {"rev_growth.y1": {"evidence": "P1.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}}
    r["departures"] = [{"input": "rev_growth.y1", "driver": "guidance", "evidence": ["P1.s1"]}]
    ids = dict(ids, **{"P1.s1": {"kind": "release", "period": "2026-10-30", "sentence": True,
                                 "text": "The company now expects full-year revenue to grow 15%."}})
    res = checks.check(r, ids, b, bar, OP.R, OP.ENDS)
    neu = checks.check(neutral_reply(b, bar), ids, b, bar, OP.R, OP.ENDS)
    assert res["status"] == "ok" and res["options"]["rev_growth.y1"] == "guidance", res.get("errors") or res.get("reverts")
    assert res["numbers"]["rev_growth.y1"] == pytest.approx(0.15)                  # the reply's number is kept for the record
    assert res["of_record"] == {"rev_growth.y1": {"model_option": "guidance", "model": res["numbers"]["rev_growth.y1"],
                                                  "record_option": "ytd", "record": 0.12}}
    assert "held_at_record: rev_growth.y1 model 0.1500 valued at 0.1200" in res["annotations"]
    assert res["values"]["base"] == neu["values"]["base"] and neu["of_record"] == {}
    result = {"ticker": "T", "T": "2026-11-01T00:00:00Z", "status": "ok", "base": b, "cost_of_equity": OP.R, "stamps": [],
              "checks": {k: v for k, v in res.items() if k != "results"}, "values": res["values"], "inputs": r}
    assert "; not valued: held at the record-neutral 0.1200 until a holdout PASSes" in memo.render(result)


def test_only_the_judged_year_1_keys_are_held():
    assert menu.HELD == ("rev_growth.y1", "op_margin.y1") and checks.CHECKS_VERSION == "m3q.checks.v18"
    assert memo.MEMO_VERSION == "m3q.memo.v7"

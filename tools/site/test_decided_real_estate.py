"""WO_NC9c: real estate on the decided method (decided_real_estate.py: the variant of decided_value for the family `real_estate`, its record block, task text,
derived FFO and the check against the reported FFO; run.prepare and inputs.base in the real-estate mode are tested in qwen_c/tests/test_value_real_estate_base.py).
Synthetic data only; the model call is stubbed (runner.call) and every run folder is a temp dir."""
import copy
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decided_real_estate as RE  # noqa: E402
import decided_value as D  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import qwen_site  # noqa: E402
import test_decided_value as TD  # noqa: E402
from qwen_c.tests import test_value_checks as C  # noqa: E402
from qwen_c.value import desk  # noqa: E402

M = 1e6
FFO_TEXT = "Funds from operations attributable to common stockholders was $15.0 million for the year."
FFO_QUOTE = "was $15.0 million for the year"
PK = copy.deepcopy(TD.PK)
PK["evidence"].append({"fact_id": "F3", "kind": "annual_section", "title": "t", "form": "10-K", "period": "2025", "effective_at": "2026-01-01T00:00:00Z",
                       "source": None, "text": FFO_TEXT})
CAPEX_WHY = "The spending is recurring upkeep of the properties: tenant improvements and renewals, not acquisitions."


def series(*vals):
    return {"values": [{"end": e, "value": v * M, "tag": "T"} for e, v in zip(C.ENDS[-len(vals):], vals)]}


def facts_re():
    """The checks' canned company plus the real-estate record's series: consolidated profit, gains, impairments and preferred dividends."""
    f = C.facts()
    f.update(profit_loss_consolidated=series(8.4, 8.9, 9.4, 9.9, 10.4), re_gain_on_sales=series(0.5, 0.0, 2.0, 0.0, 1.0), re_impairment=series(0.2, 0.2, 0.2, 0.2, 0.5),
             preferred_dividends=series(0.3, 0.3, 0.3, 0.3, 0.3))
    return f


def reply(**over):
    ffo = {"value": 15.0, "scale": "millions", "per": "total", "what": "FFO attributable to common stockholders", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}
    o = TD.reply()
    o["situation"]["property_business"] = "owns_or_operates"
    o["reported_ffo"] = ffo
    o["reasons"]["capex_to_revenue"]["why"] = CAPEX_WHY
    for path, v in over.items():
        node = o
        *head, last = path.split(".")
        for h in head:
            node = node[h]
        node[last] = v
    return o


def arrange(tmp_path, monkeypatch, replies=(), facts=None):
    return TD.arrange(tmp_path, monkeypatch, replies, facts=facts or facts_re(), pk=PK)


def run(tmp_path, packet, seed=1000):
    return TD.run(tmp_path, packet, seed=seed, family="real_estate")


# ---- the text and the routing ----------------------------------------------------------------------------------------------------------

def test_the_real_estate_task_text_is_pinned_and_is_the_generic_text_with_additions_only():
    """Changing what the model is told is a versioned decision (non-negotiable 7): re-pin this hash and bump RE.VERSION together."""
    assert hashlib.sha256(RE.TASK.encode()).hexdigest() == "8f1bd856bd223a75b6963cd6fac55c948b054787874583be2aff1e8d45f35816"
    assert RE.VERSION.startswith("decided.real_estate.v2") and RE.FAMILY == "real_estate" and D.VARIANTS["real_estate"] is RE
    head, sep, tail = D.TASK.partition("\nSchema:\n")
    assert RE.TASK.startswith(head) and RE.PARAGRAPH in RE.TASK and "recurring capital expenditure, tenant improvements and leasing costs, the hotel renewal and replacement reserve" in RE.TASK
    assert "NOT acquisitions or development" in RE.TASK and '"property_business": "owns_or_operates|lends|unclear"' in RE.TASK and '"reported_ffo": {' in RE.TASK
    stripped = RE.TASK.replace("\n" + RE.PARAGRAPH, "", 1).replace(', "property_business": "owns_or_operates|lends|unclear"', "", 1).replace(
        '"reported_ffo": {"value": x, "scale": "units|thousands|millions|billions", "per": "total|per_share", "what": "...", "quotes": [{"id": "...", "quote": "..."}]} or null,\n ', "", 1)
    assert stripped == D.TASK                                                                 # the real-estate text is the generic text plus three additions
    assert "reported_ffo" not in D.TASK and "REAL ESTATE" not in D.TASK                  # the generic text is not touched


def test_routes_only_a_real_estate_sic_that_is_not_a_mortgage_reit_by_the_balance_sheet_route():
    fam = {"family": "family_not_built", "sic": "6798", "route": "operating_real_estate"}
    assert RE.routes(fam) and RE.routes(dict(fam, sic="6500")) and RE.routes(dict(fam, sic="6599")) and RE.routes(dict(fam, route=None))
    assert not RE.routes(dict(fam, route="financial"))                                    # a mortgage REIT stays refused
    assert not RE.routes(dict(fam, sic="6770")) and not RE.routes(dict(fam, sic="2834")) and not RE.routes(dict(fam, sic=None)) and not RE.routes(dict(fam, sic="6600"))
    assert not RE.routes(dict(fam, family="operating")) and not RE.routes(dict(fam, family="financial")) and not RE.routes({"family": None})


# ---- the record ------------------------------------------------------------------------------------------------------------------------

def test_derived_ffo_by_hand():
    d = RE.derived_ffo(facts_re(), "2025-12-31")
    assert d["net_income"] == 10.4 * M and d["net_income_tag"] == "T" and d["da"] == 5 * M and d["gain"] == 1 * M and d["impairment"] == 0.5 * M and d["preferred"] == 0.3 * M
    assert d["before_preferred"] == pytest.approx((10.4 + 5 - 1 + 0.5) * M) and d["after_preferred"] == pytest.approx((10.4 + 5 - 1 + 0.5 - 0.3) * M) and d["not_filed"] == []
    f = facts_re()
    for k in ("re_gain_on_sales", "re_impairment", "preferred_dividends", "profit_loss_consolidated"):
        del f[k]
    d = RE.derived_ffo(f, "2025-12-31")                          # net income as filed, nothing else: a component not filed is 0 and named
    assert d["before_preferred"] == pytest.approx((10 + 5) * M) and d["after_preferred"] == d["before_preferred"] and d["gain"] is None
    assert d["not_filed"] == ["gains", "impairments", "preferred_dividends"]
    f2 = facts_re()
    f2["re_gain_on_sales"] = series(0.0, 0.0, 0.0, 0.0, 0.0)        # 0.0 is a value: filed as 0, not "not filed"
    assert RE.derived_ffo(f2, "2025-12-31")["gain"] == 0.0 and "gains" not in RE.derived_ffo(f2, "2025-12-31")["not_filed"]
    f3 = facts_re()
    del f3["da"]
    assert RE.derived_ffo(f3, "2025-12-31") is None and RE.derived_ffo(facts_re(), "2031-12-31") is None


def test_the_message_carries_the_real_estate_text_and_the_derived_ffo_record(tmp_path, monkeypatch):
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()])
    res = run(tmp_path, packet)
    u = sent[0][1]["content"]
    assert res["status"] == "ok" and RE.PARAGRAPH in u and u.rstrip().endswith('"confidence": "low|medium|high"}') and "REAL ESTATE RECORD" in u
    assert "2025-12-31 | 10.4 (T) | 5.0 | 1.0 | 0.5 | 0.3 | 14.9 | 14.6" in u and "2021-12-31 | 8.4 (T) | 4.0 | 0.5 | 0.2 | 0.3 | 12.1 | 11.8" in u
    assert "A gain, impairment or dividend that is not filed counts as 0" in u and "[REC] FILED RECORD" in u
    assert prepared[0]["family"] == "real_estate" and prepared[0]["real_estate"] is True and res["versions"]["variant"] == RE.VERSION and res["family"] == "real_estate"
    assert D.messages(PK, "rec", "prior")[1]["content"].count("REAL ESTATE") == 0           # the generic message is as before


def test_the_record_says_how_working_capital_and_operating_income_were_taken():
    f, b = facts_re(), {"stamps": ["nwc_not_classified_taken_as_0", "operating_income_tag_stale_not_used"]}
    t = RE.real_estate_block(f, b)
    assert "working capital is taken as 0" in t and "pretax income plus interest expense in every year" in t
    rows = lambda text: [x for x in text.splitlines() if x[:2] == "20"]  # noqa: E731
    plain = RE.real_estate_block(f, {"stamps": []})
    assert "working capital is taken as 0" not in plain and "operating income tag has not been filed" not in plain and not any("n/f" in x for x in rows(plain))
    f["re_gain_on_sales"] = {"values": []}
    assert all("n/f" in x for x in rows(RE.real_estate_block(f, {"stamps": []})))


def test_a_stale_operating_income_tag_gives_the_record_the_pretax_plus_interest_margin_and_says_why():
    mk = lambda vals: {"values": [{"end": e, "value": v * M} for e, v in zip(TD.ENDS_ALL[-len(vals):], vals)]}  # noqa: E731
    f_all = {"revenue": mk([100, 110, 120]), "operating_income": mk([10]), "pretax_income": mk([8, 9, 10]), "interest_expense": mk([1, 1, 1])}
    b = dict(inputs_base(), stamps=["oi_from_pretax_plus_interest", "operating_income_tag_stale_not_used"])
    text, rec = RE.record_text(facts_re(), f_all, b, C.R, dict(C.PROV))
    assert "(pretax income + interest expense) / revenue, the operating income tag not being filed for the latest fiscal year" in text
    assert rec["margins"] == pytest.approx({"2023-12-31": 9 / 100, "2024-12-31": 10 / 110, "2025-12-31": 11 / 120})
    text2, rec2 = RE.record_text(facts_re(), dict(f_all, operating_income=mk([10, 11, 12])), dict(b, stamps=[]), C.R, dict(C.PROV))
    assert "operating income / revenue" in text2 and rec2["margins"]["2025-12-31"] == pytest.approx(12 / 120)


def inputs_base():
    from qwen_c.value import inputs
    return inputs.base(C.facts(), market_cap=180e6, bill_rate=0.04) | {"stub_days": 0, "g_anchor": 0.03}


# ---- one run ---------------------------------------------------------------------------------------------------------------------------

def test_a_valid_real_estate_reply_is_valued_as_the_generic_one_and_carries_the_ffo_check(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and len(sent) == 1 and res["values"]["bear"] < res["values"]["base"] < res["values"]["bull"]
    assert res["values"]["base"] == D.value_inputs(b, C.R, reply()["inputs"])[0]                      # the numeric route is the generic one
    d = res["decided"]
    assert d["inputs"] == reply()["inputs"] and d["value_at_old_defaults"] == D.old_defaults(b, bar, C.R)[0]
    ffo = d["real_estate"]["ffo"]
    assert d["real_estate"]["version"] == RE.VERSION and d["real_estate"]["property_business"] == "owns_or_operates" and ffo["status"] == "compared"
    assert ffo["reported"]["value"] == 15.0 * M and ffo["reported"]["quotes"] == [{"id": "F3", "quote": FFO_QUOTE}] and ffo["reported"]["scale"] == "millions"
    assert ffo["derived_after_preferred"] == pytest.approx(14.6 * M) and ffo["derived_before_preferred"] == pytest.approx(14.9 * M) and ffo["per_share_divisor"] is None
    assert ffo["gap_after_preferred"] == pytest.approx(14.6 / 15 - 1) and ffo["gap_before_preferred"] == pytest.approx(14.9 / 15 - 1)
    assert "ffo_derived_vs_reported: -2.7%" in d["flags"] and "quotes_verified: 7 of 7" in d["flags"]
    assert not any("not_reported" in x or x.startswith("capex_reason") or x == "property_business_unclear" for x in d["flags"])
    assert RE.derived_ffo(facts_re(), "2025-12-31")["after_preferred"] == pytest.approx(ffo["derived_after_preferred"])


def test_no_reported_ffo_is_stamped_and_valued_all_the_same(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(reported_ffo=None)])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and "ffo_not_reported_or_not_found" in res["decided"]["flags"] and res["decided"]["real_estate"]["ffo"] == {"status": "not_reported_or_not_found"}
    assert not any(x.startswith("ffo_derived_vs_reported") for x in res["decided"]["flags"])


def test_a_gain_or_impairment_or_dividend_not_filed_is_named_beside_the_comparison(tmp_path, monkeypatch):
    f = facts_re()
    del f["re_gain_on_sales"], f["preferred_dividends"]
    packet, *_ = arrange(tmp_path, monkeypatch, [reply()], facts=f)
    res = run(tmp_path, packet)
    assert "ffo_derived_vs_reported: +6.0%" in res["decided"]["flags"]                           # (10.4 + 5 + 0.5) / 15 - 1
    assert "ffo_derived_gains_taken_as_0" in res["decided"]["flags"] and "ffo_derived_preferred_dividends_taken_as_0" in res["decided"]["flags"]


def test_a_per_share_figure_is_compared_on_the_bases_diluted_shares_and_says_so(tmp_path, monkeypatch):
    f = facts_re()
    pk = copy.deepcopy(PK)
    pk["evidence"][-1]["text"] = "Funds from operations attributable to common stockholders was $1.46 per diluted share for the year."
    packet, b, bar, sent, _ = TD.arrange(tmp_path, monkeypatch, [reply(reported_ffo={"value": 1.46, "scale": "units", "per": "per_share", "what": "FFO per share",
                                                                                      "quotes": [{"id": "F3", "quote": "was $1.46 per diluted share"}]})], facts=f, pk=pk)
    res = run(tmp_path, packet)
    ffo = res["decided"]["real_estate"]["ffo"]
    assert res["status"] == "ok" and ffo["per_share_divisor"] == b["shares"] and ffo["reported"]["value"] == 1.46 and ffo["reported"]["per"] == "per_share"
    assert ffo["gap_after_preferred"] == pytest.approx(14.6 * M / b["shares"] / 1.46 - 1)
    assert "ffo_compared_per_share_on_the_base_years_diluted_shares" in res["decided"]["flags"]


REPAIRS = [
    ("the digits are not in the quote", {"reported_ffo": {"value": 16.0, "scale": "millions", "per": "total", "what": "x", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}},
     "reported_ffo.value 16.0 does not appear in any quote that was found word for word"),
    ("the quote is not in the item", {"reported_ffo": {"value": 15.0, "scale": "millions", "per": "total", "what": "x", "quotes": [{"id": "F3", "quote": "was $15.0 billion"}]}},
     "reported_ffo has no quote found word for word"),
    ("the quote cites an item that does not exist", {"reported_ffo": {"value": 15.0, "scale": "millions", "per": "total", "what": "x", "quotes": [{"id": "F9", "quote": FFO_QUOTE}]}},
     "reported_ffo has no quote found word for word"),
    ("no quote", {"reported_ffo": {"value": 15.0, "scale": "millions", "per": "total", "what": "x", "quotes": []}}, "reported_ffo has no quote found word for word"),
    ("the quote is the prior read's", {"reported_ffo": {"value": 15.0, "scale": "millions", "per": "total", "what": "x",
                                                        "quotes": [{"id": "business_model", "quote": "A supported claim about the business."}]}},
     "reported_ffo has no quote found word for word"),
    ("a scale that is not one", {"reported_ffo": {"value": 15.0, "scale": "tens", "per": "total", "what": "x", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}},
     "reported_ffo.scale must be one of units, thousands, millions, billions"),
    ("a per that is not one", {"reported_ffo": {"value": 15.0, "scale": "millions", "per": "each", "what": "x", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}},
     "reported_ffo.per must be one of total, per_share"),
    ("a value of 0", {"reported_ffo": {"value": 0, "scale": "millions", "per": "total", "what": "x", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}},
     "is not a number above 0"),
    ("a value that is text", {"reported_ffo": {"value": "about fifteen", "scale": "millions", "per": "total", "what": "x", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}},
     "is not a number above 0"),
    ("what missing", {"reported_ffo": {"value": 15.0, "scale": "millions", "per": "total", "what": " ", "quotes": [{"id": "F3", "quote": FFO_QUOTE}]}}, "reported_ffo.what is missing"),
    ("reported_ffo is a number", {"reported_ffo": 15.0}, "reported_ffo must be an object or null"),
    ("property_business missing", {"situation.property_business": "somewhat"}, "situation.property_business must be one of owns_or_operates, lends, unclear"),
]


@pytest.mark.parametrize("label,over,expect", REPAIRS, ids=[r[0] for r in REPAIRS])
def test_a_failed_real_estate_check_gets_one_repair_turn_naming_the_problem(tmp_path, monkeypatch, label, over, expect):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**over), reply()])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and res["checked_attempt"] == 2 and len(sent) == 2 and expect in sent[1][3]["content"]
    assert res["attempts"][0]["outcome"] == "invalid" and res["attempts"][1]["outcome"] == "ok"
    assert res["decided"]["real_estate"]["ffo"]["reported"]["value"] == 15.0 * M                         # the second attempt's record, not the first's


def test_a_generic_reply_without_the_real_estate_fields_is_invalid_for_real_estate_and_a_second_failure_is_decision_invalid(tmp_path, monkeypatch):
    generic = TD.reply()
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [generic, generic])
    res = run(tmp_path, packet)
    assert res["status"] == "no_call" and res["reason"] == "decision_invalid" and "situation.property_business must be one of" in res["detail"] and len(sent) == 2
    o = reply()
    del o["reported_ffo"]
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [o, reply()])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and "reported_ffo is missing" in sent[1][3]["content"]


def test_a_lender_is_refused_after_the_read_says_so_with_no_value_and_no_repair_turn(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**{"situation.property_business": "lends"}), reply()])
    res = run(tmp_path, packet)
    assert res["status"] == "no_call" and res["reason"] == RE.LENDER_REFUSAL and len(sent) == 1 and "values" not in res and res["decided"]["situation"]["property_business"] == "lends"
    assert res["attempts"][0]["outcome"] == "refused"
    (path,) = (tmp_path / "runs").glob("TEST_*_decided_1000/result.json")
    assert json.loads(path.read_text(encoding="utf-8"))["reason"] == RE.LENDER_REFUSAL
    rep = G.Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, TD.N(packet) | {"family": "real_estate"}, {"1000": res, "3000": res}, "c")
    assert rep["valued"] is False and rep["no_value_reason"] == qwen_site.NO_VALUE[RE.LENDER_REFUSAL] and "decided" not in rep and rep["family"] == "real_estate"


def test_an_unclear_business_and_a_capex_reason_that_names_no_spending_are_flags_not_gates(tmp_path, monkeypatch):
    why = {k: v for k, v in reply()["reasons"].items()}
    why["capex_to_revenue"] = {"why": "Because of the usual ratio.", "quotes": [{"id": "F1", "quote": TD.QUOTE}]}
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(**{"situation.property_business": "unclear"}, reasons=why)])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and "property_business_unclear" in res["decided"]["flags"] and "capex_reason_does_not_name_the_spending" in res["decided"]["flags"]
    for text in ("Acquisitions of new hotels are excluded; the reserve for renewals is 4%.", "Redevelopment of two malls.", "FF&E reserve."):
        why["capex_to_revenue"]["why"] = text
        packet, *_ = arrange(tmp_path, monkeypatch, [reply(reasons=why)])
        assert "capex_reason_does_not_name_the_spending" not in run(tmp_path, packet)["decided"]["flags"]


def test_the_menu_families_are_unchanged_by_the_variant(tmp_path, monkeypatch):
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [TD.reply()])
    res = TD.run(tmp_path, packet, family="operating")
    assert res["status"] == "ok" and "variant" not in res["versions"] and "real_estate" not in res["decided"] and prepared[0].get("real_estate") is None
    assert "REAL ESTATE" not in sent[0][1]["content"]


def test_without_the_registered_variant_the_family_is_not_routed(tmp_path, monkeypatch):
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()])
    monkeypatch.delitem(D.VARIANTS, "real_estate")
    res = run(tmp_path, packet)
    assert res["reason"] == "family_not_routed" and sent == [] and prepared == []


def test_a_prepare_refusal_is_the_menu_methods_refusal_for_real_estate_too(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    monkeypatch.setattr(D.vrun, "prepare", lambda *a, **k: (_ for _ in ()).throw(desk.DeskRefusal("facts_stale", "pretax_income ends 2018")))
    res = run(tmp_path, packet)
    assert (res["status"], res["reason"]) == ("no_call", "facts_stale") and sent == []


def test_two_real_estate_runs_make_a_report_with_the_variant_record_in_each_run(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply(**{"inputs.long_run_op_margin": 0.12})])
    rs = {str(s): run(tmp_path, packet, seed=s) for s in (1000, 3000)}
    rep = G.Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, TD.N(packet) | {"family": "real_estate"}, rs, "c")
    assert rep["valued"] and rep["family"] == "real_estate" and rep["valuation"] is None
    assert rep["decided"]["runs"]["1000"]["real_estate"]["ffo"]["status"] == "compared" and any("ffo_derived_vs_reported" in x for x in rep["decided"]["flags"])
    json.dumps(rep)


# ---- the switch in gemini_ondemand.analyze ---------------------------------------------------------------------------------------

def switch(tmp_path, monkeypatch, method, fam):
    import test_why_losses as TW
    seeds, reports, sent = TW.arrange(tmp_path, monkeypatch, False)
    monkeypatch.setitem(sys.modules, "formation_value", types.SimpleNamespace(stocks_rows=lambda c: {"TEST": {"sector": "Real Estate", "marketCap": 1e8}}, name_family=lambda cik, T: fam))
    prepared, calls = [], []
    monkeypatch.setattr(G.vrun, "prepare", lambda *a, **k: prepared.append(k) or ({}, {}, None, None, None, None, None))
    monkeypatch.setattr(G.decided_value, "value", lambda *a, **k: calls.append((a, k)) or {"status": "ok", "seed": k["seed"]})
    monkeypatch.setattr(G, "VALUE_METHOD", method)
    return seeds, reports, prepared, calls


REIT = {"family": "family_not_built", "sic": "6798", "route": "operating_real_estate", "classification": "family_not_built"}


def test_decided_routes_a_real_estate_name_to_the_variant_and_prepares_it_in_the_real_estate_mode(tmp_path, monkeypatch):
    seeds, reports, prepared, calls = switch(tmp_path, monkeypatch, "decided", REIT)
    assert G.analyze("TEST", "list") == "ok"
    assert seeds == [] and [k["family"] for _, k in calls] == ["real_estate", "real_estate"] and prepared[0]["family"] == "real_estate" and prepared[0]["real_estate"] is True


def test_the_menu_and_a_mortgage_reit_and_other_not_built_families_stay_refused(tmp_path, monkeypatch):
    for i, (method, fam) in enumerate([("menu", REIT), ("decided", dict(REIT, route="financial")), ("decided", dict(REIT, sic="6770")),
                                       ("decided", dict(REIT, sic="2834"))]):
        (tmp_path / str(i)).mkdir()
        seeds, reports, prepared, calls = switch(tmp_path / str(i), monkeypatch, method, fam)
        G.analyze("TEST", "list")
        assert calls == [] and seeds == [1000, 3000] and all(k["family"] == "family_not_built" and "real_estate" not in k for k in prepared)


# ---- the desk keeps depreciation above upkeep for equity (real estate only; 2026-11-19, the REIT gap review) ----

def _desk_inp(capex_ratio, **over):
    rev = [1000.0 * 1.03 ** t for t in range(6)]
    d = {"revenue": rev, "margin": [0.12] * 5, "capex": [capex_ratio * R for R in rev[1:]], "d_ratio": 0.10, "w": 0.0, "p_ratio": 0.0, "rou_ratio": 0.0,
         "amort_schedule": [0.0] * 5, "amort_thereafter": 0.0, "delta": 0.4, "kd": 0.05, "tau": 0.05, "r": 0.09, "g_T": 0.03, "F": 10, "H": 0,
         "ronic0": 0.09, "ronic_T": 0.08, "m_long": 0.12, "shares": 100.0, "excess_cash": 0.0, "stub_days": 0}
    return dict(d, **over)


def test_without_the_real_estate_key_and_with_upkeep_at_or_above_depreciation_the_desk_is_unchanged():
    from qwen_c.value import checks, desk
    plain = desk.value_operating(_desk_inp(0.04))
    assert plain["depreciation_kept"] == [0.0] * 5 and plain["depreciation_kept_rate"] == 0.0
    above = _desk_inp(0.10)                                           # capex = pooled D&A: nothing above upkeep
    a, b = desk.value_operating(above), desk.value_operating(dict(above, real_estate=True))
    assert a["value_per_share"] == b["value_per_share"] and a["flows_all"] == b["flows_all"]
    checks._recompute(dict(above, real_estate=True), b)


def test_real_estate_keeps_the_depreciation_above_upkeep_whole_every_year_and_in_the_terminal():
    from qwen_c.value import checks, desk
    inp = _desk_inp(0.04)
    a, b = desk.value_operating(inp), desk.value_operating(dict(inp, real_estate=True))
    kept = b["depreciation_kept"]
    assert all(abs(k - 0.06 * R) < 1e-9 for k, R in zip(kept, inp["revenue"][1:]))
    for t in range(5):                                                # years 1..5: the frame gave 1 - delta of it; the rest is added
        assert abs(b["flows_all"][t] - a["flows_all"][t] - 0.4 * kept[t]) < 1e-9
    assert abs(b["depreciation_kept_rate"] - 0.06) < 1e-12
    n, rN = b["n_years"], inp["revenue"][5]
    g5 = inp["revenue"][5] / inp["revenue"][4] - 1.0
    for t in range(6, n + 1):
        rN *= 1.0 + g5 + (0.03 - g5) * (t - 5) / (n - 5)
    x_term = lambda v: v["tv"] * (0.09 - 0.03)                        # noqa: E731  the terminal year's flow
    assert abs(x_term(b) - x_term(a) - 0.06 * rN * 1.03) < 1e-6
    # the fading gap no longer carries the depreciation: at the last fade year the flow is the funded-growth flow plus the kept share
    assert abs(b["flows_all"][n - 1] - (b["x_all"][n - 1] * (1 - 0.03 / desk.equity_ronic(0.08, 0.4, 0.05, 0.05)) + 0.06 * rN)) < 1e-6
    assert b["value_per_share"] > a["value_per_share"]
    checks._recompute(dict(inp, real_estate=True), b)

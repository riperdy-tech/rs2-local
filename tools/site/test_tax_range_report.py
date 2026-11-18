"""WO_NC3: the site report of a name valued at a statutory tax fallback carries the base value at both rates, the label, and a flag for a verdict
that differs at the second rate (qwen_ondemand.report, qwen_site.quote_units, gemini_ondemand.verdict_differs_at_alt_tax_rate). Synthetic data."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_ondemand as G  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import qwen_site  # noqa: E402
from qwen_c.tests import test_value_checks as C  # noqa: E402
from qwen_c.tests import test_value_tax_statutory as TS  # noqa: E402
from qwen_c.value import consensus, desk, forecast, inputs, run, task  # noqa: E402


def arrange(tmp_path, monkeypatch, f):
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0, g_anchor=0.03, bill_source="test")
    bar, record = forecast.record_bar(b["record"]["op_margin"]), forecast.record_items(f)
    pk = {"evidence": [{"fact_id": k, "kind": kd, "period": per, "text": t} for k, (kd, per, t) in C.ITEMS.items()]}
    p = tmp_path / "packet.json"
    p.write_text(json.dumps(pk), encoding="utf-8")
    monkeypatch.setattr(run, "prepare", lambda *a, **k: (f, b, bar, record, C.R, C.PROV, C.ENDS))
    ids = task.evidence_ids(pk, record, b, bar, C.R, C.PROV)
    reply = C.clean()
    res = C.run((b, bar, ids), copy.deepcopy(reply))
    seed = {"status": res["status"], "inputs": reply, "checks": res, "values": res["values"], "base": b,
            "tax_range": {"values_alt": {"base": 1.5}}}
    n = {"packet": str(p), "cik": "1", "sector": "Technology", "market_cap": 180e6, "family": "operating"}
    return n, {"1000": seed, "3000": seed}, (b, bar, ids)


def report(n, results):
    return Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, n, results, "c")


def test_the_report_carries_both_values_the_label_and_the_second_rates_seed_values(tmp_path, monkeypatch):
    n, results, (b, bar, ids) = arrange(tmp_path, monkeypatch, TS.fb_facts())
    rep = report(n, results)
    tr = rep["tax_range"]
    assert rep["valued"] and tr["label"] == "statutory rate (company's filed rate), not measured" and tr["rate"] == 0.21
    assert tr["rate_alt"] == pytest.approx(0.265) and tr["status_alt"] == "ok" and tr["source_tag"] == f"us-gaap:{TS.STAT}"
    assert (tr["positive_pretax_years"], tr["pretax_years"]) == (2, 5) and tr["seed_base_alt"] == {"1000": 1.5, "3000": 1.5}
    one = consensus.combine(results, ids, b, bar, C.R, C.ENDS, "operating")["values"]                  # the filed rate's value is the report's own
    assert rep["value_per_filed_share"] == {k: one[k] for k in ("bear", "base", "bull")}
    twin = inputs.base(TS.measured_twin(0.265), market_cap=180e6, bill_rate=0.04)                      # the second rate's value is the same combine at 26.5%
    two = consensus.combine(results, ids, dict(twin, stub_days=0, g_anchor=0.03), bar, C.R, C.ENDS, "operating")["values"]
    for k in ("bear", "base", "bull"):
        assert tr["value_per_filed_share_alt"][k] == pytest.approx(two[k], rel=1e-9)
    assert tr["value_per_filed_share_alt"]["base"] < rep["value_per_filed_share"]["base"]
    assert tr["equity_value_alt"] == pytest.approx(tr["value_per_filed_share_alt"]["base"] * b["shares"]) and rep["equity_value"] == one["base"] * b["shares"]


def test_a_name_without_a_fallback_has_no_tax_range(tmp_path, monkeypatch):
    n, results, _ = arrange(tmp_path, monkeypatch, C.facts())
    assert "tax_range" not in report(n, results)


def test_a_second_value_that_cannot_be_made_leaves_the_first_report_intact(tmp_path, monkeypatch):
    n, results, _ = arrange(tmp_path, monkeypatch, TS.fb_facts())
    first = report(n, results)
    monkeypatch.setattr(run, "alt_tax_base", lambda *a: (_ for _ in ()).throw(desk.DeskRefusal("e0_not_positive", "no earnings base")))
    rep = report(n, results)
    assert rep["tax_range"]["value_per_filed_share_alt"] is None and "e0_not_positive" in rep["tax_range"]["status_alt"]
    assert {k: v for k, v in rep.items() if k != "tax_range"} == {k: v for k, v in first.items() if k != "tax_range"}


def test_quote_units_scales_the_second_rates_values_like_the_first():
    rep = {"equity_value": 100.0, "filed_shares": 10.0, "value_per_filed_share": {"bear": 8.0, "base": 10.0, "bull": 12.0},
           "tax_range": {"value_per_filed_share_alt": {"bear": 6.0, "base": 8.0, "bull": 10.0}}}
    row = dict(rep)
    qwen_site.quote_units({"T": (row, rep)}, {"T": {"price": 5.0, "marketCap": 100.0}})            # 20 quoted shares: one filed share is two quoted
    assert row["value_base"] == 5.0 and row["tax_range"]["value_alt"] == {"bear": 3.0, "base": 4.0, "bull": 5.0}
    assert rep["tax_range"] == row["tax_range"]


PROB = {"bear": 0.25, "base": 0.5, "bull": 0.25}


def _row(price, alt, alt_seeds):
    return {"valued": True, "value_bear": 18.0, "value_base": 20.0, "value_bull": 22.0, "price_at_publish": price,
            "value_per_filed_share": {"base": 20.0}, "seed_base": {"1000": 20.0, "3000": 20.0},
            "tax_range": {"value_alt": alt, "value_per_filed_share_alt": {"base": alt["base"]} if alt else None, "seed_base_alt": alt_seeds}}


def test_the_flag_is_the_same_verdict_function_on_the_second_values():
    ke = 0.10
    row = _row(17.0, {"bear": 14.0, "base": 16.0, "bull": 18.0}, {"1000": 16.0, "3000": 16.0})
    v = G.verdict(row, ke, PROB)[0]
    assert v == "BUY" and G.verdict_differs_at_alt_tax_rate(row, ke, PROB, v) is True              # 16 against a price of 17: AVOID at the second rate
    row = _row(17.0, {"bear": 18.0, "base": 20.0, "bull": 22.0}, {"1000": 20.0, "3000": 20.0})
    assert G.verdict_differs_at_alt_tax_rate(row, ke, PROB, G.verdict(row, ke, PROB)[0]) is False
    row = _row(17.0, {"bear": 18.0, "base": 20.0, "bull": 22.0}, {"1000": 20.0, "3000": 16.0})    # one second-rate run falls short of BUY: WATCH
    assert G.verdict_differs_at_alt_tax_rate(row, ke, PROB, "BUY") is True
    assert G.verdict_differs_at_alt_tax_rate(_row(17.0, None, {}), ke, PROB, "BUY") is None       # no second value: nothing to compare
    assert G.verdict(row, ke, PROB)[0] == "BUY"                                                    # the label itself reads the first values only

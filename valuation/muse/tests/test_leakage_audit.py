"""The leakage audit: dates after T, availability and replay wording, the header, identity stamps, forbidden pass-1 words, the report."""
import json
from datetime import date

import pytest

from valuation.muse import leakage_audit as la
from valuation.muse.pipeline import run_company
from valuation.muse.tests import fixtures as fx

T = date(2026, 4, 15)


def matches(text, asof=T):
    return [m for m, _a, _b in la.dates_after(text, asof)]


@pytest.mark.parametrize("text,expected", [
    ("filed 2026-04-16", ["2026-04-16"]),
    ("filed 2026-04-15", []),
    ("filed 2026-04-14", []),
    ("on March 3, 2027 the", ["March 3, 2027"]),
    ("on 3 June 2026 the", ["3 June 2026"]),
    ("in April 2026", []),
    ("in May 2026", ["May 2026"]),
    ("in March 2026", []),
    ("for FY2027", ["FY2027"]),
    ("fiscal year 2026", []),
    ("in Q3 2027", ["Q3 2027"]),
    ("by 2030", ["2030"]),
    ("by 2026", []),
    ("12,030 units and 2,030 shares and 1.2030", []),
    ("2027-01-01 and also 2027", ["2027-01-01", "2027"]),
])
def test_dates_after_T(text, expected):
    assert matches(text) == expected


def test_a_date_in_a_code_built_section_is_a_violation_and_in_a_document_body_a_review():
    f = la.scan_section("F", "Revenue as of 2026-12-31", T, "pack")
    assert [(x.kind, x.severity) for x in f] == [("date_after_T", "violation")]
    body = la.scan_section("D", "[D1] Annual report, filed 2026-02-28\nWe expect to open the plant in 2027 and 2027-06-30.", T, "pack")
    assert {x.severity for x in body} == {"review"} and {x.where for x in body} == {"pack section D body"}
    header = la.scan_section("D", "[D1] Annual report, filed 2026-05-28\nplain text", T, "pack")
    assert [(x.severity, x.where) for x in header] == [("violation", "pack section D header")]


@pytest.mark.parametrize("w", ["This is a replay of 2025", "a back-test", "backtest", "point-in-time data", "as known at the time", "data availability",
                               "the knowledge cutoff of the model", "hindsight", "look-ahead", "simulated", "available at the date"])
def test_availability_and_replay_wording_is_found(w):
    assert any(f.kind == "wording" for f in la.scan_text(w, T, "x"))


def test_ordinary_text_is_clean():
    assert la.scan_text("Revenue grew 4.2% and margins widened; securities available for sale.", T, "x") == []


def test_forbidden_pass1_words():
    for w in ("the price of the stock", "the market cap", "consensus estimates", "a price target", "valuation", "stock returns", "news flow",
              "intrinsic value"):
        assert any(f.kind == "forbidden_pass1" for f in la.scan_text(w, T, "x", pass1=True)), w
    assert not la.scan_text("return on new invested capital; operating margin; growth", T, "x", pass1=True)
    assert not la.scan_text("the price of the stock", T, "x", pass1=False)


def test_the_header_must_be_exactly_analysis_date_T():
    ok = "Analysis date: 2026-04-15\nCompany: X\n\nTASK."
    assert la.scan_prompt_text(ok, T, "p", pass1=True) == []
    for bad in ("Analysis date: 2026-04-14\nx", "Company: X\nAnalysis date: 2026-04-15", "Analysis date: 2026-04-15\nAnalysis date: 2026-04-15"):
        assert any(f.kind == "header" for f in la.scan_prompt_text(bad, T, "p", pass1=True)), bad


def test_the_templates_and_system_text_are_clean_and_carry_no_date():
    assert [f.as_dict() for f in la.audit_templates()] == []


def test_identity_must_be_stamped_as_of_T_and_late_documents_are_flagged_in_the_manifest():
    pack = {"header": "Analysis date: 2026-04-15\nCompany: X (X)", "sections": {}, "r": {},
            "manifest": {"identity": {"name_source": "current_record", "ticker_source": "as_of_T", "industry_source": "as_of_T"},
                         "documents": {"used": [{"accession": "A1", "accepted_at": "2026-04-15T20:00:01.000Z", "filed": "2026-04-15"},
                                                {"accession": "A2", "accepted_at": None, "filed": "2026-04-15"},
                                                {"accession": "A3", "accepted_at": "2026-04-15T19:00:00.000Z", "filed": "2026-04-15"}]}}}
    f = la.audit_pack(pack, T)
    assert [x.match for x in f if x.kind == "identity"] == ["name_source=current_record"]
    assert [x.match for x in f if x.kind == "date_after_T"] == ["A1", "A2"]


def make_run(tmp_path):
    run_company(pit=fx.make_pit(), identity=fx.IDENTITY, priors=fx.LabeledPlaceholderPriors(), disc_factory=fx.disc_factory, client=fx.ScriptedMuse(),
                run_dir=tmp_path / "runs" / "SYN_2026-04-15", price_info={"price": 25.0, "market_cap": 2500.0, "currency": "USD"}, documents=fx.docs(),
                quarters=fx.quarters(), n_draws=100, seed=1)
    return tmp_path / "runs"


def test_a_clean_run_audits_clean_and_a_poisoned_request_is_caught(tmp_path):
    root = make_run(tmp_path)
    assert la.audit(root)["violations"] == 0
    p = next((root / "SYN_2026-04-15").glob("01_P1_a1_request.json"))
    req = json.loads(p.read_text())
    req["messages"][1]["content"] = req["messages"][1]["content"].replace("TASK.", "TASK. This is a replay; results are due 2027-05-01 and the price is 25.0.", 1)
    p.write_text(json.dumps(req))
    rep = la.audit(root)
    kinds = {(f["kind"], f["match"]) for r in rep["runs"] for f in r["findings"]}
    assert ("wording", "replay") in kinds and ("date_after_T", "2027-05-01") in kinds and ("forbidden_pass1", "price") in kinds
    assert rep["violations"] >= 3


def test_the_report_and_the_cli(tmp_path, capsys):
    root = make_run(tmp_path)
    out = tmp_path / "report.md"
    assert la.main([str(root), "--out", str(out), "--strict"]) == 0
    md = out.read_text()
    assert md.startswith("# Muse leakage audit") and "Violations: 0" in md and "Coordinator's checklist" in md
    assert json.loads(out.with_suffix(".json").read_text())["violations"] == 0
    p = next((root / "SYN_2026-04-15").glob("02_P2_a1_request.json"))
    req = json.loads(p.read_text())
    req["messages"][1]["content"] += "\nback-test"
    p.write_text(json.dumps(req))
    assert la.main([str(root), "--strict"]) == 1
    assert "back-test" in capsys.readouterr().out

"""The old engine (revision 21's reference) on the synthetic world: it computes where its inputs exist, says why where not, and never reads past the date."""
import pytest

from rebuild_harness import old_engine, run_harness
from rebuild_harness.tests.test_run_harness import build_world, N
from valuation.pit_data import Panel
from valuation.tests import synth


ANCHORS = {"rf": 0.03, "ga": 0.03, "breakeven": 0.02, "loading": {"Technology": 1.0}, "erp": 0.05, "bill_rate_at": lambda fye: 0.02}


def make(pit, ciks, anchors=ANCHORS):
    panel = Panel(pit, ciks, ("revenue",))
    corpus = old_engine.BaseRateCorpus(panel)
    return old_engine.make_old_engine(lambda asof: anchors, corpus, sector_of=lambda cik: "Technology", family_of=lambda cik, asof: "operating")


def test_the_old_engine_computes_a_per_share_value_with_its_stamps(tmp_path):
    pit, ciks = build_world(tmp_path)
    eng = make(pit, ciks)
    r = eng("T5", "2019-06-28", pit)
    assert r["value_per_share"] is not None and r["value_per_share"] > 0, r
    assert r["family"] == "operating" and r["components"]["method"] == "growth"
    for s in ("consensus_synthetic_base_rate_median", "input_scope_not_applied", "coe_unquantised"):
        assert s in r["stamps"]
    assert any(s.startswith("base_rate_corpus_companies:") for s in r["stamps"])
    assert r["forecasts"] and r["forecasts"][1]["revenue"] > 0


def test_no_anchor_means_no_value_and_says_so(tmp_path):
    pit, ciks = build_world(tmp_path)
    eng = old_engine.make_old_engine(lambda asof: None, old_engine.BaseRateCorpus(Panel(pit, ciks, ("revenue",))))
    r = eng("T5", "2019-06-28", pit)
    assert r["value_per_share"] is None and r["reason"] == "no_pit_anchor"
    r = make(pit, ciks, anchors={**ANCHORS, "erp": None})("T5", "2019-06-28", pit)
    assert r["value_per_share"] is None and r["reason"] == "anchor_incomplete"


def test_an_unknown_ticker_and_a_date_before_any_annual_report(tmp_path):
    pit, ciks = build_world(tmp_path)
    eng = make(pit, ciks)
    assert eng("NOPE", "2019-06-28", pit)["reason"] == "no_cik_for_ticker"
    assert eng("T5", "2012-06-29", pit)["reason"] == "no_annual_report_before_date"


def test_the_value_does_not_depend_on_filings_after_the_date(tmp_path):
    pit, ciks = build_world(tmp_path / "a")
    a = make(pit, ciks)("T7", "2018-06-29", pit)["value_per_share"]
    pit2, _ = build_world(tmp_path / "b")
    for cik in ciks:
        synth.drop_filed_on_or_after(tmp_path / "b" / "store", cik, "2018-06-29")
    b = make(pit2, ciks)("T7", "2018-06-29", pit2)["value_per_share"]
    assert a == b and a is not None


def test_the_old_engine_runs_in_the_harness_and_has_a_distribution(tmp_path):
    pit, ciks = build_world(tmp_path)
    make(pit, ciks)
    res = run_harness.run(["2019-06-28"], ciks, ["old_engine_rev21", "yardstick_earnings_yield"], pit, tmp_path / "out", n_resamples=20)
    s = res["summary"]["engines"]["old_engine_rev21"]
    assert s["value_over_price"]["overall"]["n"] > 0
    assert res["coverage"]["dates"]["2019-06-28"]["engine_scored"]["old_engine_rev21"] > 0
    assert "forecast_error_vs_naive" in s


def test_the_old_engine_identity_lists_the_reference_modules():
    pit = None
    eng = old_engine.make_old_engine(lambda a: None, None)
    names = {p.name for p in eng.frozen_files}
    assert {"old_engine.py", "consensus_reference.py", "throughcycle_record.py", "base_rates.py", "growth_persistence.py", "arms.py"} <= names
    assert all(p.is_file() for p in eng.frozen_files)

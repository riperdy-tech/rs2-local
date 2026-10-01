"""Revision 18, part 2 (brief sections 2 and 1.6, amendment 1): the closure premium, the cost of equity built on it, and
`reference_inputs`, the single source of the reference's inputs.

  - the cost of equity: COE = max(rf, gA) + adjusted loading x ERP_closure, no fallback, quantized only for the pack;
  - rs2_data.reference_closure(): the artifact, its bounds and its staleness;
  - the aggregate (MRI's rules, amendment A1's exclusion), the members, the solver, the coverage floor;
  - the identity on a synthetic aggregate: sum of max(V, 0) x shares = sum of caps at the solved premium;
  - parity: the pack's printed reference is build(**reference_inputs(...)) on an independent data root.
Fixtures are synthetic (numbers written for the test).
"""
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import pack_facts  # noqa: E402
import reference_closure as rc  # noqa: E402
import rs2_data  # noqa: E402
from test_throughcycle_reference import EST, _synthetic_pack  # noqa: E402

B = 1e9
REAL_REFERENCE_CLOSURE = rs2_data.reference_closure         # captured at import, before the suite's autouse stub (conftest)


# ---- the solver ---------------------------------------------------------------------------------------------------------

def test_the_solver_finds_the_interior_root_and_flags_the_bounds():
    total = lambda erp: 1000.0 * (1.0 - 4.0 * erp)                      # decreasing: 1000 at 0, 200 at 0.2
    erp, flag = rc.solve_erp(total, 600.0)
    assert flag is None and erp == pytest.approx(0.1, abs=1e-9) and total(erp) == pytest.approx(600.0, abs=1e-6)
    assert rc.solve_erp(total, 1.0) == (rc.ERP_HIGH, "bound_high")        # even the highest premium leaves the value above the target
    assert rc.solve_erp(total, 5000.0) == (rc.ERP_LOW, "bound_low")       # even the lowest leaves it below
    assert rc.ITERATIONS == 80 and (rc.ERP_LOW, rc.ERP_HIGH) == (0.0005, 0.20)
    assert rc.closure_gap(101.0, 100.0) == pytest.approx(0.01)


def test_the_coverage_floor_refuses_below_300_members_or_60_percent_of_the_aggregates_capitalisation():
    rc.check_floor(300, 0.60)                                           # exactly at the floors passes
    for n, cov in ((299, 0.90), (500, 0.5999), (0, 0.0)):
        with pytest.raises(rc.Refused, match="coverage floor"):
            rc.check_floor(n, cov)


# ---- members and the identity on a synthetic aggregate --------------------------------------------------------------------

def _synthetic_names(n=400, seed=20261001):
    """n companies, each valued by the real `consensus_reference.build` on its own inputs at coe = rf_eff + loading x erp. The
    value per share and the share count are chosen so the market is cheap at low premiums and dear at high ones."""
    import random
    rng = random.Random(seed)
    names = []
    for i in range(n):
        oe = rng.uniform(0.2, 8.0) * B
        names.append({"ticker": f"S{i:04d}", "oe": oe, "loading": rng.uniform(0.6, 1.4), "g": rng.uniform(0.03, 0.12),
                      "shares": rng.uniform(40e6, 900e6), "cap": oe * rng.uniform(9.0, 30.0)})
    return names


def _est(g):
    return {"0y": {"revenue": {"avg": 10.0 * B * (1 + g), "analysts": 9, "growth": g, "year_ago": 10.0 * B},
                   "eps": {"avg": 1.0 * (1 + g), "analysts": 9, "growth": g, "year_ago": 1.0}},
            "+1y": {"revenue": {"avg": 10.0 * B * (1 + g) ** 2, "analysts": 9, "growth": g},
                    "eps": {"avg": 1.0 * (1 + g) ** 2, "analysts": 9, "growth": g}}}


def _value_at_factory(names, rf_eff=0.05, tg=0.0375):
    by = {n["ticker"]: n for n in names}

    def value_at(t, est, erp):
        n = by[t]
        coe = rf_eff + n["loading"] * erp
        out = cr.build(n["oe"], est, coe, tg, n["shares"], 0.05, record={"R_tc": math.inf, "ronic_t": math.inf, "stamps": []},
                       base_ni=n["oe"], base_revenue=10.0 * B, stub_months=6.0)
        return out["value"], n["shares"]
    return value_at


def test_the_identity_holds_on_a_synthetic_aggregate_at_the_solved_premium_and_members_are_fixed():
    names = _synthetic_names()
    est = {n["ticker"]: _est(n["g"]) for n in names}
    value_at = _value_at_factory(names)
    constituents = [{"ticker": n["ticker"], "market_cap": n["cap"]} for n in names]
    members, counts = rc.select_members(constituents, est.get, mri_erp=0.045, value_at=value_at)
    assert len(members) == len(names) and sum(counts.values()) == 0
    # the target is calibrated so a root exists inside the bounds: the cap of the market is the value at a known premium
    truth = 0.062
    for m, n in zip(members, names):
        m["cap"] = value_at(n["ticker"], est[n["ticker"]], truth)[0] * n["shares"]
    sol = rc.solve_closure(members, value_at)
    assert sol["flag"] is None and sol["erp"] == pytest.approx(truth, abs=1e-6)
    assert sol["gap"] <= 1e-6                                           # AT2: |sum V x shares - sum cap| / sum cap
    assert sol["sum_cap"] == pytest.approx(sum(m["cap"] for m in members))
    # a market priced far above any value the reference gives hits the low bound and says so
    for m in members:
        m["cap"] *= 100.0
    assert rc.solve_closure(members, value_at)["flag"] == "bound_low"


def test_members_are_the_names_with_estimates_a_share_count_and_a_positive_value_at_mris_premium():
    names = _synthetic_names(6)
    est = {n["ticker"]: _est(0.05) for n in names}
    est[names[1]["ticker"]] = None                                         # no consensus
    value_at_ok = _value_at_factory(names)

    def value_at(t, e, erp):
        if t == names[2]["ticker"]:
            return None, names[2]["shares"]                                # no value (a build that returned none)
        if t == names[3]["ticker"]:
            return -1.0, names[3]["shares"]                                # a value that is not positive
        if t == names[4]["ticker"]:
            return 10.0, None                                              # no share count
        return value_at_ok(t, e, erp)
    constituents = [{"ticker": n["ticker"], "market_cap": n["cap"]} for n in names]
    members, counts = rc.select_members(constituents, est.get, 0.045, value_at)
    assert [m["ticker"] for m in members] == [names[0]["ticker"], names[5]["ticker"]]
    assert counts == {"no_consensus_estimates": 1, "no_share_count": 1, "no_value_at_mri_premium": 1,
                      "value_not_positive_at_mri_premium": 1}


# ---- the aggregate: MRI's rules and amendment A1 ------------------------------------------------------------------------

class _Root(cap.DataRoot):
    """A DataRoot over written-down companies: {ticker: (financials dict, history rows, cik)}."""

    def __init__(self, companies):
        super().__init__(sd=Path("."))
        self.companies = companies
        self._cik = {t: c[2] for t, c in companies.items()}

    def financial_tickers(self):
        return sorted(self.companies)

    def fin(self, t):
        return self.companies[t][0]

    def history(self, t):
        return self.companies[t][1]


def _rows(oe=100.0, shares=1e6, years=range(2020, 2026), rev=1000.0, g=0.05):
    return {str(y): {"revenue": rev * (1 + g) ** (y - 2020), "net_income": oe, "da": 0.0, "capex": 0.0, "shares_diluted": shares}
            for y in years}


def test_the_aggregate_follows_mris_rules_and_excludes_a_share_count_scale_gap():
    companies = {
        "AAA": ({"Market_Cap": 5e9, "FX": None, "Shares_Outstanding": 1e6}, _rows(), "1"),            # a constituent
        "AAB": ({"Market_Cap": 4e9, "FX": None, "Shares_Outstanding": 1e6}, _rows(), "1"),            # same company, smaller class
        "BBB": ({"Market_Cap": 3e9, "FX": "EUR", "Shares_Outstanding": 1e6}, _rows(), "2"),           # non-USD reporter
        "CCC": ({"Market_Cap": 2e9, "FX": None, "Shares_Outstanding": 1e6}, _rows(oe=-5.0), "3"),     # owner earnings not positive
        "DDD": ({"Market_Cap": 2e9, "FX": None, "Shares_Outstanding": 1e6}, _rows(years=range(2023, 2026)), "4"),   # growth undefined
        "EEE": ({"Market_Cap": 6e9, "FX": None, "Shares_Outstanding": 1e9}, _rows(), "5"),            # vendor 1000x the filed count (A1)
        "FFF": ({"Market_Cap": 6e9, "FX": None, "Shares_Outstanding": 1e4}, _rows(), "6"),            # vendor 1/100 of the filed count (A1)
        "GGG": ({"Market_Cap": 1e9, "FX": None, "Shares_Outstanding": 99e6}, _rows(), "7"),           # 99x: inside the band, kept
        "HHH": ({"Market_Cap": 0, "FX": None, "Shares_Outstanding": 1e6}, _rows(), "8"),              # no capitalisation
        "III": ({"Market_Cap": 2e9, "FX": None, "Shares_Outstanding": 2e6}, _rows(), "9"),            # a split after the last filing: 2x, kept
    }
    agg, stats = rc.build_aggregate(_Root(companies), cap)
    tickers = [c["ticker"] for c in agg["constituents"]]
    assert tickers == ["AAA", "III", "GGG"]                                   # largest class kept, ordered by capitalisation
    assert stats["excluded_non_usd_reporters"] == 1 and stats["excluded_share_count_scale_gap_A1"] == 2
    assert stats["share_classes_collapsed"] == 1 and stats["constituents"] == 3
    assert stats["lost_names"] == {"owner_earnings_missing": 0, "owner_earnings_not_positive": 1, "revenue_growth_missing": 1}
    c0 = agg["constituents"][0]
    assert c0["cash_flow"] == 100.0 and c0["cik"] == "1" and MIN_G <= c0["growth"] <= MAX_G
    assert not any(isinstance(v, list) and v and isinstance(v[0], str) for v in stats.values())     # counts only: no names


MIN_G, MAX_G = rc.MIN_GROWTH, rc.MAX_GROWTH


# ---- the accessor ------------------------------------------------------------------------------------------------------

_N = [0]


def _write(tmp_path, **doc):
    # a new file name each time: another test may have switched on common.enable_json_cache, which caches by path
    _N[0] += 1
    p = tmp_path / f"reference_closure_{_N[0]}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_the_accessor_returns_the_premium_its_date_and_the_artifact_and_never_a_substitute(tmp_path, monkeypatch):
    now = datetime(2026, 10, 1, 12, 0, 0)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(rs2_data, "datetime", _Frozen, raising=False)
    monkeypatch.setattr(rs2_data, "reference_closure", REAL_REFERENCE_CLOSURE)
    ok = _write(tmp_path, asof="2026-09-20", erp=0.0512, members=412, flag=None)
    erp, asof, prov = rs2_data.reference_closure(ok)
    assert erp == 0.0512 and asof == "2026-09-20" and prov["members"] == 412
    # exactly the staleness limit (config.json's anchor_max_age_days, 45) is usable; one day more is not
    assert rs2_data.CONFIG["anchor_max_age_days"] == 45
    assert rs2_data.reference_closure(_write(tmp_path, asof="2026-08-17", erp=0.05))[0] == 0.05          # 45 days
    erp, asof, why = rs2_data.reference_closure(_write(tmp_path, asof="2026-08-16", erp=0.05))             # 46 days
    assert erp is None and asof == "2026-08-16" and why.startswith("reference_closure_stale")
    # a future date, an unreadable date, a premium outside the solver's bounds or missing, no file, a malformed file
    assert rs2_data.reference_closure(_write(tmp_path, asof="2026-10-05", erp=0.05))[0] is None
    assert rs2_data.reference_closure(_write(tmp_path, asof="not a date", erp=0.05))[2] == "reference_closure_asof_unreadable"
    for bad in (0.0004, 0.21, None, "0.05", True):
        assert rs2_data.reference_closure(_write(tmp_path, asof="2026-09-20", erp=bad))[2] == "reference_closure_has_no_usable_erp"
    assert rs2_data.reference_closure(tmp_path / "missing.json")[0] is None
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert rs2_data.reference_closure(tmp_path / "bad.json")[2].startswith("no_reference_closure_artifact")
    # the bounds themselves are values
    assert rs2_data.reference_closure(_write(tmp_path, asof="2026-09-20", erp=0.0005))[0] == 0.0005
    assert rs2_data.reference_closure(_write(tmp_path, asof="2026-09-20", erp=0.20))[0] == 0.20


# ---- reference_inputs: the cost of equity and the single source -------------------------------------------------------------

def _anchors(rf=0.0501, ga=0.0375, be=0.0234, loading=0.9, sector="Industrials"):
    return {"rf": rf, "ga": ga, "breakeven": be, "loading": {sector: loading}}


def _inputs(monkeypatch, anchors, closure, printed=True):
    """reference_inputs for the synthetic pack's company, on an independent DataRoot (the files read again)."""
    holder = {}
    real = cap.reference_inputs

    def spy(*a, **k):
        holder["ri"] = real(*a, **k)
        return holder["ri"]
    monkeypatch.setattr(cap, "reference_inputs", spy)
    pack = _synthetic_pack(monkeypatch)
    return pack, holder["ri"]


def test_the_cost_of_equity_is_the_larger_of_rf_and_the_growth_anchor_plus_loading_times_the_closure_premium(screener_data_stub, monkeypatch):
    pack, _ = _inputs(monkeypatch, None, None)
    root = cap.DataRoot()
    est = EST
    sector = rs2_data.sector_lookup("GEV")[0]
    today = date(2026, 9, 27)
    base = dict(t="GEV", root=root, estimates=est, today=today)
    ri = cap.reference_inputs(anchors=_anchors(sector=sector), closure={"erp": 0.05}, printed=False, **base)
    assert ri["coe"] == pytest.approx(0.0501 + 0.9 * 0.05, abs=1e-15) and ri["loading"] == 0.9 and ri["coe_reason"] is None
    # the low-rate floor: a risk-free rate below the growth anchor is lifted to it (at today's rates this changes nothing)
    low = cap.reference_inputs(anchors=_anchors(rf=0.03, ga=0.0375, sector=sector), closure={"erp": 0.05}, printed=False, **base)
    assert low["coe"] == pytest.approx(0.0375 + 0.9 * 0.05, abs=1e-15)
    assert cap.reference_inputs(anchors=_anchors(rf=0.0375, ga=0.0375, sector=sector), closure={"erp": 0.05}, printed=False,
                                **base)["coe"] == pytest.approx(0.0375 + 0.045, abs=1e-15)
    # the pack quantizes it to the two decimals it prints; the closure's solve does not
    printed = cap.reference_inputs(anchors=_anchors(sector=sector), closure={"erp": 0.05123}, printed=True, **base)
    exact = cap.reference_inputs(anchors=_anchors(sector=sector), closure={"erp": 0.05123}, printed=False, **base)
    assert printed["coe"] == float(f"{exact['coe'] * 100:.2f}") / 100.0 and printed["coe"] != exact["coe"]
    # a premium of 0.0 is a number, not an absence: the cost of equity is rf_eff
    assert cap.reference_inputs(anchors=_anchors(sector=sector), closure={"erp": 0.0}, printed=False, **base)["coe"] == pytest.approx(0.0501)


def test_there_is_no_fallback_a_missing_premium_loading_or_rate_leaves_no_cost_of_equity_and_no_value(screener_data_stub, monkeypatch):
    _inputs(monkeypatch, None, None)
    root = cap.DataRoot()
    sector = rs2_data.sector_lookup("GEV")[0]
    base = dict(t="GEV", root=root, estimates=EST, today=date(2026, 9, 27), printed=True)
    cases = [dict(anchors=_anchors(sector=sector), closure=None), dict(anchors=_anchors(sector=sector), closure={}),
             dict(anchors=_anchors(sector=sector), closure={"erp": None}), dict(anchors=_anchors(rf=None, sector=sector), closure={"erp": 0.05}),
             dict(anchors=_anchors(ga=None, sector=sector), closure={"erp": 0.05}),
             dict(anchors={"rf": 0.05, "ga": 0.0375, "breakeven": 0.02, "loading": {}}, closure={"erp": 0.05})]
    for kw in cases:
        ri = cap.reference_inputs(**base, **kw)
        assert ri["coe"] is None and ri["coe_reason"] and ri["kwargs"]["coe"] is None
        out = cr.build(**ri["kwargs"])
        assert out["value"] is None and out["reason"].startswith("cost-of-equity anchor")


def test_the_pack_prints_the_closure_cost_of_equity_the_mri_premium_as_context_and_says_when_there_is_no_premium(screener_data_stub, monkeypatch):
    pack = _synthetic_pack(monkeypatch)
    text = str(pack)
    rates = next(l for l in text.splitlines() if l.startswith("- Rates:"))
    assert "MRI universe premium (context; not used in the reference)" in rates and "implied ERP" not in rates
    coe = next(l for l in text.splitlines() if l.startswith("- COE ANCHOR for this name:"))
    assert "(the larger of rf" in coe and "the market-consistent premium" in coe and "(rs2 closure, as of 2026-09-20)" in coe
    assert pack.facts["coe_anchor"] is not None
    # no closure artifact: no cost of equity, no reference, and the pack says why - never MRI's premium in its place
    monkeypatch.setattr(rs2_data, "reference_closure", lambda path=None: (None, None, "no_reference_closure_artifact(reference_closure.json)"))
    gone = _synthetic_pack(monkeypatch)
    gtext = str(gone)
    assert gone.facts["coe_anchor"] is None and gone.facts["reference_status"] == "not_available"
    coe = next(l for l in gtext.splitlines() if l.startswith("- COE ANCHOR for this name:"))
    assert coe.startswith("- COE ANCHOR for this name: not available — the closure premium is missing or stale (no_reference_closure_artifact")
    civ = next(l for l in gtext.splitlines() if "CONSENSUS-IMPLIED VALUE" in l)
    assert civ.startswith("- CONSENSUS-IMPLIED VALUE: not available — the closure premium is missing or stale")
    # a stale premium names its date
    monkeypatch.setattr(rs2_data, "reference_closure", lambda path=None: (None, "2026-07-01", "reference_closure_stale(2026-07-01, 88 days, limit 45)"))
    assert "missing or stale (2026-07-01)" in str(_synthetic_pack(monkeypatch))


def test_the_pack_reference_is_build_of_reference_inputs_on_an_independent_data_root_to_the_cent(screener_data_stub, monkeypatch):
    """The parity test of brief section 2: the pack's printed reference equals build(**reference_inputs(...)) - the inputs read
    again through a fresh DataRoot - and the facts the pack prints for the same inputs are reference_inputs' own."""
    calls = []
    real = cr.build
    monkeypatch.setattr(cr, "build", lambda *a, **k: (calls.append((a, k, real(*a, **k))), calls[-1][2])[1])
    pack = _synthetic_pack(monkeypatch)
    f = pack.facts
    pack_args, pack_kwargs, pack_out = calls[-1]
    assert not pack_args and f["reference_status"] == "used"
    sector = rs2_data.sector_lookup("GEV")[0]
    rf, ga, be = rs2_data.anchor_risk_free_rate()[0], rs2_data.anchor_terminal_g()[0], rs2_data.anchor_breakeven_10y()[0]
    adj = rs2_data.coe_loading(sector)[0]
    erp = rs2_data.reference_closure()[0]
    ri = cap.reference_inputs("GEV", cap.DataRoot(), EST, {"rf": rf, "ga": ga, "breakeven": be, "loading": {sector: adj}},
                              {"erp": erp}, printed=True, today=date(2026, 9, 27))
    again = real(**ri["kwargs"])
    assert abs(again["value"] - pack_out["value"]) < 1e-9 and round(again["value"], 2) == f["consensus_implied_value"]
    for key in ("coe", "shares", "terminal_g", "median_5y", "da", "capex", "stub_months", "base_label", "levels_block", "base_ni",
                "base_revenue", "anchor", "base_cf"):
        assert ri["kwargs"][key] == pack_kwargs[key], key
    assert ri["coe"] == f["coe_anchor"] and ri["shares_default"] == f["shares_default"] and ri["terminal_g"] == f["terminal_g_default"]
    assert pack_facts.q_b(again["base_cf"] / B) == f["reference_base_b"]
    cash = ri["cash"]
    assert (cash is not None and cash["applies"] and f["excess_cash"] == pack_facts.q_b(cash["cash"] / B)) or f["excess_cash"] is None


def test_the_closure_values_are_unquantized_and_move_smoothly_with_the_premium(screener_data_stub, monkeypatch):
    _inputs(monkeypatch, None, None)
    root = cap.DataRoot()
    sector = rs2_data.sector_lookup("GEV")[0]
    anchors = _anchors(sector=sector)
    vals = []
    for erp in (0.0500, 0.0501, 0.0502, 0.0503):
        v, _sh = rc.reference_value("GEV", root, cap, EST, anchors, erp, date(2026, 9, 27))
        vals.append(v)
    steps = [a - b for a, b in zip(vals, vals[1:])]
    assert all(s > 0 for s in steps) and max(steps) / min(steps) < 1.3         # strictly decreasing, no quantization plateaus


# ---- the consensus batch (offline here: enrich is stubbed, nothing touches the network or the repo's cache) -------------------

def test_the_batch_caches_each_name_resumes_retries_and_records_a_manifest(tmp_path, monkeypatch):
    import closure_enrich_batch as ceb
    monkeypatch.setattr(ceb, "HERE", tmp_path)
    monkeypatch.setattr(ceb.time, "sleep", lambda s: None)
    calls = {"RAISES": 0}

    def fake(t):
        if t == "RAISES":
            calls["RAISES"] += 1
            if calls["RAISES"] == 1:
                raise ConnectionError("transient")
        if t == "BROKEN":
            return {"_ticker": t, "estimates": None, "institutional_pct": None, "analyst_target_mean": None}
        if t == "NOCOVER":
            return {"_ticker": t, "estimates": None, "institutional_pct": 61.2, "analyst_target_mean": None}
        return {"_ticker": t, "estimates": {"0y": {}}, "institutional_pct": 70.0}
    monkeypatch.setattr(ceb.enrich_ticker, "enrich", fake)
    names = tmp_path / "names.txt"
    names.write_text("AAA\nRAISES\nBROKEN\nNOCOVER\nAAA\n", encoding="utf-8")
    d = tmp_path / "cache" / "closure_enrich" / "2026-10-01"
    d.mkdir(parents=True)
    (d / "ZZZ.json").write_text("{}", encoding="utf-8")                      # an earlier run's file is not overwritten
    names.write_text("AAA\nRAISES\nBROKEN\nNOCOVER\nZZZ\n", encoding="utf-8")
    ceb.main(["--names", str(names), "--date", "2026-10-01", "--workers", "1"])
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert man["tickers_requested"] == 5 and man["files"] == 5 and man["vintage"] == "2026-10-01"
    st = man["stats"]
    assert st["skipped_existing"] == 1 and st["fetched"] == 4 and st["retried"] == 1 and st["failed_after_retry"] == 0
    assert st["suspect_retried"] == 1 and st["estimates_null"] == 2           # the broken-session record and the uncovered name
    assert set(man["file_sha256"]) == {f"{t}.json" for t in ("AAA", "RAISES", "BROKEN", "NOCOVER", "ZZZ")}
    import hashlib
    assert man["manifest_sha256"] == hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(man["file_sha256"].items())).encode()).hexdigest()
    assert (d / "AAA.json").exists() and not (tmp_path / "enrich").exists()     # only the vintage directory is written

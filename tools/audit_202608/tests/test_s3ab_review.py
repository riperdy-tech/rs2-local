"""Reviewer's tests for the S3 packages A+B review (2026-09-28), one or more per defect fixed.

Desk (financial_model_tool):
 1. R1 reads the unrounded share count: the dcf echo is rounded to 4 decimals of a billion.
 2. R5 uses the harness's basis-point rounding (terminal_g_gap_bp: > 50); R6 (revision 17) measures terminal_ronic.
 3. An order violation (R12) is named in the refusal, which says no reason overrides it.
 4. Refusal texts carry the measured quantity, not a per-share value (R10(b), R13, R14).
 5. A missing harness price is never reported as 0.0.
 6. R1b fires from the context's shares_warning.
Harness (consensus_valuation):
 7. S2b's departure is measured against the share-count default when the facts carry one.
 8. The share ratios (shares_off_pack_without_reason, dilution_in_bear) are taken against the
    share-count default when the facts carry one, and SECTION 2's count otherwise.
 9. consensus.json records the facts version actually read.
Schema (analyst_tools):
10. cash_flow_life has one JSON type.
"""
import json
from pathlib import Path
import sys
import urllib.request

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import analyst_tools  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402


def _call(**over):
    sc = [
        {"name": "Base", "prob": 0.5, "base_cf": 1.0, "explicit_growth": [0.05] * 5, "wacc": 0.09, "terminal_g": 0.0375},
        {"name": "Bull", "prob": 0.3, "base_cf": 1.2, "explicit_growth": [0.08] * 5, "wacc": 0.09, "terminal_g": 0.0375},
        {"name": "Bear", "prob": 0.2, "base_cf": 0.8, "explicit_growth": [0.02] * 5, "wacc": 0.09, "terminal_g": 0.0375},
    ]
    p = {"scenarios": sc, "terminal_g": 0.0375, "fade_years": 5, "sbc_treatment": "deducted_in_cf",
         "valuation_frame": "equity", "rate_type": "cost_of_equity",
         "cash_flow_life": "perpetual", "cash_flow_life_reason": "perpetual franchise, 10-K 2025",
         "long_run_margin": 0.10}          # revision 24 step 2a: required; no long-run facts here, so the margin is held
    for k, v in over.items():
        if k.startswith("sc_"):
            for s in sc:
                s[k[3:]] = v
        else:
            p[k] = v
    return p


def _ctx(**over):
    c = {"price": 10.0, "shares_default_b": 1.0}
    c.update(over)
    return c


def _needs(res):
    return [n["reason"] for n in res.get("needs_reasons", [])]


# ---- desk -------------------------------------------------------------------------------------

def test_r1_small_count_uses_the_unrounded_input():
    # 1.51M shares against a 1.52M default: 0.7% apart. The dcf echo rounds both to 0.0015B.
    res = fmt.execute_financial_model(_call(shares_diluted=0.00151, sc_base_cf=0.001),
                                      _ctx(price=0.5, shares_default_b=0.00152))
    assert "shares_reason" not in _needs(res)
    res = fmt.execute_financial_model(_call(shares_diluted=0.0015, sc_base_cf=0.001),
                                      _ctx(price=0.5, shares_default_b=0.00152))
    assert "shares_reason" in _needs(res)          # 1.3% apart


def test_r5_uses_basis_point_rounding():
    ctx = _ctx(terminal_g_default=0.0375)
    ok = fmt.execute_financial_model(_call(sc_terminal_g=0.04255, terminal_g=0.04255), ctx)
    assert "terminal_reason" not in _needs(ok)      # 50.5 bp rounds to 50: not more than 50
    bad = fmt.execute_financial_model(_call(sc_terminal_g=0.0426, terminal_g=0.0426), ctx)
    assert "terminal_reason" in _needs(bad)         # 51 bp


def test_r6_terminal_ronic_is_measured_against_its_default_at_two_points():
    # revision 17: the exit-multiple form of R6 left with the exit multiple; R6 now measures the Base's
    # terminal_ronic against the DEFAULTS terminal_ronic, more than 2 points needing terminal_reason
    ctx = _ctx(terminal_ronic=0.10)
    ok = fmt.execute_financial_model(_call(sc_terminal_ronic=0.12), ctx)
    assert "terminal_reason" not in _needs(ok)        # 2.0 points: not more than 2
    bad = fmt.execute_financial_model(_call(sc_terminal_ronic=0.1205), ctx)
    assert "terminal_reason" in _needs(bad)           # 2.05 points


def test_r12_order_refusal_names_the_order():
    res = fmt.execute_financial_model(_call(), _ctx())
    assert res.get("validation_error") is None or "order" not in res
    swapped = _call()
    swapped["scenarios"][1]["base_cf"] = 0.5        # Bull below Base
    res = fmt.execute_financial_model(swapped, _ctx(price=1.0))
    assert res["validation_error"] is True and "order" in res
    assert "no reason overrides the order" in res["error"]


def test_reason_texts_carry_no_per_share_value():
    res = fmt.execute_financial_model(_call(), _ctx(price=1000.0))     # Bull far below the price
    why = next(n["why"] for n in res["needs_reasons"] if n["reason"] == "bull_below_price_reason")
    assert "% below today's price" in why
    assert "1000.00" not in why
    res = fmt.execute_financial_model(_call(), _ctx(price=0.001))      # Bear far above the price
    why = next(n["why"] for n in res["needs_reasons"] if n["reason"] == "bear_above_price_reason")
    assert "% above today's price" in why


def test_missing_price_is_never_zero():
    res = fmt.execute_financial_model({"mode": "blend", "legs": [{"name": "a", "weight": 1.0, "iv": 5.0}]}, {})
    assert res.get("price") is None


def test_r1b_fires_from_the_context_warning():
    res = fmt.execute_financial_model(_call(), _ctx(shares_warning="vendor count 30% from the EPS-implied count"))
    assert "shares_reason" in _needs(res)
    res = fmt.execute_financial_model(_call(shares_reason="10-Q cover page count"),
                                      _ctx(shares_warning="vendor count 30% from the EPS-implied count"))
    assert "shares_reason" not in _needs(res)


# ---- harness ----------------------------------------------------------------------------------

def _share_check(desk_b, facts, reason=None):
    snapshot = [{"tool": "run_financial_model",
                 "params": {"shares_diluted": desk_b, "base_cf": 1.0, "explicit_growth": [0.1],
                            "fade_years": 5, "wacc": 0.10},
                 "result": {"dcf_model": {"per_share_iv": 50.0}}}]
    sc = {"shares_reason": reason} if reason is not None else {}
    return cv.extract_desk_snapshot_metrics(snapshot=snapshot, base_iv=50.0, scorecard=sc, facts=facts)


EZPW = {"shares_outstanding": 61443377.0, "filed_shares_diluted": 83383000.0, "filed_shares_fy": 2025,
        "shares_default": 79364362.0}


def test_departure_is_measured_against_the_default():
    at_default = _share_check(0.079364362, EZPW, reason="default count, SECTION 2 x filed EPS dilution")
    assert at_default["desk_share_basis_matched"] == "default"
    assert "desk_share_count_departure_with_reason" not in at_default["desk_share_flags"]
    at_vendor = _share_check(0.061443377, EZPW, reason="SECTION 2 basic count")
    assert "desk_share_count_departure_with_reason" in at_vendor["desk_share_flags"]


def test_departure_without_a_default_is_measured_against_section_2():
    facts = dict(EZPW, shares_default=None)
    res = _share_check(0.061443377, facts, reason="SECTION 2 count")
    assert "desk_share_count_departure_with_reason" not in res["desk_share_flags"]


def _desk_snapshot(root, base_sh, bear_sh):
    d = root / "sample1_research"
    d.mkdir(parents=True)
    sc = [{"name": "Base", "prob": 0.5, "base_cf": 1.0, "explicit_growth": [0.05] * 5, "wacc": 0.09,
           "terminal_g": 0.0375, "shares_diluted": base_sh},
          {"name": "Bull", "prob": 0.3, "base_cf": 1.2, "explicit_growth": [0.08] * 5, "wacc": 0.09,
           "terminal_g": 0.0375, "shares_diluted": base_sh},
          {"name": "Bear", "prob": 0.2, "base_cf": 0.8, "explicit_growth": [0.02] * 5, "wacc": 0.09,
           "terminal_g": 0.0375, "shares_diluted": bear_sh}]
    res = {"scenario_dcfs": [{"name": s["name"], "dcf": {"per_share_iv": v, "terminal_g": 0.0375}}
                             for s, v in zip(sc, (10.0, 14.0, 6.0))]}
    (d / "_research_snapshot.json").write_text(json.dumps(
        {"calls": [{"tool": "run_financial_model", "params": {"scenarios": sc}, "result": res}]}), encoding="utf-8")
    return d


def test_dilution_in_bear_is_measured_against_the_default(tmp_path):
    card = {"base_iv": 10.0, "bull_iv": 14.0, "bear_iv": 6.0}
    facts = pack_facts.empty()
    facts["shares_outstanding"] = 1.0e9          # SECTION 2's basic count
    facts["shares_default"] = 1.3e9              # 5.11: basic x filed EPS dilution
    same = _desk_snapshot(tmp_path / "same", 1.3, 1.3)
    flags, _ = cv.scenario_checks(same, card, pack_text=None, price=8.0, facts=facts)
    assert "dilution_in_bear" not in flags and "shares_off_pack_without_reason" not in flags
    more = _desk_snapshot(tmp_path / "more", 1.3, 1.4)   # contingent shares added to the Bear
    flags, _ = cv.scenario_checks(more, card, pack_text=None, price=8.0, facts=facts)
    assert "dilution_in_bear" in flags


def test_without_a_default_the_reference_is_section_2(tmp_path):
    card = {"base_iv": 10.0, "bull_iv": 14.0, "bear_iv": 6.0}
    facts = pack_facts.empty()
    facts["shares_outstanding"] = 1.0e9
    same = _desk_snapshot(tmp_path / "same", 1.3, 1.3)
    flags, _ = cv.scenario_checks(same, card, pack_text=None, price=8.0, facts=facts)
    assert "dilution_in_bear" in flags               # revision-14 behaviour (AMD s3 warrant case)


# ---- consensus.json: the facts version read -----------------------------------------------------

MEMO = ("SECTION 0. EXECUTIVE VERDICT\n" + "\n".join(f"  detail line {n}." for n in range(400))
        + "\nSECTION 12. MACHINE CONTRACT\n```json:underwriting\n"
        '{"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0, "conviction_score": 10}\n```\n')


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False


def _run_main(monkeypatch, tmp_path, with_sidecar_version):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp(
        {"message": {"content": MEMO}, "done_reason": "stop", "eval_count": 5, "prompt_eval_count": 5}))
    frozen = tmp_path / f"frozen_{with_sidecar_version}"
    frozen.mkdir()
    pack = "- Shares outstanding: 500,000,000\n"
    (frozen / "_pack.md").write_text(pack, encoding="utf-8")
    if with_sidecar_version is not None:
        f = pack_facts.from_text(pack)
        f["version"] = with_sidecar_version
        for k in ("shares_default", "shares_warning"):
            f.pop(k, None)                            # an older sidecar lacks version-3 keys
        pack_facts.write_sidecar(frozen, f)
    out = tmp_path / f"out_{with_sidecar_version}"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
                                      "--no-early-stop", "--pack-file", str(frozen / "_pack.md"),
                                      "--out-dir", str(out)])
    cv.main()
    d = next(out.glob("GEV_*"))
    return json.loads((d / "consensus.json").read_text(encoding="utf-8"))


def test_facts_version_read_is_recorded(monkeypatch, tmp_path, screener_data_stub):
    doc = _run_main(monkeypatch, tmp_path, 2)
    assert doc["pack_facts_version"] == pack_facts.FACTS_VERSION and doc["pack_facts_version_read"] == 2
    doc = _run_main(monkeypatch, tmp_path, None)
    assert doc["pack_facts_source"] == "text" and doc["pack_facts_version_read"] is None


# ---- schema -------------------------------------------------------------------------------------

def test_cash_flow_life_has_one_json_type():
    desk = next(t for t in analyst_tools.TOOLS if t["function"]["name"] == "run_financial_model")
    assert desk["function"]["parameters"]["properties"]["cash_flow_life"]["type"] == "string"


# ---- fix-up review (2026-09-28): a blend is never the answer of a revision-15 run ----------------

def _r15_joint_call(idx, base_iv):
    return {"tool": "run_financial_model", "call_index": idx,
            "params": {"cash_flow_life": "perpetual", "cash_flow_life_reason": "10-K",
                       "scenarios": [{"name": n, "prob": p, "base_cf": 1.0} for n, p in
                                     (("Base", 0.5), ("Bull", 0.3), ("Bear", 0.2))]},
            "result": {"scenario_dcfs": [
                {"name": "Base", "dcf": {"per_share_iv": base_iv, "per_share_iv_gordon": base_iv, "terminal_leg": "gordon"}},
                {"name": "Bull", "dcf": {"per_share_iv": base_iv * 1.3, "per_share_iv_gordon": base_iv * 1.3, "terminal_leg": "gordon"}},
                {"name": "Bear", "dcf": {"per_share_iv": base_iv * 0.7, "per_share_iv_gordon": base_iv * 0.7, "terminal_leg": "gordon"}}],
                "kelly_sizing": {"quarter_kelly_pct": 5.0}}}


def test_blend_after_a_revision_15_joint_run_is_not_published():
    import contract_fill
    blend = {"tool": "run_financial_model", "call_index": 2,
             "params": {"mode": "blend", "legs": [{"name": "a", "weight": 0.5, "iv": 150.0},
                                                   {"name": "b", "weight": 0.5, "iv": 100.0}]},
             "result": {"mode": "blend", "blended_per_share_iv": 125.0, "per_share_iv": 125.0}}
    typed = {"base_iv": 125.0}             # a Base value the narrative fallback read from prose
    filled, prov = contract_fill.fill([_r15_joint_call(1, 120.0), blend], typed, {}, 100.0)
    assert prov["mode"] == "joint" and prov["blend"] is False
    assert filled["base_iv"] == 120.0


def test_blend_rule_unchanged_for_an_older_run():
    import contract_fill
    older = _r15_joint_call(1, 120.0)
    del older["params"]["cash_flow_life"]   # a revision-14 call
    blend = {"tool": "run_financial_model", "call_index": 2,
             "params": {"mode": "blend", "legs": [{"name": "a", "weight": 1.0, "iv": 125.0}]},
             "result": {"mode": "blend", "blended_per_share_iv": 125.0, "per_share_iv": 125.0}}
    filled, prov = contract_fill.fill([older, blend], {"base_iv": 125.0}, {}, 100.0)
    assert prov["blend"] is True and filled["base_iv"] == 125.0

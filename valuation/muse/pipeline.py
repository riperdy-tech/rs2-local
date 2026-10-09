"""pipeline.py - Muse pass 1 (price-blind), the engine, the price reveal, pass 2 (red team) and the final assembly for ONE company at ONE date
(SPEC_muse_passes sections 2-3). No GPU, no server and no model is started here: the model is whatever `client` is (a mock in the tests).

ORDER
  0  classify (valuation.classification); build the price-free discount rate (book D/E); run the engine on the PRIOR ALONE ("code only"): a refusal
     stops here, before any model call; the code-only distribution is the baseline Muse is compared with at gate 2.
  1  build the pack (pack_v2) and call P1..P4 (P3 only for the operating and commodity families), then P5. Nothing in these prompts can carry a price.
  2  per input, failed checks after the one retry make that input `unanchored` (the prior's P50, width wide, stamped). P5 failing for an input keeps
     that input's P1-P4 position (stamped) rather than discarding a position that passed its checks; P5 may rescue an input P1-P4 left unanchored.
  3  the engine on the Muse distributions (price-free pass-1 distribution).
  4  the price is revealed: reverse valuation (reverse.py) and the red-team call P6 (at most two calls: P6 may ask for sections F, Q or D once).
  5  redteam.decide on every input (revision rule), then the engine again with the price: the final distribution, Pr(IV > price), Pr(IV > 1.2 x price),
     Pr(IV < 0.8 x price), the terminal-value share, the model disagreement, the count of hard-evidence positions, the extraordinary flags.
A transport failure (no server, timeout) stops the run with status "model_unavailable"; it is never turned into prior values.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from valuation import classification as classification_mod
from valuation.common import CompanyPIT, DataNotPresent, build_state, terminal_growth_rate
from valuation.priors_interface import Priors

from . import checkers, prompting, redteam
from .checkers import Evidence, Issue, check_pass1, check_synthesis, changed_inputs, entry_has_hard_evidence
from .mapping import MusePriors, Position, per_share_summary, positioned_curves, run_engine, unanchored
from .pack_v2 import build_pack
from .reverse import pass1_point, point_value_per_share, reverse_valuation
from .runner import DEFAULT_MAX_TOKENS, DEFAULT_URL, MuseRunner, MuseTransportError
from .schema import BUILT_FAMILIES, PASS1_PROMPTS, askable_inputs


def price_collisions(text: str, price_info: Optional[Mapping]) -> List[str]:
    """Formatted price / market-cap strings found in `text` (a coincidence with filing text: the pack builder has no price). Recorded as stamps."""
    if not price_info:
        return []
    cands = set()
    p = price_info.get("price")
    if p is not None:
        cands |= {f"{p:.2f}", f"{p:,.2f}", str(p)}
    m = price_info.get("market_cap")
    if m is not None:
        cands |= {f"{m:,.0f}", f"{m:.0f}", f"{m / 1e6:,.1f}", f"{m / 1e9:,.2f}"}
    return sorted(c for c in cands if len(c) >= 5 and c in text)


def _slim(res: dict) -> dict:
    """An engine result without the per-year detail."""
    out = dict(res)
    if isinstance(out.get("at_median_inputs"), dict):
        out["at_median_inputs"] = {k: v for k, v in out["at_median_inputs"].items() if k != "years"}
    return out


def _resolve_pass1_entries(res, inputs, ev, prompt, family):
    """(entries, positions, pool additions, extras_ok): the per-input outcome of a P1..P4 call after its final answer."""
    entries: Dict[str, Optional[dict]] = {}
    positions: Dict[str, Position] = {}
    pool: List[tuple] = []
    obj = res.obj
    issues = check_pass1(prompt, obj, family, inputs, ev) if obj is not None else []
    bad = {i.input for i in issues if i.input}
    extras_ok = obj is not None and not [i for i in issues if not i.input]
    for n in inputs:
        e = (obj or {}).get("inputs", {}).get(n) if isinstance((obj or {}).get("inputs"), dict) else None
        if obj is None or n in bad or e is None or checkers.check_entry(n, e, ev):
            why = next((i.message for i in (res.issues if obj is None else issues) if i.input == n or obj is None), "no usable answer")
            entries[n], positions[n] = None, unanchored(why[:300], prompt)
        else:
            entries[n] = e
            positions[n] = Position(float(e["percentile"]), e["width"], "anchored", prompt, [], entry_has_hard_evidence(e, ev))
            pool += [(c["section"], c["quote"]) for c in e["citations"]]
    if obj is not None:
        for key in ("bull_case", "bear_case"):
            c = obj.get(key)
            if isinstance(c, dict) and checkers.check_citation(c.get("citation"), ev, key) is None:
                pool.append((c["citation"]["section"], c["citation"]["quote"]))
        for r in obj.get("risks") or []:
            if isinstance(r, dict) and checkers.check_citation(r.get("citation"), ev, "risk") is None:
                pool.append((r["citation"]["section"], r["citation"]["quote"]))
        ch = obj.get("character")
        if isinstance(ch, dict):
            for c in ch.get("citations") or []:
                if checkers.check_citation(c, ev, "character") is None:
                    pool.append((c["section"], c["quote"]))
    return entries, positions, pool, extras_ok


def run_company(*, pit: CompanyPIT, identity: Mapping, priors: Priors, disc_factory: Callable, client, run_dir,
                price_info: Optional[Mapping] = None, documents=None, quarters=None, cik: Optional[str] = None, n_draws: int = 2000,
                seed: int = 20261006, corr=None, model: str = "muse", max_tokens: int = DEFAULT_MAX_TOKENS, llm_seed: Optional[int] = None,
                base_url: str = DEFAULT_URL, industry_context: Optional[Mapping] = None) -> dict:
    """Value one company at pit.asof (see the module docstring). `disc_factory(state, de_ratio=None, de_basis="book") -> DiscountRate`.
    `price_info` = {"price": per share, "market_cap": ..., "currency": ...} is used only after pass 1; None stops after the price-free pass.
    `industry_context` = {"industry_roic": {"value", "n", "basis"}} (operating, commodity) or {"industry_rote": ...} (financial): the median return of the company's
    industry on the date's population (Addendum H3), which the priors and the engines read from the state; without it they refuse, naming it."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out: dict = {"ticker": pit.ticker, "asof": pit.asof.isoformat(), "stamps": [], "calls": []}

    def finish(status, **kw):
        out.update(status=status, **kw)
        (run_dir / "result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        return out

    st = build_state(pit)
    st.update(industry_context or {})
    cls = classification_mod.classification(pit.ticker, pit.asof, pit)
    out["classification"] = {k: cls.get(k) for k in ("family", "reason", "conflicts", "notes")}
    family = cls["family"]
    if family not in BUILT_FAMILIES:
        return finish("not_valued", reason=f"family {family!r}: {cls.get('reason')}")
    out["family"] = family
    ps = priors.for_company(family, st, pit.asof)
    out["placeholder_priors"] = bool(ps.placeholder)
    try:
        disc = disc_factory(st)
    except DataNotPresent as e:
        return finish("refused", reason=f"discount rate: {e}")
    shares = st.get("shares_outstanding")
    # 0: the engine on the prior alone
    res0 = run_engine(family, pit, MusePriors(ps, family, st, {}), disc, n_draws=n_draws, seed=seed, corr=corr, state=st)
    if res0.get("status") != "ok":
        return finish("engine_refused", reason=res0.get("reasons"), engine=res0)
    out["code_only"] = {"iv_per_share": per_share_summary(res0, shares), "result": _slim(res0)}
    # the pack
    pack = build_pack(pit, family, identity, ps, state=st, documents=documents, quarters=quarters, cik=cik)
    out["stamps"] += pack.manifest["stamps"]
    (run_dir / "pack.json").write_text(json.dumps({"header": pack.header, "sections": pack.sections, "r": pack.r, "manifest": pack.manifest,
                                                   "provenance": pack.provenance}, indent=1, default=str), encoding="utf-8")
    runner = MuseRunner(client, run_dir, model=model, max_tokens=max_tokens, seed=llm_seed, base_url=base_url)
    runner.write_manifest({"ticker": pit.ticker, "asof": pit.asof.isoformat(), "family": family, "pack_manifest": pack.manifest,
                           "disc": disc.as_dict()})
    names = askable_inputs(family, ps, st)
    positions: Dict[str, Position] = {}
    entries: Dict[str, Optional[dict]] = {}
    pool: List[tuple] = []
    blocks: List[str] = []
    try:
        # 1-2: pass 1
        for prompt in PASS1_PROMPTS:
            rd = prompting.render_pass1(prompt, pack, family)
            if rd is None:
                continue
            for s in price_collisions(rd.user, price_info):
                out["stamps"].append(f"price_string_collision in {prompt}: {s!r} appears in filing text shown to the model")
            ev = Evidence(rd.sections)
            res = runner.call(prompt, rd.user, lambda o, p=prompt, r=rd, e=ev: check_pass1(p, o, family, r.inputs, e), schema=rd.schema)
            ent, pos, pl, extras_ok = _resolve_pass1_entries(res, rd.inputs, ev, prompt, family)
            entries.update(ent)
            positions.update(pos)
            pool += pl
            blocks.append(prompting.format_pass1(prompt, family, res.obj, ent))
            out["calls"].append({"call": prompt, "ok": res.ok, "retried": res.retried, "extras_ok": extras_ok,
                                 "issues": [i.as_dict() for i in res.issues]})
        # P5
        pass1_pos = {n: p.as_dict() for n, p in positions.items()}
        if any(p.status == "anchored" for p in positions.values()):
            rd5 = prompting.render_p5(pack, family, list(positions), blocks)
            for s in price_collisions(rd5.user, price_info):
                out["stamps"].append(f"price_string_collision in P5: {s!r}")
            ev5 = Evidence(rd5.sections, pool)

            def v5(o):
                iss = check_synthesis(o, list(positions), ev5)
                if not iss and isinstance(o.get("inputs"), dict):
                    final = {n: o["inputs"][n] for n in positions}
                    listed = {c.get("input") for c in o.get("changes") or [] if isinstance(c, dict)}
                    for n in changed_inputs(final, pass1_pos):
                        if n not in listed:
                            iss.append(Issue("schema", f"input {n} differs from the earlier analyses but has no entry in changes", n))
                return iss
            res5 = runner.call("P5", rd5.user, v5, schema=rd5.schema)
            out["calls"].append({"call": "P5", "ok": res5.ok, "retried": res5.retried, "issues": [i.as_dict() for i in res5.issues]})
            if res5.obj is not None and isinstance(res5.obj.get("inputs"), dict):
                iss5 = check_synthesis(res5.obj, list(positions), ev5)
                bad5 = {i.input for i in iss5 if i.input}
                for n in list(positions):
                    e = res5.obj["inputs"].get(n)
                    if e is None or n in bad5 or checkers.check_entry(n, e, ev5):
                        if positions[n].status == "anchored":
                            positions[n].stamps.append("synthesis_check_failed: the P1-P4 position stands")
                        continue
                    positions[n] = Position(float(e["percentile"]), e["width"], "anchored", "P5", [], entry_has_hard_evidence(e, ev5))
                    entries[n] = e
                    pool += [(c["section"], c["quote"]) for c in e["citations"]]
            else:
                for p in positions.values():
                    if p.status == "anchored":
                        p.stamps.append("synthesis_failed: the P1-P4 positions stand")
        else:
            out["stamps"].append("P5 not run: no input was anchored in P1-P4")
        out["pass1"] = {"positions": {n: p.as_dict() for n, p in positions.items()}}
        # 3: the price-free engine run on Muse's distributions
        mp1 = MusePriors(ps, family, st, positions)
        res1 = run_engine(family, pit, mp1, disc, n_draws=n_draws, seed=seed, corr=corr, state=st)
        out["pass1"].update(iv_per_share=per_share_summary(res1, shares), result=_slim(res1), muse_stamps=mp1.stamps())
        if price_info is None:
            return finish("pass1_only")
        # 4: the price
        price = float(price_info["price"])
        rev = reverse_valuation(ps, family, st, positions, disc, price, shares)
        out["reverse"] = rev
        review = []
        for n in positions:
            review.append({"name": n, "entry": entries.get(n), "required": rev["inputs"].get(n, {"status": "not_available",
                                                                                                "reason": rev.get("reason", "no reverse valuation")})})
        rd1 = prompting.render_p6(pack, family, list(positions), price_info, review, round_no=1)
        ev1 = Evidence(rd1.sections, pool)
        input_names = list(positions)

        def v6(o, ev, allow_request):
            if "request_sections" in o and "inputs" not in o:
                if not allow_request:
                    return [Issue("schema", "no further requests: answer with the inputs object")]
                rq = o["request_sections"]
                if not isinstance(rq, list) or not rq or any(x not in ("F", "Q", "D") or x not in pack.sections for x in rq):
                    return [Issue("schema", "request_sections must list sections that exist among F, Q, D")]
                return []
            return redteam.validate_p6(o, input_names, ev, entries)
        res6 = runner.call("P6", rd1.user, lambda o: v6(o, ev1, True), schema=rd1.schema)
        ev6, rd6 = ev1, rd1
        if res6.ok and "request_sections" in res6.obj and "inputs" not in res6.obj:
            rd6 = prompting.render_p6(pack, family, input_names, price_info, review, round_no=2, extra_sections=res6.obj["request_sections"])
            ev6 = Evidence(rd6.sections, pool)
            res6 = runner.call("P6_round2", rd6.user, lambda o: v6(o, ev6, False), schema=rd6.schema)
        out["calls"].append({"call": "P6", "ok": res6.ok, "retried": res6.retried, "issues": [i.as_dict() for i in res6.issues]})
        # 5: the revision rule
        seen = redteam.pass1_quote_set(list(entries.values()))
        p6_inputs = res6.obj.get("inputs") if (res6.obj is not None and isinstance(res6.obj.get("inputs"), dict)) else None
        p6_issues = redteam.validate_p6(res6.obj, input_names, ev6, entries) if p6_inputs is not None else []
        bad6 = {i.input for i in p6_issues if i.input}
        decisions = []
        for n in input_names:
            e = p6_inputs.get(n) if p6_inputs is not None else None
            if e is not None and n in bad6 and e.get("decision") == "revise":
                d = {"input": n, "proposed": True, "accepted": False, "reason": "refused: the revised entry failed the code checks twice; the pass-1 "
                     "position stands", "toward_price": None, "new_quote": False, "named_error": False, "pass1": positions[n].as_dict(),
                     "position": positions[n]}
            elif e is None:
                d = {"input": n, "proposed": False, "accepted": False, "reason": "no usable P6 answer: the pass-1 position stands",
                     "toward_price": None, "new_quote": False, "named_error": False, "pass1": positions[n].as_dict(), "position": positions[n]}
            else:
                d = redteam.decide(n, positions[n], entries.get(n), e, rev["inputs"].get(n), ev6, seen)
            d["asof"] = pit.asof.isoformat()
            decisions.append(d)
        final_pos = {d["input"]: d["position"] for d in decisions}
        out["redteam"] = {"decisions": [{k: (v.as_dict() if isinstance(v, Position) else v) for k, v in d.items()} for d in decisions],
                          "anchoring": redteam.anchoring_metric(decisions)}
        mp2 = MusePriors(ps, family, st, final_pos)
        res2 = run_engine(family, pit, mp2, disc, n_draws=n_draws, seed=seed, corr=corr, price_per_share=price, state=st)
        dist = res2.get("distribution") or {}
        out["final"] = {"positions": {n: p.as_dict() for n, p in final_pos.items()}, "iv_per_share": per_share_summary(res2, shares),
                        "prob_iv_above_price": dist.get("prob_value_above_price"), "prob_iv_above_1.2x_price": dist.get("prob_value_above_1.2x_price"),
                        "prob_iv_below_0.8x_price": dist.get("prob_value_below_0.8x_price"),
                        "tv_share_p50": (dist.get("tv_share") or {}).get("p50"), "model_disagreement": res2.get("model_disagreement"),
                        "model_disagreement_note": res2.get("model_disagreement_note"),
                        "n_hard_evidence_positions": sum(1 for p in final_pos.values() if p.hard_evidence),
                        "extraordinary_flags": rev.get("extraordinary_inputs", []),
                        "unanchored_inputs": sorted(n for n, p in final_pos.items() if p.status == "unanchored"),
                        "placeholder": bool(res2.get("placeholder")), "result": _slim(res2), "muse_stamps": mp2.stamps()}
        # the market-D/E sensitivity of the discount rate (Addendum B 3): the same median inputs under the market D/E
        mc, debt = price_info.get("market_cap"), st.get("debt_incl_finance_leases")
        if mc and debt is not None and mc > 0:
            try:
                disc_m = disc_factory(st, de_ratio=debt / mc, de_basis="market")
                point, q = pass1_point(ps, family, st, final_pos, g_terminal=terminal_growth_rate(disc.rf))
                curves, _nc, _s = positioned_curves(ps, family, st, q)
                out["final"]["market_de_sensitivity"] = {
                    "book_de": disc.de_ratio, "market_de": disc_m.de_ratio, "wacc_book": disc.wacc, "wacc_market": disc_m.wacc, "coe_book": disc.coe,
                    "coe_market": disc_m.coe, "iv_at_median_inputs_book": point_value_per_share(family, st, point, curves, disc, shares),
                    "iv_at_median_inputs_market": point_value_per_share(family, st, point, curves, disc_m, shares)}
            except DataNotPresent as e:
                out["final"]["market_de_sensitivity"] = {"not_available": str(e)}
        return finish("ok")
    except MuseTransportError as e:
        return finish("model_unavailable", reason=str(e))

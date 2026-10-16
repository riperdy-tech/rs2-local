"""contract_fill.py — Code-fills the Section 12 underwriting contract from the calculator record.

Given the calculator calls of one sample, its typed contract, the pack facts and price,
returns the values code writes into the contract and the provenance of each.
"""
import crux_check
from fiduciary_gate import payoff_skew, plausibility_gate
from financial_model_tool import _normalize_cash_flow_life

# S3 3.3: the 11 reason arguments (cash_flow_life_reason counted among them); revision 18 adds excess_cash_reason (the name
# stays REASONS_11 for its callers: it is the tuple of every reason argument).
REASONS_11 = (
    "cash_flow_life_reason", "base_cf_reason", "guidance_deviation_reason", "scenario_deviation_reason",
    "terminal_reason", "coe_adjustment_reason", "shares_reason", "net_debt_reason", "wacc_reason",
    "bull_below_price_reason", "bear_above_price_reason", "excess_cash_reason",
)
# revision 19: the label's revision-18 direction and the crux behind it, each with its owner here so none is dropped: direction_m the label before the
# crux (stamped on every sample), crux the answer call's argument, crux_check crux_check.check's record with the label's stamps, price_implied the
# answer call's block
REVISION_19 = ("direction_m", "crux", "crux_check", "price_implied")
# revision 24 step 2b: the Base's long_run_margin (the analyst's long-run input, on the verdict row) and the plausibility gate's record on the answer
# run (fiduciary_gate.plausibility_gate; None for a pack that printed long-run defaults, the rev22 arm)
REVISION_24_2B = ("long_run_margin", "plausibility_gate", "rev22_control_desk")
# revision 24 step 2d (cross-check 19, ruling 6): two diagnostics of the answer run's Base, never gates - the terminal value's share of the value
# and the terminal reinvestment rate (terminal_g / terminal_ronic, 0 when unlimited), from the desk's `implied` block
REVISION_24_2D = ("terminal_value_share", "terminal_reinvestment_rate")
# revision 25 (Stage 0.3, desk schema 25.1; SPEC_rev25_normalization_bridge.md sections 3, 6 and 8): the Base's bridge table (`dcf["bridge"]`), the
# checks of the three scenarios by role, the schema, and the two S12 figures that are derived, not typed: near_term_earnings = E_1 and
# normalized_earnings = N_0, both $B on the X basis, from the Base's bridge. Filled (and listed as unfilled) only for a pack whose facts carry
# desk_schema 25.1; every other arm's fill is as it was.
# Stage 0.5 (SPEC v1.2): the Base's class_checks (K1-K4) and the three classification labels, which the desk call owns under 25.1 (the *_evidence
# fields stay typed in the contract)
CLASS_LABELS_25 = ("growth_trajectory", "cycle_position", "margin_persistence")
REVISION_25 = ("bridge", "bridge_checks", "desk_schema", "near_term_earnings", "normalized_earnings", "class_checks") + CLASS_LABELS_25
DESK_SCHEMA_25 = "25.1"

FILLED = (
    "base_iv", "bull_iv", "bear_iv", "base_probability", "bull_probability", "bear_probability",
    "kelly_fraction_pct", "asymmetric_payoff_skew", "base_cf_used", "stage1_growth_path", "fade_years",
    "coe_used", "coe_source", "valuation_frame", "terminal_method", "terminal_multiple_or_g",
    "cash_flow_life", "shares_basis", "verdict_label",
    # S3 3.8: revision-15 additions. base_cf_basis is derived; interest_addback and the 11 reasons
    # (cash_flow_life_reason among them) are now call arguments, copied from the answer call.
    "base_cf_basis", "interest_addback",
) + REASONS_11 + REVISION_19 + REVISION_24_2B + REVISION_24_2D
FILLED_25 = FILLED + REVISION_25          # the fields a pack with desk schema 25.1 is filled with (FILLED itself is every other pack's, as it was)
ROLES = ("base", "bull", "bear")
REL = 0.010001          # the harness's 1% desk-match tolerance (consensus_valuation, `close`)


def _reason_given(v):
    """S3 3.3: a reason counts as not given when it is absent, empty, or reads "null"/"none"
    (case-insensitive, after stripping)."""
    if v is None:
        return False
    s = str(v).strip()
    return s != "" and s.lower() not in ("null", "none")


def s2b_share_match(desk_count, facts):
    """(name, ratio) — the candidate (vendor, filed_fy_wa or, from S3 5.11, default) nearest
    desk_count, matched when the ratio is at most 1%; else (None, nearest_ratio) when there is a
    nearest candidate, else (None, None). Shared by consensus_valuation's S2b share check and the
    revision-15 shares_basis (3.5's "S2b's share check in revision 15"), so there is one copy of
    the candidate list. desk_count is in billions, the unit of the candidates: a count the model
    sent is converted with financial_model_tool._to_b before it is passed."""
    facts = facts or {}
    if desk_count is None or desk_count <= 0:
        return None, None
    candidates = []
    n_val = facts.get("shares_outstanding")
    if isinstance(n_val, (int, float)) and n_val > 0:
        candidates.append(("vendor", n_val / 1e9))
    filed_val = facts.get("filed_shares_diluted")
    if (isinstance(n_val, (int, float)) and n_val > 0
            and isinstance(filed_val, (int, float)) and filed_val > 0):
        fy_vendor_ratio = filed_val / n_val
        if 0.55 < fy_vendor_ratio < 1.8:
            candidates.append(("filed_fy_wa", filed_val / 1e9))
    default_val = facts.get("shares_default")
    if isinstance(default_val, (int, float)) and default_val > 0:
        candidates.append(("default", default_val / 1e9))
    if not candidates:
        return None, None
    ratios = []
    for name, val in candidates:
        r = max(desk_count, val) / min(desk_count, val)
        ratios.append((name, val, r))
    ratios.sort(key=lambda x: x[2])
    nearest_name, _nearest_val, nearest_ratio = ratios[0]
    if nearest_ratio <= 1.010001:
        return nearest_name, nearest_ratio
    return None, nearest_ratio


def role_of(name):
    """The desk's own rule (financial_model_tool.execute_financial_model, is_base)."""
    n = str(name or "").lower()
    return "bull" if "bull" in n else "bear" if "bear" in n else "base"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _close(a, b):
    a, b = _f(a), _f(b)
    return a is not None and b is not None and b > 0 and abs(a - b) / b <= REL


def completed(call):
    """A desk run that counts. Revision 24 (R24.2): a stage-B run the guardrails rejected (`reference_revision_rejected`, its reason) does not:
    stage A's answer run stays the final run."""
    return (isinstance(call, dict) and call.get("tool") == "run_financial_model"
            and not call.get("error") and not call.get("validation_error") and not call.get("reference_revision_rejected"))


def _body(call):
    return call.get("result") if isinstance(call.get("result"), dict) else call


def entries(call):
    """[{role, name, dcf, param}] for a completed call: its scenario_dcfs, or its single top-level
    dcf_model (role base) when it has no scenarios."""
    body, params = _body(call), call.get("params") or {}
    p_scs = [s for s in (params.get("scenarios") or []) if isinstance(s, dict)]
    out = []
    for sc in body.get("scenario_dcfs") or []:
        if not isinstance(sc, dict):
            continue
        d = sc.get("dcf") or {}
        if not isinstance(d, dict) or d.get("error") or d.get("per_share_iv") is None:
            continue
        p = next((s for s in p_scs if s.get("name") == sc.get("name")), {})
        out.append({"role": role_of(sc.get("name")), "name": sc.get("name"), "dcf": d, "param": p})
    if not out and isinstance(body.get("dcf_model"), dict) and body["dcf_model"].get("per_share_iv") is not None:
        out.append({"role": "base", "name": "top-level", "dcf": body["dcf_model"], "param": {}})
    return out


def _legs(d):
    legs = {}
    if d.get("finite_life_years") is not None:
        legs["finite"] = _f(d.get("per_share_iv"))
        return legs
    if d.get("per_share_iv_exit") is not None:
        legs["exit"] = _f(d.get("per_share_iv_exit"))
    if d.get("per_share_iv_gordon") is not None:
        legs["gordon"] = _f(d.get("per_share_iv_gordon"))
    if not legs:
        legs["gordon"] = _f(d.get("per_share_iv"))
    return legs


def pick_leg(d, typed):
    """(leg, value): among the legs the desk computed for THIS scenario, the one nearest the typed
    value when at least one lies within 1% of it; otherwise the desk's primary leg (exit when an exit
    multiple was passed, else Gordon; a finite-life run has one leg). Step 2 only: the typed value
    selects a desk leg, it never supplies a value."""
    legs = _legs(d)
    primary = "finite" if "finite" in legs else ("exit" if "exit" in legs else "gordon")
    if typed is not None:
        near = [(abs(v - typed), k) for k, v in legs.items() if v is not None and _close(typed, v)]
        if near:
            k = min(near)[1]
            return k, legs[k]
    return primary, legs[primary]


def _inp(entry, call, key):
    p, top = entry["param"], call.get("params") or {}
    return p.get(key) if p.get(key) is not None else top.get(key)


def label(base, price):
    if base is None or not price:
        return None
    m = base / price - 1
    return "undervalued" if m >= 0.10 else "overvalued" if m <= -0.10 else "hold"


def answer_run(calls):
    """(call, base_iv, is_r15) of the answer run, by the rule `fill` applies: the last completed call that values Base, Bull and Bear together; with
    none, the last completed call that values a Base. The Base is that call's own per-share value (the revision-15 path); (None, None, False) when
    no completed call values a Base. Revision 21: the crux follow-up reads the answer run before the sample ends, through this one function."""
    done = [c for c in (calls or []) if completed(c)]
    ref = None
    for c in reversed(done):
        if {"base", "bull", "bear"} <= {e["role"] for e in entries(c)}:
            ref = c
            break
    if ref is None:
        ref = next((c for c in reversed(done) if any(e["role"] == "base" for e in entries(c))), None)
    if ref is None:
        return None, None, False
    e = next((x for x in entries(ref) if x["role"] == "base"), None)
    return ref, (_f(e["dcf"].get("per_share_iv")) if e else None), "cash_flow_life" in (ref.get("params") or {})


def _fill_bridge(out, prov, src, typed):
    """Revision 25: the bridge fields from the desk's own results. The two S12 figures come from the Base's bridge when it applied; a value the
    analyst typed is ignored and the sample is stamped `s12_figure_derived_under_25_1` when it differs. A Base whose bridge did not apply (the desk
    kept revision 24's path, `bridge_not_applied:<reason>`) has nothing to derive them from: the typed figures stand, stamped
    `s12_figures_typed_bridge_not_applied`."""
    out["desk_schema"] = DESK_SCHEMA_25
    out["bridge_checks"] = {role: (((src[role][1].get("dcf") or {}).get("bridge") or {}).get("checks")) for role in ROLES if role in src}
    bridge = ((src["base"][1].get("dcf") or {}).get("bridge")) if "base" in src else None
    out["bridge"] = bridge
    out["class_checks"] = bridge.get("class_checks") if isinstance(bridge, dict) else None
    if not (isinstance(bridge, dict) and bridge.get("applied")):
        prov["stamps"].append("s12_figures_typed_bridge_not_applied")
        return
    E, n0 = bridge.get("earnings"), bridge.get("n0")
    # the Stage 0.3 audit: near_term_earnings stays a number (E_1, the type every reader of the field expects); E_2 is in the bridge table
    derived = {"near_term_earnings": _f(E[1]) if isinstance(E, list) and len(E) > 1 else None, "normalized_earnings": _f(n0)}
    out.update(derived)
    decl = bridge.get("declared") or {}
    for k in CLASS_LABELS_25:          # Stage 0.5: the labels come from the Base's desk declarations; a differing typed value is ignored and stamped
        v = decl.get(k)
        out[k] = v.strip().lower() if isinstance(v, str) else None
        t = (typed or {}).get(k)
        if t is not None and (str(t).strip().lower() != out[k]) and "classification_from_desk_under_25_1" not in prov["stamps"]:
            prov["stamps"].append("classification_from_desk_under_25_1")
    for k, v in derived.items():
        t = (typed or {}).get(k)
        if t is None or v is None:
            continue
        if isinstance(v, list):
            same = isinstance(t, list) and len(t) == len(v) and all(_close(a, b) for a, b in zip(t, v))
        else:
            same = _close(t, v)
        if not same:
            prov["stamps"].append("s12_figure_derived_under_25_1")
            break


def fill(calls, typed, facts, price, ticker=None, allow_blend=True, pack_text=None, company=None):
    """(filled, prov). `typed` is the sample's parsed contract (extract_scorecard); `facts` needs
    'shares_outstanding' (raw count or None) and 'coe_anchor' (fraction or None). `ticker` is only
    needed for a revision-15 answer run's base_cf_basis (3.8); omit it and that field falls back
    to "other" when the Base is not within 2% of the DEFAULTS owner earnings.

    `allow_blend` (S3 5.12): False for a revision-15 pack (`main()` reads the pack's own revision
    marker, `pack_facts.is_revision_15`) — no blend is ever published, even when the session has
    no joint or scenario-wise desk run at all (only blend calls), which `is_r15` below cannot
    detect on its own (a blend call's `entries()` carries no role, so `ref_call` stays None and
    `is_r15` stays False). Defaults to True, so an older pack keeps S2's blend rule (R6).

    Revision 19 (brief B6): `pack_text` (the pack the model read, frozen as _pack.md) and `company` (rs2_data.resolve_name) are what the crux check
    reads, with the sample's own `calls` (its fetched pages) and `ticker`. From the answer call (`ref_call`) the fill copies `crux` (its params) and
    `price_implied` (its result), runs crux_check.check, and sets `verdict_label` by crux_check.label19; `direction_m` (the revision-18 label) is
    stamped on every sample, and `crux_check` carries the validity record with the label's stamps."""
    typed = typed or {}
    facts = facts or {}
    done = [c for c in (calls or []) if completed(c)]
    joint = None
    for c in reversed(done):
        roles = {e["role"] for e in entries(c)}
        if {"base", "bull", "bear"} <= roles:
            joint = c
            break
    prov = {"mode": None, "answer_call_index": None, "legs": {}, "unfilled": [], "blend": False}
    src = {}
    if joint is not None:
        prov["mode"], prov["answer_call_index"] = "joint", joint.get("call_index")
        for e in entries(joint):
            src.setdefault(e["role"], (joint, e))
    elif done:
        prov["mode"] = "scenario_wise"
        for role in ROLES:
            for c in reversed(done):
                e = next((x for x in entries(c) if x["role"] == role), None)
                if e:
                    src[role] = (c, e)
                    break
    else:
        prov["mode"] = "no_desk_run"

    # S3 3.8: a call is a revision-15 call when its params carry "cash_flow_life". The answer run
    # (S2 R4) is unchanged: the reference call is `joint`, else (scenario-wise) the call that
    # supplied the Base.
    ref_call = joint if joint is not None else (src.get("base", (None, None))[0])
    is_r15 = ref_call is not None and "cash_flow_life" in (ref_call.get("params") or {})

    out = {}
    desk25 = facts.get("desk_schema") == DESK_SCHEMA_25
    if desk25:
        prov["stamps"] = []
    for role in ROLES:
        if role in src:
            c, e = src[role]
            if is_r15:
                # 3.8 "Leg (replaces S2 R5)": "finite_life" on the finite path, else "gordon". Revision 17: the
                # desk has one terminal (funded growth) and no terminal_leg, so a revision-15 path never reads
                # one. There is no typed value to consult.
                d = e["dcf"]
                leg = "finite_life" if d.get("finite_life_years") is not None else "gordon"
                v = _f(d.get("per_share_iv"))
            else:
                leg, v = pick_leg(e["dcf"], _f(typed.get(f"{role}_iv")))
            out[f"{role}_iv"] = v
            prov["legs"][role] = leg
            out[f"{role}_probability"] = _f(e["param"].get("prob"))
    # blend: the last completed call is a blend and the typed base matches its value. Never for a
    # revision-15 answer run (reviewer, S3 A+B fix-up review): the TASK says a blend is never the
    # answer, and a Base value the narrative fallback of extract_scorecard pulls from the memo's prose
    # must not let a blend of model-typed leg values become the published Base. S3 5.12: `not
    # is_r15` alone misses a session with only blend calls (is_r15 needs a real scenario entry to
    # detect), so `allow_blend` (set from the pack's own revision marker) is the real gate.
    if done and not is_r15 and allow_blend:
        last = done[-1]
        b = _body(last)
        bv = None
        if (last.get("params") or {}).get("mode") == "blend" or b.get("mode") == "blend":
            # S2 review carry-over: 0.0 is a value, never defaulted with `or`.
            blended = b.get("blended_per_share_iv")
            bv = _f(blended if blended is not None else b.get("per_share_iv"))
        elif isinstance(b.get("blend"), dict):
            bv = _f(b["blend"].get("blended_per_share_iv"))
        if bv and _close(typed.get("base_iv"), bv):
            out["base_iv"], prov["blend"] = bv, True
    if "base" in src:
        c, e = src["base"]
        d = e["dcf"]
        out["base_cf_used"] = _f(_inp(e, c, "base_cf"))
        # the desk's echo of what it applied; snapshots written before the desk echoed a value carry
        # only the input, which is what the desk applied (no cap existed then)
        g = d.get("explicit_growth")
        if not isinstance(g, list):
            g = _inp(e, c, "explicit_growth") or _inp(e, c, "growth_rates")
        out["stage1_growth_path"] = [float(x) for x in g] if isinstance(g, list) else None
        out["fade_years"] = d.get("fade_years") if d.get("fade_years") is not None else _inp(e, c, "fade_years")
        r = _f(d.get("discount_rate_applied"))
        if r is None:
            r = _f(_inp(e, c, "wacc"))
            if r is None:
                r = _f(_inp(e, c, "discount_rate"))
        out["coe_used"] = r
        lrm = _inp(e, c, "long_run_margin")                 # revision 24 step 2b: the scenario's own, else the call's
        out["long_run_margin"] = _f(lrm) if lrm is not None else None
        # revision 24 step 2c (ruling 10 of step 2b): the answer run's Base was valued by the rev22 control desk (the generator's margin path)
        out["rev22_control_desk"] = True if "margin_from_generator" in ((d.get("stamps") or []) if isinstance(d, dict) else []) else None
        imp = d.get("implied") if isinstance(d, dict) and isinstance(d.get("implied"), dict) else {}
        for k in REVISION_24_2D:                            # step 2d: the diagnostics as the desk computed them (None when it did not)
            out[k] = _f(imp.get(k))
        if desk25:
            _fill_bridge(out, prov, src, typed)
        fr = d.get("valuation_frame") or _inp(e, c, "valuation_frame")
        out["valuation_frame"] = str(fr).lower() if fr is not None else None
        leg = prov["legs"].get("base")
        if leg in ("finite", "finite_life"):
            out["terminal_method"], out["terminal_multiple_or_g"] = "finite_life", None
        elif leg == "exit":
            em = (d.get("exit_multiple_terminal") or {}).get("exit_multiple")
            if em is None:
                em = _inp(e, c, "terminal_exit_multiple")
            out["terminal_method"], out["terminal_multiple_or_g"] = "exit_multiple", _f(em)
        else:
            tg = d.get("terminal_g") if d.get("terminal_g") is not None else _inp(e, c, "terminal_g")
            out["terminal_method"], out["terminal_multiple_or_g"] = "gordon", _f(tg)
        if is_r15:
            # 3.8: copied from the answer call's top-level params, not re-derived from the dcf.
            cfl_param = (ref_call.get("params") or {}).get("cash_flow_life")
            out["cash_flow_life"] = _normalize_cash_flow_life(cfl_param) if cfl_param is not None else "perpetual"
        else:
            fly = d.get("finite_life_years") if d.get("finite_life_years") is not None else _inp(e, c, "finite_life_years")
            out["cash_flow_life"] = int(fly) if fly is not None else "perpetual"
        # discount-rate source against the printed anchor
        a = facts.get("coe_anchor")
        cu = out["coe_used"]
        if cu is None:
            out["coe_source"] = None
        elif a is None:
            out["coe_source"] = "own"
        else:
            gap = abs(cu - a)
            out["coe_source"] = "anchor" if gap <= 0.0005 else "anchor_adjusted" if gap <= 0.015 else "own"
    if prov["mode"] == "joint":
        ks = _body(joint).get("kelly_sizing")
        out["kelly_fraction_pct"] = _f(ks.get("quarter_kelly_pct")) if isinstance(ks, dict) else None
    elif prov["mode"] == "scenario_wise":
        out["kelly_fraction_pct"] = None
    # shares basis: every filled scenario at the pack's count (1%)
    sh = facts.get("shares_outstanding")
    if sh and src:
        pack_b = sh / 1e9 if abs(sh) > 1e6 else sh
        vals = []
        for role, (c, e) in src.items():
            v = _f(_inp(e, c, "shares_diluted"))
            if v is not None:
                vals.append(v / 1e9 if abs(v) > 1e6 else v)
        if vals:
            out["shares_basis"] = ("diluted" if all(abs(v / pack_b - 1) <= 0.01 for v in vals)
                                   else "diluted_plus_contingent")

    if is_r15:
        # 3.8 "shares_basis (replaces S2 R7's rule for revision-15 runs)".
        shares_default = facts.get("shares_default")
        if src and shares_default and shares_default > 0:
            default_b = shares_default / 1e9 if abs(shares_default) > 1e6 else shares_default
            vals = []
            for role, (c, e) in src.items():
                v = _f(_inp(e, c, "shares_diluted"))
                if v is not None:
                    vals.append(v / 1e9 if abs(v) > 1e6 else v)
            if vals and all(abs(v / default_b - 1) <= 0.01 for v in vals):
                out["shares_basis"] = "default"
            elif "base" in src:
                base_desk_shares = _f(src["base"][1]["dcf"].get("shares_diluted"))
                matched, _ratio = s2b_share_match(base_desk_shares, facts)
                out["shares_basis"] = matched if matched in ("vendor", "filed_fy_wa") else "other"
            else:
                out["shares_basis"] = "other"
        elif "base" in src:
            base_desk_shares = _f(src["base"][1]["dcf"].get("shares_diluted"))
            matched, _ratio = s2b_share_match(base_desk_shares, facts)
            out["shares_basis"] = matched if matched in ("vendor", "filed_fy_wa") else "other"

        # 3.8 "Copied fields": cash_flow_life_reason, interest_addback and the 11 reasons come
        # from the answer call's top-level params (scenario-wise: the call that supplied the
        # Base). A reason not given (3.3) is filled as None.
        ref_params = ref_call.get("params") or {}
        for reason_name in REASONS_11:
            v = ref_params.get(reason_name)
            out[reason_name] = v if _reason_given(v) else None
        out["interest_addback"] = _f(ref_params.get("interest_addback"))

        # 3.8 "base_cf_basis", in this order: within 2% of owner_earnings_default_b; else the
        # nearest of latest_fy / multi_year_avg / ttm_fcf within OWNER_CF_TOL_PCT; else "other".
        if "base" in src:
            base_cf_val = out.get("base_cf_used")
            oe_default = facts.get("owner_earnings_default_b")
            if base_cf_val is not None and oe_default and abs(base_cf_val - oe_default) / abs(oe_default) <= 0.02:
                out["base_cf_basis"] = "owner_earnings_default"
            elif ticker and base_cf_val is not None:
                import consensus_valuation as cv
                candidates = {}
                years = cv.owner_cf_by_year(ticker)
                if years:
                    latest = max(years)
                    candidates["latest_fy"] = years[latest]
                    candidates["multi_year_avg"] = sum(years.values()) / len(years)
                ttm = cv.ttm_fcf_by_ticker(ticker)
                if ttm is not None:
                    candidates["ttm_fcf"] = ttm
                best_name, best_dist = None, None
                for name, target in candidates.items():
                    if not target:
                        continue
                    dist = abs(base_cf_val - target) / abs(target)
                    if dist <= cv.OWNER_CF_TOL_PCT / 100.0 and (best_dist is None or dist < best_dist):
                        best_name, best_dist = name, dist
                out["base_cf_basis"] = best_name or "other"
            else:
                out["base_cf_basis"] = "other"

    base = out.get("base_iv") if "base_iv" in out else None
    if base is not None:
        # revision 19 (brief 1.4, B6): the label is the revision-18 direction when it is hold, or when it is directional and the answer call's crux is
        # valid on the pack and this sample's fetched pages; otherwise hold, stamped no_valid_crux. A sample whose answer run is a frozen older pack
        # gets the same rule: with no crux, a directional sample is hold.
        crux = (ref_call.get("params") or {}).get("crux") if ref_call is not None else None
        pi = _body(ref_call).get("price_implied") if ref_call is not None else None
        chk = crux_check.check(crux, pi, pack_text, calls, company, ticker, facts)
        lab, direction_m, stamps = crux_check.label19(base, price, chk)
        out["verdict_label"] = lab
        out["direction_m"] = direction_m
        out["crux"] = crux
        out["price_implied"] = pi
        out["crux_check"] = dict(chk, stamps=stamps)
        out["asymmetric_payoff_skew"] = payoff_skew(out.get("bull_iv"), out.get("bear_iv"), price)
        # revision 24 step 2b: the plausibility gate on the answer run's Base, when the pack printed no long-run default (the iii arms); the rev22
        # arm's control and an older pack are not gated (their briefing asked for no input rationale)
        # step 2c: the growth anchor the pack prints (terminal_g's outlier threshold) and the three classifications (ruling 18) reach the gate
        out["plausibility_gate"] = (plausibility_gate(src["base"][1]["dcf"] if "base" in src else None, facts.get("population_ranges"),
                                                      typed.get("input_rationale"), pack_text, calls, company, ticker,
                                                      growth_anchor=facts.get("terminal_g_anchor"),
                                                      classifications={k: (out[k] if k in out else typed.get(k)) for k in (
                                                          "margin_persistence", "cycle_position", "growth_trajectory")})
                                    if facts.get("long_run_defaults_withheld") is True else None)
    filled = {}
    for k in (FILLED_25 if desk25 else FILLED):
        if k in out:
            filled[k] = out[k]
        else:
            prov["unfilled"].append(k)
    return filled, prov


def _pct_scaled(a, b):
    """The harness's own percent rescaling (consensus_valuation._evaluate_contract_mismatches)."""
    if abs(a) > 1.0 and abs(b) <= 1.0:
        a /= 100.0
    elif abs(b) > 1.0 and abs(a) <= 1.0:
        b /= 100.0
    return a, b


def _norm_label(x):
    s = str(x).strip().lower()
    return "hold" if s == "fair" else s


def disagrees(typed, filled):
    """Sorted field names whose typed value is present and disagrees with the filled value beyond the
    harness's existing tolerances. A field the fill did not fill is never listed."""
    out = []
    for k, fv in filled.items():
        tv = (typed or {}).get(k)
        if tv is None or fv is None:
            continue
        if k in ("base_iv", "bull_iv", "bear_iv"):
            bad = not _close(tv, fv)
        elif k.endswith("_probability"):
            bad = _f(tv) is None or abs(_f(tv) - fv) > 0.005001
        elif k == "kelly_fraction_pct":
            bad = _f(tv) is None or abs(_f(tv) - fv) > 0.050001
        elif k == "asymmetric_payoff_skew":
            bad = _f(tv) is None or abs(_f(tv) - fv) > 0.100001
        elif k == "base_cf_used":
            bad = _f(tv) is None or (abs(_f(tv) - fv) / abs(fv) > 0.020001 if fv else abs(_f(tv)) > 1e-6)
        elif k == "stage1_growth_path":
            if not isinstance(tv, list) or len(tv) != len(fv):
                bad = True
            else:
                bad = False
                for a, b in zip(tv, fv):
                    a = _f(a)
                    if a is None:
                        bad = True
                        break
                    a, b = _pct_scaled(a, float(b))
                    if abs(a - b) > 0.010001:
                        bad = True
                        break
        elif k == "fade_years":
            try:
                bad = int(tv) != int(fv)
            except (TypeError, ValueError):
                bad = True
        elif k == "coe_used":
            if _f(tv) is None:
                bad = True
            else:
                a, b = _pct_scaled(_f(tv), fv)
                bad = abs(a - b) > 0.000501
        elif k == "terminal_multiple_or_g":
            bad = _f(tv) is None or not (abs(_f(tv) - fv) <= 0.02 * abs(fv) + 1e-12)
        elif k == "cash_flow_life":
            t = str(tv).strip().lower()
            bad = t != str(fv).strip().lower()
        elif k == "verdict_label":
            bad = _norm_label(tv) != _norm_label(fv)
        else:   # coe_source, valuation_frame, terminal_method, shares_basis
            bad = str(tv).strip().lower() != str(fv).strip().lower()
        if bad:
            out.append(k)
    return sorted(out)

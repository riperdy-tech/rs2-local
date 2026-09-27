"""contract_fill.py — Code-fills the Section 12 underwriting contract from the calculator record.

Given the calculator calls of one sample, its typed contract, the pack facts and price,
returns the values code writes into the contract and the provenance of each.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from fiduciary_gate import payoff_skew

FILLED = (
    "base_iv", "bull_iv", "bear_iv", "base_probability", "bull_probability", "bear_probability",
    "kelly_fraction_pct", "asymmetric_payoff_skew", "base_cf_used", "stage1_growth_path", "fade_years",
    "coe_used", "coe_source", "valuation_frame", "terminal_method", "terminal_multiple_or_g",
    "cash_flow_life", "shares_basis", "verdict_label"
)
ROLES = ("base", "bull", "bear")
REL = 0.010001          # the harness's 1% desk-match tolerance (consensus_valuation, `close`)


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
    return (isinstance(call, dict) and call.get("tool") == "run_financial_model"
            and not call.get("error") and not call.get("validation_error"))


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


def fill(calls, typed, facts, price):
    """(filled, prov). `typed` is the sample's parsed contract (extract_scorecard); `facts` needs
    'shares_outstanding' (raw count or None) and 'coe_anchor' (fraction or None)."""
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
    out = {}
    for role in ROLES:
        if role in src:
            c, e = src[role]
            leg, v = pick_leg(e["dcf"], _f(typed.get(f"{role}_iv")))
            out[f"{role}_iv"] = v
            prov["legs"][role] = leg
            out[f"{role}_probability"] = _f(e["param"].get("prob"))
    # blend: the last completed call is a blend and the typed base matches its value
    if done:
        last = done[-1]
        b = _body(last)
        bv = None
        if (last.get("params") or {}).get("mode") == "blend" or b.get("mode") == "blend":
            bv = _f(b.get("blended_per_share_iv") or b.get("per_share_iv"))
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
        fr = d.get("valuation_frame") or _inp(e, c, "valuation_frame")
        out["valuation_frame"] = str(fr).lower() if fr is not None else None
        leg = prov["legs"].get("base")
        if leg == "finite":
            out["terminal_method"], out["terminal_multiple_or_g"] = "finite_life", None
        elif leg == "exit":
            em = (d.get("exit_multiple_terminal") or {}).get("exit_multiple")
            if em is None:
                em = _inp(e, c, "terminal_exit_multiple")
            out["terminal_method"], out["terminal_multiple_or_g"] = "exit_multiple", _f(em)
        else:
            tg = d.get("terminal_g") if d.get("terminal_g") is not None else _inp(e, c, "terminal_g")
            out["terminal_method"], out["terminal_multiple_or_g"] = "gordon", _f(tg)
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
    base = out.get("base_iv") if "base_iv" in out else None
    if base is not None:
        out["verdict_label"] = label(base, price)
        out["asymmetric_payoff_skew"] = payoff_skew(out.get("bull_iv"), out.get("bear_iv"), price)
    filled = {}
    for k in FILLED:
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

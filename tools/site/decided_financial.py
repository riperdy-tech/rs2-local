"""decided_financial.py - WO_NC9 part B: the cloud read decides the valuation inputs of a bank or an insurer (the financial route); code pins the facts,
checks the reply and values it (operator 2026-11-18). The financial twin of decided_value.py: the same two runs, the same checks, the same result and
report shapes; only the inputs and the desk differ. Cloud arms only (gemini_ondemand.analyze with VALUE_METHOD "decided"). Nothing under qwen_c/ changes.

    code pins the facts   vrun.prepare (family financial): common book equity (preferred stock out of book, its dividends out of income), income to
                          common, the return on opening common equity and the growth of common equity of every year of the base, shares, cost of equity
    the read decides      one JSON object: the situation (what kind of institution, why the return on equity is where it is, whether the base year is
                          representative, whether capital limits growth), 5 inputs (the return on equity and the growth of common book equity of years
                          1 to 5, the long-run return, the long-run growth, the fade years), a low and a high for 3 of them, a reason with exact quotes
                          for every input, the largest risks, a confidence
    code checks           shape and counts, returns inside (-1, 1), the long-run return inside (0, 1), long-run growth below the cost of equity,
                          low <= input <= high, a verified quote for every input. ONE repair turn on a failure; a second failure is `decision_invalid`.
                          Code never changes a number the read gave.
    code values           desk.value_financial (through forecast_fin.value, V1 = checks._recompute_fin) on the pinned base with the read's numbers:
                          base; bear = every ranged input at its low, bull = at its high (a growth bound moves all five yearly growths by the same
                          amount, so that year 3's growth is the bound); the weights 25/50/25 are checks.PROB
    flags, not clamps     a return or a growth outside the company's own filed record, long-run growth above the long-run return, a base year judged
                          not representative, a low confidence, quotes verified n of m
    reference number      the value at the code's old defaults (the record-neutral financial menu value), code only, kept beside the new one
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import decided_value as D  # noqa: E402
from qwen_c import contract, runner, tasks  # noqa: E402
from qwen_c.value import checks, coe, desk, facts, forecast_fin, inputs, menu, run as vrun, task as vtask  # noqa: E402

DECIDED_VERSION = "decided.fin.v1 2026-11-18 WO_NC9b"
METHOD = D.METHOD                          # "decided.v1": the report reads both families' results by this name; the route is `financial`
ROUTE = "financial"
FAMILIES = vrun.FINANCIAL

INPUT_KEYS = ("roe", "book_growth", "long_run_roe", "terminal_growth", "fade_years")
LIST_KEYS = ("roe", "book_growth")
SCALAR_KEYS = INPUT_KEYS[2:]
RANGE_KEYS = ("long_run_roe", "book_growth_y3", "terminal_growth")
INSTITUTIONS = ("bank", "insurer", "other")
SITUATION_ENUMS = {"institution": INSTITUTIONS, "base_year_representative": D.TRIPLE, "capital_constrained": D.TRIPLE}
DISAGREE_KEYS = ("institution", "capital_constrained")      # the classifications whose disagreement between the two runs is stamped (the cyclical of decided_value)

SYSTEM = ("You are an equity analyst setting the inputs of a valuation of one bank or insurer, from its filings. The company is valued from its common "
          "book equity and the return it earns on it. Decide each input for THIS company. Do not default to a generic number: say what this company's "
          "situation is and what follows from it. Use only the evidence in this conversation; quote it exactly. Where the evidence does not support a "
          "view, say so and give your best estimate with a wide range.")

TASK = """TASK. Decide the valuation inputs for this company and return ONE JSON object and nothing else (no text before or after it).
Use fractions, not percents: 0.05 means 5%, 0.5059 means 50.59%. Return on equity is on the same basis as the return on opening common equity in the FILED RECORD (income to common / common equity at the start of the year; preferred stock is out of both). Year 1 is the fiscal year after the base year in the FILED RECORD; years 1 to 5 are five consecutive fiscal years.
What each input means: roe = return on opening common equity of years 1..5 (list of 5); book_growth = growth of common book equity DURING years 1..5 (list of 5; year 1 starts from the base year's closing common equity in the FILED RECORD); long_run_roe = the return on opening common equity the company fades to over fade_years after year 5 and keeps for ever; terminal_growth = growth of common book equity for ever after that fade (growth fades linearly from year 5's to this); fade_years = the number of years (a whole number, 1 to 25) of that fade.
What follows from them: the company is worth the present value of what it can pay out to its common shareholders, which is each year's income to common less the growth of common equity. Growth below the return on equity is paid out; growth above it needs new equity to be issued. Growth adds value only where the return on equity is above the cost of equity r. Say in situation.capital_constrained whether regulatory capital or the company's payout limits how fast its book equity can grow.
Ranges: for long_run_roe, book_growth_y3 (the growth of year 3; code moves all five yearly growths together by the difference between your bound and your year-3 growth) and terminal_growth, give [low, high]: the values you judge have about a 1 in 4 chance of being undershot (low) and about a 1 in 4 chance of being overshot (high). Your own input lies between them.
Every reason needs at least one exact quote copied character for character from the evidence item it cites (id = the id in brackets at the head of the item, e.g. F1 or P2; the FILED RECORD has id REC and any reason may cite it). Do not quote the PRIOR READ: it is not evidence. biggest_risks: the largest risks to your inputs; bear_value = the number that input would have if the risk happened.
Schema:
{"situation": {"institution": "bank|insurer|other", "roe_position": "<plain words: why the return on equity is where it is: the credit cycle, interest rates, reserves, one-off items>", "base_year_representative": "yes|no|unclear", "capital_constrained": "yes|no|unclear", "why": "<2-4 sentences>"},
 "inputs": {"roe": [y1,y2,y3,y4,y5], "book_growth": [y1,y2,y3,y4,y5], "long_run_roe": x, "terminal_growth": x, "fade_years": n},
 "ranges": {"long_run_roe": [low, high], "book_growth_y3": [low, high], "terminal_growth": [low, high]},
 "reasons": {"<each key of inputs>": {"why": "<1-3 sentences tied to this company>", "quotes": [{"id": "<evidence id>", "quote": "<exact text>"}]}},
 "biggest_risks": [{"risk": "...", "input_hit": "<key of inputs>", "bear_value": x}],
 "confidence": "low|medium|high"}"""


# ---------------------------------------------------------------- the prompt
def record_text(f, b, bar, r, prov):
    """(text of the item [REC], {"roe": {end: return}, "growth": {end: growth}}): the filed record of the base's years (the ones the menu's record bar
    is taken over), then the pinned base as the prompt shows it. Facts computed by code from the filings."""
    rec = b["record"]
    filed, eq, ni, pref = D._by_end(f, "equity"), rec["common_equity"], rec["income_to_common"], rec["preferred"]
    lines = ["[REC] FILED RECORD (computed by code from the filings; facts). Currency: USD as filed. Fiscal years, oldest first.",
             "fiscal year end | book equity as filed | preferred stock taken out | common equity | income to common | return on opening common equity | growth of common equity"]
    for e in sorted(eq):
        lines.append(f"{e} | {D._money(filed[e])} | {D._money(pref[e])} | {D._money(eq[e])} | {'n/a' if e not in ni else D._money(ni[e])} | "
                     f"{D._f4(rec['roe'].get(e))} | {D._f4(rec['book_growth'].get(e))}")
    pf = [s for s in b["stamps"] if s.startswith("preferred_subtracted")]
    if pf:
        lines.append(f"Preferred stock is taken out of book equity ({pf[0]}) and its dividends out of net income.")
    lines.append(f"Base year (the last filed fiscal year): ended {b['fy0']}; common equity at its end, which opens year 1, {D._money(b['R1'])}; income to common "
                 f"{D._money(b['e0'])}; return on opening common equity {b['roe0']:.4f}.")
    lines.append(f"Return on opening common equity over the years above: min {bar['min']:.4f}, p25 {bar['p25']:.4f}, median {bar['median']:.4f}, "
                 f"p75 {bar['p75']:.4f}, max {bar['max']:.4f}, last {bar['last']:.4f}.")
    aoci = next((s for s in b["stamps"] if s.startswith("aoci_in_book_not_separated:")), None)
    if aoci:
        lines.append(f"Accumulated other comprehensive income is inside the book equity as filed (not separated): its share of book equity {aoci.split(':', 1)[1]}.")
    lines.append(f"Cost of equity r {r:.4f}; long-run nominal growth anchor g_anchor {D._f4(prov.get('g_anchor'))}. Growth of book equity adds value only where the return on equity is above r.")
    return "\n".join(lines), {"roe": dict(rec["roe"]), "growth": dict(rec["book_growth"])}


def messages(packet, rec, prior, retry=None):
    """[system, user] (+ the repair turn: the previous reply and what was wrong). The packet is shown with its prices masked."""
    user = "\n\n".join([tasks.render_packet(vtask.mask_price(packet)), rec,
                        "PRIOR READ (another analyst's notes, unverified; not evidence, not to be quoted)\n" + prior, TASK])
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    if retry:
        prev, problems = retry
        msgs += [{"role": "assistant", "content": prev},
                 {"role": "user", "content": "These inputs did not pass the code checks. Reply again with the whole JSON; keep what passed:\n"
                                             + "\n".join(f"- {p}" for p in problems)}]
    return msgs


# ---------------------------------------------------------------- the checks
def shape_problems(obj):
    """What is wrong with the reply's form (names, types, counts), or []."""
    if not isinstance(obj, dict):
        return ["the reply is not a JSON object"]
    p, num = [], D._num
    sit = obj.get("situation")
    if not isinstance(sit, dict):
        p.append("situation is missing or not an object")
    else:
        p += [f"situation.{k} must be one of {', '.join(v)}" for k, v in SITUATION_ENUMS.items() if sit.get(k) not in v]
        p += [f"situation.{k} is missing" for k in ("roe_position", "why") if not (isinstance(sit.get(k), str) and sit[k].strip())]
    inp = obj.get("inputs")
    if not isinstance(inp, dict):
        p.append("inputs is missing or not an object")
    else:
        p += [f"inputs.{k} must be a list of 5 numbers" for k in LIST_KEYS if not (isinstance(inp.get(k), list) and len(inp[k]) == 5 and all(num(x) for x in inp[k]))]
        p += [f"inputs.{k} must be a number" for k in SCALAR_KEYS if not num(inp.get(k))]
        fy = inp.get("fade_years")
        if num(fy) and not (float(fy).is_integer() and D.FADE_YEARS[0] <= fy <= D.FADE_YEARS[1]):
            p.append(f"inputs.fade_years must be a whole number from {D.FADE_YEARS[0]} to {D.FADE_YEARS[1]}")
    rng = obj.get("ranges")
    if not isinstance(rng, dict):
        p.append("ranges is missing or not an object")
    else:
        p += [f"ranges.{k} must be a list [low, high] of 2 numbers" for k in RANGE_KEYS
              if not (isinstance(rng.get(k), list) and len(rng[k]) == 2 and all(num(x) for x in rng[k]))]
    why = obj.get("reasons")
    if not isinstance(why, dict):
        p.append("reasons is missing or not an object")
    else:
        for k in INPUT_KEYS:
            e = why.get(k)
            if not (isinstance(e, dict) and isinstance(e.get("why"), str) and e["why"].strip() and isinstance(e.get("quotes"), list)):
                p.append(f"reasons.{k} must be {{why: text, quotes: a list}}")
    risks = obj.get("biggest_risks")
    if not (isinstance(risks, list) and all(isinstance(x, dict) and isinstance(x.get("risk"), str) and x["risk"].strip() and x.get("input_hit") in INPUT_KEYS for x in risks)):
        p.append("biggest_risks must be a list of {risk: text, input_hit: a key of inputs, bear_value: a number}")
    if obj.get("confidence") not in D.CONFIDENCE:
        p.append(f"confidence must be one of {', '.join(D.CONFIDENCE)}")
    return p


def scenario_inputs(inp, rng, side):
    """The inputs with every ranged input at its low (side 0) or its high (side 1): the long-run return and the long-run growth at the bound, and the
    five yearly book growths moved together by (the bound - the year-3 growth)."""
    shift = rng["book_growth_y3"][side] - inp["book_growth"][2]
    return dict(inp, book_growth=[g + shift for g in inp["book_growth"]], long_run_roe=rng["long_run_roe"][side], terminal_growth=rng["terminal_growth"][side])


def numeric_problems(obj, r):
    """The numeric checks of a reply of valid shape: yearly returns inside (-1, 1), the long-run return (and its range ends, which are valued) inside
    (0, 1), long-run growth below r (the range ends too), low <= input <= high, book growth above -1 in the base, bear and bull paths."""
    inp, rng, p = obj["inputs"], obj["ranges"], []
    p += [f"roe {x} is outside (-1, 1)" for x in inp["roe"] if not -1 < x < 1]
    p += [f"long_run_roe {x} is outside (0, 1)" for x in (inp["long_run_roe"], *rng["long_run_roe"]) if not 0 < x < 1]
    base = {"long_run_roe": inp["long_run_roe"], "book_growth_y3": inp["book_growth"][2], "terminal_growth": inp["terminal_growth"]}
    for k in RANGE_KEYS:
        lo, hi = rng[k]
        if not lo <= base[k] <= hi:
            p.append(f"ranges.{k} [{lo}, {hi}] must contain the input {base[k]} (low <= input <= high)")
    p += [f"terminal_growth {g} is not below the cost of equity {r:.4f}" for g in (inp["terminal_growth"], *rng["terminal_growth"]) if not g < r]
    for name, side in (("base", None), ("low", 0), ("high", 1)):                   # an equity path needs growth above -1 in every year
        gr = inp["book_growth"] if side is None else scenario_inputs(inp, rng, side)["book_growth"]
        p += [f"book_growth of the {name} case, year {t}: {g:.4f} is not above -1" for t, g in enumerate(gr, 1) if not g > -1]
    return p


def verify_quotes(obj, texts):
    """{key of inputs: (the quotes found word for word in the item they cite, the number given)}."""
    out = {}
    for k in INPUT_KEYS:
        qs = obj["reasons"][k]["quotes"]
        kept = []
        for q in qs:
            i, s = (q.get("id"), q.get("quote")) if isinstance(q, dict) else (None, None)
            if isinstance(i, str) and isinstance(s, str) and i in texts and contract.quote_found(s, [texts[i]]):
                kept.append({"id": i, "quote": s})
        out[k] = (kept, len(qs))
    return out


# ---------------------------------------------------------------- the numeric route
def value_inputs(b, r, inp):
    """(value per share, desk result) from numeric inputs, through forecast_fin.value (desk.value_financial rolled forward to T) on the pinned base:
    forecast_fin.assemble's own arithmetic with the five yearly paths typed instead of blended. R_0 and R_1 are the base's, R_{t+1} = R_t (1 + g_t)
    for t = 1..4 and g_5 goes to the desk as g5. Raises desk.DeskRefusal; AssertionError when V1 (checks._recompute_fin) disagrees."""
    R = [float(b["R0"]), float(b["R1"])]
    for g in inp["book_growth"][:4]:
        R.append(R[-1] * (1.0 + float(g)))
    lr = float(inp["long_run_roe"])
    path = [{"year": t, "book_growth": float(g), "roe": float(m)} for t, (g, m) in enumerate(zip(inp["book_growth"], inp["roe"]), 1)]
    d = {"revenue": R, "margin": [y["roe"] for y in path], "r": float(r), "g_T": float(inp["terminal_growth"]), "F": int(inp["fade_years"]),
         "ronic0": b["roe0"], "ronic_T": lr, "m_long": lr, "shares": b["shares"], "excess_cash": b["excess_cash"], "driver": "book",
         "g5": path[4]["book_growth"], "stub_days": b["stub_days"], "_path": path}
    v = forecast_fin.value(d)
    checks._recompute_fin(d, v, b)
    return v["value_per_share"], v


def values(b, r, inp, rng):
    """({base, bear, bull: value per share}, [what the desk could not value], the base's desk result)."""
    out, problems, base_v = {}, [], None
    for name, i in (("base", inp), ("bear", scenario_inputs(inp, rng, 0)), ("bull", scenario_inputs(inp, rng, 1))):
        try:
            out[name], v = value_inputs(b, r, i)
        except (desk.DeskRefusal, ArithmeticError) as e:
            problems.append(f"the desk could not value the {name} inputs: {e}")
        else:
            base_v = v if name == "base" else base_v
    return out, problems, base_v


def old_defaults(b, bar, r):
    """(value per share, how) at the code's old defaults: the record-neutral reply of the financial menu. Code only; never loses a valuation."""
    try:
        return checks._neutral_fin(b, bar, r)
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, OverflowError, AssertionError) as e:
        return None, f"unavailable: {type(e).__name__}: {e}"


def flags_of(obj, rec, verified, vals):
    """The stamps of one run: flags and annotations, never a clamp or a gate."""
    inp, out = obj["inputs"], []
    for series, rows, label in ((rec["roe"], [(f"roe.y{t}", x) for t, x in enumerate(inp["roe"], 1)] + [("long_run_roe", inp["long_run_roe"])], "roe"),
                                (rec["growth"], [(f"book_growth.y{t}", x) for t, x in enumerate(inp["book_growth"], 1)], "book_growth")):
        if series:
            lo, hi = min(series.values()), max(series.values())
            out += [f"{label}_outside_filed_record: {k} {x:.4f} (filed {lo:.4f} to {hi:.4f})" for k, x in rows if not lo <= x <= hi]
    if inp["terminal_growth"] > inp["long_run_roe"]:
        out.append(f"growth_above_roe_in_the_long_run: terminal_growth {inp['terminal_growth']:.4f} against long_run_roe {inp['long_run_roe']:.4f}")
    if obj["situation"]["base_year_representative"] == "no":
        out.append("base_year_not_representative")
    if obj["confidence"] == "low":
        out.append("confidence_low")
    n, m = sum(len(k) for k, _ in verified.values()), sum(t for _, t in verified.values())
    out.append(f"quotes_verified: {n} of {m}")
    if not vals["bear"] <= vals["base"] <= vals["bull"]:
        out.append(f"scenario_order_not_monotone: bear {vals['bear']:.4f}, base {vals['base']:.4f}, bull {vals['bull']:.4f}")
    return out


# ---------------------------------------------------------------- one run
def value(packet_path, cik, sector, market_cap, *, family, analysis=None, seed=runner.SEED_BASE, out_root=vrun.RUNS, online=True, root=None,
          allow_after_T=False, interest_override=None):
    """One run of the decided method for a financial name (one decision call, plus one repair turn when a check fails); writes result.json and
    raw/attempt_<n>.json under out_root. The result has vrun.value's shape (status, values, base, cost_of_equity, checks.prob, stamps, versions) and
    `decided`. A name code refuses before any call is refused as the menu method refuses it. A call that gets no reply raises (the worker's failure path)."""
    packet, src = runner.load_packet(packet_path)
    run_dir = out_root / f"{packet['ticker']}_{runner.t_compact(packet['decision_time_utc'])}_{runner.sha256_bytes(src)[:12]}_decided_{seed}"
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    result = {"ticker": packet["ticker"], "T": packet["decision_time_utc"], "packet_sha256": runner.sha256_bytes(src), "seed": seed, "route": ROUTE,
              "versions": {"method": METHOD, "decided": DECIDED_VERSION, "desk": desk.DESK_VERSION, "facts": facts.FACTS_VERSION,
                           "inputs": inputs.INPUTS_VERSION, "checks": checks.CHECKS_VERSION, "coe": coe.COE_VERSION,
                           "forecast_fin": forecast_fin.FORECAST_FIN_VERSION, "contract": contract.CONTRACT, "model": runner.MODEL, "git": runner.git_state()},
              "authority": "diagnostic_only"}
    try:
        if family not in FAMILIES:
            raise desk.DeskRefusal("family_not_routed", f"family {family!r}: the decided financial method values only {FAMILIES}")
        if any(e.get("kind") == "news" for e in packet.get("evidence") or []):         # as vrun.value
            raise desk.DeskRefusal("news_items_not_valued", "the packet holds news items; the valuation reads filings only")
        f, b, bar, record, r, prov, fy_ends = vrun.prepare(packet, cik, sector, market_cap, online=online, root=root, allow_after_T=allow_after_T, family=family,
                                                     interest_override=interest_override, decided=True)
    except desk.DeskRefusal as e:
        result.update(status="no_call", reason=e.code, detail=str(e))
        return D._write(run_dir, result)
    result.update(family=family, base=b, bar=bar, cost_of_equity=r, coe=prov, facts_provenance=f.get("_provenance"),
                  stamps=b["stamps"] + prov.get("stamps", []) + list(checks.FIN_STAMPS))     # capital_constraint_not_modeled: as the menu route
    old_value, old_how = old_defaults(b, bar, r)                       # code only: before any call
    rec_text, rec = record_text(f, b, bar, r, prov)
    texts = contract.evidence_texts(vtask.mask_price(packet))
    texts["REC"] = rec_text
    prior, n_kept, n_dropped = D.prior_read(analysis)
    attempts, retry, out = [], None, None
    for n in (1, 2):
        msgs, left_out, fits = D.fitted(lambda p: messages(packet, rec_text, p, retry), prior)
        if not fits:
            return D.too_long(result, run_dir, attempts)
        t0 = time.monotonic()
        kind, resp, detail = runner.call({"model": runner.MODEL, "stream": False, "messages": msgs}, runner.llm_provider.OLLAMA_URL, runner.TASK_TIMEOUT_S)
        secs = round(time.monotonic() - t0, 3)
        if kind != "reply":
            raise RuntimeError(f"decided call failed: {kind}: {detail}")
        content = ((resp or {}).get("message") or {}).get("content")
        obj, perr = runner.parse_reply(content)
        att = {"attempt": n, "seconds": secs, **{k: (resp or {}).get(k) for k in ("prompt_eval_count", "eval_count", "done_reason")},
               **({"prior_notes_left_out": left_out} if left_out else {})}
        verified = vals = base_v = None
        if perr:
            problems = [f"not valid JSON: {perr}"]
        else:
            problems = shape_problems(obj)
            if not problems:
                verified = verify_quotes(obj, texts)
                problems = numeric_problems(obj, r) + D.quote_problems(verified)
            if not problems:
                try:
                    vals, problems, base_v = values(b, r, obj["inputs"], obj["ranges"])
                except AssertionError as e:                               # an engine defect is recorded, never a crash
                    att.update(outcome="engine_defect", problems=[str(e)])
                    attempts.append(att)
                    runner._write_json(run_dir / "raw" / f"attempt_{n}.json", {"messages": msgs, "response": content, "problems": [str(e)]})
                    result.update(status="engine_defect", reason="engine_defect", detail=str(e), attempts=attempts)
                    return D._write(run_dir, result)
        att.update(outcome="ok" if not problems else "invalid", problems=problems)
        attempts.append(att)
        runner._write_json(run_dir / "raw" / f"attempt_{n}.json", {"messages": msgs, "response": content, "problems": problems})
        if not problems:
            out = (n, obj, verified, vals, base_v)
            break
        retry = (content or "", problems)
    result["attempts"] = attempts
    if out is None:
        result.update(status="no_call", reason="decision_invalid", detail="; ".join(attempts[-1]["problems"]))
        return D._write(run_dir, result)
    n, obj, verified, vals, base_v = out
    inp, rng = obj["inputs"], obj["ranges"]
    flags = flags_of(obj, rec, verified, vals) + D.surfaced_stamps(b)          # WO_UV2
    dec = {"route": ROUTE, "situation": obj["situation"], "inputs": inp, "ranges": rng, "risks": obj["biggest_risks"], "confidence": obj["confidence"],
           "reasons": {k: {"why": obj["reasons"][k]["why"], "quotes": verified[k][0], "quotes_given": verified[k][1]} for k in INPUT_KEYS},
           "scenarios": {s: {k: v for k, v in scenario_inputs(inp, rng, side).items() if k in ("book_growth", "long_run_roe", "terminal_growth")}
                         for s, side in (("bear", 0), ("bull", 1))},
           "flags": flags, "value_at_old_defaults": old_value, "old_defaults_inputs": old_how,
           "prior_read_claims": {"kept": n_kept, "dropped_unsupported": n_dropped},
           "diagnostics": {"equity_value": base_v["equity_value"], "tv_share": base_v["tv_pv"] / base_v["equity_value"] if base_v["equity_value"] else None,
                           "seam_ratio": base_v["seam_ratio"], "implied_pb": vals["base"] / (b["R1"] / b["shares"])}}
    result.update(status="ok", values=vals, checks={"prob": dict(checks.PROB), "version": DECIDED_VERSION}, inputs=obj, checked_attempt=n, decided=dec)
    return D._write(run_dir, result)


# ---------------------------------------------------------------- the two runs
def combine_runs(results):
    """(valued, v): the report's values from the two runs, {seed: result}, in decided_value.combine_runs's shape. Both runs must have a valued result: there
    is no fallback to a default and no single-run value. The two runs disagreeing on situation.institution or situation.capital_constrained is stamped."""
    ok = {s: x for s, x in sorted(results.items()) if str(x.get("status", "")).startswith("ok")}
    if len(ok) != 2 or len(results) != 2:
        return False, {}
    (s1, a), (s2, c) = ok.items()
    diff = {k: {s: x["decided"]["situation"][k] for s, x in ok.items()} for k in DISAGREE_KEYS if len({x["decided"]["situation"][k] for x in ok.values()}) > 1}
    unclear = bool(diff)
    flags = (["situation_unclear"] if unclear else []) + [f"run {s}: {fl}" for s, x in ok.items() for fl in x["decided"]["flags"]]
    d1 = a["decided"]
    return True, {"values": {k: (a["values"][k] + c["values"][k]) / 2 for k in ("bear", "base", "bull")},
                  "annotations": [f"seeds_disagree: situation.{k} ({', '.join(f'{s} {y}' for s, y in d.items())})" for k, d in diff.items()],
                  "decided": {"version": DECIDED_VERSION, "method": METHOD, "route": ROUTE, "runs": {s: dict(x["decided"], values=x["values"]) for s, x in ok.items()},
                              "run_gap": D.run_gap(a["values"]["base"], c["values"]["base"]), "situation_unclear": unclear, "flags": flags,
                              "value_at_old_defaults": d1["value_at_old_defaults"], "old_defaults_inputs": d1["old_defaults_inputs"]}}

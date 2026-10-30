"""run.py - one valuation of one company (SPEC_m3q §2; WO_Q5b): filed facts -> the measured base -> the cost of equity -> the filed
record -> the valuation_inputs prompt -> the model -> checks V1-V11 -> at most one repair turn -> result.json.

The model call, the reply parsing and the overflow checks are qwen_c.runner's own (call, parse_reply, reply_problem), so a valuation
fails the way an analysis task fails. Everything the model was told and returned is kept under cache/m3q/runs/<run>/ (prompts/, raw/),
and result.json carries the checks, the values and every version. A financial company (a bank, an insurer, a mortgage REIT) takes the
financial route (WO_Q6, O3): inputs.base_financial, the ROE-path task, forecast_fin and checks(route="financial").

    python -m qwen_c.value.run <packet.json> --cik <cik> --sector <MRI sector> --market-cap <USD> [--seed 1000] [--family operating]
"""
import argparse
import json
import time
from datetime import date, timedelta

import rs2_data
from qwen_c import runner
from qwen_c.value import checks, coe, desk, facts, forecast, forecast_fin, inputs, task

RUNS = runner.ROOT / "cache" / "m3q" / "runs"
REPAIR_SEED_OFFSET = 50000


def _statements(packet):
    return {e["fact_id"] for e in packet["evidence"] if e.get("kind") == "statement"}


MAX_STUB_DAYS = 800
NUM_PREDICT = 24576    # smokes 1-2: 12,288 and 16,384 ran out in thinking; prompt ~35k + 24.5k is well inside NUM_CTX
ROUTED = ("operating", "commodity")      # ruling 17: every other family not routed below is a named no_call
FINANCIAL = ("financial", "mortgage_reit")   # WO_Q6: the financial route (O3; O6 for mortgage REITs)


def prepare(packet, cik, sector, market_cap, *, online, family, root=None, allow_after_T=False):
    """Everything code owns, before any model call: (facts, base, bar, record items, r, coe provenance, fiscal-year ends).
    `family` is required (the census's), never defaulted. Raises DeskRefusal."""
    if family not in ROUTED + FINANCIAL:
        raise desk.DeskRefusal("family_not_routed", f"family {family!r}: only {ROUTED + FINANCIAL} are valued by this runner")
    T = runner._parse_t(packet["decision_time_utc"])
    f = facts.build(cik, T, online=online, root=root)
    if family in FINANCIAL:
        return _prepare_financial(f, T, sector, allow_after_T)
    fy0 = max(v["end"] for v in (f.get("revenue") or {}).get("values", [])) if f.get("revenue") else None
    if fy0 is None:
        raise desk.DeskRefusal("history_short", "no filed revenue")
    bill, bill_src = rs2_data.bill_rate_mean(str(date.fromisoformat(fy0) - timedelta(days=365)), fy0)
    b = inputs.base(f, market_cap=market_cap, bill_rate=bill)
    b["bill_source"] = bill_src
    b["stub_days"] = (T.date() - date.fromisoformat(b["fy0"])).days      # ruling 7: rolled forward from the fiscal-year end to T
    if b["stub_days"] > MAX_STUB_DAYS:                                    # CROSS_CHECK_Q2 N12: refused before any model call
        raise desk.DeskRefusal("base_year_too_old", f"the base fiscal year ended {b['stub_days']} days before T")
    if b.get("oi0") is None:                                              # ruling 24: a data no-call before any model call
        raise desk.DeskRefusal("bridge_unavailable", "operating income for the base year is not filed")
    bar = forecast.record_bar(b["record"]["op_margin"])
    record = forecast.record_items(f)
    r, prov = coe.cost_of_equity(sector, T, allow_after_T=allow_after_T)
    b["g_anchor"] = prov["g_anchor"]                                      # N7: the long-run growth anchor the checks annotate against
    fy_ends = [v["end"] for v in f["revenue"]["values"]]
    return f, b, bar, record, r, prov, fy_ends


def _prepare_financial(f, T, sector, allow_after_T):
    """prepare() for the financial route: no market value, bill rate or operating bridge is needed."""
    b = inputs.base_financial(f)
    b["stub_days"] = (T.date() - date.fromisoformat(b["fy0"])).days
    if b["stub_days"] > MAX_STUB_DAYS:
        raise desk.DeskRefusal("base_year_too_old", f"the base fiscal year ended {b['stub_days']} days before T")
    bar = forecast_fin.record_bar(b["record"]["roe"])
    record = forecast_fin.record_items(f)
    r, prov = coe.cost_of_equity(sector, T, allow_after_T=allow_after_T)
    b["g_anchor"] = prov["g_anchor"]
    fy_ends = [v["end"] for v in f["equity"]["values"]]
    return f, b, bar, record, r, prov, fy_ends


def _one_call(msgs, seed, opts, url):
    """(outcome, object or None, detail, response, seconds)."""
    body = {"model": runner.MODEL, "stream": False, "think": opts["think"], "messages": msgs,
            "options": {"num_ctx": opts["num_ctx"], "num_predict": opts["num_predict"], "seed": seed}}
    t0 = time.monotonic()
    kind, resp, detail = runner.call(body, url, runner.TASK_TIMEOUT_S)
    secs = round(time.monotonic() - t0, 3)
    if kind == "reply":
        kind, detail = runner.reply_problem(resp, opts["num_ctx"]) or (kind, detail)
    if kind != "reply":
        return kind, None, detail, resp, secs
    obj, perr = runner.parse_reply(((resp or {}).get("message") or {}).get("content"))
    return ("reply" if perr is None else "malformed"), obj, perr, resp, secs


def value(packet_path, cik, sector, market_cap, *, family, url=None, seed=runner.SEED_BASE, online=True, root=None, out_root=RUNS,
          allow_after_T=False, opts=None):
    packet, src = runner.load_packet(packet_path)
    opts = opts or {"num_ctx": runner.NUM_CTX, "num_predict": NUM_PREDICT, "think": runner.THINK}
    url = url or runner.llm_provider.OLLAMA_URL
    run_dir = out_root / f"{packet['ticker']}_{runner.t_compact(packet['decision_time_utc'])}_{runner.sha256_bytes(src)[:12]}_{seed}"
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    result = {"ticker": packet["ticker"], "T": packet["decision_time_utc"], "packet_sha256": runner.sha256_bytes(src), "seed": seed,
              "versions": {"desk": desk.DESK_VERSION, "facts": facts.FACTS_VERSION, "inputs": inputs.INPUTS_VERSION,
                           "forecast": forecast.FORECAST_VERSION, "checks": checks.CHECKS_VERSION, "coe": coe.COE_VERSION,
                           "prompt": task.VALUATION_PROMPT_FIN_VERSION if family in FINANCIAL else task.VALUATION_PROMPT_VERSION,
                           "forecast_fin": forecast_fin.FORECAST_FIN_VERSION, "contract": runner.contract.CONTRACT, "model": runner.MODEL,
                           "git": runner.git_state()},
              "authority": "diagnostic_only"}
    try:
        f, b, bar, record, r, prov, fy_ends = prepare(packet, cik, sector, market_cap, online=online, root=root,
                                                      allow_after_T=allow_after_T, family=family)
    except desk.DeskRefusal as e:
        result.update(status="no_call", reason=e.code, detail=str(e))
        runner._write_json(run_dir / "result.json", result)
        return result
    fact_stamps = {c: sorted({v["stamp"] for v in d["values"] if v.get("stamp")}) for c, d in f.items()
                   if not c.startswith("_") and any(v.get("stamp") for v in d["values"])}
    result.update(family=family, base=b, bar=bar, cost_of_equity=r, coe=prov, facts_provenance=f.get("_provenance"),
                  stamps=b["stamps"] + prov.get("stamps", []), fact_stamps=fact_stamps)            # N16
    items = {e["fact_id"]: e for e in packet["evidence"]}
    items.update({i["fact_id"]: i for i in record})
    items["V0"] = task.base_item(b, bar, r, prov)                         # smoke 1: [V0] is citable
    retry, attempts, res = None, [], None
    for n, s in enumerate((seed, seed + REPAIR_SEED_OFFSET), 1):
        msgs = task.messages(packet, record, b, bar, r, prov, retry=retry)
        outcome, obj, detail, resp, secs = _one_call(msgs, s, opts, url)
        runner._write_json(run_dir / "raw" / f"attempt_{n}.json", {"messages": msgs, "response": resp, "outcome": outcome, "detail": detail})
        att = {"attempt": n, "seed": s, "outcome": outcome, "detail": detail, "seconds": secs}
        if outcome == "reply":
            try:
                res = checks.check(obj, items, packet["ticker"], _statements(packet), b, bar, r, fy_ends,
                                   route="financial" if family in FINANCIAL else "operating")
            except AssertionError as e:                                   # N11: an engine defect is recorded, never a crash
                att.update(outcome="engine_defect", detail=str(e))
                attempts.append(att)
                break
            att.update(status=res["status"], inputs=obj, checks={k: v for k, v in res.items() if k != "results"}, values=res["values"])
            attempts.append(att)
            if res["status"] == "ok" or n == 2:
                break
            content = ((resp or {}).get("message") or {}).get("content") or ""
            retry = (content, res.get("failures") or res["unsupported"])
            continue
        attempts.append(att)
        if outcome == "malformed" and n == 1:
            retry = ((((resp or {}).get("message") or {}).get("content") or ""), [f"not valid JSON: {detail}"])
            continue
        break
    result["attempts"] = attempts                                     # ruling 23: every attempt keeps its inputs, checks and values
    last = attempts[-1]
    result["status"] = last.get("status") or last["outcome"]
    checked = [a for a in attempts if "checks" in a]
    if checked:
        result.update(checks=checked[-1]["checks"], values=checked[-1]["values"], inputs=checked[-1]["inputs"],
                      checked_attempt=checked[-1]["attempt"])
    runner._write_json(run_dir / "result.json", result)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("packet")
    ap.add_argument("--cik", required=True)
    ap.add_argument("--sector", required=True)
    ap.add_argument("--market-cap", type=float, required=True)
    ap.add_argument("--seed", type=int, default=runner.SEED_BASE)
    ap.add_argument("--family", required=True, help="the census family; operating, commodity, financial and mortgage_reit are valued")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--allow-anchor-after-T", action="store_true", help="the E2 regression on consumed dates only")
    a = ap.parse_args(argv)
    res = value(a.packet, a.cik, a.sector, a.market_cap, seed=a.seed, online=not a.offline, allow_after_T=a.allow_anchor_after_T,
                family=a.family)
    print(json.dumps({k: res.get(k) for k in ("ticker", "status", "reason", "values")}, default=str))


if __name__ == "__main__":
    main()

"""consensus.py - design revision 2, rule (a) (operator 2026-11-06): the value of record of a name valued at two seeds.

A key's departure counts in the value only when both seeds' checked results depart it in the same direction; the seed whose number
is nearer the record neutral then gives the option (and its departures entry, and its guidance entry when the option is guidance).
Every other key takes its record-neutral option and is annotated `seeds_disagree: <key> (<seed> <direction>, ...)` when either seed
departed it. A name with only one checked seed has no agreement: every key is neutral, annotated `one_seed_only`. The agreed reply is
then checked like any reply (checks.check: reverts, the safe default of menu.HELD, scenarios), so the value of record is code's.
The years to normalized (normalized.year, not a departure key) follow the same rule: kept when both seeds chose it, else
menu.NEUTRAL_YEAR, annotated. The agreed value need not lie between the seeds' values: it is neutral on every key they do not share.
Nothing here calls the model.
"""
import copy

from qwen_c.value import checks, menu

CONSENSUS_VERSION = "m3q.consensus.v1"


def _gap(k, res, m):
    a, c = res["checks"]["numbers"][k], res["checks"]["neutral"][k]
    if menu.KEYS[m["route"]][k] == "capex":
        a, c = sum(a) / len(a), sum(c) / len(c)
    return abs(a - c)


def agreed_reply(results, m):
    """(reply, notes): one reply whose options are the agreement of the seeds' checked results ({seed: result.json body})."""
    route, ok = m["route"], {s: r for s, r in results.items() if str(r.get("status", "")).startswith("ok")}
    first = ok[min(ok)] if ok else None
    if first is None:
        return None, ["no_checked_seed"]
    reply = copy.deepcopy(first["inputs"])
    base, deps, guidance, notes = menu.neutral_base(route, m), [], {}, []
    years = {s: r["checks"]["year"] for s, r in ok.items()}   # the years to normalized: not a departure key, agreed the same way
    base["normalized"]["year"] = years[min(ok)] if len(ok) == 2 and len(set(years.values())) == 1 else menu.NEUTRAL_YEAR
    if len(ok) == 2 and len(set(years.values())) > 1:
        notes.append("seeds_disagree: normalized.year (" + ", ".join(f"{s} {y}" for s, y in sorted(years.items())) + ")")
    if len(ok) < 2:
        notes.append(f"one_seed_only: {sorted(ok)}")
    for k in menu.KEYS[route]:
        dirs = {s: r["checks"]["directions"][k] for s, r in ok.items()}
        moved = {s: d for s, d in dirs.items() if d != "none"}
        if len(ok) == 2 and len(moved) == 2 and len(set(moved.values())) == 1:
            s = min(ok, key=lambda x: (_gap(k, ok[x], m), x))
            c = ok[s]["checks"]
            opt = c["options"][k]
            base = menu.set_option(base, k, tuple(opt) if isinstance(opt, list) else opt)
            deps += [d for d in c["departures"] if d["input"] == k and "inherited_from" not in d]   # an inherited entry is re-derived
            if opt == "guidance":
                guidance[k] = ok[s]["inputs"]["guidance"][k]
        elif moved:
            notes.append(f"seeds_disagree: {k} (" + ", ".join(f"{s} {d}" for s, d in sorted(dirs.items())) + ")")
    reply.update(base=base, departures=deps, guidance=guidance)
    return reply, notes


def combine(results, ids, b, bar, r, fy_ends, route):
    """The checked value of record of the agreed reply, with the consensus notes in its annotations and the seeds it read."""
    m = menu.menus(b, bar, r, route)
    reply, notes = agreed_reply(results, m)
    if reply is None:
        return {"version": CONSENSUS_VERSION, "status": "no_call", "reason": "no_checked_seed", "values": {}, "annotations": notes}
    res = checks.check(reply, ids, b, bar, r, fy_ends, route=route)
    res = {k: v for k, v in res.items() if k != "results"}
    res["annotations"] = notes + res.get("annotations", [])
    return dict(res, consensus_version=CONSENSUS_VERSION, reply=reply, seeds=sorted(results))

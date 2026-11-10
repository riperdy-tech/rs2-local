"""score_nextq.py - the next-quarter scorer of PREREG_cohorts_nextq (v0.1 with its section 7 amendments, 2026-11-10).

The rules here are pure functions on numbers, so that they can be tested on synthetic quarters. The reading of stored slots and the
realised quarter (realised_q, called with the year-to-date period's end) is `name_row`; the whole reading is `readings`.

THE RULES (PREREG section 7).
7.2 Qwen's next-quarter growth is the growth its year-1 number G implies for the unreported rest of year 1:
    g_rest = (R0 * (1 + G) - yc) / (R0 - yp) - 1
    R0: base-year revenue; yc, yp: year-to-date revenue and its prior-year leg. G is the reply's resolved rev_growth.y1 before the hold
    (checks' `numbers` stay the reply's; `of_record` holds the value only). For ytd, g_rest is the pace; for the four record options it
    is the option's own number; for guidance it is the guided year less what is reported. No figure where R0 - yp <= 0.
7.3 Error e = |ln((1 + g_forecast) / (1 + g_realised))|. A forecast with 1 + g <= 0 loses (e = inf). A realised 1 + g <= 0 has no
    error (excluded, counted). A tie (errors within TIE) is dropped.
7.4 A name departs when both seeds' G leave the pace by more than menu.TOL in the same direction; the seed nearer the pace gives G.
    One seed invalid or only one seed departing: counted, not a departure.
7.5 PASS needs (a) pooled win share >= 0.55, one-sided sign p < 0.05, >= 60 departures; (b) win share > 0.50 in at least 3 of 4
    cohorts, a cohort counting only with >= 15 departures; (c) the 5/95-winsorised mean of e_qwen - e_pace <= 0. FAIL: pooled win
    share <= 0.50. Otherwise, or fewer than 3 countable cohorts: NOT DECIDED.
7.6 S1 (selection): R is the latest-dated readable `found` entry (date tie: first listed), else the pace.
"""
import math

SCORER_VERSION = "cohorts.score_nextq.v1"
TOL = 0.001                 # qwen_c.value.menu.TOL (asserted equal in the tests)
TIE = 1e-9
BAR_SHARE, BAR_P, FLOOR, COHORT_MIN, COHORTS_AHEAD = 0.55, 0.05, 60, 15, 3
WINSOR = (0.05, 0.95)


def g_rest(G, R0, yc, yp):
    """The rest-of-year growth a year-1 growth G implies (7.2), or None."""
    if None in (G, R0, yc, yp) or not R0 - yp > 0:
        return None
    return (R0 * (1 + G) - yc) / (R0 - yp) - 1


def error(g_forecast, g_realised):
    """7.3: |ln((1+f)/(1+r))|; inf for a forecast at or below -100%; None where the realised leg is not positive."""
    if g_realised is None or 1 + g_realised <= 0:
        return None
    if g_forecast is None or 1 + g_forecast <= 0:
        return math.inf
    return abs(math.log((1 + g_forecast) / (1 + g_realised)))


def departure(seeds, pace):
    """7.4. `seeds`: [G or None per seed] (None: the seed has no checked reply). (status, G): status `departs`, `one_seed_invalid`,
    `one_seed_departs`, `split` (opposite directions), `no_departure`; G the seed nearer the pace when it departs."""
    if len(seeds) != 2 or any(g is None for g in seeds) or pace is None:
        return "one_seed_invalid", None
    d = [g - pace for g in seeds]
    out = [abs(x) > TOL for x in d]
    if not any(out):
        return "no_departure", None
    if not all(out):
        return "one_seed_departs", None
    if (d[0] > 0) != (d[1] > 0):
        return "split", None
    return "departs", min(seeds, key=lambda g: abs(g - pace))


def outcome(e_qwen, e_pace):
    """win | loss | tie (dropped) | None (no realised error)."""
    if e_qwen is None or e_pace is None:
        return None
    if math.isinf(e_qwen) and math.isinf(e_pace):
        return "tie"
    if abs(e_qwen - e_pace) <= TIE:
        return "tie"
    return "win" if e_qwen < e_pace else "loss"


def sign_p(wins, n):
    """One-sided sign test: P(X >= wins | n, 1/2)."""
    if n == 0:
        return None
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def winsorised_mean(xs, lo=WINSOR[0], hi=WINSOR[1]):
    """Mean after clamping to the lo and hi empirical quantiles (nearest rank). inf values clamp like any other."""
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    a, b = s[max(0, math.ceil(lo * n) - 1)], s[min(n - 1, math.ceil(hi * n) - 1)]
    return sum(min(max(x, a), b) for x in s) / n


def verdict(rows):
    """7.5 on rows [{cohort, outcome, d}] of departures with an outcome (ties already counted apart). Returns the reading."""
    dec = [r for r in rows if r["outcome"] in ("win", "loss")]
    n, w = len(dec), sum(1 for r in dec if r["outcome"] == "win")
    share, p = (w / n if n else None), sign_p(w, n)
    by = {}
    for r in dec:
        c = by.setdefault(r["cohort"], [0, 0])
        c[0] += r["outcome"] == "win"
        c[1] += 1
    countable = {c: v for c, v in by.items() if v[1] >= COHORT_MIN}
    ahead = sum(1 for v in countable.values() if v[0] / v[1] > 0.5)
    wm = winsorised_mean([r["d"] for r in dec])
    a = n >= FLOOR and share is not None and share >= BAR_SHARE and p < BAR_P
    b = len(countable) >= COHORTS_AHEAD and ahead >= COHORTS_AHEAD
    c = wm is not None and wm <= 0
    if a and b and c:
        v = "PASS"
    elif share is not None and share <= 0.5 and n >= FLOOR and len(countable) >= COHORTS_AHEAD:
        v = "FAIL"
    else:
        v = "NOT_DECIDED"
    return {"verdict": v, "departures_decided": n, "wins": w, "share": share, "p": p, "by_cohort": by, "countable_cohorts": len(countable),
            "cohorts_ahead": ahead, "winsorised_mean_d": wm, "conditions": {"a": a, "b": b, "c": c}}


def selection_rule(found, pace, R0, yc, yp):
    """7.6: (rule growth for the rest of year 1, source). The latest-dated readable found entry (date tie: first listed), else the pace."""
    ok = [f for f in found or [] if f.get("number") is not None]
    if not ok:
        return pace, "pace"
    best = max(enumerate(ok), key=lambda t: (str(t[1].get("period_of_evidence") or ""), -t[0]))[1]
    g = g_rest(best["number"], R0, yc, yp)
    return (g, "guidance") if g is not None else (pace, "pace")


# ------------------------------------------------------------------ one name, from its stored seeds
def seed_view(result):
    """(G, option, found, base) of one stored valuation result, or None when it has no checked reply (status not ok*)."""
    if not str(result.get("status", "")).startswith("ok"):
        return None
    c = result.get("checks") or {}
    return (c.get("numbers") or {}).get("rev_growth.y1"), (c.get("options") or {}).get("rev_growth.y1"), c.get("found") or [], result["base"]


def name_row(cohort, results, realised):
    """One P1 row. `results`: the name's stored results (two seeds); `realised(ytd_end)`: the realised_q dict for the first quarter
    after the year-to-date period (7.1). Every name gets a row; `p1` says whether it enters P1 and, if not, why (counted)."""
    views = [seed_view(r) for r in results]
    base = next((v[3] for v in views if v), None) or (results[0].get("base") if results else None) or {}
    y = base.get("ytd") or {}
    R0, yc, yp, pace = base.get("R0"), y.get("revenue"), y.get("revenue_prior"), y.get("rev_growth")
    row = {"cohort": cohort, "pace": pace, "ytd_end": y.get("end")}
    if pace is None or g_rest(pace, R0, yc, yp) is None:
        return dict(row, p1="no_rest_of_year")
    status, G = departure([v[0] if v else None for v in views], pace)
    row.update(departure=status, G=G)
    chosen = next((v for v in views if v and v[0] == G), None) if G is not None else None
    row["option"] = chosen[1] if chosen else None
    row["found"] = chosen[2] if chosen else (next((v[2] for v in views if v), []))
    if status != "departs":
        return dict(row, p1=status)
    rq = realised(y["end"])
    row.update(realised_status=rq.get("status"), realised=rq.get("revenue_growth"), quarter=(rq.get("quarter") or {}).get("report_date"))
    if rq.get("status") != "ok":
        return dict(row, p1="no_realised")
    gq = g_rest(G, R0, yc, yp)
    eq, ep = error(gq, rq["revenue_growth"]), error(pace, rq["revenue_growth"])
    o = outcome(eq, ep)
    if o is None:
        return dict(row, p1="realised_not_positive", g_qwen=gq)
    d = eq - ep if not (math.isinf(eq) and math.isinf(ep)) else 0.0
    return dict(row, p1="tie" if o == "tie" else "scored", g_qwen=gq, e_qwen=eq, e_pace=ep, outcome=o, d=d,
                points_qwen=abs(gq - rq["revenue_growth"]), points_pace=abs(pace - rq["revenue_growth"]))


def readings(rows):
    """The P1 verdict (7.5) and the counts of every row that did not enter it."""
    from collections import Counter
    scored = [r for r in rows if r.get("p1") == "scored"]
    v = verdict(scored)
    flips = sum(1 for r in scored if (r["points_qwen"] < r["points_pace"]) != (r["outcome"] == "win"))
    return dict(v, version=SCORER_VERSION, rows=len(rows), counts=dict(Counter(r.get("p1") for r in rows)),
                winner_changes_under_points=flips)

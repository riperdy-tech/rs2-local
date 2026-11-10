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
    row = {"cohort": cohort, "pace": pace, "ytd_end": y.get("end"), "ytd_accn": y.get("accn"), "R0": R0, "yc": yc, "yp": yp}
    from qwen_c.value import menu                          # the menu's own rule decides whether year 1 has an unreported rest
    if menu._year1_rest(y, R0) is None or g_rest(pace, R0, yc, yp) is None:
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


# ------------------------------------------------------------------ the driver: run once, on or after BY (PREREG v1.0 section 5)
COHORTS = ("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
SEEDS = (1200, 3200)
BY = "2026-12-31"
PRIOR_POOLS = ("archival_2025-12-31", "archival_2025-12-31_nd", "archival_2025-10-01", "archival_2025-10-01_pit", "archival_2026-06-15")
UNREADABLE = "guidance_unreadable: rev_growth.y1 "          # checks writes it to `reverts`: a guidance pick code reverted ("attempted")


def share(rows, key="outcome"):
    """{wins, n, p}: the rows carrying win or loss under `key`, and the one-sided sign test."""
    dec = [r[key] for r in rows if r.get(key) in ("win", "loss")]
    return {"wins": dec.count("win"), "n": len(dec), "p": sign_p(dec.count("win"), len(dec))}


def beside(row, g_realised, g_single):
    """S1 and the single-quarter rule for one name with a realised quarter (reported, never deciding). The forecast of Qwen is its
    departure, else the pace. `s1`: Qwen against the rule R; `single_vs_pace`, `qwen_vs_single`: the latest single quarter's growth."""
    pace = row["pace"]
    g_q = row.get("g_qwen", pace)
    g_r, src = selection_rule(row.get("found"), pace, row["R0"], row["yc"], row["yp"])
    e_q, e_p = error(g_q, g_realised), error(pace, g_realised)
    out = {"rule_source": src, "g_rule": g_r, "s1": outcome(e_q, error(g_r, g_realised))}
    if g_single is not None:
        e_s = error(g_single, g_realised)
        out.update(g_single=g_single, single_vs_pace=outcome(e_s, e_p), qwen_vs_single=outcome(e_q, e_s))
    return out


def score(names, realised, single):
    """Every row and every reading. `names`: [{"meta": {cohort, cik, cell, sector, cap_tercile, in_prior_pool, ...}, "results": the two
    stored results, or None (no packet)}], cohorts in T order. `realised(meta, ytd_end)`: the realised_q dict; `single(meta, row)`:
    the latest single quarter's growth or None. Both are called only where a reading needs them."""
    import statistics
    from collections import Counter
    rows, seen = [], set()
    for n in names:
        meta = dict(n["meta"], first_appearance=n["meta"]["cik"] not in seen)
        seen.add(meta["cik"])
        if n["results"] is None:
            rows.append(dict(meta, p1="no_packet"))
            continue
        views = [seed_view(r) for r in n["results"]]
        tried = sum(1 for r in n["results"] if any(a.startswith(UNREADABLE) for a in (r.get("checks") or {}).get("reverts") or []))
        if not any(views):
            rows.append(dict(meta, p1="no_checked_reply", attempted=tried))
            continue
        row = dict(name_row(meta["cohort"], n["results"], lambda end: realised(meta, end)), **meta, attempted=tried)
        if all(views) and row["p1"] != "no_rest_of_year" and (
                row["departure"] == "departs" or selection_rule(row["found"], row["pace"], row["R0"], row["yc"], row["yp"])[1] == "guidance"):
            rq = realised(meta, row["ytd_end"])
            if rq.get("status") == "ok" and error(row["pace"], rq["revenue_growth"]) is not None:
                row.update(beside(row, rq["revenue_growth"], single(meta, row)))
        rows.append(row)
    scored = [r for r in rows if r["p1"] == "scored"]
    for r in scored:
        r["guidance_found"] = any(f.get("number") is not None for f in r.get("found") or [])

    def cut(key):
        return {str(k): share([r for r in scored if r.get(key) == k]) for k in sorted({r.get(key) for r in scored}, key=str)}
    return {"version": SCORER_VERSION, "by": BY, "p1": readings(rows),
            "attempted": dict(Counter(r["cohort"] for r in rows for _ in range(r.get("attempted", 0)))),
            "sensitivity": {"first_appearance": readings([r for r in rows if r["first_appearance"]]),
                            "without_cohort_1": readings([r for r in rows if r["cohort"] != COHORTS[0]]),
                            "cohorts_2026": readings([r for r in rows if r["cohort"] in COHORTS[2:]]),
                            "without_prior_pools": readings([r for r in rows if not r.get("in_prior_pool")])},
            "s1": share(rows, "s1"),
            "s4": {"median_e_qwen": statistics.median(r["e_qwen"] for r in scored) if scored else None,
                   "median_e_pace": statistics.median(r["e_pace"] for r in scored) if scored else None},
            "single_quarter": {"rule_vs_pace": share(scored, "single_vs_pace"), "qwen_vs_rule": share(scored, "qwen_vs_single")},
            "segments": {k: cut(k) for k in ("option", "guidance_found", "cap_tercile", "sector")},
            "rows": rows}


def main():
    """Reads the four cohorts' stored slots and SEC (online, standing approval) and writes score_nextq.json once. S2, S3 and S5 are
    separate readings (returns; K2's annual reader)."""
    import hashlib
    import json
    import sys
    from datetime import date
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for p in (root / "tools" / "archival_j2", root / "tools" / "paper_books", root):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import book_paths
    import realised as annual
    import realised_q
    import same_filing as sf
    from qwen_c import sec_store
    from qwen_c.value import facts
    if date.today().isoformat() < BY:
        sys.exit(f"STOP: the scorer runs once, on or after {BY} (PREREG section 5); no cohort outcome is read before then")
    value = book_paths.books() / "m3o" / "value"
    out_path = value / "score_nextq.json"
    if out_path.exists():
        sys.exit(f"STOP: {out_path} exists; a score is never overwritten")

    def census(d):
        return [n for n in json.loads((value / d / "pool.json").read_text(encoding="utf-8"))["names"] if n.get("stage") is None]
    prior = {n["cik"] for d in PRIOR_POOLS for n in census(d)}
    names, store = [], {}
    for T in COHORTS:
        d = value / f"archival_cohort_{T}"
        packets = json.loads((d / "runs.json").read_text(encoding="utf-8"))["packets"]
        slots = json.loads((d / "slots.json").read_text(encoding="utf-8"))["slots"]
        for n in census(f"archival_cohort_{T}"):
            t = n["ticker"]
            meta = {"cohort": T, "ticker": t, "cik": n["cik"], "cell": n["cell"], "sector": n["sector"], "cap_tercile": n["cap_tercile"],
                    "in_prior_pool": n["cik"] in prior}
            if not (packets.get(t) or {}).get("packet"):
                names.append({"meta": meta, "results": None})
                continue
            results = []
            for seed in SEEDS:
                s = slots.get(f"{t}:{seed}")
                if s is None:
                    sys.exit(f"STOP: {T} {t}:{seed} has no slot; the scorer runs once, after every slot of all four cohorts")
                raw = Path(s["result"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != s["result_sha256"]:
                    sys.exit(f"STOP: {T} {t}:{seed} result.json does not hash to its slot")
                results.append(json.loads(raw.decode("utf-8")))
            names.append({"meta": meta, "results": results})

    def sec(meta):
        k = (meta["cohort"], meta["cik"])
        if k not in store:
            store[k] = tuple(json.loads(sec_store.get(u, online=True).decode("utf-8"))
                             for u in (facts.companyfacts_url(meta["cik"]), facts.submissions_url(meta["cik"])))
        return store[k]

    def realised(meta, end):
        k = (meta["cohort"], meta["cik"], "rq")
        if k not in store:
            store[k] = realised_q.realised_q(*sec(meta), end, BY)
        return store[k]

    def single(meta, row):
        return sf.quarter_measures(annual.store_facts(sec(meta)[0]), row["ytd_accn"], row["ytd_end"], "operating", None).get("revenue_growth")
    doc = score(names, realised, single)
    out_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

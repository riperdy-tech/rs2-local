"""side_readings.py - the readings of PREREG_cohorts_nextq that are reported and decide nothing (WO_SR1, 2026-11-12).

S2, S3, S5 (v1.0 section 4), S6 and E1 to E5 (amendment 2), E6 (amendment 3) and the run health (amendment 4 item 3). P1 stays in
score_nextq.py and nothing here calls it. Run once by the coordinator, after score_nextq, from the same commit; refuses before BY;
refuses a missing slot or a result that does not hash to its slot; writes <books>/m3o/value/side_readings_nextq.json once (mode "x").

The readings are pure functions on rows (standard library only), so the tests fix every number by hand; the driver comes last.
THE CHOICES THE REGISTRATION LEAVES OPEN (each is also in RR_SR1.md):
- Quartiles: linear interpolation between order statistics, position q * (n - 1) (numpy's default); the median is the 0.5 quantile.
- Spearman: Pearson correlation of average ranks; no figure (None) for n < 3 or when either side has no spread.
- Permutation p: two-sided, 10,000 shuffles of one side's ranks, random.Random(20261120) fresh per call; p = (hits + 1) / (shuffles + 1)
  with a hit being |rho| of the shuffle >= the observed |rho|.
- "Within 5%" / "within 10%" and E6's "differs by more than 5%" are on the log scale: |ln ratio| <= ln(1.05), ln(1.10); > ln(1.05).
- A value of record exists when the two-seed consensus status starts with "ok"; one checked seed gives the record-neutral value,
  annotated one_seed_only, and is still a value of record (E1 needs two checked seeds).
"""
import calendar
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from score_nextq import BY, COHORTS, SEEDS, UNREADABLE

VERSION = "cohorts.side_readings.v1"
WINDOWS = (3, 6, 12)                     # months after T
LOOKBACK_DAYS = 7                        # a close counts when it is at most this many days before the date asked for
SHUFFLES, PERM_SEED = 10_000, 20261120
LN5, LN10 = math.log(1.05), math.log(1.10)
KINDS = ("record", "code_only", "unheld")
MEDIUM_FILE = "slots_think_medium_2026-11-11.json"
ARCHIVAL_ENV = "RS2_ARCHIVAL_COE_DIR"
OUT_NAME = "side_readings_nextq.json"
S5_EXTRA_STATUSES = ("timeout", "context_overflow", "infra_retry", "infra_fatal", "engine_defect")   # last attempt's outcome: not scored


# ------------------------------------------------------------------ numbers
def quantile(xs, q):
    """Linear interpolation at position q * (n - 1) of the sorted values; None for no values."""
    if not xs:
        return None
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def quartiles(xs):
    return {"n": len(xs), "q1": quantile(xs, 0.25), "median": quantile(xs, 0.5), "q3": quantile(xs, 0.75)}


def ranks(xs):
    """1-based ranks, ties at their average."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _centred(r):
    m = sum(r) / len(r)
    c = [x - m for x in r]
    return c, math.sqrt(sum(x * x for x in c))


def spearman(xs, ys):
    """Rank correlation (average ranks); None for fewer than 3 pairs or no spread on a side."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    cx, sx = _centred(ranks(xs))
    cy, sy = _centred(ranks(ys))
    if sx == 0 or sy == 0:
        return None
    return sum(a * b for a, b in zip(cx, cy)) / (sx * sy)


def spearman_p(xs, ys, shuffles=SHUFFLES, seed=PERM_SEED):
    """Two-sided permutation p of the rank correlation: (hits + 1) / (shuffles + 1); None where the correlation has no figure."""
    rho = spearman(xs, ys)
    if rho is None:
        return None
    cx, sx = _centred(ranks(xs))
    ry = ranks(ys)
    _, sy = _centred(ry)
    my = sum(ry) / len(ry)
    ry = [x - my for x in ry]
    rng, hits = random.Random(seed), 0
    for _ in range(shuffles):
        rng.shuffle(ry)
        if abs(sum(a * b for a, b in zip(cx, ry)) / (sx * sy)) >= abs(rho) - 1e-12:
            hits += 1
    return (hits + 1) / (shuffles + 1)


def ratio(v, close):
    """Value over price: None without a value or without a positive price."""
    return None if v is None or close is None or not close > 0 else v / close


def ln_ratio(a, b):
    """ln(a / b), None unless both are numbers above zero."""
    return None if a is None or b is None or not (a > 0 and b > 0) else math.log(a / b)


def ok(status):
    return str(status).startswith("ok")


# ------------------------------------------------------------------ prices and windows
def add_months(d, k):
    """The same day of the month k months on, clamped to the month's last day."""
    y, m = divmod(d.year * 12 + d.month - 1 + k, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def price_at(series, d):
    """The close on d or the latest session before it, at most LOOKBACK_DAYS earlier; None otherwise."""
    for k in range(LOOKBACK_DAYS + 1):
        v = (series or {}).get((d - timedelta(k)).isoformat())
        if v is not None:
            return v
    return None


def simple_return(series, T, end):
    """(return, None) or (None, reason)."""
    if not series:
        return None, "no_price_series"
    p0, p1 = price_at(series, T), price_at(series, end)
    if p0 is None:
        return None, "no_price_at_T"
    if not p0 > 0:
        return None, "price_at_T_not_positive"
    if p1 is None:
        return None, "no_price_at_end"
    return p1 / p0 - 1, None


def prices_sha256(prices):
    rows = [[t, d, c] for t in sorted(prices) for d, c in sorted(prices[t].items())]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def with_returns(rows, prices, last_session, months=WINDOWS):
    """(rows with ret / abn / ret_reason per window, windows {T: {m: {end, closed}}}, gap {T: {m: counts}}). A window ends T + m months
    and is reported only when that date is on or before the last completed session. The abnormal return is the return less the
    equal-weight mean of the cohort's census names that have one; a name without a return is counted (survivor gap), not dropped."""
    wins = {T: {m: {"end": add_months(date.fromisoformat(T), m)} for m in months} for T in COHORTS}
    for T in wins:
        for m, w in wins[T].items():
            w["closed"] = w["end"] <= last_session
    out = [dict(r, ret={}, abn={}, ret_reason={}) for r in rows]
    for r in out:
        T = date.fromisoformat(r["cohort"])
        for m in months:
            w = wins[r["cohort"]][m]
            if not w["closed"]:
                r["ret"][str(m)], r["ret_reason"][str(m)] = None, "window_not_closed"
                continue
            r["ret"][str(m)], r["ret_reason"][str(m)] = simple_return(prices.get(r["ticker"]), T, w["end"])
    gap = {}
    for T in wins:
        mine = [r for r in out if r["cohort"] == T]
        gap[T] = {}
        for m in months:
            if not wins[T][m]["closed"]:
                gap[T][str(m)] = {"window_not_closed": True}
                for r in mine:
                    r["abn"][str(m)] = None
                continue
            have = [r["ret"][str(m)] for r in mine if r["ret"][str(m)] is not None]
            mean = sum(have) / len(have) if have else None
            for r in mine:
                v = r["ret"][str(m)]
                r["abn"][str(m)] = None if v is None or mean is None else v - mean
            gap[T][str(m)] = {"census": len(mine), "with_return": len(have), "no_price_series": len(mine) - len(have),
                              "reasons": dict(Counter(r["ret_reason"][str(m)] for r in mine if r["ret"][str(m)] is None)),
                              "equal_weight_mean": mean}
    return out, {T: {str(m): {"end": w["end"].isoformat(), "closed": w["closed"]} for m, w in ws.items()} for T, ws in wins.items()}, gap


# ------------------------------------------------------------------ one row per census name
def _run_neutral(result):
    """The record-neutral (code-only) value a stored seed result computed at run time."""
    return ((((result.get("checks") or {}).get("diagnostics")) or {}).get("record_neutral") or {}).get("value")


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def make_row(meta, results, cons):
    """`meta`: cohort, ticker, cik, sector, cap_tercile, close. `results`: {seed: stored result} or None (no packet). `cons`: {held,
    unheld: a consensus.combine result or None; held_error, unheld_error: text or None}. A name with no packet or no checked seed has
    a row with its reason and no values."""
    row = dict(meta, reason=None, seed_status={}, seed_base={}, record=None, code_only=None, unheld=None, annotations=[],
               held_at_record=False, one_seed_only=False, rebuild_matches_run=None, vp={k: None for k in KINDS})
    if results is None:
        return dict(row, reason="no_packet")
    row["seed_status"] = {str(s): r.get("status") for s, r in results.items()}
    row["seed_base"] = {str(s): ((r.get("values") or {}).get("base") if ok(r.get("status")) else None) for s, r in results.items()}
    if not any(ok(r.get("status")) for r in results.values()):
        return dict(row, reason="no_checked_seed")
    if cons.get("held_error"):
        return dict(row, reason=f"consensus_error: {cons['held_error']}")
    res = cons["held"]
    if not ok(res.get("status")):
        return dict(row, reason=f"consensus_{res.get('status')}" + (f": {res.get('reason')}" if res.get("reason") else ""))
    v = res.get("values") or {}
    row["record"] = {"status": res["status"], "base": v.get("base"), "bear": v.get("bear"), "bull": v.get("bull")}
    row["code_only"] = (((res.get("diagnostics") or {}).get("record_neutral")) or {}).get("value")
    row["annotations"] = list(res.get("annotations") or [])
    row["held_at_record"] = any(a.startswith("held_at_record") for a in row["annotations"])
    row["one_seed_only"] = any(a.startswith("one_seed_only") for a in row["annotations"])
    at_run = [_run_neutral(r) for r in results.values() if ok(r.get("status"))]
    row["rebuild_matches_run"] = all(_same(x, row["code_only"]) for x in at_run)   # the offline desk is the run's desk
    if cons.get("unheld_error"):
        row["unheld_error"] = cons["unheld_error"]
    elif cons.get("unheld") is not None and ok(cons["unheld"].get("status")):
        row["unheld"] = (cons["unheld"].get("values") or {}).get("base")
    row["vp"] = {"record": ratio(row["record"]["base"], meta["close"]), "code_only": ratio(row["code_only"], meta["close"]),
                 "unheld": ratio(row["unheld"], meta["close"])}
    return row


# ------------------------------------------------------------------ the readings
def _pairs(rows, kind, m, log=False):
    """([x], [y], counts): value over price (or its log) against the abnormal return of the m-month window."""
    xs, ys, c = [], [], Counter()
    for r in rows:
        x, y = r["vp"][kind], r["abn"][str(m)]
        if x is None or y is None:
            c["missing_value_or_return"] += 1
        elif log and not x > 0:
            c["non_positive_value"] += 1
        else:
            xs.append(math.log(x) if log else x)
            ys.append(y)
    return xs, ys, dict(c)


def _closed(wins, T, m):
    w = wins[T][str(m)]
    return w["closed"], w["end"]


def s2(rows, wins, months=(3, 6)):
    """Per cohort and window: the rank correlation of value / price with the abnormal return and its permutation p, for the value of
    record, the code-only value and the value with the year-1 departure not held. No pooled figure."""
    out = {}
    for T in COHORTS:
        mine = [r for r in rows if r["cohort"] == T]
        out[T] = {}
        for m in months:
            closed, end = _closed(wins, T, m)
            if not closed:
                out[T][f"{m}m"] = {"window_not_closed": True, "end": end}
                continue
            cell = {"end": end}
            for k in KINDS:
                xs, ys, c = _pairs(mine, k, m)
                cell[k] = {"n": len(xs), "rho": spearman(xs, ys), "p_two_sided_permutation": spearman_p(xs, ys), "left_out": c}
            out[T][f"{m}m"] = cell
    return out


def _side(rows, m):
    a = [r["abn"][str(m)] for r in rows]
    return {"n": len(a), "share_positive": (sum(1 for x in a if x > 0) / len(a)) if a else None,
            "mean_abnormal_return": (sum(a) / len(a)) if a else None, "tickers": sorted(r["ticker"] for r in rows)}


def top_third(rows, kind):
    """The first n // 3 rows by value / price descending, ties by ticker."""
    return sorted(rows, key=lambda r: (-r["vp"][kind], r["ticker"]))[:len(rows) // 3]


def s3(rows, wins, m=6):
    """Per cohort, the 6-month window: the names in Qwen's top third and not in the code-only top third, and the reverse."""
    out = {}
    for T in COHORTS:
        closed, end = _closed(wins, T, m)
        if not closed:
            out[T] = {"window_not_closed": True, "end": end}
            continue
        el = [r for r in rows if r["cohort"] == T and r["vp"]["record"] is not None and r["vp"]["code_only"] is not None
              and r["abn"][str(m)] is not None]
        q, c = top_third(el, "record"), top_third(el, "code_only")
        qs, cs = {r["ticker"] for r in q}, {r["ticker"] for r in c}
        out[T] = {"end": end, "eligible": len(el), "top_third_n": len(el) // 3,
                  "qwen_not_code_only": _side([r for r in q if r["ticker"] not in cs], m),
                  "code_only_not_qwen": _side([r for r in c if r["ticker"] not in qs], m)}
    return out


def s6(rows, wins, m=12, cohorts=COHORTS[:2]):
    """Cohorts 1 and 2, the 12-month window: rank correlation of ln(value / price) with the abnormal return; a value at or below zero
    has no logarithm and is excluded and counted. Per cohort."""
    out = {}
    for T in cohorts:
        closed, end = _closed(wins, T, m)
        if not closed:
            out[T] = {"window_not_closed": True, "end": end}
            continue
        mine = [r for r in rows if r["cohort"] == T]
        out[T] = {"end": end}
        for k in ("record", "code_only"):
            xs, ys, c = _pairs(mine, k, m, log=True)
            out[T][k] = {"n": len(xs), "rho": spearman(xs, ys), "left_out": c}
    return out


def e1_summary(xs, excluded):
    return {"n": len(xs), "median": quantile(xs, 0.5), "share_within_5pct": (sum(1 for x in xs if x <= LN5) / len(xs)) if xs else None,
            "excluded": dict(excluded)}


def _agreement(rows):
    xs, ex = [], Counter()
    for r in rows:
        b = [r["seed_base"].get(str(s)) for s in SEEDS]
        if any(x is None for x in b):
            ex["not_two_checked_seeds"] += 1
            continue
        g = ln_ratio(*b)
        if g is None:
            ex["non_positive_base"] += 1
        else:
            xs.append(abs(g))
    return xs, ex


def e1(rows):
    """Per name with two checked seeds |ln(base at 1200 / base at 3200)|: per cohort and over all four."""
    out = {T: e1_summary(*_agreement([r for r in rows if r["cohort"] == T])) for T in COHORTS}
    out["all"] = e1_summary(*_agreement(rows))
    return out


def e2(rows):
    """A company (by CIK) in more than one cohort: for each pair of adjacent appearances in T order, (ln V2 - ln V1) - (ln C2 - ln C1),
    V the value of record and C the code-only value."""
    by = {}
    for r in rows:
        by.setdefault(r["cik"], []).append(r)
    xs, left, pairs, companies = [], Counter(), 0, 0
    for apps in by.values():
        apps = sorted(apps, key=lambda r: COHORTS.index(r["cohort"]))
        companies += len(apps) > 1
        for a, b in zip(apps, apps[1:]):
            pairs += 1
            v = [x["record"]["base"] if x["record"] else None for x in (a, b)]
            c = [x["code_only"] for x in (a, b)]
            if any(x is None for x in v):
                left["no_value_of_record"] += 1
            elif any(x is None for x in c):
                left["no_code_only_value"] += 1
            elif not all(x > 0 for x in v + c):
                left["non_positive_value"] += 1
            else:
                xs.append(abs((math.log(v[1]) - math.log(v[0])) - (math.log(c[1]) - math.log(c[0]))))
    return {"companies_in_more_than_one_cohort": companies, "pairs": pairs, "used": len(xs), "median_abs_remainder": quantile(xs, 0.5),
            "share_within_5pct": (sum(1 for x in xs if x <= LN5) / len(xs)) if xs else None,
            "share_within_10pct": (sum(1 for x in xs if x <= LN10) / len(xs)) if xs else None, "left_out": dict(left)}


def e3(pool_names, rows):
    """Per cohort: names drawn (every pool.json name), in the census, with a value of record; the same by sector.
    `pool_names`: {T: [{ticker, sector, stage}]}."""
    out = {}
    for T in COHORTS:
        valued = {r["ticker"] for r in rows if r["cohort"] == T and r["record"] is not None}
        cell = {"drawn": 0, "census": 0, "valued": 0}
        sec = {}
        for n in pool_names[T]:
            s = sec.setdefault(str(n.get("sector")), {"drawn": 0, "census": 0, "valued": 0})
            for d in (cell, s):
                d["drawn"] += 1
                d["census"] += n.get("stage") is None
                d["valued"] += n.get("stage") is None and n["ticker"] in valued
        out[T] = dict(cell, by_sector=dict(sorted(sec.items())))
    return out


def e4(rows):
    """Per name ln(bull / bear) of the value of record; non-positive legs excluded and counted. Per cohort and overall."""
    def one(rs):
        xs, ex = [], 0
        for r in rs:
            if r["record"] is None:
                continue
            g = ln_ratio(r["record"]["bull"], r["record"]["bear"])
            if g is None:
                ex += 1
            else:
                xs.append(g)
        return dict(quartiles(xs), excluded_non_positive_leg=ex)
    return dict({T: one([r for r in rows if r["cohort"] == T]) for T in COHORTS}, all=one(rows))


def e5(rows):
    """Per cohort: quartiles of value of record / price and of code-only value / price."""
    return {T: {k: quartiles([r["vp"][k] for r in rows if r["cohort"] == T and r["vp"][k] is not None]) for k in ("record", "code_only")}
            for T in COHORTS}


def _seed_base(r):
    return (r.get("values") or {}).get("base") if ok(r.get("status")) else None


def e6(entries):
    """Cohort 1 names with both seeds at both thinking levels. entry: {high, medium: {seed: result}, seconds: {level: [slot seconds]},
    value: {level: base value of record or None}}."""
    out = {"names": len(entries), "levels": {}}
    for lv in ("high", "medium"):
        xs, ex = _agreement([{"seed_base": {str(s): _seed_base(e[lv][s]) for s in SEEDS}} for e in entries])
        picked = reverted = 0
        for e in entries:
            for r in e[lv].values():
                c = r.get("checks")
                if c is None:
                    continue
                rv = any(a.startswith(UNREADABLE) for a in c.get("reverts") or [])
                if (c.get("options") or {}).get("rev_growth.y1") == "guidance" or rv:
                    picked += 1
                    reverted += rv
        sec = [x for e in entries for x in e["seconds"][lv] if x is not None]
        out["levels"][lv] = {"e1": e1_summary(xs, ex),
                             "guidance_picks": {"picked": picked, "reverted_unreadable": reverted, "share": (reverted / picked) if picked else None},
                             "seconds_per_slot": {"n": len(sec), "mean": (sum(sec) / len(sec)) if sec else None,
                                                  "median": quantile(sec, 0.5)}}
    diff, n, ex = 0, 0, Counter()
    for e in entries:
        a, b = e["value"]["high"], e["value"]["medium"]
        if a is None or b is None:
            ex["no_value_of_record_at_a_level"] += 1
        elif ln_ratio(a, b) is None:
            ex["non_positive_value"] += 1
        else:
            n += 1
            diff += abs(ln_ratio(a, b)) > LN5
    out["value_of_record_differs_more_than_5pct"] = {"n": n, "differs": diff, "share": (diff / n) if n else None, "excluded": dict(ex)}
    return out


def run_health(results):
    """From each stored result's attempts: attempts that ended at their cap (done_reason length), server errors (infra_retry),
    timeouts, slots that needed a second attempt. `results`: [result]."""
    c = Counter()
    for r in results:
        att = r.get("attempts")
        if att is None:
            c["results_without_attempts"] += 1
            continue
        c["slots"] += 1
        c["attempts"] += len(att)
        c["slots_with_second_attempt"] += len(att) >= 2
        for a in att:
            c["attempts_done_reason_length"] += a.get("done_reason") == "length"
            c["attempts_server_error"] += a.get("outcome") == "infra_retry"
            c["attempts_timeout"] += a.get("outcome") == "timeout"
    return dict(c)


# ------------------------------------------------------------------ the offline consensus (settled points 1 and 2)
def consensus_of(cohort_dir, name, packet_entry, results, held=True):
    """The two-seed consensus of one census name rebuilt offline (greedy_check.score, formation_consensus): the desk prepared from the stored
    SEC documents with the cohort's pinned cost of equity, then consensus.combine. `results`: {seed: stored result}. held=False values
    the year-1 departure: menu.HELD is emptied for the call (menu.of_record then returns the reply unchanged) and restored after. The
    pinned cost of equity is read from the environment on every call (qwen_c/value/coe.py caches nothing), set per call and restored."""
    from qwen_c.value import consensus, menu, run as vrun, task
    packet = json.loads(Path(packet_entry["packet"]).read_text(encoding="utf-8"))
    ok_res = {str(s): r for s, r in results.items() if ok(r.get("status"))}
    env, saved = str(Path(cohort_dir) / "coe_pinned"), (os.environ.get(ARCHIVAL_ENV), menu.HELD)
    os.environ[ARCHIVAL_ENV] = env
    if not held:
        menu.HELD = ()
    try:
        mc = name.get("market_cap")
        f, b, bar, record, r, prov, fy_ends = vrun.prepare(packet, name["cik"], str(name["sector"]), 0 if mc is None else mc,
                                                          online=False, family=name["family"])
        ids = task.evidence_ids(packet, record, b, bar, r, prov)
        route = "financial" if name["family"] in vrun.FINANCIAL else "operating"
        return consensus.combine(ok_res, ids, b, bar, r, fy_ends, route)
    finally:
        menu.HELD = saved[1]
        if saved[0] is None:
            os.environ.pop(ARCHIVAL_ENV, None)
        else:
            os.environ[ARCHIVAL_ENV] = saved[0]


# ------------------------------------------------------------------ S5 through K2's annual reader, unchanged
def j2_annual(cohort_dir, pool_sha256):
    """tools/archival_j2/score.py score(), not edited: SEEDS set to the cohorts' and the statuses a cohort result can end with (the last
    attempt's outcome) added to KNOWN, so that they are "not scored" and never a stop. It writes its own score.json / score.md in the
    cohort folder. Returns its per-key summary (rows and excluded lists stay in that score.json), or {"not_available": the refusal}."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "archival_j2" / "score.py"
    spec = importlib.util.spec_from_file_location("j2_score_for_cohorts", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SEEDS = tuple(SEEDS)
    m.KNOWN = tuple(dict.fromkeys(tuple(m.KNOWN) + S5_EXTRA_STATUSES))
    try:
        body = json.loads((Path(cohort_dir) / "pool.json").read_text(encoding="utf-8"))
        store = {"pool_json": body.get("store"), "j2_default": m.census(body)["store"]}
        doc = m.score(cohort_dir, pool_sha256)
    except (Exception, SystemExit) as e:                    # J2's Stop is a SystemExit; a side reading never stops the others
        return {"not_available": f"{type(e).__name__}: {e}"}
    return {"store": store, "keys": {k: {x: v for x, v in kv.items() if x not in ("rows", "excluded")} for k, kv in doc["keys"].items()},
            "details_in": str(Path(cohort_dir) / "score.json")}


# ------------------------------------------------------------------ the driver
def _download(yf, tickers, start, end):
    df = yf.download(tickers, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=True, actions=False,
                     progress=False, group_by="ticker", threads=False)
    prices = {}
    for t in tickers:
        try:
            sub = df[t]                                     # one ticker or many: yfinance may or may not key the columns by ticker
        except KeyError:
            if len(tickers) > 1:
                continue
            sub = df
        for idx, rec in sub.iterrows():
            o, c = rec.get("Open"), rec.get("Close")
            if o == o and c == c and o is not None and c is not None and idx.date() <= end:
                prices.setdefault(t, {})[idx.date().isoformat()] = float(c)
    return prices


def yahoo_fetch(tickers, start, end, retries=2, pause=60):
    """(source, {ticker: {date: adjusted close}}). Writes nothing. The download parameters are forward_ledger.fetch_prices's. A ticker
    that comes back with no row is asked again, `retries` times after `pause` seconds (the pool builds lost names to Yahoo's rate
    limit; the output is written once, so a name lost here could not be fetched later)."""
    import time
    import yfinance as yf
    tickers = sorted(tickers)
    prices = _download(yf, tickers, start, end)
    for _ in range(retries):
        missing = [t for t in tickers if t not in prices]
        if not missing:
            break
        time.sleep(pause)
        prices.update(_download(yf, missing, start, end))
    return f"yfinance {yf.__version__} download auto_adjust=True, empty tickers retried {retries}x", prices


def _read_result(T, t, seed, slot, missing_ok=False):
    p = Path(slot["result"])
    if not p.exists() and missing_ok:
        return None
    try:
        raw = p.read_bytes()
    except OSError as e:
        sys.exit(f"STOP: {T} {t}:{seed} result.json unreadable ({e})")
    if hashlib.sha256(raw).hexdigest() != slot["result_sha256"]:
        sys.exit(f"STOP: {T} {t}:{seed} result.json does not hash to its slot")
    return json.loads(raw.decode("utf-8"))


def _cons(fn, d, n, packet, results):
    out = {}
    for key, held in (("held", True), ("unheld", False)):
        try:
            out[key], out[f"{key}_error"] = fn(d, n, packet, results, held=held), None
        except Exception as e:                              # recorded on the row with its reason, never silently dropped
            out[key], out[f"{key}_error"] = None, f"{type(e).__name__}: {str(e)[:300]}"
    return out


def run(value, today, *, consensus_of, fetch, s5, last_session):
    """Reads the four cohorts' stored slots and writes side_readings_nextq.json once. `today`: ISO date. `consensus_of`, `fetch`, `s5`
    and `last_session` are injected (the tests use synthetic ones)."""
    if today < BY:
        sys.exit(f"STOP: the side readings run once, on or after {BY} (PREREG section 5); no cohort outcome is read before then")
    value = Path(value)
    out_path = value / OUT_NAME
    if out_path.exists():
        sys.exit(f"STOP: {out_path} exists; the side readings are never overwritten")
    rows, pool_names, results_all, cohort_dirs, pool_sha = [], {}, {}, {}, {}
    packets_all, census_names = {}, {}
    for T in COHORTS:
        d = value / f"archival_cohort_{T}"
        pool = json.loads((d / "pool.json").read_text(encoding="utf-8"))
        runs = json.loads((d / "runs.json").read_text(encoding="utf-8"))
        slots = json.loads((d / "slots.json").read_text(encoding="utf-8"))["slots"]
        cohort_dirs[T], pool_sha[T], packets_all[T] = d, runs["pool_sha256"], runs["packets"]
        pool_names[T] = [{"ticker": n["ticker"], "sector": n.get("sector"), "stage": n.get("stage")} for n in pool["names"]]
        results_all[T], census_names[T] = [], {}
        for n in pool["names"]:
            if n.get("stage") is not None:
                continue
            t = n["ticker"]
            census_names[T][t] = n
            meta = {"cohort": T, "ticker": t, "cik": n["cik"], "sector": n["sector"], "cap_tercile": n["cap_tercile"], "close": n.get("close")}
            if not (runs["packets"].get(t) or {}).get("packet"):
                rows.append(make_row(meta, None, None))
                continue
            res = {}
            for seed in SEEDS:
                s = slots.get(f"{t}:{seed}")
                if s is None:
                    sys.exit(f"STOP: {T} {t}:{seed} has no slot; the side readings run once, after every slot of all four cohorts")
                res[seed] = _read_result(T, t, seed, s)
            results_all[T] += list(res.values())
            has = any(ok(r.get("status")) for r in res.values())
            rows.append(make_row(meta, res, _cons(consensus_of, d, n, runs["packets"][t], res) if has else None))
    last = last_session()
    tickers = sorted({r["ticker"] for r in rows})
    start = min(date.fromisoformat(T) for T in COHORTS) - timedelta(days=LOOKBACK_DAYS + 3)
    source, prices = fetch(tickers, start, last)
    rows, wins, gap = with_returns(rows, prices, last)

    medium = {"not_available": f"{MEDIUM_FILE} is not in the cohort folder"}
    mp = cohort_dirs[COHORTS[0]] / MEDIUM_FILE
    if mp.exists():
        mslots = json.loads(mp.read_text(encoding="utf-8"))["slots"]
        hslots = json.loads((cohort_dirs[COHORTS[0]] / "slots.json").read_text(encoding="utf-8"))["slots"]
        entries, left = [], Counter()
        by_t = {r["ticker"]: r for r in rows if r["cohort"] == COHORTS[0]}
        for t, n in census_names[COHORTS[0]].items():
            if not (packets_all[COHORTS[0]].get(t) or {}).get("packet"):
                continue
            keys = [f"{t}:{s}" for s in SEEDS]
            if not all(k in mslots and k in hslots for k in keys):
                left["not_at_both_levels"] += 1
                continue
            hi = {s: _read_result(COHORTS[0], t, s, hslots[f"{t}:{s}"]) for s in SEEDS}
            me = {s: _read_result(COHORTS[0], t, s, mslots[f"{t}:{s}"], missing_ok=True) for s in SEEDS}
            if any(v is None for v in me.values()):
                left["medium_result_missing"] += 1
                continue
            mv = None
            if any(ok(r.get("status")) for r in me.values()):
                try:
                    mv = ((consensus_of(cohort_dirs[COHORTS[0]], n, packets_all[COHORTS[0]][t], me, held=True).get("values")) or {}).get("base")
                except Exception:
                    left["medium_consensus_error"] += 1
            hr = by_t[t]["record"]
            entries.append({"high": hi, "medium": me, "value": {"high": hr["base"] if hr else None, "medium": mv},
                            "seconds": {"high": [hslots[k].get("seconds") for k in keys], "medium": [mslots[k].get("seconds") for k in keys]}})
        medium = dict(e6(entries), left_out=dict(left), medium_slots_file=MEDIUM_FILE)

    health = {T: run_health(results_all[T]) for T in COHORTS}
    doc = {"version": VERSION, "by": BY, "run_on": today, "decides": "nothing", "last_completed_session": last.isoformat(),
           "quartile_rule": "linear interpolation at position q * (n - 1)", "permutation": {"shuffles": SHUFFLES, "seed": PERM_SEED},
           "price": {"source": source, "rows_sha256": prices_sha256(prices), "tickers_requested": len(tickers), "tickers_with_series": len(prices)},
           "windows": wins, "survivor_gap": gap,
           "S2": s2(rows, wins), "S3": s3(rows, wins), "S6": s6(rows, wins), "E1": e1(rows), "E2": e2(rows),
           "E3": e3(pool_names, rows), "E4": e4(rows), "E5": e5(rows), "E6": medium, "run_health": health,
           "rows_by_reason": {T: dict(Counter(r["reason"] or "value_of_record" for r in rows if r["cohort"] == T)) for T in COHORTS},
           # the offline consensus is trusted only where its code-only value equals the one each seed computed at run time
           "rebuild_check": {T: dict(Counter({True: "matches_run", False: "DIFFERS_FROM_RUN"}[r["rebuild_matches_run"]]
                                             for r in rows if r["cohort"] == T and r["record"] is not None)) for T in COHORTS},
           "value_of_record_from_one_seed": {T: sum(1 for r in rows if r["cohort"] == T and r["one_seed_only"]) for T in COHORTS}}
    for k in ("S2", "S3", "S6", "E1", "E2", "E3", "E4", "E5", "E6", "run_health", "survivor_gap"):
        doc[k] = dict(doc[k], decides="nothing")
    doc["S5"] = {"decides": "nothing", **{T: s5(cohort_dirs[T], pool_sha[T]) for T in COHORTS[:2]}}    # last: it writes its own score.json
    doc["rows"] = rows
    with open(out_path, "x", encoding="utf-8") as fh:                                    # never overwritten
        fh.write(json.dumps(doc, indent=1, default=str))
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}, indent=1, default=str))
    return 0


def main():
    from datetime import date as _date
    if _date.today().isoformat() < BY:
        sys.exit(f"STOP: the side readings run once, on or after {BY} (PREREG section 5); no cohort outcome is read before then")
    root = Path(__file__).resolve().parents[2]
    for p in (root / "tools" / "archival_j2", root / "tools" / "paper_books", root):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import book_paths
    import forward_ledger
    return run(book_paths.books() / "m3o" / "value", _date.today().isoformat(), consensus_of=consensus_of, fetch=yahoo_fetch,
               s5=j2_annual, last_session=forward_ledger.last_completed_session)


if __name__ == "__main__":
    sys.exit(main())

"""Revision 19, Part I (brief_rev19.md section 10): the levels method's earnings basis. MEASURE ONLY: no engine change, no verdict, no threshold.

  python levels_eps_basis.py --day <day.json from build_day.py> [--names <file, when the day is anonymous>] [--show MU] [--out <result.json>]

The levels method values a name on the vendor's consensus EPS levels (next-FY averages for "0y" and "+1y"), whose basis (GAAP or adjusted) is unknown;
the filed D&A and capex it is combined with are GAAP-filed. For every book name the levels method valued on the day this measures, from the vendor's
year-ago EPS (`estimates["0y"]["eps"]["year_ago"]`, the vendor's own figure for the fiscal year the filings hold) and the filed base year:

  (a) ya_over_filed       year-ago EPS / filed diluted EPS (net income / filed diluted shares, on today's share basis)
  (b) ya_over_filed_plus  year-ago EPS / (filed diluted EPS + stock pay per diluted share): before tax and after tax at tax_L
                          (throughcycle_record.tax_rate of the base year's record); stock pay = the filed base year's `sbc`
  (c) class               "loss_maker" (filed diluted EPS below zero: the 2% rules mean nothing against a loss, so these are not classed by sign), else
                          "gaap_like" (year-ago EPS within 2% of filed), else "adjusted_like" (within 2% of filed plus stock pay, before tax, or above
                          filed by more than 2%), else "unclassified"; a name with no vendor year-ago EPS is "no_vendor_year_ago" and one with no usable
                          filed EPS is "no_filed_basis": both are counted, not classed
  (d) restated_ratio      the reference value if both levels were restated to the filed basis (vendor EPS x filed / vendor year-ago EPS) / today's reference

Reported: counts per class, the medians of (a), (b) and (d) overall and per class, and the row of the one development name asked for (--show, default MU).
No other name is printed or written; the day file's rows, when anonymous, are looked up through --names, in memory only. Offline: sockets are blocked.
The reviewer designs the correctness rule from this; nothing here changes what the engine does.
"""
import argparse
import copy
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "acceptance_r18"))
import accept_common as ac  # noqa: E402

TOL = 0.02                       # the brief's 2%
CLASSES = ("gaap_like", "adjusted_like", "loss_maker", "unclassified", "no_vendor_year_ago", "no_filed_basis")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _near(x, ref):
    """x within TOL of ref, relative to |ref| (a reference of 0.0 admits only 0.0)."""
    return abs(x - ref) <= TOL * abs(ref)


def measure(ya, filed_eps, stock_pay_ps, tax_l):
    """The (a)-(c) figures of one name, from plain numbers. `ya` the vendor's year-ago EPS, `filed_eps` the filed diluted EPS of the base year,
    `stock_pay_ps` the stock pay per diluted share (None when not filed), `tax_l` the through-cycle tax rate.
    Returns {"ya", "filed_eps", "stock_pay_ps", "ya_over_filed", "ya_over_filed_plus_pre_tax", "ya_over_filed_plus_after_tax", "class", "restate"}
    where `restate` is filed / ya (the factor that turns the vendor's levels into the filed basis) or None."""
    out = {"ya": ya, "filed_eps": filed_eps, "stock_pay_ps": stock_pay_ps, "tax_l": tax_l, "ya_over_filed": None,
           "ya_over_filed_plus_pre_tax": None, "ya_over_filed_plus_after_tax": None, "class": "no_filed_basis", "restate": None}
    if not _num(ya):
        out["class"] = "no_vendor_year_ago"                      # revision 19 follow-up (C1): the vendor gave no year-ago EPS; that is not a missing filing
        return out
    if not _num(filed_eps):
        return out
    plus_pre = filed_eps + stock_pay_ps if _num(stock_pay_ps) else None
    plus_after = filed_eps + stock_pay_ps * (1.0 - tax_l) if _num(stock_pay_ps) and _num(tax_l) else None
    if filed_eps != 0:
        out["ya_over_filed"] = ya / filed_eps
    if plus_pre:
        out["ya_over_filed_plus_pre_tax"] = ya / plus_pre
    if plus_after:
        out["ya_over_filed_plus_after_tax"] = ya / plus_after
    if filed_eps < 0:
        out["class"] = "loss_maker"
    elif _near(ya, filed_eps):
        out["class"] = "gaap_like"
    elif (plus_pre is not None and _near(ya, plus_pre)) or ya > filed_eps + TOL * abs(filed_eps):
        out["class"] = "adjusted_like"
    else:
        out["class"] = "unclassified"
    if ya > 0 and filed_eps > 0:
        out["restate"] = filed_eps / ya
    return out


def restated_estimates(estimates, factor):
    """A copy of the vendor's estimates with the two EPS levels the levels method reads multiplied by `factor` (everything else untouched)."""
    est = copy.deepcopy(estimates)
    for key in ("0y", "+1y"):
        eps = ((est.get(key) or {}).get("eps")) or {}
        if _num(eps.get("avg")):
            eps["avg"] = eps["avg"] * factor
    return est


def _median(xs):
    xs = [x for x in xs if _num(x)]
    return statistics.median(xs) if xs else None


def summarize(records):
    """Aggregates over the per-name measures (no names): counts per class, medians overall and per class."""
    fields = ("ya_over_filed", "ya_over_filed_plus_pre_tax", "ya_over_filed_plus_after_tax", "restated_ratio")
    out = {"names": len(records), "counts": {c: sum(1 for r in records if r["class"] == c) for c in CLASSES},
           "medians": {f: _median(r.get(f) for r in records) for f in fields}, "by_class": {}}
    for c in CLASSES:
        sub = [r for r in records if r["class"] == c]
        out["by_class"][c] = {"n": len(sub), **{f: _median(r.get(f) for r in sub) for f in fields},
                              "restated_ratio_available": sum(1 for r in sub if _num(r.get("restated_ratio"))),
                              "filed_eps_not_positive": sum(1 for r in sub if _num(r.get("filed_eps")) and r["filed_eps"] <= 0)}
    return out


def _ticker_map(rows, names_path):
    """{row key: ticker}: the row's own ticker, else, for an anonymous day (keys are hashes of names, no ticker in the row), the name `names_path` hashes to."""
    import build_day
    named = {}
    if names_path is not None:
        for t in (l.strip() for l in Path(names_path).read_text(encoding="utf-8").splitlines()):
            if t:
                named[build_day._key(t, True)] = t
    out = {}
    for key, r in rows.items():
        t = r.get("ticker") or named.get(key)
        if t:
            out[key] = t
    return out


def run(ns, rows, names_path=None, show="MU"):
    """The measurement over a day's rows. Returns the result dict (aggregates plus `show`'s row), no other name."""
    import depth_membership
    import reference_ledger as rl
    cap, cref = ns.cap, ns.cref
    tick = _ticker_map(rows, names_path)
    levels_keys = sorted(k for k, r in rows.items()
                         if isinstance(r.get("reference"), dict) and r["reference"].get("method") == "levels" and _num(r["reference"].get("value")))
    depth_membership._current_book = lambda factor_path=None: list(tick.values())
    wiring = rl.production_adapters(ns.root, today=ns.fixed.date())
    droot = cap.DataRoot()
    records, shown, skipped = [], None, 0
    for key in levels_keys:
        t = tick.get(key)
        if t is None:
            skipped += 1
            continue
        ref = rows[key]["reference"]
        h, fin = droot.history(t), droot.fin(t)
        yrs = [int(y) for y in h if str(y).isdigit()]
        rec = (h.get(str(max(yrs))) or {}) if yrs else {}
        filed_today = cap._shares_default_state(t, fin, h, droot.shares_cover(t))[2]
        ni, sbc = rec.get("net_income"), rec.get("sbc")
        filed_eps = ni / filed_today if _num(ni) and _num(filed_today) and filed_today > 0 else None
        stock_ps = sbc / filed_today if _num(sbc) and _num(filed_today) and filed_today > 0 else None
        tax_l = cap.throughcycle_record.tax_rate(rec)
        est = ref.get("estimates") or {}
        ya = ((est.get("0y") or {}).get("eps") or {}).get("year_ago")
        m = measure(ya, filed_eps, stock_ps, tax_l)
        m["restated_ratio"] = None
        if m["restate"] is not None:
            inputs = wiring["inputs_fn"](t)
            today_value = ref["value"]
            alt = cref.build(**dict(inputs, estimates=restated_estimates(inputs["estimates"], m["restate"])))
            if alt.get("method") == "levels" and _num(alt.get("value")) and today_value:
                m["restated_ratio"] = alt["value"] / today_value
        m["reference_value"] = ref["value"]
        records.append(m)
        if t == show:
            shown = {k: v for k, v in m.items()}
    result = summarize(records)
    result.update({"at": "Part I levels-method earnings basis (measure only)", "pass": True, "skipped_no_ticker": skipped,
                   "levels_names_in_day": len(levels_keys), "shown": shown,
                   "label": "measurement: no pass or fail bar; the reviewer designs the correctness rule from it"})
    c = result["counts"]
    result["summary"] = (f"{result['names']} levels-method names: " + ", ".join(f"{k} {v}" for k, v in c.items())
                         + "; median ya/filed " + str(result["medians"]["ya_over_filed"])
                         + ", median restated/today " + str(result["medians"]["restated_ratio"]))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", required=True, type=Path)
    ap.add_argument("--names", default=None, type=Path)
    ap.add_argument("--show", default="MU")
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    meta, rows = ac.load_day(a.day)
    ns = ac.bootstrap_from_day(meta)
    result = run(ns, rows, a.names, a.show)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())

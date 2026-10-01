"""reference_closure.py - the market-consistent equity risk premium, solved once a month with MRI's anchor cadence.

Revision 18, brief section 2 (and amendment 1). `reference_closure_erp` is the premium at which the reference's own
capitalisation-weighted value of the market equals the market's capitalisation. Without it, a rate implied under a faster
cash-flow model is applied to a slower one (Phase 1, finding 1).

Pipeline (each step a function here; nothing is printed that names a company):
  1. `build_aggregate`   MRI's rules (macro-regime-indicator/scripts/build_equity_aggregate.py:63-86) on production's screener data:
                         USD reporters (screener FX flag None), share classes collapsed by CIK, latest-year owner earnings > 0, revenue
                         growth defined (at least 4 points), cap from financials/<T>.json Market_Cap - and amendment A1's exclusion: a
                         name whose vendor share count and latest filed diluted count (on today's split basis) differ by 100x or more
                         in either direction is not in the aggregate, and is counted.
  2. the consensus batch (`closure_enrich_batch.py`, the one networked step, run separately): enrich_ticker.enrich over the
                         aggregate's names, cached raw under cache/closure_enrich/<vintage date>/.
  3. `members`           the aggregate names that have a loading and whose reference value is above 0 at MRI's implied premium; fixed.
                         The build refuses, before this step, when any aggregate name has no brief-A provenance marker in the history
                         (amendment 2, point 2: such a name has no reference and could only drop out silently).
  4. `solve_erp`         bisection on [0.0005, 0.20], 80 iterations, the record recomputed at each trial rate (the reference is built
                         by capability_test.reference_inputs - the single source of the reference's inputs - and consensus_reference.build).
                         No root: the nearer bound and a flag. Refuses to publish below 300 members or below 60% of the aggregate's cap.
  5. the artifact        cache/reference_closure.json (`write_artifact`), read through rs2_data.reference_closure().

CLI:  python tools/reference_closure.py --build [--asof YYYY-MM-DD] [--enrich-dir DIR] [--out FILE]
Socket-blocked: this module never opens a connection (the batch step is a separate script).
"""
import argparse
import hashlib
import json
import math
import socket
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
for _p in (str(HERE / "tools" / "audit_202608"), str(HERE / "tools"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MIN_GROWTH, MAX_GROWTH = -0.05, 0.35          # MRI's clamp (kept for the record: the closure itself does not read growth)
ERP_LOW, ERP_HIGH = 0.0005, 0.20
ITERATIONS = 80
MIN_MEMBERS = 300
MIN_COVERAGE = 0.60
REVISION = 18


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---- 1. the aggregate -----------------------------------------------------------------------------------------------------

def owner_earnings_latest(rows, latest):
    rec = (rows or {}).get(latest)
    if not isinstance(rec, dict):
        return None
    ni, da, capex = rec.get("net_income"), rec.get("da"), rec.get("capex")
    if not all(_num(v) for v in (ni, da, capex)):
        return None
    return float(ni) + float(da) - float(capex)


def revenue_cagr(rows, max_years=6):
    years = sorted(int(y) for y in (rows or {}) if str(y).isdigit())
    points = []
    for year in years:
        value = (rows.get(str(year)) or {}).get("revenue")
        if _num(value) and value > 0:
            points.append((year, float(value)))
    if len(points) < 4:
        return None
    (y0, v0), (y1, v1) = points[max(0, len(points) - max_years)], points[-1]
    if y1 <= y0 or v0 <= 0:
        return None
    return (v1 / v0) ** (1 / (y1 - y0)) - 1


def build_aggregate(root, cap_mod):
    """The aggregate of MRI's rules on `root` (a capability_test.DataRoot) with amendment A1's exclusion. `cap_mod` is the
    capability_test module (its share-count helpers are the ones the pack uses). Returns (aggregate, stats): the aggregate's
    constituents are dicts {ticker, cik, market_cap, cash_flow, growth, vendor_shares}; stats are counts and shares only."""
    cik_map = root.cik_map()
    items, excluded_fx, excluded_scale = [], 0, 0
    for t in root.financial_tickers():
        fin = root.fin(t)
        cap = fin.get("Market_Cap")
        if not _num(cap) or cap <= 0:
            continue
        if fin.get("FX") is not None:
            excluded_fx += 1
            continue
        rows = root.history(t)
        latest = max(rows) if rows else None
        if latest is None:
            continue
        # amendment A1: the vendor's count and the company's own latest filed diluted count (today's split basis) differ by 100x
        vendor = fin.get("Shares_Outstanding")
        series = cap_mod._filed_diluted_series(rows)
        if series:
            split = cap_mod._split_after_last_filing(vendor, rows)
            filed_today = series[-1][1] * (split["multiplier"] if split else 1.0)
            if cap_mod._shares_scale_gap(filed_today, vendor) is not None:
                excluded_scale += 1
                continue
        items.append({"ticker": t, "market_cap": float(cap), "cash_flow": owner_earnings_latest(rows, latest),
                      "growth": revenue_cagr(rows), "fiscal_year": latest, "cik": str(cik_map.get(t) or ""),
                      "vendor_shares": vendor if _num(vendor) else None})
    total_cap_all = sum(u["market_cap"] for u in items)
    by_key, class_collapsed = {}, 0
    for u in items:
        key = u["cik"] or f"ticker:{u['ticker']}"
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = u
        else:
            class_collapsed += 1
            if u["market_cap"] > cur["market_cap"]:
                by_key[key] = u
    collapsed = list(by_key.values())
    total_cap_collapsed = sum(u["market_cap"] for u in collapsed)
    constituents, lost = [], {"owner_earnings_missing": 0, "owner_earnings_not_positive": 0, "revenue_growth_missing": 0}
    for u in collapsed:
        if u["cash_flow"] is None:
            lost["owner_earnings_missing"] += 1
            continue
        if u["cash_flow"] <= 0:
            lost["owner_earnings_not_positive"] += 1
            continue
        if u["growth"] is None:
            lost["revenue_growth_missing"] += 1
            continue
        constituents.append({"ticker": u["ticker"], "cik": u["cik"] or u["ticker"], "market_cap": u["market_cap"],
                             "cash_flow": u["cash_flow"], "growth": min(max(u["growth"], MIN_GROWTH), MAX_GROWTH),
                             "vendor_shares": u["vendor_shares"]})
    constituents.sort(key=lambda c: (-c["market_cap"], c["ticker"]))
    usable_cap = sum(c["market_cap"] for c in constituents)
    stats = {"names_with_market_cap_after_exclusions": len(items), "excluded_non_usd_reporters": excluded_fx,
             "excluded_share_count_scale_gap_A1": excluded_scale, "share_classes_collapsed": class_collapsed,
             "collapsed_market_cap_usd_t": round(total_cap_collapsed / 1e12, 4), "constituents": len(constituents),
             "constituent_market_cap_usd_t": round(usable_cap / 1e12, 4),
             "coverage_share": round(usable_cap / total_cap_collapsed, 4) if total_cap_collapsed else 0.0, "lost_names": lost}
    return {"constituents": constituents, "universe_stats": stats}, stats


# ---- 3-4. members and the solve --------------------------------------------------------------------------------------------

def solve_erp(total_at, target, lo=ERP_LOW, hi=ERP_HIGH, iterations=ITERATIONS):
    """(erp, flag): `total_at(erp)` is the aggregate value (non-increasing in erp), `target` the aggregate capitalisation.
    flag is None for an interior root, "bound_low" when even the lowest premium leaves the value below the target (`lo` is
    used), "bound_high" when even the highest leaves it above (`hi` is used). Bisection, `iterations` halvings."""
    f_lo, f_hi = total_at(lo), total_at(hi)
    if f_lo < target:
        return lo, "bound_low"
    if f_hi > target:
        return hi, "bound_high"
    a, b = lo, hi
    for _ in range(iterations):
        mid = (a + b) / 2.0
        if total_at(mid) > target:
            a = mid
        else:
            b = mid
    return (a + b) / 2.0, None


def closure_gap(total_value, total_cap):
    """|sum(V x shares) - sum(cap)| / sum(cap): the identity check (AT2)."""
    return abs(total_value - total_cap) / total_cap


class Refused(Exception):
    """The closure is not published: the coverage floor (300 members, 60% of the aggregate's capitalisation) or an input is missing."""


def check_markers(constituents, root):
    """Refuse to build when any aggregate name has no brief-A provenance marker in the history (amendment 2, point 2): such a name
    has no reference, so it could only drop out of the membership silently, and the closure would be solved on a smaller set
    than the one the book is valued on. A marker of nothing untagged ([]) is a marker; only a missing entry refuses. The count is
    named, no ticker."""
    n = sum(1 for c in constituents if root.untagged(c["ticker"]) is None)
    if n:
        raise Refused(f"{n} of the aggregate's {len(constituents)} names have no tangible-capital provenance marker in the screener "
                      f"history (the field extractor never processed them): the closure is not built on a history that does not "
                      f"carry brief A's fields for every name valued; nothing is published")


def check_floor(n_members, coverage):
    """Refuse to publish when C holds fewer than MIN_MEMBERS names or less than MIN_COVERAGE of the aggregate's capitalisation
    (mirroring MRI's coverage floor)."""
    if n_members < MIN_MEMBERS or coverage < MIN_COVERAGE:
        raise Refused(f"the coverage floor: {n_members} members (floor {MIN_MEMBERS}), {coverage:.1%} of the aggregate's "
                      f"capitalisation (floor {MIN_COVERAGE:.0%}); nothing is published")


def reference_value(t, root, cap_mod, estimates, anchors, erp, today):
    """(value per share at premium `erp`, shares_default) - the reference built by `reference_inputs` (unquantized: the solve is
    smooth in the premium) and consensus_reference.build; (None, shares) when there is no value."""
    import consensus_reference
    ri = cap_mod.reference_inputs(t, root, estimates, anchors, {"erp": erp}, printed=False, today=today)
    out = consensus_reference.build(**ri["kwargs"])
    return out.get("value"), ri["shares_default"]


def select_members(constituents, estimates_of, mri_erp, value_at):
    """C: the aggregate's names that have consensus estimates, a positive share count and a reference value above 0 at MRI's
    implied premium `mri_erp` (a name with no sector loading has no cost of equity and so no value). Fixed for the solve.
    Returns (members, counts): members are {ticker, cap, shares, estimates}; counts say why the others are out (no names)."""
    members = []
    counts = {"no_consensus_estimates": 0, "no_share_count": 0, "no_value_at_mri_premium": 0, "value_not_positive_at_mri_premium": 0}
    for c in constituents:
        est = estimates_of(c["ticker"])
        if not est:
            counts["no_consensus_estimates"] += 1
            continue
        v, shares = value_at(c["ticker"], est, mri_erp)
        if not (_num(shares) and shares > 0):
            counts["no_share_count"] += 1
            continue
        if v is None:
            counts["no_value_at_mri_premium"] += 1
            continue
        if not v > 0:
            counts["value_not_positive_at_mri_premium"] += 1
            continue
        members.append({"ticker": c["ticker"], "cap": c["market_cap"], "shares": shares, "estimates": est})
    return members, counts


def solve_closure(members, value_at):
    """Solve the premium for the fixed members: sum over C of max(V_i, 0) x shares_i = sum over C of cap_i. Returns a dict
    {erp, flag, sum_cap, sum_value, gap, none_evaluations}."""
    target = sum(m["cap"] for m in members)
    none_n = [0]

    def total_at(erp):
        tot = 0.0
        for m in members:
            v, _sh = value_at(m["ticker"], m["estimates"], erp)
            if v is None:
                none_n[0] += 1
                continue
            tot += max(v, 0.0) * m["shares"]
        return tot

    erp, flag = solve_erp(total_at, target)
    total = total_at(erp)
    return {"erp": erp, "flag": flag, "sum_cap": target, "sum_value": total,
            "gap": closure_gap(total, target) if target > 0 else None, "none_evaluations": none_n[0]}


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _block_sockets():
    """The build never needs the network: every socket is refused (the consensus batch is a separate script)."""
    class _Blocked(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("Socket access blocked: the closure build is offline (the consensus batch is a separate step)")

    def _no(*a, **k):
        raise RuntimeError("Network name resolution blocked: the closure build is offline")
    socket.socket = _Blocked
    socket.getaddrinfo = _no
    socket.create_connection = _no


def build_closure(*, root, cap_mod, rs2_mod, enrich_dir, asof, today=None):
    """The whole build on `root` (a capability_test.DataRoot) with the consensus cache `enrich_dir` (a directory of
    <TICKER>.json raw enrich outputs): returns the artifact dict, or raises Refused (coverage floor, a missing anchor)."""
    today = today if today is not None else date.fromisoformat(asof)
    enrich_dir = Path(enrich_dir)
    rf, _ = rs2_mod.anchor_risk_free_rate()
    ga, _ = rs2_mod.anchor_terminal_g()
    be, _ = rs2_mod.anchor_breakeven_10y()
    mri_erp, _ = rs2_mod.anchor_mature_erp()
    if rf is None or ga is None or mri_erp is None:
        raise Refused("an MRI anchor the closure needs is not usable (nominal 10-year, long-run growth anchor or implied premium)")
    agg, stats = build_aggregate(root, cap_mod)
    constituents = agg["constituents"]
    check_markers(constituents, root)
    stats["constituents_without_marker"] = 0
    sectors = {}
    for c in constituents:
        sec, _ind = rs2_mod.sector_lookup(c["ticker"])
        if sec not in sectors:
            adj, _raw, _src = rs2_mod.coe_loading(sec)
            sectors[sec] = adj
    anchors = {"rf": rf, "ga": ga, "breakeven": be, "loading": sectors}
    cache = {}

    def estimates_of(t):
        if t not in cache:
            p = enrich_dir / f"{t}.json"
            doc = rs2_mod.load_json(p) if p.exists() else None
            cache[t] = (doc or {}).get("estimates") if isinstance(doc, dict) else None
        return cache[t]

    def value_at(t, est, erp):
        return reference_value(t, root, cap_mod, est, anchors, erp, today)

    members, counts = select_members(constituents, estimates_of, mri_erp, value_at)
    agg_cap = sum(c["market_cap"] for c in constituents)
    member_cap = sum(m["cap"] for m in members)
    coverage = member_cap / agg_cap if agg_cap else 0.0
    check_floor(len(members), coverage)
    sol = solve_closure(members, value_at)
    manifest = enrich_dir / "manifest.json"
    inputs = {}
    for name in ("fundamentals_history.json", "fundamentals_ttm.json", "cik_map.json"):
        inputs[name] = sha256_file(root.sd / name)
    for name in ("cost_of_capital_anchor.json", "long_run_growth_anchor.json"):
        pth = rs2_mod.anchors_dir() / name
        if pth.exists():
            inputs[name] = sha256_file(pth)
    inputs["consensus_manifest.json"] = sha256_file(manifest) if manifest.exists() else None
    inputs["reference_closure.py"] = sha256_file(Path(__file__))
    inputs["capability_test.py"] = sha256_file(cap_mod.__file__)
    inputs["consensus_reference.py"] = sha256_file(Path(__file__).resolve().parent / "consensus_reference.py")
    man = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    return {"asof": asof, "erp": sol["erp"], "rf": rf, "rf_eff": max(rf, ga), "gA": ga, "mri_universe_premium": mri_erp,
            "members": len(members), "coverage_share": coverage, "sum_cap": sol["sum_cap"], "sum_value": sol["sum_value"],
            "gap": sol["gap"], "flag": sol["flag"], "none_evaluations": sol["none_evaluations"],
            "aggregate": dict(stats), "members_excluded_counts": counts,
            "consensus_vintage": {"date": man.get("vintage"), "tickers_requested": man.get("tickers_requested"),
                                  "manifest_sha256": man.get("manifest_sha256"), "stats": man.get("stats")},
            "inputs_sha256": inputs, "revision": REVISION, "built_at": datetime.now().isoformat(timespec="seconds")}


def write_artifact(doc, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--asof", default=None, help="the premium's date (default today)")
    ap.add_argument("--enrich-dir", type=Path, default=None, help="default: the newest cache/closure_enrich/<date>")
    ap.add_argument("--out", type=Path, default=HERE / "cache" / "reference_closure.json")
    a = ap.parse_args(argv)
    if not a.build:
        ap.print_help()
        return 1
    _block_sockets()
    import capability_test as cap_mod
    import rs2_data as rs2_mod
    asof = a.asof or date.today().isoformat()
    enrich_dir = a.enrich_dir
    if enrich_dir is None:
        dirs = sorted(p for p in (HERE / "cache" / "closure_enrich").glob("*") if p.is_dir())
        if not dirs:
            print("no cache/closure_enrich/<date> directory: run tools/closure_enrich_batch.py first", file=sys.stderr)
            return 1
        enrich_dir = dirs[-1]
    try:
        doc = build_closure(root=cap_mod.DataRoot(), cap_mod=cap_mod, rs2_mod=rs2_mod, enrich_dir=enrich_dir, asof=asof)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    write_artifact(doc, a.out)
    print(f"wrote {a.out}: erp {doc['erp']:.6f} flag {doc['flag']} members {doc['members']} coverage {doc['coverage_share']:.3f} "
          f"gap {doc['gap']:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

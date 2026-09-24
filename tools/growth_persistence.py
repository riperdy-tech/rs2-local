"""How much of a high-growth year actually persists? Measured across the full corpus:
for every ticker-year with revenue growth g0, what was the REALIZED 5y forward CAGR?

Importable (Phase 4 D11 — `capability_test.build_pack`'s GROWTH BASE RATES block reuses this
logic for the "given the growth just delivered" conditional table) via `persistence_for_growth()`
/ `persistence_table()`. Run directly (`python tools/growth_persistence.py`) for the printed
report this module has always produced."""
import sys
from pathlib import Path
import statistics as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rs2_data

BUCKET_DEFS = ((0.15, 0.25, "15-25%"), (0.25, 0.40, "25-40%"),
               (0.40, 0.70, "40-70%"), (0.70, 5.0, ">70%"))


def bucket_for_growth(g0):
    """Which delivered-growth bucket label g0 (a FRACTION, e.g. 0.32 for 32%) falls into, or
    None when g0 is outside every bucket (below 15% or at/above 500%)."""
    for lo, hi, lbl in BUCKET_DEFS:
        if lo <= g0 < hi:
            return lbl
    return None


def realized_forward_buckets(sd=None, max_fiscal_year=None):
    """{label: [realized 5y forward revenue CAGR, ...]} across the full corpus — the same
    measurement the standalone report prints, exposed here as data for callers that need the
    raw table (base_rates.py, capability_test.py's GROWTH BASE RATES block) rather than the
    printed summary.

    `sd`: the screener-data directory to read from, or None to resolve
    `rs2_data.CONFIG["screener_data_dir"]` directly. A caller with its own resolved/patchable
    directory (`capability_test.SD`, test-monkeypatched) should always pass it — re-resolving
    here would read the REAL screener directory under a test fixture regardless of the patch.

    `max_fiscal_year`: point-in-time restriction (Phase 4 E4.3) — fiscal years after this one are
    excluded from EVERY ticker's series before any (start-year, +5y) pair is formed, so a trial
    pack's conditional table cannot see a year that would not yet have been filed as of the
    trial's `asof` date. None (the default) computes the full corpus, unchanged behaviour.
    """
    SD = Path(sd) if sd is not None else Path(rs2_data.CONFIG["screener_data_dir"])
    H = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers", {})
    buckets = {}
    for t, yd in H.items():
        ys = sorted(int(y) for y in yd if str(y).isdigit()
                    and (max_fiscal_year is None or int(y) <= max_fiscal_year))
        revs = {}
        for y in ys:
            r = (yd.get(str(y)) or {}).get("revenue")
            if isinstance(r, (int, float)) and r > 0:
                revs[y] = r
        for y in sorted(revs):
            if (y - 1) not in revs or (y + 5) not in revs:
                continue
            g0 = revs[y] / revs[y - 1] - 1
            if not (-0.5 < g0 < 5):
                continue
            fwd5 = (revs[y + 5] / revs[y]) ** (1 / 5) - 1
            if not (-0.9 < fwd5 < 3):
                continue
            lbl = bucket_for_growth(g0)
            if lbl:
                buckets.setdefault(lbl, []).append(fwd5)
    return buckets


def persistence_table(sd=None, max_fiscal_year=None):
    """{label: {n, p25, median, p75, p90}} (percent, 1dp) for each bucket carrying at least 30
    corpus observations. A bucket below that floor is omitted rather than shown on a sample too
    thin to trust — the same floor the standalone report has always applied. `sd`,
    `max_fiscal_year`: see realized_forward_buckets()."""
    buckets = realized_forward_buckets(sd, max_fiscal_year=max_fiscal_year)
    out = {}
    for lbl in ("15-25%", "25-40%", "40-70%", ">70%"):
        v = sorted(buckets.get(lbl, []))
        if len(v) < 30:
            continue
        q = lambda p: v[int(len(v) * p)]
        out[lbl] = {"n": len(v), "p25": round(q(.25) * 100, 1), "median": round(st.median(v) * 100, 1),
                    "p75": round(q(.75) * 100, 1), "p90": round(q(.90) * 100, 1)}
    return out


def persistence_for_growth(g0, sd=None, max_fiscal_year=None):
    """(label, stats|None) for the bucket containing delivered growth g0 (a fraction).

    `label` is None when g0 falls outside every bucket. `stats` is None when the bucket has
    fewer than 30 corpus observations (see persistence_table) — label is still returned so the
    caller can say WHICH bucket it was, even with no usable table for it. `sd`, `max_fiscal_year`:
    see realized_forward_buckets().
    """
    lbl = bucket_for_growth(g0)
    if lbl is None:
        return None, None
    return lbl, persistence_table(sd, max_fiscal_year=max_fiscal_year).get(lbl)


def _print_report():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    buckets = realized_forward_buckets()
    table = persistence_table()
    print("REALIZED next-5y revenue CAGR, by the growth rate a company just delivered:")
    print(f"{'delivered':>10s}{'n':>7s}{'p25':>8s}{'median':>8s}{'p75':>8s}{'p90':>8s}")
    for lbl in ("15-25%", "25-40%", "40-70%", ">70%"):
        s = table.get(lbl)
        if not s:
            continue
        print(f"{lbl:>10s}{s['n']:>7d}{s['p25']:>7.1f}%{s['median']:>7.1f}%{s['p75']:>7.1f}%{s['p90']:>7.1f}%")
    allv = sorted(x for v in buckets.values() for x in v)
    if allv:
        print(f"\nacross all high-growth years (n={len(allv)}): median forward 5y CAGR "
              f"{st.median(allv)*100:.1f}%, p90 {allv[int(len(allv)*.9)]*100:.1f}%")


if __name__ == "__main__":
    _print_report()

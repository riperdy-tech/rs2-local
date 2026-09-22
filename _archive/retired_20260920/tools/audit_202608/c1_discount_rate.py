"""C1 — Discount-rate sensitivity: does the rate CONSTRUCTION matter for the ranking?

Replays valuation_backbone.backbone() across the live book under rate scenarios:
  baseline    : the production 11-row sector table (7-11%)
  flat10      : every non-financial name at 10% (removes sector differentiation)
  implied_118 : every name at 11.8% (the book-implied CoE measured by tools/implied_erp.py)
  plus2/minus2: table shifted +/-2pts (level shocks)

Only names whose baseline method == reverse_dcf are compared (the sector table only governs
that route; P/B-ROE and rNPV have their own rates). Metrics per scenario vs baseline:
  - MoS distribution percentiles (level effect)
  - Spearman rank correlation of mos_pct and expectations_gap_pts (ranking effect)
  - brake-tier assignment changes, tiering each scenario on ITS OWN p33/p75 (does the
    percentile machinery actually make the ranking invariant to the level, as designed?)
"""
import copy

import common

common.enable_json_cache()
import valuation_backbone as vb  # noqa: E402


def run_book(tickers):
    out = {}
    for t in tickers:
        try:
            b = vb.backbone(t)
        except Exception as e:
            out[t] = {"ok": False, "reason": f"exc:{e}"}
            continue
        out[t] = b
    return out


def tiers(rows):
    """ticker -> brake tier from the scenario's own cross-section (chase/stage/no-chase)."""
    vals = sorted(v["mos_pct"] for v in rows.values()
                  if v.get("ok") and isinstance(v.get("mos_pct"), (int, float)))
    p33, p75 = common.percentile(vals, 33), common.percentile(vals, 75)
    out = {}
    for t, v in rows.items():
        m = v.get("mos_pct") if v.get("ok") else None
        if m is None or p33 is None:
            out[t] = "uncovered"
        elif m >= p75:
            out[t] = "chase_ok"
        elif m >= p33:
            out[t] = "stage"
        else:
            out[t] = "no_chase"
    return out, {"p33": p33, "p75": p75}


def main():
    book = common.book_tickers()
    base_table = copy.deepcopy(vb.SECTOR_WACC)
    base_default = vb.DEFAULT_WACC

    scenarios = {
        "baseline": (base_table, base_default),
        "flat10": ({k: 10 for k in base_table}, 10.0),
        "implied_118": ({k: 11.8 for k in base_table}, 11.8),
        "plus2": ({k: v + 2 for k, v in base_table.items()}, base_default + 2),
        "minus2": ({k: v - 2 for k, v in base_table.items()}, base_default - 2),
    }

    results = {}
    for name, (table, default) in scenarios.items():
        vb.SECTOR_WACC = table
        vb.DEFAULT_WACC = default
        results[name] = run_book(book)
    vb.SECTOR_WACC = base_table
    vb.DEFAULT_WACC = base_default

    base = results["baseline"]
    rdcf = [t for t, v in base.items() if v.get("ok") and v.get("method") == "reverse_dcf"]
    base_tiers, base_cuts = tiers({t: base[t] for t in rdcf})

    summary = {"n_book": len(book), "n_reverse_dcf": len(rdcf), "scenarios": {}}
    for name in scenarios:
        rows = {t: results[name][t] for t in rdcf}
        mos = sorted(v["mos_pct"] for v in rows.values()
                     if v.get("ok") and isinstance(v.get("mos_pct"), (int, float)))
        sc_tiers, sc_cuts = tiers(rows)
        flips = [t for t in rdcf if sc_tiers[t] != base_tiers[t]]
        rho_mos, n1 = common.spearman([base[t].get("mos_pct") for t in rdcf],
                                      [rows[t].get("mos_pct") for t in rdcf])
        rho_gap, n2 = common.spearman([base[t].get("expectations_gap_pts") for t in rdcf],
                                      [rows[t].get("expectations_gap_pts") for t in rdcf])
        summary["scenarios"][name] = {
            "mos_percentiles": {p: common.percentile(mos, p) for p in (10, 25, 33, 50, 67, 75, 90)},
            "n_mos": len(mos),
            "tier_cuts": sc_cuts,
            "spearman_mos_vs_baseline": {"rho": rho_mos, "n": n1},
            "spearman_gap_vs_baseline": {"rho": rho_gap, "n": n2},
            "brake_tier_flips_vs_baseline": {"count": len(flips), "tickers": sorted(flips)},
            "fair_value_method_counts": _method_counts(rows),
        }
    common.save("c1_discount_rate", summary)


def _method_counts(rows):
    c = {}
    for v in rows.values():
        if v.get("ok"):
            m = v.get("fair_value_method")
            c[m] = c.get(m, 0) + 1
    return c


if __name__ == "__main__":
    main()

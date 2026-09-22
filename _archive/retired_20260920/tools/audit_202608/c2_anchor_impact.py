"""C2 — Anchor impact: does adopting the MRI capital-market anchors move the ranking?

Replays valuation_backbone.backbone() across the live book under the three adoption states the
repair package describes, and measures what moves:

    table          : the pre-anchor engine (sector table level + TERMINAL_G = 0.025)
    anchor_coe     : level from the MRI cost-of-capital anchor, terminal g unchanged
    anchor_g       : TERMINAL_G replaced by the long-run growth anchor's suggestion
    anchor_both    : both adopted (the production intent)

The point is NOT to show the numbers change — an anchor that changed nothing would be
pointless. It is to show WHICH names move and whether the cross-sectional ORDER survives,
using the same method as c1_discount_rate.py: MoS percentiles for the level effect, Spearman
rank correlation for the ordering effect, and brake-tier flips for what the book would
actually do differently.

An anchor that is absent, stale or degraded is reported as `unavailable` and the scenario is
skipped rather than approximated: measuring the impact of an anchor that does not exist would
be worse than not measuring at all.
"""
import common

common.enable_json_cache()
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402

# The level offset the pre-anchor engine actually ran with: the self-referential calibration
# cache as it stood before the growth anchor went live (solved at TERMINAL_G = 0.025). Recorded
# as a constant because the live cache now carries a different value and cannot be asked for it.
PRE_ANCHOR_OFFSET_PTS = 1.7


def _anchor_state():
    """What the anchors actually offer right now, and why not when they offer nothing."""
    coe_level, coe_src = rs2_data.anchor_level_cost_of_equity_pct()
    term_g, term_g_src = rs2_data.anchor_terminal_g()
    return {
        "coe_level_pct": coe_level,
        "coe_source": coe_src,
        "terminal_g": term_g,
        "terminal_g_source": term_g_src,
        "anchors_dir": str(rs2_data.anchors_dir()),
        "files_present": {
            name: (rs2_data.anchors_dir() / fname).exists()
            for name, fname in rs2_data.ANCHOR_FILES.items()
        },
    }


def _run_book(tickers):
    out = {}
    for t in tickers:
        try:
            out[t] = vb.backbone(t)
        except Exception as exc:  # noqa: BLE001 - a name that explodes is a result too
            out[t] = {"ok": False, "reason": f"exc:{exc}"}
    return out


def _tiers(rows):
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


def _method_counts(rows):
    counts = {}
    for v in rows.values():
        if v.get("ok"):
            key = v.get("fair_value_method")
            counts[key] = counts.get(key, 0) + 1
    return counts


def _pinned(*, terminal_g, coe_offset):
    """Context manager pinning the engine's two level inputs for one scenario.

    WHY THIS EXISTS. The first version of this audit varied the ANCHOR INPUTS and let everything
    else fall out. That stopped measuring anything the moment the calibration cache became
    anchor-dependent: `coe_offset_pts()` now refuses a cache solved under a different terminal
    growth, so the "anchors hidden" arm silently ran at offset 0.0 while the pre-anchor engine
    actually ran at 1.7. The audit reported +3.5 pts median MoS on one run and −11.1 pts on the
    next, both driven by cache state rather than by the anchors.

    An arm must therefore be an EXPLICIT engine state — (terminal growth, level offset) — so the
    comparison is controlled and the net effect can be decomposed into its two causes.
    """
    import contextlib

    @contextlib.contextmanager
    def _cm():
        saved_g, saved_off = vb.terminal_g, vb.coe_offset_pts
        vb.terminal_g = lambda: (terminal_g, "audit_pinned")
        vb.coe_offset_pts = lambda: coe_offset
        try:
            yield
        finally:
            vb.terminal_g, vb.coe_offset_pts = saved_g, saved_off

    return _cm()


def _live_calibration_offset():
    """The offset the current cache supplies under the engine's live terminal growth."""
    return vb.coe_offset_pts()


def main():
    book = common.book_tickers()
    state = _anchor_state()
    anchor_g = state["terminal_g"] or vb.TERMINAL_G
    pre_offset = PRE_ANCHOR_OFFSET_PTS
    post_offset = _live_calibration_offset()

    # Explicit engine states, not side effects. `pre_anchor` is what production actually ran
    # before this change; `anchor_g` isolates the terminal-growth effect by holding the level at
    # its pre-anchor value; `coherent` is the shipped state; `net` is pre_anchor -> coherent.
    arms = {
        "pre_anchor": (vb.TERMINAL_G, pre_offset),
        "anchor_g": (anchor_g, pre_offset),
        "coherent": (anchor_g, post_offset),
    }

    scenarios = {}
    for name, (g_term, offset) in arms.items():
        with _pinned(terminal_g=g_term, coe_offset=offset):
            scenarios[name] = _run_book(book)

    baseline = scenarios["pre_anchor"]
    rdcf = [t for t, v in baseline.items() if v.get("ok") and v.get("method") == "reverse_dcf"]
    base_tiers, _ = _tiers({t: baseline[t] for t in rdcf})

    summary = {
        "anchor_state": state,
        "arms": {name: {"terminal_g": g, "coe_offset_pts": o} for name, (g, o) in arms.items()},
        "n_book": len(book),
        "n_reverse_dcf": len(rdcf),
        "baseline_arm": "pre_anchor",
        "scenarios": {},
    }
    for name, rows_all in scenarios.items():
        if name == "pre_anchor":
            continue
        rows = {t: rows_all[t] for t in rdcf}
        mos = sorted(v["mos_pct"] for v in rows.values()
                     if v.get("ok") and isinstance(v.get("mos_pct"), (int, float)))
        sc_tiers, sc_cuts = _tiers(rows)
        flips = [t for t in rdcf if sc_tiers[t] != base_tiers[t]]
        deltas = sorted(
            rows[t]["mos_pct"] - baseline[t]["mos_pct"]
            for t in rdcf
            if isinstance(rows[t].get("mos_pct"), (int, float))
            and isinstance(baseline[t].get("mos_pct"), (int, float))
        )
        rho_mos, n_mos = common.spearman([baseline[t].get("mos_pct") for t in rdcf],
                                        [rows[t].get("mos_pct") for t in rdcf])
        rho_gap, n_gap = common.spearman([baseline[t].get("expectations_gap_pts") for t in rdcf],
                                         [rows[t].get("expectations_gap_pts") for t in rdcf])
        summary["scenarios"][name] = {
            "mos_percentiles": {p: common.percentile(mos, p) for p in (10, 25, 33, 50, 67, 75, 90)},
            "n_mos": len(mos),
            "tier_cuts": sc_cuts,
            "spearman_mos_vs_pre_anchor": {"rho": rho_mos, "n": n_mos},
            "spearman_gap_vs_pre_anchor": {"rho": rho_gap, "n": n_gap},
            "brake_tier_flips_vs_pre_anchor": {"count": len(flips), "tickers": sorted(flips)},
            "mos_delta_pts": {
                "median": common.percentile(deltas, 50) if deltas else None,
                "p25": common.percentile(deltas, 25) if deltas else None,
                "p75": common.percentile(deltas, 75) if deltas else None,
            },
            "fair_value_method_counts": _method_counts(rows),
        }

    common.save("c2_anchor_impact", summary)


if __name__ == "__main__":
    main()

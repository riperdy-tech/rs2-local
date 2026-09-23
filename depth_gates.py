#!/usr/bin/env python3
"""depth_gates.py — SINGLE OWNER of what makes a depth verdict `actionable` (Charter v3.1, P1.3).

Phase 1 (stocks-workspace/docs/review_2026-09-22/PHASE_1_INTEGRITY_HYGIENE.md), item P1.3.

GATE ON READ, NOT ON WRITE. Nothing here deletes a ledger row or mutates a verdict — it only
judges one, exactly like non-negotiable 3 (annotate, never silently gate) requires. Today's
ledger holds test rows, pre-Charter-v3.1 rows, and rows today's own dispersion/fiduciary bars
would reject; those rows stay in the ledger (the append-only record) and simply publish with
`actionable: false` and the reasons why, so a consumer can filter without the row disappearing.

`GATE_VERSION` moved here from `depth_pipeline.py` (P1.2): that module still WRITES the field on
every verdict it produces (a verdict is stamped with the schema version live at write time), but
this module is the single owner of what the CURRENT gate version means and how it is evaluated.
A verdict with `gate_version` absent, or older than this module's `GATE_VERSION`, was produced
under different rules and cannot be judged against today's bar — it fails closed as
`pre_v3.1_gates`, not silently graded on the newer scale.
"""
from __future__ import annotations

GATE_VERSION = 2

_DIRECTIONS = ("undervalued", "hold", "overvalued")
# `run_source` values that never belong in the live book. "manual" is depth_pipeline.py's default
# for an unmarked run (P1.2); "test" is reserved for anything that stamps itself as such.
_NON_PRODUCTION_SOURCES = ("manual", "test")
HIGH_DISPERSION_TOL_PCT = 25.0


def assess(v):
    """(actionable: bool, reasons: list[str]).

    Every reason that applies is returned, evaluated in this fixed order — not just the first
    match, so a verdict can be `pre_v3.1_gates` AND `single_sample` at once and a reader sees
    both. `actionable` is True only when `reasons` is empty. `v` is a ledger/overlay verdict
    dict; every field is read with `.get()`, because a verdict from before a field existed must
    produce a reason (typically `pre_v3.1_gates`), never raise.

      1. `direction` not in {undervalued, hold, overvalued}   -> "not_usable"
      2. `gate_version` absent or < GATE_VERSION               -> "pre_v3.1_gates"
      3. `n_basis == 1`                                        -> "single_sample"
      4. `fiduciary_verdict == "FAIL"`                         -> "fiduciary_fail"
      5. `direction == overvalued` and `kelly_fraction_pct > 0` -> "kelly_on_overvalued"
      6. `direction == undervalued` and `spread_pct > 25`      -> "high_dispersion"
      7. `run_source in {manual, test}`                        -> "non_production_row"

    Symmetric dispersion for `overvalued` is Phase 4 P4.8 — deliberately not added here.
    """
    v = v or {}
    reasons = []

    direction = v.get("direction")
    if direction not in _DIRECTIONS:
        reasons.append("not_usable")

    gv = v.get("gate_version")
    try:
        stale = gv is None or gv < GATE_VERSION
    except TypeError:
        stale = True  # an unparseable gate_version is not evidence it met today's bar
    if stale:
        reasons.append("pre_v3.1_gates")

    if v.get("n_basis") == 1:
        reasons.append("single_sample")

    if v.get("fiduciary_verdict") == "FAIL":
        reasons.append("fiduciary_fail")

    kelly = v.get("kelly_fraction_pct")
    if direction == "overvalued" and kelly is not None and kelly > 0:
        reasons.append("kelly_on_overvalued")

    spread = v.get("spread_pct")
    if direction == "undervalued" and spread is not None and spread > HIGH_DISPERSION_TOL_PCT:
        reasons.append("high_dispersion")

    if v.get("run_source") in _NON_PRODUCTION_SOURCES:
        reasons.append("non_production_row")

    return (not reasons), reasons

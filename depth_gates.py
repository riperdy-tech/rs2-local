#!/usr/bin/env python3
"""depth_gates.py — SINGLE OWNER of what makes a depth verdict `actionable` (Charter v3.0, P1.3).

Phase 1 (stocks-workspace/docs/review_2026-09-22/PHASE_1_INTEGRITY_HYGIENE.md), item P1.3.

GATE ON READ, NOT ON WRITE. Nothing here deletes a ledger row or mutates a verdict — it only
judges one, exactly like non-negotiable 3 (annotate, never silently gate) requires. Today's
ledger holds test rows, rows with `gate_version` absent or < 2 (published as reason
`pre_v3.1_gates` — the string is a published contract value and is kept even though the current
charter is v3.0, see AGENTS.md §1), and rows today's own dispersion/fiduciary bars would reject;
those rows stay in the ledger (the append-only record) and simply publish with
`actionable: false` and the reasons why, so a consumer can filter without the row disappearing.

`GATE_VERSION` moved here from `depth_pipeline.py` (P1.2): that module still WRITES the field on
every verdict it produces (a verdict is stamped with the schema version live at write time), but
this module is the single owner of what the CURRENT gate version means and how it is evaluated.
A verdict with `gate_version` absent, or older than this module's `GATE_VERSION`, was produced
under different rules and cannot be judged against today's bar — it fails closed as
`pre_v3.1_gates`, not silently graded on the newer scale.
"""
from __future__ import annotations

import csv
from pathlib import Path

# Temporary (Phase 4 reviewer ruling 2026-09-27): revenue from extracting a finite stock, priced on a commodity.
DEPLETING_INDUSTRIES = frozenset({
    "Oil & Gas E&P", "Oil & Gas Integrated", "Gold", "Silver", "Copper", "Other Precious Metals & Mining",
    "Other Industrial Metals & Mining", "Thermal Coal", "Coking Coal", "Uranium"})

_PRODUCER_CSV_CACHE: dict[tuple[str, float], tuple[dict[str, tuple[str, str]], None] | tuple[None, str]] = {}


def producer_class(ticker: str, stocks_csv_path: str | Path, source_label: str) -> dict:
    """Classify ticker against screener stocks.csv depleting producer industries.

    Fail-closed: returns status 'unavailable' on any read/parse/schema defect.
    Returns status 'unknown' if ticker is missing or has empty industry.
    Returns status 'ok' with depleting boolean, sector, industry, and source otherwise.
    """
    if not stocks_csv_path:
        return {"status": "unavailable", "source": source_label, "error": "stocks_csv_path is empty or None"}

    p = Path(stocks_csv_path)
    try:
        mtime = p.stat().st_mtime
    except OSError as e:
        return {"status": "unavailable", "source": source_label, "error": str(e)}

    cache_key = (str(p.resolve()), mtime)
    cached = _PRODUCER_CSV_CACHE.get(cache_key)
    if cached is not None:
        mapping, err = cached
        if err:
            return {"status": "unavailable", "source": source_label, "error": err}
    else:
        try:
            with open(p, "r", encoding="utf-8-sig", newline="", errors="strict") as f:   # a bad byte fails closed
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    err = "stocks.csv has no header row"
                    _PRODUCER_CSV_CACHE[cache_key] = (None, err)
                    return {"status": "unavailable", "source": source_label, "error": err}
                sym_col = next((c for c in reader.fieldnames if c and c.strip().lower() == "symbol"), None)
                ind_col = next((c for c in reader.fieldnames if c and c.strip().lower() == "industry"), None)
                sec_col = next((c for c in reader.fieldnames if c and c.strip().lower() == "sector"), None)
                if not sym_col or not ind_col:
                    err = "stocks.csv missing symbol or industry column"
                    _PRODUCER_CSV_CACHE[cache_key] = (None, err)
                    return {"status": "unavailable", "source": source_label, "error": err}
                mapping = {}
                for row in reader:
                    sym = (row.get(sym_col) or "").strip().upper()
                    if sym:
                        sec = (row.get(sec_col) or "").strip() if sec_col else ""
                        ind = (row.get(ind_col) or "").strip()
                        mapping[sym] = (sec, ind)
                _PRODUCER_CSV_CACHE[cache_key] = (mapping, None)
        except Exception as e:
            err = f"failed to read/parse stocks.csv: {e}"
            _PRODUCER_CSV_CACHE[cache_key] = (None, err)
            return {"status": "unavailable", "source": source_label, "error": err}

    sym = (ticker or "").strip().upper()
    if sym not in mapping:
        return {"status": "unknown", "source": source_label}

    sec, ind = mapping[sym]
    if not ind:
        return {"status": "unknown", "source": source_label}

    return {
        "status": "ok",
        "depleting": ind in DEPLETING_INDUSTRIES,
        "sector": sec,
        "industry": ind,
        "source": source_label,
    }


# 6 (GATE_VERSION 6, brief S2c): reasons 17-18. Consensus data status and street fence required.
GATE_VERSION = 6

# P2-fix B2 (Phase 2 approval review): the ledger's `gate_version` alone does not prove a verdict
# came from a VALID analyst — depth_pipeline stamps gate_version=2 on every verdict it writes
# today, including ones produced before Phase 4 rules the current analyst valid. FIRST_VALID_
# PACK_REVISION is the single switch that turns validity on: it stays None (nothing is valid)
# until the Phase 4 ruling sets it to the first PACK_REVISION whose verdicts count.
FIRST_VALID_PACK_REVISION = None

_DIRECTIONS = ("undervalued", "hold", "overvalued")
# `run_source` values that never belong in the live book. "manual" is depth_pipeline.py's default
# for an unmarked run (P1.2); "test" is reserved for anything that stamps itself as such;
# "gate_test" is the Phase 4 gate run (B4, Phase 4 amendments) — RS2_RUN_SOURCE=gate_test routes
# like manual to the test ledger, and this row-level gate must treat it as non-production too, so
# a gate-run verdict can never become actionable even if a copy of the row ever reached the
# production ledger by some other path.
_NON_PRODUCTION_SOURCES = ("manual", "test", "gate_test")
HIGH_DISPERSION_TOL_PCT = 25.0
MIN_MOS_FOR_DIRECTION = 0.10
# the sanity audit's MOS_EXTREME (consensus_valuation), which annotates a sample, read here as a gate
MOS_BEYOND_PCT = 150.0


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
      6. `direction in {undervalued, overvalued}` and `spread_pct > 25` -> "high_dispersion"
      7. `run_source in {manual, test}`                        -> "non_production_row"
      8. `instability.unstable is True`                        -> "mode_instability"
      9. `FIRST_VALID_PACK_REVISION is set` and not `analyst_valid(v)` -> "pre_valid_analyst"
     10. `median_iv` above `street_fence.high` on an undervalued call, or below
         `street_fence.low` on an overvalued call                 -> "outside_street_fence"
     11. `|mos_vs_base_pct| > 150`                               -> "mos_beyond_150pct"
     12. a basis sample flagged `desk_not_used` / `iv_not_desk_backed` -> "desk_not_used"
     13. a sample written at reduced thinking (`LOW_EFFORT_RESCUE`);
         from 2026-09-27 such a sample is never a basis sample, so this guards rows written before that -> "low_effort_rescue"
     14. any flag starting with `SAMPLE_FAILED`               -> "sample_failed"
     15. any flag starting with `discovery_failed`            -> "discovery_failed"
     16. depleting producer, or class unavailable on v>=5     -> "depleting_producer_unsupported" / "depleting_producer_class_unavailable"
     17. `consensus_data_status` present and not "ok", or absent on v>=6 -> "consensus_data_unavailable"
     18. `street_fence` not a dict with numeric `low` and `high` -> "no_street_fence"

    Reasons 10-13 (GATE_VERSION 3, Phase 4 (b)): the sanity audit already flagged FSM's samples
    (MoS +442%, 4.9x the analyst high) and kept them, as designed, but no gate read the flags.
    Reason 10 needs a fence; since GATE_VERSION 6 a row without one fails reason 18
    (`no_street_fence`), and depth_pipeline still stamps the information flag of the same name.
    Since the desk-backed rule a desk-less sample is not a basis
    sample, so reason 12 guards rows from before that rule and any path that skips it.

    Reasons 14-15 (GATE_VERSION 4, operator ruling 2026-09-27): a sample written at reduced
    thinking, or one whose harness run failed, is not a result. Any flag starting with
    `SAMPLE_FAILED` (failed run or lost sample) produces reason `sample_failed`; any flag
    starting with `discovery_failed` produces `discovery_failed`.

    Reasons 16 (GATE_VERSION 5, reviewer ruling 2026-09-27): Depleting-producer class (stocks.csv
    industry). Phase 4 development runs (FSM, GPOR on revisions 11 and 12) valued these businesses
    as perpetuities at spot commodity decks despite the TASK, so the verdict is not actionable
    until a producer design passes its own pre-registered test. Temporary.

    Reasons 17-18 (GATE_VERSION 6, brief S2c): no verdict is actionable without its consensus
    data or its street fence. Reason 17 (`consensus_data_unavailable`): `consensus_data_status`
    is anything but "ok" ("enrich_missing", "stale", "point_in_time", "estimates_unavailable",
    "fetch_error" - the vendor answered a core request with an HTTP error - or an unknown value),
    or the field is absent and `gate_version` is at least 6. Reason 18 (`no_street_fence`): `street_fence` is not a dict with numeric `low` and `high`.
    "estimates_unavailable" is gated by reviewer ruling at the S2c review: the status also comes
    from an enrich record written before estimates were fetched, and from a failed fetch, not only
    from a name yfinance does not cover. Opening it for uncovered names is an operator decision.

    P4.8: symmetric dispersion — `high_dispersion` fires for `overvalued` too, not only
    `undervalued`. band_verdict already demotes both directions to `hold` on write when the
    spread exceeds tolerance, so this mainly guards legacy rows written before that fix.

    B3 (Phase 4 amendment): reason 9 turns validity into an actionability gate, but only once
    the Phase 4 gate itself has set `FIRST_VALID_PACK_REVISION` — this module never sets it.
    While it is None, `analyst_valid()` is False for EVERY row (nothing is valid yet), so gating
    on it unconditionally would make every past and future verdict non-actionable before the
    ruling has even happened; behaviour is therefore unchanged while it is None.
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
    if (direction in ("undervalued", "overvalued") and spread is not None
            and spread > HIGH_DISPERSION_TOL_PCT):
        reasons.append("high_dispersion")

    if v.get("run_source") in _NON_PRODUCTION_SOURCES:
        reasons.append("non_production_row")

    instability = v.get("instability")
    if isinstance(instability, dict) and instability.get("unstable") is True:
        reasons.append("mode_instability")

    if FIRST_VALID_PACK_REVISION is not None and not analyst_valid(v):
        reasons.append("pre_valid_analyst")

    fence = v.get("street_fence")
    med = v.get("median_iv")
    if isinstance(fence, dict) and _is_num(med):
        hi, lo = fence.get("high"), fence.get("low")
        if ((direction == "undervalued" and _is_num(hi) and med > hi)
                or (direction == "overvalued" and _is_num(lo) and med < lo)):
            reasons.append("outside_street_fence")

    mos = v.get("mos_vs_base_pct")
    if _is_num(mos) and abs(mos) > MOS_BEYOND_PCT:
        reasons.append("mos_beyond_150pct")

    flags = v.get("flags") or []
    if "desk_not_used" in flags or "iv_not_desk_backed" in flags:
        reasons.append("desk_not_used")

    if "LOW_EFFORT_RESCUE" in flags:
        reasons.append("low_effort_rescue")

    if any(isinstance(f, str) and f.startswith("SAMPLE_FAILED") for f in flags):
        reasons.append("sample_failed")

    if any(isinstance(f, str) and f.startswith("discovery_failed") for f in flags):
        reasons.append("discovery_failed")

    pc = v.get("producer_class")
    if isinstance(pc, dict):
        if pc.get("status") == "ok" and pc.get("depleting") is True:
            reasons.append("depleting_producer_unsupported")
        elif pc.get("status") != "unknown" and pc.get("status") != "ok":
            # "unavailable", or any status this code does not know: fail closed
            reasons.append("depleting_producer_class_unavailable")
    else:
        try:
            if gv is not None and gv >= 5:
                reasons.append("depleting_producer_class_unavailable")
        except TypeError:
            pass

    cds = v.get("consensus_data_status")
    if cds is not None and cds != "ok":
        reasons.append("consensus_data_unavailable")
    elif cds is None:
        try:
            if gv is not None and gv >= 6:
                reasons.append("consensus_data_unavailable")
        except TypeError:
            pass

    if not (isinstance(fence, dict) and _is_num(fence.get("low")) and _is_num(fence.get("high"))):
        reasons.append("no_street_fence")

    return (not reasons), reasons


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def analyst_valid(v):
    """True only if `v` was produced by the analyst Phase 4 has ruled valid.

    False whenever FIRST_VALID_PACK_REVISION is None (the ruling has not happened yet — NOTHING
    is valid). Once set, True only if `v`'s `pack_revision` is an int >= FIRST_VALID_PACK_REVISION
    AND `gate_version` is an int >= GATE_VERSION. A missing or non-int value on either field is
    False, never guessed. This is independent of `assess()`: a row can be gate-actionable (passes
    every dispersion/fiduciary bar) and still not analyst_valid (predates the Phase 4 ruling), and
    the reverse is also possible.
    """
    if FIRST_VALID_PACK_REVISION is None:
        return False
    v = v or {}
    pr = v.get("pack_revision")
    gv = v.get("gate_version")
    if not isinstance(pr, int) or isinstance(pr, bool):
        return False
    if not isinstance(gv, int) or isinstance(gv, bool):
        return False
    return pr >= FIRST_VALID_PACK_REVISION and gv >= GATE_VERSION

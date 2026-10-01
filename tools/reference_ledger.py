"""The forward ledger of the consensus-implied reference (revision 18, brief section 5, pre-registered).

One JSON line per name per snapshot, appended to cache/reference_ledger.jsonl, for the book and the untouched names. The ledger
is APPEND-ONLY: nothing here rewrites, truncates or edits a line. It runs offline (no model, no network) from the reference's
single source of inputs, `reference_inputs`, so it can run while DEPTH_PAUSED stays. Evaluation is a separate frozen script
(tools/reference_ledger_eval.py) and is report only.

  python tools/reference_ledger.py --snapshot --untouched-list <path> [--untouched-sha256 <hex>] [--ledger <path>]
                                   [--data-root <dir>]

The snapshot's date is today: a forward ledger is never back-dated. The weekly schedule is the operator's decision at ship
time; nothing here registers a task.

THE UNTOUCHED NAMES are read from a list file named by `--untouched-list` or the environment variable RS2_UNTOUCHED_LIST
(never a default, never copied into the repository). They are never printed, logged or put in an error message; every report
here carries counts only.

Integration with revision 18's part 2 (not on this branch yet) is confined to `production_adapters` at the bottom of this file;
the engine of the ledger (`snapshot`, `append_rows`, `read_ledger`) takes its inputs as parameters and is tested with fakes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import sys
from datetime import date as _date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = HERE / "cache" / "reference_ledger.jsonl"
UNTOUCHED_ENV = "RS2_UNTOUCHED_LIST"

# Brief section 5.1: date, ticker, price, reference value and status; V/P; COE, closure premium and its as-of date; revision;
# the published verdict, if any. A line carries exactly these keys, in this order.
FIELDS = ("date", "ticker", "price", "reference_value", "reference_status", "vp", "coe", "closure_erp",
          "closure_asof", "revision", "verdict")
STATUSES = ("used", "outside_fence_above", "outside_fence_below", "not_meaningful", "not_available")
_NUMERIC = ("price", "reference_value", "vp", "coe", "closure_erp")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LedgerSchemaError(ValueError):
    """The ledger, or a row to append, does not match the schema. Nothing is written."""


# ---- the append-only file -------------------------------------------------------------------------------------------

def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_row(row):
    """Raise LedgerSchemaError unless `row` is exactly the schema: the FIELDS and nothing else, each of its type."""
    if not isinstance(row, dict):
        raise LedgerSchemaError(f"a ledger row must be an object, got {type(row).__name__}")
    keys = set(row)
    if keys != set(FIELDS):
        raise LedgerSchemaError(f"schema mismatch: missing {sorted(set(FIELDS) - keys)}, unexpected {sorted(keys - set(FIELDS))}")
    if not (isinstance(row["date"], str) and _DATE_RE.match(row["date"])):
        raise LedgerSchemaError("date must be an ISO date string (YYYY-MM-DD)")
    if not (isinstance(row["ticker"], str) and row["ticker"].strip() and row["ticker"] == row["ticker"].strip()):
        raise LedgerSchemaError("ticker must be a non-empty string")
    for k in _NUMERIC:
        v = row[k]
        if v is not None and not (_is_number(v) and math.isfinite(v)):
            raise LedgerSchemaError(f"{k} must be a finite number or null")
    if row["reference_status"] not in STATUSES:
        raise LedgerSchemaError(f"reference_status must be one of {STATUSES}")
    ca = row["closure_asof"]
    if ca is not None and not (isinstance(ca, str) and _DATE_RE.match(ca)):
        raise LedgerSchemaError("closure_asof must be an ISO date string or null")
    if not (isinstance(row["revision"], int) and not isinstance(row["revision"], bool)):
        raise LedgerSchemaError("revision must be an integer")
    if row["verdict"] is not None and not isinstance(row["verdict"], dict):
        raise LedgerSchemaError("verdict must be an object or null")


def _line(row):
    """One canonical JSON line (FIELDS order, no NaN or infinity) as bytes, newline included."""
    ordered = {k: row[k] for k in FIELDS}
    return (json.dumps(ordered, separators=(",", ":"), allow_nan=False, ensure_ascii=True) + "\n").encode("ascii")


def read_ledger(path):
    """Every row of the ledger at `path`, each validated against the schema; [] when the file does not exist.
    A line that is not valid JSON, a row that does not match the schema, or a file that does not end in a newline (a partial
    write) raises LedgerSchemaError: the ledger is never repaired in place."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "rb") as f:
        raw = f.read()
    if raw and not raw.endswith(b"\n"):
        raise LedgerSchemaError("the ledger does not end in a newline (a partial last line); it is not repaired automatically")
    rows = []
    for n, ln in enumerate(raw.split(b"\n")[:-1], start=1):
        try:
            row = json.loads(ln.decode("utf-8"))
        except ValueError as e:
            raise LedgerSchemaError(f"ledger line {n} is not valid JSON ({e})") from None
        try:
            validate_row(row)
        except LedgerSchemaError as e:
            raise LedgerSchemaError(f"ledger line {n}: {e}") from None
        rows.append(row)
    return rows


def append_rows(path, rows):
    """Append `rows` to the ledger at `path`, never touching a byte already there. Returns (appended, skipped_existing).

    Refuses (LedgerSchemaError, nothing written) when any new row, or any line already in the file, does not match the
    schema, or when two new rows share a (date, ticker). A (date, ticker) already in the ledger is skipped, not rewritten, so
    a second run on one date adds nothing. The file is opened for append only; the new lines go down in one write."""
    p = Path(path)
    for r in rows:
        validate_row(r)
    seen = {(r["date"], r["ticker"]) for r in read_ledger(p)}
    new, batch = [], set()
    skipped = 0
    for r in rows:
        key = (r["date"], r["ticker"])
        if key in batch:
            raise LedgerSchemaError("two rows in one batch share a date and a ticker")
        batch.add(key)
        if key in seen:
            skipped += 1
        else:
            new.append(r)
    if new:
        payload = b"".join(_line(r) for r in new)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "ab") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    return len(new), skipped


# ---- the untouched list ---------------------------------------------------------------------------------------------

def load_untouched(path=None, expect_sha256=None):
    """The untouched names as an upper-case set, read from `path` (or RS2_UNTOUCHED_LIST). One ticker per line; blank lines and
    '#' lines are ignored. Raises, naming no ticker, when no path is configured, the file is missing, or its sha256 differs
    from `expect_sha256`."""
    chosen = path if path is not None else (os.environ.get(UNTOUCHED_ENV) or "").strip() or None
    if chosen is None:
        raise FileNotFoundError(f"the untouched list is not configured: pass --untouched-list or set {UNTOUCHED_ENV}")
    p = Path(chosen).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"the untouched list does not exist at the configured path {p}")
    with open(p, "rb") as f:
        raw = f.read()
    if expect_sha256 is not None and hashlib.sha256(raw).hexdigest().lower() != str(expect_sha256).strip().lower():
        raise ValueError("the untouched list's sha256 differs from the expected value; it is not used")
    names = set()
    for ln in raw.decode("utf-8-sig").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            names.add(s.upper())
    return names


# ---- status, as the pack prints it ----------------------------------------------------------------------------------

def classify_status(value, fence_side):
    """The reference's status, by the pack's own rule (capability_test.build_pack, E15 and brief F5): no value is
    not_available; a value of zero or less as printed to the cent is not_meaningful (the fence is not evaluated for it);
    otherwise outside_fence_above / outside_fence_below when `fence_side()` says so, else used.
    `fence_side` is a zero-argument callable returning 'above', 'below' or None, called only when the fence applies."""
    if value is None:
        return "not_available"
    if float(f"{value:.2f}") <= 0:
        return "not_meaningful"
    side = fence_side()
    return f"outside_fence_{side}" if side else "used"


# ---- the snapshot ---------------------------------------------------------------------------------------------------

def _closure_fields(closure):
    """(erp, asof) from the closure accessor's result (erp, asof, provenance), or (None, None) when there is none."""
    if isinstance(closure, (tuple, list)) and len(closure) >= 2 and _is_number(closure[0]) and math.isfinite(closure[0]):
        asof = closure[1]
        return float(closure[0]), (asof.isoformat() if hasattr(asof, "isoformat") else (None if asof is None else str(asof)[:10]))
    return None, None


def snapshot(snap_date, tickers, untouched, *, inputs_fn, build_fn, fence_fn, price_fn, verdict_fn, closure, revision,
             ledger_path=DEFAULT_LEDGER):
    """Append one row per name to the ledger for `snap_date` (an ISO string) and return a summary of COUNTS ONLY.

    tickers      the book's names; `untouched` (a set) are added to them (a name in both counts once, as untouched).
    inputs_fn    t -> the kwargs of consensus_reference.build, from reference_inputs (must carry 'coe').
    build_fn     the keyword arguments -> consensus_reference.build's dict (carries 'value').
    fence_fn     (value, t) -> 'above' | 'below' | None, the street-target fence the pack applies.
    price_fn     t -> the price, or None.
    verdict_fn   t -> the published verdict as a dict, or None.
    closure      the closure accessor's (erp, asof, provenance), or None.
    A name whose computation raises gets no row and is counted by group and exception class; the summary says so and the
    caller exits non-zero."""
    book = {t.strip().upper() for t in tickers}
    untouched = {t.strip().upper() for t in untouched}
    groups = {t: ("untouched" if t in untouched else "book") for t in sorted(book | untouched)}
    erp, asof = _closure_fields(closure)
    rows, errors, error_samples = [], {}, []
    by_status = {g: {} for g in ("book", "untouched")}
    no_price = 0
    for t, g in groups.items():
        try:
            price = price_fn(t)
            price = float(price) if price is not None else None
            inputs = inputs_fn(t)
            ref = build_fn(**inputs)
            value = ref.get("value")
            value = float(value) if value is not None else None
            status = classify_status(value, lambda: fence_fn(value, t))
            coe = inputs.get("coe")
            vp = value / price if (value is not None and price is not None and price > 0) else None
            row = {"date": snap_date, "ticker": t, "price": price, "reference_value": value, "reference_status": status,
                   "vp": vp, "coe": None if coe is None else float(coe), "closure_erp": erp, "closure_asof": asof,
                   "revision": revision, "verdict": verdict_fn(t)}
            validate_row(row)
        except Exception as e:  # counted and reported by class, never swallowed: the caller exits non-zero
            key = f"{g}:{type(e).__name__}"
            errors[key] = errors.get(key, 0) + 1
            if g == "book" and len(error_samples) < 3:
                error_samples.append(f"{t}: {type(e).__name__}: {str(e)[:200]}")
            continue
        rows.append(row)
        by_status[g][status] = by_status[g].get(status, 0) + 1
        no_price += int(price is None)
    appended, skipped = append_rows(ledger_path, rows)
    return {"date": snap_date, "revision": revision, "names_book": sum(1 for g in groups.values() if g == "book"),
            "names_untouched": sum(1 for g in groups.values() if g == "untouched"),
            "in_both_lists": len(book & untouched), "rows_appended": appended, "skipped_existing": skipped,
            "no_price": no_price, "closure_erp_recorded": erp is not None, "status_counts": by_status,
            "errors": errors, "error_samples_book_only": error_samples}


# ---- the CLI and its production wiring ------------------------------------------------------------------------------

def block_network():
    """The ledger runs offline. Any socket opened from here on raises."""
    class _Blocked(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("network access is blocked in the reference ledger run")
    socket.socket = _Blocked

    def _no_resolve(*a, **k):
        raise RuntimeError("network name resolution is blocked in the reference ledger run")
    socket.getaddrinfo = _no_resolve
    socket.create_connection = _no_resolve


def production_adapters(data_root):
    """The five callables `snapshot` takes, wired to production, plus the book, the closure and the revision.

    INTEGRATION POINTS (revision 18 part 2; none of these exists on the branch this was written on):
      1. `capability_test.reference_inputs(t, data_root, estimates, anchors, closure)` -> the keyword arguments of
         `consensus_reference.build`, with 'coe' among them (brief section 2.1).
      2. `rs2_data.reference_closure()` -> (erp, asof, provenance), or a stated reason (brief section 2.7).
    The rest exists today: capability_test._reference_outside_fence and valuation_backbone._consensus_band (the fence),
    consensus_reference.build, capability_test.PACK_REVISION, depth_membership._current_book (the book) and the local
    overlay (cache/depth_overlay.json) for the published verdict. The price is the screener's own file
    (financials/<T>.json, 'Price'), so the run needs no network."""
    root = Path(data_root)
    for p in (HERE / "tools" / "audit_202608", HERE / "tools", HERE):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import capability_test as cap
    import consensus_reference as cref
    import depth_membership
    import rs2_data
    import valuation_backbone as vb
    for need, mod in (("reference_inputs", cap), ("reference_closure", rs2_data)):
        if not hasattr(mod, need):
            raise ImportError(f"{mod.__name__}.{need} does not exist yet: this needs revision 18 part 2 (brief section 2)")
    closure = rs2_data.reference_closure()
    anchors = rs2_data.load_anchors()
    sd = Path(rs2_data.CONFIG["screener_data_dir"])
    overlay = rs2_data.load_json(root / "cache" / "depth_overlay.json") or {}
    published = overlay.get("tickers") or {}

    def inputs_fn(t):
        en = rs2_data.load_json(root / "enrich" / f"{t}.json") or {}
        return cap.reference_inputs(t, root, en.get("estimates"), anchors, closure)

    def fence_fn(value, t):
        side, _ = cap._reference_outside_fence(value, vb._consensus_band(t))
        return side

    def price_fn(t):
        fin = rs2_data.load_json(sd / "financials" / f"{t}.json") or {}
        px = fin.get("Price")
        return None if px is None else float(px)

    def verdict_fn(t):
        v = published.get(t)
        if not v:
            return None
        return {"direction": v.get("direction"), "date": v.get("date"), "median_iv": v.get("median_iv")}

    return {"inputs_fn": inputs_fn, "build_fn": lambda **kw: cref.build(**kw), "fence_fn": fence_fn, "price_fn": price_fn,
            "verdict_fn": verdict_fn, "closure": closure, "revision": cap.PACK_REVISION,
            "book": depth_membership._current_book()}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Append today's forward-ledger snapshot (brief section 5). Offline.")
    ap.add_argument("--snapshot", action="store_true", required=True)
    ap.add_argument("--untouched-list", default=None, help=f"the untouched names, one per line (else {UNTOUCHED_ENV})")
    ap.add_argument("--untouched-sha256", default=None, help="refuse the list unless it has this sha256")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--data-root", default=str(HERE), help="the directory holding enrich/ cache/ research/")
    args = ap.parse_args(argv)
    block_network()
    try:
        untouched = load_untouched(args.untouched_list, args.untouched_sha256)
        wiring = production_adapters(args.data_root)
        book = wiring.pop("book")
        summary = snapshot(_date.today().isoformat(), book, untouched, ledger_path=args.ledger, **wiring)
    except (LedgerSchemaError, FileNotFoundError, ValueError, ImportError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=1))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

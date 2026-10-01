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

The production wiring (reference_inputs, the closure accessor, the shared status rule) is confined to `production_adapters` at
the bottom of this file; the engine of the ledger (`snapshot`, `append_rows`, `read_ledger`) takes its inputs as parameters and is
tested with fakes, and tests/test_reference_ledger_production.py pins a production snapshot row to the pack's printed reference.
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
# the published verdict, if any. A line carries exactly these keys, in this order. `price_date` is the date of the quote the
# price comes from (the screener file's fetch date); there is no group field: book and untouched are re-derived from the list.
FIELDS = ("date", "ticker", "price", "price_date", "reference_value", "reference_status", "vp", "coe", "closure_erp",
          "closure_asof", "revision", "verdict")
# The verdict, when there is one: the published label, the Base the verdict rested on, the date it was published and the pack
# revision it was produced under (the evaluation reads the revision to tell a verdict the reference informed from one it did not).
VERDICT_KEYS = ("label", "base_iv", "published_at", "pack_revision")
RUNS_NAME = "reference_ledger_runs.jsonl"
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
    pd_ = row["price_date"]
    if pd_ is not None and not (isinstance(pd_, str) and _DATE_RE.match(pd_)):
        raise LedgerSchemaError("price_date must be an ISO date string or null")
    if row["price"] is None and pd_ is not None:
        raise LedgerSchemaError("price_date without a price")
    if not (isinstance(row["revision"], int) and not isinstance(row["revision"], bool)):
        raise LedgerSchemaError("revision must be an integer")
    v = row["verdict"]
    if v is not None:
        if not isinstance(v, dict) or set(v) != set(VERDICT_KEYS):
            raise LedgerSchemaError(f"verdict must be null or an object with exactly the keys {VERDICT_KEYS}")
        if v["base_iv"] is not None and not (_is_number(v["base_iv"]) and math.isfinite(v["base_iv"])):
            raise LedgerSchemaError("verdict.base_iv must be a finite number or null")
        if v["published_at"] is not None and not (isinstance(v["published_at"], str) and _DATE_RE.match(v["published_at"])):
            raise LedgerSchemaError("verdict.published_at must be an ISO date string or null")
        if v["label"] is not None and not isinstance(v["label"], str):
            raise LedgerSchemaError("verdict.label must be a string or null")
        if v["pack_revision"] is not None and not (isinstance(v["pack_revision"], int) and not isinstance(v["pack_revision"], bool)):
            raise LedgerSchemaError("verdict.pack_revision must be an integer or null")


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
    """The reference's status - the pack's own rule, one copy: consensus_reference.classify_status (revision 18; build_pack
    calls the same function). `fence_side` is a zero-argument callable returning 'above', 'below' or None, called only when the
    fence applies."""
    import consensus_reference
    return consensus_reference.classify_status(value, fence_side)


# ---- the snapshot ---------------------------------------------------------------------------------------------------

def _closure_fields(closure):
    """(erp, asof) from the closure accessor's result (erp, asof, provenance), or (None, None) when there is none."""
    if isinstance(closure, (tuple, list)) and len(closure) >= 2 and _is_number(closure[0]) and math.isfinite(closure[0]):
        asof = closure[1]
        return float(closure[0]), (asof.isoformat() if hasattr(asof, "isoformat") else (None if asof is None else str(asof)[:10]))
    return None, None


def snapshot(snap_date, tickers, untouched, *, inputs_fn, build_fn, fence_fn, price_fn, verdict_fn, closure, revision,
             ledger_path=DEFAULT_LEDGER, runs_path=None):
    """Append one row per name to the ledger for `snap_date` (an ISO string) and return a summary of COUNTS ONLY.

    tickers      the book's names; `untouched` (a set) are added to them (a name in both counts once, as untouched).
    inputs_fn    t -> the kwargs of consensus_reference.build, from reference_inputs (must carry 'coe').
    build_fn     the keyword arguments -> consensus_reference.build's dict (carries 'value').
    fence_fn     (value, t) -> 'above' | 'below' | None, the street-target fence the pack applies.
    price_fn     t -> (price, price_date) - the quote and the ISO date it was taken - or (None, None) / None.
    verdict_fn   t -> the published verdict as {label, base_iv, published_at, pack_revision}, or None.
    closure      the closure accessor's (erp, asof, provenance), or None.
    A name whose computation raises gets NO ROW; it is counted by exception class (the reason), never by name. The summary is
    appended as one line to the append-only runs file (`runs_path`, default next to the ledger) - counts by reason and by
    status, no names - and the caller exits non-zero when any name failed."""
    book = {t.strip().upper() for t in tickers}
    untouched = {t.strip().upper() for t in untouched}
    groups = {t: ("untouched" if t in untouched else "book") for t in sorted(book | untouched)}
    erp, asof = _closure_fields(closure)
    rows, errors, error_samples = [], {}, []
    by_status = {g: {} for g in ("book", "untouched")}
    no_price = 0
    for t, g in groups.items():
        try:
            quote = price_fn(t)
            price, price_date = quote if quote is not None else (None, None)
            price = float(price) if price is not None else None
            price_date = str(price_date)[:10] if (price is not None and price_date is not None) else None
            inputs = inputs_fn(t)
            ref = build_fn(**inputs)
            value = ref.get("value")
            value = float(value) if value is not None else None
            status = classify_status(value, lambda: fence_fn(value, t))
            coe = inputs.get("coe")
            vp = value / price if (value is not None and price is not None and price > 0) else None
            row = {"date": snap_date, "ticker": t, "price": price, "price_date": price_date, "reference_value": value,
                   "reference_status": status, "vp": vp, "coe": None if coe is None else float(coe), "closure_erp": erp,
                   "closure_asof": asof, "revision": revision, "verdict": verdict_fn(t)}
            validate_row(row)
        except Exception as e:  # counted by reason, never swallowed: the caller exits non-zero
            key = type(e).__name__
            errors[key] = errors.get(key, 0) + 1
            if g == "book" and len(error_samples) < 3:
                error_samples.append(f"{t}: {type(e).__name__}: {str(e)[:200]}")
            continue
        rows.append(row)
        by_status[g][status] = by_status[g].get(status, 0) + 1
        no_price += int(price is None)
    appended, skipped = append_rows(ledger_path, rows)
    summary = {"date": snap_date, "revision": revision, "names_book": sum(1 for g in groups.values() if g == "book"),
               "names_untouched": sum(1 for g in groups.values() if g == "untouched"),
               "in_both_lists": len(book & untouched), "rows_appended": appended, "skipped_existing": skipped,
               "no_price": no_price, "closure_erp_recorded": erp is not None, "status_counts": by_status,
               "errors": errors, "error_samples_book_only": error_samples}
    append_run(runs_path if runs_path is not None else Path(ledger_path).with_name(RUNS_NAME), summary)
    return summary


def append_run(path, summary):
    """Append one summary line for a snapshot to the append-only runs file: the date, the revision, the counts of names, rows,
    skipped rows and rows with no price, the counts by status (book and untouched together) and the counts of failed names by
    reason. No name, no group split, no sample message."""
    status_total = {}
    for g in summary["status_counts"].values():
        for k, n in g.items():
            status_total[k] = status_total.get(k, 0) + n
    line = {"date": summary["date"], "revision": summary["revision"],
            "names": summary["names_book"] + summary["names_untouched"], "rows_appended": summary["rows_appended"],
            "skipped_existing": summary["skipped_existing"], "no_price": summary["no_price"],
            "closure_erp_recorded": summary["closure_erp_recorded"], "status_counts": dict(sorted(status_total.items())),
            "failed_by_reason": dict(sorted(summary["errors"].items())),
            "failed": sum(summary["errors"].values())}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab") as f:
        f.write((json.dumps(line, separators=(",", ":"), allow_nan=False) + chr(10)).encode("ascii"))
        f.flush()
        os.fsync(f.fileno())


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


class _Loadings:
    """{sector: Blume-adjusted loading}, read from the MRI cost-of-capital anchor on demand (reference_inputs' `anchors["loading"]`)."""

    def __init__(self, rs2_data):
        self._rs2_data = rs2_data
        self._memo = {}

    def get(self, sector, default=None):
        if sector not in self._memo:
            self._memo[sector] = self._rs2_data.coe_loading(sector)[0]
        v = self._memo[sector]
        return default if v is None else v


def production_adapters(data_root, today=None):
    """The callables `snapshot` takes, wired to production, plus the book, the closure and the revision.

      1. inputs_fn: `capability_test.reference_inputs(t, DataRoot(), estimates, anchors, closure, printed=True)["kwargs"]` - the
         keyword arguments of `consensus_reference.build` (with 'coe'), exactly the call the pack makes; `estimates` are
         `<data_root>/enrich/<T>.json["estimates"]` (a record older than the pack's 45-day suppression gives none, as in the
         pack) and `anchors` the MRI anchors through rs2_data's accessors (rf, the long-run growth anchor, breakeven, loadings).
      2. closure: `rs2_data.reference_closure()` -> (erp, asof, provenance), or (None, asof, reason); the cost of equity has no
         fallback, so without a usable premium a name has no value (status not_available).
      3. status: `classify_status`, which is consensus_reference.classify_status, the rule the pack uses.
      4. fence: `capability_test._reference_outside_fence` on `capability_test._consensus_band_or_none` - the pack's own pair.
      5. price: the screener's own file (financials/<T>.json: 'Price' and the date of its fetch); verdict: the local overlay
         (cache/depth_overlay.json) as {label: direction, base_iv: contract_base of its scorecard, published_at: date, pack_revision};
         book: depth_membership._current_book(); revision: capability_test.PACK_REVISION. `today` is the date the base year's age is
      measured at (default: today). The run needs no network."""
    root = Path(data_root)
    for p in (HERE / "tools" / "audit_202608", HERE / "tools", HERE):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import capability_test as cap
    import consensus_reference as cref
    import depth_membership
    import fiduciary_gate
    import rs2_data
    closure = rs2_data.reference_closure()
    erp = closure[0]
    anchors = {"rf": rs2_data.anchor_risk_free_rate()[0], "ga": rs2_data.anchor_terminal_g()[0],
               "breakeven": rs2_data.anchor_breakeven_10y()[0], "loading": _Loadings(rs2_data)}
    droot = cap.DataRoot()
    sd = Path(rs2_data.CONFIG["screener_data_dir"])
    overlay = rs2_data.load_json(root / "cache" / "depth_overlay.json") or {}
    published = overlay.get("tickers") or {}
    today = today if today is not None else _date.today()

    def inputs_fn(t):
        en = rs2_data.load_json(root / "enrich" / f"{t}.json") or {}
        estimates = en.get("estimates")
        age = cap._age_days(en)
        if age is not None and age > cap.STALE_SUPPRESS_DAYS:
            estimates = None                      # the pack's rule: stale consensus builds no reference
        if not isinstance(estimates, dict):
            estimates = None
        ri = cap.reference_inputs(t, droot, estimates, anchors, {"erp": erp} if erp is not None else None, printed=True, today=today)
        return ri["kwargs"]

    def fence_fn(value, t):
        side, _ = cap._reference_outside_fence(value, cap._consensus_band_or_none(t))
        return side

    def price_fn(t):
        fin = rs2_data.load_json(sd / "financials" / f"{t}.json") or {}
        px = fin.get("Price")
        if px is None:
            return None, None
        fetched = fin.get("Data_Fetched_Date")
        return float(px), (None if fetched is None else str(fetched)[:10])

    def verdict_fn(t):
        v = published.get(t)
        if not v:
            return None
        base = fiduciary_gate.contract_base(v.get("scorecard") or v)
        return {"label": v.get("direction"), "base_iv": None if base is None else float(base),
                "published_at": v.get("date"), "pack_revision": v.get("pack_revision")}

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

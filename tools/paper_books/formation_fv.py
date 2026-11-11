"""formation_fv.py - PREREG_m3o_bookV: the snapshot of one formation's values of record that paper book FV (m3o_engine.py) reads.

    python tools/paper_books/formation_fv.py 2026-11-30

Writes <books>/m3o/value/fv_<T>.json once, from formation_value.py's index (formation_<T>.json), the seed consensus (consensus_<T>.json) and the
formation's map. The values of record exist only after the filing reads finish, which is after the A0 book's fill open, so FV fills on its
own session: the first New York session whose 09:30 open is strictly after the snapshot's written_utc (recorded in the file). Per name:
cheapness = equity value of record / market cap (the single owner of that number; the engine reads it and does not recompute it), or
valued false with the first reason that applies: not_in_index, no_value, shares_missing, shares_differ, market_cap_missing.
Order of checks (each prints one line and returns 0 unless it is a STOP): T before FV_START; the file exists (unchanged: never rewritten,
never compared); no consensus or index yet; a map of a later formation exists (the next formation has been decided, so FV skips T and its
history stays append-only); else build and write (tmp + replace).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402
import m3o_engine as E  # noqa: E402

INPUTS = book_paths.books() / "m3o" / "inputs"
VALUE = book_paths.books() / "m3o" / "value"
EXCLUDED = book_paths.operator_excluded()


def sha(b):
    return E.sha256_bytes(b)


def number(x):
    """x as a float when it is a real number (not a bool, not NaN or infinite), else None. 0.0 is a number."""
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else None


def no_value_reason(c, slots):
    """The consensus reason of a name, else its slots' status:reason joined."""
    r = (c or {}).get("reason")
    if isinstance(r, list):
        r = "; ".join(str(x) for x in r)
    return r or "; ".join(sorted({f"{s.get('status')}:{s.get('reason')}" for s in slots.values()})) or "none recorded"


def seed_shares(slots):
    """The base.shares of every seed whose result is readable and has status ok*."""
    out = []
    for s in slots.values():
        try:
            body = json.loads(Path(s["result"]).read_text(encoding="utf-8"))
        except (KeyError, TypeError, OSError, ValueError):
            continue
        if str(body.get("status", "")).startswith("ok") and number((body.get("base") or {}).get("shares")) is not None:
            out.append(number(body["base"]["shares"]))
    return out


def name_entry(role, t, idx, cons):
    """One name of the snapshot (see the module docstring)."""
    out = {"role": role, "valued": False, "reason": None, "value_base": None, "shares": None, "equity_value": None, "market_cap": None,
           "cheapness": None}
    n = (idx["names"]).get(t)
    if n is None:
        return {**out, "reason": "not_in_index"}
    c = cons["names"].get(t)
    base = number(((c or {}).get("values") or {}).get("base"))
    if c is None or not str(c.get("status", "")).startswith("ok"):
        return {**out, "reason": "no_value: " + no_value_reason(c, n.get("slots") or {})}
    if base is None:
        return {**out, "reason": "no_value: consensus has no base value"}
    shares = seed_shares(n.get("slots") or {})
    if not shares:
        return {**out, "reason": "shares_missing"}
    if len(set(shares)) > 1:
        return {**out, "reason": "shares_differ"}
    cap = number(n.get("market_cap"))
    if cap is None or not cap > 0:
        return {**out, "reason": "market_cap_missing"}
    equity = base * shares[0]
    return {**out, "valued": True, "value_base": base, "shares": shares[0], "equity_value": equity, "market_cap": cap, "cheapness": equity / cap}


def main(formation_T, now=None):
    T = formation_T
    if T < E.FV_START:
        print(f"{T} is before FV_START {E.FV_START}: nothing to do")
        return 0
    out = VALUE / f"fv_{T}.json"
    if out.exists():
        print(f"unchanged: {out.name}")
        return 0
    cpath, ipath, mpath = VALUE / f"consensus_{T}.json", VALUE / f"formation_{T}.json", INPUTS / f"formation_{T}.json"
    if not (cpath.is_file() and ipath.is_file()):
        print(f"not valued yet: {T} has no {'consensus' if not cpath.is_file() else 'valuation index'} file")
        return 0
    later = sorted(p.name for p in INPUTS.glob("formation_*.json")
                   if re.fullmatch(r"formation_(\d{4}-\d{2}-\d{2})\.json", p.name) and p.name[10:20] > T)
    if later:
        print(f"the next formation has been decided ({later[0]}); FV skips {T}")
        return 0
    if not mpath.is_file():
        sys.exit(f"STOP: {mpath.name} is missing")
    craw, iraw, mraw = cpath.read_bytes(), ipath.read_bytes(), mpath.read_bytes()
    cons, idx, m = json.loads(craw), json.loads(iraw), json.loads(mraw)
    held = [e["ticker"] for e in m.get("fv_held") or []]
    both = sorted(set(held) & set(m["names"]))
    if both:
        sys.exit(f"STOP: {both} are in the book and in fv_held of {mpath.name}")
    covered = [("book", t) for t, n in sorted(m["names"].items()) if n.get("state") != "operator_excluded" and t not in EXCLUDED]
    covered += [("fv_held", t) for t in sorted(held)]
    written = (datetime.now(timezone.utc) if now is None else now).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snap = {"formation_T": T, "written_utc": written, "fill_session": E.first_open_after(E.parse_utc(written)).isoformat(),
            "consensus_sha256": sha(craw), "index_sha256": sha(iraw), "map_sha256": sha(mraw),
            "names": {t: name_entry(role, t, idx, cons) for role, t in covered}}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out)
    print(f"wrote {out}: {sum(v['valued'] for v in snap['names'].values())} of {len(snap['names'])} names valued, fill {snap['fill_session']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

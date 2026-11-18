"""PREREG B3b v1.0 with amendment 1 (stocks-workspace docs/review_2026-11-03/PREREG_flags_b3b_v1.0.md and ..._amendment1.md): the scorer of
Qwen's filing-read flag (rule Q1) on the four archival cohorts.

    python tools/archival_flags/flags_score.py classify
        no prices: each slot's group only (kept, q1_only, b1_only, both, no_read, no_packet, open), written to
        cache/m3m_flags_score/classify.json; safe to run any time after the pass (rewritten each time)
    python tools/archival_flags/flags_score.py score --prereg-sha SHA --amendment-sha SHA
        the one scoring, to cache/m3m_flags_score/score.json. Refuses before 2026-11-21 12:00 KST, while any slot with a packet has no final
        run, and when score.json already exists. One price fetch (dropped_readout.yf_fetch, unchanged), made only after every refusal and
        after every row is classified.

Q1 and B1 are m3o_engine.q1 and m3o_engine.b1 called unchanged, with the arguments the live engine gives them. Prices: sessions are SPY's
bars; session 0 is the first session after T (its adjusted open is the base); horizon h is the adjusted close of session h; a name with no
bar on the horizon session itself has no return at that horizon (`no_price`, with its last traded date); nothing is carried forward. Each
name's excess return is reduced by the mean of its own cohort's read-and-priced names at that horizon; the groups are compared by the
difference of those means with a 90% interval from bootstrap draws of companies (by CIK), seed 1000. The functions below take plain data;
only load_rows and main touch files.
"""
import argparse
import copy
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flags_run as FRUN  # noqa: E402  (also puts the repository root and tools/paper_books on sys.path)
import baseline_b  # noqa: E402
import dropped_readout as DR  # noqa: E402
import m3o_engine as E  # noqa: E402
from qwen_c.runner import sha256_file  # noqa: E402

ROOT = FRUN.ROOT
OUT_DIR = ROOT / "cache" / "m3m_flags_score"
HORIZONS = (20, 60, 120, 250)
PRIMARY_H = 60
SEED, DRAWS = 1000, 10000
NOT_BEFORE = datetime(2026, 11, 21, 12, 0, tzinfo=timezone(timedelta(hours=9)))       # 12:00 KST
GROUPS = ("kept", "q1_only", "b1_only", "both")
SETS = {"kept": ("kept",), "q1_only": ("q1_only",), "b1_only": ("b1_only",), "q1_restricted": ("q1_only", "both"),
        "q1_not_restricted": ("kept", "b1_only")}
COMPARISONS = (("primary", "q1_only", "kept"), ("q1_restricted_vs_not", "q1_restricted", "q1_not_restricted"),
               ("b1_only_vs_kept", "b1_only", "kept"), ("q1_only_vs_b1_only", "q1_only", "b1_only"))
MIN_CLASS_NAMES = 5
BELOW = -0.20


class Refused(Exception):
    pass


# ---------------------------------------------------------------- groups, S0, later names (pure)

def group_of(q1_restricted, b1_restricted, state):
    """kept / q1_only / b1_only / both for a name with a read; else its state (no_read, no_packet, open)."""
    if state != "read":
        return state
    return {(False, False): "kept", (True, False): "q1_only", (False, True): "b1_only", (True, True): "both"}[(bool(q1_restricted), bool(b1_restricted))]


def acting_s0_claims(q):
    """The acting Q1 claims (m3o_engine.q1's output) that cite the screener row item S0 (amendment C)."""
    return [c for c in q["claims"] if c.get("acts") and "S0" in (c.get("fact_ids") or [])]


def s0_name(packet):
    """The company name printed on the packet's S0 line `name: ...`, or None."""
    for e in packet.get("evidence") or []:
        if e.get("fact_id") == "S0":
            for line in (e.get("text") or "").splitlines():
                if line.startswith("name: "):
                    return line[len("name: "):].strip()
    return None


def _norm(name):
    return None if name is None else " ".join(name.casefold().split())


def later_name(s0, names_at_T):
    """Amendment C: True when the S0 company name is not among the names the pinned SEC submissions file shows in use at T."""
    return _norm(s0) not in {_norm(n) for n in names_at_T}


def names_in_use(subs, T):
    """The company names an SEC submissions document shows in use on T's date: each former name whose period holds that date, and the
    current name unless a former name ended after it (the current name was then adopted later)."""
    day, formers = T[:10], subs.get("formerNames") or []
    out = {f.get("name") for f in formers if str(f.get("from") or "")[:10] <= day < str(f.get("to") or "")[:10]}
    if not any(str(f.get("to") or "")[:10] > day for f in formers):
        out.add(subs.get("name"))
    return out


def names_at_T(packet, T):
    """names_in_use of the packet's pinned submissions file (raw_inputs: url and sha256; the bytes are in the packet store's raw folder,
    checked against the sha256). A packet with no such pin has no names: its row is later-name (it cannot be shown otherwise)."""
    pins = [r for r in packet.get("raw_inputs") or [] if str(r.get("url", "")).startswith("https://data.sec.gov/submissions/CIK")]
    if not pins:
        return set()
    raw = FRUN.PACKETS.parent / "raw" / pins[0]["sha256"]
    if sha256_file(raw) != pins[0]["sha256"]:
        raise Refused(f"{packet.get('ticker')}: the stored submissions file does not match its pinned sha256")
    return names_in_use(json.loads(raw.read_bytes().decode("utf-8")), T)


# ---------------------------------------------------------------- one slot (Q1 and B1 unchanged)

def classify_slot(T, ticker, packet, state, analysis, type_to_class, compiled, names_fn=None):
    """One row. state: read | no_read | open (a slot with a packet and no final run) | no_packet (packet None)."""
    row = {"ticker": ticker, "T": T, "cohort": T[:10], "cik": None, "state": "no_packet" if packet is None else state, "q1_restricted": None,
           "b1_restricted": None, "acting_claims": [], "cites_s0": False, "s0_claims": [], "s0_name": None, "later_name": None}
    if packet is None or state not in ("read", "no_read"):
        row["group"] = row["state"]
        return row
    T_date = date.fromisoformat(T[:10])
    row["cik"] = packet.get("cik")
    row["s0_name"] = s0_name(packet)
    row["b1_restricted"] = any(h["acts"] for h in E.b1(packet, T_date, compiled))
    if state == "read":
        items = {e["fact_id"]: e.get("text") or "" for e in packet.get("evidence") or []}
        q = E.q1(analysis, T_date, type_to_class, items)
        row["q1_restricted"] = q["restricted"]
        row["acting_claims"] = [c for c in q["claims"] if c.get("acts")]
        row["s0_claims"] = acting_s0_claims(q)
        row["cites_s0"] = bool(row["s0_claims"])
    if names_fn is not None:
        row["later_name"] = later_name(row["s0_name"], names_fn(packet, T))
    row["group"] = group_of(row["q1_restricted"], row["b1_restricted"], state)
    return row


# ---------------------------------------------------------------- prices (pure; no carry-forward)

def sessions_after(spy_bars, T_date):
    """SPY's session dates after T (session 0 first)."""
    return [d for d in sorted(spy_bars) if d > T_date.isoformat()]


def closed_horizons(spy_bars, T_date, horizons=HORIZONS):
    """The horizons whose session exists among SPY's sessions on the scoring day."""
    n = len(sessions_after(spy_bars, T_date))
    return [h for h in horizons if n > h]


def excess_returns(bars, spy_bars, T_date, horizons=HORIZONS):
    """({h: excess return or None}, {h: True when closed and the name has no return}, last traded date or None), closed horizons only
    appear in the first two. Base: the adjusted open of session 0; horizon h: the adjusted close of session h itself, never an earlier bar."""
    after = sessions_after(spy_bars, T_date)
    ex, no_price = {}, {}
    for h in horizons:
        if len(after) <= h:
            continue
        base, d = bars.get(after[0]), after[h]
        if base is None or base[0] == 0 or d not in bars:
            ex[h], no_price[h] = None, True
            continue
        s_base = spy_bars[after[0]][0]
        ex[h] = (bars[d][1] / base[0] - 1.0) - (spy_bars[d][1] / s_base - 1.0)
        no_price[h] = False
    return ex, no_price, (max(bars) if bars else None)


def add_prices(rows, bars_by_ticker, spy_bars, horizons=HORIZONS):
    """Fills each row's excess, no_price (list of horizons), last_traded and demeaned ({h: value}); the demeaning mean is over the read and
    priced names of the row's own cohort at that horizon. Rows without a read have no return."""
    closed = {}
    for r in rows:
        r["excess"], r["demeaned"], r["no_price"], r["last_traded"] = {}, {}, [], None
        closed.setdefault(r["cohort"], closed_horizons(spy_bars, date.fromisoformat(r["cohort"]), horizons))
        if r["state"] != "read":
            continue
        ex, npx, r["last_traded"] = excess_returns(bars_by_ticker.get(r["ticker"]) or {}, spy_bars, date.fromisoformat(r["cohort"]), horizons)
        r["excess"] = {str(h): v for h, v in ex.items()}
        r["no_price"] = [h for h, v in npx.items() if v]
    for r in rows:
        for h in closed[r["cohort"]]:
            if r["excess"].get(str(h)) is None:
                continue
            mates = [x["excess"][str(h)] for x in rows if x["cohort"] == r["cohort"] and x["excess"].get(str(h)) is not None]
            r["demeaned"][str(h)] = r["excess"][str(h)] - statistics.fmean(mates)
    return closed


# ---------------------------------------------------------------- statistics (pure)

def bootstrap(a, b, seed=SEED, draws=DRAWS):
    """a, b: {company: [values]}. (5th percentile, 95th percentile, skipped draws) of the difference of means (a minus b) over draws of
    companies with all their appearances; a draw where either group is empty is skipped."""
    comps = sorted(set(a) | set(b))
    if not comps:
        return None, None, draws
    sa = np.array([sum(a.get(c, ())) for c in comps], dtype=float)
    sb = np.array([sum(b.get(c, ())) for c in comps], dtype=float)
    na = np.array([len(a.get(c, ())) for c in comps], dtype=float)
    nb = np.array([len(b.get(c, ())) for c in comps], dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(comps), size=(draws, len(comps)))
    NA, NB = na[idx].sum(axis=1), nb[idx].sum(axis=1)
    ok = (NA > 0) & (NB > 0)
    skipped = int((~ok).sum())
    if not ok.any():
        return None, None, skipped
    diff = sa[idx].sum(axis=1)[ok] / NA[ok] - sb[idx].sum(axis=1)[ok] / NB[ok]
    return float(np.percentile(diff, 5)), float(np.percentile(diff, 95)), skipped


def _company(r):
    return r["cik"] if r["cik"] is not None else f"nocik:{r['ticker']}"


def _side(rows, groups, h):
    by, no_price = {}, 0
    for r in rows:
        if r["group"] in groups:
            v = r["demeaned"].get(str(h))
            if v is None:
                no_price += r["excess"].get(str(h)) is None and h in r["no_price"]
            else:
                by.setdefault(_company(r), []).append(v)
    vals = [v for x in by.values() for v in x]
    return by, {"n": len(vals), "mean": statistics.fmean(vals) if vals else None, "median": statistics.median(vals) if vals else None,
                "n_no_price": no_price}


def compare(rows, h, a_groups, b_groups, seed=SEED, draws=DRAWS):
    """Two groups at horizon h (demeaned excess): n, mean, median, difference of means, 90% interval and skipped draws."""
    a, sa = _side(rows, a_groups, h)
    b, sb = _side(rows, b_groups, h)
    diff = sa["mean"] - sb["mean"] if sa["n"] and sb["n"] else None
    lo, hi, skipped = bootstrap(a, b, seed, draws)
    return {"a": sa, "b": sb, "diff_of_means": diff, "interval90": [lo, hi], "skipped_draws": skipped}


def sentence(primary, h=PRIMARY_H):
    """The sentence of amendment E from the primary comparison (an interval wholly below zero, wholly above, or neither)."""
    lo, hi = primary["interval90"]
    n = f"{primary['a']['n']} restricted, {primary['b']['n']} kept"       # amendment D: the survivorship statement rides on every form
    if hi is not None and hi < 0:
        return f"Names restricted by Qwen's read alone did worse than kept names over {h} sessions ({n}; survivor-conditioned pool)"
    if lo is not None and lo > 0:
        return f"Names restricted by Qwen's read alone did better than kept names over {h} sessions ({n}; survivor-conditioned pool)"
    return f"no difference shown ({n}; survivor-conditioned pool)"


def scopes(cohorts):
    out = {"all": list(cohorts)}
    out.update({c: [c] for c in cohorts})
    out.update({y: [c for c in cohorts if c.startswith(y)] for y in sorted({c[:4] for c in cohorts})})
    return out


def r4(rows, closed):
    """Share of names with excess return below -20% at the longest horizon closed for the name's cohort: Q1-restricted against kept."""
    out = {}
    for label, cohorts in scopes(sorted(closed)).items():
        cell = {"restricted": [0, 0], "kept": [0, 0]}
        for r in rows:
            if r["cohort"] in cohorts and closed[r["cohort"]] and r["group"] in SETS["q1_restricted"] + SETS["kept"]:
                v = r["excess"].get(str(max(closed[r["cohort"]])))
                if v is not None:
                    k = cell["restricted" if r["group"] in SETS["q1_restricted"] else "kept"]
                    k[0] += 1
                    k[1] += v < BELOW
        out[label] = {g: {"n": n, "n_below": b, "share": b / n if n else None} for g, (n, b) in cell.items()}
    return out


def r5(rows, h=PRIMARY_H):
    """Acting Q1 claims by event class: names with such a claim, and the mean raw excess return at h of those with a price (no mean under
    5 priced names)."""
    by = {}
    for r in rows:
        for cls in {c["class"] for c in r["acting_claims"]}:
            by.setdefault(cls, []).append(r["excess"].get(str(h)))
    out = {}
    for cls, vs in sorted(by.items()):
        priced = [v for v in vs if v is not None]
        out[cls] = {"n_names": len(vs), "n_priced": len(priced), "mean": statistics.fmean(priced) if len(priced) >= MIN_CLASS_NAMES else None}
    return out


def analyze(rows, closed, seed=SEED, draws=DRAWS):
    """Every reading on `rows` (already priced and demeaned): counts, the four comparisons per scope and closed horizon, R4, R5."""
    out = {"counts": {}, "comparisons": {}}
    for label, cohorts in scopes(sorted(closed)).items():
        sub = [r for r in rows if r["cohort"] in cohorts]
        c = {g: sum(r["group"] == g for r in sub) for g in GROUPS + ("no_read", "no_packet", "open")}
        n_read = sum(c[g] for g in GROUPS)
        c["share_restricted_by_q1"] = (c["q1_only"] + c["both"]) / n_read if n_read else None
        out["counts"][label] = c
        for h in HORIZONS:
            used = [d for d in cohorts if h in closed[d]]
            if used:
                s = [r for r in sub if r["cohort"] in used]
                out["comparisons"].setdefault(label, {})[str(h)] = {"cohorts": used, **{n: compare(s, h, SETS[a], SETS[b], seed, draws)
                                                                                      for n, a, b in COMPARISONS}}
    out["r4"], out["r5"] = r4(rows, closed), r5(rows)
    return out


def score_rows(rows, bars_by_ticker, spy_bars, seed=SEED, draws=DRAWS):
    """Prices the rows and returns the readings for the full set and without the later-name set, with the sentences."""
    closed = add_prices(rows, bars_by_ticker, spy_bars)
    full = analyze(rows, closed, seed, draws)
    left = copy.deepcopy([r for r in rows if not r["later_name"]])
    add_prices(left, bars_by_ticker, spy_bars)                            # demeaned again over the names left (the later-name set is out)
    without = analyze(left, closed, seed, draws)
    sent = {k: sentence(v["comparisons"]["all"][str(PRIMARY_H)]["primary"]) if str(PRIMARY_H) in v["comparisons"].get("all", {}) else None
            for k, v in (("full", full), ("without_later_name", without))}
    return {"closed": closed, "full": full, "without_later_name": without, "sentences": sent}


# ---------------------------------------------------------------- the commands

def check_gates(now, open_slots, out_exists):
    """The three refusals of the scoring, in order: the date, an open slot, an existing output."""
    if now < NOT_BEFORE:
        raise Refused(f"not before {NOT_BEFORE.isoformat()} (now {now.isoformat()})")
    if open_slots:
        raise Refused(f"{len(open_slots)} slot(s) still open, first {open_slots[0]}")
    if out_exists:
        raise Refused("the output file exists: one scoring only")


def final_runs():
    """{(ticker, T): (state, run_id)} for slots with a final run: flags_run.final_runs (one owner of the rule)."""
    return FRUN.final_runs()


def load_rows(with_names):
    """(rows, open slots) from the pool files, the packets and the final runs of flags_run.OUT."""
    type_to_class = {v: k for k, v in json.loads(E.PREREG_M3O.read_bytes())["rules"]["Q1"]["event_types"].items()}
    compiled, final, rows, open_slots = baseline_b.rules(), final_runs(), [], []
    for T, ticker, path in FRUN.slots():
        packet = json.loads(path.read_text(encoding="utf-8")) if path is not None else None
        state, run_id = final.get((ticker, T), ("open", None))
        analysis = None
        if state == "read":
            d = FRUN.OUT / "runs" / run_id
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            if sha256_file(d / "analysis.json") != man.get("analysis_sha256"):
                raise Refused(f"{ticker} {T}: analysis.json does not match its manifest sha256")
            analysis = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
        if packet is not None and state == "open":
            open_slots.append(f"{ticker}@{T[:10]}")
        rows.append(classify_slot(T, ticker, packet, state, analysis, type_to_class, compiled, names_at_T if with_names else None))
    return rows, open_slots


def write_new(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)


def cmd_classify(load=load_rows, out_dir=OUT_DIR):
    rows, open_slots = load(True)
    out = {"open_slots": open_slots, "rows": [{k: r[k] for k in ("ticker", "T", "cohort", "cik", "state", "group", "q1_restricted", "b1_restricted",
                                                                 "later_name")} for r in rows],
           "counts": {c: {**{g: sum(r["cohort"] == c and r["group"] == g for r in rows) for g in GROUPS + ("no_read", "no_packet", "open")},
                          "later_name": sum(r["cohort"] == c and bool(r["later_name"]) for r in rows)}
                      for c in sorted({r["cohort"] for r in rows})}}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classify.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    return out


def cmd_score(prereg_sha, amendment_sha, now, load=load_rows, fetch=DR.yf_fetch, out_dir=OUT_DIR):
    out_path = out_dir / "score.json"
    rows, open_slots = load(False)
    check_gates(now, open_slots, out_path.exists())
    rows, _ = load(True)                                      # the later-name set is decided before the one price fetch is spent
    read = [r for r in rows if r["state"] == "read"]
    start = min(date.fromisoformat(r["cohort"]) for r in read)
    source, px = fetch(sorted({r["ticker"] for r in read} | {"SPY"}), start, now.date())
    res = score_rows(rows, px, px["SPY"])
    out = {"prereg_sha256": prereg_sha, "amendment_sha256": amendment_sha, "scored_at": now.isoformat(), "price_source": source,
           "horizons": list(HORIZONS), "seed": SEED, "draws": DRAWS, "rows": rows, **res,
           "later_name_set": [f"{r['ticker']}@{r['cohort']}" for r in rows if r["later_name"]],
           "cites_s0": [{"ticker": r["ticker"], "T": r["T"], "claims": r["s0_claims"]} for r in rows if r["cites_s0"]],
           "no_price": [{"ticker": r["ticker"], "cohort": r["cohort"], "horizons": r["no_price"], "last_traded": r["last_traded"]}
                        for r in rows if r["no_price"]],
           "no_read": [f"{r['ticker']}@{r['cohort']}" for r in rows if r["state"] == "no_read"],
           "no_packet": [f"{r['ticker']}@{r['cohort']}" for r in rows if r["state"] == "no_packet"]}
    write_new(out_path, out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("classify")
    s = sub.add_parser("score")
    s.add_argument("--prereg-sha", required=True)
    s.add_argument("--amendment-sha", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "classify":
            print(json.dumps(cmd_classify()["counts"], indent=1))
        else:
            print(json.dumps(cmd_score(a.prereg_sha, a.amendment_sha, datetime.now(timezone.utc))["sentences"], indent=1))
    except Refused as e:
        print(f"refused: {e}")
        sys.exit(3)

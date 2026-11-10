"""v13_score.py - the registered reading of the prompt v13 replay (SPEC_prompt_v13, check 2; written 2026-11-11, before its run ended).

    python tools/archival_street/v13_score.py

v12 = S1b's seed-1000 slot (slots.json); v13 = the replay's seed-1300 slot (v13_slots.json), both in archival_2025-10-01_pit.
A year-1 guidance pick is a reply whose rev_growth.y1 code read as guidance (options rev_growth.y1 == "guidance") or reverted as
unreadable (an annotation "guidance_unreadable: rev_growth.y1 ..."). Realised year-1 growth: J2's annual reader on the documents the
pool recorded (score.realised_of, growth_same); a name without one is counted, never imputed.
(1) unreadable share = unreadable / picks, per prompt; v13 passes (1) when its share is not above v12's.
(2) on names where both prompts read guidance and realised exists: median |ln((1 + G) / (1 + realised))|; v13 passes (2) when its
    median is not above v12's.
PASS when both hold. Reported, never judged: found entries on names where v13 kept the pace (readable / unreadable).
Amendment 2026-11-11 (SPEC_prompt_v13, written before the replay ended): v13 is used when that reading passes or the paired reading
(`paired`) passes. The paired reading needs a hand ruling on each v13 period revert of a name v12 read (v13_period_rulings.json
beside the slots); without one the scorer lists the sentences and stops.
Output v13_score.json beside the slots; it is never overwritten.
"""
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(HERE), str(ROOT / "tools" / "archival_j2")):
    if p not in sys.path:
        sys.path.insert(0, p)
from greedy_check import DIR, sha  # noqa: E402

KEY = "rev_growth.y1"
SIDES = (("v12", "slots.json", 1000), ("v13", "v13_slots.json", 1300))
P_WORSE, TIE = 0.10, 1e-9                                  # the paired reading's bar and its tie width
PERIOD_WHY = "the sentence guides a "                      # menu.read_guidance's v7 period revert
RULINGS = "v13_period_rulings.json"                        # {ticker: {"guides": "year" | "half" | "quarter", "note": ...}}, by hand


def pick(r):
    """'read', 'unreadable', 'pace', or None (no checked reply)."""
    ch = (r or {}).get("checks") or {}
    if not ch.get("options"):
        return None
    if unreadable_why(r) is not None:
        return "unreadable"
    return "read" if ch["options"].get(KEY) == "guidance" else "pace"


def unreadable_why(r):
    """Why code reverted the year-1 guidance pick as unreadable, or None. checks writes it to `reverts` (and `stamps`), never to
    `annotations` (fixed 2026-11-11 before any score: the first version looked in `annotations` and would have counted none)."""
    pre = f"guidance_unreadable: {KEY} "
    return next((a[len(pre):] for a in ((r or {}).get("checks") or {}).get("reverts") or [] if a.startswith(pre)), None)


def sign_p(k, n):
    """One-sided exact sign test: P(X >= k | n, 1/2); None for n = 0."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else None


def paired(rows, caught=()):
    """The paired reading (SPEC_prompt_v13, amendment 2026-11-11): v13 fails only where it is clearly worse.
    `caught`: names whose v13 period revert was ruled, by hand, a sentence that does guide a half or a quarter."""
    picks = ("read", "unreadable")
    pairs = {t: x for t, x in rows.items() if x["v12"][0] in picks and x["v13"][0] in picks}
    b = sorted(t for t, x in pairs.items() if (x["v12"][0], x["v13"][0]) == ("read", "unreadable") and t not in caught)
    c = sorted(t for t, x in pairs.items() if (x["v12"][0], x["v13"][0]) == ("unreadable", "read"))
    p1 = sign_p(len(b), len(b) + len(c))
    d = [err(x["v13"][1], x["realised"]) - err(x["v12"][1], x["realised"]) for x in pairs.values()
         if x["v12"][0] == x["v13"][0] == "read" and x["realised"] is not None]
    worse, better = sum(1 for v in d if v > TIE), sum(1 for v in d if v < -TIE)
    p2 = sign_p(worse, worse + better)
    f1, f2 = len(b) > len(c) and p1 < P_WORSE, worse > better and p2 < P_WORSE
    one = {side: sorted(t for t, x in rows.items() if x[side][0] in picks and x[other][0] not in picks)
           for side, other in (("v12", "v13"), ("v13", "v12"))}
    return {"pairs": len(pairs), "b": b, "c": c, "caught": sorted(caught), "p1": p1, "fail1": f1, "worse": worse, "better": better,
            "ties": len(d) - worse - better, "p2": p2, "fail2": f2, "pick_under_one_prompt_only": one,
            "verdict": "FAIL" if f1 or f2 else "PASS"}


def err(g, real):
    return abs(math.log((1 + g) / (1 + real)))


def reading(rows):
    """rows: {ticker: {"v12": (pick, G), "v13": (pick, G), "realised": r or None}} -> the registered reading."""
    out = {}
    for side, _, _ in SIDES:
        ps = [x[side][0] for x in rows.values() if x[side][0] is not None]
        k, n = ps.count("unreadable"), ps.count("unreadable") + ps.count("read")
        out[side] = {"checked": len(ps), "picks": n, "read": ps.count("read"), "unreadable": k, "share": k / n if n else None}
    both = {t: x for t, x in rows.items() if x["v12"][0] == "read" and x["v13"][0] == "read"}
    have = {t: x for t, x in both.items() if x["realised"] is not None}
    for side, _, _ in SIDES:
        out[side]["median_error"] = statistics.median(err(x[side][1], x["realised"]) for x in have.values()) if have else None
    c1 = out["v12"]["share"] is not None and out["v13"]["share"] is not None and out["v13"]["share"] <= out["v12"]["share"]
    c2 = bool(have) and out["v13"]["median_error"] <= out["v12"]["median_error"]
    out.update(both_read=len(both), both_read_with_realised=len(have), check1=c1, check2=c2, verdict="PASS" if c1 and c2 else "FAIL")
    return out


def cited(r, packet_path):
    """The year-1 guidance entry of the checked reply and the text of the packet sentence it cites (for the hand ruling)."""
    from qwen_c.value import sentences
    a = next((x for x in r.get("attempts") or [] if x.get("attempt") == r.get("checked_attempt")), None) or {}
    e = ((a.get("inputs") or {}).get("guidance") or {}).get(KEY) or {}
    ids = sentences.index(json.loads(Path(packet_path).read_text(encoding="utf-8")).get("evidence") or [])
    return {"entry": e, "why": unreadable_why(r), "sentence": (ids.get(e.get("evidence")) or {}).get("text")}


def main():
    import score as J2                                       # J2's scorer: realised_of, census
    out_path = DIR / "v13_score.json"
    if out_path.exists():
        sys.exit(f"STOP: {out_path} exists; a score is never overwritten")
    pool = J2.census(json.loads((DIR / "pool.json").read_text(encoding="utf-8")))
    by = {n["ticker"]: n for n in pool["pool"]}
    slots = {side: json.loads((DIR / f).read_text(encoding="utf-8"))["slots"] for side, f, _ in SIDES}
    names = json.loads((DIR / "v13_slots.json").read_text(encoding="utf-8"))["names"]
    packets = json.loads((DIR / "runs.json").read_text(encoding="utf-8"))["packets"]
    rows, found, missing, period = {}, {"pace_with_readable": [], "pace_with_unreadable_only": [], "pace_with_none": 0}, [], {}
    for t in names:
        res = {}
        for side, _, seed in SIDES:
            s = slots[side].get(f"{t}:{seed}")
            if s is None:
                missing.append(f"{t}:{seed}")
                continue
            raw = Path(s["result"]).read_bytes()
            if sha(raw) != s["result_sha256"]:
                sys.exit(f"STOP: {t}:{seed} result.json does not hash to its slot")
            res[side] = json.loads(raw.decode("utf-8"))
        if len(res) < 2:
            continue
        row = {side: (pick(res[side]), ((res[side].get("checks") or {}).get("numbers") or {}).get(KEY)) for side, _, _ in SIDES}
        row["realised"] = None
        if row["v12"][0] == "read" and row["v13"][0] == "read":
            row["realised"] = J2.realised_of(by[t], Path(pool["store"]))["growth_same"]
        rows[t] = row
        if row["v12"][0] == "read" and (unreadable_why(res["v13"]) or "").startswith(PERIOD_WHY):
            period[t] = cited(res["v13"], packets[t]["packet"])   # needs a ruling by hand: does it guide a half or a quarter?
        if row["v13"][0] == "pace":
            fl = (res["v13"].get("checks") or {}).get("found") or []
            if any(e.get("number") is not None for e in fl):
                found["pace_with_readable"].append(t)
            elif fl:
                found["pace_with_unreadable_only"].append(t)
            else:
                found["pace_with_none"] += 1
    rp = DIR / RULINGS
    rulings = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    if set(period) - set(rulings):
        print(json.dumps({t: period[t] for t in sorted(set(period) - set(rulings))}, indent=1))
        sys.exit(f"STOP: the period reverts above need a ruling in {rp} before the score is written")
    reg = reading(rows)
    par = paired(rows, {t for t in period if rulings[t]["guides"] in ("half", "quarter")})
    doc = {"reading": reg, "paired": par, "period_reverts": {t: dict(period[t], ruling=rulings[t]) for t in period},
           "use_v13": reg["verdict"] == "PASS" or par["verdict"] == "PASS",
           "found_on_pace": found, "missing_slots": missing, "rows": rows}
    out_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("reading", "paired", "use_v13", "missing_slots")}, indent=1))
    print("found on pace:", {k: (len(v) if isinstance(v, list) else v) for k, v in found.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())

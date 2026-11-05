"""score.py - J2-6: the scorer of the archival year-1 forecast test at T 2025-12-31, as registered in the FROZEN PREREG
m3o.value_addendum.v1.0 ("archival_test"), with J2_SPEC_forecast_test_v02.md sections 4-7 and the coordinator's rulings of 2026-11-04.

    python tools/archival_j2/score.py [--dir DIR]

Inputs (DIR, default <books>/m3o/value/archival_2025-12-31/): pool.json (its sha256 must be the PREREG's), runs.json (packets), slots.json
(the seeds' result.json files, each rechecked against its recorded sha256). Writes score.json and score.md beside them; refuses to
overwrite score.json, and refuses an incomplete run: a pool name without a packet entry, or a packeted name missing a seed.

THE RULES, per company-key (rev_growth.y1, op_margin.y1). A company-key leaves at the first of these, counted by reason:
 1 neutral_not_run_rate   pool.json run_rate[key] is False (the neutral is the anchor or the record median: reported, never judged).
                          The flag is primary; every stored result is cross-checked against it (base.ytd measured exactly where the flag
                          is True, by menu's own rules; checks.neutral[key] == that ytd value; the ytd value identical across seeds).
                          Any disagreement STOPS the scorer.
 2 packet_refused:<code>  runs.json holds a refusal for the name (a "held_out: ..." refusal included); <code> is the refusal's own code.
 3 seed_<one|none>_scored:<statuses>   a seed not scored. Scored: ok, ok_with_reverts, and a no_call that carries checks.numbers
                          (PREREG: year 1 is scored from checks.numbers even when the desk refuses the Base). Not scored: reply_invalid,
                          malformed, no_call_without_numbers. Both seeds must be scored (per-protocol exclusion).
 4 not_departed           neither seed's checks.numbers[key] differs from checks.neutral[key] by more than menu.TOL (menu.departed).
 5 realised_unavailable:<why>   realised.py on the exact companyfacts and submissions the pool recorded (sec_store.get_pinned) gives no
                          same-filing growth (its status) or no margin (margin_absent). Counted, never imputed.
JUDGED: model = the two-seed mean of checks.numbers[key]; run_rate = the ytd value; d = |model - realised| - |run_rate - realised|.
Per key: n (ties included), median d, share of d < 0 (of n), the one-sided exact sign test of "model no better than the run rate"
(k = #{d < 0} of the non-ties, p = P(Bin(n_nontie, 1/2) >= k); ties |d| <= 1e-12 dropped), the winsorised mean d (d clipped at its 5th
and 95th percentiles, numpy linear interpolation), and the 90th percentile of 2,000 company-level bootstrap medians (numpy
default_rng(20261104), companies in ticker order; reported only).
VERDICT: NOT_DECIDED when n < 20; else PASS iff p < 0.05 AND winsorised mean d <= 0; else FAIL.
REPORTED, never judged: segments (per seed: guidance citing an outlook = every cited kind release/other_8k; guidance citing a 10-Q
actual = every cited kind quarterly_section; guidance_source_unclassified = any other kind or a mix; record_persistence; other_drivers;
not_departed; the company's segment is seeds_disagree when its two seeds' differ), the comparators last, the old anchor neutral and
the record median (each d against the model, read from the seed's own menus; for the margin the old anchor neutral IS the record median),
and growth measured on the first-filed FY2024 revenue.
"""
import argparse
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(HERE), str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import realised  # noqa: E402
from qwen_c import sec_store  # noqa: E402
from qwen_c.value import facts, menu  # noqa: E402

SCORE_VERSION = "j2.score.v1"
PREREG = "m3o.value_addendum.v1.0"
PREREG_FILE = "PREREG_m3o_value_addendum.json"
POOL_SHA256 = "d966575262e8d946cfb1f3a93b82a02187a9bf1d808afa948744a8908ce50e22"      # PREREG archival_test.pool
SEEDS = (1000, 3000)
KEYS = ("rev_growth.y1", "op_margin.y1")
TIE = 1e-12
ALPHA = 0.05
MIN_N = 20
WINSOR = (5, 95)
BOOT_N, BOOT_SEED, BOOT_Q = 2000, 20261104, 90
SCORED = ("ok", "ok_with_reverts")
KNOWN = SCORED + ("no_call", "reply_invalid", "malformed")
OUTLOOK_KINDS = ("release", "other_8k")
ACTUAL_KINDS = ("quarterly_section",)
SEGMENTS = ("guidance_outlook", "guidance_10q_actual", "guidance_source_unclassified", "record_persistence", "other_drivers",
            "seeds_disagree")
PINNED_STAMP = "coe_archival_pinned"
POWER = ("Exact one-sided 5% sign-test power at win rates 60% / 65%: n 20: 12.6% / 24.5%; n 30: 29% / 51%; n 40: 32% / 57%. "
         "A fail is weak evidence. (PREREG archival_test.power)")
DIR = book_paths.books() / "m3o" / "value" / "archival_2025-12-31"


class Stop(SystemExit):
    """The scorer refuses: an incomplete run, a changed input or a disagreement the rulings say to stop on."""

    def __init__(self, msg):
        super().__init__(f"STOP: {msg}")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ statistics
def sign_p(k, n):
    """One-sided exact sign test: P(Bin(n, 1/2) >= k). None when n == 0."""
    if n == 0:
        return None
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def describe(ds):
    """{n, ties, n_nontie, k_negative, median, share_negative, sign_p} of a list of d."""
    nt = [x for x in ds if abs(x) > TIE]
    k = sum(x < 0 for x in nt)
    return {"n": len(ds), "ties": len(ds) - len(nt), "n_nontie": len(nt), "k_negative": k,
            "median": statistics.median(ds) if ds else None, "share_negative": (sum(x < 0 for x in ds) / len(ds)) if ds else None,
            "sign_p": sign_p(k, len(nt))}


def winsorised_mean(ds):
    a = np.asarray(ds, dtype=float)
    lo, hi = np.percentile(a, WINSOR)
    return float(np.clip(a, lo, hi).mean())


def bootstrap_q90(ds):
    a = np.asarray(ds, dtype=float)
    rng = np.random.default_rng(BOOT_SEED)
    meds = np.median(a[rng.integers(0, len(a), size=(BOOT_N, len(a)))], axis=1)
    return float(np.percentile(meds, BOOT_Q))


def judge(ds):
    out = describe(ds)
    out.update(winsorised_mean=winsorised_mean(ds) if ds else None, bootstrap_median_q90=bootstrap_q90(ds) if ds else None)
    if out["n"] < MIN_N:
        out["verdict"] = "NOT_DECIDED"
    else:
        out["verdict"] = "PASS" if (out["sign_p"] is not None and out["sign_p"] < ALPHA and out["winsorised_mean"] <= 0) else "FAIL"
    return out


# ------------------------------------------------------------------ inputs
def refusal_code(text):
    """The refusal's own code: the last non-empty line's leading `code:` (e.g. held_out, or an exception's dotted class name)."""
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    m = re.match(r"([A-Za-z_][\w.]*):", lines[-1]) if lines else None
    return m.group(1) if m else "unparsed"


def ytd_value(base, key):
    """The year-to-date value of a key as the menu reads it (menu.menus: growth when not None; margin only inside (-1, 1))."""
    y = (base or {}).get("ytd") or {}
    return y.get("rev_growth") if key == "rev_growth.y1" else menu._ok(y.get("op_margin"))


def read_results(t, pk, slots, head):
    """{seed: result} of a packeted name, each checked against its slot (sha256, status, ticker, seed, packet, commit, pinned stamp)."""
    out = {}
    for seed in SEEDS:
        s = slots.get(f"{t}:{seed}")
        if s is None:
            raise Stop(f"incomplete run: {t} has a packet and no slot for seed {seed}")
        raw = Path(s["result"]).read_bytes()
        if sha(raw) != s["result_sha256"]:
            raise Stop(f"{t}:{seed} result.json does not hash to its slot's sha256")
        r = json.loads(raw.decode("utf-8"))
        if (r.get("ticker"), r.get("seed"), r.get("packet_sha256"), r.get("status")) != (t, seed, pk["packet_sha256"], s["status"]):
            raise Stop(f"{t}:{seed} result.json is not its slot's (ticker, seed, packet or status)")
        if r["status"] not in KNOWN:
            raise Stop(f"{t}:{seed} status {r['status']!r} is not one the scorer knows")
        want = s.get("git") or head                                            # a slot before a --continue-from fix: the first commit
        if want is not None and ((r.get("versions") or {}).get("git") or [None])[0] != want:
            raise Stop(f"{t}:{seed} was valued at another commit than slots.json records")
        if r.get("base") is not None and PINNED_STAMP not in ((r.get("coe") or {}).get("stamps") or []):
            raise Stop(f"{t}:{seed} has a cost of equity without the {PINNED_STAMP} stamp")
        if r.get("checks") is not None and r["checks"].get("route") != "operating":
            raise Stop(f"{t}:{seed} is not on the operating route")
        out[seed] = r
    return out


def scored(r):
    """(scored, why not)."""
    st = r["status"]
    nums = (r.get("checks") or {}).get("numbers")
    if st in SCORED:
        if not nums:
            raise Stop(f"{r['ticker']}:{r['seed']} is {st} without checks.numbers")
        return True, None
    if st == "no_call":
        return (True, None) if nums else (False, "no_call_without_numbers")
    return False, st


def cross_check(t, n, res):
    """Ruling 1: the pool's run_rate flag against every stored base.ytd and checks.neutral; the ytd identical across seeds."""
    for key in KEYS:
        flag = bool(n["run_rate"][key])
        vals = []
        for seed, r in res.items():
            if r.get("base") is None:
                continue
            v = ytd_value(r["base"], key)
            if (v is not None) != flag:
                raise Stop(f"{t}:{seed} {key}: pool run_rate {flag}, the stored base.ytd {'measures' if v is not None else 'does not measure'} it")
            neu = ((r.get("checks") or {}).get("neutral") or {}).get(key)
            if flag and (r.get("checks") or {}).get("neutral") is not None and neu != v:
                raise Stop(f"{t}:{seed} {key}: checks.neutral {neu} is not the ytd value {v}")
            vals.append(v)
        if len(set(vals)) > 1:
            raise Stop(f"{t} {key}: the ytd value differs across seeds {vals}")


def realised_of(n, store):
    """realised.realised on the exact documents the pool recorded."""
    docs = {}
    for name, url in (("companyfacts", facts.companyfacts_url(n["cik"])), ("submissions", facts.submissions_url(n["cik"]))):
        docs[name] = json.loads(sec_store.get_pinned(url, n["sec_documents"][name]["sha256"], root=store).decode("utf-8"))
    return realised.realised(docs["companyfacts"], docs["submissions"], n["fy0"])


# ------------------------------------------------------------------ per seed: departure, segment, comparators
def departs(r, key):
    ck = r["checks"]
    return menu.departed(key, ck["numbers"], ck["neutral"], {"route": "operating"})


def segment(r, key):
    """(segment, driver) of one seed's key."""
    if not departs(r, key):
        return "not_departed", None
    ck = r["checks"]
    opt = ck["options"][key]
    entry = next((d for d in ck.get("departures") or [] if d.get("input") == key), None)
    driver = entry.get("driver") if entry else None
    if opt == "guidance" or driver == "guidance":
        ids = [r["inputs"]["guidance"][key]["evidence"]] if opt == "guidance" else [i for i in entry["evidence"] if i != "V0"]
        kinds = {ck["evidence"][i]["kind"] for i in ids}
        if kinds and kinds <= set(OUTLOOK_KINDS):
            return "guidance_outlook", driver
        if kinds and kinds <= set(ACTUAL_KINDS):
            return "guidance_10q_actual", driver
        return "guidance_source_unclassified", driver
    if driver == "record_persistence":
        return "record_persistence", driver
    return "other_drivers", driver


def comparators(r, key):
    """{last, old_anchor_neutral, record_median}: the seed's own menu numbers (menu.menus on its stored base, bar and cost of equity)."""
    m = menu.menus(r["base"], r["bar"], r["cost_of_equity"], "operating")
    line, med = ("growth", "record_median") if key == "rev_growth.y1" else ("margin", "median")
    return {"last": m[line]["last"], "old_anchor_neutral": m[line][menu.NEUTRAL["operating"][key]], "record_median": m[line][med]}


# ------------------------------------------------------------------ the score
def score(d, pool_sha256=POOL_SHA256):
    d = Path(d)
    if (d / "score.json").exists():
        raise Stop(f"{d / 'score.json'} exists; a score is never overwritten")
    pool_b = (d / "pool.json").read_bytes()
    if sha(pool_b) != pool_sha256:
        raise Stop(f"pool.json sha256 {sha(pool_b)} is not the registered {pool_sha256}")
    pool, runs_b, slots_b = json.loads(pool_b), (d / "runs.json").read_bytes(), (d / "slots.json").read_bytes()
    runs, sl = json.loads(runs_b), json.loads(slots_b)
    if runs.get("pool_sha256") != pool_sha256:
        raise Stop("runs.json was begun on another pool.json")
    packets, slots = runs["packets"], sl["slots"]
    head = sl["git_changes"][0]["from"] if sl.get("git_changes") else sl.get("git")      # the commit of the slots without their own
    store = Path(pool["store"])
    missing = [n["ticker"] for n in pool["pool"] if n["ticker"] not in packets]
    if missing:
        raise Stop(f"incomplete run: {len(missing)} pool names have no packet entry")
    for n in pool["pool"]:                                                    # every slot present before any is read
        if packets[n["ticker"]].get("packet"):
            for seed in SEEDS:
                if f"{n['ticker']}:{seed}" not in slots:
                    raise Stop(f"incomplete run: {n['ticker']} has a packet and no slot for seed {seed}")

    excluded, rows, anchor_dep = {k: [] for k in KEYS}, {k: [] for k in KEYS}, {k: Counter() for k in KEYS}
    for n in sorted(pool["pool"], key=lambda x: x["ticker"]):
        t, pk = n["ticker"], packets[n["ticker"]]
        res = read_results(t, pk, slots, head) if pk.get("packet") else {}
        cross_check(t, n, res)
        sc = {s: scored(r) for s, r in res.items()}
        real = None
        for key in KEYS:
            def out(reason, detail=None):
                excluded[key].append({"ticker": t, "reason": reason, "detail": detail})
            if not n["run_rate"][key]:
                if res and all(ok for ok, _ in sc.values()):
                    anchor_dep[key]["departed" if any(departs(r, key) for r in res.values()) else "not_departed"] += 1
                out("neutral_not_run_rate")
                continue
            if not pk.get("packet"):
                out(f"packet_refused:{refusal_code(pk.get('refused'))}", str(pk.get("refused"))[-300:])
                continue
            bad = sorted({why for ok, why in sc.values() if not ok})
            if bad:
                n_ok = sum(ok for ok, _ in sc.values())
                out(f"seed_{'one' if n_ok == 1 else 'none'}_scored:{'+'.join(bad)}",
                    {str(s): res[s].get("reason") for s in SEEDS})
                continue
            if not any(departs(r, key) for r in res.values()):
                out("not_departed")
                continue
            real = real if real is not None else realised_of(n, store)
            rv = real["growth_same"] if key == "rev_growth.y1" else real["margin"]
            if rv is None:
                why = real["status"] if (key == "rev_growth.y1" or real["margin_absent"] is None) else "margin_absent"
                out(f"realised_unavailable:{why}", real["margin_absent"] if why == "margin_absent" else None)
                continue
            nums = [res[s]["checks"]["numbers"][key] for s in SEEDS]
            model, rr = sum(nums) / 2, ytd_value(res[SEEDS[0]]["base"], key)
            segs = {s: segment(res[s], key) for s in SEEDS}
            seg = segs[SEEDS[0]][0] if len({v[0] for v in segs.values()}) == 1 else "seeds_disagree"
            cps = [comparators(res[s], key) for s in SEEDS]
            comp = {c: (cps[0][c] if cps[0][c] == cps[1][c] else "seeds_disagree") for c in cps[0]}
            row = {"ticker": t, "model_by_seed": dict(zip(map(str, SEEDS), nums)), "model": model, "run_rate": rr, "realised": rv,
                   "d": abs(model - rv) - abs(rr - rv), "segment": seg,
                   "segment_by_seed": {str(s): v[0] for s, v in segs.items()}, "driver_by_seed": {str(s): v[1] for s, v in segs.items()},
                   "status_by_seed": {str(s): res[s]["status"] for s in SEEDS}, "comparators": comp,
                   "realised_detail": {k: real.get(k) for k in ("status", "year1", "revenue", "scope", "margin_absent", "restated_base",
                                                                   "base_move", "growth_gap_points")}}
            if key == "rev_growth.y1":
                gf = real.get("growth_first")
                row.update(realised_first_filed=gf, d_first_filed=None if gf is None else abs(model - gf) - abs(rr - gf))
            rows[key].append(row)
    return report(pool, pool_b, runs_b, slots_b, head, rows, excluded, anchor_dep, d)


def report(pool, pool_b, runs_b, slots_b, head, rows, excluded, anchor_dep, d):
    keys = {}
    for key in KEYS:
        rs, ds = rows[key], [r["d"] for r in rows[key]]
        seg = {s: describe([r["d"] for r in rs if r["segment"] == s]) for s in SEGMENTS}
        drivers = Counter(f"{s}:{v}" for r in rs for s, v in r["driver_by_seed"].items())
        comp = {}
        for c in ("last", "old_anchor_neutral", "record_median"):
            have = [r for r in rs if isinstance(r["comparators"][c], (int, float))]
            comp[c] = dict(describe([abs(r["model"] - r["realised"]) - abs(r["comparators"][c] - r["realised"]) for r in have]),
                           unavailable=sum(r["comparators"][c] is None for r in rs),
                           seeds_disagree=sum(r["comparators"][c] == "seeds_disagree" for r in rs))
        if key == "op_margin.y1":
            comp["note"] = "for the margin the old anchor neutral is the record median (menu.NEUTRAL op_margin.y1 = median): identical rows"
        order = Counter(e["reason"] for e in excluded[key])
        keys[key] = {"judged": judge(ds), "exclusions": dict(order),
                     "exclusions_by_stage": dict(Counter(e["reason"].split(":")[0] for e in excluded[key])),
                     "segments": seg, "drivers_by_seed": dict(drivers), "comparators_reported_not_judged": comp,
                     "neutral_not_run_rate_departures_reported": dict(anchor_dep[key]),
                     "rows": rs, "excluded": excluded[key]}
        if key == "rev_growth.y1":
            keys[key]["first_filed_reported_not_judged"] = describe([r["d_first_filed"] for r in rs if r["d_first_filed"] is not None])
    pr = book_paths.prereg(PREREG_FILE)
    doc = {"version": SCORE_VERSION, "prereg": PREREG, "prereg_sha256": sha(pr.read_bytes()) if pr.is_file() else None,
           "spec": "J2_SPEC_forecast_test_v02.md sections 4-7; coordinator rulings 2026-11-04", "T": pool.get("T"),
           "inputs": {"pool_sha256": sha(pool_b), "runs_sha256": sha(runs_b), "slots_sha256": sha(slots_b), "valuation_commit": head,
                      "pool_names": len(pool["pool"])},
           "code": {"commit": _git("rev-parse", "HEAD"), "tracked_tree_clean": not _git("status", "--porcelain", "--untracked-files=no"),
                    "realised": realised.REALISED_VERSION, "menu": menu.MENU_VERSION},
           "rules": {"keys": KEYS, "seeds": SEEDS, "tolerance": menu.TOL, "tie": TIE, "alpha_one_sided": ALPHA, "minimum_n": MIN_N,
                     "winsor_percentiles": WINSOR, "bootstrap": {"resamples": BOOT_N, "seed": BOOT_SEED, "percentile": BOOT_Q,
                                                                 "unit": "company", "reported_only": True},
                     "verdict": "NOT_DECIDED if n < 20; PASS iff sign_p < 0.05 and winsorised_mean <= 0; else FAIL",
                     "power": POWER},
           "keys": keys}
    md = render_md(doc)
    tmp = d / "score.md.tmp"
    tmp.write_text(md, encoding="utf-8")
    os.replace(tmp, d / "score.md")
    with open(d / "score.json", "x", encoding="utf-8") as fh:                  # never overwritten
        fh.write(json.dumps(doc, indent=1, sort_keys=True, default=str))
    return doc


def _git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def _f(x, p=4):
    return "-" if x is None else (f"{x:.{p}f}" if isinstance(x, float) else str(x))


def render_md(doc):
    L = [f"# Archival year-1 forecast test: score ({doc['version']})", "",
         f"PREREG {doc['prereg']} (archival_test), T {doc['T']}. Pool sha256 {doc['inputs']['pool_sha256']}, {doc['inputs']['pool_names']} "
         f"names; valuations at commit {doc['inputs']['valuation_commit']}; scorer at {doc['code']['commit']}.", "",
         "d = |model - realised| - |run rate - realised|, model = the two-seed mean; d < 0 means the model was closer.", "",
         "| Key | Verdict | n | ties | d < 0 | median d | sign p (one-sided) | winsorised mean d | bootstrap q90 of median (reported) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for key, k in doc["keys"].items():
        j = k["judged"]
        L.append(f"| {key} | **{j['verdict']}** | {j['n']} | {j['ties']} | {j['k_negative']} of {j['n_nontie']} | {_f(j['median'])} | "
                 f"{_f(j['sign_p'])} | {_f(j['winsorised_mean'])} | {_f(j['bootstrap_median_q90'])} |")
    L += ["", f"Rule: {doc['rules']['verdict']}. {doc['rules']['power']}", ""]
    for key, k in doc["keys"].items():
        L += [f"## {key}", "", "Exclusions, in the order applied (company-keys):", ""]
        L += [f"- {r}: {c}" for r, c in sorted(k["exclusions"].items())] or ["- none"]
        L += ["", "Segments (reported, never judged):", "", "| Segment | n | d < 0 | median d |", "|---|---|---|---|"]
        L += [f"| {s} | {v['n']} | {v['k_negative']} of {v['n_nontie']} | {_f(v['median'])} |" for s, v in k["segments"].items()]
        L += ["", "Comparators (d of the model against each; reported, never judged):", "", "| Comparator | n | d < 0 | median d | unavailable |",
              "|---|---|---|---|---|"]
        L += [f"| {c} | {v['n']} | {v['k_negative']} of {v['n_nontie']} | {_f(v['median'])} | {v['unavailable']} |"
              for c, v in k["comparators_reported_not_judged"].items() if isinstance(v, dict)]
        if "note" in k["comparators_reported_not_judged"]:
            L += ["", k["comparators_reported_not_judged"]["note"] + "."]
        if "first_filed_reported_not_judged" in k:
            v = k["first_filed_reported_not_judged"]
            L += ["", f"Growth on the first-filed FY2024 revenue (reported, never judged): n {v['n']}, d < 0 {v['k_negative']} of "
                      f"{v['n_nontie']}, median d {_f(v['median'])}, sign p {_f(v['sign_p'])}."]
        L += ["", f"Keys whose neutral is not the run rate, departures (reported, never judged): {k['neutral_not_run_rate_departures_reported'] or 'none'}.", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(DIR))
    ap.add_argument("--pool-sha256", default=POOL_SHA256, help="the registered pool hash (PREREG amendment 2 for the non-December holdout)")
    a = ap.parse_args(argv)
    doc = score(a.dir, a.pool_sha256)
    for key, k in doc["keys"].items():
        j = k["judged"]
        print(key, j["verdict"], "n", j["n"], "p", _f(j["sign_p"]), "wmean", _f(j["winsorised_mean"]), "median", _f(j["median"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

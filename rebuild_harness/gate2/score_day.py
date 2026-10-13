"""score_day.py - gate 2's scoring day as one procedure (remaining-work plan A0, Addendum AK): preconditions, outcomes, baselines, the registered bars,
the reported diagnostics, the coordinator's independent recomputation and Audit 1, ending in one report, negatives first.

    python -m rebuild_harness.gate2.score_day check     --state-dir RUN2 [--repeat-state REP]            preconditions only; reads no outcome
    python -m rebuild_harness.gate2.score_day refresh   --state-dir RUN2                                 new companyfacts snapshot + outcome store (no model loaded)
    python -m rebuild_harness.gate2.score_day score     --state-dir RUN2 (--repeat-state REP | --repeat-later) --store NEW_STORE [--scoring-date D]
    python -m rebuild_harness.gate2.score_day r8        --state-dir RUN2 --repeat-state REP --scoring-date D   R8 after a --repeat-later score
    python -m rebuild_harness.gate2.score_day rehearse  --state-dir RUN2 --baselines FILE --out DIR       dummy outcomes; writes only into DIR

WHAT IT REFUSES.  `score` runs only when: gate2_finished.flag exists; the masked control and the repeat control are final (or, with --repeat-later, the
repeat control is deferred: operator 2026-10-13, Addendum AK.25 - R8 is a reported diagnostic, not a bar, it reads no outcome, and it runs from the frozen
worktree on hash-verified inputs, so scoring first cannot touch it; `r8` then reports it beside the score); no outcomes file exists yet for
the scoring date (outcome_extract writes once); the store passed is NOT the store the packs were built from (the outcome store must be a newer snapshot,
built by the `PitData.build_company` path from a newer companyfacts.zip); and the memory guard holds (no llama-server running, commit headroom >= 8 GB,
memory `ram-limit-during-gpu-runs`).  Each refusal names its reason.

THE SCORING DATE is the earliest of the data snapshots the outcomes read, so every outcome lies inside data on disk: the outcome store's companyfacts date,
the last daily close of SPY, and the delisting index's submissions date.  It can be given lower, never higher.

STAGES of `score` (each writes into <state>/scoring/<scoring date>/, never over an existing file):
  1 outcomes      `outcome_extract.main` (q1, q2, the fiscal-year-1 annual outcome, returns under the three bounds)
  2 baselines     `baselines.main` on the run's state (the packs' own store: quarters known at T), baselines_v2.json
  3 bars          `scoring.score` (G1-G6, the verdict, registration section 5)
  4 diagnostics   `diagnostics.run` (R3a/R3b on q1 and annual, R3c, R8)
  5 independent   scratch/rev23/gate2_audit/independent_g1.py on both targets; every shared number must agree exactly
  6 audit 1       look-ahead (every outcome filed after T), coverage by date x family x measure, included against missing, and 20 seeded outcomes listed for the
                  coordinator's hand check against the SEC filings
  7 report        report.md, negatives first; report.json with everything
`rehearse` runs stages 3-7 on DUMMY outcomes (random numbers) and an existing baselines file: it exercises the whole procedure on the real run files
without reading a single real outcome (Q3).
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Mapping, Optional

import numpy as np

from . import config

INDEPENDENT = config.WORKSPACE / "scratch" / "rev23" / "gate2_audit" / "independent_g1.py"
REPRODUCED = config.WORKSPACE / "scratch" / "rev23" / "gate2_audit" / "reproduced_refusals.json"     # Addendum AK.5: evidence-backed, each key re-verified by scoring
MIN_COMMIT_GB = 8.0


# ---- preconditions --------------------------------------------------------------------------------------------------------------------------------

def commit_headroom_gb() -> Optional[float]:
    try:
        import ctypes

        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong), ("totpf", ctypes.c_ulonglong),
                        ("availpf", ctypes.c_ulonglong), ("totv", ctypes.c_ulonglong), ("availv", ctypes.c_ulonglong), ("x", ctypes.c_ulonglong)]
        m = M()
        m.l = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.availpf / 1e9
    except Exception:
        return None


def llama_server_running() -> bool:
    try:
        import psutil
        return any((p.info.get("name") or "").lower().startswith("llama-server") for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def control_final(state_dir, mode: str) -> Optional[bool]:
    """True when every job of the control is final in its state folder; None when the folder is not given."""
    if state_dir is None:
        return None
    from . import sample as sample_mod
    from .runner import Gate2Runner, all_final
    try:
        smp = sample_mod.load_verified(sample_mod.sample_path(state_dir))
    except sample_mod.SampleError:
        return False                                                   # no verified sample: never treated as final
    jobs = sample_mod.masked_control(smp) if mode == "masked" else sample_mod.repeat_control(smp)
    r = Gate2Runner(state_dir=state_dir, sample=smp, env=None, server=None, probe=None, client=None)
    return all_final(r, jobs, masked=(mode == "masked"))


def index_snapshot_date(log: Path) -> Optional[str]:
    """The SEC Last-Modified date of the submissions.zip the delisting index was built from (the download log's last 'HEAD ok ... lm=' line)."""
    from email.utils import parsedate_to_datetime
    try:
        lines = [x for x in Path(log).read_text(encoding="utf-8").splitlines() if "HEAD ok" in x and "lm=" in x]
        return parsedate_to_datetime(lines[-1].split("lm=", 1)[1].strip()).date().isoformat() if lines else None
    except (OSError, ValueError, IndexError):
        return None


def scoring_date_from(store_date: str, spy_last: str, index_date: str, given: Optional[str] = None) -> str:
    d = min(store_date, spy_last, index_date)
    if given is not None:
        if given > d:
            raise ValueError(f"scoring date {given} is after the data on disk ({d}: store {store_date}, prices {spy_last}, delisting index {index_date})")
        d = given
    return d


def preconditions(state_dir, repeat_state=None, store=None, packs_store=None, memory: bool = True, repeat_later: bool = False) -> Dict[str, object]:
    paths = config.state_paths(state_dir)
    out = {"finished_flag": paths["finished"].exists(), "masked_control_final": control_final(state_dir, "masked"),
           "repeat_control_final": control_final(repeat_state, "repeat"), "repeat_deferred": bool(repeat_later)}
    if store is not None:
        out["outcome_store_is_new"] = Path(store).resolve() != Path(packs_store).resolve() if packs_store else None
    if memory:
        out["llama_server_running"] = llama_server_running()
        out["commit_headroom_gb"] = commit_headroom_gb()
    refusals = []
    if not out["finished_flag"]:
        refusals.append("gate2_finished.flag is missing: the replay is not finished")
    if out["masked_control_final"] is not True:
        refusals.append("the masked control (G6) is not final")
    if out["repeat_control_final"] is not True and not repeat_later:
        refusals.append("the repeat control (R8) is not final or its state folder was not given")
    if store is not None and out.get("outcome_store_is_new") is False:
        refusals.append("the outcome store is the packs' store (an August snapshot): outcomes need a newer companyfacts snapshot")
    if memory and out["llama_server_running"]:
        refusals.append("a llama-server is running: the CPU-heavy stages wait until no model is loaded")
    if memory and (out["commit_headroom_gb"] or 0) < MIN_COMMIT_GB:
        refusals.append(f"commit headroom {out['commit_headroom_gb']} GB < {MIN_COMMIT_GB} GB")
    out["refusals"] = refusals
    return out


# ---- refresh: a newer companyfacts snapshot and the outcome store built from it ---------------------------------------------------------------------

COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SEC_UA = {"User-Agent": "RS2-Local research riperdy@gmail.com"}      # the workspace's declared SEC identity (rs2-local sec_guidance.UA), SEC fair access


def _build_chunk(args):
    store, zip_path, ciks = args
    from valuation.pit_data import PitData
    pit = PitData(store, zip_path=zip_path)
    return sum(1 for c in ciks if pit.build_company(c))


def refresh(sec_bulk: Path, store_root: Path, workers: int = 4, opener=None) -> dict:
    """Download companyfacts.zip into a NEW folder sec_bulk/companyfacts_<SEC Last-Modified date>/ (sha256 recorded; standing approval, memory
    `sec-downloads-standing-approval`) and build store_root/store_<date>/ from it by `PitData.build_company`, the path the packs' store was built by.
    Nothing existing is overwritten: an existing snapshot folder or store is refused."""
    import hashlib
    import urllib.request
    import zipfile
    from email.utils import parsedate_to_datetime
    from multiprocessing import Pool
    op = opener or urllib.request.urlopen
    head = op(urllib.request.Request(COMPANYFACTS_URL, headers=SEC_UA, method="HEAD"))
    d = parsedate_to_datetime(head.headers["Last-Modified"]).date().isoformat()
    folder, store = Path(sec_bulk) / f"companyfacts_{d}", Path(store_root) / f"store_{d}"
    if folder.exists() or store.exists():
        raise FileExistsError(f"{folder} or {store} exists: a snapshot is written once")
    folder.mkdir(parents=True)
    zp, part, h = folder / "companyfacts.zip", folder / "companyfacts.zip.part", hashlib.sha256()
    with op(urllib.request.Request(COMPANYFACTS_URL, headers=SEC_UA)) as r, open(part, "xb") as fh:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            fh.write(b)
            h.update(b)
    part.rename(zp)
    meta = {"url": COMPANYFACTS_URL, "last_modified": head.headers["Last-Modified"], "snapshot_date": d, "bytes": zp.stat().st_size, "sha256": h.hexdigest(),
            "why": "gate-2 scoring: outcomes filed after the packs' August snapshot (plan A0)"}
    (folder / "companyfacts.zip.sha256.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    ciks = [n.filename[3:13] for n in zipfile.ZipFile(zp).infolist() if n.filename.endswith(".json")]
    with Pool(workers) as p:
        built = sum(p.map(_build_chunk, [(store, zp, ciks[i::workers * 4]) for i in range(workers * 4)]))
    meta.update(store=str(store), members=len(ciks), built=built)
    store.parent.mkdir(parents=True, exist_ok=True)
    (store.parent / f"store_{d}.manifest.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


# ---- audit 1 --------------------------------------------------------------------------------------------------------------------------------------

MEASURES = (("growth", "operating", ("revenue_growth", "revenue_growth")), ("margin", "operating", ("operating_margin_change", "operating_margin_change")),
            ("rote", "financial", ("rote_change_annualised_on_tbv_at_T", "rote_change")))


def audit1(outcomes: Mapping[str, dict], rows: List[Mapping], seed: int = 20261013, n_hand: int = 20) -> dict:
    """Look-ahead, coverage and the hand-check list over the scored rows' outcomes (registration section 3; plan A3)."""
    look = []
    cover = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        o = outcomes.get(r["key"]) or {}
        q1 = (o.get("quarters") or {}).get("q1") or {}
        an = o.get("annual") or {}
        if q1 and str(q1.get("filed", ""))[:10] <= r["date"]:
            look.append({"key": r["key"], "what": "q1 filed on or before T", "filed": q1.get("filed")})
        if an.get("status") == "ok" and str(an.get("year1_filed", ""))[:10] <= r["date"]:
            look.append({"key": r["key"], "what": "year-1 annual report filed on or before T", "filed": an.get("year1_filed")})
        for m, fam, (qf, af) in MEASURES:
            if r["family"] != fam:
                continue
            c = cover[(r["date"], fam, m)]
            c["rows"] += 1
            c["q1"] += q1.get(qf) is not None
            c["annual"] += an.get("status") == "ok" and an.get(af) is not None
            if an.get("status") not in (None, "ok"):
                c["annual_" + str(an.get("status"))] += 1
    rng = random.Random(seed)
    with_q1 = sorted(r["key"] for r in rows if ((outcomes.get(r["key"]) or {}).get("quarters") or {}).get("q1"))
    hand = []
    for k in rng.sample(with_q1, min(n_hand, len(with_q1))):
        o = outcomes[k]
        q1 = o["quarters"]["q1"]
        hand.append({"key": k, "ticker": o.get("ticker"), "cik": o.get("cik"), "q1_period_end": q1.get("period_end"), "q1_filed": q1.get("filed"),
                     "accession": q1.get("accession"), "revenue_growth": q1.get("revenue_growth"), "operating_margin_change": q1.get("operating_margin_change"),
                     "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={o.get('cik')}&type=10-Q&dateb=&owner=include&count=40"})
    return {"look_ahead_violations": look, "coverage": {f"{d}|{f}|{m}": dict(c) for (d, f, m), c in sorted(cover.items())}, "hand_check": hand,
            "rule": "every outcome first filed after T; coverage counted, never imputed; 20 seeded outcomes for the coordinator's check against the filings"}


def missing_vs_included(rows: List[Mapping], outcomes: Mapping[str, dict]) -> dict:
    """Included against missing (annual target), compared on what the run files hold: family, date and the base-year margin level."""
    grp = {"included": collections.defaultdict(list), "missing": collections.defaultdict(list)}
    for r in rows:
        an = (outcomes.get(r["key"]) or {}).get("annual") or {}
        g = "included" if an.get("status") == "ok" else "missing"
        grp[g]["family:" + r["family"]].append(1)
        grp[g]["date:" + r["date"]].append(1)
        mb = (r.get("code") or {}).get("margin_base")
        if mb is not None:
            grp[g]["base_margin_or_rote"].append(mb)
    out = {}
    for g, d in grp.items():
        out[g] = {k: (len(v) if k != "base_margin_or_rote" else {"n": len(v), "median": float(np.median(v)) if v else None}) for k, v in sorted(d.items())}
    return out


# ---- independent agreement ------------------------------------------------------------------------------------------------------------------------

def independent_agreement(state_dir, outcomes_path, baselines_path, rep: Mapping, diag: Mapping) -> dict:
    res, mism = {}, []
    for target, k3a in (("q1", "R3a"), ("annual", "R3a_annual")):
        ind = json.loads(subprocess.run([sys.executable, str(INDEPENDENT), str(state_dir), str(outcomes_path), str(baselines_path), target],
                                        capture_output=True, text=True, check=True).stdout)
        res[target] = ind
        for m in ("growth", "margin"):
            pairs = [(f"{k3a}.{m}.{b}", diag[k3a][m][b], ind.get(f"pass1_vs_{b}_{m}")) for b in ("code", "persistence", "pop_median", "t4q", "persist_rr", "popmed_rr")]
            pairs.append((f"{k3a}.final_vs_pass1.{m}", diag["R3b" if target == "q1" else "R3b_annual"][m], ind.get(f"final_vs_pass1_{m}")))
            if target == "q1":
                pairs.append((f"G1.{m}_q1", rep["G1"][f"{m}_q1"], ind.get(f"final_vs_code_{m}")))
            for name, a, b in pairs:
                if b is None:
                    continue
                if a["n"] != b["n"] or (a["n"] and abs((a.get("median_d") or 0) - (b.get("median_d") or 0)) > 1e-12):
                    mism.append({"what": name, "scoring": (a["n"], a.get("median_d")), "independent": (b["n"], b.get("median_d"))})
    return {"mismatches": mism, "independent": res}


# ---- the report -----------------------------------------------------------------------------------------------------------------------------------

def negatives(rep: Mapping, diag: Mapping, agree: Mapping, aud: Mapping) -> List[str]:
    neg = []
    v = rep["verdict"]
    if v["verdict"] != "PASS":
        neg.append(f"Gate 2 verdict {v['verdict']} (failed: {v['failed']}; undecided: {v['undecided']})")
    if agree["mismatches"]:
        neg.append(f"INDEPENDENT RECOMPUTATION DISAGREES on {len(agree['mismatches'])} numbers: nothing below is reported until resolved")
    if aud["look_ahead_violations"]:
        neg.append(f"LOOK-AHEAD: {len(aud['look_ahead_violations'])} outcomes filed on or before T")
    if not rep["G5"]["passes"]:
        neg.append(f"G5 integrity fails: {json.dumps({k: rep['G5'][k] for k in ('leakage_violations', 'citations_failed', 'runs_with_unrecorded_fallback')})}")
    for m in ("growth", "margin"):
        if diag["R3a"][m].get("filing_skill") is not True:
            neg.append(f"R3a {m}: filing skill not shown (C1 arms: code, persist_rr, popmed_rr) -> {diag['R3a'][m].get('filing_skill')}")
    if diag["R3c"].get("passes") is False:
        neg.append(f"G4-strict fails: {diag['R3c']['n_toward_without_new_filing_quote']}/{diag['R3c']['n_proposed']}")
    return neg


def render(rep, diag, agree, aud, mvi, meta) -> str:
    from . import scoring
    neg = negatives(rep, diag, agree, aud)
    L = [f"# Gate 2 scoring day — {meta['mode']} — scoring date {meta['scoring_date']}", "", "## Negatives first", ""]
    L += [f"- {x}" for x in neg] or ["- none"]
    L += ["", "## Registered bars", "", scoring.render_markdown(rep), "", "## Diagnostics (reported, AD R3/R8, AH)", ""]
    for k in ("R3a", "R3a_annual"):
        for m in ("growth", "margin"):
            L.append(f"- {k} {m}: " + "; ".join(f"{b} n={diag[k][m][b]['n']} med={diag[k][m][b]['median_d']}" for b in ("code", "persist_rr", "popmed_rr", "persistence", "pop_median", "t4q"))
                     + f"; filing_skill={diag[k][m]['filing_skill']}")
    L.append(f"- R3b (final vs pass 1): " + "; ".join(f"{m} n={diag['R3b'][m]['n']} med={diag['R3b'][m]['median_d']}" for m in ("growth", "margin"))
             + f"; red team revised nothing: {diag['R3b']['red_team_revised_nothing']}")
    L.append(f"- R3c: {json.dumps(diag['R3c'])}")
    if "R8" in diag:
        L.append(f"- R8: {json.dumps(diag['R8'])}")
    elif str(meta.get("repeat_control", "")).startswith("deferred"):
        L.append("- R8: deferred (AK.25): the repeat control runs after scoring; `score_day r8` writes r8.json beside this report")
    L += ["", "## Independent recomputation", "", f"- mismatches: {len(agree['mismatches'])}"] + [f"  - {m}" for m in agree["mismatches"][:20]]
    L += ["", "## Audit 1", "", f"- look-ahead violations: {len(aud['look_ahead_violations'])}", "- coverage (date|family|measure: rows, q1, annual, ...):"]
    L += [f"  - {k}: {v}" for k, v in aud["coverage"].items()]
    L += [f"- included vs missing (annual): {json.dumps(mvi)}", f"- hand-check list: {len(aud['hand_check'])} outcomes in report.json (audit1.hand_check)"]
    return "\n".join(L)


def run_stages(state_dir, outcomes_path, baselines_path, repeat_state, out_dir: Path, meta: Mapping, draws: int = config.BOOT_DRAWS) -> dict:
    from . import diagnostics, scoring
    reproduced = json.loads(REPRODUCED.read_text(encoding="utf-8")) if REPRODUCED.exists() else None
    rep = scoring.score(state_dir, outcomes_path, draws=draws, reproduced=reproduced)
    diag = diagnostics.run(state_dir, outcomes_path, baselines_path, repeat_state, draws=draws)
    agree = independent_agreement(state_dir, outcomes_path, baselines_path, rep, diag)
    rows, _s, _e = scoring.load_rows(state_dir)
    outs = scoring.load_outcomes(outcomes_path)
    aud = audit1(outs, rows)
    mvi = missing_vs_included(rows, outs)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "report.json", "x", encoding="utf-8") as fh:
        json.dump({"meta": dict(meta), "bars": rep, "diagnostics": diag, "independent": agree, "audit1": aud, "missing_vs_included": mvi}, fh, indent=1, default=str)
    md = render(rep, diag, agree, aud, mvi, meta)
    with open(out_dir / "report.md", "x", encoding="utf-8") as fh:
        fh.write(md)
    return {"report": str(out_dir / "report.md"), "negatives": negatives(rep, diag, agree, aud), "mismatches": len(agree["mismatches"])}


def dummy_outcomes(state_dir, path: Path, seed: int = 7) -> Path:
    """Random outcomes for every scored row (rehearsal only; no real outcome is read)."""
    from . import scoring
    rows, _s, _e = scoring.load_rows(state_dir)
    rng = np.random.default_rng(seed)
    with open(path, "x", encoding="utf-8") as fh:
        for r in rows:
            d = date.fromisoformat(r["date"])
            q = {"period_end": r["date"], "filed": (d + timedelta(days=45)).isoformat(), "accession": "DUMMY",
                 "revenue_growth": float(rng.normal(.05, .1)), "operating_margin_change": float(rng.normal(0, .02)), "rote_change_annualised_on_tbv_at_T": float(rng.normal(0, .02))}
            an = {"status": "ok" if rng.random() < .6 else "year1_not_filed_by_scoring_date", "year1_filed": f"{d.year + 1}-03-01",
                  "revenue_growth": float(rng.normal(.05, .1)), "operating_margin_change": float(rng.normal(0, .02)), "rote_change": float(rng.normal(0, .02))}
            fh.write(json.dumps({"key": r["key"], "cik": r["cik"], "ticker": "DUMMY", "quarters": {"q1": q, "q2": None}, "annual": an,
                                 "returns": {"3": {"status": "observed", "bounds": {b: float(rng.normal(0, .1)) for b in scoring.BOUNDS}}}}) + "\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("check", "refresh", "score", "r8", "rehearse"))
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--repeat-state", type=Path)
    ap.add_argument("--repeat-later", action="store_true", help="score: defer the repeat control (AK.25); R8 is reported later by the r8 stage")
    ap.add_argument("--store", type=Path, help="score: the NEW outcome store (a newer companyfacts snapshot)")
    ap.add_argument("--store-date", help="score: the companyfacts snapshot date of --store (YYYY-MM-DD)")
    ap.add_argument("--scoring-date")
    ap.add_argument("--baselines", type=Path, help="rehearse: an existing baselines file")
    ap.add_argument("--out", type=Path, help="rehearse: the output folder (outside the run's state)")
    ap.add_argument("--draws", type=int, default=config.BOOT_DRAWS)
    a = ap.parse_args(argv)
    g = None
    if a.stage == "check":
        print(json.dumps(preconditions(a.state_dir, a.repeat_state, memory=True), indent=1, default=str))
        return 0
    if a.stage == "refresh":
        pre = preconditions(a.state_dir, None, memory=True)
        mem = [x for x in pre["refusals"] if "llama-server" in x or "commit headroom" in x]
        if mem:
            print("REFUSED:", "; ".join(mem))
            return 5
        print(json.dumps(refresh(config.WORKSPACE / "data" / "sec_bulk", config.WORKSPACE / "data" / "pit_store"), indent=1))
        return 0
    if a.stage == "r8":
        from . import diagnostics, scoring
        if a.repeat_state is None or a.scoring_date is None:
            print("REFUSED: r8 needs --repeat-state and --scoring-date (the date of the score it reports beside)")
            return 2
        out = config.state_paths(a.state_dir)["root"] / "scoring" / a.scoring_date
        if not (out / "report.json").exists():
            print(f"REFUSED: no score at {out}: r8 reports beside an existing score")
            return 2
        if (out / "r8.json").exists():
            print(f"REFUSED: {out / 'r8.json'} exists (written once)")
            return 2
        if control_final(a.repeat_state, "repeat") is not True:
            print("REFUSED: the repeat control is not final")
            return 5
        rows, _s, _e = scoring.load_rows(a.state_dir)
        rep_rows, _s, _e = scoring.load_rows(a.repeat_state)
        res = dict(diagnostics.r8(rows, rep_rows), repeat_state=str(a.repeat_state), note="deferred R8 (AK.25); it reads no outcome")
        with open(out / "r8.json", "x", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print(json.dumps(res, indent=1))
        return 0
    if a.stage == "rehearse":
        if a.out is None or a.baselines is None:
            print("REFUSED: rehearse needs --out (outside the run's state) and --baselines")
            return 2
        if config.state_paths(a.state_dir)["root"].resolve() in a.out.resolve().parents:
            print("REFUSED: the rehearsal writes nothing into the run's state")
            return 2
        a.out.mkdir(parents=True, exist_ok=True)
        po = dummy_outcomes(a.state_dir, a.out / "dummy_outcomes.jsonl")
        res = run_stages(a.state_dir, po, a.baselines, a.repeat_state, a.out, {"mode": "REHEARSAL (dummy outcomes)", "scoring_date": "n/a"}, a.draws)
        print(json.dumps(res, indent=1))
        return 0 if res["mismatches"] == 0 else 1
    # score
    from . import env as env_mod
    g = env_mod._g1r()
    if a.repeat_later and a.repeat_state is not None:
        print("REFUSED: give --repeat-state or --repeat-later, not both")
        return 2
    pre = preconditions(a.state_dir, a.repeat_state, a.store, g.DEFAULT_STORE, memory=True, repeat_later=a.repeat_later)
    if a.store is None or a.store_date is None:
        pre["refusals"].append("score needs --store and --store-date")
    if pre["refusals"]:
        print(json.dumps(pre, indent=1, default=str))
        print("REFUSED:", "; ".join(pre["refusals"]))
        return 5
    import gzip
    spy_last = gzip.open(config.WORKSPACE / "data" / "prices_daily" / "SPY.csv.gz", "rt").read().strip().splitlines()[-1].split(",")[0]
    idx_date = index_snapshot_date(config.WORKSPACE / "data" / "sec_bulk" / "_logs" / "d1_submissions.log")
    if idx_date is None:
        print("REFUSED: the delisting index's submissions snapshot date cannot be read from its download log")
        return 5
    sd = scoring_date_from(a.store_date, spy_last, idx_date, a.scoring_date)
    out = config.state_paths(a.state_dir)["root"] / "scoring" / sd
    from . import baselines as bl_mod, outcome_extract
    rc = outcome_extract.main(["--scoring-date", sd, "--state-dir", str(a.state_dir), "--store", str(a.store),
                               "--delisting-index", str(config.WORKSPACE / "data" / "sec_bulk" / "index_P4b"),
                               "--delisting-docs", str(config.WORKSPACE / "data" / "sec_bulk" / "delisting_docs")])
    if rc != 0:
        print("REFUSED: outcome extraction failed")
        return rc
    bfile = config.state_paths(a.state_dir)["root"] / "baselines" / bl_mod.BASELINES_FILE
    if not bfile.exists() and bl_mod.main(["--state-dir", str(a.state_dir)]) != 0:
        print("REFUSED: the baselines build failed")
        return 6
    res = run_stages(a.state_dir, outcome_extract.outcomes_path(sd, a.state_dir), bfile, a.repeat_state, out,
                     {"mode": "SCORING", "scoring_date": sd, "store": str(a.store), "store_date": a.store_date, "spy_last": spy_last, "index_date": idx_date,
                      "repeat_control": "deferred: R8 follows in r8.json (AK.25)" if a.repeat_later else "final"}, a.draws)
    print(json.dumps(res, indent=1))
    return 0 if res["mismatches"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

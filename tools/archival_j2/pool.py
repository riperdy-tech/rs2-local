"""pool.py - J2-1: the census pool of the archival year-1 forecast test at T = 2025-12-31T21:00:00Z (J2 v0.2 section 7 items 3, 7, 8, 9;
PREREG addendum draft v0.2 archival_test.pool and exclusions_before_the_census).

    python tools/archival_j2/pool.py [--screener-repo DIR] [--store DIR] [--offline] [--limit N]

Writes <rs2_state_dir>/paper_books/m3o/value/archival_2025-12-31/pool.json (names and CIKs are data: they stay in the private rs2-state,
never in this public repository) and prints the counts and the file's sha256. Reads no forecast and computes no error statistic; the
realised year 1 is read only for the exclusions that need it, and no realised growth or margin of a kept name is written.

STAGES, in order; a name leaves at the first stage it fails, with its reason and detail:
 1 frame: every row of public/data/stocks.json at screener commit d327fe8 (2025-12-14), read through git from the screener repository
   (paths.py screener_publish_repo; --screener-repo when that clone does not hold the commit; the blob's git sha is recorded).
 2 cik: SEC's company_tickers.json through qwen_c.sec_store (SEC publishes no dated map; the copy's sha256 is recorded): the ticker as
   written, else with '.' as '-'. Unmapped: leaves (no_cik). Several frame tickers of one CIK make one company (the first ticker in sorted
   order); the others leave as duplicate_company. CIKs are 10-digit, zero-padded.
 3 sec_documents: companyfacts and submissions through qwen_c.sec_store under --store: the store's copy when it has one, else one online
   fetch (SEC standing approval). Each document's sha256 is recorded.
 4 family: tools/paper_books/value_family.family at T. operating and commodity (qwen_c.value.run.ROUTED: valued on the operating route)
   stay; financial leaves (J2 section 7 item 3), and so does every other family.
 5 december: the base fiscal year (facts.annual_facts' latest annual revenue year at T) ends 2024-12-24..2025-01-07, so that year 1 is
   FY2025 for every name (a December year, 52/53-week years ending near it included). Otherwise: leaves.
 6 prepare: qwen_c.value.run.prepare at T on those documents, offline, with the family above and the frame's market cap, and its
   cost-of-equity step SKIPPED (J2 section 7 item 1: the archival cost of equity awaits the operator): coe.cost_of_equity is replaced by a
   function that raises a sentinel, so every data step before it runs exactly as in a valuation; a DeskRefusal leaves with its code.
 7 run_rate: year 1's year-to-date pair as inputs.base carries it (facts `_ytd`, F11): rev_growth.y1 is measured when its growth is not
   None; op_margin.y1 when its margin passes menu._ok (inside (-1, 1)), the menu's own rule for making ytd the neutral. Recorded per key;
   neither key measured: leaves.
 8 exclusions before the census (every one is evaluated and recorded; any one excludes):
   item_202_public  same_filing.item_202_public (gate 2, ported): an 8-K with Item 2.02 accepted after year 1's end and before 16:00 ET on
                    T (year 1's end: the year-1 annual filing's report date, else fy0 + 365 days, stamped).
   release          an 8-K with Item 2.02 accepted after the run rate's 10-Q, effective at T, more than ONE NYSE session after it (sessions
                    between the two filings' effective sessions, the packet's acceptance policy and calendar).
   base_move        the year-1 growth on the FY2025 annual filing's same-filing comparative minus that on the first-filed FY2024 revenue,
                    more than 1 growth point in absolute value (realised.py). Not evaluable (no realised pair or no first-filed base):
                    recorded, not excluded.
   revenue_scope    AK.37 v2's total-revenue abstention: realised.py's revenue_scope status closure_fail.
   Reported, not excluded: the run rate's revenue tag differing from the realised revenue tag (tag_mismatch), revenue_scope unverified,
   no year-1 annual filing by 2026-10-31.
 pool: the rest, a census.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(HERE), str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import realised  # noqa: E402
import same_filing as sf  # noqa: E402
import value_family  # noqa: E402
from qwen_c import packet, sec_store  # noqa: E402
from qwen_c.value import desk, facts, menu, run  # noqa: E402

POOL_VERSION = "j2.pool.v1"
T_STR = "2025-12-31T21:00:00Z"
T = datetime(2025, 12, 31, 21, 0, 0, tzinfo=timezone.utc)
FRAME_COMMIT = "d327fe8"
STOCKS_PATH = "public/data/stocks.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FY0_WINDOW = ("2024-12-24", "2025-01-07")
RELEASE_MAX_SESSIONS = 1
BASE_MOVE_POINTS = 0.01
KEYS = ("rev_growth.y1", "op_margin.y1")
OUT = book_paths.books() / "m3o" / "value" / "archival_2025-12-31" / "pool.json"


class CoeSkipped(Exception):
    """Raised in place of the cost-of-equity step: prepare's data steps all ran."""


def default_store():
    """<main checkout>/cache/archival_j2/sec_raw: a worktree shares the main checkout's git directory; cache/ is untracked."""
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=HERE, text=True).strip()
    gitdir = Path(common) if Path(common).is_absolute() else (HERE / common)
    return gitdir.resolve().parent / "cache" / "archival_j2" / "sec_raw"


def git_out(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, check=True).stdout


def frame_rows(repo):
    """(rows, full commit, stocks.json blob sha) at FRAME_COMMIT."""
    full = git_out(repo, "rev-parse", f"{FRAME_COMMIT}^{{commit}}").decode().strip()
    blob = git_out(repo, "rev-parse", f"{full}:{STOCKS_PATH}").decode().strip()
    rows = json.loads(git_out(repo, "show", f"{full}:{STOCKS_PATH}").decode("utf-8-sig"))
    return rows, full, blob


def get_doc(url, store, offline):
    """Bytes of url from the store, else (online) one fetch into it."""
    try:
        return sec_store.get(url, online=False, root=store)
    except sec_store.NotInStore:
        if offline:
            raise
        return sec_store.get(url, online=True, root=store)


def ticker_map(store, offline):
    data = get_doc(TICKERS_URL, store, offline)
    rec = sec_store.latest_receipt(TICKERS_URL, root=store)
    m = {}
    for r in json.loads(data).values():
        m.setdefault(str(r["ticker"]).upper(), (str(int(r["cik_str"])).zfill(10), r.get("title")))
    return m, {"url": TICKERS_URL, "sha256": rec["sha256"], "fetched_at": rec["fetched_at"]}


_STOP = {"inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "holdings", "holding", "group", "the", "class", "sa",
         "nv", "ag", "lp", "llc", "and", "of", "de", "se", "trust", "incorporated", "international"}


def _tokens(s):
    return {t for t in re.findall(r"[a-z0-9]+", str(s or "").lower()) if t not in _STOP}


def name_shared(a, b):
    """Whether the frame name and SEC's title share a significant word (a check on a current ticker map applied to a 2025 frame)."""
    return bool(_tokens(a) & _tokens(b))


def prepare_at_T(cik, sector, market_cap, family, store):
    """("ok", None, base) when every data step of run.prepare passes (the cost-of-equity step skipped), else ("refused", code: detail,
    base or None)."""
    seen = {}
    real_base = run.inputs.base

    def base(f, **kw):
        seen["b"] = real_base(f, **kw)
        return seen["b"]

    def skip(*a, **k):
        raise CoeSkipped()
    with mock.patch.object(run.coe, "cost_of_equity", skip), mock.patch.object(run.inputs, "base", base):
        try:
            run.prepare({"decision_time_utc": T_STR}, cik, sector, market_cap, online=False, family=family, root=store)
        except CoeSkipped:
            return "ok", None, seen["b"]
        except desk.DeskRefusal as e:
            return "refused", f"{e.code}: {e}"[:400], seen.get("b")
    raise AssertionError("run.prepare returned without reaching the cost-of-equity step")


def sessions_between(a_utc, b_utc):
    """NYSE sessions from the session of a to that of b (both effective times, i.e. session opens): 0 for the same session."""
    cal = packet._calendar()
    da, db = a_utc.astimezone(packet.EASTERN).date(), b_utc.astimezone(packet.EASTERN).date()
    return len(cal.sessions_in_range(da.isoformat(), db.isoformat())) - 1


def release_rule(subs, ytd):
    """{"excluded", "ten_q", "releases": [{accession, accepted, effective, sessions}]} for the run rate's 10-Q."""
    rows = packet._filing_rows(subs)
    tq = [r for r in rows if r["form"] in ("10-Q", "10-Q/A") and r["effective"] and r["effective"] <= T]
    q = next((r for r in tq if r["accession"] == ytd.get("accn")), None) or max(tq, key=lambda r: (r["effective"], r["accession"]), default=None)
    if q is None:
        return {"excluded": False, "ten_q": None, "releases": [], "note": "no 10-Q effective at T"}
    rel = []
    for r in rows:
        if (str(r["form"]).startswith("8-K") and "2.02" in str(r.get("items") or "") and r["accepted"] and r["effective"]
                and r["accepted"] > q["accepted"] and r["effective"] <= T):
            rel.append({"accession": r["accession"], "accepted": r["accepted"].isoformat(), "effective": r["effective"].isoformat(),
                        "sessions": sessions_between(q["effective"], r["effective"])})
    return {"excluded": any(x["sessions"] > RELEASE_MAX_SESSIONS for x in rel),
            "ten_q": {"accession": q["accession"], "accepted": q["accepted"].isoformat(), "effective": q["effective"].isoformat()},
            "releases": sorted(rel, key=lambda x: x["accepted"])}


def exclusions(cf, subs, fy0, ytd):
    """(excluded reasons, record): the four exclusions before the census and the reported-only flags. No realised growth or margin of a
    kept name enters the record."""
    real = realised.realised(cf, subs, fy0)
    y1 = real.get("year1") or {}
    y1_end, y1_stamp = (y1["report_date"], None) if y1 else ((date.fromisoformat(fy0) + timedelta(days=365)).isoformat(), "year1_end_fy0_plus_365")
    reasons = {}
    pub = sf.item_202_public(subs, y1_end, T.date().isoformat())
    if pub:
        reasons["item_202_public"] = pub
    rel = release_rule(subs, ytd)
    if rel["excluded"]:
        reasons["release"] = [x for x in rel["releases"] if x["sessions"] > RELEASE_MAX_SESSIONS]
    gap = real.get("growth_gap_points")
    if gap is not None and abs(gap) > BASE_MOVE_POINTS:
        reasons["base_move"] = {"growth_gap_points": gap, "base_move": real["base_move"], "first_filed": real["first_filed"]}
    scope = (real.get("scope") or {}).get("status")
    if scope == "closure_fail":
        reasons["revenue_scope"] = real["scope"]
    rtag = (real.get("revenue") or {}).get("tag")
    rec = {"year1_filing": {k: y1.get(k) for k in ("accession", "form", "filed", "report_date", "stamp")} if y1 else None,
           "year1_end_used": y1_end, "year1_end_stamp": y1_stamp, "realised_status": real["status"],
           "realised_margin_available": real.get("margin") is not None, "revenue_scope": scope, "restated_base": real.get("restated_base"),
           "base_move_evaluable": gap is not None, "release": rel, "item_202_public": pub,
           "tag_mismatch": bool(rtag and ytd.get("revenue_tag") and rtag != ytd["revenue_tag"]),
           "realised_revenue_tag": rtag, "run_rate_revenue_tag": ytd.get("revenue_tag")}
    return reasons, rec


def one(company, store, offline):
    """The record of one company (stages 3-8)."""
    out = dict(company)
    cik = company["cik"]
    try:
        for url in (facts.companyfacts_url(cik), facts.submissions_url(cik)):
            get_doc(url, store, offline)
        cf, subs, prov = facts.fetch(cik, T, online=False, root=store)
    except (sec_store.StoreError, ValueError) as e:
        return dict(out, stage="sec_documents", reason=type(e).__name__, detail=str(e)[:300])
    out["sec_documents"] = {k: {"sha256": v["sha256"], "fetched_at": v["fetched_at"]} for k, v in prov.items()}
    out["sec_name"], out["submissions_fiscal_year_end"] = subs.get("name"), subs.get("fiscalYearEnd")
    out["name_shares_a_word"] = name_shared(company["frame_name"], subs.get("name"))
    f = facts.annual_facts(cf, subs, T)
    fam = value_family.family(cf, subs, f, T)
    out.update(family=fam["family"], family_reason=fam["reason"], sic=fam["sic"], family_version=fam["version"])
    if fam["family"] not in run.ROUTED:
        return dict(out, stage="family", reason=str(fam["family"]), detail=fam["reason"])
    rev = (f.get("revenue") or {}).get("values") or []
    fy0 = rev[-1]["end"] if rev else None
    out["fy0"] = fy0
    if not (fy0 and FY0_WINDOW[0] <= fy0 <= FY0_WINDOW[1]):
        return dict(out, stage="december", reason="base_year_not_december_2024",
                    detail=f"latest annual revenue year at T ends {fy0}; submissions fiscalYearEnd {subs.get('fiscalYearEnd')}")
    status, why, b = prepare_at_T(cik, company["sector"], company["market_cap"], fam["family"], store)
    if status != "ok":
        return dict(out, stage="prepare", reason=why.split(":")[0], detail=why)
    y = b.get("ytd") or {}
    rr = {"rev_growth.y1": y.get("rev_growth") is not None, "op_margin.y1": menu._ok(y.get("op_margin")) is not None}
    out["run_rate"] = dict(rr, quarter=y.get("quarter"), accn=y.get("accn"), end=y.get("end"), stamp=y.get("stamp"),
                           absent=y.get("absent"), op_margin_absent=y.get("op_margin_absent"))
    if not any(rr.values()):
        return dict(out, stage="run_rate", reason="no_run_rate", detail=y.get("absent") or y.get("op_margin_absent"))
    reasons, rec = exclusions(cf, subs, fy0, y)
    out["checks"] = rec
    if reasons:
        return dict(out, stage="exclusion", reason="+".join(sorted(reasons)), detail=reasons)
    return dict(out, stage=None, reason=None, detail=None)


def code_state():
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    return {"commit": head, "tracked_tree_clean": not dirty}


def counts(frame_n, names):
    c = {"frame_rows": frame_n}
    order = ("cik", "duplicate_company", "sec_documents", "family", "december", "prepare", "run_rate", "exclusion")
    left = Counter(n["stage"] for n in names)
    alive = frame_n
    for s in order:
        alive -= left.get(s, 0)
        c[f"after_{s}"] = alive
    c["companies"] = c["after_duplicate_company"]
    c["family"] = dict(Counter(n.get("family") for n in names if n.get("family") is not None or n["stage"] == "family"))
    c["prepare_refusals"] = dict(Counter(n["reason"] for n in names if n["stage"] == "prepare"))
    reached = [n for n in names if n.get("run_rate")]
    c["run_rate_measured"] = {k: sum(n["run_rate"][k] for n in reached) for k in KEYS}
    c["run_rate_both"] = sum(all(n["run_rate"][k] for k in KEYS) for n in reached)
    checked = [n for n in names if n.get("checks")]
    c["exclusion_hits_any_order"] = {r: sum(r in (n["detail"] or {}) for n in checked if n["stage"] == "exclusion")
                                     for r in ("item_202_public", "release", "base_move", "revenue_scope")}
    c["exclusion_sets"] = dict(Counter(n["reason"] for n in checked if n["stage"] == "exclusion"))
    pool = [n for n in names if n["stage"] is None]
    c["pool"] = len(pool)
    c["pool_by_family"] = dict(Counter(n["family"] for n in pool))
    c["pool_run_rate"] = {k: sum(n["run_rate"][k] for n in pool) for k in KEYS}
    c["reported_not_excluded"] = {
        "no_year1_annual_filing_by_2026_10_31": sum(n["checks"]["realised_status"] == "no_year1_annual_filing" for n in pool),
        "realised_status": dict(Counter(n["checks"]["realised_status"] for n in pool)),
        "realised_margin_available": sum(n["checks"]["realised_margin_available"] for n in pool),
        "base_move_not_evaluable": sum(not n["checks"]["base_move_evaluable"] for n in pool),
        "restated_base_within_1_point": sum(bool(n["checks"]["restated_base"]) for n in pool),
        "revenue_scope": dict(Counter(n["checks"]["revenue_scope"] for n in pool)),
        "tag_mismatch": sum(n["checks"]["tag_mismatch"] for n in pool),
        "release_within_1_session": sum(bool(n["checks"]["release"]["releases"]) for n in pool),
        "year1_end_fy0_plus_365": sum(n["checks"]["year1_end_stamp"] is not None for n in pool)}
    c["frame_name_shares_no_word_with_sec_title"] = sum(n.get("name_shares_a_word") is False for n in names)
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--screener-repo", help="a screener clone holding the frame commit (default: paths.py screener_publish_repo)")
    ap.add_argument("--store", help="the qwen_c.sec_store root for this pool (default: <main checkout>/cache/archival_j2/sec_raw)")
    ap.add_argument("--offline", action="store_true", help="never fetch: a document not in the store leaves the name at sec_documents")
    ap.add_argument("--limit", type=int, help="the first N frame rows only (a smoke; nothing is written)")
    a = ap.parse_args(argv)
    repo = Path(a.screener_repo) if a.screener_repo else book_paths.screener_repo()
    store = Path(a.store) if a.store else default_store()
    rows, commit, blob = frame_rows(repo)
    frame_n = len(rows)
    rows = rows[: a.limit] if a.limit else rows
    tmap, tprov = ticker_map(store, a.offline)
    names, by_cik = [], {}
    for r in sorted(rows, key=lambda r: str(r.get("symbol"))):
        sym = str(r.get("symbol") or "")
        hit = tmap.get(sym.upper()) or tmap.get(sym.upper().replace(".", "-"))
        base = {"ticker": sym, "frame_name": r.get("name"), "sector": r.get("sector"), "market_cap": r.get("marketCap")}
        if not hit:
            names.append(dict(base, cik=None, stage="cik", reason="no_cik", detail="not in SEC company_tickers.json"))
            continue
        base.update(cik=hit[0], sec_title=hit[1])
        if hit[0] in by_cik:
            by_cik[hit[0]]["other_tickers"].append(sym)
            names.append(dict(base, stage="duplicate_company", reason="duplicate_company", detail=f"CIK of {by_cik[hit[0]]['ticker']}"))
            continue
        by_cik[hit[0]] = dict(base, other_tickers=[])
    for i, (cik, comp) in enumerate(sorted(by_cik.items(), key=lambda kv: kv[1]["ticker"]), 1):
        names.append(one(comp, store, a.offline))
        if i % 100 == 0:
            print(f"{i}/{len(by_cik)}", flush=True)
    c = counts(len(rows), names)
    doc = {"version": POOL_VERSION, "T": T_STR, "spec": "J2 v0.2 section 7 (items 3, 7, 8, 9); PREREG addendum draft v0.2",
           "frame": {"commit": commit, "stocks_json_blob": blob, "path": STOCKS_PATH, "rows": frame_n},
           "cik_map": tprov, "store": str(store), "code": dict(code_state(), pool=POOL_VERSION, realised=realised.REALISED_VERSION,
                                                              facts=facts.FACTS_VERSION, inputs=run.inputs.INPUTS_VERSION,
                                                              family=value_family.FAMILY_VERSION, menu=menu.MENU_VERSION),
           "rules": {"fy0_window": FY0_WINDOW, "release_max_sessions": RELEASE_MAX_SESSIONS, "base_move_points": BASE_MOVE_POINTS,
                     "routed_families": list(run.ROUTED), "cost_of_equity": "skipped in the pool definition (J2 section 7 item 1)",
                     "pool_keys": "a name stays with at least one key's run rate measured; each key is judged only where measured"},
           "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "counts": c,
           "pool": [n for n in names if n["stage"] is None], "left": [n for n in names if n["stage"] is not None]}
    print(json.dumps(c, indent=1, default=str))
    if a.limit:
        print("--limit: a smoke, nothing written")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, indent=1, sort_keys=True, default=str).encode("utf-8")
    tmp = OUT.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, OUT)
    print(f"wrote {OUT} sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

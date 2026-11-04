"""score.py (J2-6): the archival test's scorer on a synthetic run directory (pool.json, runs.json, slots.json, result.json files and a
synthetic sec_store of companyfacts and submissions). No real company, no network."""
import hashlib
import json
import math

import numpy as np
import pytest

import score as S
from qwen_c import sec_store
from qwen_c.value import facts

FY0, FY1 = "2024-12-31", "2025-12-31"
K0, K1 = "0000000001-25-000001", "0000000001-26-000002"
G, M = "rev_growth.y1", "op_margin.y1"
GIT = "a" * 40


# ------------------------------------------------------------------ synthetic SEC documents (as test_realised.py)
def fact(start, end, val, accn, filed, form="10-K", fp="FY"):
    return {"start": start, "end": end, "val": val, "accn": accn, "filed": filed, "form": form, "fp": fp}


def documents(growth, margin, filed=True, r0_first=None):
    r0, r1 = 1000.0, 1000.0 * (1 + growth)
    cf = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fact("2024-01-01", FY0, r0 if r0_first is None else r0_first, K0, "2025-02-20"),
                                       fact("2025-01-01", FY1, r1, K1, "2026-02-19"), fact("2024-01-01", FY0, r0, K1, "2026-02-19")]}},
        "OperatingIncomeLoss": {"units": {"USD": [fact("2025-01-01", FY1, margin * r1, K1, "2026-02-19"),
                                                  fact("2024-01-01", FY0, 90.0, K1, "2026-02-19")]}}}}}
    rows = [("10-K", K0, "2025-02-20", FY0)] + ([("10-K", K1, "2026-02-19", FY1)] if filed else [])
    subs = {"filings": {"recent": {"form": [r[0] for r in rows], "accessionNumber": [r[1] for r in rows],
                                   "filingDate": [r[2] for r in rows], "reportDate": [r[3] for r in rows]}}}
    return cf, subs


# ------------------------------------------------------------------ synthetic valuation results
BAR = {"median": 0.11, "p25": 0.09, "p75": 0.13, "last": 0.12, "min": 0.05, "max": 0.15}
RECORD = {"rev_growth": {"2022-12-31": 0.02, "2023-12-31": 0.04, "2024-12-31": 0.07}, "capex_ratio": {}}
EVIDENCE = {"P1.s1": "release", "P2.s1": "quarterly_section", "P3.s1": "annual_section", "S1": "statement", "Y2024-12-31": "filed_record"}


def result(t, seed, *, g=0.10, m=0.10, ytd_g=0.05, ytd_m=0.10, status="ok", opt_g="last", drv_g="pricing", ev_g=("S1",),
           guide_g=None, numbers=True, base=True):
    """One result.json. g, m: checks.numbers; the neutral is the ytd pair (None: not measured, the anchor / record median stands)."""
    neutral = {G: 0.03 if ytd_g is None else ytd_g, M: 0.11 if ytd_m is None else ytd_m}
    deps = [{"input": G, "driver": drv_g, "evidence": list(ev_g)}] if abs(g - neutral[G]) > 0.001 and drv_g else []
    r = {"ticker": t, "seed": seed, "packet_sha256": f"pk-{t}", "status": status, "versions": {"git": [GIT, False]}}
    if base:
        r.update(base={"ytd": {"rev_growth": ytd_g, "op_margin": ytd_m}, "g_anchor": 0.03, "record": RECORD, "R0": 1000.0,
                       "c_ratio": 0.05, "delta": 0.0, "ronic0": None},
                 bar=BAR, cost_of_equity=0.09, coe={"stamps": ["coe_archival_pinned"]})
    if numbers:
        r["checks"] = {"route": "operating", "numbers": {G: g, M: m}, "neutral": neutral,
                       "options": {G: "guidance" if guide_g else opt_g, M: "ytd"}, "departures": deps,
                       "evidence": {i: {"kind": k, "text": "", "period": FY1} for i, k in EVIDENCE.items()}}
        r["inputs"] = {"guidance": {G: {"evidence": guide_g, "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}} if guide_g else {}}
    elif status == "no_call" and base:
        r["checks"] = {"route": "operating", "status": "no_call", "reason": "record_neutral_unavailable"}
    return r


class Run:
    """A synthetic archival_2025-12-31 directory."""

    def __init__(self, tmp):
        self.d, self.store = tmp, tmp / "store"
        self.pool, self.packets, self.results = [], {}, {}

    def add(self, t, *, real=(0.08, 0.12), rr=(True, True), refused=None, filed=True, **kw):
        """A company: realised (growth, margin); its two results built by result(**kw), or per-seed kw under s1000 / s3000."""
        cik = str(len(self.pool) + 1).zfill(10)
        cf, subs = documents(*real, filed=filed)
        shas = {}
        for name, url, doc in (("companyfacts", facts.companyfacts_url(cik), cf), ("submissions", facts.submissions_url(cik), subs)):
            shas[name] = {"sha256": sec_store._store(self.store, url, json.dumps(doc).encode("utf-8"), 200, "test")}
        self.pool.append({"ticker": t, "cik": cik, "fy0": FY0, "run_rate": {G: rr[0], M: rr[1]}, "sec_documents": shas})
        if refused is not None:
            self.packets[t] = {"packet": None, "refused": refused}
            return
        self.packets[t] = {"packet": f"packets/{t}.json", "packet_sha256": f"pk-{t}", "annotations": None}
        base_kw = {k: v for k, v in kw.items() if k not in ("s1000", "s3000")}
        if not rr[0]:
            base_kw.setdefault("ytd_g", None)
        if not rr[1]:
            base_kw.setdefault("ytd_m", None)
        for seed in S.SEEDS:
            self.results[(t, seed)] = result(t, seed, **dict(base_kw, **kw.get(f"s{seed}", {})))

    def write(self, drop_slot=None, drop_packet=None):
        (self.d / "res").mkdir(exist_ok=True)
        pool_b = json.dumps({"T": "2025-12-31T21:00:00Z", "store": str(self.store), "pool": self.pool}).encode("utf-8")
        (self.d / "pool.json").write_bytes(pool_b)
        self.pool_sha = hashlib.sha256(pool_b).hexdigest()
        slots = {}
        for (t, seed), r in self.results.items():
            p = self.d / "res" / f"{t}_{seed}.json"
            p.write_text(json.dumps(r), encoding="utf-8")
            slots[f"{t}:{seed}"] = {"status": r["status"], "reason": r.get("reason"), "result": str(p),
                                    "result_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        slots.pop(drop_slot, None)
        packets = {t: v for t, v in self.packets.items() if t != drop_packet}
        (self.d / "runs.json").write_text(json.dumps({"pool_sha256": self.pool_sha, "packets": packets, "slots": {}, "git": None}))
        (self.d / "slots.json").write_text(json.dumps({"git": GIT, "slots": slots}))
        return self

    def score(self):
        return S.score(self.d, pool_sha256=self.pool_sha)


# ------------------------------------------------------------------ statistics
def test_the_sign_test_is_exact_and_one_sided():
    assert S.sign_p(15, 20) == pytest.approx(sum(math.comb(20, i) for i in range(15, 21)) / 2 ** 20)
    assert S.sign_p(0, 5) == 1.0 and S.sign_p(5, 5) == 1 / 32 and S.sign_p(0, 0) is None


def test_ties_are_dropped_from_the_sign_test_and_counted_in_n():
    d = S.describe([-0.01, -0.02, 0.0, 1e-13, 0.03])
    assert (d["n"], d["ties"], d["n_nontie"], d["k_negative"]) == (5, 2, 3, 2)
    assert d["sign_p"] == pytest.approx(S.sign_p(2, 3)) and d["share_negative"] == pytest.approx(2 / 5) and d["median"] == 0.0


def test_pass_needs_the_sign_test_and_a_winsorised_mean_not_above_zero():
    win = [-0.01] * 16 + [0.005] * 4                                  # k 16 of 20: p 0.0059, mean below 0
    assert S.judge(win)["verdict"] == "PASS"
    harm = [-0.001] * 18 + [0.5] * 7                                   # k 18 of 25: p 0.022, but a few large misses
    j = S.judge(harm)
    assert j["sign_p"] < 0.05 and j["winsorised_mean"] > 0 and j["verdict"] == "FAIL"
    weak = [-0.01] * 12 + [0.01] * 8                                   # p 0.25
    assert S.judge(weak)["verdict"] == "FAIL"
    assert S.judge([-0.01] * 19)["verdict"] == "NOT_DECIDED"          # fewer than 20 judged companies
    assert S.judge([-0.01] * 15 + [0.0] * 5)["verdict"] == "PASS"     # ties count toward n = 20


def test_the_winsorised_mean_clips_at_the_5th_and_95th_percentiles():
    d = list(np.linspace(-1, 1, 21)) + [100.0]
    lo, hi = np.percentile(d, [5, 95])
    assert S.winsorised_mean(d) == pytest.approx(float(np.clip(d, lo, hi).mean())) and S.winsorised_mean(d) < 1


def test_the_bootstrap_is_company_level_seeded_and_reproducible():
    d = [(-1) ** i * 0.01 * i for i in range(25)]
    rng = np.random.default_rng(20261104)
    a = np.asarray(d)
    want = float(np.percentile(np.median(a[rng.integers(0, 25, size=(2000, 25))], axis=1), 90))
    assert S.bootstrap_q90(d) == want == S.bootstrap_q90(d)


def test_refusal_codes():
    assert S.refusal_code("held_out: B5 holdout / Stage-2 sealed") == "held_out"
    tb = 'Traceback...\n  File "x", line 1\nqwen_c.sec_store.FetchFailed: fetch failed: status=200 ... larger than 80000000 bytes\n'
    assert S.refusal_code(tb) == "qwen_c.sec_store.FetchFailed" and S.refusal_code(None) == "unparsed"


# ------------------------------------------------------------------ the score
def test_a_full_census_is_scored_by_the_registered_statistic(tmp_path):
    run = Run(tmp_path)
    # 20 judged growth departures: the model (two-seed mean 0.075) is closer to the realised 0.08 than the run rate 0.05 in 16
    for i in range(16):
        run.add(f"W{i:02d}", s1000={"g": 0.07}, s3000={"g": 0.08})
    for i in range(4):
        run.add(f"L{i:02d}", real=(0.04, 0.12), g=0.10)
    doc = run.write().score()
    j = doc["keys"][G]["judged"]
    assert (j["n"], j["k_negative"], j["n_nontie"]) == (20, 16, 20) and j["verdict"] == "PASS"
    assert j["sign_p"] == pytest.approx(S.sign_p(16, 20))
    w = next(r for r in doc["keys"][G]["rows"] if r["ticker"] == "W00")
    assert w["model"] == pytest.approx(0.075) and w["run_rate"] == 0.05 and w["realised"] == pytest.approx(0.08)
    assert w["d"] == pytest.approx(abs(0.075 - 0.08) - abs(0.05 - 0.08))
    lo = next(r for r in doc["keys"][G]["rows"] if r["ticker"] == "L00")
    assert lo["d"] == pytest.approx(abs(0.10 - 0.04) - abs(0.05 - 0.04))
    assert w["realised_first_filed"] == pytest.approx(0.08) and w["d_first_filed"] == pytest.approx(w["d"])
    # margins never depart (the model kept the ytd 0.10): no margin key is judged
    assert doc["keys"][M]["judged"]["verdict"] == "NOT_DECIDED" and doc["keys"][M]["exclusions"] == {"not_departed": 20}
    assert (tmp_path / "score.json").exists() and "PASS" in (tmp_path / "score.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "score.json").read_text())["inputs"]["pool_sha256"] == run.pool_sha


def test_exclusions_are_counted_in_the_registered_order(tmp_path):
    run = Run(tmp_path)
    run.add("A", rr=(False, True), m=0.13)                                       # growth: neutral is the anchor
    run.add("B", refused="held_out: B5 holdout / Stage-2 sealed / operator excluded")
    run.add("C", refused="Traceback\nqwen_c.sec_store.FetchFailed: fetch failed\n")
    run.add("D", s3000={"status": "reply_invalid", "numbers": False})            # one seed
    run.add("E", status="no_call", numbers=False)                                  # no numbers in either seed
    run.add("F", status="no_call", g=0.09)                                         # a desk refusal of the Base still carries numbers: scored
    run.add("G", g=0.05)                                                           # at the run rate: not departed
    run.add("H", filed=False)                                                      # no FY2025 annual filing by 2026-10-31
    run.add("I", rr=(True, False), s1000={"g": 0.0505})                            # inside TOL in seed 1000, departed in 3000
    doc = run.write().score()
    ex = doc["keys"][G]["exclusions"]
    assert ex == {"neutral_not_run_rate": 1, "packet_refused:held_out": 1, "packet_refused:qwen_c.sec_store.FetchFailed": 1,
                  "seed_one_scored:reply_invalid": 1, "seed_none_scored:no_call_without_numbers": 1, "not_departed": 1,
                  "realised_unavailable:no_year1_annual_filing": 1}
    assert sorted(r["ticker"] for r in doc["keys"][G]["rows"]) == ["F", "I"]
    f = next(r for r in doc["keys"][G]["rows"] if r["ticker"] == "F")
    assert f["status_by_seed"] == {"1000": "no_call", "3000": "no_call"} and f["model"] == pytest.approx(0.09)
    i = next(r for r in doc["keys"][G]["rows"] if r["ticker"] == "I")
    assert i["model"] == pytest.approx((0.0505 + 0.10) / 2) and i["segment"] == "seeds_disagree"
    assert i["segment_by_seed"] == {"1000": "not_departed", "3000": "other_drivers"}
    exm = doc["keys"][M]["exclusions"]
    assert exm["neutral_not_run_rate"] == 1 and exm["packet_refused:held_out"] == 1
    assert next(r for r in doc["keys"][M]["rows"] if r["ticker"] == "A")["realised"] == pytest.approx(0.12)
    assert doc["keys"][G]["neutral_not_run_rate_departures_reported"] == {"departed": 1}   # A departs from its anchor: reported only


def test_a_margin_without_a_same_filing_operating_income_is_unavailable_not_imputed(tmp_path, monkeypatch):
    run = Run(tmp_path)
    run.add("A", m=0.13)
    real = S.realised.realised

    def no_margin(cf, subs, fy0):
        cf["facts"]["us-gaap"].pop("OperatingIncomeLoss")
        return real(cf, subs, fy0)
    monkeypatch.setattr(S.realised, "realised", no_margin)
    doc = run.write().score()
    assert doc["keys"][M]["exclusions"] == {"realised_unavailable:margin_absent": 1}
    assert doc["keys"][M]["excluded"][0]["detail"] == "no same-filing operating income pair"
    assert [r["ticker"] for r in doc["keys"][G]["rows"]] == ["A"]


def test_segments_by_the_cited_kind_and_driver(tmp_path):
    run = Run(tmp_path)
    run.add("A", guide_g="P1.s1", drv_g="guidance", ev_g=("P1.s1",))             # guidance option citing a release
    run.add("B", drv_g="guidance", ev_g=("P2.s1", "V0"))                          # a menu option, guidance driver, a 10-Q sentence
    run.add("C", guide_g="P3.s1", drv_g="volume", ev_g=("P3.s1",))                # an annual report sentence: unclassified
    run.add("D", drv_g="guidance", ev_g=("P1.s1", "P2.s1"))                       # both: unclassified
    run.add("E", drv_g="record_persistence", ev_g=("Y2024-12-31",))
    run.add("F", drv_g="pricing")
    run.add("G", s1000={"drv_g": "record_persistence"}, s3000={"drv_g": "pricing"})
    doc = run.write().score()
    seg = {r["ticker"]: r["segment"] for r in doc["keys"][G]["rows"]}
    assert seg == {"A": "guidance_outlook", "B": "guidance_10q_actual", "C": "guidance_source_unclassified",
                   "D": "guidance_source_unclassified", "E": "record_persistence", "F": "other_drivers", "G": "seeds_disagree"}
    assert doc["keys"][G]["segments"]["guidance_outlook"]["n"] == 1 and doc["keys"][G]["drivers_by_seed"]["1000:pricing"] == 1


def test_comparators_are_the_seed_menus_numbers_and_the_margin_anchor_is_the_record_median(tmp_path):
    run = Run(tmp_path)
    run.add("A", m=0.13, real=(0.08, 0.125))
    doc = run.write().score()
    g = doc["keys"][G]["rows"][0]["comparators"]
    assert g == {"last": 0.07, "old_anchor_neutral": 0.03, "record_median": 0.04}
    m = doc["keys"][M]["rows"][0]["comparators"]
    assert m == {"last": 0.12, "old_anchor_neutral": 0.11, "record_median": 0.11}
    c = doc["keys"][M]["comparators_reported_not_judged"]
    assert c["old_anchor_neutral"] == c["record_median"] and "identical" in c["note"]
    assert c["last"]["median"] == pytest.approx(abs(0.13 - 0.125) - abs(0.12 - 0.125))


# ------------------------------------------------------------------ stops
def test_the_pool_flag_disagreeing_with_a_stored_ytd_stops(tmp_path):
    run = Run(tmp_path)
    run.add("A", rr=(False, True), ytd_g=0.05)                                    # the pool says unmeasured, the result measured it
    with pytest.raises(S.Stop, match="pool run_rate False"):
        run.write().score()


def test_a_neutral_that_is_not_the_ytd_stops(tmp_path):
    run = Run(tmp_path)
    run.add("A")
    run.results[("A", 3000)]["checks"]["neutral"][G] = 0.03
    with pytest.raises(S.Stop, match="checks.neutral"):
        run.write().score()


def test_a_ytd_that_differs_across_seeds_stops(tmp_path):
    run = Run(tmp_path)
    run.add("A", s3000={"ytd_g": 0.06})
    with pytest.raises(S.Stop, match="differs across seeds"):
        run.write().score()


def test_an_incomplete_run_is_refused(tmp_path):
    run = Run(tmp_path)
    run.add("A")
    run.add("B")
    with pytest.raises(S.Stop, match="no packet entry"):
        run.write(drop_packet="B").score()
    with pytest.raises(S.Stop, match="no slot for seed 3000"):
        run.write(drop_slot="B:3000").score()
    assert not (tmp_path / "score.json").exists()


def test_score_json_is_never_overwritten(tmp_path):
    run = Run(tmp_path)
    run.add("A")
    run.write().score()
    with pytest.raises(S.Stop, match="never overwritten"):
        run.score()


def test_changed_inputs_stop(tmp_path):
    run = Run(tmp_path)
    run.add("A")
    run.write()
    with pytest.raises(S.Stop, match="registered"):
        S.score(tmp_path, pool_sha256="0" * 64)
    p = tmp_path / "res" / "A_1000.json"
    p.write_text(p.read_text() + " ")
    with pytest.raises(S.Stop, match="does not hash"):
        run.score()


def test_a_result_without_the_pinned_cost_of_equity_stops(tmp_path):
    run = Run(tmp_path)
    run.add("A")
    run.results[("A", 1000)]["coe"]["stamps"] = []
    with pytest.raises(S.Stop, match="coe_archival_pinned"):
        run.write().score()


def test_realised_reads_only_the_pinned_documents(tmp_path):
    run = Run(tmp_path)
    run.add("A")
    run.pool[0]["sec_documents"]["companyfacts"]["sha256"] = "f" * 64            # not the bytes the pool recorded
    with pytest.raises(sec_store.NotInStore):
        run.write().score()


def test_a_fix_commit_after_a_stop_is_read_per_slot(tmp_path):
    # j2_run --continue-from: slots before the fix carry no commit of their own (the first commit, git_changes[0].from); later ones do
    run = Run(tmp_path)
    run.add("A")
    run.add("B")
    for seed in S.SEEDS:
        run.results[("B", seed)]["versions"]["git"] = ["b" * 40, False]
    run.write()
    sl = json.loads((tmp_path / "slots.json").read_text())
    sl.update(git="b" * 40, git_changes=[{"from": GIT, "to": "b" * 40, "utc": "2026-11-04T08:00:00Z"}])
    for seed in S.SEEDS:
        sl["slots"][f"B:{seed}"]["git"] = "b" * 40
    (tmp_path / "slots.json").write_text(json.dumps(sl))
    run.score()
    (tmp_path / "score.json").unlink()
    sl["slots"]["B:1000"]["git"] = GIT                                  # the slot says the first commit, its result says the fix
    (tmp_path / "slots.json").write_text(json.dumps(sl))
    with pytest.raises(S.Stop, match="another commit"):
        run.score()

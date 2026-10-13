"""Engine v2's near-term table builder (SPEC_engine_v2.md sections 2-3, 6; REGISTRATION_engine_v2 E6): what it measures, and the cut proof."""
import copy
import math
import json

import numpy as np
import pandas as pd
import pytest

from valuation import near_term as nt
from valuation.priors_build import near_term as nb


def obs_frame(n=400, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        fam = "operating" if i % 4 else "financial"
        own = f"{2014 + i % 8}-03-01"
        r = {"cik": i, "fye": own[:4] + "-12-31", "own_filed": own, "family": fam, "rev": 100.0, "tbv": 50.0}
        for k in nt.KS:
            r[f"rev_{k}"] = 100.0 * (1 + rng.normal(0.06, 0.1)) ** k
            r[f"tbv_{k}"] = 50.0 * (1 + rng.normal(0.05, 0.05)) ** k
            r[f"m_{k}"] = rng.normal(0.12, 0.05)
            r[f"rote_{k}"] = rng.normal(0.11, 0.04)
            r[f"filed_{k}"] = f"{2014 + i % 8 + k}-03-01"
        rows.append(r)
    return pd.DataFrame(rows)


def panel_frame(n=300, seed=2):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        fam = "operating" if i % 3 else "financial"
        y = 2016 + i % 8
        r = {"date": f"{y}-06-30", "cik": 10_000 + i, "family": fam, "f_rev": 2e9, "f_g3": 0.07, "f_g_latest": 0.07, "f_tg3": 0.05, "f_tg_latest": 0.05,
             "f_m": rng.uniform(0, 0.3), "f_rote": rng.uniform(0, 0.25)}
        shock = rng.normal(0, 0.05)
        for k in nt.KS:
            r[f"c_growth_{k}_p50"] = 0.08
            r[f"c_margin_curve_{k}_p50"] = 0.14
            r[f"c_rote_curve_{k}_p50"] = 0.12
            r[f"g_{k}"] = 0.07 + shock + rng.normal(0, 0.01)
            r[f"m_{k}"] = 0.13 + shock + rng.normal(0, 0.01)
            r[f"tg_{k}"] = 0.05 + shock
            r[f"rote_{k}"] = 0.11 + shock
            r[f"filed_{k}"] = f"{y + k}-02-15"
        rows.append(r)
    return pd.DataFrame(rows)


def test_population_medians_use_only_rows_and_outcomes_filed_before_the_cut():
    d = obs_frame()
    for k in nt.KS:
        pr = "rev" if k == 1 else f"rev_{k - 1}"
        d[f"g_{k}"] = d[f"rev_{k}"] / d[pr] - 1.0
    m = nb.population_medians(d, "2019-01-01")
    sel = d[(d["family"] == "operating") & (d["own_filed"] < "2019-01-01") & (d["filed_1"] < "2019-01-01")]
    assert m["operating"]["growth"]["1"]["n"] == len(sel) and m["operating"]["growth"]["1"]["median"] == pytest.approx(sel["g_1"].median())
    assert m["operating"]["growth"]["1"]["max_filed"] < "2019-01-01"


def _obs():
    d = obs_frame()
    for k in nt.KS:
        pr, pt = ("rev", "tbv") if k == 1 else (f"rev_{k - 1}", f"tbv_{k - 1}")
        d[f"g_{k}"] = d[f"rev_{k}"] / d[pr] - 1.0
        d[f"tg_{k}"] = d[f"tbv_{k}"] / d[pt] - 1.0
    return d


def test_residuals_are_the_outcome_minus_the_rule_at_the_origins_own_cut_and_nothing_filed_after_the_cut():
    obs, panel = _obs(), panel_frame()
    res = nb.residual_frame(panel, obs, "2021-01-01")
    assert (res["date"].astype(str) < "2021-01-01").all()
    row = res[(res["var"] == "growth") & (res["k"] == 1)].iloc[0]
    p = panel[(panel["cik"] == row["cik"])].iloc[0]
    i = nb.population_medians(obs, f"{str(p['date'])[:4]}-01-01")["operating"]["growth"]["1"]["median"]
    assert row["resid"] == pytest.approx(math.log1p(p["g_1"]) - math.log1p(i + 0.5 * (0.08 - i)))    # section 2's rule; growth in log space (AL.1)
    m = res[(res["var"] == "margin") & (res["k"] == 2)].iloc[0]
    pm = panel[panel["cik"] == m["cik"]].iloc[0]
    assert m["resid"] == pytest.approx(pm["m_2"] - 0.14)                                   # margin: the code's path
    for _, r in res.iterrows():                                                            # every outcome used was filed before the cut
        assert str(panel[panel["cik"] == r["cik"]].iloc[0][f"filed_{r['k']}"]) < "2021-01-01"


def test_the_table_measures_pools_cells_and_the_copula_and_leaves_the_unmeasurable_partner_independent():
    t = nb.build_table(2022, panel_frame(n=600), _obs())
    pool = t["residuals"]["operating"]["growth"]["1"]["pool"]
    assert pool["n"] >= nt.MIN_N and list(pool["q"]) == [str(p) for p in nt.RESID_LEVELS]
    assert t["corr"]["operating"]["nt_lgrowth_1|nt_lgrowth_2"] > 0.9                         # a shared shock: strongly dependent residuals
    assert t["corr"]["operating"]["nt_margin_3|margin_target"] is None and t["level_cuts"]["operating"] is not None
    assert t["cut_date"] == "2023-01-01" and t["i"]["operating"]["growth"]["1"]["max_filed"] < "2023-01-01"


def test_the_cut_proof_every_fact_filed_on_or_after_the_cut_changes_and_the_table_does_not():
    obs, panel = _obs(), panel_frame(n=600)
    a = nb.build_table(2020, panel, obs)
    cut = a["cut_date"]
    obs2, panel2 = obs.copy(), panel.copy()
    late_rows = obs2["own_filed"].astype(str) >= cut
    for c in obs2.columns:
        if c not in ("cik", "fye", "own_filed", "family") and not c.startswith("filed_"):
            obs2.loc[late_rows, c] = obs2.loc[late_rows, c] * 3 + 7
    for k in nt.KS:
        lo = obs2[f"filed_{k}"].astype(str) >= cut
        for c in (f"rev_{k}", f"tbv_{k}", f"m_{k}", f"rote_{k}", f"g_{k}", f"tg_{k}"):
            obs2.loc[lo, c] = obs2.loc[lo, c] * 3 + 7
        lp = panel2[f"filed_{k}"].astype(str) >= cut
        for c in (f"g_{k}", f"m_{k}", f"tg_{k}", f"rote_{k}"):
            panel2.loc[lp, c] = panel2.loc[lp, c] * 3 + 7
    late_origin = panel2["date"].astype(str) >= cut
    for c in panel2.columns:
        if c.startswith(("c_", "f_", "g_", "m_", "tg_", "rote_")):
            panel2.loc[late_origin, c] = panel2.loc[late_origin, c] * 3 + 7
    b = nb.build_table(2020, panel2, obs2)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


# ---- Addendum AL.10: per-vintage inputs ----------------------------------------------------------------------------------------------------------------

def test_the_medians_at_each_origins_cut_come_from_that_cuts_own_obs_when_given():
    obs, panel = _obs(), panel_frame()
    other = _obs()
    other["rev_1"] = other["rev_1"] * 1.5                                                  # a different extraction: other medians
    other["g_1"] = other["rev_1"] / other["rev"] - 1.0
    seen = []

    def medians_obs(ocut):
        seen.append(ocut)
        return other
    res = nb.residual_frame(panel, obs, "2021-01-01", medians_obs)
    row = res[(res["var"] == "growth") & (res["k"] == 1)].iloc[0]
    p = panel[(panel["cik"] == row["cik"])].iloc[0]
    i = nb.population_medians(other, f"{str(p['date'])[:4]}-01-01")["operating"]["growth"]["1"]["median"]
    assert row["resid"] == pytest.approx(math.log1p(p["g_1"]) - math.log1p(i + 0.5 * (0.08 - i)))
    used = panel[(panel["date"].astype(str) < "2021-01-01") & (panel["filed_1"].astype(str) < "2021-01-01")]       # origins with a residual: medians only where needed
    assert sorted(set(seen)) == sorted({f"{str(d)[:4]}-01-01" for d in used["date"]})


def _write_vintage(root, v, obs, cut=None):
    import hashlib
    d = root / str(v)
    d.mkdir(parents=True)
    p = d / "obs.csv.gz"
    obs.to_csv(p, index=False)
    (d / "obs_meta.json").write_text(json.dumps({"vintage": v, "cut_date": cut or f"{v + 1}-01-01", "obs_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}))
    return p


def test_own_obs_path_refuses_another_vintages_extraction_and_altered_bytes(tmp_path):
    _write_vintage(tmp_path, 2019, obs_frame(n=40))
    assert nb.own_obs_path(tmp_path, 2019).name == "obs.csv.gz"
    _write_vintage(tmp_path, 2020, obs_frame(n=40), cut="2022-01-01")
    with pytest.raises(SystemExit, match="not vintage 2020's own extraction"):
        nb.own_obs_path(tmp_path, 2020)
    with open(tmp_path / "2019" / "obs.csv.gz", "ab") as fh:
        fh.write(b"x")
    with pytest.raises(SystemExit, match="obs_sha256"):
        nb.own_obs_path(tmp_path, 2019)


def test_per_vintage_main_refuses_a_panel_not_joined_to_the_vintages_own_obs_and_labels_the_extractor(tmp_path):
    import hashlib
    root = tmp_path / "obs"
    for v in range(2015, 2023):
        _write_vintage(root, v, obs_frame())
    panel = panel_frame(n=600)
    meta = json.loads((root / "2022" / "obs_meta.json").read_text())
    panel.attrs.update(cut="2022-12-31", obs_sha256=meta["obs_sha256"])
    panel.to_pickle(tmp_path / "panel_2022.pkl")
    bad = panel.copy()
    bad.attrs.update(cut="2023-12-31", obs_sha256=meta["obs_sha256"])
    bad.to_pickle(tmp_path / "panel_2021.pkl")
    with pytest.raises(SystemExit, match="not joined to vintage 2021's own obs"):
        nb.main(["--vintages", "2021", "--obs-root", str(root), "--panel-pattern", str(tmp_path / "panel_{V}.pkl"), "--out", str(tmp_path / "out")])
    nb.main(["--vintages", "2022", "--obs-root", str(root), "--panel-pattern", str(tmp_path / "panel_{V}.pkl"), "--out", str(tmp_path / "out")])
    raw = (tmp_path / "out" / "2022" / "near_term.json").read_bytes()
    t = json.loads(raw)
    assert (tmp_path / "out" / "2022" / "near_term.sha256").read_text() == hashlib.sha256(raw).hexdigest()
    assert t["inputs"]["mode"].startswith("per_vintage") and t["extractor"]["label"] == "legacy"
    assert t["extractor"]["vendored_extractor_sha256"] == nb.LEGACY_EXTRACTOR_SHA256 and len(t["extractor"]["known_defects"]) == 2
    with pytest.raises(SystemExit):
        nb.main(["--vintages", "2022", "--obs-root", str(root), "--out", str(tmp_path / "out2")])     # the two per-vintage options go together


def test_the_cut_proof_holds_in_per_vintage_mode():
    obs, panel = _obs(), panel_frame(n=600)
    by = {y: _obs() for y in range(2014, 2021)}
    a = nb.build_table(2020, panel, obs, lambda ocut: by[int(ocut[:4]) - 1])
    cut = a["cut_date"]

    def late(d):
        d = d.copy()
        for k in nt.KS:
            lo = d[f"filed_{k}"].astype(str) >= cut
            for c in (f"rev_{k}", f"tbv_{k}", f"m_{k}", f"rote_{k}", f"g_{k}", f"tg_{k}"):
                d.loc[lo, c] = d.loc[lo, c] * 3 + 7
        return d
    panel2 = panel.copy()
    for k in nt.KS:
        lp = panel2[f"filed_{k}"].astype(str) >= cut
        for c in (f"g_{k}", f"m_{k}", f"tg_{k}", f"rote_{k}"):
            panel2.loc[lp, c] = panel2.loc[lp, c] * 3 + 7
    by2 = {y: late(d) for y, d in by.items()}
    b = nb.build_table(2020, panel2, late(obs), lambda ocut: by2[int(ocut[:4]) - 1])
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)

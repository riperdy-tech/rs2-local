"""Check 4: the survival model (V2).  (i) refit each date's model with the stage-2 code and the frozen inputs and compare to the frozen coefficients; (ii) list the training labels: every
event date < T, the training dates t + 12m <= T; (iii) the evidence behind the failure events used as positive labels: how many have a filing dated on/after T (an event dated before T but
classified or confirmed by a filing that was not yet public); (iv) refit with only events whose EVERY evidence filing is before T, and recompute the registered bars with that P(fail)."""
import sys, json
import numpy as np, pandas as pd
from leak_audit import lib
from rebuild_harness.stage2 import survival as S, layers as L, devcheck as DC
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 199
fz = json.load(open(lib.GATE / "gate1b_freeze.json"))
td = fz["stage2"]["training_data"]
panel_q = pd.read_pickle(lib.WS / "scratch" / "rev23" / "forensics" / "analysis" / "panel_q20.pkl")
panel_q = L.add_dispersion(S.with_features(panel_q.reset_index(drop=True)))
pool = DC.training_pool(panel_q, DC.load_obs(lib.WS / "scratch" / "rev23" / "stage2_data" / "obs_pre2020"))
EV = lib.WS / "data" / "sec_bulk" / "index_P4b" / "events_all.json"
raw = json.load(open(EV))
events = S.load_fail_events(EV)
out = {"dates": {}}
frozen = fz["stage2"]["survival_coefficients"]
# evidence lookup: cik -> [(event date, max evidence date, min evidence date, class)]
fail = [e for e in raw if e["class"] in S.FAIL_CLASSES]
byc = {}
for e in fail:
    ev_dates = [x["date"] for x in e["evidence"]]
    byc.setdefault(str(e["cik"]).zfill(10), []).append((e["date"], max(ev_dates), min(ev_dates), e["class"], e["evidence"]))
models_strict = {}
for T in lib.DATES:
    m = S.fit_for_date(pool, T, events)
    fr = frozen[T]
    cdiff = max(abs(m.coef[i] - fr["coef"][k]) for i, k in enumerate(S.FEATURES))
    mask = S.training_mask(pool["date"], T)
    tr = pool[mask]
    y = np.array([S.label_failure(c, d, events, known_before=T) for c, d in zip(tr["cik"], tr["date"])])
    # independent label audit
    n_bad_event_date = 0
    n_post_evidence = 0
    n_post_evidence_in_last_quarter = 0
    pos_rows = tr[y == 1]
    used_events = set()
    for c, d in zip(pos_rows["cik"], pos_rows["date"]):
        lo, hi = pd.Timestamp(d), min(S.add_months(d), pd.Timestamp(T) - pd.Timedelta(days=1))
        for (edate, emax, emin, cls, evid) in byc.get(c, []):
            if lo < pd.Timestamp(edate) <= hi:
                used_events.add((c, edate))
                if pd.Timestamp(edate) >= pd.Timestamp(T):
                    n_bad_event_date += 1
    for (c, edate) in used_events:
        rec = [x for x in byc[c] if x[0] == edate][0]
        if pd.Timestamp(rec[1]) >= pd.Timestamp(T):
            n_post_evidence += 1
    # strict events: drop failure events with any evidence filing on/after T
    ev_strict = {}
    for c, lst in byc.items():
        ds = [np.datetime64(x[0]) for x in lst if pd.Timestamp(x[1]) < pd.Timestamp(T)]
        if ds:
            ev_strict[c] = np.sort(np.array(ds, dtype="datetime64[D]"))
    ms = S.fit_for_date(pool, T, ev_strict)
    models_strict[T] = ms
    out["dates"][T] = {"n_train": int(len(tr)), "n_events_label": int(y.sum()), "n_events_frozen": fr["n_events"], "max_train_date": str(tr["date"].max()), "max_train_date_plus_12m": str(S.add_months(tr["date"].max()).date()),
                       "train_end_ok": bool(S.add_months(tr["date"].max()) <= pd.Timestamp(T)), "coef_refit_max_abs_diff_vs_frozen": float(cdiff), "n_event_dates_ge_T_in_labels": n_bad_event_date,
                       "distinct_positive_events_used": len(used_events), "positive_events_with_an_evidence_filing_on_or_after_T": n_post_evidence,
                       "strict_refit_n_events": ms.n_events if ms else None, "strict_coef_max_abs_diff": (float(max(abs(ms.coef[i] - m.coef[i]) for i in range(len(m.coef)))) if ms else None)}
    print(T, out["dates"][T], flush=True)
# P(fail) strict and the bars
pan = lib.load_panel()
pan = L.add_dispersion(S.with_features(pan))
pan["pfail_strict"] = np.nan
for d, idx in pan.groupby("date").groups.items():
    pan.loc[idx, "pfail_strict"] = models_strict[d].predict(pan.loc[idx, list(S.FEATURES)].to_numpy(dtype=float))
pan["s_strict"] = L.v2_score(pan["vp_mean"], pan["pfail_strict"])
pan["s_nosurv"] = pan["vp_mean"]
out["pfail_corr_frozen_vs_strict"] = float(np.corrcoef(pan.pfail.fillna(0), pan.pfail_strict.fillna(0))[0, 1])
out["pfail_stats"] = {"mean": float(pan.pfail.mean()), "p99": float(pan.pfail.quantile(.99)), "max": float(pan.pfail.max())}
out["score_corr_with_without_survival"] = float(pan[["s_cfg", "s_nosurv"]].corr(method="spearman").iloc[0, 1])
rows = lib.load_rows(pan)
for lab, col in (("frozen s_cfg", "s_cfg"), ("strict events (all evidence < T)", "s_strict"), ("no survival layer (mean only)", "s_nosurv")):
    sc = lib.key_map(pan, col)
    res = lib.bars(rows, lambda r, sc=sc: sc.get(r["_k"]), n_boot=nb)
    out[lab] = res
    print(f"{lab:40s} {lib.fmt(res)}", flush=True)
lib.dump(out, "a12_survival_audit.json")

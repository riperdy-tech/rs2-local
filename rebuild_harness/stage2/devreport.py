"""Render the development check (`devcheck`) as markdown tables.

    python -m rebuild_harness.stage2.devreport DEVCHECK_DIR

Reads variants.json, survival_auc.json and survival_coefficients.json from the folder and writes report.md next to them."""
import json
import sys
from pathlib import Path

BOUNDS = ("excluded", "minus100", "last_close")
BL = {"excluded": "excluded", "minus100": "-100%", "last_close": "last close"}
CFG = "V1+V2+V3 mean x (1-P), commodity out (THE CONFIGURATION)"


def f(x, nd=3, pct=False, star=False):
    if x is None or x != x:
        return "n/a"
    s = f"{100 * x:+.{nd}f}" if pct else f"{x:+.{nd}f}"
    return s + ("*" if star else "")


def b1_row(m, key, sub_lower=False):
    cells = []
    for b in BOUNDS:
        c = m[b].get(key)
        if c is None:
            cells.append("n/a")
            continue
        lo = c.get("lower90")
        cells.append(f"{c['beta']:+.4f}" + (f" ({lo:+.4f})" if lo is not None else "") + f" t {c['t']:+.1f}")
    return cells


def b2_row(m, key):
    return [f(m[b][key]["spread_resid"], 2, pct=True, star=(m[b][key].get("spread_resid_lo", -1) or -1) > 0) + f" [{f(m[b][key].get('spread_resid_lo'), 1, pct=True)}, {f(m[b][key].get('spread_resid_hi'), 1, pct=True)}]" for b in BOUNDS]


def table(header, rows):
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def main(d):
    d = Path(d)
    var = json.loads((d / "variants.json").read_text(encoding="utf-8"))
    auc = json.loads((d / "survival_auc.json").read_text(encoding="utf-8"))
    co = json.loads((d / "survival_coefficients.json").read_text(encoding="utf-8"))
    L = ["# Stage 2, development check (Phase B)", ""]
    L += ["## Survival model: out-of-sample AUC (each date scored by the model fitted on data resolved before it)", ""]
    rows = [["pooled", auc["pooled"]["n"], auc["pooled"]["events"], f(auc["pooled"]["auc"], 3), f(auc["pooled"]["mean_p"], 4), f(auc["pooled"]["rate"], 4)]]
    for k in ("sub_2020_2022", "sub_2023_2024"):
        a = auc[k]
        rows.append([k, a["n"], a["events"], f(a["auc"], 3), f(a["mean_p"], 4), f(a["rate"], 4)])
    for y, a in auc["by_year"].items():
        rows.append([y, a["n"], a["events"], f(a["auc"], 3), f(a["mean_p"], 4), f(a["rate"], 4)])
    L += table(["period", "name-dates", "failures within 12m", "AUC", "mean predicted P", "realised rate"], rows) + ["", f"mean within-date AUC over the dates with a model: {f(auc['mean_within_date_auc'], 3)}", ""]
    L += ["### by date", ""] + table(["date", "n", "failures", "AUC", "mean P", "rate", "train events", "train n"],
                                     [[k, v["n"], v["events"], f(v["auc"], 3), f(v["mean_p"], 4), f(v["rate"], 4), (co.get(k) or {}).get("n_events"), (co.get(k) or {}).get("n_train")] for k, v in auc["by_date"].items()]) + [""]
    L += ["## Coefficients per date (standardised variables; intercept)", ""]
    feats = list(next(v for v in co.values() if v)["coef"])
    L += table(["date", "intercept"] + feats, [[k, f(v["intercept"], 2)] + [f(v["coef"][x], 2) for x in feats] for k, v in co.items() if v]) + [""]
    L += ["## The rule on the configuration", ""]
    r = var[CFG]["rule"]
    L += table(["condition", "result", "detail"], [["P1 B1 lower bound > 0, all dates, all bounds", r["P1_B1_lower_bound_positive_all_bounds"], r["P1_detail"]],
                                                   ["P2 B1 point > 0, each sub-period, all bounds", r["P2_B1_point_positive_each_subperiod_all_bounds"], r["P2_detail"]],
                                                   ["P3 B2 residual spread > 0, each sub-period, all bounds", r["P3_B2_positive_each_subperiod_all_bounds"], r["P3_detail"]],
                                                   ["P4 dispersion guard holds", r["P4_dispersion_guard_holds"], r["P4_detail"]], ["PASS", r["PASS"], ""]]) + [""]
    for lab, v in var.items():
        m = v["metrics"]
        L += [f"## {lab}", "", f"rows {m['n_rows']}, dates {m['n_dates']}; rule PASS = {v['rule']['PASS']}", ""]
        hd = ["B1 coefficient (lower 90% bound), t"] + [BL[b] for b in BOUNDS]
        rows = [["all 20 dates"] + b1_row(m, "B1_all"), ["2020-2022"] + b1_row(m, "B1_2020_2022"), ["2023-2024"] + b1_row(m, "B1_2023_2024"),
                ["all 20 dates, + dispersion control"] + b1_row(m, "B1_all_guard"), ["2020-2022, + control"] + b1_row(m, "B1_2020_2022_guard"), ["2023-2024, + control"] + b1_row(m, "B1_2023_2024_guard")]
        L += table(hd, rows) + [""]
        hd = ["B2 residual quintile spread, pp [90% block interval]"] + [BL[b] for b in BOUNDS]
        rows = [["all 20 dates"] + b2_row(m, "B2_all"), ["2020-2022"] + b2_row(m, "B2_2020_2022"), ["2023-2024"] + b2_row(m, "B2_2023_2024"),
                ["all 20 dates, + dispersion control"] + b2_row(m, "B2_all_guard"), ["2020-2022, + control"] + b2_row(m, "B2_2020_2022_guard"), ["2023-2024, + control"] + b2_row(m, "B2_2023_2024_guard")]
        L += table(hd, rows) + [""]
    (d / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1])

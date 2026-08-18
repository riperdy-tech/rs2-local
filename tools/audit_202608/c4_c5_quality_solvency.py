"""C4 + C5 — earnings-quality battery join and solvency screen vs published verdicts.

C4: joins the screener's fundamentals_battery.json (f_score, accruals_ratio, m_score,
net_issuance) - which RS2 never loads - against the published overlay verdicts. How many
current BULL-action names carry red flags RS2 never saw?

C5: computes leverage/coverage from ingested-but-unused fundamentals_history fields
(interest_expense, lt_debt, cash, ocf, operating_income) for the same population.

Flag thresholds (standard, stated):
  f_score <= 3 (of >=6 checks available)      - Piotroski low
  accruals_ratio >= +0.10                     - earnings far ahead of cash (Sloan-high)
  m_score > -1.78                             - Beneish elevated-manipulation zone
  net_issuance_1y >= +5%                      - active dilution
  interest coverage (op income / int exp) < 3 - thin coverage
  net_debt / ocf > 4 (ocf > 0)                - heavy leverage vs cash generation
  ocf <= 0 with net_debt > 0                  - burning cash while levered
"""
import common

common.enable_json_cache()
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402


def main():
    ov = common.overlay()
    bat = (rs2_data.load_json(common.SD / "fundamentals_battery.json") or {}).get("tickers") or {}

    rows = {}
    for t, v in ov.items():
        fam = common.action_family(v.get("action"))
        b = bat.get(t) or {}
        flags = []
        f, avail = b.get("f_score"), b.get("f_score_checks_available") or 0
        if f is not None and avail >= 6 and f <= 3:
            flags.append(f"f_score={f}/{avail}")
        acc = b.get("accruals_ratio")
        if isinstance(acc, (int, float)) and acc >= 0.10:
            flags.append(f"accruals={acc:+.3f}")
        m = b.get("m_score")
        if isinstance(m, (int, float)) and m > -1.78:
            flags.append(f"m_score={m:.2f}")
        iss = b.get("net_issuance_1y")
        if isinstance(iss, (int, float)) and iss >= 0.05:
            flags.append(f"issuance_1y={iss:+.1%}")

        solv = []
        h = vb._hist(t)
        if h:
            fy = h[str(max(int(y) for y in h.keys()))]
            oi, ie = vb._num(fy.get("operating_income")), vb._num(fy.get("interest_expense"))
            ltd, cash, ocf = (vb._num(fy.get("lt_debt")), vb._num(fy.get("cash")),
                              vb._num(fy.get("ocf")))
            nd = (ltd - cash) if (ltd is not None and cash is not None) else None
            if oi is not None and ie and ie > 0:
                cov = oi / ie
                if cov < 3:
                    solv.append(f"coverage={cov:.1f}x")
            if nd is not None and nd > 0 and ocf is not None:
                if ocf > 0 and nd / ocf > 4:
                    solv.append(f"net_debt/ocf={nd/ocf:.1f}x")
                elif ocf <= 0:
                    solv.append("ocf<=0_with_net_debt")
        rows[t] = {"family": fam, "conviction": v.get("conviction"),
                   "quality_flags": flags, "solvency_flags": solv,
                   "battery_present": bool(b), "history_present": bool(h)}

    fams = {}
    for t, r in rows.items():
        fams.setdefault(r["family"], []).append(t)

    def summarize(key):
        out = {}
        for fam, ts in sorted(fams.items()):
            flagged = {t: rows[t][key] for t in ts if rows[t][key]}
            out[fam] = {"n": len(ts), "n_flagged": len(flagged),
                        "flagged": {t: flagged[t] for t in sorted(flagged)}}
        return out

    common.save("c4_c5_quality_solvency", {
        "n_overlay": len(rows),
        "n_battery_missing": sum(1 for r in rows.values() if not r["battery_present"]),
        "n_history_missing": sum(1 for r in rows.values() if not r["history_present"]),
        "family_counts": {f: len(ts) for f, ts in sorted(fams.items())},
        "c4_quality_by_family": summarize("quality_flags"),
        "c5_solvency_by_family": summarize("solvency_flags"),
    })


if __name__ == "__main__":
    main()

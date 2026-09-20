"""C10 — CORRECTION of C3's SBC finding (2026-08-19).

C3 subtracted TTM SBC from every name's base_cf. That was WRONG for owner-earnings-derived
flows: GAAP net income already expenses SBC, and owner earnings (NI + D&A - capex) adds back
only D&A (verified against the screener builder: `da` maps to pure D&A XBRL tags;
`fcf` = ocf - capex where OCF carries the SBC add-back). C3 therefore DOUBLE-COUNTED SBC for
the owner-earnings population, and its 30-tier-flip headline is an artifact for those names.

The SBC adjustment is legitimate ONLY where base_cf derives from OCF/FCF:
  kinds: fcf_ttm_yf (yfinance Free_Cash_Flow_TTM), any FY-fcf fallback, ocf-da proxy.

This experiment measures the REAL population and impact:
  1. base_cf_kind census across the live book.
  2. For FCF-derived kinds only: SBC/base_cf ratio, gap move, tier flips.
"""
import common

common.enable_json_cache()
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402

# kinds whose flow embeds the OCF SBC add-back (SBC NOT expensed) vs NI-derived kinds
FCF_KINDS_SUBSTR = ("fcf", "ocf")


def main():
    book = common.book_tickers()
    census, rows = {}, {}
    for t in book:
        try:
            b = vb.backbone(t)
        except Exception:
            continue
        if not b.get("ok"):
            census[str(b.get("reason"))] = census.get(str(b.get("reason")), 0) + 1
            continue
        kind = str(b.get("base_cf_kind"))
        census[kind] = census.get(kind, 0) + 1
        if b.get("method") != "reverse_dcf":
            continue
        if not any(s in kind for s in FCF_KINDS_SUBSTR):
            continue
        fin = rs2_data.load_json(common.SD / "financials" / f"{t}.json") or {}
        sbc = vb._num(fin.get("SBC_Stock_Based_Comp"))
        if sbc is None:
            rows[t] = {"kind": kind, "sbc": None, "note": "no SBC datum"}
            continue
        cf = b["base_cf"]
        cf_adj = cf - abs(sbc)
        r = {"kind": kind, "sbc_over_cf": round(abs(sbc) / cf, 3), "gap_base": b.get("expectations_gap_pts")}
        if cf_adj > 0:
            implied = vb._solve_implied_growth(cf_adj, b["market_cap"], b["wacc"])
            demo = b.get("demonstrated_cagr")
            if implied is not None and demo is not None:
                r["gap_adj"] = round((implied - demo) * 100, 1)
                r["gap_move_pts"] = round(r["gap_adj"] - (r["gap_base"] or 0), 1)
        else:
            r["flow_turns_nonpositive"] = True
        rows[t] = r

    common.save("c10_sbc_correction", {
        "verified_premise": ("net_income is GAAP (SBC-expensed); da = pure D&A tags; "
                             "fcf = ocf - capex with OCF's SBC add-back "
                             "(build_fundamentals_history.py:75-83,414,601)"),
        "base_cf_kind_census": dict(sorted(census.items(), key=lambda kv: -kv[1])),
        "n_fcf_kind_names": len(rows),
        "fcf_kind_detail": rows,
        "conclusion": ("C3's uniform SBC subtraction was invalid for owner-earnings kinds "
                       "(double count). The legitimate SBC fix applies only to the names "
                       "listed here."),
    })


if __name__ == "__main__":
    main()

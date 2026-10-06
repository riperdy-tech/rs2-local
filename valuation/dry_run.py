"""dry_run.py - a plumbing check of classification + the three engines on live book names, with PLACEHOLDER priors and rates.

It prints and writes ONLY whether each step ran and which family was assigned. It never prints a valuation figure, because the priors and
the rates are placeholders (round numbers, not measurements): a figure from this run would be a number to be believed by mistake.

    python -m valuation.dry_run --asof 2026-10-06 [--census] [--out path.json]

Reads (read-only) the screener's companyfacts files and the live rs2-local submissions cache; SEC submissions missing from that cache are
fetched with the repo's own helper (sec_primary: <= 10 requests per second) into this tree's gitignored cache/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import paths
from . import classification, common, engine_commodity, engine_financial, engine_operating
from .discount_rate import PlaceholderRates, discount_rate_for_state
from .pit_companyfacts import CompanyFactsSource
from .priors_interface import PlaceholderPriors


def book_names():
    """The latest membership snapshot's `in` list (cache/depth_membership.jsonl of the live rs2-local tree, read only)."""
    p = paths.stocks_root() / "rs2-local" / "cache" / "depth_membership.jsonl"
    if not p.exists():
        p = paths.HERE / "cache" / "depth_membership.jsonl"
    last = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = json.loads(line)
    return sorted(last["in"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-10-06")
    ap.add_argument("--census", action="store_true", help="classify the whole book and report the balance-sheet test shares (no valuation)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-family", default="4,3,3", help="operating,commodity,financial names to run the engines on")
    a = ap.parse_args(argv)
    live_subs = paths.stocks_root() / "rs2-local" / "cache" / "sec_submissions"
    src = CompanyFactsSource(submissions_dirs=[live_subs, paths.HERE / "cache" / "sec_submissions"], allow_network=True)
    names = book_names()
    want = dict(zip(("operating", "commodity", "financial"), (int(x) for x in a.per_family.split(","))))
    got = {k: [] for k in want}
    census, runs = [], []
    pr, rates = PlaceholderPriors(True), PlaceholderRates(True)
    for t in names:
        try:
            pit = src.load(t, a.asof)
        except Exception as e:                        # a missing file or CIK is a result, not a crash
            census.append({"ticker": t, "family": None, "load_error": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        c = classification.classification(t, a.asof, pit)
        census.append({"ticker": t, "family": c["family"], "reason": c["reason"], "conflicts": c["conflicts"],
                       "insurance_reserve_share": c["tests"]["insurance_reserve_share"], "lending_book_share": c["tests"]["lending_book_share"],
                       "not_evaluated": len(c["tests"]["not_evaluated"])})
        fam = c["family"]
        if fam in got and len(got[fam]) < want[fam] and not a.census:
            got[fam].append(t)
            row = {"ticker": t, "family": fam}
            try:
                st = common.build_state(pit)
                disc = discount_rate_for_state(st, a.asof, industry="placeholder", rf_provider=rates.rf, beta_provider=rates.beta,
                                               erp_provider=rates.erp, placeholder=True)
                mod = {"operating": engine_operating, "commodity": engine_commodity, "financial": engine_financial}[fam]
                r = mod.run(pit, pr, disc, n_draws=200, seed=1)
                row["engine_status"] = r["status"]
                if r["status"] != "ok":
                    row["reasons"] = r["reasons"]
                else:
                    row["placeholder_flag"] = r["placeholder"]
                    row["secondary_present"] = r["model_disagreement"] is not None
                    row["invalid_draw_share"] = round(r["distribution"]["n_invalid"] / r["distribution"]["n_draws"], 3)
            except Exception as e:
                row["engine_status"] = f"{type(e).__name__}: {str(e)[:160]}"
            runs.append(row)
        if not a.census and all(len(got[k]) >= want[k] for k in want):
            break
    out = {"asof": a.asof, "runs": runs}
    if a.census:
        out["census"] = census
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

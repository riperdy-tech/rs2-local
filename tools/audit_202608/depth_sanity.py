#!/usr/bin/env python3
"""depth_sanity.py — audit ONE depth verdict the moment it lands.

Operator instruction (2026-08-24): the per-ticker watcher must check the sanity of the report and
the result, not just print the verdict.

Written because the first 24 verdicts lost 10 of 72 samples and NOBODY NOTICED until the whole
book was inspected at once. Of those 10, only 2 were the model failing (one empty report, one
truncation); 3 were my IV parser not recognising a phrasing the report stated plainly, and 5 were
plausibility-guard rejections. A lost sample narrows the IV band, and a narrower band converts
`hold` into a directional buy/sell call - so silent sample loss biases what gets published.

Checks, in severity order:

  FAIL  no usable sample, or the published direction disagrees with the band it was computed from
  FAIL  a sample scored "no value extracted" while the report DOES state a value the current
        patterns can find - i.e. a parser miss that cost a real vote (this is how ATI, AZN and
        CIEN each lost one)
  WARN  fewer than 3 usable samples, with the cause named per sample
  WARN  degenerate band (single surviving sample, so the band is a point and the spread is
        unknowable) - ATI published exactly this and nothing on the page said so
  WARN  empty or stub report, truncation at the output cap
  WARN  every surviving sample on one side of the price by a wide margin while a rejected sample
        agreed - the guard removed an opinion, not a malfunction
  INFO  spread, band, direction, per-sample durations

Exit 0 = clean, 1 = warnings, 2 = failures. The watcher prints whatever it returns.

  python tools/audit_202608/depth_sanity.py ATI
  python tools/audit_202608/depth_sanity.py --all      # sweep every published verdict
"""
import io
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
# NOTE: no sys.stdout wrapper here on purpose. consensus_valuation installs its own utf-8
# TextIOWrapper at import time; wrapping the same buffer a second time means whichever wrapper is
# collected first closes the buffer out from under the other, and every print then raises
# "I/O operation on closed file". Importing it is enough to get utf-8 output.
from consensus_valuation import extract_iv  # noqa: E402

LEDGER = HERE / "cache" / "depth_ledger.jsonl"
CONS = HERE / "ab_reports" / "consensus"
STUB_CHARS = 5000        # below this a "report" is a stub, not a deliverable


def newest_verdicts():
    out = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                out[v["ticker"]] = v
            except Exception:
                continue
    return out


def audit(ticker, verdict):
    """-> (level, [lines]) where level is 0 clean / 1 warn / 2 fail."""
    L, level = [], 0

    def note(sev, msg):
        nonlocal level
        level = max(level, sev)
        L.append(f"  {'FAIL' if sev == 2 else 'WARN' if sev == 1 else 'info'}  {msg}")

    d = CONS / (verdict.get("consensus_dir") or "")
    doc = {}
    if (d / "consensus.json").exists():
        doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    price = verdict.get("price")
    lo, hi = verdict.get("iv_band_low"), verdict.get("iv_band_high")
    direction = verdict.get("direction")
    n = verdict.get("n_basis") or 0

    L.append(f"{ticker}: {direction.upper()} | band ${lo}-${hi} vs ${price} | "
             f"n_basis {n} | spread {verdict.get('spread_pct')}% | size {verdict.get('size_hint')}")

    # --- the verdict must follow from its own band -------------------------------------------
    if lo is not None and hi is not None and price:
        expect = "overvalued" if price > hi else "undervalued" if price < lo else "hold"
        if expect != direction:
            note(2, f"direction '{direction}' contradicts its band: price ${price} vs "
                    f"${lo}-${hi} implies '{expect}'")
    elif direction != "NOT_USABLE":
        note(2, "no band, but a direction was published")

    # --- sample accounting -------------------------------------------------------------------
    runs = doc.get("runs") or []
    if not runs:
        note(1, "consensus.json missing — cannot audit samples")
    # A sample that raised before producing a result never gets a runs[] entry, so counting only
    # recorded runs makes it invisible. EXPE published on ONE sample and the audit reported only
    # the point band, because samples 2 and 3 died with HTTP 400 and left no trace here.
    intended = 3
    if runs and len(runs) < intended:
        note(2, f"only {len(runs)} of {intended} samples produced ANY result — "
                f"{intended - len(runs)} raised before recording. Check the sweep log for "
                f"'sample N: FAILED'; these are invisible in consensus.json.")
    lost = []
    for r in runs:
        usable = r.get("iv") and r.get("plausible") and not r.get("truncated")
        sp = d / f"sample{r['sample']}.md"
        body = sp.read_text(encoding="utf-8", errors="replace") if sp.exists() else ""
        if usable:
            if len(body) < STUB_CHARS:
                note(1, f"sample {r['sample']} counted as usable but its report is only "
                        f"{len(body):,} chars — a stub, not a deliverable")
            continue
        reasons = " ".join(r.get("reasons") or [])
        if r.get("truncated"):
            lost.append((r["sample"], "truncated at the output cap"))
        elif not body.strip():
            lost.append((r["sample"], f"EMPTY report after {r.get('thinking_chars', 0):,} chars "
                                      f"of thinking"))
        elif "no value extracted" in reasons:
            found = extract_iv(body, price)
            if found:
                note(2, f"sample {r['sample']} PARSER MISS — the report states "
                        f"${st.median(found):,.2f} but the run scored 'no value extracted'. "
                        f"A real vote was discarded by our code, not by the model.")
                lost.append((r["sample"], "parser miss (recoverable)"))
            else:
                lost.append((r["sample"], "report states no value anywhere"))
        else:
            lost.append((r["sample"], f"guard: {reasons[:90]}"))

    if lost:
        note(1, f"{len(lost)} of {len(runs)} samples lost:")
        for s, why in lost:
            L.append(f"          sample {s}: {why}")

    # --- degenerate band ---------------------------------------------------------------------
    if n == 1:
        note(1, "single surviving sample — the band is a POINT, so the published spread is "
                "unknowable and the size hint rests on one opinion")
    elif n == 2:
        note(1, "two surviving samples — band is ~1/3 narrower than a 3-sample band would be, "
                "which biases the verdict toward a directional call over 'hold'")

    # --- did the guard remove an opinion that agreed with the survivors? ---------------------
    rejected = [r for r in runs if r.get("iv") and not r.get("plausible")]
    if rejected and lo is not None and price:
        for r in rejected:
            same_side = (r["iv"] < price and hi < price) or (r["iv"] > price and lo > price)
            if same_side:
                note(1, f"sample {r['sample']} (${r['iv']}) was guard-rejected but agreed with "
                        f"the survivors on DIRECTION — the guard removed an opinion, not a "
                        f"malfunction")
    return level, L


def main():
    verdicts = newest_verdicts()
    if "--all" in sys.argv:
        targets = sorted(verdicts)
    else:
        # .strip() is load-bearing: piped from a shell on Windows the ticker arrives as "EXPE\r",
        # which prints identically to "EXPE" but matches nothing, so the audit silently reported
        # "no verdict on file" for a verdict that was sitting right there in the ledger.
        args = [a.strip() for a in sys.argv[1:] if not a.startswith("--") and a.strip()]
        targets = [args[0].upper()] if args else [max(verdicts, key=lambda t: verdicts[t]["date"])]
    worst = 0
    for t in targets:
        v = verdicts.get(t)
        if not v:
            print(f"{t}: no verdict on file")
            worst = max(worst, 1)
            continue
        lvl, lines = audit(t, v)
        worst = max(worst, lvl)
        print("\n".join(lines))
        print(f"  -> {'FAIL' if lvl == 2 else 'WARN' if lvl == 1 else 'CLEAN'}\n")
    return worst


if __name__ == "__main__":
    sys.exit(main())

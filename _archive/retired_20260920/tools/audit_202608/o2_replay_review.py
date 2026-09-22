"""O2 rollout guardrail — full-book side-by-side replay: pre-change vs post-change backbone.

Pre-change = the backbone as committed at the Option-1 commits (git show d33906d:...), which
has neither the SBC adjustment, nor the CoE anchor, nor the comps fields. Post-change = the
working tree with both calibrations built. Emits audit/O2_replay_review.{json,md}: every
name whose published fields (kind / rate / gap / MoS / brake tier) change, for human review
before sweeps resume.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import common

common.enable_json_cache()
import valuation_backbone as vb_new  # noqa: E402

OLD_SRC = common.RESULTS.parent.parent / "tools" / "audit_202608" / "_vb_old_snapshot.py"


def load_old():
    src = subprocess.run(["git", "show", "d33906d:valuation_backbone.py"],
                         cwd=common.ROOT, capture_output=True, text=True,
                         encoding="utf-8").stdout
    OLD_SRC.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("vb_old", OLD_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tier(m, p33, p75):
    if m is None or p33 is None:
        return "uncovered"
    return "chase_ok" if m >= p75 else ("stage" if m >= p33 else "no_chase")


def cuts(rows):
    vals = sorted(v["mos"] for v in rows.values() if isinstance(v.get("mos"), (int, float)))
    return common.percentile(vals, 33), common.percentile(vals, 75), vals


def snap(mod, t):
    try:
        b = mod.backbone(t)
    except Exception as e:
        return {"ok": False, "reason": f"exc:{e}"}
    if not b.get("ok"):
        return {"ok": False, "reason": b.get("reason")}
    return {"ok": True, "kind": b.get("base_cf_kind"), "wacc": b.get("wacc_pct"),
            "gap": b.get("expectations_gap_pts"), "mos": b.get("mos_pct"),
            "fv": b.get("fair_value"), "comps": b.get("comps_signal")}


def main():
    vb_old = load_old()
    book = common.book_tickers()
    old, new = {}, {}
    for t in book:
        old[t] = snap(vb_old, t)
        new[t] = snap(vb_new, t)
    o33, o75, _ = cuts(old)
    n33, n75, nvals = cuts(new)

    changes = []
    for t in book:
        o, n = old[t], new[t]
        ot = tier(o.get("mos"), o33, o75)
        nt = tier(n.get("mos"), n33, n75)
        delta = {}
        if o.get("kind") != n.get("kind"):
            delta["kind"] = [o.get("kind"), n.get("kind")]
        if o.get("ok") != n.get("ok"):
            delta["ok"] = [o.get("ok"), n.get("ok"), n.get("reason") or o.get("reason")]
        og, ng = o.get("gap"), n.get("gap")
        if og is not None and ng is not None and abs(ng - og) >= 1.0:
            delta["gap"] = [og, ng]
        if ot != nt:
            delta["tier"] = [ot, nt]
        if delta:
            changes.append({"ticker": t, **delta})

    tier_flips = [c for c in changes if "tier" in c]
    kind_changes = [c for c in changes if "kind" in c]
    doc = {
        "old_ref": "d33906d (Option 1 commits)",
        "book_n": len(book),
        "coe_calibration": json.loads((common.ROOT / "cache" / "coe_calibration.json").read_text(encoding="utf-8")),
        "old_cuts": {"p33": o33, "p75": o75}, "new_cuts": {"p33": n33, "p75": n75},
        "new_mos_percentiles": {p: common.percentile(nvals, p) for p in (10, 25, 33, 50, 67, 75, 90)},
        "n_changed": len(changes), "n_tier_flips": len(tier_flips),
        "n_kind_changes": len(kind_changes),
        "changes": changes,
    }
    common.save("o2_replay_review", doc)

    md = ["# O2 Replay Review — pre vs post (SBC + CoE anchor + comps)", "",
          f"Book n={len(book)} | old ref d33906d | implied CoE "
          f"{doc['coe_calibration']['implied_coe_pct']}% -> offset "
          f"{doc['coe_calibration']['level_offset_pts']:+}pts", "",
          f"Brake cuts: old p33 {o33} / p75 {o75}  ->  new p33 {n33} / p75 {n75}", "",
          f"**{len(changes)} names changed** ({len(tier_flips)} brake-tier flips, "
          f"{len(kind_changes)} base_cf-kind changes). Sweeps are PAUSED; review before resuming.", "",
          "| Ticker | kind | gap (pts) | tier | note |", "|---|---|---|---|---|"]
    for c in sorted(changes, key=lambda c: -abs(c.get("gap", [0, 0])[1] - c.get("gap", [0, 0])[0]) if c.get("gap") else 0):
        k = " -> ".join(map(str, c["kind"])) if "kind" in c else ""
        g = f"{c['gap'][0]} -> {c['gap'][1]}" if "gap" in c else ""
        tr = " -> ".join(c["tier"]) if "tier" in c else ""
        note = ("valuation route changed: " + str(c["ok"])) if "ok" in c else ""
        md.append(f"| {c['ticker']} | {k} | {g} | {tr} | {note} |")
    (common.RESULTS.parent / "O2_replay_review.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"changed {len(changes)} | tier flips {len(tier_flips)} | kinds {len(kind_changes)}")


if __name__ == "__main__":
    main()

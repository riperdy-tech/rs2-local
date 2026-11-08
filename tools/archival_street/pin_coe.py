"""pin_coe.py - S1-1 (WO_street_S1_build deliverable 2): the pinned cost-of-equity set of the Qwen-versus-analysts test at T 2026-06-15.

    python tools/archival_street/pin_coe.py --workbook <ERPbymonth.xlsx> [--mri-asof 2026-06-15] [--erp-month 2026-06-01] [--out DIR]

Writes <books>/m3o/value/archival_2026-06-15/coe_pinned/ (never over an existing directory):
 cost_of_capital_anchor.json, long_run_growth_anchor.json  the model_dump of MRI's two anchors from
     macro_engine.anchors.service.build_anchors(as_of=<mri-asof>, write=False), run in MRI's own interpreter from its repository root
     (paths.py mri_dir). write=False is fixed here: write=True would overwrite MRI's live anchors and its anchor_runs table.
 external_premium.json  {"erp", "asof", "source", "source_sha256"}: Damodaran's monthly implied ERP, sheet "Historical ERP", the row whose
     "Start of month" is <erp-month>, column "ERP (T12m)" (operator-approved for this test: the reference closure cannot be rebuilt for
     June). The workbook is untrusted data, read with pandas/openpyxl only; its sha256 is recorded.
 manifest.json  {"premium": "external", "files": {name: {sha256, asof}}, sources, the MRI build's scoring mode and input dates}.
qwen_c/value/coe.py's archival mode (RS2_ARCHIVAL_COE_DIR) reads the set and checks every sha256 on every call.

STOPS (exit 2, nothing written): either anchor degraded (coe.py would refuse the growth anchor; a degraded cost-of-capital anchor is not
pinned either); an anchor's asof, an input date of its provenance, or the premium's month after T; the workbook row or value absent or
outside the closure's bounds.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import paths  # noqa: E402

PIN_VERSION = "s1.pin_coe.v1"
T_DATE = "2026-06-15"
def out_for(t_date, tag=""):
    """<books>/m3o/value/archival_<T><tag>/coe_pinned (S1b, 2026-11-09: T 2025-10-01 pins into a new archival_2025-10-01_pit set)."""
    return book_paths.books() / "m3o" / "value" / f"archival_{t_date}{tag}" / "coe_pinned"
SHEET, MONTH_COL, ERP_COL = "Historical ERP", "Start of month", "ERP (T12m)"
ERP_BOUNDS = (0.0005, 0.20)                     # rs2_data.reference_closure's bounds, which coe.external_premium applies
ANCHORS = (("cost_of_capital", "cost_of_capital_anchor.json"), ("long_run_growth", "long_run_growth_anchor.json"))
# Run in MRI's interpreter; prints one JSON object. write=False is literal here, never a parameter.
MRI_CODE = """
import json, sys
from macro_engine.anchors.service import build_anchors
b = build_anchors(as_of=sys.argv[1], write=False)
print(json.dumps({"asof": b.asof, "scoring_mode": b.scoring_mode, "degraded": b.degraded,
                  "cost_of_capital": b.cost_of_capital.model_dump(mode="json"),
                  "long_run_growth": b.long_run_growth.model_dump(mode="json")}))
"""


class Stop(Exception):
    """A condition under which nothing is pinned."""


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True).encode("utf-8")


def mri_build(mri_dir, asof):
    """The bundle's two anchors as JSON-mode dicts, from MRI's own interpreter at its repository root."""
    py = Path(mri_dir) / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise Stop(f"MRI interpreter not found at {py}")
    r = subprocess.run([str(py), "-c", MRI_CODE, asof], cwd=str(mri_dir), capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise Stop(f"MRI build_anchors(as_of={asof}, write=False) failed: {r.stderr[-800:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def check_anchors(bundle, t_date):
    """[problem, ...] for the two anchors against T: degraded, asof after T, a provenance input date after T, a missing consumed field."""
    out = []
    for key, _ in ANCHORS:
        a = bundle.get(key) or {}
        if a.get("degraded"):
            out.append(f"{key}: degraded ({'; '.join((a.get('provenance') or {}).get('degradation_reasons') or [])})")
        if not a.get("asof") or a["asof"] > t_date:
            out.append(f"{key}: asof {a.get('asof')} is after T {t_date} or missing")
        for s, d in sorted(((a.get("provenance") or {}).get("input_dates") or {}).items()):
            if str(d)[:10] > t_date:
                out.append(f"{key}: input {s} dated {d}, after T {t_date}")
    coc, lrg = bundle.get("cost_of_capital") or {}, bundle.get("long_run_growth") or {}
    rf = (coc.get("risk_free") or {}).get("nominal_10y")
    if not (isinstance(rf, (int, float)) and rf > 0):
        out.append("cost_of_capital: no risk_free.nominal_10y")
    if not (isinstance(coc.get("sector_loadings"), dict) and coc["sector_loadings"]):
        out.append("cost_of_capital: no sector_loadings")
    if not isinstance(lrg.get("terminal_g_suggestion"), (int, float)):
        out.append("long_run_growth: no terminal_g_suggestion")
    return out


def erp_at(rows, month):
    """The ERP (T12m) of the row whose Start of month is `month` (ISO date), from rows of {column: value}; Stop when absent, not a finite
    number, or outside ERP_BOUNDS. Exactly one row must match."""
    hits = [r for r in rows if str(r.get(MONTH_COL))[:10] == month]
    if len(hits) != 1:
        raise Stop(f"{len(hits)} rows of sheet {SHEET!r} have {MONTH_COL} {month}; exactly one is required")
    v = hits[0].get(ERP_COL)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise Stop(f"{ERP_COL} at {month} is {v!r}, not a number")
    if not ERP_BOUNDS[0] <= v <= ERP_BOUNDS[1]:
        raise Stop(f"{ERP_COL} at {month} is {v}, outside {ERP_BOUNDS}")
    return float(v)


def workbook_rows(path):
    import pandas as pd
    df = pd.read_excel(path, sheet_name=SHEET, header=0)
    if MONTH_COL not in df.columns or ERP_COL not in df.columns:
        raise Stop(f"sheet {SHEET!r} lacks {MONTH_COL!r} or {ERP_COL!r}: {list(df.columns)}")
    return [{MONTH_COL: (r[MONTH_COL].date().isoformat() if hasattr(r[MONTH_COL], "date") else r[MONTH_COL]), ERP_COL: r[ERP_COL]}
            for _, r in df.iterrows()]


def premium_doc(erp, month, wb_name, wb_sha):
    return {"erp": erp, "asof": month, "source": f"Damodaran monthly implied ERP, {wb_name}, sheet {SHEET!r}, {MONTH_COL} {month}, "
            f"column {ERP_COL!r}", "source_sha256": wb_sha}


def manifest(blobs, bundle, mri_asof, mri_commit, wb_path, wb_sha, month, t_date):
    asofs = {f: bundle[k]["asof"] for k, f in ANCHORS}
    asofs["external_premium.json"] = month
    return {"version": PIN_VERSION, "premium": "external", "T": t_date,
            "purpose": f"Qwen-versus-analysts test at T {t_date} only (WO_street_S1_build; S1b PREREG_s1b_street_k2). Operator: Damodaran's "
                       "published premium replaces the reference closure for this test.",
            "files": {f: {"sha256": sha(b), "asof": asofs[f]} for f, b in sorted(blobs.items())},
            "sources": {"anchors": f"macro-regime-indicator build_anchors(as_of={mri_asof}, write=False) at commit {mri_commit}",
                        "external_premium": {"workbook": Path(wb_path).name, "sha256": wb_sha, "sheet": SHEET, "row": month,
                                             "column": ERP_COL}},
            "mri": {"asof": bundle["asof"], "scoring_mode": bundle["scoring_mode"], "degraded": bundle["degraded"],
                    "input_dates": {k: (bundle[k].get("provenance") or {}).get("input_dates") for k, _ in ANCHORS}},
            "not_read_by_coe": "the cost-of-capital anchor's implied_erp, implied_cost_of_equity, equity_aggregate and erp_percentile "
                               "come from MRI's current equity aggregate file (not point in time); coe.py reads only risk_free.nominal_10y, "
                               "sector_loadings, asof and degraded of it"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workbook", required=True, help="Damodaran's ERPbymonth.xlsx")
    ap.add_argument("--mri-asof", default=T_DATE)
    ap.add_argument("--erp-month", default="2026-06-01")
    ap.add_argument("--t", default=T_DATE, help="the test date T (S1 2026-06-15, S1b 2025-10-01)")
    ap.add_argument("--out", default=None, help="default out_for(T)")
    a = ap.parse_args(argv)
    t_date = date.fromisoformat(a.t).isoformat()
    out = Path(a.out) if a.out else out_for(t_date)
    try:
        if out.exists():
            raise Stop(f"{out} exists; a pinned set is never overwritten")
        for d in (a.mri_asof, a.erp_month):
            if date.fromisoformat(d).isoformat() > t_date:
                raise Stop(f"{d} is after T {t_date}")
        mri_dir = paths.resolve("mri_dir")
        mri_commit = subprocess.run(["git", "-C", str(mri_dir), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        bundle = mri_build(mri_dir, a.mri_asof)
        problems = check_anchors(bundle, t_date)
        if problems:
            raise Stop("MRI anchors not pinnable:\n  " + "\n  ".join(problems))
        wb = Path(a.workbook)
        wb_sha = sha(wb.read_bytes())
        erp = erp_at(workbook_rows(wb), a.erp_month)
    except Stop as e:
        print("STOP:", e)
        return 2
    blobs = {f: dump(bundle[k]) for k, f in ANCHORS}
    blobs["external_premium.json"] = dump(premium_doc(erp, a.erp_month, wb.name, wb_sha))
    m = dump(manifest(blobs, bundle, a.mri_asof, mri_commit, wb, wb_sha, a.erp_month, t_date))
    out.mkdir(parents=True)
    for f, b in blobs.items():
        (out / f).write_bytes(b)
    (out / "manifest.json").write_bytes(m)
    print(json.dumps({"out": str(out), "manifest_sha256": sha(m), "erp": erp, "workbook_sha256": wb_sha,
                      "rf": bundle["cost_of_capital"]["risk_free"]["nominal_10y"],
                      "g": bundle["long_run_growth"]["terminal_g_suggestion"],
                      "input_dates": {k: bundle[k]["provenance"]["input_dates"] for k, _ in ANCHORS}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

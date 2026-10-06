"""Backtest registration section 9, "Data freeze": the sha256 of everything the run rests on, recorded before Look 1.

  python -m backtest_phase2.freeze --bt-root <SP\\backtest> --zip <companyfacts.zip> --sector-proxy <sector_proxy_prices.csv>

Writes <bt-root>/out/prelook/data_freeze.json.  The 167-name list is hashed, never read into any output.
"""
import argparse
import json
import subprocess
from pathlib import Path

from .checks import sha256
from .common import DATES, REGISTRATION_SHA256

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(["git", *args], cwd=HARNESS_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt-root", required=True, type=Path)
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--sector-proxy", required=True, type=Path)
    a = ap.parse_args(argv)
    r = a.bt_root
    f = {}
    f["companyfacts.zip"] = sha256(a.zip)
    f["registration_LOCKED_d09bb4a4.md"] = sha256(r / "registration_LOCKED_d09bb4a4.md")
    assert f["registration_LOCKED_d09bb4a4.md"] == REGISTRATION_SHA256
    f["registration_amendments_A1-A3.md"] = sha256(r / "registration_amendments_A1-A3.md")
    assert f["registration_amendments_A1-A3.md"] == "a8c9ba23f65006dbf098567ea097a775d6965ea43465f196242505feb01fd930"
    f["extractor_build_fundamentals_history.py (byte-identical copy)"] = sha256(r / "pit" / "extractor" / "build_fundamentals_history.py")
    f["prices_monthly_raw.json"] = sha256(r / "prices" / "prices_monthly_raw.json")
    f["sector_proxy_prices.csv"] = sha256(a.sector_proxy)
    f["s1_calibration.json"] = sha256(r / "s1_calibration.json")
    f["untouched167.txt (excluded; never printed)"] = sha256(r / "untouched" / "untouched167.txt")
    f["mri/pit_anchors.json (the MRI artifact)"] = sha256(r / "mri" / "pit_anchors.json")
    f["mri/coe_mkt_B.json"] = sha256(r / "mri" / "coe_mkt_B.json")
    f["mri/pit_anchors.py (the MRI script)"] = sha256(r / "mri" / "pit_anchors.py")
    for name in ("cut_zips.py", "run_extractor.py", "prepare_universe.py", "verify_cut.py"):
        f[f"harness pit_build/{name} (as committed)"] = sha256(HARNESS_ROOT / "backtest_phase2" / "pit_build" / name)
    for name in ("stocks_ex167.json", "labels.json"):
        f[f"pit/universe/{name}"] = sha256(r / "pit" / "universe" / name)
    for y in DATES:
        f[f"H({y}) fundamentals_history.json"] = sha256(r / "pit" / f"H_{y}" / "fundamentals_history.json")
        f[f"H_census({y}) fundamentals_history.json"] = sha256(r / "pit" / f"Hc_{y}" / "fundamentals_history.json")
    cut = {}
    for zp in sorted((r / "pit" / "cut").glob("cut_*.zip")):
        cut[zp.name] = sha256(zp)
    for sp in sorted((r / "pit" / "cut").glob("side_*.json")):
        cut[sp.name] = sha256(sp)
    inputs = {p.name: sha256(p) for p in sorted((r / "out" / "inputs").glob("*")) if p.is_file() and p.suffix in (".pkl", ".json")}
    out = {"harness_commit": git("rev-parse", "HEAD"), "harness_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
           "look_files_at_freeze": {f"AUTHORISED_LOOK_{n}.txt": (r / f"AUTHORISED_LOOK_{n}.txt").exists() for n in (1, 2)},
           "harness_tree_clean": git("status", "--porcelain", "--", "backtest_phase2") == "",
           "revisions": {"baseline": "fee17cf", "candidate": "ac68e25"}, "files": f, "cut_archives": cut, "built_inputs": inputs}
    (r / "out" / "prelook" / "data_freeze.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("cut_archives", "built_inputs")}, indent=1))


if __name__ == "__main__":
    main()

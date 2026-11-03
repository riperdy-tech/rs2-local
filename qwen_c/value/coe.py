"""coe.py - the code-owned cost of equity of 3Q (SPEC_m3q §2), the revision-18 anchor ported from capability_test (rev 26):

    COE = max(rf, g_anchor) + adjusted sector loading x closure ERP

rf: rs2_data.anchor_risk_free_rate (MRI); g_anchor: rs2_data.anchor_terminal_g; the Blume-adjusted loading: rs2_data.coe_loading(sector);
the closure premium: rs2_data.reference_closure (rs2's market-consistent ERP; no fallback to MRI's premium). Every leg must exist, or the
cost of equity is refused by name. Point in time: a leg dated after T is refused unless allow_after_T (the E2 regression on consumed
dates only), and then stamped `anchor_after_T`.

THE ARCHIVAL MODE (J2 v0.2 section 7 item 1; OFF unless selected). Selected only by a non-empty environment variable RS2_ARCHIVAL_COE_DIR
naming a pinned directory that holds copies of every leg - cost_of_capital_anchor.json (rf, the sector loading), long_run_growth_anchor.json
(g_anchor) and reference_closure.json (the premium) - and manifest.json, {"files": {name: {"sha256": ...}}} for at least those three. Every
listed file is hashed on every call; a missing manifest, a missing required file or a sha256 that does not match REFUSES
(coe_archival_unreadable / coe_archival_sha256_mismatch). In that mode, and only there, the after-T check and the 45-day age checks (the
anchors' and the closure's) are skipped; every other rule of the live accessors holds (the same fields, the degraded growth anchor refused,
the closure's publish rules). The provenance then carries the stamp `coe_archival_pinned` and `archival` = {dir, manifest_sha256, files}.
Without the variable nothing here changes.
"""
import hashlib
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path

import rs2_data
from qwen_c.value.desk import DeskRefusal

COE_VERSION = "m3q.coe.v1"
ARCHIVAL_VERSION = "m3q.coe.archival.v1"
ARCHIVAL_ENV = "RS2_ARCHIVAL_COE_DIR"
ARCHIVAL_STAMP = "coe_archival_pinned"
ARCHIVAL_FILES = ("cost_of_capital_anchor.json", "long_run_growth_anchor.json", "reference_closure.json")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def closure_path():
    """The closure artifact of this repository's main checkout (a worktree shares its git directory; the artifact is untracked cache)."""
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=Path(__file__).resolve().parent, text=True).strip()
    root = (Path(__file__).resolve().parent / common).resolve().parent if not Path(common).is_absolute() else Path(common).resolve().parent
    return root / "cache" / "reference_closure.json"


def _asof(src):
    m = _DATE.findall(str(src or ""))
    return date.fromisoformat(m[-1]) if m else None


def archival_dir():
    """The pinned directory when the archival mode is selected (a non-empty RS2_ARCHIVAL_COE_DIR), else None."""
    v = os.environ.get(ARCHIVAL_ENV, "").strip()
    return Path(v) if v else None


def _pinned(d):
    """({file: bytes}, manifest sha256, {file: sha256}) of the pinned directory, every listed file rechecked; else DeskRefusal."""
    try:
        mbytes = (d / "manifest.json").read_bytes()
        files = json.loads(mbytes)["files"]
        want = {f: (v["sha256"] if isinstance(v, dict) else None) for f, v in files.items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise DeskRefusal("coe_archival_unreadable", f"{ARCHIVAL_ENV}={d}: no readable manifest.json with files.<name>.sha256 ({e})") from None
    missing = [f for f in ARCHIVAL_FILES if not want.get(f)]
    if missing:
        raise DeskRefusal("coe_archival_unreadable", f"{ARCHIVAL_ENV}={d}: the manifest lists no sha256 for {missing}")
    blobs = {}
    for f, sha in sorted(want.items()):
        try:
            b = (d / f).read_bytes()
        except OSError as e:
            raise DeskRefusal("coe_archival_unreadable", f"{ARCHIVAL_ENV}={d}: {f} unreadable ({e})") from None
        got = hashlib.sha256(b).hexdigest()
        if got != sha:
            raise DeskRefusal("coe_archival_sha256_mismatch", f"{ARCHIVAL_ENV}={d}: {f} hashes to {got}, the manifest pins {sha}")
        blobs[f] = b
    return blobs, hashlib.sha256(mbytes).hexdigest(), want


def _archival_legs(d, sector):
    """The four legs from the pinned copies, by the live accessors' field rules without their age checks:
    ((rf, src), (g, src), (adj, raw, src), (erp, asof, why), archival record)."""
    blobs, msha, want = _pinned(d)
    try:
        coc = json.loads(blobs["cost_of_capital_anchor.json"])
        lrg = json.loads(blobs["long_run_growth_anchor.json"])
    except ValueError as e:
        raise DeskRefusal("coe_archival_unreadable", f"{ARCHIVAL_ENV}={d}: an anchor copy is not JSON ({e})") from None
    coc, lrg = (x if isinstance(x, dict) else {} for x in (coc, lrg))
    rf = (coc.get("risk_free") or {}).get("nominal_10y")                  # rs2_data.anchor_risk_free_rate
    rf = (float(rf), rs2_data._coc_leg_source(coc, "nominal_10y")) if isinstance(rf, (int, float)) and rf > 0 else (None, "anchor_has_no_risk_free_leg")
    g = lrg.get("terminal_g_suggestion")                                 # rs2_data.anchor_terminal_g
    if lrg.get("degraded"):
        g = (None, f"long_run_growth_anchor_degraded({lrg.get('asof')})")
    else:
        g = (float(g), f"anchor_long_run_growth({lrg.get('asof')})") if isinstance(g, (int, float)) else (None, "long_run_growth_anchor_has_no_suggestion")
    sec_id = rs2_data.mri_sector_id(sector)                              # rs2_data.anchor_sector_loading and coe_loading
    raw = (coc.get("sector_loadings") or {}).get(sec_id) if sec_id else None
    load = (0.67 * float(raw) + 0.33, float(raw), rs2_data._coc_leg_source(coc, f"sector_loading:{sec_id}")) \
        if isinstance(raw, (int, float)) else (None, None, f"no_loading_for_sector({sec_id or sector})")
    erp = rs2_data.reference_closure(d / "reference_closure.json", check_age=False)
    rec = {"version": ARCHIVAL_VERSION, "dir": str(d), "manifest_sha256": msha, "files": want}
    return rf, g, load, erp, rec


def cost_of_equity(sector, T, *, closure=None, allow_after_T=False):
    """(r, provenance). T: aware datetime of the decision. In the archival mode (module docstring) the pinned copies are read and
    `closure` and `allow_after_T` are not used."""
    d = archival_dir()
    if d is not None:
        (rf, rf_src), (ga, ga_src), load, (erp, erp_asof, erp_why), archival = _archival_legs(d, sector)
    else:
        rf, rf_src = rs2_data.anchor_risk_free_rate()
        ga, ga_src = rs2_data.anchor_terminal_g()
        load = rs2_data.coe_loading(sector)
        erp, erp_asof, erp_why = rs2_data.reference_closure(closure or closure_path())
        archival = None
    legs = {"rf": (rf, _asof(rf_src)), "g_anchor": (ga, _asof(ga_src)), "loading": (load[0] if load else None, None),
            "closure_erp": (erp, _asof(erp_asof))}
    missing = [k for k, (v, _) in legs.items() if v is None]
    if missing:
        raise DeskRefusal("coe_unavailable", f"missing {missing}" + (f"; closure: {erp_why}" if erp is None else "")
                          + (f"; archival {ARCHIVAL_ENV}={d}" if archival else ""))
    stamps = [f"coe_leg_undated:{k}" for k, (_, dt) in legs.items() if dt is None]      # ruling 29: the loading carries no date
    late = [k for k, (_, dt) in legs.items() if dt is not None and dt > T.date()]
    if archival:
        stamps.append(ARCHIVAL_STAMP)                                     # the after-T check is not applied to a pinned copy
    elif late:
        if not allow_after_T:
            raise DeskRefusal("coe_anchor_after_T", f"{late} dated after {T.date()}")
        stamps.append("anchor_after_T")
    r = max(rf, ga) + load[0] * erp
    prov = {"version": COE_VERSION, "rf": rf, "rf_source": rf_src, "g_anchor": ga, "g_source": ga_src, "loading_adjusted": load[0],
            "loading_raw": load[1], "closure_erp": erp, "closure_asof": str(erp_asof), "sector": sector, "stamps": stamps}
    if archival:
        prov["archival"] = dict(archival, legs_after_T=late)
    return r, prov

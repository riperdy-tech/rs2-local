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

THE EXTERNAL PREMIUM (archival v2, WO_street_S1_build deliverable 1, 2026-11-09; operator-approved for the Qwen-versus-analysts test at
T 2026-06-15, whose reference closure cannot be rebuilt: it needs Street estimates first saved 2026-10-04). Only in the archival mode and
only when the manifest declares "premium": "external": the premium is read from external_premium.json, {"erp": float, "asof":
"YYYY-MM-DD", "source": str, "source_sha256": str} (erp within the closure's bounds 0.0005..0.20, asof a date, source and its 64-hex
sha256 non-empty), instead of reference_closure.json, and the required files are the two anchors and external_premium.json. An unusable
premium is a missing leg (coe_unavailable, the reason named), as an unusable closure is. The provenance adds the stamp
`coe_external_premium` and `external_premium` = {erp, asof, source, source_sha256}; `closure_erp`/`closure_asof` carry that premium and
its date. A manifest without the key is the closure path, unchanged: its record keeps CLOSURE_ARCHIVAL_VERSION, so J2/K2 results stay
byte-identical. Any other value of the key refuses (coe_archival_unreadable).
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
ARCHIVAL_VERSION = "m3q.coe.archival.v2"     # v2 2026-11-09: the external premium (manifest "premium": "external")
CLOSURE_ARCHIVAL_VERSION = "m3q.coe.archival.v1"   # what a closure-premium pinned set records: its computation is v1's, unchanged
ARCHIVAL_ENV = "RS2_ARCHIVAL_COE_DIR"
ARCHIVAL_STAMP = "coe_archival_pinned"
ARCHIVAL_FILES = ("cost_of_capital_anchor.json", "long_run_growth_anchor.json", "reference_closure.json")
EXTERNAL_FILES = ("cost_of_capital_anchor.json", "long_run_growth_anchor.json", "external_premium.json")
EXTERNAL_STAMP = "coe_external_premium"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def closure_path():
    """The closure artifact of this repository's main checkout (a worktree shares its git directory; the artifact is untracked cache).
    RS2_REFERENCE_CLOSURE, when set, is used verbatim: a formation's pinned copy (formation_value.py; the live file is rebuilt in place
    each month, so a later pass would otherwise read a premium dated after the decision, 2026-11-06)."""
    if os.environ.get("RS2_REFERENCE_CLOSURE", "").strip():
        return Path(os.environ["RS2_REFERENCE_CLOSURE"].strip())
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
    """({file: bytes}, manifest sha256, {file: sha256}, external) of the pinned directory, every listed file rechecked; else DeskRefusal.
    external: the manifest declares "premium": "external"."""
    try:
        mbytes = (d / "manifest.json").read_bytes()
        manifest = json.loads(mbytes)
        files = manifest["files"]
        want = {f: (v["sha256"] if isinstance(v, dict) else None) for f, v in files.items()}
        premium = manifest.get("premium")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise DeskRefusal("coe_archival_unreadable", f"{ARCHIVAL_ENV}={d}: no readable manifest.json with files.<name>.sha256 ({e})") from None
    if premium not in (None, "external"):
        raise DeskRefusal("coe_archival_unreadable", f"{ARCHIVAL_ENV}={d}: the manifest's premium is {premium!r}; only \"external\" or none")
    external = premium == "external"
    missing = [f for f in (EXTERNAL_FILES if external else ARCHIVAL_FILES) if not want.get(f)]
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
    return blobs, hashlib.sha256(mbytes).hexdigest(), want, external


def external_premium(b):
    """(erp, asof, record) of external_premium.json's bytes, or (None, asof or None, the reason): the closure's bounds, a date, a source."""
    try:
        doc = json.loads(b)
    except ValueError:
        return None, None, "external_premium_not_json"
    if not isinstance(doc, dict):
        return None, None, "external_premium_not_an_object"
    erp, asof = doc.get("erp"), doc.get("asof")
    try:
        asof = date.fromisoformat(asof).isoformat() if isinstance(asof, str) and len(asof) == 10 else None
    except ValueError:
        asof = None
    if asof is None:
        return None, None, "external_premium_undated"
    if not (isinstance(erp, (int, float)) and not isinstance(erp, bool) and 0.0005 <= erp <= 0.20):
        return None, asof, "external_premium_has_no_usable_erp"
    src, ssha = doc.get("source"), doc.get("source_sha256")
    if not (isinstance(src, str) and src.strip() and isinstance(ssha, str) and _SHA256.fullmatch(ssha)):
        return None, asof, "external_premium_has_no_source_or_source_sha256"
    return float(erp), asof, {"erp": float(erp), "asof": asof, "source": src, "source_sha256": ssha}


def _archival_legs(d, sector):
    """The four legs from the pinned copies, by the live accessors' field rules without their age checks:
    ((rf, src), (g, src), (adj, raw, src), (erp, asof, why), archival record). With the external premium, `why` is its record when usable."""
    blobs, msha, want, external = _pinned(d)
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
    if external:
        erp = external_premium(blobs["external_premium.json"])
    else:
        erp = rs2_data.reference_closure(d / "reference_closure.json", check_age=False)
    rec = {"version": ARCHIVAL_VERSION if external else CLOSURE_ARCHIVAL_VERSION, "dir": str(d), "manifest_sha256": msha, "files": want}
    if external:
        rec["premium"] = "external"
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
        if archival.get("premium") == "external":
            stamps.append(EXTERNAL_STAMP)
    elif late:
        if not allow_after_T:
            raise DeskRefusal("coe_anchor_after_T", f"{late} dated after {T.date()}")
        stamps.append("anchor_after_T")
    r = max(rf, ga) + load[0] * erp
    prov = {"version": COE_VERSION, "rf": rf, "rf_source": rf_src, "g_anchor": ga, "g_source": ga_src, "loading_adjusted": load[0],
            "loading_raw": load[1], "closure_erp": erp, "closure_asof": str(erp_asof), "sector": sector, "stamps": stamps}
    if archival:
        prov["archival"] = dict(archival, legs_after_T=late)
        if archival.get("premium") == "external":
            prov["external_premium"] = erp_why
    return r, prov

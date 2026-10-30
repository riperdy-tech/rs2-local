"""coe.py - the code-owned cost of equity of 3Q (SPEC_m3q §2), the revision-18 anchor ported from capability_test (rev 26):

    COE = max(rf, g_anchor) + adjusted sector loading x closure ERP

rf: rs2_data.anchor_risk_free_rate (MRI); g_anchor: rs2_data.anchor_terminal_g; the Blume-adjusted loading: rs2_data.coe_loading(sector);
the closure premium: rs2_data.reference_closure (rs2's market-consistent ERP; no fallback to MRI's premium). Every leg must exist, or the
cost of equity is refused by name. Point in time: a leg dated after T is refused unless allow_after_T (the E2 regression on consumed
dates only), and then stamped `anchor_after_T`.
"""
import re
import subprocess
from datetime import date
from pathlib import Path

import rs2_data
from qwen_c.value.desk import DeskRefusal

COE_VERSION = "m3q.coe.v1"
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def closure_path():
    """The closure artifact of this repository's main checkout (a worktree shares its git directory; the artifact is untracked cache)."""
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=Path(__file__).resolve().parent, text=True).strip()
    root = (Path(__file__).resolve().parent / common).resolve().parent if not Path(common).is_absolute() else Path(common).resolve().parent
    return root / "cache" / "reference_closure.json"


def _asof(src):
    m = _DATE.findall(str(src or ""))
    return date.fromisoformat(m[-1]) if m else None


def cost_of_equity(sector, T, *, closure=None, allow_after_T=False):
    """(r, provenance). T: aware datetime of the decision."""
    rf, rf_src = rs2_data.anchor_risk_free_rate()
    ga, ga_src = rs2_data.anchor_terminal_g()
    load = rs2_data.coe_loading(sector)
    erp, erp_asof, erp_why = rs2_data.reference_closure(closure or closure_path())
    legs = {"rf": (rf, _asof(rf_src)), "g_anchor": (ga, _asof(ga_src)), "loading": (load[0] if load else None, None),
            "closure_erp": (erp, _asof(erp_asof))}
    missing = [k for k, (v, _) in legs.items() if v is None]
    if missing:
        raise DeskRefusal("coe_unavailable", f"missing {missing}" + (f"; closure: {erp_why}" if erp is None else ""))
    stamps = []
    late = [k for k, (_, d) in legs.items() if d is not None and d > T.date()]
    if late:
        if not allow_after_T:
            raise DeskRefusal("coe_anchor_after_T", f"{late} dated after {T.date()}")
        stamps.append("anchor_after_T")
    r = max(rf, ga) + load[0] * erp
    return r, {"version": COE_VERSION, "rf": rf, "rf_source": rf_src, "g_anchor": ga, "g_source": ga_src, "loading_adjusted": load[0],
               "loading_raw": load[1], "closure_erp": erp, "closure_asof": str(erp_asof), "sector": sector, "stamps": stamps}

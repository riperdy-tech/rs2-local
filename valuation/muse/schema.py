"""schema.py - the names, shapes and stated conventions of Muse's two passes (SPEC_muse_passes.md; SPEC_rebuild.md section 5, Addenda A-D).

Muse PLACES the company inside the population distribution of each judgment input; it does not write numbers. Python maps the
placement to a value (mapping.py). The inputs Muse is asked about are the family engine's judgment inputs plus the two curve
inputs (how long growth persists, how much of today's margin gap stays open):

  operating and commodity : g1, growth_persistence, margin_target, margin_retention, ronic, g_terminal
  financial               : g1, growth_persistence, rote_target,   rote_retention,   g_terminal        (no ronic: P3 is not run)

A LEVEL input is an engine input with a prior QuantileDist (priors.PriorSet.inputs). A CURVE input is a position on one of the
engine's measured curves. The priors object supplies the population distribution of that position through
`PriorSet.refs["curve_position"](name, state) -> QuantileDist` (the fraction of the initial gap still open CURVE_REF_YEAR years
out). Its MEDIAN must equal the measured curve's own value at year CURVE_REF_YEAR, so that a placement at P50 reproduces the prior's curve. A curve input for which the priors supply no such distribution is NOT asked of Muse and the engine runs on the prior's
measured curve (stamped `no_prior`): there is nothing to place the company in.

Every convention below is a stated convention, not a measurement; the calibration of SPEC_muse_passes section 4 replaces
WIDTH_FACTORS once the replay has measured them.
"""
from __future__ import annotations

from typing import Dict, List, Optional

PACK_VERSION = "2"

WIDTHS = ("narrow", "normal", "wide")
# SPEC_muse_passes section 2: the prior's own spread scaled by width. Stated convention until the replay calibrates it.
WIDTH_FACTORS: Dict[str, float] = {"narrow": 0.5, "normal": 1.0, "wide": 1.5}

PCT_MIN, PCT_MAX = 5.0, 95.0          # the range of a position (percentile points)
HARD_LO, HARD_HI = 10.0, 90.0         # a position outside P10..P90 needs hard evidence
NEAR_EXTRAORDINARY_POINTS = 10.0      # pass 2: a revised position within this many percentile points of an extraordinary requirement
EXTRAORDINARY_LO, EXTRAORDINARY_HI = 0.05, 0.95   # a price requirement outside P5..P95 is an extraordinary assumption
REVERSE_LO, REVERSE_HI = 0.01, 0.99   # the reverse valuation looks inside P1..P99
CURVE_REF_YEAR = 5                    # a curve input is the fraction of the initial gap still open after this many years

LEVEL, CURVE = "level", "curve"
INPUTS: Dict[str, dict] = {
    "g1": {"kind": LEVEL},
    "g_terminal": {"kind": LEVEL},
    "margin_target": {"kind": LEVEL},
    "ronic": {"kind": LEVEL},
    "rote_target": {"kind": LEVEL},
    "growth_persistence": {"kind": CURVE, "curve": "growth_decay"},
    "margin_retention": {"kind": CURVE, "curve": "margin_retention"},
    "rote_retention": {"kind": CURVE, "curve": "rote_retention"},
}

BUILT_FAMILIES = ("operating", "commodity", "financial")
PASS1_PROMPTS = ("P1", "P2", "P3", "P4")
PROMPTS = ("P1", "P2", "P3", "P4", "P5", "P6")

_OPERATING_PROMPTS = {"P1": ["g1", "growth_persistence"], "P2": ["margin_target", "margin_retention"], "P3": ["ronic"],
                      "P4": ["g_terminal"]}
_FINANCIAL_PROMPTS = {"P1": ["g1", "growth_persistence"], "P2": ["rote_target", "rote_retention"], "P3": [], "P4": ["g_terminal"]}
PROMPT_INPUTS: Dict[str, Dict[str, List[str]]] = {"operating": _OPERATING_PROMPTS, "commodity": _OPERATING_PROMPTS,
                                                  "financial": _FINANCIAL_PROMPTS}

# the pack sections each prompt reads (SPEC_muse_passes section 1 "Used by"; R is only the inputs of the prompt)
PROMPT_SECTIONS = {"P1": ("F", "Q", "D", "S", "R"), "P2": ("F", "Q", "D", "S", "R"), "P3": ("F", "D", "S", "R"),
                   "P4": ("F", "D", "S", "R"), "P5": ("S", "R"), "P6": ("S", "R")}
SECTION_TITLES = {"F": "Filed financial history", "Q": "Latest quarters", "D": "Primary documents", "S": "Company state",
                  "R": "Population priors"}

EVIDENCE_SECTIONS = ("D", "Q")        # a citation that can carry a position outside P10..P90 comes from these
CALCULATED_FROM = "Python"


def muse_inputs(family: str) -> List[str]:
    """Every input Muse is asked about for a family, in prompt order."""
    if family not in PROMPT_INPUTS:
        raise ValueError(f"family {family!r} is not built (operating, commodity, financial)")
    out: List[str] = []
    for p in PASS1_PROMPTS:
        out += PROMPT_INPUTS[family][p]
    return out


def prompt_inputs(family: str, prompt: str) -> List[str]:
    return list(PROMPT_INPUTS[family][prompt])


def prior_distribution(prior_set, name: str, state: Optional[dict] = None):
    """The population distribution of input `name` from a PriorSet: engine inputs from `inputs`, curve positions from
    `refs["curve_position"]`. None when the priors do not supply one (the input is then not asked of Muse)."""
    meta = INPUTS[name]
    if meta["kind"] == LEVEL:
        return prior_set.inputs.get(name)
    fn = prior_set.refs.get("curve_position")
    return None if fn is None else fn(name, state)


def askable_inputs(family: str, prior_set, state: Optional[dict] = None) -> List[str]:
    """The inputs of `muse_inputs(family)` the priors can place a company in."""
    return [n for n in muse_inputs(family) if prior_distribution(prior_set, n, state) is not None]

"""paths.py — the single owner of where RS2's PEER repositories live.

Before this module, four absolute Windows paths were baked into config.json
(`screener_data_dir`, `screener_publish_repo`, `mri_outputs_dir`, `anchors_dir`), and two more
absolute paths were baked into the Macro Regime Indicator repo pointing back here. Moving any
folder meant editing several repos, and nothing declared the relationship — the screener even
reached its peer by walking UP one directory and back down by name, so the nesting depth itself
was load-bearing.

The contract: every cross-repo location resolves from ONE root, `STOCKS_ROOT`, and every
individual location can be overridden by its own environment variable. Resolution order per key:

  1. the key's own environment variable, if set — used VERBATIM, never probed. An operator who
     names a path means it; a typo must fail loudly at the consumer, not be silently replaced.
  2. an explicit non-empty value in config.json — kept so a machine with an unusual layout can
     still pin a path the old way.
  3. the layout probe below, relative to `STOCKS_ROOT`.

`STOCKS_ROOT` itself defaults to this repo's parent directory, which is the CURRENT location
(`C:/Users/riper/Downloads`). So introducing this module changes no behaviour: every path it
resolves today is the path that was hardcoded yesterday. That is deliberate — the operator
decision of 2026-09-22 was contract first, move second, so that relocating the folders later is a
configuration change rather than a code change.

THE PROBE ACCEPTS TWO LAYOUTS. Today the screener and the MRI sit inside a non-repo wrapper
folder named `Stock Screener`; after the planned move they are siblings named `stock-screener` and
`macro-regime-indicator`. Both spellings are listed for each key, in that order, and the first one
that EXISTS wins. This is what lets the move happen without a code change in between. When
neither exists, `resolve()` raises and names every candidate it tried — a missing peer repo is a
real failure and must not degrade into a silently-empty data directory, which would look to the
pipeline like a book with no names in it.

Nothing here is cached: `load_config()` resolves on every call, so a moved folder or a changed
environment variable takes effect on the next process start without a stale value surviving in
config.json.

See docs/superpowers/specs/2026-09-22-stocks-workspace-reorg-design.md (stock-screener repo).
"""

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent          # the rs2-local repo root

# Ordered candidates per key, relative to STOCKS_ROOT: (current nested layout, post-move layout).
# `screener_publish_repo` has one spelling because the dedicated publish clone is already a
# sibling and the move does not rename it.
_CANDIDATES = {
    "screener_data_dir": (
        "Stock Screener/Stock Screener/public/data",
        "stock-screener/public/data",
    ),
    "screener_publish_repo": (
        "screener-publish",
    ),
    "mri_outputs_dir": (
        "Stock Screener/Macro Regime Indicator/outputs",
        "macro-regime-indicator/outputs",
    ),
    "rs2_state_dir": (
        "rs2-state",
    ),
}

# Per-key environment overrides. `anchors_dir` deliberately reads MRI_ANCHORS_DIR first and then
# MRI_OUTPUTS_DIR: the anchors are additive artifacts that MRI writes BESIDE its other outputs, so
# one variable normally covers both, but a calibration run can point the anchors elsewhere without
# also redirecting current_regime.json.
_ENV = {
    "screener_data_dir": ("SCREENER_DATA_DIR",),
    "screener_publish_repo": ("SCREENER_PUBLISH_REPO",),
    "mri_outputs_dir": ("MRI_OUTPUTS_DIR",),
    "anchors_dir": ("MRI_ANCHORS_DIR", "MRI_OUTPUTS_DIR"),
    "rs2_state_dir": ("RS2_STATE_DIR",),
}


def stocks_root():
    """The parent directory holding every stock-system repo.

    Defaults to this repo's parent, which is where they all live today. Set STOCKS_ROOT to move
    them as a group.
    """
    env = (os.environ.get("STOCKS_ROOT") or "").strip()
    return Path(env).expanduser() if env else HERE.parent


def _from_env(key):
    for var in _ENV.get(key, ()):
        val = (os.environ.get(var) or "").strip()
        if val:
            return Path(val).expanduser()
    return None


def _probe(key, root):
    """First existing candidate for `key` under `root`, or None.

    Returns None rather than a best guess. The caller decides whether a missing peer is fatal,
    because it is fatal for some keys and merely absent for others.
    """
    for rel in _CANDIDATES.get(key, ()):
        p = root / rel
        if p.exists():
            return p
    return None


def _candidate_list(key, root):
    return [str(root / rel) for rel in _CANDIDATES.get(key, ())]


def resolve(key, config=None, required=True):
    """Resolve one cross-repo path. See the module docstring for the precedence rules."""
    env = _from_env(key)
    if env is not None:
        return env

    if config:
        pinned = str(config.get(key) or "").strip()
        if pinned:
            return Path(pinned).expanduser()

    root = stocks_root()

    # anchors_dir has no candidates of its own: the anchors live in the MRI outputs directory.
    probe_key = "mri_outputs_dir" if key == "anchors_dir" else key
    hit = _probe(probe_key, root)
    if hit is not None:
        return hit

    if not required:
        return None
    raise FileNotFoundError(
        f"cannot locate {key!r}. STOCKS_ROOT={root}. Tried, in order: the environment "
        f"variable(s) {'/'.join(_ENV.get(key, ()))}; an explicit config.json value; and these "
        f"paths: {', '.join(_candidate_list(probe_key, root)) or '(none)'}. Set STOCKS_ROOT or "
        f"the per-key variable to the real location - do not guess."
    )


# Keys naming a location INSIDE this repo. They were absolute too, which means they break on a
# move exactly like the peer paths do — a folder rename would leave the pipeline writing reports
# into a directory that no longer exists. They are derived from HERE instead, so they cannot be
# wrong. An explicit config.json value still wins, for the case where reports or the research venv
# genuinely live off-repo (a different drive, say).
_SELF_PATHS = {
    "agentwebsearch_dir": "AgentWebSearch-MCP",
    "out_reports_dir": "reports",
    "out_enrich_dir": "enrich",
    "out_research_dir": "research",
    "research_venv_python": "research-venv/Scripts/python.exe",
}


def resolve_self(key, config=None):
    """Resolve a path inside this repo: an explicit config.json value, else derived from HERE.

    No existence probe and no error: `reports/` and friends are created on demand, and
    `research-venv` is checked by its own caller, which already reports a useful message when the
    interpreter is missing.
    """
    if config:
        pinned = str(config.get(key) or "").strip()
        if pinned:
            return Path(pinned).expanduser()
    return HERE / _SELF_PATHS[key]


def load_config(path=None):
    """Read config.json and overlay the resolved cross-repo paths onto it.

    Every RS2 module that needs config.json goes through here, so the four path keys have exactly
    one resolution site. Consumers keep reading `CONFIG["screener_data_dir"]` and friends
    unchanged; they just no longer read a hardcoded absolute path.

    utf-8-sig, because config.json has carried a BOM at times and json.loads rejects one.
    """
    cfg_path = Path(path) if path else (HERE / "config.json")
    config = json.loads(cfg_path.read_text(encoding="utf-8-sig"))

    for key in ("screener_data_dir", "screener_publish_repo", "mri_outputs_dir", "anchors_dir",
                "rs2_state_dir"):
        config[key] = str(resolve(key, config))

    for key in _SELF_PATHS:
        config[key] = str(resolve_self(key, config))

    return config


if __name__ == "__main__":
    cfg = load_config()
    print(f"STOCKS_ROOT = {stocks_root()}")
    for k in ("screener_data_dir", "screener_publish_repo", "mri_outputs_dir", "anchors_dir",
              "rs2_state_dir"):
        p = Path(cfg[k])
        print(f"{k:24s} = {cfg[k]}  {'(exists)' if p.exists() else '(MISSING)'}")

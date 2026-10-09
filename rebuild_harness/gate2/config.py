"""config.py - the registered constants of gate 2 and where its state lives.

Every number here is from REGISTRATION_gate2_DRAFT.md (approved 2026-10-07) unless it says otherwise.  Paths follow the workspace rule: the environment variable wins,
then STOCKS_ROOT (default: this workspace), then paths inside this repository from its root; there is no walking up the tree and no path to a sibling repository.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STOCKS = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks"))
WORKSPACE = STOCKS / "stocks-workspace"
STATE_DIR = Path(os.environ.get("GATE2_STATE_DIR") or (WORKSPACE / "data" / "gate2"))   # NOT %TEMP%: it survives a reboot and an app update

# registration section 2
DATES = ("2025-10-31", "2025-12-31", "2026-02-27", "2026-04-30", "2026-06-30")
PER_DATE = 120
SEED = 20261007
MCAP_FLOOR = 300e6
PILOT_DATE = "2025-10-31"
PILOT_N = 10
# Addendum V3 (binding for gate 2 by Addendum W): the commodity family is out of scope for BOTH arms
OUT_OF_SCOPE_FAMILIES = ("commodity",)
# registration section 4, G6
MASKED_N = 30
MASKED_SEED_LABEL = "masked_control"
# SPEC_rebuild Addendum AD R8 (a reported diagnostic): the repeatability control, 30 company-dates rerun with a second model seed in their own state folder
REPEAT_N = 30
REPEAT_SEED_LABEL = "repeat_control"
REPEAT_LLM_SEED_OFFSET = 1          # the second seed: (the company-date's model seed + 1) mod 2**31; the engine draws keep their seed
REPEAT_MARKER = "REPEAT_CONTROL"    # a state folder holding the repeat control carries this file and holds nothing else

# registration section 1: Muse settings
CONTEXT = 32768                      # registered ("context 32k"); the pinned production line is 98304 (server.PINNED_WINDOW)
PINNED_WINDOW = 98304
# NOT registered: the cap on the generated tokens of ONE request.  The prompt and the answer share the 32768-token window, so a cap of the whole window could never
# be honoured; 16384 leaves room for a prompt of about 16k tokens, and the context guard (guard.py) lowers it per request when the prompt is longer.
MAX_TOKENS = 16384
CTX_MARGIN_TOKENS = 512
CTX_FLOOR_TOKENS = 2048
CHARS_PER_TOKEN = 3.0                # a conservative estimate used only by the guard; the measured usage of every response is recorded to calibrate it

# registration section 3 / 4
RETURN_HORIZONS = (3, 6, 12)
G4_MAX_SHARE = 0.10
BOOT_DRAWS = 2000
BOOT_SEED = 20261008
ONE_SIDED_LEVEL = 0.90

# the runner
POLL_SECONDS = 60
BUSY_MIB = 2048                      # more than this in use while nothing of ours is loaded: another program (a game)
MAX_CONSECUTIVE_TRANSPORT_FAILURES = 3
RUNNER_VERSION = "1"


def state_paths(state_dir: Path = None) -> dict:
    d = Path(state_dir) if state_dir is not None else STATE_DIR
    return {"root": d, "sample": d / "sample", "ctx": d / "ctx", "runs": d / "runs", "runs_masked": d / "runs_masked", "server": d / "server",
            "freeze": d / "freeze", "stage2": d / "stage2", "submissions": d / "submissions", "doc_cache": d / "doc_cache", "outcomes": d / "outcomes", "reports": d / "reports",
            "progress": d / "progress.jsonl", "events": d / "events.jsonl", "pause": d / "PAUSE", "lock": d / "runner.lock", "pid": d / "runner.pid",
            "finished": d / "gate2_finished.flag", "pilot_done": d / "pilot_done.flag"}

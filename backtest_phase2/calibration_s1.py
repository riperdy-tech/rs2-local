"""Backtest registration 3.2.2: the calibration file of the structural candidate, `s1_calibration.json`.

Every margin fraction (the four cells and the loss cell) is 1.0, so the long-run margin is the record's trend level reached in
full.  w8 and the retention caps are set to 1.0 and are unused (the harness sets r_blend and ronic_t itself, 3.2.1).  The file has
the shape throughcycle_record.calibration() reads; the harness points throughcycle_record.CALIBRATION_FILE at it, in the worker
process only.  No rate here is estimated from any data.
"""
import json
import sys
from pathlib import Path

CELLS = ("peak_swing", "peak_trend", "trough_swing", "trough_trend", "loss")
BUCKETS = ("p_lt_0.5", "p_0.5_to_lt_1", "p_eq_1")


def s1_document():
    return {"purpose": "backtest registration d09bb4a4, 3.2.2: full reversion toward the trend level; no estimated parameter",
            "margin_series": "operating_margin",
            "cells": {c: {"f": 1.0} for c in CELLS},
            "w8": 1.0,
            "retention_caps": {b: {"cap": 1.0} for b in BUCKETS}}


def write(path):
    Path(path).write_text(json.dumps(s1_document(), indent=1), encoding="utf-8")


if __name__ == "__main__":
    write(sys.argv[1])

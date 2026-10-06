"""Backtest registration section 6 / 11: two looks, each authorised by the reviewer in writing.

Nothing that reads a return runs unless <bt-root>/AUTHORISED_LOOK_<n>.txt exists.  The harness never creates that file.
"""
from pathlib import Path


def gate_path(bt_root, n):
    return Path(bt_root) / f"AUTHORISED_LOOK_{n}.txt"


def require_look(n, bt_root):
    if n not in (1, 2):
        raise ValueError(f"look must be 1 or 2, not {n!r}")
    p = gate_path(bt_root, n)
    if not p.is_file():
        raise PermissionError(f"Look {n} is not authorised: {p} does not exist.  No return is computed.")
    return p

"""One writer at a time in the rs2-state clone.

sync_state.py hard-resets the clone to its upstream and commits everything (`add -A`); tools/paper_books/run_monthly.py appends to
paper_books/ and commits it. Either one running inside the other would lose or mis-commit the other's files, so both hold this lock
while they touch the clone. It is an OS byte-range lock on cache/rs2_state.lock, released by Windows when the holder exits or dies,
so a crashed holder never leaves a stale lock (and no process-liveness probe is needed).
"""
import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK = Path(__file__).resolve().parent / "cache" / "rs2_state.lock"


@contextmanager
def rs2_state_lock(wait_s=0.0, poll_s=5.0):
    """Yields True while the lock is held, or False when it is still busy after wait_s seconds."""
    if os.name != "nt":                      # only the Windows PC writes rs2-state
        yield True
        return
    import msvcrt
    LOCK.parent.mkdir(exist_ok=True)
    f = open(LOCK, "a+b")
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(poll_s)
        try:
            yield True
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        f.close()

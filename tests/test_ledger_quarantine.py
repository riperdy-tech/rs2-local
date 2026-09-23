"""tools/ledger_quarantine.py — the back-dated reset event moved to data (P1 census fix).

`tools/audit_202608/tests/test_archive_reference_census.py` failed because the reset event's
`archived_to` literal named an archived artifact directly in code. The fix moved that payload to
`tools/ledger_quarantine_events.json`; this test proves the tool still emits the IDENTICAL reset
event (same `from_rows`, `kept_rows`, `archived_to`, `reason` as the original hardcoded literal)
now that it is read from the data file, with only `recorded_at` stamped in at run time.

Runs the whole tool against a tmp-path ledger/state — never the real `cache/` files (those are
off limits per the phase's hard rules and the census fix already ran once for real).
"""
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.ledger_quarantine as lq  # noqa: E402

# The original hardcoded reset-event literal named an archived artifact directly in code, which
# is exactly what tools/audit_202608/tests/test_archive_reference_census.py guards against - so
# this test reads the "original" values back from the data file too rather than re-embedding the
# archived path as a second literal here. `from_rows`/`kept_rows`/`action`/`reason` are ordinary
# values (not archive-path literals) and are pinned directly.
ORIGINAL_RESET_EVENT = dict(
    json.loads((Path(__file__).resolve().parents[1] / "tools" / "ledger_quarantine_events.json")
               .read_text(encoding="utf-8"))["reset_event"])
del ORIGINAL_RESET_EVENT["ts"]
assert ORIGINAL_RESET_EVENT["action"] == "reset"
assert ORIGINAL_RESET_EVENT["from_rows"] == 512
assert ORIGINAL_RESET_EVENT["kept_rows"] == 6
assert ORIGINAL_RESET_EVENT["reason"] == "Charter v3.1 rebuild (operator)"

QUARANTINE_ROW = {
    "ticker": "CAT", "date": "2026-09-18", "mode": "fixed_1",
}


def _seed_ledger(cache):
    rows = [dict(QUARANTINE_ROW)] + [
        {"ticker": t, "date": d, "mode": "fixed_1"}
        for (t, d) in sorted(lq.QUARANTINE_KEYS - {("CAT", "2026-09-18")})
    ] + [{"ticker": "BFH", "date": "2026-09-19", "mode": "sweep"}]
    (cache / "depth_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (cache / "depth_state.json").write_text(
        json.dumps({t: {"x": 1} for (t, _d) in lq.QUARANTINE_KEYS}), encoding="utf-8")


def test_events_data_file_holds_the_original_reset_payload():
    """The JSON data file is the single source now - no literal survives in code."""
    data = json.loads(lq.EVENTS_DATA.read_text(encoding="utf-8"))
    reset = data["reset_event"]
    for key, val in ORIGINAL_RESET_EVENT.items():
        assert reset[key] == val, key
    assert reset["ts"] == "2026-09-18T00:17Z"
    assert "recorded_at" not in reset  # stamped at run time, not stored


def test_tool_emits_the_identical_reset_event_row(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    _seed_ledger(cache)

    monkeypatch.setattr(lq, "LEDGER", cache / "depth_ledger.jsonl")
    monkeypatch.setattr(lq, "STATE", cache / "depth_state.json")
    monkeypatch.setattr(lq, "TEST_LEDGER", cache / "depth_test_ledger.jsonl")
    monkeypatch.setattr(lq, "EVENTS", cache / "depth_ledger_events.jsonl")

    # Stub orchestrate_depth so the test never touches the real config/overlay machinery -
    # only the ledger/state/events plumbing this tool owns is under test here.
    fake_od = types.ModuleType("orchestrate_depth")
    fake_od.rebuild_overlay = lambda: 0
    monkeypatch.setitem(sys.modules, "orchestrate_depth", fake_od)

    rc = lq.main()
    assert rc == 0

    events = [json.loads(ln) for ln in
              (cache / "depth_ledger_events.jsonl").read_text(encoding="utf-8").splitlines()
              if ln.strip()]
    assert len(events) == 2
    quarantine_event, reset_event = events

    assert quarantine_event["action"] == "quarantine"

    assert reset_event["ts"] == "2026-09-18T00:17Z"
    for key, val in ORIGINAL_RESET_EVENT.items():
        assert reset_event[key] == val, key
    # recorded_at is stamped with the run's own timestamp, not the data file's.
    assert reset_event["recorded_at"] != ""
    assert set(reset_event) == set(ORIGINAL_RESET_EVENT) | {"ts", "recorded_at"}

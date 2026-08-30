import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_bus  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, reply=b"[]"):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req)
        return FakeResponse(reply)

    monkeypatch.setattr(control_bus.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        control_bus, "_secrets",
        lambda: {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "sk"},
    )
    return calls


def test_push_heartbeat_upserts(monkeypatch):
    calls = _capture(monkeypatch)
    control_bus.push_heartbeat("rs2-pc", {"ts": "2026-08-30T00:00:00+00:00"})
    (req,) = calls
    assert req.full_url == "https://x.supabase.co/rest/v1/control_heartbeat?on_conflict=id"
    assert req.get_method() == "POST"
    assert req.get_header("Prefer") == "resolution=merge-duplicates"
    assert req.get_header("Apikey") == "sk"
    body = json.loads(req.data.decode())
    assert body[0]["id"] == "rs2-pc"
    assert body[0]["payload"]["ts"] == "2026-08-30T00:00:00+00:00"


def test_fetch_pending_commands(monkeypatch):
    calls = _capture(monkeypatch, reply=b'[{"id": 1, "command": "depth_pause"}]')
    rows = control_bus.fetch_pending_commands()
    (req,) = calls
    assert "status=eq.pending" in req.full_url and "order=id.asc" in req.full_url
    assert rows[0]["command"] == "depth_pause"


def test_mark_command(monkeypatch):
    calls = _capture(monkeypatch, reply=b"")
    control_bus.mark_command(7, "done", "ok")
    (req,) = calls
    assert req.full_url.endswith("control_commands?id=eq.7")
    assert req.get_method() == "PATCH"
    body = json.loads(req.data.decode())
    assert body["status"] == "done" and body["result"] == "ok" and body["executed_at"]


def test_fetch_heartbeat_none(monkeypatch):
    _capture(monkeypatch, reply=b"[]")
    assert control_bus.fetch_heartbeat("rs2-pc") is None

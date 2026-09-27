"""Pins ensuring no model-visible changes.

Frozen datetime modules replaced for deterministic pack generation:
- capability_test
- rs2_data
- catalyst_research
- valuation_backbone
"""
import hashlib
import inspect
import json
from pathlib import Path
import re
import socket
import sys
from datetime import datetime as _real_datetime, timezone
import pytest

import analyst_tools
import capability_test
import catalyst_research
import consensus_valuation
import rs2_data
import valuation_backbone

REPO = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixture_data"

# Step 0.1: Text pin sha256 literals computed on unmodified tree
TASK_SHA256 = "fa18e9967d0401db32a45797d0d3f7ad8e59d317df050cc4e350b04ea4cf0bed"
RESEARCH_ADDENDUM_SHA256 = "a2dbd6ec296cff777373421babca855291e6b4f2f9a6181fce8e387bef92932d"
TOOLS_SHA256 = "d9163b2096b730965f5f89bc88bfcc0e87757146427d344a430427bdd8edc4b0"
RESEARCH_TOOLS_SHA256 = "b325e8e236993e09a8d0230eccd3f17206af3133b64ff93e31ec82f613c91a35"
SYSTEM_MTP5_SHA256 = "a76fd089a4c3c2ca25b21eee1633a233ffca3e8c0dbb8c02a6b044edd3d56a7d"
SYSTEM_MTP5_Q4_SHA256 = "a76fd089a4c3c2ca25b21eee1633a233ffca3e8c0dbb8c02a6b044edd3d56a7d"
CONTINUE_REPORT_SHA256 = "707e547dd3ccdbe8e6303180852c9171a46085d3085cfe9f3d8d320923708151"


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _get_system_block(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    m = re.search(r'SYSTEM """(.*?)"""', content, re.DOTALL)
    if not m:
        raise ValueError(f"SYSTEM block not found in {path}")
    return m.group(1)


def test_text_pins():
    assert capability_test.PACK_REVISION == 14
    assert _sha256(capability_test.TASK) == TASK_SHA256
    assert _sha256(capability_test.RESEARCH_ADDENDUM) == RESEARCH_ADDENDUM_SHA256
    assert _sha256(json.dumps(analyst_tools.TOOLS, sort_keys=True, ensure_ascii=False)) == TOOLS_SHA256
    assert _sha256(json.dumps(analyst_tools.research_tools(), sort_keys=True, ensure_ascii=False)) == RESEARCH_TOOLS_SHA256

    sys_mtp5 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5.Modelfile")
    sys_mtp5_q4 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5-Q4.Modelfile")
    assert _sha256(sys_mtp5) == SYSTEM_MTP5_SHA256
    assert _sha256(sys_mtp5_q4) == SYSTEM_MTP5_Q4_SHA256

    assert _sha256(inspect.getsource(consensus_valuation.continue_report)) == CONTINUE_REPORT_SHA256


FIXED_LOCAL = _real_datetime(2026, 9, 27, 12, 0, 0)


class FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FIXED_LOCAL.astimezone(tz)
        return FIXED_LOCAL


def test_pack_byte_pin(screener_data_stub, monkeypatch):
    """Confirm build_pack determinism and byte equality with golden_pack_GEV_rev14.md.

    Datetime is frozen at 2026-09-27 12:00 local across:
    - capability_test
    - rs2_data
    - catalyst_research
    - valuation_backbone
    """
    # Block sockets
    class BlockedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")
        def connect(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")

    monkeypatch.setattr(socket, "socket", BlockedSocket)

    # Stubs
    monkeypatch.setattr(
        capability_test.company_news,
        "fetch",
        lambda company, t: {
            "date": "2026-09-27",
            "rows": [],
            "unresponsive_engines": [],
            "errors": ["stubbed"],
        },
    )
    monkeypatch.setattr(
        capability_test.sec_guidance,
        "latest_earnings_release",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        capability_test.world_news,
        "digest",
        lambda *a, **k: None,
    )
    # build_pack imports the screener's industry_taxonomy through sys.path entries it appends itself
    # (capability_test.py SECTION 1). Whether the import succeeds depends on what earlier tests left
    # in sys.path and sys.modules: the SECTION 1 cluster line then reads "Unknown" or the real cluster
    # (20 characters on GEV). Blocking the import pins the fallback branch, so the bytes do not depend
    # on test order. Both branches print through the same lines.
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)

    # Freeze clock across all four modules
    for mod in (capability_test, rs2_data, catalyst_research, valuation_backbone):
        monkeypatch.setattr(mod, "datetime", FrozenDatetime, raising=False)

    # Build twice and confirm identical
    pack1 = capability_test.build_pack("GEV", include_research=False)
    pack2 = capability_test.build_pack("GEV", include_research=False)
    text1 = str(pack1)
    text2 = str(pack2)
    assert text1 == text2
    assert len(text1) == 21152

    # Assert byte equality with golden file
    golden_file = FIXTURE / "golden_pack_GEV_rev14.md"
    golden_bytes = golden_file.read_bytes()
    assert text1.encode("utf-8") == golden_bytes

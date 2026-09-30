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
# S3 (2026-09-28, package A+B): the TASK, RESEARCH_ADDENDUM, TOOLS JSON (run_financial_model's
# schema) and continue_report's source changed on purpose (brief section 2). Old literals:
# TASK_SHA256 = "fa18e9967d0401db32a45797d0d3f7ad8e59d317df050cc4e350b04ea4cf0bed"
# RESEARCH_ADDENDUM_SHA256 = "a2dbd6ec296cff777373421babca855291e6b4f2f9a6181fce8e387bef92932d"
# TOOLS_SHA256 = "d9163b2096b730965f5f89bc88bfcc0e87757146427d344a430427bdd8edc4b0"
# CONTINUE_REPORT_SHA256 = "707e547dd3ccdbe8e6303180852c9171a46085d3085cfe9f3d8d320923708151"
# 2026-09-28 (reviewer, S3 C review): the Shares sentence names 5.11's DEFAULTS shares_default; was
# "b9d6528f8f865dd6c661d0b97731dfa3585962c52f74a3a6e81b6a386b38fe99" ("use SECTION 2's count").
# 2026-09-28 (package D): pack sections renamed DATA n (brief §D2).
# 2026-09-30 (revision 17, brief_rev17_B_valuation.md): the TASK changed on purpose (terminal_ronic replaces the exit
# multiple and terminal leg in item 3; the Growth, Terminal value, Working capital and Valuation date sub-bullets); was
# "017954dba1760027997a91e8456b63952ee5e2bcc7109ae4a9d03605ffd819ce".
TASK_SHA256 = "647be918454d5249b3fb6f70da3932e48d6a69b86dc728d46781de405fe0ab91"
RESEARCH_ADDENDUM_SHA256 = "e8904157f94de97e64e2ec78c82e068f7f14a8cf04454b405ac8ff56a7420acb"
# 2026-09-28 (reviewer, S3 A+B review): cash_flow_life takes one JSON type, "string"; was
# "fd75fbe0f4aea35b74e3d2c1f72caec603e89b18be10d5d2bddd9f9aae4567b8" with ["string", "integer"].
# 2026-09-28 (reviewer, S3 C review): shares_diluted's description names the DEFAULTS
# shares_default; was "59ba2b728999b3f5be6f964fc9e4294d42678ffe611a5c6825f67369acb95861".
# 2026-09-28 (package D): analyst_tools descriptions renamed DATA n (brief §D2).
# 2026-09-29 (revision 16, brief_rev16.md): exactly three descriptions changed on purpose: both
# shares_diluted descriptions (a whole share count, billions also accepted) and the scenarios
# description (exactly three entries, one each Base, Bull and Bear); was
# "cc6c27898d5fba93399520922cc29194506834fa86396d93c7b5047b43e5a3a6".
# 2026-09-30 (revision 17): run_financial_model's schema changed on purpose (terminal_ronic replaces terminal_exit_multiple
# and terminal_leg; the description, base_cf_reason, guidance_deviation_reason, terminal_reason, explicit_growth, fade_years
# and sbc_dilution texts); was "2600921006ada7440b52f6e79da682c8be693d1ebba705b2d8a37efed6ddebe1".
# 2026-09-30 (revision 17, brief B2 F2): the description's firm-frame sentence says the return on new investment is
# measured on tangible invested capital before interest and applied to equity earnings; was
# "2c23b3f0d23a40d3d9839f28a8efbe65d49249a0181291e065d5c97b62ea7196".
TOOLS_SHA256 = "69b8bb654011315fae51b12c17b6eb84cb62f1b520875d093c24806043a7eb0e"
# research_tools() (search_web, fetch_page) is unchanged, so its pin stays.
RESEARCH_TOOLS_SHA256 = "b325e8e236993e09a8d0230eccd3f17206af3133b64ff93e31ec82f613c91a35"
SYSTEM_MTP5_SHA256 = "a76fd089a4c3c2ca25b21eee1633a233ffca3e8c0dbb8c02a6b044edd3d56a7d"
SYSTEM_MTP5_Q4_SHA256 = "a76fd089a4c3c2ca25b21eee1633a233ffca3e8c0dbb8c02a6b044edd3d56a7d"
SYSTEM_MTP5_V32_SHA256 = "04894e6c3b217be46f48c329ca7c6c8dd7347d344513ec4c5cd723213b0c0ab7"
SYSTEM_MTP5_Q4_V32_SHA256 = "04894e6c3b217be46f48c329ca7c6c8dd7347d344513ec4c5cd723213b0c0ab7"
CONTINUE_REPORT_SHA256 = "71742a7a93e0d6f1aa02792c3414936abf07cf8fdf45d6989be4f94ecd8d64c3"


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _get_system_block(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    m = re.search(r'SYSTEM """(.*?)"""', content, re.DOTALL)
    if not m:
        raise ValueError(f"SYSTEM block not found in {path}")
    return m.group(1)


def test_text_pins():
    # Revision 17 (brief_rev17_B_valuation.md): the pack text, the TASK and the tool schema changed on purpose (the
    # through-cycle package); revision 16 changed only the number on the first line.
    assert capability_test.PACK_REVISION == 17
    assert _sha256(capability_test.TASK) == TASK_SHA256
    assert _sha256(capability_test.RESEARCH_ADDENDUM) == RESEARCH_ADDENDUM_SHA256
    assert _sha256(json.dumps(analyst_tools.TOOLS, sort_keys=True, ensure_ascii=False)) == TOOLS_SHA256
    assert _sha256(json.dumps(analyst_tools.research_tools(), sort_keys=True, ensure_ascii=False)) == RESEARCH_TOOLS_SHA256

    sys_mtp5 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5.Modelfile")
    sys_mtp5_q4 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5-Q4.Modelfile")
    assert _sha256(sys_mtp5) == SYSTEM_MTP5_SHA256
    assert _sha256(sys_mtp5_q4) == SYSTEM_MTP5_Q4_SHA256

    sys_mtp5_v32 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5-v32.Modelfile")
    sys_mtp5_q4_v32 = _get_system_block(REPO / "RS2-Analyst-Deep-MTP5-Q4-v32.Modelfile")
    assert _sha256(sys_mtp5_v32) == SYSTEM_MTP5_V32_SHA256
    assert _sha256(sys_mtp5_q4_v32) == SYSTEM_MTP5_Q4_V32_SHA256

    assert _sha256(inspect.getsource(consensus_valuation.continue_report)) == CONTINUE_REPORT_SHA256


FIXED_LOCAL = _real_datetime(2026, 9, 27, 12, 0, 0)


class FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FIXED_LOCAL.astimezone(tz)
        return FIXED_LOCAL


def test_pack_byte_pin(screener_data_stub, monkeypatch):
    """Confirm build_pack determinism and byte equality with golden_pack_GEV_rev17.md.

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
    # 2026-09-28 (package D): pack sections renamed DATA n (brief §D2). 32 occurrences of SECTION -> DATA, -96 chars.
    # revision 17: the exit-multiple line and DEFAULTS line left; terminal_ronic, long_run and working_capital lines
    # and the new explanations joined (was 20006 at revision 16); brief B2 F6 shortened the long_run explanation
    # (was 21077 before the fixes)
    assert len(text1) == 20823

    # Assert byte equality with golden file
    golden_file = FIXTURE / "golden_pack_GEV_rev17.md"
    # core.autocrlf checks the fixture out with CRLF on Windows; the pack itself is built with "\n"
    golden_bytes = golden_file.read_bytes().replace(b"\r\n", b"\n")
    assert text1.encode("utf-8") == golden_bytes

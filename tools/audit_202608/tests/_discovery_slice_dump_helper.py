"""S3 6.5 / test_pack_rev15.py helper: build a GEV pack in the tree given as argv[1] (a revision-14
or revision-15 checkout root) with a stubbed company_news.fetch (3 rows: one with an excerpt, two
without, one of the without-excerpt ones undated) and a frozen clock, then dump the four slices
catalyst_research.discovery_context reads (SECTION 2.5, RECENT COMPANY NEWS, CONSENSUS ESTIMATES,
GUIDANCE) as JSON to argv[2]. Run as a subprocess (once per tree) because two different
capability_test modules cannot coexist in one process.
"""
import json
import os
import socket
import sys
from datetime import datetime as _real_datetime
from pathlib import Path

tree_root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
supports_news_snippets = len(sys.argv) > 3 and sys.argv[3] == "1"

os.environ.setdefault("STOCKS_ROOT", r"C:\Users\riper\stocks")
sys.path.insert(0, str(tree_root / "tools" / "audit_202608"))
sys.path.insert(0, str(tree_root / "tools"))
sys.path.insert(0, str(tree_root))

import capability_test as cap  # noqa: E402
import catalyst_research as cr  # noqa: E402
import rs2_data  # noqa: E402


class BlockedSocket(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("blocked")

    def connect(self, *a, **k):
        raise RuntimeError("blocked")


socket.socket = BlockedSocket

STUB_ROWS = [
    {"date": "2026-09-20", "source": "reuters", "title": "GE Vernova wins turbine order",
     "url": "https://example.com/a", "snippet": "GE Vernova secured a large turbine order.",
     "excerpt": "GE Vernova secured a large turbine order from a European utility, the company said.",
     "read_from": "https://example.com/a"},
    {"date": "2026-09-18", "source": "bloomberg", "title": "Analysts raise GEV price target",
     "url": "https://example.com/b", "snippet": "Analysts raised price targets on GEV."},
    {"source": "prnewswire", "title": "GE Vernova reaffirms guidance",
     "url": "https://example.com/c", "snippet": "GE Vernova reaffirmed its FY guidance."},
]


def fake_fetch(company, t):
    return {"date": "2026-09-27", "rows": STUB_ROWS, "unresponsive_engines": [], "errors": []}


cap.company_news.fetch = fake_fetch
cap.sec_guidance.latest_earnings_release = lambda *a, **k: None
cap.world_news.digest = lambda *a, **k: None
sys.modules["industry_taxonomy"] = None

FIXED_LOCAL = _real_datetime(2026, 9, 27, 12, 0, 0)


class FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FIXED_LOCAL.astimezone(tz)
        return FIXED_LOCAL


for mod in (cap, rs2_data):
    mod.datetime = FrozenDatetime

if supports_news_snippets:
    pack_text = str(cap.build_pack("GEV", include_research=False, news_snippets=True))
else:
    pack_text = str(cap.build_pack("GEV", include_research=False))

sec25 = cr._slice_section(pack_text, "## DATA 2.5") or cr._slice_section(pack_text, "## SECTION 2.5")
news = cr._slice_section(pack_text, "## RECENT COMPANY NEWS")
est = cr._slice_consensus_estimates(pack_text)
guidance = cr._slice_guidance(pack_text)

out_path.write_text(json.dumps({
    "section_2_5": sec25, "recent_news": news, "consensus_estimates": est, "guidance": guidance,
}, indent=1), encoding="utf-8")

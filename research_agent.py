#!/usr/bin/env python3
"""
research_agent.py — agentic web research (Bucket C of the plan).

Wraps AgentWebSearch (real Chrome via CDP, no API keys) to produce a per-ticker
RESEARCH BRIEF covering the qualitative layers the screener does NOT have:
  - Recent news & catalysts        (RS2 Layer 7 / top_catalyst)
  - Earnings / guidance narrative   (Layer 2-3 context)
  - Short-seller / activist reports (Layer 9 adversarial data)
  - Regulatory / legal events       (Engine 5 binary, Layer 7 risks)
  - Competitive dynamics            (Layer 3.5 second-order effects)

GROUNDING (news-soundness): the brief is assembled DETERMINISTICALLY from the
search engine's own results — title + snippet + real URL straight from Chrome.
No LLM rewrites the links, so there are no fabricated sources. The downstream
rs2-analyst is instructed (DATA DISCIPLINE) to cite only these URLs.

Must run with the AgentWebSearch venv python (has httpx/websocket-client/bs4).
run_rs2.py invokes it as a subprocess and passes the resolved company name.

CLI:  <venv-python> research_agent.py NVDA "NVIDIA Corporation"
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# Make AgentWebSearch importable + start Chrome on demand.
AWS_DIR = Path(CONFIG["agentwebsearch_dir"])
sys.path.insert(0, str(AWS_DIR))

PORTALS = ["google", "brave"]          # skip Naver for US/global equities
ITEMS_PER_SECTION = 6
# Domains that add noise rather than analyzable news.
DROP_DOMAINS = ("youtube.com", "youtu.be", "tiktok.com", "facebook.com",
                "pinterest.com", "instagram.com", "reddit.com/r/")


def ensure_chrome():
    import chrome_launcher as cl
    for portal in PORTALS:
        port = cl.CHROME_INSTANCES[portal]["port"]
        if not cl.is_chrome_running(port):
            cl.start_chrome(portal)


def _clean(results):
    """Dedup by URL, drop junk domains/empty, keep order."""
    seen, out = set(), []
    for r in results:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        if any(d in url.lower() for d in DROP_DOMAINS):
            continue
        key = re.sub(r"[#?].*$", "", url).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "url": url,
                    "snippet": (r.get("snippet") or "").strip(),
                    "source": r.get("source") or ""})
    return out


def run_query(keyword):
    from cdp_search import search_parallel
    try:
        results = search_parallel(keyword, PORTALS)
        return _clean([{"url": r.url, "title": r.title,
                        "snippet": r.snippet, "source": r.source} for r in results])
    except Exception as e:
        return [{"title": f"[search error: {str(e)[:120]}]", "url": "", "snippet": "", "source": ""}]


def build_queries(ticker, name):
    subj = f"{name} ({ticker})" if name else ticker
    yr = datetime.now().year
    return [
        ("Recent News & Catalysts",        f"{subj} stock news {yr}"),
        ("Earnings / Guidance",            f"{subj} latest earnings results guidance outlook {yr}"),
        ("Capex / Segment Revenue",        f"{subj} capital expenditure capex guidance segment revenue breakdown {yr}"),
        ("Backlog / RPO",                  f"{subj} backlog remaining performance obligations RPO orders {yr}"),
        ("Short-Seller / Activist / Forensic", f"{subj} short seller report OR activist investor OR accounting concerns"),
        ("Regulatory / Legal",             f"{subj} regulatory investigation antitrust lawsuit ruling {yr}"),
        ("Competitive Dynamics",           f"{subj} competition market share competitive threat rivals"),
    ]


def section_md(title, items):
    L = [f"### {title}"]
    if not items:
        L.append("- (no results returned)")
    for it in items[:ITEMS_PER_SECTION]:
        snip = it["snippet"][:240].replace("\n", " ")
        src = f" [{it['source']}]" if it["source"] else ""
        if it["url"]:
            L.append(f"- **{it['title'][:140]}**{src} — {snip}\n  Source: {it['url']}")
        else:
            L.append(f"- {it['title']}")
    L.append("")
    return "\n".join(L)


def build_brief(ticker, name):
    ensure_chrome()
    t = ticker.upper()
    header = [
        f"# RESEARCH BRIEF — {name + ' ' if name else ''}({t})",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"Source: agentic web search (Google + Brave via Chrome CDP)",
        "All items below are raw search results with real source URLs. "
        "Cite only these URLs; do not assert news not listed here.",
        "",
    ]
    body = []
    for title, q in build_queries(t, name):
        body.append(section_md(title, run_query(q)))
    return "\n".join(header + body)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: research_agent.py <TICKER> [Company Name]", file=sys.stderr)
        sys.exit(1)
    ticker = sys.argv[1].upper()
    name = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else ""
    md = build_brief(ticker, name)
    out_dir = Path(CONFIG["out_research_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}.md"
    path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n-> {path}", file=sys.stderr)

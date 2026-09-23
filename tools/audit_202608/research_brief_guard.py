#!/usr/bin/env python3
"""research_brief_guard.py — Harness verification for research briefs (Charter v3.1 / Phase 4 D8).

The brief must name the company: its legal name alone is enough; a ticker-only match
additionally needs a sector or industry word (tickers can be ordinary words).
A mismatch flags `research_wrong_company`, refuses snapshotting as valid, and triggers
re-generation or fallback to --no-research semantics.
"""
from __future__ import annotations

import re
from pathlib import Path
import rs2_data

# The fixed header line deep_research.py now writes as the brief's first line (P4 T4 / D4, D8,
# E3): "Company: <legal name> | Ticker: <T> | Industry: <industry>". Only searched near the top
# of the brief (not the whole text) so a coincidental later occurrence never counts as the header.
_HEADER_RE = re.compile(
    r"^Company:\s*(?P<name>.+?)\s*\|\s*Ticker:\s*(?P<ticker>[A-Za-z][A-Za-z.\-]{0,9})\s*\|\s*"
    r"Industry:\s*(?P<industry>.+?)\s*$",
    re.MULTILINE)


def _header_company_match(brief_text: str, ticker: str, company_name: str | None) -> bool:
    """True when the brief's own header line names this exact ticker and legal name.

    An exact match here is the strong signal deep_research.py was asked to provide, so it is
    sufficient on its own (no sector/industry word needed) — unlike a name match found by
    scanning the free-text body, which still had to fall back to the industry-word check.
    """
    if not company_name:
        return False
    m = _HEADER_RE.search(brief_text[:500])
    if not m:
        return False
    if m.group("ticker").strip().upper() != ticker.upper():
        return False
    norm = lambda s: re.sub(r"\s+", " ", s.strip()).lower()
    return norm(m.group("name")) == norm(company_name)


def check_research_brief(
    ticker: str,
    brief_text: str | None = None,
    company_name: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
) -> tuple[bool, str | None]:
    """(ok: bool, reason: str | None)

    Checks:
      1. Brief contains ticker or legal company name.
      2. Brief contains at least one word from the sector or industry.
    """
    t = ticker.upper()
    if brief_text is None:
        r_dir = rs2_data.CONFIG.get("out_research_dir") or "research"
        r_path = Path(r_dir)
        if not r_path.is_absolute():
            here = Path(__file__).resolve().parents[2]
            r_path = here / r_path
        brief_file = r_path / f"{t}.md"
        if not brief_file.exists():
            return True, None
        brief_text = brief_file.read_text(encoding="utf-8", errors="replace")

    if not brief_text or not brief_text.strip():
        return True, None

    if company_name is None:
        company_name = rs2_data.resolve_name(t)

    # 0. Header check (preferred): the brief's own "Company: ... | Ticker: ... | Industry: ..."
    # line, when present, names the exact ticker and legal name deep_research.py resolved before
    # ever starting a search — that is stronger evidence than anything found later in free text,
    # so an exact match there is sufficient and skips the sector/industry word check below.
    if _header_company_match(brief_text, t, company_name):
        return True, None

    # 1. Company check: brief text must contain ticker or legal name
    has_ticker = bool(re.search(rf"\b{re.escape(t)}\b", brief_text, re.IGNORECASE))
    has_name = False
    if company_name:
        clean_name = company_name.strip()
        has_name = bool(re.search(rf"\b{re.escape(clean_name)}\b", brief_text, re.IGNORECASE))
        if not has_name:
            # Strip legal corporate suffixes like Inc., Corp., Ltd., Co., LLC, PLC, Class A
            base_name = re.sub(
                r",?\s*(?:Inc\.?|Corp(?:oration)?\.?|Ltd\.?|Co\.?|LLC|PLC|Class\s+[A-Z])\s*$",
                "", clean_name, flags=re.IGNORECASE
            ).strip()
            if base_name and len(base_name) >= 3:
                has_name = bool(re.search(rf"\b{re.escape(base_name)}\b", brief_text, re.IGNORECASE))

    if not (has_ticker or has_name):
        return False, f"brief text does not contain ticker '{t}' or company name '{company_name}'"

    # 2. Industry or Sector check: brief text must contain an industry or sector word
    if sector is None or industry is None:
        sec_lookup, ind_lookup = rs2_data.sector_lookup(t)
        if sector is None:
            sector = sec_lookup
        if industry is None:
            industry = ind_lookup

    words_to_check = set()
    stop_words = {"and", "the", "for", "with", "other", "services", "general", "non", "all", "etc"}
    for source in (sector, industry):
        if source:
            for w in re.findall(r"[A-Za-z]{3,}", source.lower()):
                if w not in stop_words:
                    words_to_check.add(w)
                    if w.endswith("ies"):
                        words_to_check.add(w[:-3] + "y")
                    elif w.endswith("s"):
                        words_to_check.add(w[:-1])
            if "technology" in source.lower():
                words_to_check.add("tech")
            if "semiconductor" in source.lower():
                words_to_check.add("semi")
                words_to_check.add("semis")

    # Decision (orchestrator, 2026-09-24): the company NAME is the strong signal. A correct brief
    # often never uses the vendor's industry label (GEV's brief speaks of power, grid and
    # turbines, never "industrial machinery"), so a name match is enough. A ticker-only match is
    # weak (CART, NOW, ALL, ON are English words), so it additionally needs a sector/industry word.
    if has_name:
        return True, None
    if words_to_check:
        has_sec_ind = any(re.search(rf"\b{re.escape(w)}\b", brief_text, re.IGNORECASE) for w in words_to_check)
        if not has_sec_ind:
            return False, (f"brief matches only the ticker '{t}' (not the company name '{company_name}') "
                           f"and contains no sector/industry word (checked: {sorted(words_to_check)})")
    return True, None

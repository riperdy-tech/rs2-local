#!/usr/bin/env python3
"""sec_guidance.py — company guidance extracted directly from SEC EDGAR 8-K Item 2.02 filings.

Extracts the company's own dated words from its latest earnings release exhibit (EX-99.1,
EX-99.01, EX-99), filtering for outlook, guidance, backlog, bookings, and orders.
"""
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

SUB_CACHE = HERE / "cache" / "sec_submissions"
SEC_8K_CACHE = HERE / "cache" / "sec_8k"
UA = {"User-Agent": "RS2-Local research riperdy@gmail.com"}

PAT_OUTLOOK = re.compile(
    r'\b(outlook|guidance|expects?|expected to|reaffirm\w*|rais(es|ed|ing)|backlog|remaining performance obligations?|book-to-bill|bookings|orders)\b',
    re.IGNORECASE,
)
PAT_FORWARD = re.compile(
    r'\b(outlook|guidance|expects?|expected to|reaffirm\w*|rais(es|ed|ing))\b',
    re.IGNORECASE,
)
PAT_SAFE_HARBOR = re.compile(
    r'forward-looking statements|safe harbor|risks and uncertainties|undertakes no (intent|obligation)',
    re.IGNORECASE,
)


def _submissions(cik):
    """SEC submissions JSON, cached per UTC day. None on any failure — a missing feed must
    degrade to 'no filing trigger today', never to a crash or a fabricated trigger."""
    SUB_CACHE.mkdir(parents=True, exist_ok=True)
    p = SUB_CACHE / f"CIK{cik}.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("_fetched_utc", "")[:10] == today:
                return d
        except Exception:
            pass
    try:
        req = urllib.request.Request(
            f"https://data.sec.gov/submissions/CIK{cik}.json", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        d["_fetched_utc"] = datetime.now(timezone.utc).isoformat()
        p.write_text(json.dumps(d), encoding="utf-8")
        time.sleep(0.15)          # stay far under SEC's 10 req/s ceiling
        return d
    except Exception:
        return None


def _has_item_202(val) -> bool:
    if not val:
        return False
    if isinstance(val, (list, tuple)):
        return any(_has_item_202(x) for x in val)
    parts = re.split(r'[,;\s]+', str(val).strip())
    return "2.02" in parts


def _clean_html(raw_html: str) -> str:
    """Strip scripts, styles, comments, HTML tags, unescape entities, and collapse whitespace."""
    text = re.sub(r'(?is)<script\b.*?</script>', ' ', raw_html)
    text = re.sub(r'(?is)<style\b.*?</style>', ' ', text)
    text = re.sub(r'(?is)<!--.*?-->', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def latest_earnings_release(cik, asof=None) -> dict | None:
    """Find and fetch the latest 8-K (Item 2.02) earnings release exhibit for a CIK.

    Returns {"accession", "filing_date", "url", "text"} or None on failure.
    Caches forever in cache/sec_8k/<CIK>_<accession>.json.
    """
    if not cik:
        latest_earnings_release.last_reason = "no CIK"
        return None

    subs = _submissions(cik)
    if not subs:
        print(f"[sec_guidance] failed to retrieve submissions for CIK {cik}", file=sys.stderr)
        latest_earnings_release.last_reason = "SEC fetch failed"
        return None

    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    dates = rec.get("filingDate") or []
    items = rec.get("items") or []
    accs = rec.get("accessionNumber") or []

    asof_limit = asof.isoformat()[:10] if hasattr(asof, "isoformat") else (str(asof)[:10] if asof is not None else None)

    candidates = []
    for i in range(len(forms)):
        f = forms[i] if i < len(forms) else ""
        if f not in ("8-K", "8-K/A"):
            continue
        dt = dates[i] if i < len(dates) else ""
        if asof_limit is not None and dt > asof_limit:
            continue
        it = items[i] if i < len(items) else ""
        if not _has_item_202(it):
            continue
        acc = accs[i] if i < len(accs) else ""
        if not acc:
            continue
        candidates.append((dt, i, acc))

    if not candidates:
        target_date = asof_limit or datetime.now().strftime("%Y-%m-%d")
        latest_earnings_release.last_reason = f"no 8-K Item 2.02 on or before {target_date}"
        return None

    candidates.sort(key=lambda c: (c[0], -c[1]), reverse=True)
    filing_date, _, accession = candidates[0]

    cik_str = str(cik).zfill(10) if str(cik).isdigit() else str(cik)
    cache_file = SEC_8K_CACHE / f"{cik_str}_{accession}.json"
    if not cache_file.exists() and (SEC_8K_CACHE / f"{cik}_{accession}.json").exists():
        cache_file = SEC_8K_CACHE / f"{cik}_{accession}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            latest_earnings_release.last_reason = None
            return cached
        except Exception as e:
            print(f"[sec_guidance] failed reading cache {cache_file}: {e}", file=sys.stderr)

    try:
        int_cik = int(cik)
    except (ValueError, TypeError):
        int_cik = cik
    acc_no_dash = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int_cik}/{acc_no_dash}/{accession}.txt"

    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_data = resp.read().decode("utf-8", "replace")
        time.sleep(0.2)
    except Exception as e:
        print(f"[sec_guidance] failed fetching {url}: {e}", file=sys.stderr)
        latest_earnings_release.last_reason = "SEC fetch failed"
        return None

    docs = re.findall(r'<DOCUMENT>(.*?)</DOCUMENT>', raw_data, flags=re.DOTALL | re.IGNORECASE)
    if not docs:
        docs = re.split(r'(?i)<DOCUMENT>', raw_data)[1:]

    doc_by_type = {}
    for doc in docs:
        m = re.search(r'<TYPE>\s*([^\r\n<]+)', doc, flags=re.IGNORECASE)
        if m:
            t = m.group(1).strip().upper()
            if t not in doc_by_type:
                doc_by_type[t] = doc

    chosen_doc = (doc_by_type.get("EX-99.1") or
                  doc_by_type.get("EX-99.01") or
                  doc_by_type.get("EX-99"))

    if not chosen_doc:
        print(f"[sec_guidance] no EX-99 exhibit found in {accession}", file=sys.stderr)
        latest_earnings_release.last_reason = "SEC fetch failed"
        return None

    tm = re.search(r'<TEXT>(.*?)</TEXT>', chosen_doc, flags=re.DOTALL | re.IGNORECASE)
    raw_doc_text = tm.group(1) if tm else chosen_doc
    cleaned_text = _clean_html(raw_doc_text)

    res = {
        "accession": accession,
        "filing_date": filing_date,
        "url": url,
        "text": cleaned_text,
    }

    try:
        SEC_8K_CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[sec_guidance] failed writing cache {cache_file}: {e}", file=sys.stderr)

    latest_earnings_release.last_reason = None
    return res


def earnings_releases(cik, asof=None, days=365, limit=4) -> list:
    """The company's 8-K Item 2.02 earnings releases filed within `days` before `asof` (newest first, at most `limit`), each as
    latest_earnings_release returns it. Stepping `asof` back to the day before each filing reuses that function's selection and cache."""
    from datetime import date, timedelta
    end = date.fromisoformat(asof.isoformat()[:10] if hasattr(asof, "isoformat") else (str(asof)[:10] if asof is not None else datetime.now().strftime("%Y-%m-%d")))
    floor = (end - timedelta(days=days)).isoformat()
    out, at = [], end
    while len(out) < limit:
        rel = latest_earnings_release(cik, asof=at.isoformat())
        if not rel or (rel.get("filing_date") or "") < floor:
            break
        out.append(rel)
        at = date.fromisoformat(rel["filing_date"]) - timedelta(days=1)
    return out


def guidance_excerpt(text: str, cap: int = 3000) -> str:
    """Extract first 400 chars and guidance/backlog/orders sentences from exhibit text."""
    if not text:
        return ""

    lead = text[:400].strip()
    if lead and len(f"- {lead}") > cap:
        return ""

    # Candidates in document order. Forward-looking sentences (outlook, guidance, expects,
    # reaffirms, raises) are selected BEFORE backlog/orders/bookings sentences: measured
    # 2026-09-24, DXC's and GEV's releases list segment bookings and orders first, and the
    # document-order fill spent the whole cap on them — DXC's full-year guidance line was cut
    # mid-word and GEV's raised guidance never appeared. The output is still in document order.
    cands, seen = [], set()
    for idx, s in enumerate(re.split(r'(?<=[.;])\s+(?=[A-Z•])', text)):
        s = s.strip()
        if (not s or s in seen or len(s) >= 700 or not PAT_OUTLOOK.search(s)
                or not re.search(r'\d', s) or PAT_SAFE_HARBOR.search(s)):
            continue
        seen.add(s)
        cands.append((idx, s, 0 if PAT_FORWARD.search(s) else 1))

    # The lead is dropped when a selected-anyway sentence already carries its opening words
    # (DXC's release headline repeated as its first bullet).
    lead_key = re.sub(r"\s+", " ", lead[:120]) if lead else ""
    lead_dup = bool(lead_key) and any(lead_key[:80] in re.sub(r"\s+", " ", s) for _, s, _ in cands)
    budget = cap - (0 if (not lead or lead_dup) else len(f"- {lead}") + 1)

    chosen = []
    for group in (0, 1):
        for idx, s, g in cands:
            if g != group:
                continue
            line_len = len(f"- {s}") + 1
            if line_len > budget:
                continue
            chosen.append((idx, s))
            budget -= line_len

    lines = [] if (not lead or lead_dup) else [f"- {lead}"]
    lines += [f"- {s}" for _, s in sorted(chosen)]
    return "\n".join(lines)

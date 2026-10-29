"""packet.py - the input contract `m3m.packet.v1` of qwen_c (SPEC_m3m_qwen_pipeline.md §3).

`build(ticker, T, screener_commit, online=..., verified_record=...)` freezes, for one ticker and one decision time T, the screener's row
(git blobs at a verified commit) and the company's own SEC documents (through sec_store) into one packet dict. `canonical_bytes` is the one
byte form a packet is stored and hashed in. `build` reads no clock: T is an argument, and with online=False over the same store and commit
it gives byte-identical output.

ELIGIBILITY. A filing is used only when effective_at(accepted_at(acceptanceDateTime)) <= T (policy SEC_POLICY, re-implemented from
m3l_sec_pit_asof.py; no cross-repository import). An ineligible filing that would otherwise have been chosen for a slot is listed in
`excluded` with its accession and effective_at.

EVIDENCE, in this fixed order (ids S0, then F1..., then P1..., sequential within their letter):
  S0 screener_row       the stocks.json record and the factor_scores_dual_door.json profile, rendered as `key: value` lines (0 prints as 0)
  F  statement          balance sheet, income statement, cash flows: FilingSummary R reports of the latest eligible 10-Q/10-K/20-F/40-F
  P  annual_section     Business, Risk Factors, MD&A of the latest eligible 10-K / 20-F / 40-F
  P  quarterly_section  MD&A and Part II Item 1A of the latest eligible 10-Q accepted after that annual report
  P  release            the latest eligible 8-K Item 2.02 EX-99 release (sec_primary.select_text rules)
  P  other_8k           eligible 8-Ks of the OTHER_8K_DAYS before T with a listed item, newest first, at most MAX_OTHER_8K
A section is found only by its heading in the cleaned text and ends at the next item heading; a heading followed by under TOC_MIN_CHARS
characters before the next item heading is a table-of-contents entry and is skipped. A section or statement that cannot be found is an
annotation, never a guess and never a whole-document fallback. Every cut is marked with sec_primary.OMIT.

REFUSALS (PacketRefused; a degraded packet is never built): an excluded ticker; a screener commit that is not on a PASS / pair PASS row of
the verified record; a ticker missing from that commit's stocks.json or from its factor profiles; no CIK; a screener commit dated after T.
A document that cannot be had (NotInStore offline, FetchFailed online, StoreCorrupt) raises too.
"""
import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from sec_guidance import _has_item_202
from sec_primary import (_is_text_exhibit, _items_list, _main_exhibit, _release_doc, _split_documents, blocks_of, canonical,
                         prefix_text, select_text)

from qwen_c import sec_store

CONTRACT = "m3m.packet.v1"
BUILDER_VERSION = "m3m.packet.builder.v1"
SEC_POLICY = "sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1"
EXCLUDED_TICKERS = ("MG", "MOV", "SENEA", "SENEB")

REPO = Path(__file__).resolve().parent.parent
PACKETS_DIR = REPO / "cache" / "m3m" / "packets"

STOCKS_PATH = "public/data/stocks.json"
FACTOR_PATH = "public/data/factor_scores_dual_door.json"
CIK_MAP_PATH = "public/data/cik_map.json"

TOTAL_CAP = 140_000
STATEMENT_CAP = 8_000
RELEASE_CAP = 14_000
OTHER_8K_CAP = 4_000
OTHER_8K_DAYS = 120
MAX_OTHER_8K = 4
OTHER_8K_ITEMS = ("1.01", "1.03", "2.01", "2.03", "2.04", "2.06", "3.01", "4.01", "4.02", "5.02", "8.01")
TOC_MIN_CHARS = 1_500
SHORT_MIN_CHARS = 100            # a short section kept only as the last of two or more headings (find_section)
MIN_TRIMMED = 600

PERIODIC_FORMS = ("10-Q", "10-K", "20-F", "40-F")
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
EIGHT_K_FORMS = ("8-K", "8-K/A")

EASTERN = ZoneInfo("America/New_York")
_CAL = []


class PacketError(Exception):
    pass


class PacketRefused(PacketError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# ---- the acceptance rule (m3l_sec_pit_asof.py, policy SEC_POLICY) --------------------------------------------------------------

def _calendar():
    if not _CAL:
        # explicit bounds: the library's default bounds are relative to today, and a build must not depend on the clock
        _CAL.append(xcals.get_calendar("XNYS", start="2005-01-01", end="2031-12-31"))
    return _CAL[0]


def accepted_at(value):
    """SEC acceptanceDateTime as UTC. A Z-suffixed clock has been reported both as UTC and as Eastern wall clock mislabeled Z; until a
    filing header corroborates it, the LATER reading is used so that a filing is never selected too early. A naive clock is Eastern."""
    if not isinstance(value, str) or not value:
        raise ValueError("SEC acceptanceDateTime missing")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EASTERN).astimezone(timezone.utc)
    as_utc = dt.astimezone(timezone.utc)
    as_eastern_wall = dt.replace(tzinfo=None).replace(tzinfo=EASTERN).astimezone(timezone.utc)
    return max(as_utc, as_eastern_wall)


def _accepted_earliest(value):
    """The EARLIER reading of the same clock: used only to decide that a filing existed at T and so belongs in `excluded`."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EASTERN).astimezone(timezone.utc)
    return min(dt.astimezone(timezone.utc), dt.replace(tzinfo=None).replace(tzinfo=EASTERN).astimezone(timezone.utc))


def effective_at(accepted_utc, calendar=None):
    """The open of the first full NYSE session after the acceptance's Eastern date; at or after 17:30 ET one more session. A policy proxy
    for public dissemination, never an observed first-public time."""
    calendar = calendar or _calendar()
    loc = accepted_utc.astimezone(EASTERN)
    target = pd.Timestamp(loc.date() + timedelta(days=1))
    session = calendar.date_to_session(target, direction="next")
    if loc.time() >= time(17, 30):
        session = calendar.next_session(session)
    return calendar.session_open(session).to_pydatetime().astimezone(timezone.utc)


def _z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_T(T):
    """T as an aware UTC datetime of whole seconds (an ISO string or an aware datetime)."""
    dt = datetime.fromisoformat(T.replace("Z", "+00:00")) if isinstance(T, str) else T
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError("T must be a timezone-aware time")
    if dt.microsecond:
        raise ValueError("T must be whole seconds")
    return dt.astimezone(timezone.utc)


def t_compact(T):
    return parse_T(T).strftime("%Y%m%dT%H%M%SZ")


# ---- bytes, git and the screener ------------------------------------------------------------------------------------------------

def canonical_bytes(packet):
    return json.dumps(packet, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def packet_sha256(packet):
    return hashlib.sha256(canonical_bytes(packet)).hexdigest()


def _decode(data):
    """Document bytes as text: UTF-8 when they are valid UTF-8, else Windows-1252 (EDGAR HTML often carries raw 0x92 quote bytes)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def screener_repo():
    """The screener clone, through paths.py (key `screener_publish_repo`, the dedicated clone; never a written path)."""
    import paths
    return paths.resolve("screener_publish_repo", paths.load_config())


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if r.returncode != 0:
        raise PacketError(f"git {' '.join(args)} failed in {repo}: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout


def _resolve_commit(repo, commit):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{10,40}", commit):
        raise PacketRefused("screener_commit_invalid", f"{commit!r} is not 10 to 40 hex characters")
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{commit.lower()}^{{commit}}").decode("ascii").strip()


def verified_row(rows, commit_full):
    """The first row of a check_new_runs record that verifies `commit_full`: verdict PASS, pair PASS, and output_commit (at least 10 hex
    characters) a prefix of the commit. Refuses when none does."""
    if not isinstance(rows, list):
        raise PacketRefused("screener_commit_not_verified", "the verified record is not a list of rows")
    for r in rows:
        if not isinstance(r, dict):
            continue
        oc = r.get("output_commit")
        if (r.get("verdict") == "PASS" and r.get("pair") == "PASS" and isinstance(oc, str)
                and re.fullmatch(r"[0-9a-fA-F]{10,40}", oc) and commit_full.startswith(oc.lower())):
            return r
    raise PacketRefused("screener_commit_not_verified", f"{commit_full} is on no PASS / pair PASS row of the verified record")


def _fmt(v):
    """A JSON value as S0 prints it: 0 and 0.0 print as 0, null as null, a float in its shortest round-trip form."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return "0" if v == 0 else repr(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items()) + "}"
    return str(v)


def _kv_lines(obj, prefix=""):
    out = []
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out += _kv_lines(v, key + ".")
        else:
            out.append(f"{key}: {_fmt(v)}")
    return out


def _screener(repo, commit_full, ticker):
    """(S0 item, header fields, cik) from the screener blobs at `commit_full`, or a refusal."""
    blobs, shas = {}, {}
    for path in (STOCKS_PATH, FACTOR_PATH, CIK_MAP_PATH):
        blobs[path] = _git(repo, "show", f"{commit_full}:{path}")
        shas[path] = _git(repo, "rev-parse", f"{commit_full}:{path}").decode("ascii").strip()
    stocks = json.loads(blobs[STOCKS_PATH])
    rows = [r for r in stocks if isinstance(r, dict) and r.get("symbol") == ticker]
    if not rows:
        raise PacketRefused("ticker_not_in_stocks", f"{ticker} is not in {STOCKS_PATH} at {commit_full}")
    if len(rows) > 1:
        raise PacketError(f"{ticker} has {len(rows)} rows in {STOCKS_PATH} at {commit_full}")
    profiles = (json.loads(blobs[FACTOR_PATH]) or {}).get("profiles")
    if not isinstance(profiles, dict) or not isinstance(profiles.get(ticker), dict):
        raise PacketRefused("ticker_not_in_factor_profiles", f"{ticker} has no profile in {FACTOR_PATH} at {commit_full}")
    cmap = json.loads(blobs[CIK_MAP_PATH]) or {}
    cmap = cmap.get("map") if isinstance(cmap.get("map"), dict) else cmap
    raw_cik = cmap.get(ticker)
    if not raw_cik or not str(raw_cik).strip().isdigit():
        raise PacketRefused("no_cik", f"{ticker} has no CIK in {CIK_MAP_PATH} at {commit_full}")
    cik = str(raw_cik).strip().zfill(10)
    lines = [f"stocks.json record ({STOCKS_PATH} at {commit_full}):"] + _kv_lines(rows[0])
    lines += [f"factor_scores_dual_door.json profile ({FACTOR_PATH} at {commit_full}):"] + _kv_lines(profiles[ticker])
    s0 = {"kind": "screener_row", "name": "screener_row", "title": "Screener row: stocks.json record and factor_scores_dual_door.json profile",
          "source": {"git_commit": commit_full, "path": [STOCKS_PATH, FACTOR_PATH]}, "form": None, "period": None,
          "accepted_raw": None, "effective_at": None,
          "raw_sha256": [hashlib.sha256(blobs[STOCKS_PATH]).hexdigest(), hashlib.sha256(blobs[FACTOR_PATH]).hexdigest()],
          "text": canonical("\n".join(lines))}
    header = {"commit": commit_full, "stocks_blob_sha": shas[STOCKS_PATH], "factor_blob_sha": shas[FACTOR_PATH],
              "cik_map_blob_sha": shas[CIK_MAP_PATH]}
    return s0, header, cik


# ---- SEC documents --------------------------------------------------------------------------------------------------------------

class _Inputs:
    """The document reader of one build: bytes by url, every url used recorded once, in first-use order, with the sha256 of its bytes."""

    def __init__(self, get):
        self._get = get
        self.used = []
        self._seen = {}

    def __call__(self, url):
        data = self._get(url)
        sha = hashlib.sha256(data).hexdigest()
        if url in self._seen:
            if self._seen[url] != sha:
                raise PacketError(f"{url} gave two different byte strings in one build")
        else:
            self._seen[url] = sha
            self.used.append({"url": url, "sha256": sha})
        return data


def _base(cik, accession):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"


def _filing_rows(subs):
    """The recent filings of a submissions JSON, one dict each, with their acceptance read by the policy (an unreadable clock: None)."""
    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    out = []
    for i, form in enumerate(forms):
        def col(name):
            v = rec.get(name) or []
            return v[i] if i < len(v) else ""
        acc = col("accessionNumber")
        if not acc:
            continue
        raw = col("acceptanceDateTime")
        try:
            accepted, earliest = accepted_at(raw), _accepted_earliest(raw)
        except (ValueError, TypeError):
            accepted = earliest = None
        out.append({"form": form, "accession": acc, "filed": col("filingDate"), "report_date": col("reportDate") or None,
                    "items": col("items"), "primary_document": col("primaryDocument"), "accepted_raw": raw,
                    "accepted": accepted, "earliest": earliest, "effective": effective_at(accepted) if accepted else None})
    return out


def _pick(rows, pred, slot, T, excluded, notes, limit=1):
    """The newest `limit` eligible rows satisfying `pred`, newest first. A newer ineligible row that existed at T is listed in `excluded`;
    a row with an unreadable acceptance clock is never used and is annotated."""
    cands = [r for r in rows if pred(r)]
    for r in cands:
        if r["accepted"] is None:
            notes.append(f"acceptance_unreadable: {slot} {r['accession']}")
    cands = sorted([r for r in cands if r["accepted"] is not None], key=lambda r: (r["accepted"], r["accession"]), reverse=True)
    chosen = []
    for r in cands:
        if len(chosen) >= limit:
            break
        if r["effective"] <= T:
            chosen.append(r)
        elif r["earliest"] <= T:
            excluded.append({"slot": slot, "accession": r["accession"], "form": r["form"], "accepted_raw": r["accepted_raw"],
                             "effective_at": _z(r["effective"])})
    return chosen


def _evidence(kind, name, title, row, url, raw, text):
    return {"kind": kind, "name": name, "title": title, "source": {"accession": row["accession"], "url": url}, "form": row["form"],
            "period": row["report_date"], "accepted_raw": row["accepted_raw"], "effective_at": _z(row["effective"]),
            "raw_sha256": hashlib.sha256(raw).hexdigest(), "text": text}


# -- FilingSummary statements

_STATEMENTS = ("balance_sheet", "income_statement", "cash_flows")
_STATEMENT_TITLE = {"balance_sheet": "balance sheet", "income_statement": "income statement", "cash_flows": "cash flow statement"}
_INCOME_WORD = re.compile(r"\b(income|operations|earnings|profit or loss|loss)\b", re.I)


def _reports(summary_xml):
    """[(ShortName, HtmlFileName, MenuCategory)] of a FilingSummary.xml in file order (sec_primary._short_names plus the category)."""
    out = []
    for m in re.finditer(r"<Report\b[^>]*>(.*?)</Report>", summary_xml, flags=re.S | re.I):
        b = m.group(1)
        sn = re.search(r"<ShortName>(.*?)</ShortName>", b, flags=re.S | re.I)
        hf = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", b, flags=re.S | re.I)
        mc = re.search(r"<MenuCategory>(.*?)</MenuCategory>", b, flags=re.S | re.I)
        if sn and hf:
            out.append((html.unescape(re.sub(r"\s+", " ", sn.group(1))).strip(), hf.group(1).strip(),
                        mc.group(1).strip() if mc else None))
    return out


def _income_rank(name):
    """0: an income statement; 1: a statement of comprehensive income only (used when the filer has no separate one); None: neither."""
    n = re.sub(r"retained earnings", "", name, flags=re.I)
    if re.search(r"\b(equity|cash flows?|financial position|balance sheets?|deficit)\b", n, re.I):
        return None
    m = _INCOME_WORD.search(n)
    c = re.search(r"\bcomprehensive\b", n, re.I)
    if m and (c is None or m.start() < c.start()):
        return 0
    if c and m and not re.search(r"\bother\s+comprehensive\b", n, re.I):
        return 1
    return None


def pick_statements(summary_xml):
    """{name: (ShortName, HtmlFileName)} of the balance sheet, income statement and cash flows among the primary statements (MenuCategory
    "Statements" when the summary has categories), by ShortName, never a parenthetical or a details report; first match in file order."""
    reps = _reports(summary_xml)
    if any(c is not None for _, _, c in reps):
        reps = [r for r in reps if (r[2] or "").lower() == "statements"]
    reps = [r for r in reps if not re.search(r"parenthetical|\bdetails?\b|\btables?\b|polic(y|ies)", r[0], re.I)]
    out = {}
    for sn, hf, _ in reps:
        if "balance_sheet" not in out and re.search(r"balance sheets?|financial position|financial condition|statements? of condition", sn, re.I):
            out["balance_sheet"] = (sn, hf)
        if "cash_flows" not in out and re.search(r"cash flows?", sn, re.I):
            out["cash_flows"] = (sn, hf)
    for rank in (0, 1):
        for sn, hf, _ in reps:
            if "income_statement" not in out and _income_rank(sn) == rank:
                out["income_statement"] = (sn, hf)
    return out


def _flatten_report(raw_text):
    """An R report as sec_primary flattens a segment table: one line per table row (cells joined by ' | '), paragraphs as lines."""
    rows = []
    for k, c in blocks_of(raw_text):
        rows += c if k == "t" else [c]
    return "\n".join(rows)


def _statements(cik, row, fetch, notes):
    base = _base(cik, row["accession"])
    url = f"{base}/FilingSummary.xml"
    summary = _decode(fetch(url))
    picks = pick_statements(summary)
    out = []
    for name in _STATEMENTS:
        if name not in picks:
            notes.append(f"statement_not_found: {name} {row['accession']}")
            continue
        sn, hf = picks[name]
        if not hf.lower().endswith(".htm"):
            notes.append(f"statement_not_html: {name} {row['accession']} {hf}")
            continue
        rurl = f"{base}/{hf}"
        raw = fetch(rurl)
        text = canonical(prefix_text(_flatten_report(_decode(raw)), STATEMENT_CAP))
        if not text:
            notes.append(f"statement_not_found: {name} {row['accession']}")
            continue
        out.append(_evidence("statement", name, f"{row['form']} {_STATEMENT_TITLE[name]}: \"{sn}\" ({hf})", row, rurl, raw, text))
    return out


# -- sections of 10-K, 10-Q and 20-F

_SEP = r"[\s.:;—–\-|]*"
_AFTER = r"(?=\s*[.:;—–\-|]|\s+[A-Z\[(]|\s*$)"
_PART = r"(?:(?i:part)\s+[IVXivx]+\b" + _SEP + r")?"


def _item_re(num):
    return r"^\s*" + _PART + r"(?i:items?)\s*" + num + _AFTER


_ANY_ITEM = re.compile(_item_re(r"(?P<num>\d{1,2}[A-Za-z]?)(?:\s*(?:and|&|,)\s*\d{1,2}[A-Za-z]?)?"))
_MDNA = r"management\W{0,3}s?\s+discussion"

# form -> [(name, item number pattern (None: 20-F Item 3.D), the item's own number, title pattern, label, cap)]
SECTIONS = {
    "10-K": [("business", r"1(?:\s*(?:and|&|,)\s*2)?", "1", r"business", "Item 1 Business", 20_000),
             ("risk_factors", r"1[Aa]", "1A", r"risk\s+factors", "Item 1A Risk Factors", 30_000),
             ("mdna", r"7", "7", _MDNA, "Item 7 Management's Discussion and Analysis", 30_000)],
    "20-F": [("business", r"4", "4", r"information\s+on\s+the\s+company", "Item 4 Information on the Company", 20_000),
             ("risk_factors", None, "3", None, "Item 3.D Risk Factors", 30_000),
             ("mdna", r"5", "5", r"operating\s+and\s+financial\s+review", "Item 5 Operating and Financial Review and Prospects", 30_000)],
    "10-Q": [("quarterly_mdna", r"2", "2", _MDNA, "Part I Item 2 Management's Discussion and Analysis", 15_000),
             ("quarterly_risk_factors", r"1[Aa]", "1A", r"risk\s+factors", "Part II Item 1A Risk Factors", 8_000)],
}
SECTIONS["40-F"] = SECTIONS["10-K"]           # a 40-F's annual information form and MD&A are exhibits: its primary document finds none
_RISK_3D = re.compile(r"^\s*(?:(?i:item)\s*)?(?:3\s*\.?\s*)?D\s*[.:\-—–]?\s*\|?\s*(?i:risk\s+factors)\s*(?:\|\s*\d+\s*)?$")


def doc_lines(raw_text):
    """The cleaned lines of a document: one per paragraph, one per table row (sec_primary.blocks_of)."""
    out = []
    for k, c in blocks_of(raw_text):
        out += c if k == "t" else [c]
    return out


def _heading_at(lines, i, num, title):
    """The number of lines the heading at line i spans (1, or 2 when 'Item 7.' and its title are separate lines), or 0."""
    if num is None:
        return 1 if _RISK_3D.match(lines[i]) else 0
    head = _item_re(num) + _SEP + r"(?i:" + title + r")"
    if re.match(head, lines[i]):
        return 1
    if i + 1 < len(lines) and re.match(_item_re(num) + _SEP + r"$", lines[i]) and re.match(r"^\s*(?i:" + title + r")", lines[i + 1]):
        return 2
    return 0


def _is_boundary(line, own):
    """An item heading of ANOTHER item: a running page header that repeats the section's own item does not end the section."""
    m = _ANY_ITEM.match(line)
    return bool(m) and m.group("num").upper() != own


def find_section(lines, num, own, title):
    """(start, end) line indexes of a section: its heading through the line before the next heading of another item. The first heading
    whose body is at least TOC_MIN_CHARS characters is the section; a shorter one is a contents entry. When no heading has such a body, a
    short section is still the section when it is the LAST of at least two headings of the item (the first being the contents entry) and
    its body holds at least SHORT_MIN_CHARS characters: a 10-Q's one-sentence "no material changes" Item 1A (audit 2026-10-29). A heading
    with no later item heading has no end and is skipped. None when nothing qualifies: not found, never a guess."""
    hits = []
    for i in range(len(lines)):
        n = _heading_at(lines, i, num, title)
        if not n:
            continue
        end = next((j for j in range(i + n, len(lines)) if _is_boundary(lines[j], own)), None)
        if end is None:
            continue
        body = sum(len(l) + 1 for l in lines[i + n:end])
        if body >= TOC_MIN_CHARS:
            return i, end
        hits.append((i, end, body))
    if len(hits) >= 2 and hits[-1][2] >= SHORT_MIN_CHARS:
        return hits[-1][0], hits[-1][1]
    return None


def _sections(cik, row, fetch, kind, notes):
    if not row.get("primary_document"):
        for name, *_ in SECTIONS[row["form"]]:
            notes.append(f"section_not_found: {name} {row['accession']}")
        return []
    url = f"{_base(cik, row['accession'])}/{row['primary_document']}"
    raw = fetch(url)
    lines = doc_lines(_decode(raw))
    out = []
    for name, num, own, title, label, cap in SECTIONS[row["form"]]:
        hit = find_section(lines, num, own, title)
        if hit is None:
            notes.append(f"section_not_found: {name} {row['accession']}")
            continue
        text = canonical(prefix_text(canonical("\n".join(lines[hit[0]:hit[1]])), cap))
        out.append(_evidence(kind, name, f"{row['form']} {label}", row, url, raw, text))
    return out


# -- 8-Ks

def _eight_k_docs(raw):
    docs = []
    for dtype, fname, text, desc in _split_documents(_decode(raw), with_description=True):
        if _is_text_exhibit(dtype, fname):
            docs.append({"type": dtype, "filename": fname, "raw": text, "description": desc})
    return docs


def _release(cik, row, fetch, notes):
    url = f"{_base(cik, row['accession'])}/{row['accession']}.txt"
    raw = fetch(url)
    d = _release_doc(_eight_k_docs(raw))
    if d is None:
        notes.append(f"release_exhibit_not_found: {row['accession']}")
        return []
    text = canonical(select_text(blocks_of(d["raw"]), RELEASE_CAP))
    if not text:
        notes.append(f"release_exhibit_not_found: {row['accession']}")
        return []
    return [_evidence("release", "earnings_release", f"{row['form']} Item 2.02 earnings release ({d['type']} {d['filename']})", row, url,
                      raw, text)]


def _other_8k(cik, row, fetch, notes):
    url = f"{_base(cik, row['accession'])}/{row['accession']}.txt"
    raw = fetch(url)
    docs = _eight_k_docs(raw)
    ex = _main_exhibit({"docs": docs}) if docs else None
    if ex is None:
        notes.append(f"8k_text_not_found: {row['accession']}")
        return []
    blocks = blocks_of(ex["raw"])
    if not ex["type"].upper().startswith("EX-"):             # an 8-K body opens with its cover page: start at the item text
        item_re = re.compile(r"Item\s+(%s)\b" % "|".join(re.escape(i) for i in OTHER_8K_ITEMS))
        blocks = blocks[next((n for n, (k, c) in enumerate(blocks) if k == "p" and item_re.match(c)), 0):]
    text = canonical(prefix_text("\n".join(c if k == "p" else "\n".join(c) for k, c in blocks), OTHER_8K_CAP))
    if not text:
        notes.append(f"8k_text_not_found: {row['accession']}")
        return []
    its = _items_list(row["items"])
    where = ex["type"] if ex["type"].upper().startswith("EX-") else f"{row['form']} body"
    return [_evidence("other_8k", "other_8k", f"{row['form']} Item{'s' if len(its) != 1 else ''} {', '.join(its)} ({where})", row, url,
                      raw, text)]


# ---- trimming, ids and the build ------------------------------------------------------------------------------------------------

def _trim(items, notes):
    """TOTAL_CAP characters of evidence text: items are cut in reverse order of the evidence list, each cut annotated; an item that would
    keep under MIN_TRIMMED characters is left out."""
    for it in list(reversed(items)):
        excess = sum(len(i["text"]) for i in items) - TOTAL_CAP
        if excess <= 0:
            break
        where = it["source"].get("accession") or it["source"].get("git_commit")
        room = len(it["text"]) - excess
        if room < MIN_TRIMMED:
            items.remove(it)
            notes.append(f"trimmed_out: {it['kind']} {it['name']} {where} (packet over {TOTAL_CAP} characters)")
        else:
            it["text"] = canonical(prefix_text(it["text"], room))
            notes.append(f"trimmed: {it['kind']} {it['name']} {where} to {len(it['text'])} characters (packet over {TOTAL_CAP} characters)")
    return items


def _assign_ids(items):
    f = p = 0
    for it in items:
        if it["kind"] == "screener_row":
            fid = "S0"
        elif it["kind"] == "statement":
            f += 1
            fid = f"F{f}"
        else:
            p += 1
            fid = f"P{p}"
        it["fact_id"] = fid
    return items


def _core(ticker, T, commit_full, repo, fetch, verified_run_id):
    """The packet of an already-verified commit. `fetch` is an _Inputs. Pure given the store, the repository and the arguments."""
    s0, sheader, cik = _screener(repo, commit_full, ticker)
    committed = datetime.fromisoformat(_git(repo, "show", "-s", "--format=%cI", commit_full).decode("ascii").strip())
    if committed.astimezone(timezone.utc) > T:
        raise PacketRefused("screener_commit_after_T", f"{commit_full} is dated {committed.isoformat()}, after T {_z(T)}")
    sheader["verified_run_id"] = verified_run_id
    notes, excluded = [], []
    subs = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    rows = _filing_rows(subs)

    items = [s0]
    periodic = _pick(rows, lambda r: r["form"] in PERIODIC_FORMS, "statements", T, excluded, notes)
    if periodic:
        items += _statements(cik, periodic[0], fetch, notes)
    else:
        notes.append("no_eligible_filing: statements (10-Q, 10-K, 20-F or 40-F in the recent submissions)")
    annual = _pick(rows, lambda r: r["form"] in ANNUAL_FORMS, "annual", T, excluded, notes)
    if annual:
        items += _sections(cik, annual[0], fetch, "annual_section", notes)
    else:
        notes.append("no_eligible_filing: annual (10-K, 20-F or 40-F in the recent submissions)")
    after = annual[0]["accepted"] if annual else None
    quarterly = _pick(rows, lambda r: r["form"] == "10-Q" and (after is None or r["accepted"] is None or r["accepted"] > after),
                      "quarterly", T, excluded, notes)
    if quarterly:
        items += _sections(cik, quarterly[0], fetch, "quarterly_section", notes)
    else:
        notes.append("no_eligible_filing: quarterly (10-Q after the annual report in the recent submissions)")
    release = _pick(rows, lambda r: r["form"] in EIGHT_K_FORMS and _has_item_202(r["items"]), "release", T, excluded, notes)
    if release:
        items += _release(cik, release[0], fetch, notes)
    else:
        notes.append("no_eligible_filing: release (8-K Item 2.02 in the recent submissions)")
    since = T - timedelta(days=OTHER_8K_DAYS)
    rel_acc = release[0]["accession"] if release else None
    others = _pick(rows, lambda r: (r["form"] in EIGHT_K_FORMS and r["accession"] != rel_acc
                                    and (r["accepted"] is None or r["accepted"] >= since)
                                    and set(_items_list(r["items"])) & set(OTHER_8K_ITEMS)),
                   "other_8k", T, excluded, notes, limit=MAX_OTHER_8K)
    for r in others:
        items += _other_8k(cik, r, fetch, notes)

    items = _assign_ids(_trim(items, notes))
    return {"contract": CONTRACT, "builder_version": BUILDER_VERSION, "ticker": ticker, "cik": cik, "decision_time_utc": _z(T),
            "screener": sheader, "sec_policy": SEC_POLICY, "raw_inputs": list(fetch.used), "evidence": items, "annotations": notes,
            "excluded": excluded}


def _check_ticker(ticker):
    if not isinstance(ticker, str) or not ticker.strip():
        raise PacketRefused("ticker_invalid", repr(ticker))
    t = ticker.strip().upper()
    if t in EXCLUDED_TICKERS:
        raise PacketRefused("ticker_excluded", f"{t} is excluded from qwen_c")
    return t


def build(ticker, T, screener_commit, *, online, verified_record, screener_repo_path=None, store_root=None):
    """The packet dict of `ticker` at decision time T over the screener commit `screener_commit`. `verified_record` is the check_new_runs
    record (a path to its JSON, or the loaded list of rows). See the module docstring for the refusals."""
    t = _check_ticker(ticker)
    T = parse_T(T)
    repo = Path(screener_repo_path) if screener_repo_path is not None else screener_repo()
    if isinstance(verified_record, (str, os.PathLike)):
        verified_record = json.loads(Path(verified_record).read_text(encoding="utf-8"))
    commit_full = _resolve_commit(repo, screener_commit)
    row = verified_row(verified_record, commit_full)
    fetch = _Inputs(lambda url: sec_store.get(url, online=online, root=store_root))
    return _core(t, T, commit_full, repo, fetch, row.get("run_id"))


def save(packet, root=None):
    """Write the packet's canonical bytes to <root>/<ticker>_<T compact>.json, atomically. An existing file with other bytes is never
    overwritten (a PacketError); the same bytes are a no-op."""
    root = Path(root) if root is not None else PACKETS_DIR
    root.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(packet)
    path = root / f"{packet['ticker']}_{t_compact(packet['decision_time_utc'])}.json"
    if path.exists():
        if path.read_bytes() != data:
            raise PacketError(f"{path} exists with other bytes; packets are never overwritten")
        return path
    fd, tmp = tempfile.mkstemp(dir=str(root), prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build one m3m.packet.v1 packet into cache/m3m/packets/")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--T", required=True, help="decision time, ISO with a zone (e.g. 2026-10-29T00:00:00Z), or 'now'")
    ap.add_argument("--commit", required=True, help="the screener output commit")
    ap.add_argument("--verified-record", required=True, help="a check_new_runs out/check_<utc>.json")
    ap.add_argument("--online", action="store_true", help="fetch what the store lacks from SEC")
    a = ap.parse_args(argv)
    T = datetime.now(timezone.utc).replace(microsecond=0) if a.T == "now" else a.T
    pk = build(a.ticker, T, a.commit, online=a.online, verified_record=a.verified_record)
    path = save(pk)
    print(json.dumps({"packet": str(path), "packet_sha256": packet_sha256(pk), "evidence": [e["fact_id"] for e in pk["evidence"]],
                      "annotations": pk["annotations"], "excluded": pk["excluded"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

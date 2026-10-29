"""packet.py - the input contract `m3m.packet.v1` of qwen_c (SPEC_m3m_qwen_pipeline.md §3).

`build(ticker, T, screener_commit, online=..., verified_record=...)` freezes, for one ticker and one decision time T, the screener's row
(git blobs at a verified commit) and the company's own SEC documents (through sec_store) into one packet dict. `canonical_bytes` is the one
byte form a packet is stored and hashed in. `build` reads no clock: T is an argument. With online=False it gives byte-identical output
over the same store state and commit; the store is append-only and `get` serves the LATEST receipt of a url, so a later online fetch of a
submissions JSON changes what an offline build reads. The determinism gate is replay.py, which reads only the pinned bytes (get_pinned).

ELIGIBILITY. A filing is used only when effective_at(accepted_at(acceptanceDateTime)) <= T (policy SEC_POLICY, re-implemented from
m3l_sec_pit_asof.py; no cross-repository import). An ineligible filing that would otherwise have been chosen for a slot is listed in
`excluded` with its accession and effective_at.

EVIDENCE, in this fixed order (ids S0, then F1..., then P1..., sequential within their letter):
  S0 screener_row       identity and market fields of the stocks.json record only (S0_FIELDS), `key: value` lines (0 prints as 0);
                        Last_Updated is labelled as the price as-of. Nothing from factor_scores_dual_door.json is evidence: its blob
                        is pinned in the header for audit only
  F  statement          balance sheet, income statement, cash flows: FilingSummary R reports of the latest eligible 10-Q/10-K/20-F/40-F
  P  annual_section     Business, Risk Factors, MD&A of the latest eligible 10-K / 20-F / 40-F
  P  quarterly_section  MD&A and Part II Item 1A of the latest eligible 10-Q accepted after that annual report
  P  amendment          up to MAX_AMENDMENTS eligible 10-K/A, 10-Q/A, 20-F/A, 40-F/A accepted after that annual report, newest first:
                        the primary document from its first Item heading, at most AMENDMENT_CAP characters
  P  release            the latest eligible 8-K Item 2.02 EX-99 release (sec_primary.select_text rules); one accepted more than
                        RELEASE_MAX_DAYS before T is not used and is annotated release_stale
  P  other_8k           eligible 8-Ks of the OTHER_8K_DAYS before T with a listed item, newest first, at most MAX_OTHER_8K: the 8-K body
                        from its first Item heading of an item the filing lists, then its EX-99.x exhibits, to OTHER_8K_CAP. Contracts
                        and other exhibits (EX-1, EX-3, EX-4, EX-10, ...) are never used
A section is found only by its heading in the cleaned text and ends at the next item heading; a heading followed by under TOC_MIN_CHARS
characters before the next item heading is a table-of-contents entry and is skipped. A section or statement that cannot be found is an
annotation, never a guess and never a whole-document fallback. Every cut is marked with sec_primary.OMIT.

HEADER. `screener` carries the commit, the three blob shas and `verified_row`, the verified record's row as found (run_id, verdict, pair,
output_commit, run_updated_at). `builder_code` carries the sha256 of the builder's source files (line ends normalised to LF) and the
exchange_calendars and tzdata versions.

REFUSALS (PacketRefused; a degraded packet is never built): an excluded ticker; a screener commit that is not on a PASS / pair PASS row of
the verified record; a verified row without a readable GitHub `run_updated_at`, or with one after T; a T outside the trading calendar;
a ticker missing from that commit's stocks.json or from its factor profiles; no CIK; a screener commit dated after T; a T older than the
oldest row of the submissions' filings.recent (older filings are in filings.files, which v1 does not read).
A document that cannot be had (NotInStore offline, FetchFailed online, StoreCorrupt) raises too.
"""
import argparse
import hashlib
import html
import importlib.metadata
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

import sec_guidance
import sec_primary
from sec_guidance import _has_item_202
from sec_primary import _is_text_exhibit, _items_list, _release_doc, _split_documents, blocks_of, canonical, prefix_text, select_text

from qwen_c import sec_store

CONTRACT = "m3m.packet.v1"
BUILDER_VERSION = "m3m.packet.builder.v3"
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
RELEASE_MAX_DAYS = 120
AMENDMENT_CAP = 4_000
MAX_AMENDMENTS = 2
TOC_MIN_CHARS = 1_500
SHORT_MIN_CHARS = 100            # a short section kept only as the last of two or more headings (find_section); an amendment's heading
MIN_TRIMMED = 600

PERIODIC_FORMS = ("10-Q", "10-K", "20-F", "40-F")
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
AMENDMENT_FORMS = ("10-K/A", "10-Q/A", "20-F/A", "40-F/A")
EIGHT_K_FORMS = ("8-K", "8-K/A")

# S0: the stocks.json fields printed, in this order, with their label (CROSS_CHECK_M ruling 3.1). Nothing else of the row is evidence.
S0_FIELDS = (("symbol", "symbol"), ("name", "name"), ("sector", "sector"), ("industry", "industry"), ("country", "country"),
             ("price", "price"), ("marketCap", "marketCap"), ("Last_Updated", "price as-of (Last_Updated, zone not stated)"),
             ("last_listed", "last_listed"))
VERIFIED_FIELDS = ("run_id", "verdict", "pair", "output_commit", "run_updated_at")
BUILDER_FILES = (("packet.py", Path(__file__)), ("sec_primary.py", Path(sec_primary.__file__)),
                 ("sec_guidance.py", Path(sec_guidance.__file__)))

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


def check_T_in_calendar(T):
    """Refuses (T_outside_calendar) a T before the calendar's first session open, or so late that the policy cannot be applied to a
    filing accepted at T (its effective session lies past the calendar's end)."""
    cal = _calendar()
    if T < cal.first_session_open.to_pydatetime():
        raise PacketRefused("T_outside_calendar", f"T {_z(T)} is before the calendar's first session open {_z(cal.first_session_open)}")
    try:
        effective_at(T, cal)
    except (xcals.errors.DateOutOfBounds, xcals.errors.RequestedSessionOutOfBounds) as e:
        raise PacketRefused("T_outside_calendar", f"T {_z(T)}: a filing accepted at T has no session in the calendar ({e})") from e


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


def pinned_row(row):
    """The verified row as the header pins it: VERIFIED_FIELDS as found (a field the row lacks is null)."""
    return {k: row.get(k) for k in VERIFIED_FIELDS}


def check_run_time(verified, T):
    """The run-time check of a pinned verified row (CROSS_CHECK_M 2.1): GitHub's `run_updated_at` (the end of the run that witnessed the
    commit) must be a zoned ISO time at or before T. Refuses when it is missing, unreadable or after T."""
    raw = verified.get("run_updated_at") if isinstance(verified, dict) else None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) and raw else None
    except ValueError:
        at = None
    if at is None or at.tzinfo is None:
        raise PacketRefused("verified_run_time_missing", f"the verified row has no readable zoned run_updated_at ({raw!r})")
    if at.astimezone(timezone.utc) > T:
        raise PacketRefused("verified_run_after_T", f"the verified run ended at {raw}, after T {_z(T)}")


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


def s0_lines(row):
    """The S0 lines of a stocks.json row: S0_FIELDS only, in their order; a field the row lacks prints as `absent`."""
    return [f"{label}: {_fmt(row[k]) if k in row else 'absent'}" for k, label in S0_FIELDS]


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
    lines = [f"stocks.json record ({STOCKS_PATH} at {commit_full}), identity and market fields only:"] + s0_lines(rows[0])
    s0 = {"kind": "screener_row", "name": "screener_row", "title": "Screener row: identity and market fields of the stocks.json record",
          "source": {"git_commit": commit_full, "path": STOCKS_PATH}, "form": None, "period": None,
          "accepted_raw": None, "effective_at": None, "raw_sha256": hashlib.sha256(blobs[STOCKS_PATH]).hexdigest(),
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


def eight_k_body_lines(lines, items):
    """The lines of an 8-K body from its first heading of an item the filing lists (`Item 1.01`, `ITEM 8.01.`, `Items 1.01 and 2.03`, a
    table row `Item 8.01. | Other Events.`), or None when the body has no such heading: the cover page is never used."""
    if not items:
        return None
    head = re.compile(r"^\s*(?i:items?)\s*(?:%s)(?!\d)" % "|".join(re.escape(i) for i in items))
    start = next((n for n, l in enumerate(lines) if head.match(l)), None)
    return None if start is None else lines[start:]


def _other_8k(cik, row, fetch, notes):
    """The other-8-K item (CROSS_CHECK_M 6.1b): the 8-K body from its first listed Item heading, then the EX-99.x exhibits in file order,
    to OTHER_8K_CAP. No other exhibit is read: contracts (EX-1, EX-3, EX-4, EX-10) and everything else are never used."""
    url = f"{_base(cik, row['accession'])}/{row['accession']}.txt"
    raw = fetch(url)
    docs = _eight_k_docs(raw)
    its = _items_list(row["items"])
    parts = []                                                  # (label, canonical text)
    body = next((d for d in docs if d["type"].upper() in EIGHT_K_FORMS), None)
    body_lines = eight_k_body_lines(doc_lines(body["raw"]), its) if body is not None else None
    if body_lines is None:
        notes.append(f"8k_item_heading_not_found: {row['accession']}")
    elif canonical("\n".join(body_lines)):
        parts.append((f"{body['type']} body", canonical("\n".join(body_lines))))
    for d in docs:
        if d["type"].upper().startswith("EX-99"):
            t = canonical("\n".join(doc_lines(d["raw"])))
            if t:
                parts.append((d["type"], t))
    if not parts:
        notes.append(f"8k_text_not_found: {row['accession']}")
        return []
    full = "\n".join(t for _, t in parts)
    text = canonical(prefix_text(full, OTHER_8K_CAP))
    kept = len(full) if len(full) <= OTHER_8K_CAP else text.rfind("\n")    # a cut text ends "\n" + the OMIT marker
    used, at = [], 0
    for label, t in parts:                                      # the title names only the documents the kept text reaches
        if at < kept:
            used.append(label)
        at += len(t) + 1
    return [_evidence("other_8k", "other_8k", f"{row['form']} Item{'s' if len(its) != 1 else ''} {', '.join(its)} ({', '.join(used)})",
                      row, url, raw, text)]


def amendment_lines(lines):
    """The lines of an amendment from its first Item heading, or None; from an EXPLANATORY NOTE heading instead when one comes before that
    Item heading (the note says why the amendment was filed, e.g. only to add an auditor report's date: without it an amended Item 8 reads
    like a restatement; audit 2026-10-29). A heading followed by under SHORT_MIN_CHARS characters before the next heading of another item
    is a contents entry, not the heading, and is skipped; a heading with no later item heading runs to the end."""
    for i, l in enumerate(lines):
        m = _ANY_ITEM.match(l)
        if not m:
            continue
        own = m.group("num").upper()
        end = next((j for j in range(i + 1, len(lines)) if _is_boundary(lines[j], own)), len(lines))
        if sum(len(x) + 1 for x in lines[i + 1:end]) >= SHORT_MIN_CHARS:
            note = next((j for j in range(i) if _EXPLANATORY.match(lines[j])), None)
            return lines[note if note is not None else i:]
    return None


_EXPLANATORY = re.compile(r"^\s*(?i:explanatory\s+note)\s*[.:]?\s*$")


def _amendment(cik, row, fetch, notes):
    """An amendment item (CROSS_CHECK_M 6.2a): the primary document from its first Item heading, at most AMENDMENT_CAP characters."""
    if not row.get("primary_document"):
        notes.append(f"amendment_text_not_found: {row['form']} {row['accession']}")
        return []
    url = f"{_base(cik, row['accession'])}/{row['primary_document']}"
    raw = fetch(url)
    body = amendment_lines(doc_lines(_decode(raw)))
    text = canonical(prefix_text(canonical("\n".join(body)), AMENDMENT_CAP)) if body else ""
    if not text:
        notes.append(f"amendment_text_not_found: {row['form']} {row['accession']}")
        return []
    return [_evidence("amendment", "amendment", f"{row['form']} amendment, from its first Item heading", row, url, raw, text)]


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


def builder_code():
    """{file name: sha256 of its bytes with CRLF normalised to LF, ..., "exchange_calendars": version, "tzdata": version} (ruling 5.3)."""
    out = {name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name, path in BUILDER_FILES}
    for dist in ("exchange_calendars", "tzdata"):
        try:
            out[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            out[dist] = None
    return out


def check_filings_window(rows, T):
    """Refuses (T_before_filings_recent) a T older than the oldest row of filings.recent (CROSS_CHECK_M 2.3): the filings of such a T
    are in filings.files, which v1 does not read. The oldest row is the one with the earliest readable acceptance (the policy reading)."""
    times = [r["accepted"] for r in rows if r["accepted"] is not None]
    if not times:
        raise PacketRefused("T_before_filings_recent", "filings.recent has no row with a readable acceptance clock")
    if T < min(times):
        raise PacketRefused("T_before_filings_recent", f"T {_z(T)} is older than the oldest filings.recent row, accepted {_z(min(times))}")


def _core(ticker, T, commit_full, repo, fetch, verified):
    """The packet of an already-verified commit. `fetch` is an _Inputs; `verified` is the pinned verified row (pinned_row). Pure given the
    store, the repository, the builder's code and the arguments."""
    check_T_in_calendar(T)
    check_run_time(verified, T)
    s0, sheader, cik = _screener(repo, commit_full, ticker)
    committed = datetime.fromisoformat(_git(repo, "show", "-s", "--format=%cI", commit_full).decode("ascii").strip())
    if committed.astimezone(timezone.utc) > T:
        raise PacketRefused("screener_commit_after_T", f"{commit_full} is dated {committed.isoformat()}, after T {_z(T)}")
    sheader["verified_row"] = dict(verified)
    notes, excluded = [], []
    subs = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    rows = _filing_rows(subs)
    check_filings_window(rows, T)

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
    amendments = _pick(rows, lambda r: r["form"] in AMENDMENT_FORMS and (after is None or r["accepted"] is None or r["accepted"] > after),
                       "amendment", T, excluded, notes, limit=MAX_AMENDMENTS)
    for r in amendments:
        items += _amendment(cik, r, fetch, notes)
    release = _pick(rows, lambda r: r["form"] in EIGHT_K_FORMS and _has_item_202(r["items"]), "release", T, excluded, notes)
    if release and release[0]["accepted"] < T - timedelta(days=RELEASE_MAX_DAYS):
        notes.append(f"release_stale: {release[0]['accession']} accepted {release[0]['accepted_raw']}, more than {RELEASE_MAX_DAYS} days "
                     f"before T")
        release = []
    elif release:
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
    return {"contract": CONTRACT, "builder_version": BUILDER_VERSION, "builder_code": builder_code(), "ticker": ticker, "cik": cik,
            "decision_time_utc": _z(T), "screener": sheader, "sec_policy": SEC_POLICY, "raw_inputs": list(fetch.used), "evidence": items,
            "annotations": notes, "excluded": excluded}


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
    return _core(t, T, commit_full, repo, fetch, pinned_row(row))


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

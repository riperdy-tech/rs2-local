"""leakage_audit.py - the scripted part of the formal leakage audit that runs before the first AI replay (SPEC_rebuild Addendum C 8).

It scans every pack section, every prompt template and every saved request for
  * DATES AFTER T: ISO dates, long-form dates ("March 3, 2026", "3 March 2026"), month-year ("March 2026"), fiscal-year and quarter labels ("FY2027", "Q3 2026")
    and bare years later than T's year;
  * WORDING about data availability or replays ("replay", "back-test", "point-in-time", "as known", "knowledge cut-off", "hindsight", ...). The only date
    statement a prompt may carry is the header line "Analysis date: <T>" (checked exactly);
  * for pass-1 requests (P1-P5), the WORDS that must never appear in them (the bare word price, market cap, consensus, valuation, news, returns of the
    stock, ...);
  * IDENTITY: a manifest whose company name, ticker or industry is not stamped "as_of_T" (current names and tickers after mergers).
A finding is a VIOLATION anywhere in a header, a template, a section built by code (F, Q, S, R) or a document item's header line, and a REVIEW inside the
verbatim body of a document item (section D): a company's own filing legitimately says "we expect ... in 2027" and "available for sale"; the
coordinator reads those. Nothing here decides: the report (markdown + json) is READ by the coordinator, with the checklist at its end.

    python -m valuation.muse.leakage_audit <run_dir or runs root> [--out report.md] [--strict]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import List, Optional

from valuation import pit_data as pdm

from .prompting import PROMPT_DIR, prompt_files

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_MON = {m.lower(): i + 1 for i, m in enumerate(MONTHS)}
_MON.update({m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)})
_MON["sept"] = 9
_MONRE = "|".join(sorted(_MON, key=len, reverse=True))

ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d])")
LONG = re.compile(r"\b(" + _MONRE + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
DMY = re.compile(r"\b(\d{1,2})\s+(" + _MONRE + r")\.?,?\s+(\d{4})\b", re.I)
MONYEAR = re.compile(r"\b(" + _MONRE + r")\.?,?\s+(\d{4})\b", re.I)
FISCAL = re.compile(r"\b(?:FY|fiscal(?:\s+year)?)\s*'?(\d{4})\b", re.I)
QTR = re.compile(r"\bQ[1-4]\s*'?\s*(\d{4})\b|\b[1-4]Q\s*'?(\d{4})\b")
YEAR = re.compile(r"(?<![\d.,$])((?:19|20)\d{2})(?!\d|[.,]\d)")

WORDING = [re.compile(p, re.I) for p in (
    r"\breplay\w*", r"\bback-?test\w*", r"\bsimulat\w*", r"\bpoint[- ]in[- ]time\b", r"\bas[- ]known\b", r"\bdata availab\w*",
    r"\bavailab(?:le|ility)\s+(?:at|as of|on|before|then)\b", r"\bknowledge\s+cut-?off\b", r"\btraining\s+(?:cut-?off|data)\b", r"\bhindsight\b",
    r"\blook-?ahead\b", r"\bhistorical(?:ly)?\s+(?:date|analysis|exercise)\b", r"\bpretend\w*", r"\bimagine\s+(?:that\s+)?it\s+is\b",
    r"\bknown\s+(?:at|by|on|as of)\s+(?:that|the)\b", r"\bas of that date\b", r"\bat that time\b", r"\bin the past\b")]

# words that must not appear in a pass-1 prompt outside the verbatim body of a filing
FORBIDDEN_PASS1 = [re.compile(p, re.I) for p in (
    r"\bprice[sd]?\b", r"\bpricing\b", r"market[- ]cap\w*", r"\bmarket value\b", r"\bconsensus\b", r"\bprice target\w*", r"\banalyst (?:estimate|target|rating)s?\b",
    r"\bvaluation\w*", r"\bintrinsic value\b", r"\b(?:under|over)valued\b", r"\bnews\b", r"\b(?:stock|share|total|excess|market) returns?\b",
    r"\bshare price\b", r"\bstock price\b", r"\bupside\b", r"\bdownside\b", r"\bmultiples?\b")]

HEADER_RE = re.compile(r"^Analysis date: (\d{4}-\d{2}-\d{2})$", re.M)

# Addendum AD.10 (operator ruling 2026-10-10): text the MODEL wrote in pass 1, echoed into the P5 and P6 prompts (prompting.format_pass1 / review_block), is a
# REVIEW item, not a violation. The model's knowledge ends about August 2025, before every replay date, so its words cannot carry information from after T; its
# dates and words come from the filings it was shown (company guidance such as "calendar 2026 revenue", "pricing power"). Code-built lines stay violations.
MODEL_ECHO = re.compile(r"^(\s+reason \d+: |\s+cited \[[^\]]*\]: |bull_case: |bear_case: |character of today's level: |risk \d+ \(moves )")
D_FILED = re.compile(r"\bfiled (\d{4}-\d{2}-\d{2})\b")
ACCEPTED_IDENTITY = {"name_source": ("as_of_T",), "ticker_source": ("as_of_T", "verified_in_filing", "withheld"), "industry_source": ("as_of_T",)}


@dataclass
class Finding:
    where: str
    kind: str                # date_after_T | wording | forbidden_pass1 | header | identity
    severity: str            # violation | review
    match: str
    context: str

    def as_dict(self):
        return asdict(self)


def _ctx(text: str, a: int, b: int, w: int = 50) -> str:
    return text[max(0, a - w):b + w].replace("\n", " ")


def _safe_date(y, m, d) -> Optional[date]:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def dates_after(text: str, asof: date) -> List[tuple]:
    """[(match text, start, end)] of every date-like statement later than `asof` (month-year: later than asof's month; fiscal / quarter / bare year:
    later than asof's year)."""
    found: List[tuple] = []
    spans: List[tuple] = []

    def take(m, d):
        spans.append(m.span())
        if d is not None and d > asof:
            found.append((m.group(0), *m.span()))

    for m in ISO.finditer(text):
        take(m, _safe_date(m.group(1), m.group(2), m.group(3)))
    for m in LONG.finditer(text):
        take(m, _safe_date(m.group(3), _MON[m.group(1).lower().rstrip(".")], m.group(2)))
    for m in DMY.finditer(text):
        take(m, _safe_date(m.group(3), _MON[m.group(2).lower().rstrip(".")], m.group(1)))

    def inside(s, e):
        return any(a <= s and e <= b for a, b in spans)

    for m in MONYEAR.finditer(text):
        if inside(*m.span()):
            continue
        spans.append(m.span())
        ym = (int(m.group(2)), _MON[m.group(1).lower().rstrip(".")])
        if ym > (asof.year, asof.month):
            found.append((m.group(0), *m.span()))
    for rx in (FISCAL, QTR):
        for m in rx.finditer(text):
            if inside(*m.span()):
                continue
            spans.append(m.span())
            y = int(next(g for g in m.groups() if g))
            if y > asof.year:
                found.append((m.group(0), *m.span()))
    for m in YEAR.finditer(text):
        if inside(*m.span()):
            continue
        if int(m.group(1)) > asof.year:
            found.append((m.group(0), *m.span()))
    return sorted(found, key=lambda t: t[1])


def scan_text(text: str, asof: Optional[date], where: str, *, verbatim_body: bool = False, pass1: bool = False) -> List[Finding]:
    """Findings in one piece of text. `verbatim_body`: the text is a company's own words (review, not violation). `pass1`: also apply FORBIDDEN_PASS1."""
    sev = "review" if verbatim_body else "violation"
    out: List[Finding] = []
    if asof is not None:
        for m, a, b in dates_after(text, asof):
            out.append(Finding(where, "date_after_T", sev, m, _ctx(text, a, b)))
    else:                                              # a template: no date at all
        for rx in (ISO, LONG, DMY, MONYEAR, FISCAL, QTR, YEAR):
            for m in rx.finditer(text):
                out.append(Finding(where, "date_after_T", sev, m.group(0), _ctx(text, *m.span())))
    for rx in WORDING:
        for m in rx.finditer(text):
            out.append(Finding(where, "wording", sev, m.group(0), _ctx(text, *m.span())))
    if pass1:
        for rx in FORBIDDEN_PASS1:
            for m in rx.finditer(text):
                out.append(Finding(where, "forbidden_pass1", sev, m.group(0), _ctx(text, *m.span())))
    return out


# ---- a section / a prompt / a pack -------------------------------------------------------------------------------------------------------

def scan_section(name: str, text: str, asof: date, where: str, *, pass1: bool = False) -> List[Finding]:
    """A pack section. For D the item header lines ("[D1] ... filed <date>") are metadata (violations); the item bodies are the company's words (review)."""
    if name != "D":
        return scan_text(text, asof, f"{where} section {name}", pass1=pass1)
    out: List[Finding] = []
    body: List[str] = []
    for line in text.split("\n"):
        if re.match(r"^\[D\d+\] ", line):
            found = scan_text(line, asof, f"{where} section D header", pass1=pass1)
            m = D_FILED.search(line)
            if m is not None and m.group(1) < asof.isoformat():
                # Addendum AD.10: a fiscal-period label ("Q2 2026", "FY2026") in the header of a document filed before T is the filer's own period name: review
                for f in found:
                    if f.kind == "date_after_T" and not ISO.fullmatch(f.match):
                        f.severity = "review"
            out += found
        else:
            body.append(line)
    out += scan_text("\n".join(body), asof, f"{where} section D body", verbatim_body=True, pass1=pass1)
    return out


def split_user_text(text: str):
    """[(section letter or None, text)] of a rendered prompt: the part before the first section marker and each "=== SECTION X: ..." block."""
    parts = re.split(r"(?m)^=== SECTION ([FQDSR]):[^\n]*\n", text)
    out = [(None, parts[0])]
    for i in range(1, len(parts), 2):
        out.append((parts[i], parts[i + 1]))
    return out


def ground(findings: List[Finding], grounding: Optional[str], asof: Optional[date] = None) -> List[Finding]:
    """Addendum AE.4 (as revised in AE.12): a future date found in MODEL text stays `review` only when the run's filing text (the pack, accepted before T)
    itself refers to the same future YEAR in some date form ("2026", "fiscal 2026", "Q2 2026", "FY2026"); the model writes "FY2026" where a filing writes
    "fiscal 2026", so an exact-string test is too literal. A future year the filings never mention is an ungrounded statement about the future (a
    hallucination or a leak) and becomes a `violation`. Stated limit: a year the filings mention for another reason (a note due 2027) also grounds it,
    and the finding stays a review item that the coordinator reads. Without grounding text (an older caller) nothing changes."""
    if grounding is None:
        return findings
    years = {y for m, _a, _b in (dates_after(grounding, asof) if asof is not None else []) for y in re.findall(r"(?:19|20)\d{2}", m)}
    if asof is None:
        years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", grounding))
    for f in findings:
        ys = set(re.findall(r"(?:19|20)\d{2}", f.match))
        if f.kind != "date_after_T" or (ys & years):
            continue
        # Addendum AJ (operator 2026-10-11): naming the year being forecast (year(T) + 1, "into 2026") is forward reasoning, not information from after T
        # (the model's knowledge ends before every replay date): a review item. Any other ungrounded future year is a review item the coordinator MUST read
        # before scoring (kind `date_beyond_forecast_year`); it counts against G5 only if it ties a value to a period ending after T (recorded judgement).
        if asof is not None and ys and all(int(y) == asof.year + 1 for y in ys):
            f.severity = "review"
            f.context = "[the forecast year, not in the filings shown] " + f.context
        else:
            f.severity = "review"
            f.kind = "date_beyond_forecast_year"
            f.context = "[READ BEFORE SCORING: a future year beyond the forecast year, not in the filings shown] " + f.context
    return findings


RETRY_QUOTE = re.compile(r"the quote '(.+?)' was", re.S)


def scan_retry_message(text: str, asof: date, where: str, *, pass1: bool, grounding: Optional[str]) -> List[Finding]:
    """Addendum AJ: a retry message is checker text plus the model's OWN failed quotes, which the checker echoes back ("the quote '...' was not found
    verbatim"). The echoed quote is model text (review, grounded as model text); the rest stays code-built text (strict)."""
    quotes = [m.group(1) for m in RETRY_QUOTE.finditer(text)]
    code = RETRY_QUOTE.sub("the quote '' was", text)
    out = scan_text(code, asof, f"{where} retry message", pass1=pass1)
    if quotes:
        out += ground(scan_text("\n".join(quotes), asof, f"{where} retry message (model quote echoed)", verbatim_body=True, pass1=pass1), grounding, asof)
    return out


def scan_prompt_text(text: str, asof: date, where: str, *, pass1: bool, grounding: Optional[str] = None) -> List[Finding]:
    """A rendered user prompt. Its only date is the header line; the template text around the sections is scanned like code-built text."""
    out: List[Finding] = []
    m = HEADER_RE.search(text)
    if m is None or not text.startswith("Analysis date: "):
        out.append(Finding(where, "header", "violation", "", "the prompt does not open with the line 'Analysis date: <T>'"))
    elif m.group(1) != asof.isoformat():
        out.append(Finding(where, "header", "violation", m.group(0), f"the analysis date is not T = {asof.isoformat()}"))
    if len(HEADER_RE.findall(text)) > 1:
        out.append(Finding(where, "header", "violation", "", "more than one 'Analysis date:' line"))
    for sec, chunk in split_user_text(text):
        if sec is None:
            chunk = HEADER_RE.sub("", chunk, count=1)
            code_lines, echo_lines = [], []
            open_quote = False                         # Addendum AJ.4: a multi-line quote echoed after "cited [Dn]:" continues on the next lines until it closes
            for line in chunk.split("\n"):
                if MODEL_ECHO.match(line) or open_quote:
                    echo_lines.append(line)
                    if line.count('"') % 2 == 1:
                        open_quote = not open_quote
                else:
                    code_lines.append(line)
            out += scan_text("\n".join(code_lines), asof, f"{where} prompt text", pass1=pass1)
            out += ground(scan_text("\n".join(echo_lines), asof, f"{where} model text echoed", verbatim_body=True, pass1=pass1), grounding, asof)
        else:
            out += scan_section(sec, chunk, asof, where, pass1=pass1)
    return out


def audit_templates(directory=PROMPT_DIR) -> List[Finding]:
    """The template files and the system text carry no date at all and no availability wording; P1-P5 carry none of the pass-1 forbidden words."""
    out: List[Finding] = []
    for p in prompt_files():
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".json":
            continue
        is_pass1 = p.stem in ("P1", "P2", "P3", "P4", "P5", "system")
        out += scan_text(text, None, f"template {p.name}", pass1=is_pass1)
    return out


def audit_pack(pack: dict, asof: date, where: str = "pack") -> List[Finding]:
    out: List[Finding] = []
    lines = pack["header"].split("\n")
    if lines[0] != f"Analysis date: {asof.isoformat()}":
        out.append(Finding(f"{where} header", "header", "violation", lines[0], "the first header line must be 'Analysis date: <T>'"))
    out += scan_text("\n".join(lines[1:]), asof, f"{where} header")
    for name, text in pack["sections"].items():
        out += scan_section(name, text, asof, where, pass1=True)
    for name, text in pack["r"].items():
        out += scan_section("R", text, asof, f"{where} {name}", pass1=True)
    idn = (pack.get("manifest") or {}).get("identity") or {}
    for k in ("name_source", "ticker_source", "industry_source"):
        if idn.get(k) not in ACCEPTED_IDENTITY[k]:
            out.append(Finding(f"{where} manifest", "identity", "violation", f"{k}={idn.get(k)}", "identity must be stamped as of T (no current names or tickers)"))
    for it in ((pack.get("manifest") or {}).get("documents") or {}).get("used") or []:
        t = pdm.parse_accepted(it.get("accepted_at")) if it.get("accepted_at") else None
        if t is not None and t > pdm.decision_time_utc(asof):
            out.append(Finding(f"{where} manifest", "date_after_T", "violation", it.get("accession", ""), "a document accepted after the 16:00 ET cutoff is in section D"))
        elif t is None and str(it.get("filed", "9999"))[:10] >= asof.isoformat():
            out.append(Finding(f"{where} manifest", "date_after_T", "violation", it.get("accession", ""), "a document with no acceptance timestamp filed on or after T is in section D"))
    return out


# ---- a run directory and a tree --------------------------------------------------------------------------------------------------------------

def audit_run_dir(run_dir) -> dict:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    asof = date.fromisoformat(manifest["asof"])
    findings: List[Finding] = []
    n_requests = 0
    grounding = None
    if (run_dir / "pack.json").exists():
        pack = json.loads((run_dir / "pack.json").read_text(encoding="utf-8"))
        findings += audit_pack(pack, asof)
        grounding = "\n".join(v for k, v in (pack.get("sections") or {}).items() if k in ("F", "Q", "D", "S"))
    sys_msg = manifest.get("system_message", "")
    findings += scan_text(sys_msg, None, "system message", pass1=True)
    for p in sorted(run_dir.glob("*_request.json")):
        n_requests += 1
        req = json.loads(p.read_text(encoding="utf-8"))
        call = re.match(r"\d+_(P\d)", p.name)
        pass1 = bool(call) and call.group(1) in ("P1", "P2", "P3", "P4", "P5")
        msgs = req.get("messages") or []
        for i, m in enumerate(msgs):
            if m["role"] == "user" and i == 1:
                findings += scan_prompt_text(m["content"], asof, p.name, pass1=pass1, grounding=grounding)
            elif m["role"] == "user":                                  # the retry message (checker text) and nothing else
                findings += scan_retry_message(m["content"], asof, p.name, pass1=pass1, grounding=grounding)
            elif m["role"] == "assistant":
                findings += ground(scan_text(m["content"], asof, f"{p.name} earlier answer", verbatim_body=True), grounding, asof)
    return {"run_dir": str(run_dir), "ticker": manifest.get("ticker"), "asof": manifest["asof"], "n_requests": n_requests,
            "findings": [f.as_dict() for f in findings],
            "violations": sum(1 for f in findings if f.severity == "violation"), "reviews": sum(1 for f in findings if f.severity == "review")}


def find_run_dirs(root) -> List[Path]:
    root = Path(root)
    if (root / "run_manifest.json").exists():
        return [root]
    return sorted(p.parent for p in root.rglob("run_manifest.json"))


CHECKLIST = [
    "Read every 'review' finding: a date after T inside a company's own words is normal for a forward-looking statement; a date that describes an event "
    "after T is not.",
    "Names and tickers: for each company confirm the name and ticker in the header are those in force at T (mergers, renames, redomiciles).",
    "Cached snippets, file names and URLs: confirm no document item text or manifest field was produced from a source dated after T.",
    "Read two or three full prompts end to end as the model sees them.",
    "Confirm the templates' sha256 in run_manifest.json equal the frozen prompt set named in the registration.",
]


def audit(root) -> dict:
    reports = [audit_run_dir(d) for d in find_run_dirs(root)]
    tmpl = audit_templates()
    return {"templates": [f.as_dict() for f in tmpl], "runs": reports,
            "violations": sum(r["violations"] for r in reports) + sum(1 for f in tmpl if f.severity == "violation"),
            "reviews": sum(r["reviews"] for r in reports)}


def render_markdown(rep: dict, limit: int = 300) -> str:
    L = ["# Muse leakage audit", "", f"Violations: {rep['violations']}; items for review: {rep['reviews']}; runs scanned: {len(rep['runs'])}", ""]
    L.append("## Templates")
    L += [f"- {f['where']}: {f['kind']} {f['match']!r} ({f['severity']}) ...{f['context']}..." for f in rep["templates"]] or ["- clean"]
    for r in rep["runs"]:
        L += ["", f"## {r['ticker']} {r['asof']} ({r['n_requests']} requests): {r['violations']} violations, {r['reviews']} review"]
        for f in r["findings"][:limit]:
            L.append(f"- [{f['severity']}] {f['where']}: {f['kind']} {f['match']!r} ...{f['context']}...")
        if len(r["findings"]) > limit:
            L.append(f"- ... {len(r['findings']) - limit} more in the json")
    L += ["", "## Coordinator's checklist"] + [f"- [ ] {c}" for c in CHECKLIST]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", help="a run directory, or a folder holding run directories")
    ap.add_argument("--out", default=None, help="write the markdown report here (and .json beside it)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when there is a violation")
    a = ap.parse_args(argv)
    rep = audit(a.root)
    md = render_markdown(rep)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        Path(a.out).with_suffix(".json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    else:
        sys.stdout.write(md)
    return 1 if (a.strict and rep["violations"]) else 0


if __name__ == "__main__":
    sys.exit(main())

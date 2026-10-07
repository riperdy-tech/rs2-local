"""Delisting events from free SEC records (Addendum D): a scripted classification over SEC submissions (form types and 8-K item numbers).

Input: SEC submissions JSON per company (`filings.recent` and the files listed under `filings.files`): parallel arrays `form`, `filingDate`, `items`
(8-K item numbers, comma separated), `accessionNumber`.  Nothing here downloads anything: it reads a directory the operator has filled.

Per company the pass finds the exit records and classes the event:
  * Form 25 / 25-NSE (an exchange delisting) and Form 15 family (deregistration) give the date of the event (the Form 25 date when there is one);
  * `bankruptcy`            an 8-K Item 1.03 within 540 days before the exit record;
  * `acquisition_completed` an 8-K Item 2.01 within the 45 days before to 10 days after the exit record, together with Item 3.01 (delisting notice)
                            or Item 5.01 (change in control) in an 8-K of that window;
  * `acquisition_weak`      Item 2.01 alone: possibly the company as acquirer, not decided by code;
  * `exit_record_still_reporting`  a Form 25 / 15 after which the company kept filing periodic reports (10-K, 10-Q, 20-F, 40-F) more than 120 days later:
                            a listing of notes, preferred shares or warrants ended, or the common moved exchange - NOT a delisting of the common stock;
  * `delisted_other`        Form 25 with none of the above (a voluntary or exchange-initiated delisting; the shares may continue elsewhere);
  * `deregistered_other`    Form 15 only;
  * `bankruptcy_no_exit_record` an Item 1.03 with no Form 25 / 15 on record.
Priority: bankruptcy, acquisition_completed, acquisition_weak, delisted_other, deregistered_other.

Outcome resolution is deliberately conservative.  The consideration of an acquisition and the treatment of a bankrupt company's common stock are in
the merger proxy / 8-K / plan text, which code reads only through the pluggable readers below; by default there is no reader, so the event is
`unresolved` and the outcome is OUTCOME_UNOBSERVABLE.  The harness then reports every return under three bounds: unobservable delistings excluded, at
-100%, and at the last close the provider has.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

DEREG_FORMS = ("15", "15-12B", "15-12G", "15-15D", "15F-12B", "15F-12G", "15F-15D")
EXCHANGE_FORMS = ("25", "25-NSE")
PERIODIC = ("10-K", "10-K/A", "10-KT", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
STILL_REPORTING_DAYS = 120
CLASSES = ("exit_record_still_reporting", "bankruptcy", "acquisition_completed", "acquisition_weak", "delisted_other", "deregistered_other", "bankruptcy_no_exit_record")
BANKRUPTCY_LOOKBACK_DAYS = 540
ACQ_BEFORE_DAYS, ACQ_AFTER_DAYS = 45, 10


def _d(s):
    return date.fromisoformat(s[:10])


def filings_of(doc):
    """[(form, filing date iso, items set, accession)] of a submissions document (recent block plus any listed older files already merged by the caller)."""
    out = []
    for b in doc if isinstance(doc, list) else [doc]:
        r = (b.get("filings") or {}).get("recent") if "filings" in b else b
        r = r or {}
        n = len(r.get("form") or [])
        items = r.get("items") or [""] * n
        accs = r.get("accessionNumber") or [""] * n
        for i in range(n):
            out.append((r["form"][i], r["filingDate"][i], {x.strip() for x in str(items[i] or "").split(",") if x.strip()}, accs[i]))
    return sorted(out, key=lambda x: x[1])


def classify_company(cik, filings):
    """The delisting event of one company from its filings, or None.  {cik, date, class, evidence: [{form, date, accession, items}]}."""
    exits = [f for f in filings if f[0] in EXCHANGE_FORMS]
    deregs = [f for f in filings if f[0] in DEREG_FORMS]
    ev8k = [f for f in filings if f[0] in ("8-K", "8-K/A")]
    bk = [f for f in ev8k if "1.03" in f[2]]
    anchor = (exits or deregs or [None])[0]
    if anchor is None:
        if bk:
            return {"cik": cik, "date": bk[0][1], "class": "bankruptcy_no_exit_record", "evidence": [_ev(bk[0])]}
        return None
    d0 = _d(anchor[1])
    near = [f for f in ev8k if -ACQ_BEFORE_DAYS <= (_d(f[1]) - d0).days <= ACQ_AFTER_DAYS]
    bk_near = [f for f in bk if 0 <= (d0 - _d(f[1])).days <= BANKRUPTCY_LOOKBACK_DAYS]
    a201 = [f for f in near if "2.01" in f[2]]
    support = [f for f in near if f[2] & {"3.01", "5.01"}]
    evidence = [_ev(anchor)]
    last_periodic = max((f[1] for f in filings if f[0] in PERIODIC), default=None)
    still = last_periodic is not None and (_d(last_periodic) - d0).days > STILL_REPORTING_DAYS
    if bk_near:
        return {"cik": cik, "date": anchor[1], "class": "bankruptcy", "evidence": evidence + [_ev(bk_near[-1])]}
    if still:
        return {"cik": cik, "date": anchor[1], "class": "exit_record_still_reporting", "evidence": evidence + [{"form": "periodic", "date": last_periodic,
                                                                                                           "items": [], "accession": ""}]}
    if a201 and support:
        return {"cik": cik, "date": anchor[1], "class": "acquisition_completed", "evidence": evidence + [_ev(a201[0]), _ev(support[0])]}
    if a201:
        return {"cik": cik, "date": anchor[1], "class": "acquisition_weak", "evidence": evidence + [_ev(a201[0])]}
    return {"cik": cik, "date": anchor[1], "class": "delisted_other" if exits else "deregistered_other", "evidence": evidence}


def _ev(f):
    return {"form": f[0], "date": f[1], "items": sorted(f[2]), "accession": f[3]}


def classify_dir(directory):
    """Classify every `CIK##########.json` in a directory of submissions files (older files `CIK##########-submissions-NNN.json` are merged)."""
    directory = Path(directory)
    events = []
    for p in sorted(directory.glob("CIK??????????.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        blocks = [doc]
        for f in (doc.get("filings") or {}).get("files") or []:
            q = directory / f.get("name", "")
            if q.is_file():
                blocks.append(json.loads(q.read_text(encoding="utf-8")))
        ev = classify_company(p.name[3:13], filings_of(blocks))
        if ev:
            ev["name"] = doc.get("name")
            events.append(ev)
    return events


def counts_per_class_per_year(events):
    """{year of the event date: {class: n}} (calendar years of the delisting date, i.e. the years a valuation date's horizon runs into)."""
    out = defaultdict(Counter)
    for e in events:
        out[e["date"][:4]][e["class"]] += 1
    return {y: dict(c) for y, c in sorted(out.items())}


def counts_for_valuation_dates(events, dates, horizon_months=36):
    """{valuation date: {class: n}}: events whose date falls after the valuation date and within `horizon_months` of it."""
    from valuation.pit_data import add_months, to_date
    out = {}
    for d in dates:
        t0, t1 = to_date(d), add_months(to_date(d), horizon_months)
        out[d] = dict(Counter(e["class"] for e in events if t0 < _d(e["date"]) <= t1))
    return out


# ---- readers: the only way an event becomes anything but unobservable --------------------------------------------------------------------

_CASH = re.compile(r"(?:receive|entitled to receive|converted into the right to receive)[^.;]{0,120}?\$\s?(\d{1,4}(?:\.\d{1,4})?)\s+(?:per share\s+)?in cash", re.I)
_CASH2 = re.compile(r"\$\s?(\d{1,4}(?:\.\d{1,4})?)\s+(?:in cash\s+)?per share", re.I)
_STOCK_WORDS_M5 = re.compile(r"exchange ratio|shares of (?:the )?(?:parent|acquirer|buyer)|stock consideration|in stock|common stock of|contingent value|cvr|collar|election", re.I)     # Addenda D, M5
# Addendum N5: 'common stock of' alone names the shares being BOUGHT in a target's consideration sentence, not stock paid, so it no longer declines; the same phrase naming the ACQUIRER ('common stock of
# Parent') still does, as do elections, exchange ratios and the other words (the ruling: "named acquirer stock still decline")
_STOCK_WORDS = re.compile(_STOCK_WORDS_M5.pattern.replace("common stock of|", "common stock of (?:the )?(?:parent|acquirer|buyer)|"), re.I)


_ABBREV = re.compile(r"\b(Inc|Corp|Co|Ltd|LLC|L\.P|U\.S|No|Nos|Mr|Mrs|Ms|Dr|St|Cos|Bros|plc|N\.V|S\.A|a\.m|p\.m|e\.g|i\.e|vs|Sec|Dec|Jan|Feb|Mar|Apr|Aug|Sept|Oct|Nov)\.", re.I)
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
_DOT = "․"                                           # a stand-in for the period of an abbreviation, so that the sentence split does not cut after it


def sentences(text):
    """The sentences of a flattened document: split after . ! ? followed by white space and a capital letter, the period of an abbreviation (Inc., Corp., U.S., ...) and of a decimal never ends one.  A split
    that is missed makes a sentence longer, and the reader below stricter; it is never made shorter than the sentence."""
    t = _ABBREV.sub(lambda m: m.group(0)[:-1] + _DOT, text)
    return [x.replace(_DOT, ".").strip() for x in _SENT_END.split(t) if x.strip()]


def read_cash_consideration_whole_text(text):
    """The reader as it stood before Addendum M5 (with its stock words of then, `_STOCK_WORDS_M5`), kept to report the yield BEFORE: the all-cash price per share in a completion 8-K / merger text, or None.  Exactly one distinct dollar amount
    per share, and none of the words that mean stock, ratios, elections or contingent rights ANYWHERE in the text."""
    if not text or _STOCK_WORDS_M5.search(text):
        return None
    amounts = {m.group(1) for m in _CASH.finditer(text)} | {m.group(1) for m in _CASH2.finditer(text)}
    return float(next(iter(amounts))) if len(amounts) == 1 else None


def consideration_sentences(text):
    """The sentences that state a per-share dollar amount (Addendum M5): the scope of the cash reader."""
    return [x for x in sentences(text or "") if _CASH.search(x) or _CASH2.search(x)]


def read_cash_consideration(text, stock_words=None):
    """The all-cash price per share in a completion 8-K / merger text, or None (Addendum M5: scoped to the sentence that states the per-share merger consideration; Addendum N5: 'common stock of'
    is not a stock word).  Strict where it looks: in
    EVERY sentence that states a per-share dollar amount there must be none of the words that mean stock, ratios, elections or contingent rights (a cash-and-stock election, an exchange ratio and
    a named acquirer's stock in that sentence still decline), and across those sentences there must be exactly one distinct amount.  A word elsewhere in the document (a mention of an election of directors in another Item, a risk
    factor) does not decline it.  No sentence stating a per-share amount is None (unobservable): a wrong price is worse than none.  `stock_words`: a REPORT-ONLY alternative pattern, never used by the registered run."""
    sw = stock_words if stock_words is not None else _STOCK_WORDS
    scoped = consideration_sentences(text)
    if not scoped or any(sw.search(x) for x in scoped):
        return None
    amounts = {m.group(1) for x in scoped for m in (*_CASH.finditer(x), *_CASH2.finditer(x))}
    return float(next(iter(amounts))) if len(amounts) == 1 else None


def read_equity_cancelled(text):
    """True only when the text says the common stock is cancelled AND that holders receive nothing; otherwise None (not decided by code)."""
    if not text:
        return None
    cancelled = re.search(r"(?:common stock|equity interests?|existing equity)[^.;]{0,80}(?:will be|shall be|are|is)\s+(?:cancelled|canceled|extinguished)", text, re.I)
    nothing = re.search(r"(?:will not|shall not|do not|does not)\s+(?:receive|be entitled to)\s+(?:any\s+)?(?:distribution|recovery|consideration)|no (?:distribution|recovery) (?:to|for) (?:holders of )?(?:common|equity)", text, re.I)
    return True if (cancelled and nothing) else None


def price_event(e, text):
    """The price event of one delisting event (a dict of the D1 event with its evidence) given the text of its completion filing / plan (or None: no reader input): type 'unresolved_<class>' unless
    a strict reader resolves it ('bankruptcy', or 'acquisition' with `cash_per_share`).  Shared by `to_price_events` (keyed by ticker) and the survivorship census (keyed by company)."""
    ev = {"date": e["date"], "type": "unresolved_" + e["class"], "class": e["class"], "evidence": e["evidence"]}
    if e["class"] == "bankruptcy" and read_equity_cancelled(text):
        ev["type"] = "bankruptcy"
    elif e["class"] == "acquisition_completed":
        cash = read_cash_consideration(text)
        if cash is not None:
            ev.update(type="acquisition", cash_per_share=cash)
    return ev


def to_price_events(events, tickers_for, text_for=None):
    """{ticker: delisting event dict for the PriceSource}.  `tickers_for(cik)` -> tickers; `text_for(event)` -> text of the completion filing / plan (or None:
    no reader input).  Without text every event is `unresolved`: type 'unresolved_<class>', which the harness turns into OUTCOME_UNOBSERVABLE with bounds."""
    out = {}
    for e in events:
        ev = price_event(e, text_for(e) if text_for else None)
        for t in tickers_for(e["cik"]):
            out[t] = ev
    return out

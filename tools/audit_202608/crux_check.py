"""crux_check.py - the single owner of the validity of a crux (revision 19, brief_rev19.md sections 1.2-1.4 and B5).

A directional call (undervalued or overvalued) needs a stated disagreement with the price: one to three of the desk's judgment inputs on which
the analyst's evidence says the price is wrong, each with a reason and at least one citation {source, date, quote} of this company's own
evidence. The desk computes the price-implied value of each input (financial_model_tool.price_implied); this module decides, deterministically,
whether the crux is valid, and turns the harness's label into the revision-19 label.

Pure functions, with no I/O except reading the texts passed in. Nothing here is a model call.

Validity (1.3). Every entry must pass, in this order:
  (v1) `input` is one of J, else `not_judgment`;
  (v2) the desk's price-implied value for it is reachable inside its bound, else `not_reachable`;
  (v3) at least one citation is company evidence whose quote is found verbatim in its source: none is company evidence is
       `no_company_evidence`; company evidence is cited but no quote is found is `quote_not_found`.
No crux at all is `missing`. The crux's reason is the first failure found, entries in order. Company evidence is exactly one of two classes:
the company's own filings or release as printed in the pack (sources named `DATA 3`, `DATA 4`, `DATA 5`, `DATA 6`, `GUIDANCE` or, from pack
revision 21, `PRIMARY P#`: an item of the PRIMARY SOURCES section, verbatim, which a URL that is an item's own also names), and a page
fetched in this sample that names the company (the source is its URL). Everything else is context and never company evidence.
"""
import re
import unicodedata

# revision 24 step 2b: long_run_margin (the analyst's earnings margin at the end of the fade, step 2a's desk input) joins the judgment inputs; the
# DEFAULTS block's price_implied line keeps the six inputs it printed (pi_text.INPUTS), for it is solved at defaults this input does not have
J = ("coe", "growth_years_3_5", "fade_years", "terminal_g", "terminal_ronic", "year2_level", "long_run_margin")
REASONS = ("missing", "not_judgment", "not_reachable", "no_company_evidence", "quote_not_found")
PACK_SOURCES = ("DATA 3", "DATA 4", "DATA 5", "DATA 6", "GUIDANCE")
CLASSES = ("pack_company", "fetched_page_naming_company", "generic", "unknown_source")
QUOTE_MIN, QUOTE_MAX = 30, 600
MAX_ENTRIES, MAX_CITATIONS = 3, 5
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# "At its default" (1.1): the analyst's value within the tolerance of the DEFAULTS value.
TOL_COE = 0.0005
TOL_GROWTH = 0.0005
TOL_TERMINAL_G = 0.0001
TOL_TERMINAL_RONIC = 0.0001
TOL_LEVEL = 0.005
_EPS = 1e-9               # "within" a tolerance includes the tolerance itself, whatever the float arithmetic says

# code points (written as numbers: several of these characters are invisible)
_QUOTE_MAP = {0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",  # typographic single quotes and the prime
              0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"', 0x2033: '"',  # typographic double quotes and the double prime
              0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2015: "-", 0x2212: "-"}   # hyphens, dashes and the minus sign
# invisible characters a filing carries and a copy leaves out: zero-width and word-joiner characters, the soft hyphen, the direction marks and the
# invisible operators (revision 21, Q2: the round trip of a filing's every sentence)
_ZERO_WIDTH = {0x200B: None, 0x200C: None, 0x200D: None, 0x2060: None, 0xFEFF: None, 0x00AD: None, 0x200E: None, 0x200F: None,
               0x202A: None, 0x202B: None, 0x202C: None, 0x202D: None, 0x202E: None, 0x2061: None, 0x2062: None, 0x2063: None, 0x2064: None}
_PRE_NFKC = {0x2033: '"', 0x2036: '"'}                                          # the double prime and the reversed double prime, before NFKC reads them
_OWN_WORDS = re.compile(r"^(?:STALE \(\d+ days\) " + chr(0x2014) + r" )?COMPANY'S OWN WORDS")


def normalise(text):
    """The text as the verbatim test reads it: NFKC; typographic quotes made straight; en and em dashes made a hyphen; zero-width
    characters removed; every run of whitespace one space; stripped. Matching on it is case-sensitive."""
    s = "" if text is None else str(text)
    s = s.translate(_PRE_NFKC)                    # NFKC would turn a double prime into two primes, which a copy cannot be told from two apostrophes
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_QUOTE_MAP).translate(_ZERO_WIDTH)
    return re.sub(r"\s+", " ", s).strip()


def pack_sources(pack_text):
    """{source name: text} for the company-evidence sources the pack prints (1.3). A `DATA n` source (n = 3, 4, 5, 6) is its section, from its
    `## DATA n` header to the next `## ` header (DATA 6 includes its `### DATA 6A/6B/6C` subsections); GUIDANCE is only the company's part, from
    the line starting `COMPANY'S OWN WORDS` (a stale release carries a `STALE (n days) - ` prefix on that line) to the line starting
    `Research-brief rows`, exclusive. A source the pack does not print is absent."""
    lines = (pack_text or "").split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    out = {}
    for n in (3, 4, 5, 6):
        pat = re.compile(r"^## DATA %d(?:\s|$)" % n)
        for k, i in enumerate(heads):
            if pat.match(lines[i]):
                end = heads[k + 1] if k + 1 < len(heads) else len(lines)
                out["DATA %d" % n] = "\n".join(lines[i:end])
                break
    start = next((i for i, l in enumerate(lines) if _OWN_WORDS.match(l)), None)
    if start is not None:
        end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("Research-brief rows")), len(lines))
        out["GUIDANCE"] = "\n".join(lines[start:end])
    return out


def _body(call):
    return call.get("result") if isinstance(call.get("result"), dict) else call


def fetched_texts(calls):
    """{normalised URL: the concatenation, in call order, of the text of every `fetch_page` record of the sample that carries no error} (1.3):
    only what the model was shown (a call refused with a pointer to PRIMARY SOURCES fetched nothing). A record counts under the URL it was asked for and under the URL the page was served from, when they differ;
    a fetched page that served no text is still a fetched page (its text is empty)."""
    import catalyst_research
    parts = {}
    for c in calls or []:
        if not isinstance(c, dict) or c.get("tool") != "fetch_page":
            continue
        body = _body(c)
        if not isinstance(body, dict) or body.get("error") or body.get("refused") or c.get("error"):
            continue
        if body.get("served_from_primary") is not None:       # revision 21: a pointer to PRIMARY SOURCES, no page was fetched
            continue
        text = body.get("text")
        keys = {catalyst_research.normalize_url(str((c.get("params") or {}).get("url") or "")),
                catalyst_research.normalize_url(str(body.get("url") or ""))} - {""}
        for k in keys:
            parts.setdefault(k, [])
            if isinstance(text, str):
                parts[k].append(text)
    return {k: "\n".join(v) for k, v in parts.items()}


def _is_url(source):
    return re.match(r"^https?://", source.strip(), re.I) is not None


def _pack_source_name(source):
    s = source.strip()
    if s in ("DATA 6A", "DATA 6B", "DATA 6C"):
        return "DATA 6"
    return s if s in PACK_SOURCES else None


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _as_float(x):
    if x == "unlimited":
        return float("inf")
    return float(x) if _num(x) else None


def at_default(name, own, defaults, own_path=None):
    """Is the analyst's value of `name` at its DEFAULTS value (1.1)? `defaults` is the pack's facts object. False when the DEFAULTS value is not
    available (an input cannot be at a default the pack does not print)."""
    d = defaults or {}
    if name == "coe":
        a, b = _as_float(own), d.get("coe_anchor")
        return a is not None and _num(b) and abs(a - b) <= TOL_COE + _EPS
    if name == "growth_years_3_5":
        ref = d.get("reference_path")
        if not (isinstance(own_path, (list, tuple)) and len(own_path) == 3 and isinstance(ref, (list, tuple)) and len(ref) >= 5):
            return False
        return all(_num(a) and _num(b) and abs(a - b) <= TOL_GROWTH + _EPS for a, b in zip(own_path, ref[2:5]))
    if name == "fade_years":
        import consensus_reference
        return _num(own) and own == consensus_reference.FADE_YEARS
    if name == "terminal_g":
        a, b = _as_float(own), d.get("terminal_g_default")
        return a is not None and _num(b) and abs(a - b) <= TOL_TERMINAL_G + _EPS
    if name == "terminal_ronic":
        a, b = _as_float(own), d.get("terminal_ronic")
        if a is None or not _num(b):
            return False
        if a == float("inf") or b == float("inf"):
            return a == b
        return abs(a - b) <= TOL_TERMINAL_RONIC + _EPS
    if name == "year2_level":
        a, b = _as_float(own), (d.get("levels") or {}).get("year2")
        return a is not None and _num(b) and b != 0 and abs(a - b) / abs(b) <= TOL_LEVEL + _EPS
    return False


def primary_items(pack_text):
    """The PRIMARY SOURCES items the pack prints (revision 21): [{"id", "type", "form", "accession", "filed", "period", "url", "title", "text"}],
    sec_primary.parse_pack's; empty for a pack that prints none (an older pack, or `not available`)."""
    import sec_primary
    return sec_primary.parse_pack(pack_text)


def classify_citations(citations, sources, fetched, company, ticker, primary=None):
    """[{"source", "class", "quote_found"}] for the citations of one entry. `sources` is `pack_sources(pack)`, `fetched` is `fetched_texts(calls)`,
    `primary` is `primary_items(pack)` (revision 21; None reads none).
    The class is `pack_company` (a pack source named exactly, or a PRIMARY source: `PRIMARY P1`, `P1`, or an sec.gov URL that is a primary item's
    own, which resolves to that item; the quote is looked for in that item's text), `fetched_page_naming_company` (a URL fetched in this sample, no error, whose text
    names the company by the news filter's rule), `unknown_source` (a URL not fetched in this sample) or `generic` (anything else, including a
    fetched page that does not name the company). `quote_found` is whether the normalised quote is a substring of the normalised source text, for
    the two company classes; None for the others (context is never checked: it can never be company evidence)."""
    out = []
    name_ok = {}
    for c in citations if isinstance(citations, list) else []:
        src = c.get("source") if isinstance(c, dict) else None
        quote = c.get("quote") if isinstance(c, dict) else None
        rec = {"source": src if isinstance(src, str) else None, "class": "generic", "quote_found": None}
        if isinstance(src, str) and src.strip():
            pack_name = _pack_source_name(src)
            item = None if pack_name is not None else _primary_item(src, primary, quote)
            if pack_name is not None:
                rec["class"] = "pack_company"
                text = sources.get(pack_name, "")
                rec["quote_found"] = _found(quote, text)
            elif item is not None:
                rec["class"] = "pack_company"
                rec["quote_found"] = _found(quote, item["text"])
            elif _is_url(src):
                import catalyst_research
                key = catalyst_research.normalize_url(src.strip())
                if key not in fetched:
                    rec["class"] = "unknown_source"
                else:
                    if key not in name_ok:
                        name_ok[key] = _names_company(fetched[key], company, ticker)
                    if name_ok[key]:
                        rec["class"] = "fetched_page_naming_company"
                        rec["quote_found"] = _found(quote, fetched[key])
        out.append(rec)
    return out


def _primary_item(src, primary, quote):
    if not primary:
        return None
    import sec_primary
    return sec_primary.resolve_source(src, primary, quote)


def _found(quote, text):
    q = normalise(quote)
    return bool(q) and q in normalise(text)


def _names_company(text, company, ticker):
    """The news filter's own rule on the page text as a headline: the full name, or the ticker in a finance pattern. With neither a company
    name nor a ticker to test, no page names the company."""
    if not (company or ticker):
        return False
    import company_news
    return bool(company_news.names_company(company_news._clean_company_name(company, ticker), ticker, title=text))


def check(crux, price_implied, pack_text, calls, company, ticker, defaults):
    """The validity of a crux (1.3). `crux` is the answer call's crux argument, `price_implied` its block (the desk's), `pack_text` the pack the
    model read, `calls` the sample's snapshot calls, `company` and `ticker` the name for the news filter's rule, `defaults` the pack's facts.
    Returns {"valid", "reason", "entries": [{"input", "own", "implied", "reachable", "at_default", "citations": [{"source", "class",
    "quote_found"}], "valid", "reason"}]}: the crux's reason is the first failure found, entries in order, v1 then v2 then v3 within an entry;
    None when valid. An entry with its own failure keeps it in "reason" whatever the others are."""
    if not isinstance(crux, list) or not crux:
        return {"valid": False, "reason": "missing", "entries": []}
    sources = pack_sources(pack_text)
    fetched = fetched_texts(calls)
    primary = primary_items(pack_text)
    pi = price_implied if isinstance(price_implied, dict) and not price_implied.get("error") else {}
    entries = []
    for e in crux:
        entry = e if isinstance(e, dict) else {}
        name = entry.get("input")
        blk = pi.get(name) if isinstance(name, str) else None
        blk = blk if isinstance(blk, dict) else {}
        rec = {"input": name if isinstance(name, str) else None, "own": blk.get("own"), "implied": blk.get("value"),
               "reachable": bool(blk.get("reachable")) if blk else False, "at_default": False, "citations": [], "valid": False, "reason": None}
        if not isinstance(e, dict) or not e:
            rec["reason"] = "missing"
        elif name not in J:
            rec["reason"] = "not_judgment"
        else:
            rec["at_default"] = at_default(name, blk.get("own"), defaults, blk.get("own_path"))
            rec["citations"] = classify_citations(entry.get("citations"), sources, fetched, company, ticker, primary)
            if not rec["reachable"]:
                rec["reason"] = "not_reachable"
            else:
                company_ev = [c for c in rec["citations"] if c["class"] in ("pack_company", "fetched_page_naming_company")]
                if not company_ev:
                    rec["reason"] = "no_company_evidence"
                elif not any(c["quote_found"] for c in company_ev):
                    rec["reason"] = "quote_not_found"
                else:
                    rec["valid"] = True
        entries.append(rec)
    first = next((x for x in entries if not x["valid"]), None)
    return {"valid": first is None, "reason": None if first is None else first["reason"], "entries": entries}


def label19(base, price, chk):
    """(label, direction_m, stamps) for revision 19 (1.4). direction_m is the revision-18 label (`contract_fill.label`: the base against the price,
    plus or minus 10%); stamped on every sample. When it is undervalued or overvalued the label is direction_m if the crux is valid, else hold
    with the stamp `no_valid_crux:<reason>`; a valid crux with an entry at its default is stamped `crux_at_default`. Otherwise the label is
    direction_m with no stamp. None, None, [] when there is no base or price."""
    from contract_fill import label
    dm = label(base, price)
    if dm is None:
        return None, None, []
    if dm not in ("undervalued", "overvalued"):
        return dm, dm, []
    if chk and chk.get("valid") is True:
        stamps = ["crux_at_default"] if any(e.get("at_default") for e in chk.get("entries") or []) else []
        return dm, dm, stamps
    reason = (chk or {}).get("reason") or "missing"
    return "hold", dm, [f"no_valid_crux:{reason}"]


def form_problems(crux, run_date):
    """The desk's form check (B2): the problems with the `crux` argument as sent, each a sentence for a refusal; [] when it is well formed or absent
    (a crux is optional: none means HOLD, never a refusal). A crux is a list of one to three objects; each carries an `input` in J, a `reason` that
    reads as given, and a list of one to five citations, each with a non-empty `source`, a `date` of the form YYYY-MM-DD that is not after
    `run_date` (an ISO date string), and a `quote` of 30 to 600 characters after normalising."""
    if crux is None:
        return []
    if not isinstance(crux, list) or not 1 <= len(crux) <= MAX_ENTRIES:
        return ["crux (a list of one to three entries, each {input, reason, citations})"]
    problems = []
    for i, e in enumerate(crux, 1):
        tag = f"crux[{i}]"
        if not isinstance(e, dict):
            problems.append(f"{tag} (an object with input, reason and citations)")
            continue
        if e.get("input") not in J:
            problems.append(f"{tag}.input (one of {', '.join(J)})")
        r = e.get("reason")
        s = "" if r is None else str(r).strip()
        if s == "" or s.lower() in ("null", "none"):
            problems.append(f"{tag}.reason (why this company's value of the input differs from what the price implies, and by how much)")
        cits = e.get("citations")
        if not isinstance(cits, list) or not 1 <= len(cits) <= MAX_CITATIONS:
            problems.append(f"{tag}.citations (one to five of {{source, date, quote}})")
            continue
        for k, c in enumerate(cits, 1):
            ct = f"{tag}.citations[{k}]"
            if not isinstance(c, dict):
                problems.append(f"{ct} (an object with source, date and quote)")
                continue
            src = c.get("source")
            if not isinstance(src, str) or not src.strip():
                problems.append(f"{ct}.source (PRIMARY P#, DATA 3, DATA 4, DATA 5, DATA 6, GUIDANCE or the URL of a page you fetched)")
            d = c.get("date")
            if not isinstance(d, str) or not DATE_RE.match(d):
                problems.append(f"{ct}.date (YYYY-MM-DD)")
            elif run_date is not None and d > run_date:
                problems.append(f"{ct}.date ({d} is after the run's date {run_date})")
            q = c.get("quote")
            n = len(normalise(q)) if isinstance(q, str) else -1
            if not QUOTE_MIN <= n <= QUOTE_MAX:
                problems.append(f"{ct}.quote ({QUOTE_MIN} to {QUOTE_MAX} characters copied exactly from the source)")
    return problems

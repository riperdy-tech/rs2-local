"""r26_stages.py - the staged analyst of revision 26 (SPEC_rev26_staged_analyst.md): four separate model sessions joined only by artifacts.

    stage1  research and the fact ledger      -> dossier.json     (built here: brief R26-A1)
    stage2  the blind forecast, K = 3 samples -> forecasts.json   (stub: brief R26-A2, on R26-C's functions)
    stage3  reveal and reconcile, one revision-> reveal.json      (stub: brief R26-A2)
    stage4  the memorandum                    -> final.json       (stub: brief R26-A2)

Every stage starts from a FRESH message list built only from the artifacts the SPEC names for it (ALLOWED_INPUTS; `fresh_messages` refuses any
other); no stage reads another stage's messages, reasoning or tool results. The artifacts are written under the run directory. Every model turn of
every stage is logged by the ollama_raw provider under <run_dir>/turns/<stage>_<n>.json (turn_log.py; SPEC section 0).

STAGE 1
-------
The session sees the blind pack (the pack without its valuation TASK), the tools search_web, fetch_page and register_facts, and the stage-1 TASK. It
researches, registers facts (each with the exact quote it rests on) and ends with register_facts(done=true, research_summary=...). Code checks every
fact and ANNOTATES it (SPEC section 1); nothing is deleted:

  quote            `quote_verified` when the quote occurs in its source after NORMALIZATION (below), else `quote_not_found`.
  proximity        every content word of `metric` and of `entity` must occur within +-300 characters of the quote's place in the source, else
                   `metric_not_near_quote` naming the missing words. When the quote occurs more than once, the occurrence with the fewest missing
                   words counts. Content words: letters-only tokens of at least 4 letters, lower-cased, not in STOPWORDS, a plural -s/-ies folded.
  value            `value_in_quote` when a number written in the quote equals `value` in the same written form (WRITTEN FORMS below), else
                   `value_not_in_quote`; `value_null` when the fact carries no value.
  usable           a fact is usable iff it is well-formed, `quote_verified` and not `metric_not_near_quote`. The others stay in the dossier, with
                   the reason, and later stages list them as "unusable, why".
  incomplete       the dossier is marked `incomplete` (with the cause) when the session ended without an accepted register_facts(done=true).

NORMALIZATION (applied to the quote and to the source alike; the quote is found in the normalized source and mapped back to the source's own
character positions for the proximity window): Unicode NFKC; case folded; every whitespace character dropped (HTML-stripped pages put spaces where
tags were: "$ 274.4" and "$274.4" are the same text); the markdown marks * and ` dropped; the curly single quotes and primes become ', the curly double
quotes become ", every dash variant (hyphen, non-breaking hyphen, en dash, em dash, minus sign) becomes -. All other punctuation is KEPT, so 1.5 never
equals 15. For a pack source the "> " that opens each line of a quoted filing is removed first.

WRITTEN FORMS of a value: the quote's number tokens are read as [sign] [$] digits[,digits][.digits] [unit word], the sign being a leading - or minus sign,
or parentheses; a unit word scales the token (thousand/k 1e3, million/mm/mn/m 1e6, billion/bn/b 1e9, trillion/tn/t 1e12; % and percent do not scale). The value is
in the quote when it equals a token or a token times its own scale, compared as exact decimals. 12.5 matches "12.5%" and "$12.5 million"; 12500000 matches "$12.5 million"; it does not match "0.125", "125", "-12.5" or "12,500 thousand".

SOURCES a fact may cite: `pack:<section id>`, `page:<url>` (a page this session fetched), `query:Q<n>` (the n-th tool call, a search this session ran;
its text is the results it returned: title, url, snippet). A pack section id is the slug of a pack heading: see pack_sections().
"""
import copy
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
from decimal import Decimal, InvalidOperation
from pathlib import Path

_AUDIT_DIR = str(Path(__file__).resolve().parent)
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)
_REPO = str(Path(__file__).resolve().parents[2])
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import analyst_tools  # noqa: E402
import llm_provider  # noqa: E402
import sec_primary  # noqa: E402
import turn_log  # noqa: E402

PACK_REVISION_R26 = 26
ARM = "r26"
STAGES = ("stage1", "stage2", "stage3", "stage4")
ARTIFACTS = {"stage1": "dossier.json", "stage2": "forecasts.json", "stage3": "reveal.json", "stage4": "final.json"}

# What each stage may be handed (SPEC sections 1-4). `fresh_messages` refuses any other name, so a stage cannot be given another stage's reasoning.
ALLOWED_INPUTS = {
    "stage1": {"blind_pack", "task"},
    "stage2": {"blind_pack", "dossier", "op_margin_bar", "task"},
    "stage3": {"dossier", "median_forecast", "median_desk_result", "base_values", "price", "price_implied_inputs", "consensus_corrected",
               "diagnostics", "task"},
    "stage4": {"dossier", "frozen_desk_result", "bridge_table", "crux", "crux_verification", "stage2_spread", "diagnostics", "task"},
}

QUOTE_MAX_CHARS = 400
PROXIMITY_CHARS = 300
SUMMARY_MAX_WORDS = 600
BASIS_VALUES = ("filed_gaap", "company_adjusted", "third_party", "n/a")
FACT_FIELDS = ("fact_id", "source", "quote", "entity", "metric", "period", "value", "unit", "basis", "duration_years")
SOURCE_RE = re.compile(r"^(pack|page|query):(\S.*)$", re.S)

# English function words plus the corporate-form words every company name carries; no industry term, no company term.
STOPWORDS = frozenset("""
about above after again against all also and any are because been before being below between both but can could did does doing down during each
few for from further had has have having her here hers him his how into its itself just more most other our ours out over own same she should
some such than that the their theirs them then there these they this those through too under until upon very was were what when where which while
who whom why will with would you your yours
corporation company companies incorporated limited holdings holding group inc corp
""".split())


# ---------------------------------------------------------------- the pack's section ids

_HEADING = re.compile(r"^(#{2,3}) +(.+?) *$")
_ITEM = re.compile(r"^\[P(\d+)\]")


def slug(text):
    """lower case; every run of characters other than a-z, 0-9 and the dot becomes one hyphen; no leading or trailing hyphen."""
    return re.sub(r"[^a-z0-9.]+", "-", (text or "").lower()).strip("-.")


def strip_quote_marks(text):
    """The "> " that opens each line of a quoted filing in the pack."""
    return re.sub(r"(?m)^> ?", "", text)


def pack_sections(pack_text):
    """{section id: text} for a pack. A pack section opens at a line `## ...` or `### ...` whose title (the heading up to its first " - ", " [" or
    two spaces) has no lower-case letter: `## DATA 5 - FISCAL-YEAR ...` -> `data-5`, `### DATA 6A - ...` -> `data-6a`, `## GUIDANCE & CONSENSUS   [...]` ->
    `guidance-consensus`, `## PRIMARY SOURCES   [...]` -> `primary-sources`, `## DEFAULTS` -> `defaults`. The headings of the research brief inside DATA 11
    (`## Competitive Position & Moat`) have lower-case letters, so they are not sections: the brief is part of `data-11`. A section's text runs to the
    next section heading of the same or a higher level (a `###` section is inside its `##` parent as well). A repeated id gets -2, -3. Each filing item
    `[P1]` .. `[Pn]` of PRIMARY SOURCES is also a section: `primary-p1` .. `primary-pn`. Ids are lower case; `section_id()` slugs a model's spelling."""
    lines = (pack_text or "").split("\n")
    heads = []                                  # (line index, level, id)
    seen = {}
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if not m:
            continue
        title = re.split(r" - | \[|  ", m.group(2), maxsplit=1)[0].strip()
        if not re.search(r"[A-Za-z]", title) or title != title.upper():
            continue
        sid = slug(title)
        if not sid:
            continue
        seen[sid] = seen.get(sid, 0) + 1
        if seen[sid] > 1:
            sid = f"{sid}-{seen[sid]}"
        heads.append((i, len(m.group(1)), sid))
    out = {}
    for k, (i, level, sid) in enumerate(heads):
        end = len(lines)
        for j, lv, _ in heads[k + 1:]:
            if lv <= level:
                end = j
                break
        out[sid] = "\n".join(lines[i:end])
    prim = out.get("primary-sources")
    if prim is not None:
        plines = prim.split("\n")
        starts = [(i, int(m.group(1))) for i, ln in enumerate(plines) for m in [_ITEM.match(ln)] if m]
        for k, (i, n) in enumerate(starts):
            j = starts[k + 1][0] if k + 1 < len(starts) else len(plines)
            out.setdefault(f"primary-p{n}", "\n".join(plines[i:j]))
    return out


def section_id(text):
    """The id a model's spelling of a section means: `DATA 5`, `data-5`, `PRIMARY P1` -> data-5, data-5, primary-p1."""
    return slug(text)


TASK_SEPARATOR = "\n\n---\n\nYou are underwriting this company"


def split_task(pack):
    """(pack without its valuation TASK, True) when `pack` ends with the TASK block of the revision-24 family (the separator line and the TASK's first
    sentence), whatever follows the TASK (the research addendum) included; else (pack, False)."""
    k = pack.rfind(TASK_SEPARATOR)
    if k < 0:
        return pack, False
    return pack[:k], True


# ---------------------------------------------------------------- normalization and the three fact checks

_CHARMAP = {}
for _c in "‘’‚‛′´":
    _CHARMAP[_c] = "'"
for _c in "“”„‟″":
    _CHARMAP[_c] = '"'
for _c in "‐‑‒–—―−﹣－":
    _CHARMAP[_c] = "-"
_DROPPED = frozenset("*`​‌‍⁠﻿")


def normalize_with_map(text):
    """(normalized text, positions): the NORMALIZATION of the module docstring, and for each normalized character the index of the source character it came from."""
    out, pos = [], []
    for i, ch in enumerate(text or ""):
        for c in unicodedata.normalize("NFKC", ch):
            if c.isspace() or c in _DROPPED:
                continue
            c = _CHARMAP.get(c, c)
            for c2 in c.casefold():
                out.append(c2)
                pos.append(i)
    return "".join(out), pos


def normalize(text):
    return normalize_with_map(text)[0]


def find_quote(source, quote, limit=50):
    """[(start, end)] character spans of `source` (the source's own indexes) where the normalized quote occurs in the normalized source."""
    nq = normalize(quote)
    if not nq:
        return []
    ns, pos = normalize_with_map(source)
    spans, k = [], ns.find(nq)
    while k >= 0 and len(spans) < limit:
        spans.append((pos[k], pos[k + len(nq) - 1] + 1))
        k = ns.find(nq, k + 1)
    return spans


def _stem(w):
    if w.endswith("ies") and len(w) > 5:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 4:
        return w[:-1]
    return w


def content_word_forms(text):
    """{folded form: the word as written (lower case)} for the letters-only tokens of at least 4 letters that are not stopwords; plurals fold (-s, -ies)."""
    return {_stem(w): w for w in (t.lower() for t in re.findall(r"[^\W\d_]+", text or "")) if len(w) >= 4 and w not in STOPWORDS}


def content_words(text):
    """The folded content words of `text`, a set."""
    return set(content_word_forms(text))


def _window(source, a, b, radius):
    """source[a - radius : b + radius], a word cut by either edge kept whole."""
    lo, hi = max(0, a - radius), min(len(source), b + radius)
    while 0 < lo < len(source) and source[lo].isalpha() and source[lo - 1].isalpha():
        lo -= 1
    while 0 < hi < len(source) and source[hi].isalpha() and source[hi - 1].isalpha():
        hi += 1
    return source[lo:hi]


def proximity(source, spans, entity, metric, radius=PROXIMITY_CHARS):
    """(missing words sorted, the span used): over the quote's occurrences, the one whose window (`radius` characters each side of the quote, in the source's
    own characters) misses the fewest content words of `entity` and `metric`; the words are named as the model wrote them. No content word at all gives no
    missing word (nothing to look for)."""
    need = {**content_word_forms(entity), **content_word_forms(metric)}
    best = None
    for a, b in spans:
        have = content_words(_window(source, a, b, radius))
        miss = sorted(need[k] for k in need if k not in have)
        if best is None or len(miss) < len(best[0]):
            best = (miss, (a, b))
        if not miss:
            break
    return best if best is not None else (sorted(need.values()), None)


_SCALES = {"thousand": Decimal(10) ** 3, "k": Decimal(10) ** 3, "million": Decimal(10) ** 6, "mm": Decimal(10) ** 6, "mn": Decimal(10) ** 6,
           "m": Decimal(10) ** 6, "billion": Decimal(10) ** 9, "bn": Decimal(10) ** 9, "b": Decimal(10) ** 9, "trillion": Decimal(10) ** 12,
           "tn": Decimal(10) ** 12, "t": Decimal(10) ** 12, "%": Decimal(1), "percent": Decimal(1)}
_NUMBER = re.compile(r"(?P<pre>[(\-−–—])?\s*\$?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                     r"(?:\s*(?P<unit>%|(?:thousand|million|billion|trillion|percent)\b|(?:mm|mn|bn|tn|k|m|b|t)\b))?(?P<post>\))?", re.I)


def number_tokens(quote):
    """[(Decimal value, scale Decimal)] for every number written in `quote` (signed; the scale of its unit word, 1 without one)."""
    out = []
    for m in _NUMBER.finditer(quote or ""):
        try:
            v = Decimal(m.group("num").replace(",", ""))
        except InvalidOperation:
            continue
        pre = m.group("pre")
        if pre in ("-", "−", "–", "—") or (pre == "(" and m.group("post") == ")"):
            v = -v
        unit = (m.group("unit") or "").lower()
        out.append((v, _SCALES.get(unit, Decimal(1))))
    return out


def value_in_quote(value, quote):
    """True when `value` equals a number written in `quote` or that number times its unit word's scale (module docstring, WRITTEN FORMS)."""
    try:
        want = Decimal(repr(float(value))) if not isinstance(value, int) else Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return False
    return any(want == v or want == v * s for v, s in number_tokens(quote))


# ---------------------------------------------------------------- the facts

def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_fact_shape(f):
    """[problem, ...] for a fact object that does not have the SPEC section 1 shape; [] when it does."""
    if not isinstance(f, dict):
        return ["the fact is not an object"]
    bad = []
    for k in FACT_FIELDS:
        if k not in f:
            bad.append(f"{k} is missing")
    for k in ("fact_id", "source", "quote", "entity", "metric", "period", "unit"):
        if k in f and (not isinstance(f[k], str) or not f[k].strip()) and not (k == "unit" and f[k] == ""):
            bad.append(f"{k} must be a non-empty string")
    if "source" in f and isinstance(f["source"], str) and f["source"].strip() and not SOURCE_RE.match(f["source"].strip()):
        bad.append("source must be pack:<section id>, page:<url> or query:<query id>")
    if "value" in f and f["value"] is not None and not _is_number(f["value"]):
        bad.append("value must be a number or null")
    if "basis" in f and f["basis"] not in BASIS_VALUES:
        bad.append(f"basis must be one of {', '.join(BASIS_VALUES)}")
    if "duration_years" in f:
        d = f["duration_years"]
        if not (d is None or d == "ongoing" or (_is_number(d) and d >= 0)):
            bad.append('duration_years must be a number of years, "ongoing" or null')
    return bad


def company_words(company, ticker):
    """The folded content words of the pack company's name plus its ticker (lower case): the entity words a `pack:` fact need not find near its quote."""
    return content_words(company) | ({_stem(ticker.lower())} if ticker else set())


def check_fact(fact, source_text, waived=None):
    """The SPEC section 1 annotations of one well-formed fact against the text of its source (None when the source could not be resolved).
    Returns {"quote_status", "quote_over_400_chars", "proximity_status", "missing_words", "value_status", "usable", "unusable_reason"}."""
    quote = fact["quote"]
    rec = {"quote_status": None, "quote_over_400_chars": len(quote.strip()) > QUOTE_MAX_CHARS, "proximity_status": "not_checked", "missing_words": [],
           "value_status": ("value_null" if fact["value"] is None else
                            ("value_in_quote" if value_in_quote(fact["value"], quote) else "value_not_in_quote"))}
    spans = find_quote(source_text, quote) if source_text is not None else []
    rec["quote_status"] = "quote_verified" if spans else "quote_not_found"
    if spans:
        miss, _ = proximity(source_text, spans, fact["entity"], fact["metric"])
        if waived and miss:
            # a `pack:` source: the pack is about the company, so its name tokens and ticker as ENTITY words count as satisfied (never as metric words)
            keep = {w: w for w in content_word_forms(fact["entity"]).values() if _stem(w) not in waived}
            miss2, _ = proximity(source_text, spans, " ".join(keep), fact["metric"])
            rec["entity_from_pack_company"] = sorted(set(miss) - set(miss2))
            miss = miss2
        rec["missing_words"] = miss
        rec["proximity_status"] = "metric_not_near_quote" if miss else "near"
    rec["usable"] = rec["quote_status"] == "quote_verified" and rec["proximity_status"] != "metric_not_near_quote"
    rec["unusable_reason"] = (None if rec["usable"] else
                              ("source not resolved" if source_text is None else "quote not found in its source")
                              if rec["quote_status"] != "quote_verified" else
                              "metric_not_near_quote: " + ", ".join(rec["missing_words"]))
    return rec


class Evidence:
    """What a fact's source names, as this session saw it: the pack's sections, the pages it fetched, the searches it ran."""

    def __init__(self, pack_text, url_cache):
        self.sections = pack_sections(pack_text)
        self.url_cache = url_cache
        self.fetched = {}               # url the model asked for (and the url it was served) -> the url cache key of the page
        self.queries = {}               # "Q<n>" -> the text of the results returned

    @staticmethod
    def _norm_url(u):
        return (u or "").split("#", 1)[0].rstrip("/")

    def resolve(self, source):
        """(text, None) or (None, why) for a fact's `source`."""
        m = SOURCE_RE.match((source or "").strip())
        if not m:
            return None, "malformed source"
        kind, key = m.group(1), m.group(2).strip()
        if kind == "pack":
            sid = section_id(key)
            if sid in self.sections:
                return strip_quote_marks(self.sections[sid]), None
            return None, f"no pack section {sid!r} (known: {', '.join(self.sections)})"
        if kind == "query":
            qid = key.upper()
            if qid in self.queries:
                return self.queries[qid], None
            return None, f"no search {qid!r} was run in this session"
        want = self._norm_url(key)
        for u, cache_key in self.fetched.items():
            if self._norm_url(u) == want:
                rec = self.url_cache.get(cache_key) or {}
                text = rec.get("full_text") if rec.get("full_text") is not None else rec.get("text")
                if text is not None:
                    return text, None
        return None, f"page {key!r} was not fetched in this session"


class Ledger:
    """The facts of stage 1 with their annotations."""

    def __init__(self, evidence, company=None, ticker=None):
        self.evidence = evidence
        self.waived = company_words(company, ticker)
        self.facts = []             # annotated facts, in registration order
        self.rejected = []          # {"fact_id", "why"} - a fact that could not be kept (a repeated fact_id)
        self.done = False
        self.summary = ""
        self.calls_refused = []     # register_facts calls that were not understood at all

    def _ids(self):
        return {f["fact_id"] for f in self.facts}

    def register(self, args):
        """Apply one register_facts call; returns the tool result shown to the model."""
        facts = args.get("facts")
        if isinstance(facts, dict):
            facts = [facts]
        if facts is None:
            facts = []
        if not isinstance(facts, list):
            self.calls_refused.append("facts is not a JSON array")
            return {"error": "facts must be a JSON array of fact objects; nothing was registered."}
        shown = []
        for raw in facts:
            f = copy.deepcopy(raw) if isinstance(raw, dict) else raw
            problems = validate_fact_shape(f)
            fid = f.get("fact_id") if isinstance(f, dict) else None
            if not problems and f["fact_id"] in self._ids():
                self.rejected.append({"fact_id": f["fact_id"], "why": "fact_id already registered"})
                shown.append({"fact_id": f["fact_id"], "status": "rejected: fact_id already registered; use a new id"})
                continue
            if problems:
                rec = {**(f if isinstance(f, dict) else {"raw": f}), "statuses": {"shape": "malformed", "problems": problems},
                       "usable": False, "unusable_reason": "malformed: " + "; ".join(problems)}
                if not isinstance(fid, str) or not fid.strip() or fid in self._ids():
                    rec["fact_id"] = f"_malformed_{len(self.facts) + 1}"
                self.facts.append(rec)
                shown.append({"fact_id": rec["fact_id"], "status": rec["unusable_reason"]})
                continue
            text, why = self.evidence.resolve(f["source"])
            chk = check_fact(f, text, self.waived if f["source"].strip().lower().startswith("pack:") else None)
            statuses = {k: chk[k] for k in ("quote_status", "proximity_status", "missing_words", "value_status", "quote_over_400_chars")}
            if chk.get("entity_from_pack_company"):
                statuses["entity_from_pack_company"] = chk["entity_from_pack_company"]
            if why:
                statuses["source_problem"] = why
            rec = {**f, "statuses": statuses, "usable": chk["usable"], "unusable_reason": chk["unusable_reason"]}
            if why:
                rec["unusable_reason"] = f"{chk['unusable_reason']} ({why})"
            self.facts.append(rec)
            shown.append({"fact_id": f["fact_id"], "status": ", ".join(
                [chk["quote_status"], *(["metric_not_near_quote: " + ", ".join(chk["missing_words"])] if chk["proximity_status"] == "metric_not_near_quote" else []),
                 chk["value_status"], "usable" if chk["usable"] else "unusable"])})
        out = {"registered": shown, "facts_registered": len(self.facts), "facts_usable": sum(1 for x in self.facts if x["usable"])}
        if args.get("done") is True:
            summary = args.get("research_summary")
            if not isinstance(summary, str) or not summary.strip():
                out["done"] = "not accepted: done=true needs research_summary (at most 600 words). Call register_facts again with done=true and the summary."
            else:
                self.done, self.summary = True, summary.strip()
                out["done"] = "accepted"
        elif "research_summary" in args and isinstance(args.get("research_summary"), str) and args["research_summary"].strip():
            out["note"] = "research_summary is read only with done=true"
        return out

    def dossier(self, **extra):
        usable = [f for f in self.facts if f["usable"]]
        return {
            "schema": "r26.dossier.v1", "stage": "stage1", "pack_revision": PACK_REVISION_R26,
            "done": self.done, "incomplete": not self.done,
            "summary": self.summary, "summary_words": len(self.summary.split()),
            "summary_over_600_words": len(self.summary.split()) > SUMMARY_MAX_WORDS,
            "facts": self.facts, "rejected": self.rejected,
            "counts": {"facts": len(self.facts), "usable": len(usable), "unusable": len(self.facts) - len(usable)},
            **extra,
        }


def usable_facts(dossier):
    return [f for f in dossier["facts"] if f.get("usable")]


def unusable_listing(dossier):
    """[(fact_id, why)] for the facts later stages list as "unusable, why"."""
    return [(f["fact_id"], f.get("unusable_reason")) for f in dossier["facts"] if not f.get("usable")]


# ---------------------------------------------------------------- the register_facts tool and the stage-1 TASK

REGISTER_FACTS_TOOL = {
    "type": "function",
    "function": {
        "name": "register_facts",
        "description": (
            "Register the facts the valuation will need, each with the exact quote it rests on. Call it as often as you like while you research, and "
            "finish the stage by calling it once with done=true and your research_summary. Code checks every fact against its source: that the quote "
            "occurs there verbatim, that the entity and the metric are named near it, and that the value is written in the quote. A fact that fails a "
            "check is kept with its status and cannot be used by later stages, so quote the source exactly. A fact has no number when value is null "
            "(a qualitative fact). A later stage sees only the facts you register and the summary: it cannot see this research."),
        "parameters": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "description": "The facts to register in this call (an empty list is allowed with done=true).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact_id": {"type": "string", "description": "Your id for the fact, unique in this stage: F1, F2, ..."},
                            "source": {"type": "string", "description": "pack:<section id> (an id from the list in the TASK), page:<the exact url of a page you fetched>, or query:Q<n> (the search made as [call n])."},
                            "quote": {"type": "string", "description": "Copied exactly from that source, at most 400 characters, containing the number when there is one."},
                            "entity": {"type": "string", "description": "The company, segment or market the number is about."},
                            "metric": {"type": "string", "description": "What is measured, in the source's own words where you can."},
                            "period": {"type": "string", "description": "The period, e.g. FY2025, Q2 2026, 2027-2029."},
                            "value": {"type": ["number", "null"], "description": "The number as written in the quote (12.5 for 12.5%), or null."},
                            "unit": {"type": "string", "description": "%, USD m, USD/day, x, ... (empty when there is no value)."},
                            "basis": {"type": "string", "enum": list(BASIS_VALUES), "description": "filed_gaap, company_adjusted, third_party, or n/a."},
                            "duration_years": {"type": ["number", "string", "null"], "description": "The span the fact speaks for: a contract term, a guidance horizon or a backlog, in years; \"ongoing\"; null for a one-off figure."},
                        },
                        "required": list(FACT_FIELDS),
                    },
                },
                "done": {"type": "boolean", "description": "true on the last call of the stage: your research is finished."},
                "research_summary": {"type": "string", "description": "With done=true: at most 600 words: the business as the evidence shows it, what you found, where sources conflict, and what you could not establish."},
            },
            "required": ["facts"],
        },
    },
}

STAGE1_TASK = """STAGE 1 OF 4: RESEARCH AND THE FACT LEDGER.

You are the analyst for the company in the data pack above. In this stage you do NOT value the company: no value per share, no verdict, no scenario, no probability, no
desk. You research, and you register the facts a valuation will need, each with the exact quote it rests on. A later stage, in a new session, sees only the facts you register and
your research summary; it cannot see this conversation, the pack's research or your reasoning.

1. Read the pack. Its figures are the company's filings and our systems' data; its PRIMARY SOURCES hold the company's own filings verbatim. Do not search for or fetch what the pack already holds.
2. Research what the pack does not hold with search_web and fetch_page: the company's own guidance and plans, contracts and backlog and how long they run, capacity, pricing, the competitive position, regulation, one-off items inside the reported
   figures, and the facts of the industry that decide how long today's economics last. Prefer the company's own words and primary documents; a number from a secondary source is third_party.
3. Register facts with register_facts as you find them (do not leave them all to the end). A fact is one statement with its exact quote: what the number is about (entity), what is measured (metric), the period, the value as written in the quote, its unit, the basis
   (filed_gaap, company_adjusted, third_party, n/a) and, for contracts, guidance and backlog, how many years the fact speaks for (duration_years; "ongoing"; null for a one-off).
4. The quote is copied exactly from the source you name in `source`: pack:<section id> (one of the ids listed below; filings in PRIMARY SOURCES are pack:primary-p1, pack:primary-p2, ...), page:<the exact url> of a page you fetched, or query:Q<n> for a search result ([call n]).
   Name the entity and the metric in words the source uses, close to the quote: code checks that they appear within 300 characters of it.
5. Register what disagrees as well as what agrees. Do not register an opinion as a fact; register what the source says and who says it.
6. When your research is done, call register_facts with done=true and your research_summary (at most 600 words). That ends the stage.

Pack section ids you may cite: {section_ids}."""


def stage1_task(pack_text):
    ids = ", ".join(pack_sections(pack_text)) or "(none found)"
    return STAGE1_TASK.format(section_ids=ids)


def fresh_messages(stage, inputs):
    """The message list of a new session: one user message built only from `inputs`, whose names must all be in ALLOWED_INPUTS[stage]. Stage 1 is
    built here; stages 2-4 are assembled by brief R26-A2 and refuse to start until then."""
    if stage not in ALLOWED_INPUTS:
        raise ValueError(f"unknown stage {stage!r}")
    extra = sorted(set(inputs) - ALLOWED_INPUTS[stage])
    if extra:
        raise ValueError(f"{stage} may not be handed {', '.join(extra)} (SPEC revision 26 names only {', '.join(sorted(ALLOWED_INPUTS[stage]))})")
    if stage != "stage1":
        raise NotImplementedError(f"{stage}: the session is built by brief R26-A2 on R26-C's functions")
    return [{"role": "user", "content": inputs["blind_pack"].rstrip() + "\n\n---\n\n" + inputs["task"]}]


# ---------------------------------------------------------------- stage 1: the session

MAX_TURNS = 40
NUDGE = ("You ended the turn without calling a tool. Register the facts you have found with register_facts and, when your research is done, call it with done=true and "
         "your research_summary. Do not write the memorandum or a valuation in this stage.")
LAST_TURNS = ("Two turns remain in this stage. Register any fact you have not registered yet, and end with register_facts done=true and your research_summary.")


def _turn_options(base_opts, msgs_sent, cpt, ctx, num_predict):
    est = int(len(json.dumps(msgs_sent)) / (cpt if cpt is not None else 3.0))
    np_req = base_opts.get("num_predict", num_predict)
    eff_np = max(1024, min(np_req, ctx - est - 2048))
    return dict(base_opts, num_predict=eff_np), est, eff_np


def _result_text(result):
    return "\n".join(f"{r.get('title', '')} | {r.get('url', '')} | {r.get('snippet', '')}" for r in (result.get("results") or []) if isinstance(r, dict))


def run_stage1(model, pack, run_dir, think="high", ctx=98304, num_predict=49152, seed=None, timeout=14400, verbose=True, draft_num_predict=None,
               temperature=None, query_cache=None, url_cache=None, max_search_calls=25, max_turns=MAX_TURNS, num_batch=None, ticker=None, company=None):
    """Run the stage-1 session on `pack` (the blind pack; a trailing valuation TASK is cut off) and write <run_dir>/dossier.json. Returns the dossier.
    Also written: _research_snapshot.json (the tool calls, in the format of chat_with_tools), evidence_query_cache.json, evidence_url_cache.json and the
    turn log under turns/ (stage1_<n>.json, run_hashes.json). The session uses the tools search_web, fetch_page and register_facts only."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    body_pack, task_split = split_task(pack)
    task = stage1_task(body_pack)
    msgs = fresh_messages("stage1", {"blind_pack": body_pack, "task": task})
    meta_msgs = [None]
    q_cache = query_cache if query_cache is not None else {}
    u_cache = url_cache if url_cache is not None else {}
    evidence = Evidence(body_pack, u_cache)
    ledger = Ledger(evidence, company, ticker)
    primary_items = sec_primary.parse_pack(body_pack)
    opts = {"num_ctx": ctx, **({"num_batch": num_batch} if num_batch else {}), "num_predict": num_predict, "repeat_penalty": 1.05, "presence_penalty": 0.05}
    if seed is not None:
        opts["seed"] = seed
    if draft_num_predict is not None:
        opts["draft_num_predict"] = draft_num_predict
    if temperature is not None:
        opts["temperature"] = temperature
    tools_all = [REGISTER_FACTS_TOOL, *analyst_tools.research_tools()]
    snap, turns = [], []
    t0 = time.time()
    calls = search_calls = server_errors = primary_refusals = 0
    cpt = None
    nudged = False
    warned = False
    seen_result_urls = {}
    ended = None

    def write_dossier(final=False):
        d = ledger.dossier(
            ticker=ticker, pack_sha256=hashlib.sha256(pack.encode("utf-8")).hexdigest(), blind_pack_sha256=hashlib.sha256(body_pack.encode("utf-8")).hexdigest(),
            task_split=task_split, incomplete_reason=(None if ledger.done else ended or "in_progress"),
            research={"turns": len(turns), "tool_calls": calls, "search_and_fetch_calls": search_calls, "queries": {k: v[:200] for k, v in evidence.queries.items()},
                      "pages_fetched": sorted(set(evidence.fetched.values()))},
            provenance={"model": model, "seed": seed, "think": think, "ctx": ctx, "num_predict": num_predict, "temperature": temperature,
                        "provider": llm_provider.provider_name(), "elapsed_s": round(time.time() - t0)})
        (run_dir / ARTIFACTS["stage1"]).write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
        return d

    for turn in range(1, max_turns + 1):
        if turn == max_turns - 1 and not warned and max_turns > 2:
            msgs.append({"role": "user", "content": LAST_TURNS})
            meta_msgs.append(None)
            warned = True
        active = analyst_tools._compact_history(msgs, meta_msgs)
        req_opts, est, eff_np = _turn_options(opts, active, cpt, ctx, num_predict)
        tools = [t for t in tools_all if search_calls < max_search_calls or t["function"]["name"] == "register_facts"]
        body = {"model": model, "stream": False, "think": think, "messages": active, "options": req_opts, "tools": tools}
        try:
            with turn_log.logging_to(run_dir / "turns", "stage1"):
                resp = llm_provider.chat(body, timeout)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            server_errors += 1
            resp = {"message": {}, "done_reason": "server_error", "http_status": e.code,
                    **({"server_error_cause": e.cause} if getattr(e, "cause", None) else {})}
        if resp.get("prompt_eval_count"):
            cpt = len(json.dumps(active)) / resp["prompt_eval_count"]
        msg = resp.get("message") or {}
        turns.append({"turn": turn, **analyst_tools.turn_metrics(resp), "think": think, "est_prompt_tokens": est, "num_predict": eff_np})
        if server_errors >= 2:
            ended = "server_error"
            break
        tcs = msg.get("tool_calls") or []
        if not tcs:
            if nudged or turn == max_turns:
                ended = "no_tool_call" if nudged else "turn_budget"
                break
            nudged = True
            msgs.append({"role": "assistant", "content": msg.get("content") or ""})
            meta_msgs.append(None)
            msgs.append({"role": "user", "content": NUDGE})
            meta_msgs.append(None)
            continue
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        meta_msgs.append(None)
        for tc in tcs:
            calls += 1
            fn = tc.get("function") or {}
            name, args = fn.get("name"), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            rec = {"tool": name, "call_index": calls, "ts": time.strftime("%H:%M:%S"), "params": args}
            snap.append(rec)
            if name == "register_facts":
                result = ledger.register(args if isinstance(args, dict) else {})
            elif name in ("search_web", "fetch_page"):
                result = _research_call(name, args, calls, snap_rec=rec, evidence=evidence, q_cache=q_cache, u_cache=u_cache, known=seen_result_urls,
                                        primary_items=primary_items, ticker=ticker, search_calls=search_calls, max_search_calls=max_search_calls,
                                        primary_refusals=primary_refusals)
                if result.pop("_counted"):
                    search_calls += 1
                if result.pop("_primary_refusal"):
                    primary_refusals += 1
            else:
                result = {"error": f"unknown tool {name}; the tools of this stage are register_facts, search_web and fetch_page"}
            if isinstance(result, dict) and name != "register_facts":
                rec.update({k: v for k, v in result.items() if not k.startswith("_audit")})
            elif isinstance(result, dict):
                rec["result"] = result
            content, _cut = analyst_tools.tool_message(name, args, result)
            msgs.append({"role": "tool", "content": content})
            meta_msgs.append({"name": name, "args": args, "result": result, "call_index": calls})
            if verbose:
                q = (args or {}).get("query") or (args or {}).get("url") or (f"{len((args or {}).get('facts') or [])} fact(s)" if name == "register_facts" else "")
                print(f"    [stage1 tool {calls}] {name}: {str(q)[:88]}", flush=True)
        analyst_tools._write_snapshot(run_dir, model, seed, calls, False, turns, t0, snap)
        write_dossier()
        if ledger.done:
            break
    else:
        ended = "turn_budget"
    if not ledger.done and ended is None:
        ended = "turn_budget"
    analyst_tools._write_snapshot(run_dir, model, seed, calls, False, turns, t0, snap)
    analyst_tools._write_own_evidence_caches(run_dir, q_cache if query_cache is None else None, u_cache if url_cache is None else None)
    dossier = write_dossier(final=True)
    if verbose:
        print(f"    [stage1] {'done' if ledger.done else 'INCOMPLETE (' + str(ended) + ')'}: {dossier['counts']['facts']} fact(s), {dossier['counts']['usable']} usable", flush=True)
    return dossier


def _research_call(name, args, call_index, snap_rec, evidence, q_cache, u_cache, known, primary_items, ticker, search_calls, max_search_calls, primary_refusals):
    """search_web / fetch_page for the stage-1 session. Adds `_counted` (it used a research call) and `_primary_refusal` to the result (popped by the caller)."""
    args = args if isinstance(args, dict) else {}
    pref = analyst_tools.primary_refusal(name, args, primary_items, ticker) if primary_items else None
    if pref is not None:
        result, rule = pref
        snap_rec["primary_refusal"] = rule
        over = primary_refusals + 1 > analyst_tools.PRIMARY_REFUSAL_CAP
        return {**result, "_counted": over, "_primary_refusal": True}
    if search_calls >= max_search_calls:
        return {"status": "search_quota_met", "message": f"Web search budget completed ({max_search_calls} calls). Do not search again. Register your facts with register_facts "
                f"and finish with done=true and your research_summary.", "_counted": False, "_primary_refusal": False}
    if name == "search_web":
        res = analyst_tools.dispatch_tool("search_web", args, snap=None, query_cache=q_cache, url_cache=u_cache, known_urls=known)
        if isinstance(res, dict):
            for r in (res.get("results") or []):
                if isinstance(r, dict) and r.get("url"):
                    known.setdefault(r["url"], r.get("title") or "")
            qid = f"Q{call_index}"
            evidence.queries[qid] = (args.get("query") or "") + "\n" + _result_text(res)
            res = {"query_id": qid, **res}
        return {**res, "_counted": True, "_primary_refusal": False}
    # fetch_page: part 1 from the dispatcher (which fills the url cache), then the part or the find the model asked for
    u = args.get("url") or ""
    res = analyst_tools.dispatch_tool("fetch_page", {"url": u}, snap=None, query_cache=q_cache, url_cache=u_cache, known_urls=known)
    if not isinstance(res, dict) or res.get("error") or res.get("refused"):
        return {**(res if isinstance(res, dict) else {"error": str(res)}), "_counted": True, "_primary_refusal": False}
    src = res.get("url") or u
    evidence.fetched[src] = evidence.fetched[u] = src
    rec = u_cache.get(src)
    if rec is None:
        rec = {"url": src, "chars": res.get("chars", len(res.get("text") or "")), "text": res.get("text") or ""}
        u_cache[src] = rec
    find, raw_part = args.get("find"), args.get("part")
    if find is not None:
        res = {**analyst_tools.find_in_page(rec, str(find)), **({"cache_hit": res["cache_hit"]} if "cache_hit" in res else {})}
    elif raw_part is not None:
        part, err = analyst_tools._parse_part(raw_part)
        res = {"url": src, "error": err} if err else analyst_tools.page_part(rec, part)
    return {**res, "_counted": True, "_primary_refusal": False}


# ---------------------------------------------------------------- stages 2-4 (brief R26-A2)

def run_stage2(*, run_dir, **artifacts):
    """Stage 2, the blind forecast (K = 3 samples, seeds s, s+1, s+2). Reads dossier.json; hands the session only blind_pack, dossier (usable facts and the
    summary), op_margin_bar and its TASK; writes forecasts.json (SPEC section 2). Built by brief R26-A2 on R26-C's functions."""
    fresh_messages("stage2", artifacts)
    raise NotImplementedError("stage2 is built by brief R26-A2")


def run_stage3(*, run_dir, **artifacts):
    """Stage 3, reveal and reconcile (one revision at most). Reads dossier.json and forecasts.json; writes reveal.json (SPEC section 3)."""
    fresh_messages("stage3", artifacts)
    raise NotImplementedError("stage3 is built by brief R26-A2")


def run_stage4(*, run_dir, **artifacts):
    """Stage 4, the memorandum. Reads dossier.json and the frozen final desk result; writes final.json (SPEC section 4)."""
    fresh_messages("stage4", artifacts)
    raise NotImplementedError("stage4 is built by brief R26-A2")


def run_sample(model, pack, run_dir, **kw):
    """The arm r26's counterpart of analyst_tools.chat_with_tools for consensus_valuation: returns (report, thinking, meta). Stage 1 runs and writes
    dossier.json; stages 2-4 follow in brief R26-A2 (until then the NotImplementedError of stage 2 fails the sample after the dossier is on disk)."""
    dossier = run_stage1(model, pack, run_dir, **kw)
    run_stage2(run_dir=run_dir)
    return "", "", {"r26": {"stage1": dossier["counts"]}}

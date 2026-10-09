"""checkers.py - the code checks on every Muse output (SPEC_muse_passes section 2, "Code checks on every output").

  1. QUOTES. Every quote must be found in the section it cites. The matching rule is the revision-21 `crux_check` rule, imported, not copied:
     `crux_check.normalise` (NFKC, typographic quotes and dashes made plain, zero-width characters removed, whitespace collapsed; case-sensitive)
     and a substring test on the normalised section. A quote is QUOTE_MIN..QUOTE_MAX normalised characters (a short quote matches anywhere and proves
     nothing). A section the prompt did not show cannot be cited, except that a quote already VERIFIED in pass 1 may be re-cited in a later step
     that does not show the section (P5 sees no document text; its citations are checked against the pool of pass-1 quotes).
  2. HARD EVIDENCE. A position outside P10..P90 must cite section D or Q with a quote that holds a firm commitment or a figure with a forward
     word. The rule, in code (`qualifies`):
         STRONG commitment words anywhere in the quote: contract, agreement, backlog, awarded, purchase order, take-or-pay, offtake,
                                                        remaining performance obligation, bookings;
         OR a figure AND a weak word: guidance, guided, outlook, expects, anticipates, forecast, target, plan to, will, capacity,
                                      committed, commitment.
     A figure is a number that is not a bare calendar year and is decorated (decimal point, thousands comma, currency sign, %, a magnitude or unit word)
     or has three or more digits. A general outlook sentence ("we expect demand to remain strong") holds neither and does not qualify.
  3. SCHEMA. percentile a real number in [5, 95]; width one of narrow, normal, wide; reasons a non-empty list of text; citations a non-empty list.
     Missing and unexpected inputs are failures; so are the prompt-specific fields (P1 bull/bear, P2 character, P4 risks).

SECTION D's PARTS (Addendum AD, the coordinator's ruling on Addendum AC 2). The pack labels each document of section D "[D1] ...", "[D2] ...". A citation
may name the part ("D2"); its quote must then be found inside that part's text, and it counts as section D everywhere else (shown-section rule, hard
evidence, the P2 character rule). `Evidence` is the single owner of the split (`d_subsections`), so the G5 re-check (rebuild_harness/gate2/integrity.py)
applies exactly the rule the pipeline applied. Run 1 cited D parts 281 times and the old checker refused every one.

Each check yields `Issue`s with a message the runner sends back in the one retry. Nothing here calls a model.
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parents[2]
for _p in (_HERE, _HERE / "tools" / "audit_202608"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import crux_check  # noqa: E402  (revision 21: the single owner of the quote-normalisation rule)

from .schema import EVIDENCE_SECTIONS, HARD_HI, HARD_LO, PCT_MAX, PCT_MIN, WIDTHS, muse_inputs  # noqa: E402

QUOTE_MIN, QUOTE_MAX = 12, 600
MAX_REASONS, MAX_CITATIONS = 6, 6
REASON_MAX_CHARS = 1200
SECTIONS = ("F", "Q", "D", "S")       # coordinator 2026-10-07: R (the population prior) is never evidence for a placement inside it
CHARACTERS = ("cyclical", "structural", "one_off")
NAMED_ERROR_MIN_CHARS = 20

normalise = crux_check.normalise
_D_PART = re.compile(r"^D(\d+)$")
_D_MARK = re.compile(r"(?m)^\[(D\d+)\] ")


def base_section(label) -> Optional[str]:
    """'D3' -> 'D' (a part of section D); any other label unchanged."""
    if not isinstance(label, str):
        return None
    return "D" if _D_PART.match(label) else label


def d_subsections(text: Optional[str]) -> Dict[str, str]:
    """{"D1": text, "D2": text, ...}: section D split at the pack's "[Dn] " markers (pack_v2.build_d). A label that occurs twice keeps both texts."""
    out: Dict[str, str] = {}
    if not text:
        return out
    marks = list(_D_MARK.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        part = text[m.start():end]
        out[m.group(1)] = (out[m.group(1)] + "\n" + part) if m.group(1) in out else part
    return out


@dataclass
class Issue:
    code: str                          # not_json | schema | quote | section | hard_evidence | revision ...
    message: str
    input: Optional[str] = None

    def as_dict(self):
        return {"code": self.code, "message": self.message, "input": self.input}


def issues_message(issues: Sequence[Issue]) -> str:
    """The text the retry sends back: every failed check, one line each."""
    return "\n".join(f"- {i.message}" for i in issues)


# ---- the answer as JSON --------------------------------------------------------------------------------------------------------------

def parse_json(text) -> Tuple[Optional[dict], Optional[str]]:
    """(object, None) for an answer that is one JSON object (a surrounding ``` fence is tolerated), else (None, message)."""
    s = "" if text is None else str(text).strip()
    if not s:
        return None, "the answer is empty; answer with one JSON object and nothing else"
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    if m:
        s = m.group(1)
    try:
        obj = json.loads(s)
    except ValueError as e:
        return None, f"the answer is not valid JSON ({str(e)[:120]}); answer with one JSON object and nothing else"
    if not isinstance(obj, dict):
        return None, "the answer must be one JSON object, not a list or a bare value"
    return obj, None


# ---- evidence: the text a quote is looked for in ------------------------------------------------------------------------------------

class Evidence:
    """The sections a prompt showed (raw text by section letter) and, optionally, a pool of (section, quote) pairs verified earlier."""

    def __init__(self, sections: Mapping[str, str], pool: Iterable[Tuple[str, str]] = ()):
        self.sections = dict(sections)
        self.norm = {k: normalise(v) for k, v in self.sections.items()}
        self.parts = {k: normalise(v) for k, v in d_subsections(self.sections.get("D")).items()}
        self.pool = [(base_section(s), normalise(q)) for s, q in pool]

    def shown(self, section: str) -> bool:
        """The section (or, for 'Dn', section D) was shown to the prompt or has quotes in the verified pool."""
        b = base_section(section)
        return b in self.sections or any(s == b for s, _ in self.pool)

    def find(self, section: str, quote: str) -> bool:
        q = normalise(quote)
        b = base_section(section)
        if b != section:                                    # a part of D: only that part's text, or a pooled D quote
            if section in self.parts and q in self.parts[section]:
                return True
        elif section in self.norm and q in self.norm[section]:
            return True
        return any(s == b and q in pq for s, pq in self.pool)


def check_citation(cit, ev: Evidence, where: str, input_name: Optional[str] = None) -> Optional[Issue]:
    """None when the citation passes, else the Issue."""
    if not isinstance(cit, dict) or not isinstance(cit.get("section"), str) or not isinstance(cit.get("quote"), str):
        return Issue("schema", f"{where}: a citation must be an object {{\"section\": \"F|Q|D|S\", \"quote\": \"...\"}}", input_name)
    sec, quote = cit["section"].strip(), cit["quote"]
    if base_section(sec) not in SECTIONS:
        return Issue("schema", f"{where}: section {sec!r} is not one of F, Q, D (or a part of D such as D2), S (section R, the population distributions, "
                               f"cannot be cited as evidence)", input_name)
    n = len(normalise(quote))
    if n < QUOTE_MIN or n > QUOTE_MAX:
        return Issue("quote", f"{where}: a quote must be {QUOTE_MIN} to {QUOTE_MAX} characters of contiguous text (yours has {n})", input_name)
    if not ev.shown(sec):
        return Issue("section", f"{where}: section {base_section(sec)} was not shown in this prompt, so it cannot be cited here", input_name)
    if base_section(sec) != sec and "D" in ev.sections and sec not in ev.parts:
        return Issue("section", f"{where}: section D has no part {sec} (its parts are {', '.join(ev.parts) or 'none'})", input_name)
    if not ev.find(sec, quote):
        return Issue("quote", f"{where}: the quote {quote[:80]!r} was not found verbatim in section {sec}. Quote contiguous text copied exactly "
                              f"from the section, with no ellipsis and no paraphrase", input_name)
    return None


# ---- hard evidence -----------------------------------------------------------------------------------------------------------------

_STRONG = re.compile(r"\b(contract(?:s|ed)?|agreements?|backlog|awarded|purchase orders?|take-or-pay|offtake|"
                     r"remaining performance obligations?|bookings)\b", re.I)
_WEAK = re.compile(r"\b(guidance|guided|outlook|expects?|expected|expecting|anticipates?|anticipated|forecasts?|targets?|plans? to|will|"
                   r"capacity|committed|commitments?)\b", re.I)
_NUM = re.compile(r"(?<![A-Za-z0-9])([$€£]|US\$|C\$)?\s?(\d[\d,]*(?:\.\d+)?)"
                  r"(\s?(?:%|percent\b|bps\b|basis points\b|million\b|billion\b|trillion\b|thousand\b|bn\b|mn\b|mm\b|[kKmMbB]\b|GW\b|MW\b|GWh\b|"
                  r"MWh\b|MMBtu\b|barrels?\b|tons?\b|tonnes?\b|units?\b|systems?\b|aircraft\b|vessels?\b|stores?\b|sites?\b|customers?\b))?")


def has_figure(text: str) -> bool:
    """A number that is not a bare calendar year and is decorated (decimal, comma, currency, % or a unit word) or has >= 3 digits."""
    for m in _NUM.finditer(text):
        cur, num, suf = m.group(1), m.group(2), m.group(3)
        if re.fullmatch(r"(19|20)\d\d", num) and not cur and not suf:
            continue
        if cur or suf or "." in num or "," in num or len(re.sub(r"\D", "", num)) >= 3:
            return True
    return False


def qualifies(quote: str) -> bool:
    """The hard-evidence rule for one quote (module docstring)."""
    q = normalise(quote)
    return bool(_STRONG.search(q)) or (has_figure(q) and bool(_WEAK.search(q)))


def hard_evidence(citations, ev: Evidence) -> bool:
    """True when some citation is from section D or Q, found in it (or in the verified pool for that section), and `qualifies`."""
    for c in citations if isinstance(citations, list) else []:
        if isinstance(c, dict) and base_section(c.get("section")) in EVIDENCE_SECTIONS and isinstance(c.get("quote"), str):
            if ev.find(c["section"], c["quote"]) and qualifies(c["quote"]):
                return True
    return False


def outside_hard_band(percentile: float) -> bool:
    return percentile < HARD_LO or percentile > HARD_HI


# ---- one input's entry -----------------------------------------------------------------------------------------------------------------

def is_real(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def check_entry(name: str, entry, ev: Evidence, where: Optional[str] = None) -> List[Issue]:
    """Schema, quotes and hard evidence of {"percentile", "width", "reasons", "citations"} for input `name`."""
    w = where or f"input {name}"
    if not isinstance(entry, dict):
        return [Issue("schema", f"{w}: must be an object with percentile, width, reasons and citations", name)]
    out: List[Issue] = []
    pct = entry.get("percentile")
    pct_ok = is_real(pct) and PCT_MIN <= pct <= PCT_MAX
    if not pct_ok:
        out.append(Issue("schema", f"{w}: percentile must be a number from {PCT_MIN:g} to {PCT_MAX:g} (got {pct!r})", name))
    if entry.get("width") not in WIDTHS:
        out.append(Issue("schema", f"{w}: width must be one of {', '.join(WIDTHS)} (got {entry.get('width')!r})", name))
    reasons = entry.get("reasons")
    if (not isinstance(reasons, list) or not reasons or len(reasons) > MAX_REASONS
            or any(not isinstance(r, str) or not r.strip() or len(r) > REASON_MAX_CHARS for r in reasons)):
        out.append(Issue("schema", f"{w}: reasons must be a list of 1 to {MAX_REASONS} non-empty texts", name))
    cits = entry.get("citations")
    cits_ok = True
    if not isinstance(cits, list) or not cits or len(cits) > MAX_CITATIONS:
        out.append(Issue("schema", f"{w}: citations must be a list of 1 to {MAX_CITATIONS} {{section, quote}} objects", name))
        cits_ok = False
    else:
        for k, c in enumerate(cits, 1):
            iss = check_citation(c, ev, f"{w}, citation {k}", name)
            if iss is not None:
                out.append(iss)
                cits_ok = False
    if pct_ok and outside_hard_band(float(pct)) and not (cits_ok and hard_evidence(cits, ev)):
        out.append(Issue("hard_evidence",
                         f"{w}: position P{pct:g} is outside P10..P90, so it needs at least one citation from section D or Q whose quote holds a "
                         f"firm commitment (contract, agreement, backlog, award, purchase order) or a figure together with guidance, capacity or a "
                         f"stated plan. A general outlook sentence does not qualify. Move the position inside P10..P90 or cite such a quote", name))
    return out


def entry_has_hard_evidence(entry, ev: Evidence) -> bool:
    return (isinstance(entry, dict) and is_real(entry.get("percentile")) and outside_hard_band(float(entry["percentile"]))
            and hard_evidence(entry.get("citations"), ev))


# ---- the prompts' outputs ----------------------------------------------------------------------------------------------------------

def _check_inputs_block(inputs_obj, expected: Sequence[str], ev: Evidence) -> List[Issue]:
    if not isinstance(inputs_obj, dict):
        return [Issue("schema", "the answer needs an object \"inputs\" with one entry per input")]
    out: List[Issue] = []
    for n in expected:
        if n not in inputs_obj:
            out.append(Issue("schema", f"input {n} is missing from \"inputs\"", n))
    for n in inputs_obj:
        if n not in expected:
            out.append(Issue("schema", f"unexpected input {n!r}; the inputs asked are {', '.join(expected)}"))
    for n in expected:
        if n in inputs_obj:
            out += check_entry(n, inputs_obj[n], ev)
    return out


def _check_case(obj, key: str, ev: Evidence) -> List[Issue]:
    c = obj.get(key)
    if not isinstance(c, dict) or not isinstance(c.get("text"), str) or not c["text"].strip():
        return [Issue("schema", f"{key} must be an object {{\"text\": one sentence, \"citation\": {{section, quote}}}}")]
    out: List[Issue] = []
    text = c["text"].strip()
    if len(text) > 500 or len(re.findall(r"[.!?](?:\s+[A-Z]|$)", text)) > 1:
        out.append(Issue("schema", f"{key}.text must be one sentence of at most 500 characters"))
    iss = check_citation(c.get("citation"), ev, f"{key}.citation")
    if iss is not None:
        out.append(iss)
    return out


def check_pass1(prompt: str, obj: dict, family: str, expected: Sequence[str], ev: Evidence) -> List[Issue]:
    """P1..P4: the inputs block plus the prompt's own fields."""
    out = _check_inputs_block(obj.get("inputs"), expected, ev)
    if prompt == "P1":
        out += _check_case(obj, "bull_case", ev)
        out += _check_case(obj, "bear_case", ev)
    elif prompt == "P2":
        ch = obj.get("character")
        if not isinstance(ch, dict) or ch.get("value") not in CHARACTERS:
            out.append(Issue("schema", f"character must be {{\"value\": one of {', '.join(CHARACTERS)}, \"reasons\": text, \"citations\": [...]}}"))
        else:
            if not isinstance(ch.get("reasons"), str) or not ch["reasons"].strip():
                out.append(Issue("schema", "character.reasons must be a non-empty text"))
            cc = ch.get("citations")
            if not isinstance(cc, list) or not cc:
                out.append(Issue("schema", "character.citations must be a non-empty list"))
            else:
                bad = [check_citation(c, ev, f"character, citation {k}") for k, c in enumerate(cc, 1)]
                out += [b for b in bad if b is not None]
                if not any(isinstance(c, dict) and base_section(c.get("section")) == "D" for c in cc):
                    out.append(Issue("schema", "character must cite section D (the company's own documents)"))
    elif prompt == "P4":
        risks = obj.get("risks")
        names = set(muse_inputs(family))
        if not isinstance(risks, list) or len(risks) != 3:
            out.append(Issue("schema", "risks must be a list of exactly three objects {risk, input, citation}"))
        else:
            for k, r in enumerate(risks, 1):
                if not isinstance(r, dict) or not isinstance(r.get("risk"), str) or not r["risk"].strip():
                    out.append(Issue("schema", f"risk {k} must be an object {{\"risk\": text, \"input\": name, \"citation\": {{section, quote}}}}"))
                    continue
                if r.get("input") not in names:
                    out.append(Issue("schema", f"risk {k}: input must be one of {', '.join(sorted(names))}"))
                iss = check_citation(r.get("citation"), ev, f"risk {k}.citation")
                if iss is not None:
                    out.append(iss)
    return out


def check_synthesis(obj: dict, expected: Sequence[str], ev: Evidence) -> List[Issue]:
    """P5: the final position per input, the coherence note and the list of changes (the changes' reasons are required; which inputs changed is
    verified by the caller against the pass-1 positions)."""
    out = _check_inputs_block(obj.get("inputs"), expected, ev)
    if not isinstance(obj.get("coherence"), str) or not obj["coherence"].strip():
        out.append(Issue("schema", "coherence must be a non-empty text stating the coherence check (combinations of extreme positions and the evidence)"))
    ch = obj.get("changes")
    if not isinstance(ch, list):
        out.append(Issue("schema", "changes must be a list (empty when nothing changed) of {input, reason}"))
    else:
        for k, c in enumerate(ch, 1):
            if not isinstance(c, dict) or c.get("input") not in expected or not isinstance(c.get("reason"), str) or not c["reason"].strip():
                out.append(Issue("schema", f"change {k} must be {{\"input\": one of {', '.join(expected)}, \"reason\": text}}"))
    return out


def changed_inputs(final: Mapping[str, Mapping], before: Mapping[str, Mapping], eps: float = 1e-9) -> List[str]:
    """Inputs whose (percentile, width) differ between two position maps."""
    out = []
    for n, f in final.items():
        b = before.get(n)
        if b is None or abs(float(f["percentile"]) - float(b["percentile"])) > eps or f["width"] != b["width"]:
            out.append(n)
    return out

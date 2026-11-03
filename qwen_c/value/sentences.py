"""sentences.py - the evidence IDs of the valuation prompt (F_SPEC_valuation_menu §1).

A prose item (a filing section, a going-concern note, an amendment, an 8-K release or exhibit) is split into sentences numbered
<fact_id>.s<n>, and the prompt prints each sentence after its ASCII marker [[P4.s17]]. A line holding a table row (cells joined by
" | ") is one sentence. Otherwise a sentence ends at ".", "?" or "!" (with any closing quote or bracket) followed by white space and a
capital, a digit, an opening quote or bracket, or "$"; so never inside a number, and never after a common abbreviation, a single letter
or a dotted token ("U.S.", "No.", "Inc.", "p.m."). Statements, the screener row, the code-built [Y] record items and [V0] are cited by
item ID and carry no markers. Each ID carries its item's kind, period and form; checks maps the period to a fiscal year.
"""
import re

SENTENCES_VERSION = "m3q.sentences.v1"
PROSE_KINDS = ("annual_section", "quarterly_section", "gc_note", "amendment", "release", "other_8k", "news")
ABBREV = {"inc", "corp", "co", "ltd", "llc", "no", "nos", "mr", "mrs", "ms", "dr", "st", "vs", "approx", "fig", "jan", "feb", "mar",
          "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
_END = re.compile(r"[.?!][\"'”’)\]]*\s+(?=[A-Z0-9\"'“‘(\[$])")


def _ends_abbreviation(text):
    """True when the token before a sentence-ending mark is an abbreviation, a single letter or a dotted token."""
    tok = text.rstrip("\"'”’)]").rsplit(None, 1)[-1] if text.strip() else ""
    tok = tok.lstrip("(\"'“‘[")
    if not tok.endswith((".", "?", "!")):
        return False
    word = tok[:-1]
    dotted = "." in word and not any(c.isdigit() for c in word)            # U.S., p.m.; never a figure such as $6.50
    return dotted or (len(word) == 1 and word.isalpha()) or word.lower() in ABBREV


def split_line(line):
    """The sentences of one line, in order, each with its own text exactly as printed (the white space between them dropped). A line
    with no letter or digit (a blank, a zero-width space) holds none."""
    if not any(c.isalnum() for c in line):
        return []
    if " | " in line:
        return [line.strip()]
    out, start = [], 0
    for m in _END.finditer(line):
        head = line[start:m.end()].rstrip()
        if _ends_abbreviation(head):
            continue
        out.append(head.strip())
        start = m.end()
    tail = line[start:].strip()
    return out + ([tail] if tail else [])


def split(text):
    """[[sentence of line 1], [sentences of line 2], ...]: one list per line, empty for a blank line."""
    return [split_line(line) for line in (text or "").split("\n")]


def marked(item):
    """The item's text with a marker before each sentence; numbering runs over the whole item. A line with no sentence is printed as is."""
    lines, n = [], 0
    for line, sents in zip((item.get("text") or "").split("\n"), split(item.get("text"))):
        parts = []
        for s in sents:
            n += 1
            parts.append(f"[[{item['fact_id']}.s{n}]] {s}")
        lines.append(" ".join(parts) if parts else line)
    return "\n".join(lines)


def marked_packet(packet):
    """A copy of the packet whose prose items print their sentence markers."""
    return dict(packet, evidence=[dict(e, text=marked(e)) if e.get("kind") in PROSE_KINDS else e for e in packet.get("evidence") or []])


def index(evidence):
    """{id: {"fact_id", "kind", "period", "form", "text", "sentence"}}: a prose item's sentences by sentence ID (the item's own ID is not
    citable), every other item by its item ID."""
    out = {}
    for e in evidence:
        meta = {"fact_id": e["fact_id"], "kind": e.get("kind"), "period": e.get("period"), "form": e.get("form")}
        if e.get("kind") not in PROSE_KINDS:
            out[e["fact_id"]] = dict(meta, text=e.get("text") or "", sentence=False)
            continue
        n = 0
        for s in (s for sents in split(e.get("text")) for s in sents):
            n += 1
            out[f"{e['fact_id']}.s{n}"] = dict(meta, text=s, sentence=True)
    return out

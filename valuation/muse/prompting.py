"""prompting.py - the versioned prompt templates (prompts/P1.txt .. P6.txt, system.txt, inputs.json) and how a pack is rendered into them.

A template is a text file; its sha256 is recorded with every run (`prompt_hashes`), together with the hash of the whole prompt set, so a run says
exactly which wording it used. Changing what the model is told is a versioned decision (workspace non-negotiable 7): a changed template is a NEW
version, never an edit in place. The placeholders ({{HEADER}}, {{SECTIONS}}, ...) are filled here; the first line of a template ("# template P1,
version 1: ...") is a comment for people and is not sent.

Pass-1 templates (P1-P4) and P5 never receive a price, a market cap or any value: `render_pass1` and `render_p5` take no argument that could carry one.
Only `render_p6` takes price information.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from .jsonschemas import pass1_schema, redteam_schema, synthesis_schema
from .pack_v2 import Pack, input_texts, pct
from .schema import SECTION_TITLES, muse_inputs, prompt_inputs

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
CRLF, LF = bytes([13, 10]), bytes([10])
SECTION_ORDER = ("F", "Q", "D", "S", "R")


def prompt_files() -> List[Path]:
    return sorted(p for p in PROMPT_DIR.iterdir() if p.is_file() and p.suffix in (".txt", ".json"))


def file_sha256(path) -> str:
    """sha256 of the file with CRLF read as LF, so a checkout with git's autocrlf hashes the same as one without."""
    return hashlib.sha256(Path(path).read_bytes().replace(CRLF, LF)).hexdigest()


def prompt_hashes() -> dict:
    """{file name: sha256 of its bytes, ..., "prompt_set": sha256 over the sorted name:hash lines}."""
    out = {p.name: file_sha256(p) for p in prompt_files()}
    out["prompt_set"] = hashlib.sha256("\n".join(f"{k}:{v}" for k, v in sorted(out.items())).encode("utf-8")).hexdigest()
    return out


def read_template(name: str) -> str:
    text = (PROMPT_DIR / f"{name}.txt").read_bytes().decode("utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[0].startswith("# template"):
        lines = lines[1:]
    return "\n".join(lines).strip("\n")


def system_text() -> str:
    return (PROMPT_DIR / "system.txt").read_bytes().decode("utf-8").replace("\r\n", "\n").strip("\n")


@dataclass
class Rendered:
    name: str
    user: str
    sections: Dict[str, str]                 # the section texts the prompt shows, by letter (what quotes are checked against)
    template_sha256: str
    inputs: List[str] = field(default_factory=list)
    schema: Optional[dict] = None            # the JSON schema sent with the call (jsonschemas.py): the answer's exact shape


def render_sections(sections: Mapping[str, str]) -> str:
    parts = []
    for s in SECTION_ORDER:
        if s in sections:
            parts.append(f"=== SECTION {s}: {SECTION_TITLES[s]} ===\n{sections[s]}")
    return "\n\n".join(parts)


def _fill(template: str, values: Mapping[str, str]) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        raise ValueError(f"unfilled placeholders: {sorted(set(left))}")
    return out


def _round_blocks(text: str, round_no: int) -> str:
    for n in (1, 2):
        pat = re.compile(r"\[\[IF_ROUND%d\]\]\n(.*?)\[\[/IF_ROUND%d\]\]\n?" % (n, n), re.S)
        text = pat.sub(lambda m: m.group(1) if n == round_no else "", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _inputs_block(names: Sequence[str]) -> str:
    t = input_texts()
    return "\n".join(f"- {n} ({t[n]['label']}): {t[n]['question']}" for n in names)


def _entry_skeleton() -> str:
    return ('{"percentile": <5 to 95>, "width": "<narrow|normal|wide>", "reasons": ["..."], '
            '"citations": [{"section": "<F|Q|D|S|R>", "quote": "<exact text>"}]}')


def _example(prompt: str, names: Sequence[str], family: str) -> str:
    inputs = "{" + ", ".join(f'"{n}": {_entry_skeleton()}' for n in names) + "}"
    cit = '{"section": "<F|Q|D|S|R>", "quote": "<exact text>"}'
    if prompt == "P1":
        return ('{"inputs": ' + inputs + ', "bull_case": {"text": "<one sentence>", "citation": ' + cit + '}, '
                '"bear_case": {"text": "<one sentence>", "citation": ' + cit + '}}')
    if prompt == "P2":
        return ('{"inputs": ' + inputs + ', "character": {"value": "<cyclical|structural|one_off>", "reasons": "<text>", "citations": [' + cit + ']}}')
    if prompt == "P4":
        r = '{"risk": "<one sentence>", "input": "<input name>", "citation": ' + cit + '}'
        return '{"inputs": ' + inputs + ', "risks": [' + ", ".join([r] * 3) + ']}'
    if prompt == "P5":
        return ('{"inputs": ' + inputs + ', "changes": [{"input": "<input name>", "reason": "<text>"}], "coherence": "<text>"}')
    if prompt == "P6":
        e = ('{"market_case": "<text>", "decision": "<keep|revise>", "percentile": <5 to 95, revise only>, "width": "<narrow|normal|wide, revise only>", '
             '"reasons": ["<revise only>"], "citations": [<revise only>], "new_quote": <{"section", "quote"} or null>, '
             '"named_error": <{"reason_index": n, "why_wrong": "<text>"} or null>}')
        return '{"inputs": {' + ", ".join(f'"{n}": {e}' for n in names) + '}}'
    return '{"inputs": ' + inputs + '}'


def render_pass1(prompt: str, pack: Pack, family: str) -> Optional[Rendered]:
    """P1..P4 for `family`; None when the prompt has no input to place (P3 for the financial family) or the priors supply none of its inputs."""
    names = [n for n in prompt_inputs(family, prompt) if n in pack.r]
    if not names:
        return None
    sections = pack.sections_for(prompt, names)
    tpl = read_template(prompt)
    user = _fill(tpl, {"HEADER": pack.header, "INPUTS": _inputs_block(names), "SECTIONS": render_sections(sections),
                      "EXAMPLE": _example(prompt, names, family), "ALL_INPUT_NAMES": ", ".join(muse_inputs(family))})
    return Rendered(prompt, user, sections, file_sha256(PROMPT_DIR / f"{prompt}.txt"), names, pass1_schema(prompt, names, family))


# ---- P5 -----------------------------------------------------------------------------------------------------------------------------

def format_entry(name: str, entry: Optional[Mapping], note: str = "") -> str:
    if entry is None:
        return f"{name}: no usable placement ({note or 'the checks failed twice'}); the prior's median stands for now."
    lines = [f"{name}: position P{float(entry['percentile']):g}, width {entry['width']}"]
    for k, r in enumerate(entry.get("reasons") or [], 1):
        lines.append(f"  reason {k}: {r}")
    for c in entry.get("citations") or []:
        lines.append(f"  cited [{c['section']}]: \"{c['quote']}\"")
    return "\n".join(lines)


def format_pass1(prompt: str, family: str, obj: Optional[Mapping], entries: Mapping[str, Optional[Mapping]]) -> str:
    """One earlier analysis as shown to P5 (and the red team): each input's placement, reasons and verified quotes, plus the prompt's own fields."""
    parts = [f"-- {prompt} --"]
    for n, e in entries.items():
        parts.append(format_entry(n, e))
    obj = obj or {}
    for key in ("bull_case", "bear_case"):
        c = obj.get(key)
        if isinstance(c, dict):
            cit = c.get("citation") or {}
            parts.append(f"{key}: {c.get('text')} [{cit.get('section')}: \"{cit.get('quote')}\"]")
    ch = obj.get("character")
    if isinstance(ch, dict):
        parts.append(f"character of today's level: {ch.get('value')} - {ch.get('reasons')}")
        for c in ch.get("citations") or []:
            parts.append(f"  cited [{c.get('section')}]: \"{c.get('quote')}\"")
    for k, r in enumerate(obj.get("risks") or [], 1):
        if isinstance(r, dict):
            cit = r.get("citation") or {}
            parts.append(f"risk {k} (moves {r.get('input')}): {r.get('risk')} [{cit.get('section')}: \"{cit.get('quote')}\"]")
    return "\n".join(parts)


def render_p5(pack: Pack, family: str, inputs: Sequence[str], pass1_blocks: Sequence[str]) -> Rendered:
    sections = pack.sections_for("P5", inputs)
    user = _fill(read_template("P5"), {"HEADER": pack.header, "PASS1_RESULTS": "\n\n".join(pass1_blocks), "INPUT_NAMES": ", ".join(inputs),
                                       "SECTIONS": render_sections(sections), "EXAMPLE": _example("P5", inputs, family)})
    return Rendered("P5", user, sections, file_sha256(PROMPT_DIR / "P5.txt"), list(inputs), synthesis_schema(list(inputs)))


# ---- P6 -----------------------------------------------------------------------------------------------------------------------------

def price_block(price_info: Mapping) -> str:
    ccy = price_info.get("currency") or ""
    lines = [f"Market price per share: {price_info['price']:,.2f} {ccy}".rstrip()]
    if price_info.get("market_cap") is not None:
        lines.append(f"Market capitalisation: {price_info['market_cap']:,.0f} {ccy}".rstrip())
    return "\n".join(lines)


def review_block(review: Sequence[Mapping]) -> str:
    """Per input: the pass-1 position with its numbered reasons and quotes, and what the price requires (a percentile of the population prior, its
    value, or 'not reachable within P1..P99'; EXTRAORDINARY when outside P5..P95)."""
    parts = []
    for r in review:
        lines = [format_entry(r["name"], r["entry"])]
        req = r["required"]
        if req.get("status") == "ok":
            lines.append(f"  the price requires: {pct(req['required_value'])} for {r['name']}, which is P{req['required_percentile']:.0f} of the population"
                         + ("  [EXTRAORDINARY: outside P5..P95]" if req.get("extraordinary") else "")
                         + " (all other inputs at your earlier medians)")
        elif req.get("status") == "not_reachable":
            lines.append(f"  the price requires: not reachable within P1..P99 of the population ({req.get('direction')})  [EXTRAORDINARY]")
        else:
            lines.append(f"  the price requires: not available ({req.get('reason')})")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def section_index(pack: Pack, shown: Sequence[str]) -> str:
    lines = []
    for s in SECTION_ORDER:
        if s == "R":
            continue
        text = pack.sections.get(s)
        if text is None:
            continue
        lines.append(f"Section {s} ({SECTION_TITLES[s]}, {len(text):,} characters): " + ("shown below" if s in shown else "provided on request"))
    return "\n".join(lines)


def render_p6(pack: Pack, family: str, inputs: Sequence[str], price_info: Mapping, review: Sequence[Mapping], *, round_no: int = 1,
              extra_sections: Sequence[str] = ()) -> Rendered:
    sections = pack.sections_for("P6", inputs)
    for s in extra_sections:
        if s in ("F", "Q", "D") and s in pack.sections:
            sections[s] = pack.sections[s]
    tpl = _round_blocks(read_template("P6"), round_no)
    user = _fill(tpl, {"HEADER": pack.header, "PRICE_BLOCK": price_block(price_info), "INPUT_REVIEW": review_block(review),
                      "SECTION_INDEX": section_index(pack, list(sections)), "SECTIONS": render_sections(sections),
                      "EXAMPLE": _example("P6", inputs, family)})
    return Rendered("P6", user, sections, file_sha256(PROMPT_DIR / "P6.txt"), list(inputs), redteam_schema(list(inputs), round_no))

"""jsonschemas.py - the JSON schema sent with every Muse call (Addendum AC 1: schema-constrained decoding).

WHY. A behaviour check of the first 38 companies of gate 2 found the answers failing on form, not on judgment: invalid JSON (an extra closing brace after "bull_case" and "bear_case"
had been written INSIDE the "inputs" object), the per-prompt extras nested among the inputs, and section labels the checker did not know. llama-server compiles a JSON schema to a
grammar and samples only tokens the grammar allows, so every answer is one syntactically valid object of the shape the checker reads.

THE SHAPE IS THE CHECKER'S SHAPE (checkers.py, redteam.py), nothing new: a top-level object with "inputs" (one entry per input asked, each exactly {percentile, width, reasons,
citations}) and, OUTSIDE "inputs", the prompt's own fields:
  P1  bull_case, bear_case {text, citation}              P2  character {value, reasons, citations}      P3  nothing      P4  risks [3 x {risk, input, citation}]
  P5  changes [{input, reason}], coherence                P6  per input {market_case, decision, [percentile, width, reasons, citations], new_quote, named_error}; round 1 may instead
      answer {"request_sections": [...]}.
A citation's "section" is F, Q, S, D or a document label D1..D99 (checkers.py, Addendum AC 2); R is not allowed (it is never evidence).

WHAT IS NOT IN THE SCHEMA, on purpose. Numeric ranges (llama.cpp enforces minimum/maximum for integers only), string length bounds (a {12,600} repetition would make the grammar
large for no gain) and everything that needs the filing text (the quote is found, the hard-evidence rule): the code checks and the one retry still decide those. The schema removes
the form failures; it does not decide whether an answer is acceptable.

The schema travels as `response_format` (runner.py): {"type": "json_schema", "json_schema": {"name", "strict": true, "schema": S}} on the build's OpenAI-compatible endpoint, with
{"type": "json_object", "schema": S} as the alternative spelling of the same constraint.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .schema import WIDTHS, muse_inputs

CHARACTERS = ("cyclical", "structural", "one_off")
MAX_REASONS, MAX_CITATIONS = 6, 6
SECTION_PATTERN = "^(F|Q|S|D|D[1-9][0-9]?)$"


def _obj(props: Dict[str, dict], required: Optional[Sequence[str]] = None) -> dict:
    return {"type": "object", "properties": props, "required": list(props) if required is None else list(required), "additionalProperties": False}


def _arr(items: dict, lo: int, hi: Optional[int] = None) -> dict:
    out = {"type": "array", "items": items, "minItems": lo}
    if hi is not None:
        out["maxItems"] = hi
    return out


STRING = {"type": "string"}
CITATION = _obj({"section": {"type": "string", "pattern": SECTION_PATTERN}, "quote": STRING})
CITATIONS = _arr(CITATION, 1, MAX_CITATIONS)
REASONS = _arr(STRING, 1, MAX_REASONS)
WIDTH = {"type": "string", "enum": list(WIDTHS)}
PERCENTILE = {"type": "number"}


def entry_schema() -> dict:
    return _obj({"percentile": PERCENTILE, "width": WIDTH, "reasons": REASONS, "citations": CITATIONS})


def _inputs(names: Sequence[str], entry: dict) -> dict:
    return _obj({n: entry for n in names})


def _case() -> dict:
    return _obj({"text": STRING, "citation": CITATION})


def pass1_schema(prompt: str, names: Sequence[str], family: str) -> dict:
    """P1..P4: {"inputs": {name: entry}} plus the prompt's own fields beside it."""
    props: Dict[str, dict] = {"inputs": _inputs(names, entry_schema())}
    if prompt == "P1":
        props["bull_case"], props["bear_case"] = _case(), _case()
    elif prompt == "P2":
        props["character"] = _obj({"value": {"type": "string", "enum": list(CHARACTERS)}, "reasons": STRING, "citations": _arr(CITATION, 1, MAX_CITATIONS)})
    elif prompt == "P4":
        risk = _obj({"risk": STRING, "input": {"type": "string", "enum": list(muse_inputs(family))}, "citation": CITATION})
        props["risks"] = _arr(risk, 3, 3)
    elif prompt != "P3":
        raise ValueError(f"no schema for prompt {prompt!r}")
    return _obj(props)


def synthesis_schema(names: Sequence[str]) -> dict:
    """P5: the final entry per input, the list of changes and the coherence note."""
    change = _obj({"input": {"type": "string", "enum": list(names)}, "reason": STRING})
    return _obj({"inputs": _inputs(names, entry_schema()), "changes": {"type": "array", "items": change}, "coherence": STRING})


def redteam_schema(names: Sequence[str], round_no: int = 1) -> dict:
    """P6: per input the market case and the decision; a revision adds the entry fields; new_quote / named_error are null or an object."""
    nullable = lambda s: {"anyOf": [s, {"type": "null"}]}       # noqa: E731
    named_error = _obj({"reason_index": {"type": "integer"}, "why_wrong": STRING})
    e = _obj({"market_case": STRING, "decision": {"type": "string", "enum": ["keep", "revise"]}, "percentile": PERCENTILE, "width": WIDTH, "reasons": REASONS,
              "citations": CITATIONS, "new_quote": nullable(CITATION), "named_error": nullable(named_error)}, required=["market_case", "decision"])
    answer = _obj({"inputs": _inputs(names, e)})
    if round_no != 1:
        return answer
    request = _obj({"request_sections": _arr({"type": "string", "enum": ["F", "Q", "D"]}, 1, 3)})
    return {"anyOf": [answer, request]}


def response_format(schema: dict, style: str = "json_schema", name: str = "muse_answer") -> dict:
    """The `response_format` field of the chat request. style "json_schema": the OpenAI spelling; "json_object": llama.cpp's own spelling of the same constraint."""
    if style == "json_schema":
        return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
    if style == "json_object":
        return {"type": "json_object", "schema": schema}
    raise ValueError(f"unknown response_format style {style!r}")

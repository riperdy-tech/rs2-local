"""jsonschemas.py - the JSON schema each Muse call is constrained to (SPEC_rebuild Addendum AC 1; Addendum AD R4).

WHY. In gate-2 run 1 the model's long answers broke on structure, not on content: 150 of 171 failed parses were complete JSON missing one closing brace,
because the model nested the prompt's extra fields (bull_case, bear_case, character) inside "inputs". llama-server's `response_format` with a JSON schema
constrains decoding to the shape below, so the answer is always syntactically valid and the extra fields cannot be nested.

ONE OWNER OF THE RULES. Every number and name here is imported from the checker (checkers.py), the schema module (schema.py) and the red-team module
(redteam.py), so the grammar and the checks cannot drift apart. The checker remains the authority: it re-checks every answer (quotes verbatim, the
hard-evidence rule, the revision rule), and a grammar keyword the server does not enforce changes nothing about what is accepted.

Free texts that the checker leaves unbounded (coherence, character.reasons, a change's reason) are capped at FREE_TEXT_MAX characters so a constrained
answer cannot run on until the token limit; the checker's own bounds (quotes, reasons, case text) are used where they exist.

The citation section enum lists exactly the sections a prompt may cite: the non-R sections it shows (R, the population priors, is never evidence) and,
when section D is shown, its parts D1..Dn as the pack labels them. P5 and P6 show no filing text of their own, so they may cite any filing section of the
pack (their quotes are checked against the pool of quotes verified in pass 1, or against sections P6 requested).
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from .checkers import (CHARACTERS, MAX_CITATIONS, MAX_REASONS, NAMED_ERROR_MIN_CHARS, QUOTE_MAX, QUOTE_MIN, REASON_MAX_CHARS, SECTIONS,
                       d_subsections)
from .redteam import MARKET_CASE_MIN
from .schema import PCT_MAX, PCT_MIN, WIDTHS, muse_inputs

CASE_MAX = 500                 # checkers._check_case: one sentence of at most 500 characters
FREE_TEXT_MAX = 2000
REQUESTABLE = ("F", "Q", "D")  # pipeline.v6: P6 round 1 may ask for these sections


def citation_labels(sections: Mapping[str, str], d_text: Optional[str] = None) -> List[str]:
    """The section labels a prompt may cite: the shown sections among F, Q, D, S, plus D1..Dn when D is shown (or `d_text` is given)."""
    out = [s for s in SECTIONS if s in sections]
    d = sections.get("D") if d_text is None else d_text
    if d is not None and "D" in out:
        out += list(d_subsections(d))
    return out


def pack_labels(pack_sections: Mapping[str, str]) -> List[str]:
    """Every filing section of the pack (for P5 and P6, which cite quotes verified earlier or sections they requested)."""
    return citation_labels(pack_sections)


def _citation(labels: Sequence[str]) -> dict:
    return {"type": "object", "properties": {"section": {"type": "string", "enum": list(labels)},
                                             "quote": {"type": "string", "minLength": QUOTE_MIN, "maxLength": QUOTE_MAX}},
            "required": ["section", "quote"], "additionalProperties": False}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _entry_props(labels: Sequence[str]) -> Dict[str, dict]:
    return {"percentile": {"type": "number", "minimum": PCT_MIN, "maximum": PCT_MAX},
            "width": {"type": "string", "enum": list(WIDTHS)},
            "reasons": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": REASON_MAX_CHARS}, "minItems": 1, "maxItems": MAX_REASONS},
            "citations": {"type": "array", "items": _citation(labels), "minItems": 1, "maxItems": MAX_CITATIONS}}


def _entry(labels: Sequence[str]) -> dict:
    return {"type": "object", "properties": _entry_props(labels), "required": ["percentile", "width", "reasons", "citations"], "additionalProperties": False}


def _inputs(names: Sequence[str], entry: dict) -> dict:
    return {"type": "object", "properties": {n: entry for n in names}, "required": list(names), "additionalProperties": False}


def _case(labels: Sequence[str]) -> dict:
    return {"type": "object", "properties": {"text": {"type": "string", "minLength": 1, "maxLength": CASE_MAX}, "citation": _citation(labels)},
            "required": ["text", "citation"], "additionalProperties": False}


def _object(props: Dict[str, dict]) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def pass1_schema(prompt: str, names: Sequence[str], family: str, labels: Sequence[str]) -> dict:
    """P1..P4: the inputs block plus the prompt's own fields, each at the top level (never inside "inputs")."""
    props: Dict[str, dict] = {"inputs": _inputs(names, _entry(labels))}
    if prompt == "P1":
        props["bull_case"] = _case(labels)
        props["bear_case"] = _case(labels)
    elif prompt == "P2":
        props["character"] = _object({"value": {"type": "string", "enum": list(CHARACTERS)},
                                      "reasons": {"type": "string", "minLength": 1, "maxLength": FREE_TEXT_MAX},
                                      "citations": {"type": "array", "items": _citation(labels), "minItems": 1, "maxItems": MAX_CITATIONS}})
    elif prompt == "P4":
        risk = _object({"risk": {"type": "string", "minLength": 1, "maxLength": CASE_MAX}, "input": {"type": "string", "enum": muse_inputs(family)},
                        "citation": _citation(labels)})
        props["risks"] = {"type": "array", "items": risk, "minItems": 3, "maxItems": 3}
    return _object(props)


def synthesis_schema(names: Sequence[str], labels: Sequence[str]) -> dict:
    """P5: the final position per input, the list of changes and the coherence note."""
    change = _object({"input": {"type": "string", "enum": list(names)}, "reason": {"type": "string", "minLength": 1, "maxLength": FREE_TEXT_MAX}})
    return _object({"inputs": _inputs(names, _entry(labels)),
                    "changes": {"type": "array", "items": change, "maxItems": len(names)},
                    "coherence": {"type": "string", "minLength": 1, "maxLength": FREE_TEXT_MAX}})


def redteam_schema(names: Sequence[str], labels: Sequence[str], round_no: int = 1, requestable: Sequence[str] = REQUESTABLE) -> dict:
    """P6: per input either a kept position or a revision (redteam.validate_p6); in round 1 the alternative answer {"request_sections": [...]}."""
    named_error = _object({"reason_index": {"type": "integer", "minimum": 1}, "why_wrong": {"type": "string", "minLength": NAMED_ERROR_MIN_CHARS,
                                                                                                    "maxLength": FREE_TEXT_MAX}})
    common = {"market_case": {"type": "string", "minLength": MARKET_CASE_MIN, "maxLength": FREE_TEXT_MAX},
              "new_quote": _nullable(_citation(labels)), "named_error": _nullable(named_error)}
    keep = _object({"market_case": common["market_case"], "decision": {"type": "string", "enum": ["keep"]},
                    "new_quote": common["new_quote"], "named_error": common["named_error"]})
    revise = _object({"market_case": common["market_case"], "decision": {"type": "string", "enum": ["revise"]}, **_entry_props(labels),
                      "new_quote": common["new_quote"], "named_error": common["named_error"]})
    answer = _object({"inputs": _inputs(names, {"anyOf": [keep, revise]})})
    if round_no == 1 and requestable:
        request = _object({"request_sections": {"type": "array", "items": {"type": "string", "enum": list(requestable)}, "minItems": 1,
                                                "maxItems": len(requestable)}})
        return {"anyOf": [answer, request]}
    return answer


def response_format(schema: dict, name: str) -> dict:
    """The llama-server / OpenAI request field that constrains decoding to `schema`."""
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}

#!/usr/bin/env python3
"""
valuation_io.py — extract the structured assumption JSON the LLM emits in the
S3 (valuation_inputs) and S4 (scenario_probs) stages, tolerant of the messy
output a small model produces. Stdlib only.

Strategy:
  1. Prefer a ```json ... ``` fenced block.
  2. Else scan for a balanced {...} object that contains an expected key.
  3. json.loads; on failure, light repairs (trailing commas, single quotes).
Returns the parsed dict or None (caller then triggers a repair re-prompt).
"""
import json
import re


def _balanced_objects(text):
    """Yield every top-level {...} substring (brace-balanced, string-aware)."""
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start:i + 1]
                    start = None


def _try_load(s):
    for candidate in (s, _repair(s)):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _repair(s):
    s = re.sub(r",\s*([}\]])", r"\1", s)          # trailing commas
    s = re.sub(r"//[^\n]*", "", s)                  # // comments
    s = re.sub(r"(?<![\\])'", '"', s)               # naive single→double quotes
    return s


def extract_json(text, require_key=None):
    """Return the first parseable JSON object (optionally containing require_key)."""
    if not text:
        return None
    # 1) fenced ```json blocks first
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE):
        obj = _try_load(m.group(1))
        if obj is not None and (require_key is None or require_key in obj):
            return obj
    # 2) any balanced object, largest first (more likely the full payload)
    cands = sorted(_balanced_objects(text), key=len, reverse=True)
    for c in cands:
        obj = _try_load(c)
        if obj is not None and (require_key is None or require_key in obj):
            return obj
    return None


# ── schema validation (loose — clamp/sanity is in valuation_engine) ────────
def valid_valuation_inputs(d):
    if not isinstance(d, dict):
        return False
    if "engine" not in d or "scenarios" not in d:
        return False
    sc = d["scenarios"]
    return isinstance(sc, dict) and any(k in sc for k in ("bear", "base", "bull"))


def valid_scenario_probs(d):
    if not isinstance(d, dict):
        return False
    keys = [k for k in ("bear", "base", "bull") if k in d]
    return len(keys) >= 2 and all(isinstance(d[k], (int, float)) for k in keys)


if __name__ == "__main__":
    sample = (
        'Here are my assumptions.\n```json\n'
        '{"engine":1,"base_cf":9.6e10,"net_cash":7.2e10,"shares":2.42e10,'
        '"scenarios":{"bear":{"growth":0.15,"wacc":0.095,"terminal_growth":0.025},'
        '"base":{"growth":0.28,"wacc":0.085,"terminal_growth":0.03,},'   # repaired trailing comma
        '"bull":{"growth":0.40,"wacc":0.08,"terminal_growth":0.035}}}\n```\nDone.'
    )
    d = extract_json(sample, "engine")
    assert valid_valuation_inputs(d), d
    print("parsed engine", d["engine"], "scenarios", list(d["scenarios"]))
    p = extract_json('probs: {"bear":0.25,"base":0.5,"bull":0.25}', "base")
    assert valid_scenario_probs(p), p
    print("probs", p, "OK")

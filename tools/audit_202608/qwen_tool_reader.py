"""qwen_tool_reader.py - reads a raw Qwen completion into the Ollama /api/chat message shape (pure functions).

The completion is the text the model wrote after the chat template's generation prompt (brief H, depth_provider
"ollama_raw"). Three parts, in order: thinking up to `</think>`, free content, and tool calls written as

    <tool_call>
    <function=NAME>
    <parameter=KEY>
    VALUE
    </parameter>
    </function>
    </tool_call>

Values are converted by the tool's top-level schema type for that parameter, as Ollama's qwen3coder.parseTypedToolValue does:
one leading and one trailing newline stripped; array/object kept whole by json.loads (nested values are never filtered);
number/integer numeric with no int64 clamping (Ollama issue #18421 is a known bug); boolean; otherwise string. An array or
object that does not parse stays the raw string.

Malformed or truncated tool-call markup makes NO call: not even a well-formed sibling in the same turn runs, and the whole text
after the thinking stays in `content`.
"""
import json
import math
import re

THINK_CLOSE = "</think>"
_CALL_OPEN, _CALL_CLOSE = "<tool_call>", "</tool_call>"
_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
_FUNC_RE = re.compile(r"\s*<function=([^>\n]+)>(.*)</function>\s*", re.S)
_PARAM_RE = re.compile(r"\s*<parameter=([^>\n]+)>(.*?)</parameter>", re.S)


def _one_newline_each_side(s):
    if s.startswith("\r\n"):
        s = s[2:]
    elif s.startswith("\n"):
        s = s[1:]
    if s.endswith("\r\n"):
        s = s[:-2]
    elif s.endswith("\n"):
        s = s[:-1]
    return s


def _declared_type(schema):
    t = (schema or {}).get("type") if isinstance(schema, dict) else None
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    return t


def convert_value(raw, schema):
    """The python value of one parameter's text under its top-level schema `type`."""
    s = _one_newline_each_side(raw)
    t = _declared_type(schema)
    if t in ("array", "object"):
        try:
            v = json.loads(s)
        except ValueError:
            return s
        return v if isinstance(v, list if t == "array" else dict) else s
    if t in ("integer", "number"):
        try:
            return int(s.strip())
        except ValueError:
            pass
        try:
            f = float(s.strip())
        except ValueError:
            return s
        return f if math.isfinite(f) else s
    if t == "boolean":
        low = s.strip().lower()
        return True if low == "true" else False if low == "false" else s
    return s


def _tool_schemas(tools):
    """{function name: properties dict} from the OpenAI-style tool list the harness sends."""
    out = {}
    for t in tools or []:
        fn = (t.get("function") if isinstance(t, dict) else None) or {}
        if fn.get("name"):
            out[fn["name"]] = (fn.get("parameters") or {}).get("properties") or {}
    return out


def parse_tool_calls(text, tools=None):
    """(calls, ok). calls = [{"function": {"name", "arguments"}}]; ok False when any tool-call markup is malformed or
    unclosed, in which case calls is []."""
    if _CALL_OPEN not in text and "<function=" not in text:
        return [], True
    schemas = _tool_schemas(tools)
    calls, pos = [], 0
    for m in _CALL_RE.finditer(text):
        if text[pos:m.start()].count(_CALL_OPEN) or "<function=" in text[pos:m.start()]:
            return [], False
        pos = m.end()
        f = _FUNC_RE.fullmatch(m.group(1))
        if not f:
            return [], False
        name, inner = f.group(1).strip(), f.group(2)
        args, ipos = {}, 0
        for p in _PARAM_RE.finditer(inner):
            if inner[ipos:p.start()].strip():
                return [], False
            ipos = p.end()
            key = p.group(1).strip()
            args[key] = convert_value(p.group(2), schemas.get(name, {}).get(key))
        if inner[ipos:].strip():
            return [], False
        calls.append({"function": {"name": name, "arguments": args}})
    tail = text[pos:]
    if _CALL_OPEN in tail or _CALL_CLOSE in tail or "<function=" in tail or not calls:
        return [], False
    return calls, True


def read_completion(text, tools=None, thinking_open=True):
    """{"content", "thinking", "tool_calls"} of one raw completion.

    thinking_open: the generation prompt ended inside `<think>` (thinking on), so the completion starts as thinking. Then a
    completion with no `</think>` is all thinking (a truncated turn), with no content and no calls, as Ollama's own parser
    treats it. With thinking off the prompt carries the closed empty block and the whole completion is content."""
    thinking = ""
    if thinking_open:
        head, sep, rest = text.partition(THINK_CLOSE)
        if not sep:
            return {"content": "", "thinking": text.strip(), "tool_calls": []}
        thinking, text = head.strip(), rest
    elif THINK_CLOSE in text:       # a stray closing tag with no open block: the text before it is thinking
        head, _, text = text.partition(THINK_CLOSE)
        thinking = head.replace("<think>", "").strip()
    calls, ok = parse_tool_calls(text, tools)
    if calls:
        text = text[:text.index(_CALL_OPEN)]
    return {"content": text.strip(), "thinking": thinking, "tool_calls": calls}

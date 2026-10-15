"""pi_text.py - how a price-implied value is written down, and read back (revision 19, brief_rev19.md A5 and D3).

One owner of the text of a price-implied value. The desk shows the model one line per judgment input (financial_model_tool.price_implied_lines);
the DEFAULTS block prints the same values at the default inputs (pack_facts.render_defaults_block, the `price_implied` line); the facts hold what
the line prints, so a fact read back from the text equals the fact the build holds (the parity check). Pure functions.

A value is written by the input it belongs to:
  coe, terminal_g     9.80%                    (two decimals of a percent)
  growth_years_3_5    +50.5% a year            (the geometric mean of years 3-5; one decimal of a percent, signed)
  fade_years          38.9 years               (one decimal; the desk's own value is an integer)
  terminal_ronic      33.0%  or  unlimited
  year2_level         $0.903B                  (three decimals, thousands grouped)
  long_run_margin     12.50%                   (two decimals of a percent; revision 24 step 2b, the desk's block only)
The DEFAULTS line lists the six inputs with "; " between them, each `name=value`, `name=not reachable (low to high)` or
`name=not available (reason)`.
"""
import math
import re

# the six inputs the DEFAULTS line prints (a revision-22 pack's line, byte for byte); the desk's block also holds long_run_margin (crux_check.J)
INPUTS = ("coe", "growth_years_3_5", "fade_years", "terminal_g", "terminal_ronic", "year2_level")
NA = "not available"


def fmt_value(name, v):
    """A value as the model and the DEFAULTS block read it. None reads "not available"; +inf (a return on new investment, or its string) "unlimited"."""
    if v is None:
        return NA
    if v == "unlimited" or (isinstance(v, float) and math.isinf(v)):
        return "unlimited"
    if name in ("coe", "terminal_g", "long_run_margin"):
        return f"{v * 100:.2f}%"
    if name == "growth_years_3_5":
        return f"{v * 100:+.1f}% a year"
    if name == "fade_years":
        return f"{v:.1f} years" if isinstance(v, float) else f"{v} years"
    if name == "terminal_ronic":
        return f"{v * 100:.1f}%"
    return f"${v:,.3f}B"                                            # year2_level


def fmt_bound(name, v):
    """The end of a bound: as a value, except that a whole number of years (the fade's 0 and 60) reads without a decimal."""
    if name == "fade_years" and isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
        return f"{int(v)} years"
    return fmt_value(name, v)


def parse_value(name, text):
    """The number a `fmt_value` text carries (inf for "unlimited"), at the precision it prints; None for "not available"."""
    s = text.strip()
    if s == NA:
        return None
    if s == "unlimited":
        return math.inf
    if name in ("coe", "terminal_g", "long_run_margin"):
        return float(s.rstrip("%")) / 100.0
    if name == "growth_years_3_5":
        return float(s.replace("% a year", "")) / 100.0
    if name == "fade_years":
        return float(s.replace(" years", ""))
    if name == "terminal_ronic":
        return float(s.rstrip("%")) / 100.0
    return float(s.lstrip("$").rstrip("B").replace(",", ""))


def quantize(name, v):
    """The value at the precision it prints: what a fact must hold so that the text it prints reads back equal."""
    return None if v is None else parse_value(name, fmt_value(name, v))


def quantize_block(pi):
    """The facts' form of a price-implied block (the desk's A4 block at the DEFAULTS): per input {"value", "reachable", "bound": {"low", "high"},
    "not_available"}, every number at its printed precision. A block with an error, or None, is {"not_available": <reason>} / None."""
    if not isinstance(pi, dict):
        return None
    if pi.get("error"):
        why = ("the price-implied solver failed its identity check" if pi["error"] == "identity" else str(pi["error"]))
        return {"not_available": why}
    out = {}
    for name in INPUTS:
        blk = pi.get(name)
        if not isinstance(blk, dict):
            return {"not_available": f"the price-implied block has no {name}"}
        bd = blk.get("bound") or {}
        na = blk.get("not_available")
        out[name] = {"value": quantize(name, blk.get("value")) if blk.get("reachable") else None, "reachable": bool(blk.get("reachable")),
                     "bound": {"low": quantize(name, bd.get("low")) if (not na and not blk.get("reachable")) else None,
                               "high": quantize(name, bd.get("high")) if (not na and not blk.get("reachable")) else None},
                     "not_available": na}
    return out


def render_line_value(facts_block):
    """The DEFAULTS `price_implied` line's value from the facts' block: "name=value; ..." for the six inputs, or "not available - <reason>" (an em
    dash) when there is no DEFAULTS run, or "not available" when the fact is absent."""
    if not isinstance(facts_block, dict):
        return NA
    if "not_available" in facts_block and len(facts_block) == 1:
        return f"{NA} — {facts_block['not_available']}"
    parts = []
    for name in INPUTS:
        e = facts_block.get(name) or {}
        if e.get("not_available"):
            parts.append(f"{name}={NA} ({e['not_available']})")
        elif e.get("reachable"):
            parts.append(f"{name}={fmt_value(name, e.get('value'))}")
        else:
            bd = e.get("bound") or {}
            parts.append(f"{name}=not reachable ({fmt_bound(name, bd.get('low'))} to {fmt_bound(name, bd.get('high'))})")
    return "; ".join(parts)


_ITEM_RE = re.compile(r"^(?P<name>[a-z0-9_]+)=(?P<rest>.*)$")
_UNREACHABLE_RE = re.compile(r"^not reachable \((?P<lo>.*) to (?P<hi>.*)\)$")
_UNAVAILABLE_RE = re.compile(r"^" + NA + r" \((?P<why>.*)\)$")


def parse_line_value(raw):
    """The facts' block a `render_line_value` text carries (the inverse of it): None for "not available"; {"not_available": reason} for the
    em-dash form; else the six inputs. Raises ValueError for a text that is neither, never guessing."""
    s = raw.strip()
    if s == NA:
        return None
    if s.startswith(NA + " — "):
        return {"not_available": s[len(NA) + 3:]}
    out = {}
    for item in s.split("; "):
        m = _ITEM_RE.match(item.strip())
        if not m or m.group("name") not in INPUTS:
            raise ValueError(f"price_implied item {item!r} is not name=value")
        name, rest = m.group("name"), m.group("rest").strip()
        mu, mn = _UNREACHABLE_RE.match(rest), _UNAVAILABLE_RE.match(rest)
        if mu:
            lo, hi = mu.group("lo").strip(), mu.group("hi").strip()
            out[name] = {"value": None, "reachable": False, "bound": {"low": parse_value(name, lo), "high": parse_value(name, hi)}, "not_available": None}
        elif mn:
            out[name] = {"value": None, "reachable": False, "bound": {"low": None, "high": None}, "not_available": mn.group("why")}
        else:
            out[name] = {"value": parse_value(name, rest), "reachable": True, "bound": {"low": None, "high": None}, "not_available": None}
    if set(out) != set(INPUTS):
        raise ValueError(f"price_implied lists {sorted(out)}, not the six judgment inputs")
    return out

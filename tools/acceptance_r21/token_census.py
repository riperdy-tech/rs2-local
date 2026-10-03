"""Revision 21 (coordinator review F): how large is the first prompt of a revision-21 pack, in tokens, against the 98,304-token window. Offline, no model.

  python token_census.py --packs <dir of <NAME>.md packs> [--consensus-dir <ab_reports/consensus of a recorded run>] --out <result.json>

The first prompt of a sample is the pack, the separator, the TASK and, with the research tools on, the RESEARCH_ADDENDUM (consensus_valuation.main), plus the tool
schemas and the system text the serving layer adds. Tokens are estimated three ways, the same number of characters each: the usual chars/4 proxy; chars/3, the
tree's own default (analyst_tools._turn_options reads 3.0 until a request has measured the true ratio); and the ratio MEASURED on the recorded run, when
--consensus-dir is given: the first turn's `prompt_tokens` over the characters of that run's `_pack.md` (the pack, the TASK and the addendum), tool schemas and system text
included. A pack whose estimate exceeds 60% of the window is flagged under each. Counts and sizes only: a pack is named by its rank, never by ticker.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "tools" / "audit_202608"))

WINDOW = 98304
LIMIT = 0.60


def measured_ratio(consensus_dir):
    """The median of tokens per character over the first turns of a recorded run: [(prompt_tokens of turn 1) / (characters of that run's _pack.md)] per sample, or
    None when the directory holds none."""
    rs = []
    for d in sorted(Path(consensus_dir).iterdir()) if consensus_dir and Path(consensus_dir).is_dir() else []:
        pack = d / "_pack.md"
        if not pack.exists():
            continue
        chars = len(pack.read_text(encoding="utf-8"))
        for n in (1, 2):
            f = d / f"sample{n}_research" / "_research_snapshot.json"
            if not f.exists():
                continue
            turns = json.loads(f.read_text(encoding="utf-8")).get("turns") or []
            pt = next((t.get("prompt_tokens") for t in turns if isinstance(t.get("prompt_tokens"), int)), None)
            if pt and chars:
                rs.append(pt / chars)
    return statistics.median(rs) if rs else None


def dist(xs):
    xs = sorted(xs)
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    return {"n": len(xs), "min": xs[0], "p50": statistics.median(xs), "p90": q(0.90), "max": xs[-1]} if xs else None


def census(packs_dir, ratio=None):
    import capability_test as cap
    extra = len("\n\n---\n\n") + len(cap.TASK) + len(cap.RESEARCH_ADDENDUM)
    rows = []
    for p in sorted(Path(packs_dir).glob("*.md")):
        text = p.read_text(encoding="utf-8")
        i = text.find("## PRIMARY SOURCES")
        j = text.find("\n## ", i + 3) if i != -1 else -1
        section = (j if j != -1 else len(text)) - i if i != -1 else 0
        rows.append({"pack_chars": len(text), "primary_chars": section, "chars": len(text) + extra})
    est = {"chars_over_4": lambda c: c / 4.0, "chars_over_3": lambda c: c / 3.0}
    if ratio:
        est["measured_ratio"] = lambda c: c * ratio
    out = {"packs": len(rows), "extra_chars": extra, "window": WINDOW, "limit_tokens": int(LIMIT * WINDOW), "measured_tokens_per_char": ratio,
           "chars": dist([r["chars"] for r in rows]), "primary_section_chars": dist([r["primary_chars"] for r in rows]), "estimates": {}}
    for k, f in est.items():
        toks = [f(r["chars"]) for r in rows]
        over = sum(1 for t in toks if t > LIMIT * WINDOW)
        out["estimates"][k] = {"tokens": dist([round(t) for t in toks]), "share_of_window_max": round(max(toks) / WINDOW, 4) if toks else None,
                               "packs_over_60_percent": over}
    out["largest_pack_chars"] = max((r["chars"] for r in rows), default=None)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--consensus-dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = census(a.packs, measured_ratio(a.consensus_dir))
    with open(a.out, "x", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""strip_low_trust.py — remove AI content-farm / hijacked-domain citations from EXISTING briefs.

deep_research now drops these at write time, but that only helps briefs built after the change.
1,093 such citations (12.6%) sit in briefs written earlier. They do not need re-researching --
a citation is a line in a markdown list, and removing it costs nothing but the bad source.

A topic left with ZERO sources after stripping is no longer grounded, so it is reported (and
with --apply, the whole brief is deleted so rebuild_briefs re-researches it properly rather
than leaving a topic asserting things with nothing behind it).

    python strip_low_trust.py            # dry run — report only
    python strip_low_trust.py --apply    # rewrite briefs in place
"""
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rs2_data
import deep_research as dr

RD = Path(rs2_data.CONFIG["out_research_dir"])
APPLY = "--apply" in sys.argv


def low_trust(url):
    try:
        d = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return False
    return any(p in d for p in dr.LOW_TRUST_DOMAINS)


def main():
    touched = removed = 0
    orphaned = []          # briefs where a topic loses ALL its sources
    for f in sorted(RD.glob("*.md")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        out, drop_here = [], 0
        for line in txt.splitlines():
            m = re.match(r"- (https?://\S+)", line)
            if m and low_trust(m.group(1)):
                drop_here += 1
                continue
            out.append(line)
        if not drop_here:
            continue
        new = "\n".join(out) + "\n"
        # any topic section left with no source lines?
        bare = [s.split("\n", 1)[0].split("  _(")[0].strip()
                for s in re.split(r"\n## ", new)[1:]
                if not re.search(r"^- https?://", s, re.M)]
        touched += 1
        removed += drop_here
        if bare:
            orphaned.append((f.stem, bare))
        elif APPLY:
            f.write_text(new, encoding="utf-8")

    print(f"briefs containing low-trust citations : {touched}")
    print(f"citations {'removed' if APPLY else 'that would be removed'} : {removed}")
    print(f"briefs where a topic would be left UNSOURCED: {len(orphaned)}")
    for t, topics in orphaned[:12]:
        print(f"   {t:7s} -> {', '.join(x[:30] for x in topics)}")
    if orphaned and APPLY:
        for t, _ in orphaned:
            (RD / f"{t}.md").unlink(missing_ok=True)
        print(f"   deleted {len(orphaned)} brief(s) so rebuild_briefs re-researches them")


if __name__ == "__main__":
    main()

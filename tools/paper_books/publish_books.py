"""publish_books.py - publishes m3o_books.json (the paper books' targets of one formation) and nothing else (plan M5, WO_formation_cloud_reader 2026-11-20).

    python tools/paper_books/publish_books.py [<formation T>] [--dry-run]

The file is qwen_site.books(T), written as qwen_site.build writes it (indent 1, sorted keys). Published through the dedicated publish clone
(paths.py screener_publish_repo, never the shared screener tree; non-negotiable 6): fetch, reset the clone to origin/main, copy the one file, commit it
by pathspec, push (rebase and retry, as the site publishers). qwen_overlay.json and qwen_reports are never read or written here; a clone with any other
change refuses. --dry-run writes the file to cache/site/ (qwen_site.OUT), fetches origin, prints the difference against origin/main's copy, and commits and
pushes nothing. Held under the shared publish lock (cache/screener_publish.lock of the main checkout).
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "site"))
import book_paths  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import qwen_site  # noqa: E402

REL = "public/data/m3o_books.json"


def build_text(T):
    return json.dumps(qwen_site.books(T), indent=1, sort_keys=True)


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)


def summary(old, new):
    """What changes between the published file (None when it is not there) and the new one, in words."""
    if old is None:
        return "no published copy: the file is new"
    out = [f"formation {old.get('formation')} -> {new['formation']}", f"generated_at {old.get('generated_at')} -> {new['generated_at']}",
           f"slots {old.get('slots')} -> {new['slots']}"]
    for b in sorted(set(old.get("books") or {}) | set(new["books"])):
        o, w = (old.get("books") or {}).get(b) or {}, new["books"].get(b) or {}
        out.append(f"{b}: {len(o)} -> {len(w)} names, added {len(set(w) - set(o))}, removed {len(set(o) - set(w))}, "
                   f"weight changed {sum(o[t] != w[t] for t in set(o) & set(w))}")
    return "; ".join(out) + ("" if old != new else " (identical)")


def published(repo):
    r = git(repo, "show", f"origin/main:{REL}")
    return json.loads(r.stdout) if r.returncode == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("formation_T", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    T = a.formation_T or qwen_site.latest_formation()
    text = build_text(T)
    new = json.loads(text)
    repo = book_paths.screener_repo()
    if "stock-screener" not in git(repo, "remote", "get-url", "origin").stdout:
        sys.exit("ABORT: the publish clone's origin is not stock-screener")
    qwen_site.OUT.mkdir(parents=True, exist_ok=True)
    mine = qwen_site.OUT / "m3o_books.json"
    mine.write_text(text, encoding="utf-8")
    qwen_site.LOCK = G._main_checkout() / "cache" / "screener_publish.lock"
    if not qwen_site._lock():
        sys.exit("ABORT: screener_publish.lock held")
    try:
        if git(repo, "fetch", "origin", "main").returncode:
            sys.exit("ABORT: fetch failed")
        old = published(repo)
        if a.dry_run:
            print(f"dry run: {mine} written; {summary(old, new)}", flush=True)
            return 0
        if git(repo, "status", "--porcelain", "--", f":!{REL}").stdout.strip():
            sys.exit("ABORT: the publish clone has unexpected local changes")
        if git(repo, "checkout", "-B", "main", "origin/main").returncode:
            sys.exit("ABORT: could not reset the publish clone to origin/main")
        shutil.copyfile(mine, repo / REL)
        json.loads((repo / REL).read_text(encoding="utf-8"))
        if (g := git(repo, "add", "--", REL)).returncode:                          # a failed add stages nothing and would read as "unchanged"
            sys.exit(f"ABORT: git add failed: {(g.stderr or g.stdout).strip()[:300]}")
        if git(repo, "diff", "--cached", "--quiet", "--", REL).returncode == 0:
            print("m3o_books.json unchanged: nothing to push", flush=True)
            return 0
        if git(repo, "-c", "commit.gpgsign=false", "commit", "-m", f"m3o books: formation {T} targets", "--", REL).returncode:
            sys.exit("ABORT: commit failed")
        for _ in range(5):
            git(repo, "fetch", "origin", "main")
            if git(repo, "rebase", "origin/main").returncode:
                git(repo, "rebase", "--abort")
                sys.exit("ABORT: rebase conflict against origin/main")
            if git(repo, "push", "origin", "main").returncode == 0:
                print("pushed m3o_books.json", git(repo, "rev-parse", "--short", "HEAD").stdout.strip(), summary(old, new), flush=True)
                return 0
            time.sleep(4)
        sys.exit("ABORT: push failed after 5 attempts")
    finally:
        if not a.dry_run:                                                          # the one file is not left pending in the clone, whatever happened
            git(repo, "reset", "-q", "--", REL)
            git(repo, "checkout", "-q", "--", REL)
        qwen_site.LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

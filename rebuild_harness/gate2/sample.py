"""sample.py - the gate-2 sample drawer (registration section 2).

    python -m rebuild_harness.gate2.sample draw  [--state-dir DIR] [--universe-dir DIR]
    python -m rebuild_harness.gate2.sample verify [--state-dir DIR]

For each replay date, 120 companies drawn AT RANDOM from the gate universe (market cap of at least $300M at T, a built family, an annual report accepted before T),
STRATIFIED BY FAMILY IN PROPORTION, seed 20261007, DRAWN ONCE, before any run.

THE UNIVERSE is read from `universe_<date>.json` files (written by `env.prepare_dates`, which applies the three conditions to the date's prepared companies); this
module sees only {cik, ticker, family} per company, never a price or an engine value, so the draw cannot depend on either.

THE DRAW.  Per date: the families' shares of the universe are turned into whole numbers summing to 120 by the largest-remainder rule (ties to the family name that
sorts first); a family never gets more than it has.  Within a family, `random.Random("<seed>:<date>:<family>").sample` of the ciks in sorted order.  The drawn
companies are then put in a random order (`random.Random("<seed>:<date>:order")`), which is the order the runner follows (the pilot is the first 10 of the first
date).  Every random generator is seeded by a string, so the draw does not depend on the Python hash seed.

WRITTEN ONCE.  The sample file is created with exclusive creation and its sha256 goes next to it (`<file>.sha256`).  A second draw REFUSES when the file exists; nothing
here ever overwrites or removes a sample file.  `load_verified` re-hashes the file against the recorded sha256 before anything is run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from . import config

BUILT_FAMILIES = ("operating", "commodity", "financial")


RULE = ("per date: family shares of the universe by the largest-remainder rule summing to per_date; within a family random.Random('<seed>:<date>:<family>').sample of the ciks "
        "in sorted order; the drawn companies shuffled by random.Random('<seed>:<date>:order')")


class SampleError(RuntimeError):
    pass


class SampleExists(SampleError):
    """The sample is drawn once; this refusal is the point of the module."""


def allocate(counts: Mapping[str, int], total: int) -> Dict[str, int]:
    """Whole numbers per family, proportional to `counts`, summing to min(total, sum(counts)): the largest-remainder rule; a family never gets more than it has."""
    n = sum(counts.values())
    if n <= 0:
        return {f: 0 for f in counts}
    total = min(total, n)
    exact = {f: counts[f] * total / n for f in counts}
    out = {f: min(int(exact[f]), counts[f]) for f in counts}
    left = total - sum(out.values())
    order = sorted(counts, key=lambda f: (-(exact[f] - int(exact[f])), f))
    while left > 0:
        moved = False
        for f in order:
            if left > 0 and out[f] < counts[f]:
                out[f] += 1
                left -= 1
                moved = True
        if not moved:
            break
    return out


def draw_date(companies: Sequence[Mapping], date: str, seed: int = config.SEED, per_date: int = config.PER_DATE) -> dict:
    """{"entries": [{cik, ticker, family}...] in the runner's order, "universe": {family: n}, "allocation": {family: k}} for one date."""
    seen = set()
    by_family: Dict[str, List[Mapping]] = {}
    for c in sorted(companies, key=lambda c: str(c["cik"])):
        cik = str(c["cik"]).zfill(10)
        if cik in seen:
            raise SampleError(f"{date}: company {cik} is listed twice in the universe")
        seen.add(cik)
        fam = c["family"]
        if fam not in BUILT_FAMILIES:
            raise SampleError(f"{date}: company {cik} has family {fam!r}, which is not built (the universe holds built families only)")
        by_family.setdefault(fam, []).append({"cik": cik, "ticker": c.get("ticker"), "family": fam})
    counts = {f: len(v) for f, v in sorted(by_family.items())}
    alloc = allocate(counts, per_date)
    chosen: List[dict] = []
    for fam in sorted(by_family):
        rng = random.Random(f"{seed}:{date}:{fam}")
        chosen += rng.sample(by_family[fam], alloc[fam])
    random.Random(f"{seed}:{date}:order").shuffle(chosen)
    return {"entries": chosen, "universe": counts, "allocation": alloc}


def draw(universe: Mapping[str, Sequence[Mapping]], dates: Sequence[str] = config.DATES, seed: int = config.SEED, per_date: int = config.PER_DATE) -> dict:
    out = {"registration": "REGISTRATION_gate2_DRAFT.md section 2", "seed": seed, "per_date": per_date, "dates": list(dates), "rule": RULE,
           "universe_counts": {}, "allocation": {}, "entries": {}}
    for d in dates:
        if d not in universe:
            raise SampleError(f"no universe for {d}")
        r = draw_date(universe[d], d, seed, per_date)
        out["universe_counts"][d], out["allocation"][d], out["entries"][d] = r["universe"], r["allocation"], r["entries"]
    return out


def sample_path(state_dir=None) -> Path:
    return config.state_paths(state_dir)["sample"] / "sample.json"


def sha256_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_once(path, sample: dict) -> str:
    """Create the sample file (exclusive creation) and its sha256 file; refuse when the sample file exists.  Returns the sha256."""
    path = Path(path)
    sha_path = path.with_name(path.name + ".sha256")
    if path.exists() or sha_path.exists():
        raise SampleExists(f"{path} already exists: the sample is drawn once and is never redrawn")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(sample, indent=1, sort_keys=True)
    data = text.encode("utf-8")
    with open(path, "xb") as fh:                    # 'x': an existing file is an error here as well, even if the check above raced
        fh.write(data)
    sha = hashlib.sha256(data).hexdigest()
    with open(sha_path, "x", encoding="utf-8") as fh:
        fh.write(json.dumps({"file": path.name, "sha256": sha, "written_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return sha


def load_verified(path) -> dict:
    """The sample, after its bytes are checked against the recorded sha256 (a changed sample file is refused)."""
    path = Path(path)
    sha_path = path.with_name(path.name + ".sha256")
    if not path.exists() or not sha_path.exists():
        raise SampleError(f"no sample at {path} (or no sha256 file): draw it first")
    want = json.loads(sha_path.read_text(encoding="utf-8"))["sha256"]
    got = sha256_file(path)
    if got != want:
        raise SampleError(f"{path} hashes to {got}, the recorded sha256 is {want}: the sample changed after it was drawn")
    return json.loads(path.read_text(encoding="utf-8"))


def read_universe(universe_dir, dates=config.DATES) -> Dict[str, list]:
    out = {}
    for d in dates:
        p = Path(universe_dir) / f"universe_{d}.json"
        if not p.exists():
            raise SampleError(f"{p} is missing: run env.prepare_dates for {d} first")
        doc = json.loads(p.read_text(encoding="utf-8"))
        out[d] = doc["companies"]
    return out


def jobs(sample: Mapping, dates: Sequence[str] = None) -> List[dict]:
    """Every (date, company) of the sample in the runner's order: dates ascending, each date in its drawn order."""
    out = []
    for d in (dates or sample["dates"]):
        for e in sample["entries"][d]:
            out.append({"date": d, "cik": e["cik"], "ticker": e.get("ticker"), "family": e["family"]})
    return out


def pilot_jobs(sample: Mapping, n: int = config.PILOT_N, date: str = config.PILOT_DATE) -> List[dict]:
    """The pilot: the first `n` companies of the first date's drawn order (a random mix of the families); they are part of the sample."""
    return jobs(sample, [date])[:n]


def masked_control(sample: Mapping, n: int = config.MASKED_N, seed: int = config.SEED) -> List[dict]:
    """The G6 control: `n` company-dates of the sample, chosen by a seeded generator (deterministic from the sample file)."""
    allj = jobs(sample)
    rng = random.Random(f"{seed}:{config.MASKED_SEED_LABEL}")
    return sorted(rng.sample(allj, min(n, len(allj))), key=lambda j: (j["date"], j["cik"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["draw", "verify"])
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--universe-dir", type=Path)
    a = ap.parse_args(argv)
    paths = config.state_paths(a.state_dir)
    path = paths["sample"] / "sample.json"
    if a.cmd == "verify":
        s = load_verified(path)
        print(json.dumps({"sha256": sha256_file(path), "dates": s["dates"], "n": {d: len(v) for d, v in s["entries"].items()}}, indent=1))
        return 0
    uni = read_universe(a.universe_dir or paths["ctx"])
    try:
        sha = write_once(path, draw(uni))
    except SampleExists as e:
        print(f"REFUSED: {e}")
        return 5
    print(f"sample written: {path}\nsha256 {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

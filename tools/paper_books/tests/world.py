"""Test world: writes formations, prices, factor_scores, packets, runs and maps for m3o_engine into a folder (fixtures only).

    python tools/paper_books/tests/world.py <dir>     rewrites the checked-in fixtures (tests/fixtures/) from the standard scenario
Layout under root: forward/ (formations.jsonl, prices/), factor_scores/<commit>.json, packets/, runs/, inputs/ (maps; relative paths).
"""
import csv
import hashlib
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import m3o_engine as E  # noqa: E402

fl = E.fl
SESSIONS = []
_d = date(2026, 7, 27)
while _d <= date(2026, 10, 16):
    if fl.session(_d):
        SESSIONS.append(_d)
    _d += timedelta(days=1)
GROWTH = {"A": .002, "B": .001, "C": -.001, "D": .003, "E": .0005, "F": .0015, "G": .0007, "OPXA": .001, "SPY": .0005,
          "ZERO": 0.0, "DEAD": .001, "H": .0012}
BASE = {t: 20.0 + 3 * i for i, t in enumerate(sorted(GROWTH))}
T1, T2, T3 = "2026-07-31", "2026-08-31", "2026-09-30"
FILLS = {T1: "2026-08-03", T2: "2026-09-01", T3: "2026-10-01"}
DEFAULT_FORMATIONS = [
    {"T": T1, "book": ["A", "B", "C", "D", "E", "OPXA"]},
    {"T": T2, "book": ["A", "B", "C", "D", "F", "OPXA"]},
    {"T": T3, "book": ["A", "B", "C", "D", "F", "OPXA"]},
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def price(t, d):
    """(adj_open, adj_close) of ticker t on session d, or None. ZERO is flat; DEAD opens at 0.0 from 2026-09-01; GONE has no series."""
    if t == "GONE" or d not in SESSIONS:
        return None
    i = SESSIONS.index(d)
    if t == "DEAD" and d >= date(2026, 9, 1):
        return (0.0, 0.0)
    o = BASE.get(t, 25.0) * (1 + GROWTH.get(t, 0.001) * i)
    return (o, o * (1 + GROWTH.get(t, 0.001) / 2))


def jdump(obj):
    return json.dumps(obj, indent=1, sort_keys=True).encode("utf-8")


def claim(event_type="bankruptcy_or_restructuring", support="supported", status="occurred", occurred_on="not stated", fact_ids=("P1",)):
    return {"claim": "The company filed a petition.", "fact_ids": list(fact_ids), "quotes": [], "numbers": [], "confidence_basis": "x",
            "event_type": event_type, "status": status, "occurred_on": occurred_on, "support": support}


class World:
    def __init__(self, root, formations=None):
        self.root = Path(root)
        self.formations = formations or DEFAULT_FORMATIONS
        self.spec = {}
        for d in ("forward/prices", "factor_scores", "packets", "runs", "inputs", "ledger"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.forward, self.inputs, self.ledger = self.root / "forward", self.root / "inputs", self.root / "ledger"
        self.prices_for(sorted(set(GROWTH) | {"GONE"}))
        self.write_formations()

    # --- inputs
    def dec(self, T):
        return f"{T}T18:00:00Z"

    def prices_for(self, tickers):
        rows = [(t, d.isoformat(), *price(t, d)) for t in tickers for d in SESSIONS if price(t, d)]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["ticker", "date", "adj_open", "adj_close"])
        w.writerows(rows)
        raw = buf.getvalue().encode("utf-8")
        stem = "2026-10-17T000000Z"
        (self.forward / "prices" / f"{stem}.csv").write_bytes(raw)
        (self.forward / "prices" / f"{stem}.receipt.json").write_bytes(
            jdump({"fetched_utc_local_clock": stem, "source": "fixture", "sha256": sha(raw), "rows": len(rows),
                   "window": [SESSIONS[0].isoformat(), SESSIONS[-1].isoformat()], "note": "fixture"}))
        self.px = {}
        for t, d, o, c in rows:
            self.px.setdefault(t, {})[d] = (o, c)

    def commit(self, T):
        return ("c" + T.replace("-", "")).ljust(40, "0")

    def write_formations(self):
        lines = []
        for f in self.formations:
            T, book = f["T"], f["book"]
            fs = {"tickers": {t: {"fct_band": "research_now" if t in book else "pass", "fct_rank": i + 1, "fct_veto": None,
                                  "fct_nominated_doors": ["DOOR_1_COMPOUNDER"], "fct_flags": []}
                              for i, t in enumerate(sorted(set(book) | {"Z1", "Z2"}))}}
            (self.root / "factor_scores" / f"{self.commit(T)}.json").write_bytes(jdump(fs))
            rec = {"book": sorted(book), "book_size": len(book), "decision_time_utc": self.dec(T), "fill_session": FILLS[T], "flags": {},
                   "formation_T": T, "output_commit": self.commit(T), "run_id": "run" + T, "scoring_base": "b" * 40,
                   "verifier": {"verdict": "PASS", "checks": {}, "input_issues": [], "mri": None}, "workflow": "fixture"}
            lines.append(json.dumps(rec, sort_keys=True))
        (self.forward / "formations.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def loader(self):
        return lambda c: (self.root / "factor_scores" / f"{c}.json").read_bytes()

    def set(self, T, t, **kw):
        self.spec.setdefault((T, t), {}).update(kw)

    def materialize(self):
        for f in self.formations:
            T = f["T"]
            if f.get("map", True) is False:
                continue
            names = {}
            for t in sorted(f["book"]):
                if t in fl.OPERATOR_EXCLUDED:
                    names[t] = {"packet": None, "run_dir": None, "attempts": 0, "state": "operator_excluded"}
                    continue
                names[t] = self.name_entry(T, t, self.spec.get((T, t), {}))
            m = {"formation_T": T, "decision_time_utc": self.dec(T), "builder_version": "m3m.packet.builder.v6",
                 "run_id": "run" + T, "output_commit": self.commit(T), "book": sorted(f["book"]), "names": names}
            if f.get("label"):
                m["label"] = f["label"]
            (self.inputs / f"formation_{T}.json").write_bytes(jdump(m))

    def name_entry(self, T, t, s):
        items = s.get("items", [("Quarterly results discussion.", "2026-05-01T12:00:00Z")])
        pk = None
        if s.get("packet", True):
            ev = [{"kind": "screener_row", "fact_id": "S0", "name": "screener_row", "text": f"symbol: {t}", "accepted_raw": None}]
            ev += [{"kind": "annual_section", "fact_id": f"P{i + 1}", "name": "x", "text": text, "accepted_raw": acc,
                    "source": {"accession": f"0000000000-26-{i + 1:06d}", "url": ""}} for i, (text, acc) in enumerate(items)]
            packet = {"contract": "m3m.packet.v1", "builder_version": "m3m.packet.builder.v6", "builder_code": {"packet.py": "bc-" + t},
                      "ticker": t, "decision_time_utc": self.dec(T), "evidence": ev}
            (self.root / "packets" / f"{T}_{t}.json").write_bytes(jdump(packet))
            pk = f"../packets/{T}_{t}.json"
        finished = s.get("finished", f"{T}T19:00:00.000000Z")      # None: no run; "running": a manifest without finished_at
        entry = {"packet": pk, "run_dir": None, "attempts": 1,
                 "state": s.get("state", "complete" if finished not in (None, "running") else "to_run")}
        if "reason" in s:
            entry["reason"] = s["reason"]
        if finished is not None:
            rd = self.root / "runs" / f"{T}_{t}"
            rd.mkdir(parents=True, exist_ok=True)
            me = s.get("me_status", "ok")
            man = {"run_id": f"{t}-{T}", "ticker": t, "decision_time_utc": self.dec(T), "status": s.get("run_status", "complete"),
                   "qwen_c": {"git_commit": "q" * 7 + "abc"}, "model": {"tag": "rs2-analyst-deep-mtp5-v33"},
                   "prompt_version": "m3m.prompt.v3", "contract": "m3m.analysis.v2", "builder_version": "m3m.packet.builder.v6"}
            if finished != "running":
                an = jdump({"tasks": {"material_events": {"status": me, "claims": s.get("claims", []) if me == "ok" else []}}})
                (rd / "analysis.json").write_bytes(an)
                man.update(finished_at=finished, analysis_sha256="0" * 64 if s.get("tamper") else sha(an))
            (rd / "manifest.json").write_bytes(jdump(man))
            entry["run_dir"] = f"../runs/{T}_{t}"
        return entry

    # --- engine
    def run(self):
        self.materialize()
        return E.run(self.forward, self.inputs, self.ledger, factor_loader=self.loader())

    def write(self):
        L, marks = self.run()
        return E.write_ledger(L, marks, self.ledger)

    def lines(self, name):
        p = self.ledger / f"{name}.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def accepted_days_before(T, days):
    d = datetime.fromisoformat(T) - timedelta(days=days)
    return d.strftime("%Y-%m-%dT12:00:00Z")


def date_days_before(T, days):
    return date.fromisoformat(T) - timedelta(days=days)


def standard(root):
    """The checked-in fixture scenario (fixtures/): a B1 hit on B, a late-finishing run for D at T1, an incomplete name F at T2."""
    w = World(root)
    w.set(T1, "B", items=[("Item 1.03 Bankruptcy or Receivership.", accepted_days_before(T1, 30))])
    w.set(T1, "D", finished="2026-08-04T15:00:00.000000Z")
    w.set(T2, "F", state="analysis_incomplete", reason="runner_attempts", finished=None)
    w.materialize()
    return w


if __name__ == "__main__":
    standard(Path(sys.argv[1]))

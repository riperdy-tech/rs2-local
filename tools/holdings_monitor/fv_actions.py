"""fv_actions.py - WO_TB2b: the holdings monitor's warnings act on paper book FV between formations. Paper only; nothing here trades.

    python tools/holdings_monitor/fv_actions.py run [--root DIR] [--dry-run]

SPEC_m3o_bookV rules 6 to 8, PREREG_m3o_bookV `between_formations`. One pass reads the monitor's journal for `resolved` lines that carry a
`warning_kind`, on a name FV holds now, read after the decision in force was made, and not yet handled:

    news_event                       the name leaves at the next open, reason `under_review`. No valuation (it reads filings only).
    event_found / thesis_changed     re-valued (packet at the read's T, two seeds, the formation's pinned anchors, closure and rates). It leaves at
                                     the next open, reason `revalued_not_cheap`, when the new cheapness is below the formation's cut or there is no
                                     value; otherwise it stays (`revalued_stays`).

FV NOW is read from the engine's recomputation (m3o_engine.run over the standard folders and value_dir), never from the stored ledger.
A newer snapshot (value/fv_<T'>.json) whose fill is not priced yet is a decision about to replace the one in force: every warning waits
(`waiting`, reason decision_not_priced) and is acted on under T' at the first pass after it is priced, so no exit is written that the next
decision would supersede.

FILES (under the monitor root, `--root`)
    fv_actions.jsonl               append-only journal: decided, covered, waiting, slot_filled, slot_failed, stop (a line whose event_id is held is not
                                   written again, the rule of monitor._write_journal)
    state/fv_actions.json          re-valuations in progress, per warning: price, packet, filled slots, failures (tmp + replace); a filled slot never reruns
    state/fv_actions.lock          one pass at a time (monitor.take_lock)
    state/fv_actions_STOP.flag     a code defect, a third transport failure, or a missing pinned folder: the pass refuses to start while it exists
and, beside FV's snapshots, `<value_dir>/fv_exits.jsonl` (the file m3o_engine.fv_exits reads), one line per exit with exactly m3o_engine.EXIT_KEYS.
A `decided` line that is an exit holds its exit record whole (`exit_record`); a crash between the journal line and the record is repaired at the
next pass by appending that record unchanged. Never two records for one (formation_T, ticker).

Exit codes: 0 done, 2 the engine could not be read, 3 another pass holds the lock, 4 GPU busy or a formation has work left (yielding),
6 transport failure or a changed tracked tree, 7 the stop flag.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "paper_books"))
import monitor as M  # noqa: E402
import m3o_engine as E  # noqa: E402
import formation_fv as FF  # noqa: E402
import formation_run as FR  # noqa: E402
import formation_value as FVAL  # noqa: E402

VALUE = E.BOOKS / "m3o" / "value"
SEEDS = FVAL.SEEDS                                          # 1000 and 3000
MAX_FAILS = FVAL.MAX_FAILS                                  # the third transport failure of a slot writes the stop flag
PRICE_WINDOW_DAYS = 7                                       # price_T: the close on the formation's date or the last bar of the 7 days before it
EXIT_OUTCOMES = ("under_review", "revalued_not_cheap")
CONSENSUS_KEYS = ("status", "reason", "detail", "values", "annotations", "reverts", "of_record", "options", "numbers", "neutral", "directions",
                  "departures", "evidence", "year", "seeds")


class Halt(Exception):
    """The pass ends here with this exit code."""

    def __init__(self, code, why):
        super().__init__(why)
        self.code, self.why = code, why


# ---------------------------------------------------------------- files

def append_journal(path, lines):
    """Append the lines whose event_id the journal does not hold yet (monitor._write_journal's rule), each flushed and synced."""
    path = Path(path)
    have = {l.get("event_id") for l in M._jsonl(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        if f.tell() > 0:
            with open(path, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != b"\n":
                    f.write(b"\n")                                    # never bury a torn last line mid-file
        for line in lines:
            if line["event_id"] in have:
                continue
            have.add(line["event_id"])
            f.write((json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())


def append_exit(value_dir, record):
    """One line of fv_exits.jsonl. Refuses a second record for the same (formation_T, ticker)."""
    path = Path(value_dir) / "fv_exits.jsonl"
    if any((r.get("formation_T"), r.get("ticker")) == (record["formation_T"], record["ticker"]) for r in M._jsonl(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        if f.tell() > 0:
            with open(path, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != b"\n":
                    f.write(b"\n")
        f.write((json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    return True


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- FV now

def view_from_lines(L, value_dir):
    """FV's standing from the engine's recomputed lines L: {"T", "decision_time_utc", "held", "cut", "lines", "exits", "pending_T"}; T is None
    when FV has no decision. `exits` are the (formation_T, ticker) keys of fv_exits.jsonl; `pending_T` the latest snapshot newer than T that is
    not a decision yet (its fill is not priced)."""
    fv = [l for l in L["actions"] if l["arm"] == "FV" and l["kind"] == "at_fill_open"]
    exits = [(r["formation_T"], r["ticker"]) for r, _ in E.fv_exits(value_dir)]
    if not fv:
        return {"T": None, "decision_time_utc": None, "held": [], "cut": None, "lines": {}, "exits": exits, "pending_T": None}
    T = max(l["formation_T"] for l in fv)
    form = next(f for f in L["formations"] if f["formation_T"] == T)
    lines = {l["ticker"]: l for l in fv if l["formation_T"] == T}
    cut = next((l["value"]["cut"] for l in lines.values() if l.get("value")), None)
    later = sorted(p.name[3:13] for p in Path(value_dir).glob("fv_*.json") if re.fullmatch(r"fv_\d{4}-\d{2}-\d{2}\.json", p.name) and p.name[3:13] > T)
    return {"T": T, "decision_time_utc": form["decision_time_utc"], "held": E.fv_held_now(L), "cut": cut, "lines": lines, "exits": exits,
            "pending_T": later[-1] if later else None}


def real_engine(value_dir):
    L, _ = E.run(E.fl.HERE, E.BOOKS / "m3o" / "inputs", E.BOOKS / "m3o" / "ledger", value_dir=value_dir)
    return view_from_lines(L, value_dir)


# ---------------------------------------------------------------- prices

def pick_prices(resp, T):
    """(price_T, price_now) from a monitor.yf_prices response: price_T the last close on or before T and within 7 days of it, price_now the
    latest close. None for a price that is not there. 0.0 is a close."""
    rows = sorted((M.as_date(r["date"]), float(r["close"])) for r in resp["closes"] if M.is_number(r.get("close")))
    d = date.fromisoformat(T)
    near = [c for x, c in rows if d - timedelta(days=PRICE_WINDOW_DAYS) <= x <= d]
    return (near[-1] if near else None), (rows[-1][1] if rows else None)


# ---------------------------------------------------------------- the real slot, consensus, guards (not run by any test of this folder)

def real_slot(n, seed, fields, anchors, closure):
    """One valuation slot, as formation_value runs it: the run directory of a killed pass moved aside, `qwen_c.value.run` from the repository
    root, judged by formation_value.judge. {"outcome": "filled", status, reason, result, result_sha256, seconds, git} or {"outcome": "defect" |
    "transport", "detail", "aside"}."""
    head = FVAL.git("rev-parse", "HEAD")
    rd, pk = FVAL.run_dir(n, seed)
    moved = []
    if rd.exists():
        moved.append(FVAL.aside(rd))
    env = dict(os.environ, MRI_ANCHORS_DIR=str(anchors), RS2_REFERENCE_CLOSURE=str(closure), PYTHONIOENCODING="utf-8")
    t0 = time.time()
    r = subprocess.run([FVAL.PY, "-m", "qwen_c.value.run", n["packet"], "--cik", str(fields["cik"]), "--sector", str(fields["sector"]),
                        "--market-cap", str(fields["market_cap"]), "--family", str(fields["family"]), "--seed", str(seed)],
                       cwd=FVAL.ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    res = rd / "result.json"
    try:
        body = json.loads(res.read_text(encoding="utf-8")) if (r.returncode == 0 and res.exists()) else {}
    except ValueError:
        body = {}
    fill, why, defect = FVAL.judge(body, n, pk, seed, head)
    if not fill:
        if rd.exists():
            moved.append(FVAL.aside(rd))
        return {"outcome": "defect" if defect else "transport", "detail": f"{why}; {(r.stderr or r.stdout or '')[-300:]}", "aside": moved}
    return {"outcome": "filled", "status": body["status"], "reason": body.get("reason"), "result": str(res), "result_sha256": sha256_file(res),
            "seconds": round(time.time() - t0, 1), "git": head, "aside": moved}


def real_consensus(n, fields, ok, anchors, closure):
    """formation_consensus's block for one name, offline: the two seeds' checked results combined (no model call), with the moved market cap."""
    saved = {k: os.environ.get(k) for k in ("MRI_ANCHORS_DIR", "RS2_REFERENCE_CLOSURE")}
    os.environ["MRI_ANCHORS_DIR"], os.environ["RS2_REFERENCE_CLOSURE"] = str(anchors), str(closure)
    try:
        sys.path.insert(0, str(FVAL.ROOT))
        from qwen_c.value import consensus, run, task
        packet = json.loads(Path(n["packet"]).read_text(encoding="utf-8"))
        f, b, bar, record, r, prov, fy_ends = run.prepare(packet, fields["cik"], str(fields["sector"]), fields["market_cap"] or 0, online=False,
                                                          family=fields["family"])
        ids = task.evidence_ids(packet, record, b, bar, r, prov)
        res = consensus.combine(ok, ids, b, bar, r, fy_ends, "financial" if fields["family"] in run.FINANCIAL else "operating")
        return {k: res.get(k) for k in CONSENSUS_KEYS}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def real_dirty():
    return FVAL.git("status", "--porcelain", "--untracked-files=no")


# ---------------------------------------------------------------- the pass

class Pass:
    def __init__(self, root, value_dir, view, *, checks_dir, screener_repo, worktree, build, slot, consensus, prices, gpu, waiting, dirty,
                 lock_value, unlock_value, clock):
        self.root, self.value_dir, self.view, self.clock = Path(root), Path(value_dir), view, clock
        self.journal, self.state_path, self.flag = self.root / "fv_actions.jsonl", self.root / "state" / "fv_actions.json", self.root / "state" / "fv_actions_STOP.flag"
        self.checks_dir, self.screener_repo, self.worktree = checks_dir, screener_repo, worktree
        self.build, self.slot, self.consensus, self.prices, self.gpu, self.waiting, self.dirty = build, slot, consensus, prices, gpu, waiting, dirty
        self.lock_value, self.unlock_value, self.have_value_lock = lock_value, unlock_value, False
        self.state = M.read_json(self.state_path, {"revals": {}})
        self.T, self.cut = view["T"], view["cut"]
        self.exit_keys = {tuple(k) for k in view["exits"]}

    # -- small writers
    def line(self, kind, event_id, ticker, **fields):
        return {"kind": kind, "event_id": event_id, "t": M.iso(self.clock()), "ticker": ticker, **fields}

    def save(self):
        M.write_json_atomic(self.state_path, self.state)

    def stop(self, why):
        append_journal(self.journal, [self.line("stop", "stop:" + M.iso(self.clock()), None, reason=why)])
        self.flag.parent.mkdir(parents=True, exist_ok=True)
        self.flag.write_text(why, encoding="utf-8")
        raise Halt(7, why)

    # -- crash repair
    def repair(self, journal, dry_run):
        out = []
        for l in journal:
            rec = l.get("exit_record") if l.get("kind") == "decided" else None
            if rec and (rec["formation_T"], rec["ticker"]) not in self.exit_keys:
                if not dry_run:
                    append_exit(self.value_dir, rec)
                self.exit_keys.add((rec["formation_T"], rec["ticker"]))
                out.append(rec["ticker"])
        return out

    # -- the warnings to act on
    def candidates(self, monitor_journal, handled):
        held, cutoff = set(self.view["held"]), M.parse_utc(self.view["decision_time_utc"])
        return [l for l in monitor_journal if l.get("kind") == "resolved" and l.get("warning_kind") and l.get("ticker") in held
                and l.get("decision_time_utc") and M.parse_utc(l["decision_time_utc"]) > cutoff and l.get("event_id") not in handled]

    # -- the decision
    def decide(self, w, others, outcome, revaluation, cover_reason):
        decided_utc = M.iso(self.clock())
        rec = None
        if outcome in EXIT_OUTCOMES:
            rec = {"formation_T": self.T, "ticker": w["ticker"], "reason": outcome, "warning_kind": w["warning_kind"], "warning_event_id": w["event_id"],
                   "decided_utc": decided_utc, "effective_session": E.first_open_after(M.parse_utc(decided_utc)).isoformat(), "revaluation": revaluation}
            assert tuple(sorted(rec)) == tuple(sorted(E.EXIT_KEYS))
        did = "decided:" + w["event_id"]
        lines = [self.line("decided", did, w["ticker"], formation_T=self.T, warning_event_id=w["event_id"], warning_kind=w["warning_kind"],
                           run_id=w.get("run_id"), decision_time_utc=w["decision_time_utc"], outcome=outcome, decided_utc=decided_utc,
                           revaluation=revaluation, exit_record=rec)]
        lines += [self.covered(o, cover_reason, did) for o in others]
        append_journal(self.journal, lines)                  # the journal line first; the record after it (a crash between is repaired)
        if rec is not None:
            append_exit(self.value_dir, rec)
            self.exit_keys.add((self.T, w["ticker"]))
        self.state["revals"].pop(w["event_id"], None)
        self.save()
        return {"ticker": w["ticker"], "warning_event_id": w["event_id"], "outcome": outcome}

    def covered(self, w, reason, by=None):
        return self.line("covered", "covered:" + w["event_id"], w["ticker"], formation_T=self.T, warning_event_id=w["event_id"], reason=reason, covered_by=by)

    # -- the re-valuation
    def revalue(self, w):
        """("decided", outcome, revaluation) or ("wait", reason, None). Halt ends the pass."""
        wid, t, T = w["event_id"], w["ticker"], self.T
        read_T = M.iso(M.parse_utc(w["decision_time_utc"]))
        st = self.state["revals"].setdefault(wid, {"ticker": t, "formation_T": T, "read_T": read_T, "price": None, "packet": None,
                                                    "packet_refused": None, "slots": {}, "failures": {}})
        obj = {"read_T": read_T, "packet": None, "packet_sha256": None, "code_commit": None, "slots": {}, "consensus_status": None,
               "consensus_annotations": [], "value_base": None, "shares": None, "equity_value": None, "market_cap": None, "price_T": None,
               "price_now": None, "market_cap_moved": None, "cheapness": None, "cut": self.cut, "reason": None, "prior_value": (self.view["lines"].get(t) or {}).get("value")}
        ip = self.value_dir / f"formation_{T}.json"
        if not ip.is_file():
            self.stop(f"the valuation index {ip} is missing")
        idx = json.loads(ip.read_text(encoding="utf-8"))
        n = (idx.get("names") or {}).get(t)
        if n is None:
            return "decided", "revalued_not_cheap", {**obj, "reason": "not_in_index"}
        cap = FF.number(n.get("market_cap"))
        missing = [k for k in ("cik", "sector", "family") if n.get(k) is None or n.get(k) == ""] + (["market_cap"] if cap is None or not cap > 0 else [])
        if missing:
            return "decided", "revalued_not_cheap", {**obj, "reason": "field_missing", "detail": missing}
        obj["market_cap"] = cap
        if st["price"] is None:                                           # b. one fetch, kept so a resumed pass uses the same prices
            try:
                price_T, price_now = pick_prices(self.prices(t), T)
            except Exception as e:  # noqa: BLE001  the source failed: the warning waits
                price_T, price_now, err = None, None, f"{type(e).__name__}: {e}"
            else:
                err = None
            if price_T is None or price_now is None or not price_T > 0:
                self.journal_once("waiting", f"waiting:{wid}:{self.clock().date().isoformat()}", t, warning_event_id=wid, reason="price_unavailable",
                                  detail=err, price_T=price_T, price_now=price_now)
                return "wait", "price_unavailable", None
            st["price"] = {"price_T": price_T, "price_now": price_now, "market_cap_moved": cap * price_now / price_T, "fetched_utc": M.iso(self.clock())}
            self.save()
        moved = st["price"]["market_cap_moved"]
        obj.update(price_T=st["price"]["price_T"], price_now=st["price"]["price_now"], market_cap_moved=moved)
        if st["packet"] is None and st["packet_refused"] is None:         # c. filings only, at the read's T and the commit the read used
            c = M.verified_commit(self.checks_dir, read_T)
            if c is None:
                st["packet_refused"] = "no_verified_commit_at_T"
            else:
                try:
                    pk = self.build(t, read_T, c["commit"], c["check_file"], self.screener_repo, self.worktree)
                    st["packet"] = {"packet": pk["packet"], "packet_sha256": pk["packet_sha256"], "builder_version": pk.get("builder_version"),
                                    "commit": c["commit"], "file_sha256": sha256_file(pk["packet"])}
                except M.PacketRefused as ex:
                    st["packet_refused"] = str(ex)
            self.save()
        if st["packet"] is None:
            return "decided", "revalued_not_cheap", {**obj, "reason": "packet_refused", "detail": st["packet_refused"]}
        pk = st["packet"]
        obj.update(packet=pk["packet"], packet_sha256=pk["packet_sha256"])
        pn = {"packet": pk["packet"], "packet_sha256": pk["packet_sha256"]}
        fields = {"cik": n["cik"], "sector": n["sector"], "family": n["family"], "market_cap": moved}
        anchors, closure = self.value_dir / f"anchors_{T}", self.value_dir / f"closure_{T}" / "reference_closure.json"
        for seed in SEEDS:                                                # d. two slots
            k = str(seed)
            if k in st["slots"]:
                continue
            self.guard(anchors, closure, pk)
            r = self.slot(pn, seed, fields, anchors, closure)
            if r["outcome"] == "filled":
                st["slots"][k] = {key: r.get(key) for key in ("status", "reason", "result", "result_sha256", "seconds", "git")}
                self.save()
                append_journal(self.journal, [self.line("slot_filled", f"slot:{wid}:{k}", t, warning_event_id=wid, seed=seed, **st["slots"][k])])
                continue
            st["failures"][k] = st["failures"].get(k, 0) + 1
            self.save()
            append_journal(self.journal, [self.line("slot_failed", f"slot_failed:{wid}:{k}:{st['failures'][k]}", t, warning_event_id=wid, seed=seed,
                                                    kind_of_failure=r["outcome"], detail=r.get("detail"), attempt=st["failures"][k])])
            if r["outcome"] == "defect":
                self.stop(f"{t} seed {seed}: {r.get('detail')}")
            if st["failures"][k] >= MAX_FAILS:
                self.stop(f"{t} seed {seed}: {st['failures'][k]} transport failures: {r.get('detail')}")
            raise Halt(6, f"{t} seed {seed}: transport failure {st['failures'][k]}: {r.get('detail')}")
        ok = {}
        for k, s in st["slots"].items():
            if s.get("result"):
                body = json.loads(Path(s["result"]).read_text(encoding="utf-8"))
                if str(body.get("status", "")).startswith("ok"):
                    ok[k] = body
        if ok:                                                            # e. the value, by name_entry's own rules
            try:
                c = self.consensus(pn, fields, ok, anchors, closure)
            except Exception as ex:  # noqa: BLE001  a consensus that cannot be computed offline is a code defect
                self.stop(f"{t}: consensus failed: {type(ex).__name__}: {ex}")
        else:
            c = {"status": "no_call", "reason": sorted({f"{s.get('status')}:{s.get('reason')}" for s in st["slots"].values()}), "values": {}}
        e = FF.name_entry("fv_held", t, {"names": {t: {"slots": st["slots"], "market_cap": moved}}}, {"names": {t: c}})
        commits = sorted({s["git"] for s in st["slots"].values() if s.get("git")})
        formation_git = idx.get("git")
        obj.update(slots=st["slots"], code_commit=commits[0] if commits else None, consensus_status=c.get("status"),
                   consensus_annotations=list(c.get("annotations") or [])
                   + (["code_moved_between_seeds"] if len(commits) > 1 else [])
                   + (["code_differs_from_formation_valuations"] if formation_git and commits and commits != [formation_git] else []),
                   value_base=e["value_base"], shares=e["shares"], equity_value=e["equity_value"], cheapness=e["cheapness"],
                   reason=None if e["valued"] else e["reason"])
        if not e["valued"] or (self.cut is not None and e["cheapness"] < self.cut):    # f. no value, or below the cut: out; no cut: stays
            return "decided", "revalued_not_cheap", obj
        return "decided", "revalued_stays", obj

    def guard(self, anchors, closure, pk):
        """Before every slot: the pinned folders (7), a formation with work left or a busy GPU (4), changed tracked files (6)."""
        if not anchors.is_dir() or not closure.is_file():
            self.stop(f"the formation's pinned folders are missing ({anchors}, {closure})")
        if sha256_file(pk["packet"]) != pk["file_sha256"]:
            self.stop(f"the packet {pk['packet']} changed since it was built")
        if not self.have_value_lock:
            if not self.lock_value():
                raise Halt(4, "formation_value's value.lock is held: yielding")
            self.have_value_lock = True
        if self.waiting():
            raise Halt(4, "a formation has Q1 work left: yielding the GPU")
        ok, why = self.gpu()
        if not ok:
            raise Halt(4, f"GPU busy or unreadable: {why}")
        if self.dirty():
            raise Halt(6, "the tracked files of the repository have changed")

    def journal_once(self, kind, event_id, ticker, **fields):
        append_journal(self.journal, [self.line(kind, event_id, ticker, **fields)])


def run_pass(root, *, value_dir=VALUE, checks_dir=M.CHECKS_DIR, screener_repo=M.SCREENER_REPO, worktree=M.WORKTREE, dry_run=False, engine=None,
             build=None, slot=None, consensus=None, prices=None, gpu=None, waiting=None, dirty=None, lock_value=None, unlock_value=None, clock=None):
    """One pass (module docstring). Everything outside is injectable: engine() -> view_from_lines' dict; build(ticker, T, commit, check_file,
    screener_repo, cwd) -> {"packet", "packet_sha256", "builder_version"} or raises PacketRefused; slot(n, seed, fields, anchors, closure) ->
    real_slot's dict; consensus(n, fields, ok_results, anchors, closure) -> a consensus dict; prices(ticker) -> monitor.yf_prices' dict;
    gpu() -> (ok, why); waiting() -> bool (a formation has Q1 work left); dirty() -> text of changed tracked files, "" when clean;
    lock_value() -> bool and unlock_value() (formation_value's value.lock); clock() -> aware datetime.
    Returns {"exit", "notes", "decided", "covered", "waiting", "repaired", "planned"}."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    root = Path(root)
    rep = {"dry_run": bool(dry_run), "exit": 0, "notes": [], "decided": [], "covered": [], "waiting": [], "repaired": [], "planned": []}
    flag, lock = root / "state" / "fv_actions_STOP.flag", root / "state" / "fv_actions.lock"
    if flag.exists():
        rep.update(exit=7, notes=[f"stop flag present, a human must look: {flag.read_text(encoding='utf-8')}"])
        return rep
    if not dry_run:
        try:
            M.take_lock(lock)
        except M.LockHeld as e:
            rep.update(exit=3, notes=[str(e)])
            return rep
    p = None
    try:
        try:
            view = (engine or (lambda: real_engine(value_dir)))()
        except Exception as e:  # noqa: BLE001  the engine stopped or raised: nothing is written
            rep.update(exit=2, notes=[f"the engine could not be read: {type(e).__name__}: {e}"])
            return rep
        if view["T"] is None:
            rep["notes"].append("FV holds nothing")
            return rep
        p = Pass(root, value_dir, view, checks_dir=checks_dir, screener_repo=screener_repo, worktree=worktree, build=build or M.qwen_build_packet,
                 slot=slot or real_slot, consensus=consensus or real_consensus, prices=prices or (lambda t: M.yf_prices(t, now=clock())),
                 gpu=gpu or FVAL.gpu_ok, waiting=waiting or FR.formation_waiting, dirty=dirty or real_dirty,
                 lock_value=lock_value or FVAL.take_lock, unlock_value=unlock_value or FVAL.release_lock, clock=clock)
        _work(p, rep, dry_run)
    except Halt as h:
        rep.update(exit=h.code)
        rep["notes"].append(h.why)
    finally:
        if p is not None and p.have_value_lock:
            p.unlock_value()
        if not dry_run:
            M.release_lock(lock)
    return rep


def _work(p, rep, dry_run):
    journal = M._jsonl(p.journal)
    rep["repaired"] = p.repair(journal, dry_run)
    handled = {l["warning_event_id"] for l in journal if l.get("kind") in ("decided", "covered") and l.get("warning_event_id")}
    cands = p.candidates(M._jsonl(p.root / "journal.jsonl"), handled)
    if p.view["pending_T"]:                                               # a newer decision is about to be priced: its fill would supersede any exit
        for w in cands:
            rep["waiting"].append(w["event_id"])
            if not dry_run:
                p.journal_once("waiting", f"waiting:{w['event_id']}:{p.clock().date().isoformat()}", w["ticker"], warning_event_id=w["event_id"],
                               reason="decision_not_priced", pending_formation_T=p.view["pending_T"])
        if cands:
            rep["notes"].append(f"{len(cands)} warning(s) wait for the decision at {p.view['pending_T']} to be priced")
        return
    by_ticker = {}
    for w in cands:
        by_ticker.setdefault(w["ticker"], []).append(w)
    for t in sorted(by_ticker):
        ws = sorted(by_ticker[t], key=lambda w: (M.parse_utc(w["decision_time_utc"]), w["event_id"]))
        if (p.T, t) in p.exit_keys:
            rep["covered"] += [w["event_id"] for w in ws]
            if not dry_run:
                append_journal(p.journal, [p.covered(w, "already_exiting") for w in ws])
            continue
        news = [w for w in ws if w["warning_kind"] == "news_event"]
        target = (news or ws)[-1]
        others = [w for w in ws if w is not target]
        if dry_run:
            rep["planned"].append({"ticker": t, "warning_event_id": target["event_id"], "action": "under_review" if news else "revalue", "covers": len(others)})
            continue
        if news:
            res = p.decide(target, others, "under_review", None, "covered_by_news_event")
        else:
            kind, outcome, obj = p.revalue(target)
            if kind == "wait":
                continue
            res = p.decide(target, others, outcome, obj, "covered_by_revaluation")
        rep["decided"].append(res)
        rep["covered"] += [w["event_id"] for w in others]


def format_pass(rep):
    out = [("dry run: nothing is run or written" if rep["dry_run"] else "fv_actions pass") + f", exit {rep['exit']}"]
    out += [f"  {n}" for n in rep["notes"]]
    out += [f"  repaired the exit record of {t}" for t in rep["repaired"]]
    out += [f"  would do: {x}" for x in rep["planned"]]
    out += [f"  decided {d['ticker']}: {d['outcome']} ({d['warning_event_id']})" for d in rep["decided"]]
    if rep["covered"]:
        out.append(f"  covered {len(rep['covered'])} warning(s)")
    if rep["waiting"]:
        out.append(f"  waiting {len(rep['waiting'])} warning(s)")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python fv_actions.py", description="The monitor's warnings act on paper book FV. Paper only.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="one pass")
    r.add_argument("--root", default=str(M.MONITOR_ROOT), help="the monitor's state folder")
    r.add_argument("--dry-run", action="store_true", help="print what would be done; write nothing, run no slot")
    a = ap.parse_args(argv)
    FVAL.STATE.mkdir(parents=True, exist_ok=True)
    rep = run_pass(a.root, dry_run=a.dry_run)
    print(format_pass(rep))
    return rep["exit"]


if __name__ == "__main__":
    sys.exit(main())

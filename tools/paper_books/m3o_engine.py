"""WO_O1: the 3O paper decision engine (SPEC_m3o_integration.md v1.1, PREREG_m3o.json v1.1). Paper only.

Usage: python m3o_engine.py [--ledger-dir DIR] [--inputs-dir DIR] [--forward-dir DIR] [--universe-dir DIR]
Folders default to <rs2_state_dir>/paper_books/{m3l_forward, m3o/...} (tools/paper_books/book_paths.py).
Reads   m3l_forward/formations.jsonl and the latest m3l_forward/prices/*.receipt.json (+ its csv);
        public/data/factor_scores.json of each formation's output_commit through `git show`;
        m3o/inputs/formation_<T>.json (WO_O2) and each run's manifest.json / analysis.json, each packet.json.
Writes  m3o/ledger/{formations,factor,qwen,verification,actions}.jsonl (append-only) and ledger/marks/<asof>.json.
Rerun:  every line is recomputed; a stored line that differs from its recomputation stops the engine with the line named.

Series: F (A0 equal weight, forward_ledger.py's arithmetic), FB (F minus B1), FQ (FB plus Q1, pending/incomplete slots cash),
FQ_decisions_only (analysis series: FB plus Q1, pending/incomplete filled as in FB), and F_ex_operator (marks only). They start at the
first contemporaneous formation that has a map, from cash. A map labelled "retrospective" is its own one-period group.
B1 is the deterministic text rule (3N baseline B); it is never called verified.
"""
import argparse, csv, hashlib, io, json, math, re, statistics, subprocess, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True      # write no __pycache__ beside the code
sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths            # noqa: E402  (where the books live: paths.py rs2_state_dir)
import baseline_b            # noqa: E402  (3N baseline B, unchanged)
import forward_ledger as fl  # noqa: E402  (A0 formations, calendar, period_return; unchanged)
import universe as uni       # noqa: E402  (WO_S1: the universe records and prices for the U benchmark in the marks)

ENGINE_VERSION = "m3o_engine.v2"
ENGINE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SCHEMA = "m3o.decision.v1"
PREREG_M3O = book_paths.prereg("PREREG_m3o.json")   # frozen copy in rs2-state; its sha256 is on every line and checked by the stop rule
BOOKS = book_paths.books()
WINDOW_DAYS = 180                    # PREREG B1 item_window_days_before_T and Q1 occurred_on window
TOL = 1e-6                           # float tolerance of the stop rule (price-fetch noise); see RR_O1
POST_3N_FIRST_FORMATION = "2026-11-30"  # 3N closed 2026-10-31 (CLOSE_3N); first formation labelled paper_post_3N
B1_NAME = "B1 deterministic text rule (3N baseline B)"
NY = ZoneInfo("America/New_York")
SERIES = ("F", "FB", "FQ", "FQ_decisions_only")          # series that have action lines
ALL_SERIES = SERIES + ("F_ex_operator",)
LINE_FILES = ("formations", "factor", "qwen", "verification", "actions")
KEYS = {"formations": lambda l: (l["formation_T"],),
        "factor": lambda l: (l["formation_T"], l["ticker"]),
        "qwen": lambda l: (l["formation_T"], l["ticker"], l["kind"]),
        "verification": lambda l: (l["formation_T"], l["ticker"], l["kind"]),
        "actions": lambda l: (l["formation_T"], l["ticker"], l["arm"], l["kind"])}


class Stop(Exception):
    """The engine stops; the message names what and why."""


# ---------------------------------------------------------------- book accounting (quarterly-capable; after baselineA/m3_quarterly.py)

def is_rebalance_month(asof, initialized):
    """Quarterly cadence (Mar/Jun/Sep/Dec month-end, and the first month). The engine's series rebalance at every formation (SPEC_m3o);
    this and `target=None` of monthly_step are the quarterly capability PLAN 3O item 4 asks for, tested on fixtures."""
    return not initialized or int(asof[5:7]) in (3, 6, 9, 12)


def monthly_step(pre, returns, target):
    """Rebalance at the start of the period, then let positions drift. A None target means no order. CASH accrues 0%; 0.0 is a value."""
    if not pre or not all(math.isfinite(float(v)) and v >= 0 for v in pre.values()):
        raise ValueError("invalid pre-trade weights")
    if abs(sum(pre.values()) - 1.0) > 1e-9:
        raise ValueError("pre-trade weights do not sum to one")
    orders = target is not None
    w = dict(target) if orders else dict(pre)
    if not w or any(not math.isfinite(float(v)) or v < 0 for v in w.values()):
        raise ValueError("invalid target")
    if abs(sum(w.values()) - 1.0) > 1e-9:
        raise ValueError("target weights do not sum to one")
    turnover = 0.5 * sum(abs(w.get(s, 0.0) - pre.get(s, 0.0)) for s in
                         set(pre) | set(w) if s != "CASH") if orders else 0.0
    contribution = {}
    for s, wt in w.items():
        if s == "CASH":
            contribution[s] = 0.0
        else:
            if s not in returns:
                raise ValueError(f"missing next-session total return: {s}")
            value = returns[s]
            if value is None or not math.isfinite(float(value)) or value < -1.0:
                raise ValueError(f"invalid next-session total return: {s}")
            contribution[s] = float(value)
    gross = sum(wt * contribution[s] for s, wt in w.items())
    total = 1.0 + gross
    if total <= 0:
        raise ValueError("book entirely lost, no valid next weight")
    post = {s: wt * (1.0 + contribution[s]) / total for s, wt in w.items()}
    return {"gross_ret": gross, "turnover": turnover, "post": post, "orders": orders, "pre": dict(pre), "target": w}


# ---------------------------------------------------------------- small helpers

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def parse_utc(s):
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def accepted_at(value):
    """SEC acceptanceDateTime as UTC, read as qwen_c packet.py reads it: a Z-labelled clock has been seen both as UTC and as Eastern
    wall clock mislabelled Z, so the LATER reading is used; a naive clock is Eastern. A copy of that rule (no cross-repository import)."""
    if not isinstance(value, str) or not value:
        raise ValueError("acceptanceDateTime missing")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NY).astimezone(timezone.utc)
    as_utc = dt.astimezone(timezone.utc)
    as_wall = dt.replace(tzinfo=None).replace(tzinfo=NY).astimezone(timezone.utc)
    return max(as_utc, as_wall)


_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_RES = (("iso", re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")),
             ("mdy", re.compile(r"(?<![A-Za-z])" + _MON + r"\.?\s+(\d{1,2})\s*,\s*(\d{4})(?!\d)", re.I)),   # "Month D, YYYY", "Mon. D, YYYY"
             ("dmy", re.compile(r"(?<!\d)(\d{1,2})\s+" + _MON + r"\.?\s+(\d{4})(?!\d)", re.I)))              # "D Month YYYY"


def scan_dates(text):
    """[(start, end, date)] of every date in text printed in one of the four forms (an impossible date is skipped)."""
    out = []
    for kind, rx in _DATE_RES:
        for m in rx.finditer(text or ""):
            g = m.groups()
            try:
                if kind == "iso":
                    d = date(int(g[0]), int(g[1]), int(g[2]))
                elif kind == "mdy":
                    d = date(int(g[2]), _MONTHS[g[0][:3].lower()], int(g[1]))
                else:
                    d = date(int(g[2]), _MONTHS[g[1][:3].lower()], int(g[0]))
            except ValueError:
                continue
            out.append((m.start(), m.end(), d))
    return out


def parse_occurred_on(value):
    """The date of a material_events `occurred_on` that is, in full, one date in one of the four forms; else None (missing)."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    found = [d for a, b, d in scan_dates(s) if a == 0 and b == len(s)]
    return found[0] if len(found) == 1 else None


def first_open_after(dt):
    """The first session date whose 09:30 New York open is strictly after dt (an aware datetime)."""
    d = dt.astimezone(NY).date()
    while not fl.session(d) or fl.open_utc(d) <= dt:
        d += timedelta(days=1)
    return d


def arm_label(arm, T, retro=False):
    if arm == "F":
        return "factor_only"
    if retro:
        return "retrospective"
    return "paper_post_3N" if POST_3N_FIRST_FORMATION and T >= POST_3N_FIRST_FORMATION else "shadow_pre_3N_close"


def git_factor_scores(commit):
    return subprocess.run(["git", "-C", str(fl.REPO), "show", f"{commit}:public/data/factor_scores.json"],
                          capture_output=True, check=True).stdout


# ---------------------------------------------------------------- inputs

def load_formations(forward_dir):
    out = []
    for line in (Path(forward_dir) / "formations.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append((json.loads(line), sha256_bytes(line.encode("utf-8"))))
    out.sort(key=lambda x: x[0]["formation_T"])
    if not out:
        raise Stop("formations.jsonl has no formation")
    return out


def load_prices(prices_dir):
    """The latest fetch receipt of prices_dir (its csv must hash to the receipt): ({ticker: {date: (adj_open, adj_close)}}, receipt)."""
    receipts = sorted(Path(prices_dir).glob("*.receipt.json"))
    if not receipts:
        raise Stop(f"no price receipt in {prices_dir}")
    rp = receipts[-1]
    receipt = json.loads(rp.read_text(encoding="utf-8"))
    raw = rp.with_name(rp.name.replace(".receipt.json", ".csv")).read_bytes()
    if sha256_bytes(raw) != receipt["sha256"]:
        raise Stop(f"{rp.name}: the csv does not hash to its receipt")
    px = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        px.setdefault(r["ticker"], {})[r["date"]] = (float(r["adj_open"]), float(r["adj_close"]))
    return px, receipt


def load_map(inputs_dir, rec):
    p = Path(inputs_dir) / f"formation_{rec['formation_T']}.json"
    if not p.exists():
        return None, None
    raw = p.read_bytes()
    m = json.loads(raw)
    for k in ("formation_T", "decision_time_utc", "run_id", "output_commit"):
        if m.get(k) is not None and m[k] != rec[k]:
            raise Stop(f"{p.name}: {k} {m[k]} is not the formation's {rec[k]}")
    if m.get("book") is not None and list(m["book"]) != list(rec["book"]):
        raise Stop(f"{p.name}: book differs from the stored A0 book")
    for e in (m.get("names") or {}).values():                      # a relative path is relative to the map's folder
        for k in ("packet", "run_dir"):
            if e.get(k) and not Path(e[k]).is_absolute():
                e[k] = str(Path(inputs_dir) / e[k])
    return m, sha256_bytes(raw)


def read_run(name, entry, decision_time_utc):
    """The run of one name: None (no run_dir), else {manifest, manifest_sha, finished (aware datetime or None), analysis (dict or None),
    analysis_sha, me_status, run_dir}. A finished run's analysis.json must hash to the manifest's analysis_sha256, else the engine refuses."""
    if not entry.get("run_dir"):
        return None
    d = Path(entry["run_dir"])
    mp = d / "manifest.json"
    if not mp.exists():
        raise Stop(f"{name}: {d} has no manifest.json")
    raw = mp.read_bytes()
    man = json.loads(raw)
    if man.get("ticker") != name or man.get("decision_time_utc") != decision_time_utc:
        raise Stop(f"{name}: manifest of {d} is for {man.get('ticker')} at {man.get('decision_time_utc')}, not {name} at {decision_time_utc}")
    info = {"manifest": man, "manifest_sha": sha256_bytes(raw), "finished": None, "analysis": None, "analysis_sha": None,
            "me_status": "absent", "run_dir": str(d)}
    if not man.get("finished_at"):
        return info                                  # running or crashed: not finished
    info["finished"] = parse_utc(man["finished_at"])
    if man.get("analysis_sha256"):
        ar = (d / "analysis.json").read_bytes()
        if sha256_bytes(ar) != man["analysis_sha256"]:
            raise Stop(f"{name}: analysis.json of {d} does not hash to the manifest's analysis_sha256 (refused)")
        info["analysis"], info["analysis_sha"] = json.loads(ar), man["analysis_sha256"]
        info["me_status"] = ((info["analysis"].get("tasks") or {}).get("material_events") or {}).get("status", "absent")
    return info


# ---------------------------------------------------------------- B1 and Q1

def b1(packet, T_date, compiled):
    """Baseline-B hits of a packet, each with the item's SEC acceptance (the evidence item's `accepted_raw`) and whether it acts
    (acceptance within 180 days before T)."""
    items = {e["fact_id"]: e for e in packet.get("evidence") or []}
    out = []
    for h in baseline_b.hits(packet, compiled):
        raw = items[h["fact_id"]].get("accepted_raw")
        try:
            acc = accepted_at(raw)
        except (ValueError, TypeError):
            out.append({**h, "accepted_raw": raw, "accepted_utc": None, "days_before_T": None, "acts": False, "reason": "b_hit_undated"})
            continue
        days = (T_date - acc.date()).days
        reason = "after_T" if days < 0 else ("within_180d" if days <= WINDOW_DAYS else "outside_window")
        out.append({**h, "accepted_raw": raw, "accepted_utc": acc.strftime("%Y-%m-%dT%H:%M:%SZ"), "days_before_T": days,
                    "acts": reason == "within_180d", "reason": reason})
    return out


def q1(analysis, T_date, type_to_class, items):
    """Q1 over a run's material_events claims. `items` is {fact_id: text} of the packet (None: no packet).
    {"restricted", "claims": [critical claims with acts/reason], "escalations": [claims undated / date_unsupported], "n_noncritical"}."""
    claims = ((analysis.get("tasks") or {}).get("material_events") or {}).get("claims") or []
    out, n_non = [], 0
    for c in claims:
        cls = type_to_class.get(c.get("event_type"))
        if cls is None:
            n_non += 1
            continue
        e = {"class": cls, "event_type": c.get("event_type"), "support": c.get("support"), "status": c.get("status"),
             "occurred_on": c.get("occurred_on"), "fact_ids": c.get("fact_ids"), "claim": (c.get("claim") or "")[:300]}
        if c.get("support") != "supported":
            e.update(acts=False, reason="unsupported_critical_claim")
        elif c.get("status") == "announced_pending":
            e.update(acts=True, reason="announced_pending")
        elif c.get("status") == "occurred":
            d = parse_occurred_on(c.get("occurred_on"))
            cited = [d2 for f in c.get("fact_ids") or [] for _, _, d2 in scan_dates((items or {}).get(f))]
            if d is None:
                e.update(acts=False, reason="undated", escalation=True)
            elif d not in cited:
                e.update(acts=False, reason="date_unsupported", escalation=True)
            else:
                days = (T_date - d).days
                reason = "occurred_on_after_T" if days < 0 else ("occurred_within_180d" if days <= WINDOW_DAYS else "occurred_outside_window")
                e.update(acts=reason == "occurred_within_180d", reason=reason, days_before_T=days)
        else:
            e.update(acts=False, reason="unknown_status")
        out.append(e)
    return {"restricted": any(e["acts"] for e in out), "claims": out, "n_noncritical": n_non,
            "escalations": [e for e in out if e.get("escalation")]}


def evaluate_name(name, entry, rec, T_date, fill_open, compiled, type_to_class):
    """Everything known about one name at a formation: B1, the analysis state at the fill open (a function of the run's finished_at only,
    so a stored line does not change when a pending run finishes later), and the later resolution (separate lines)."""
    packet, packet_sha, items = None, None, None
    if entry.get("packet"):
        raw = Path(entry["packet"]).read_bytes()
        packet, packet_sha = json.loads(raw), sha256_bytes(raw)
        if packet.get("ticker") != name:
            raise Stop(f"{name}: packet {entry['packet']} is for {packet.get('ticker')}")
        items = {e["fact_id"]: e.get("text") or "" for e in packet.get("evidence") or []}
    hits = b1(packet, T_date, compiled) if packet is not None else None
    info = read_run(name, entry, rec["decision_time_utc"])
    me_ok = bool(info and info["finished"] and info["me_status"] == "ok")
    complete = me_ok and info["finished"] <= fill_open
    commit = ((info or {}).get("manifest") or {}).get("qwen_c", {}).get("git_commit") if info else None
    ev = {"packet": entry.get("packet"), "packet_sha": packet_sha, "builder_code": (packet or {}).get("builder_code"),
          "hits": hits, "b1_restricted": any(h["acts"] for h in hits or []), "info": info, "qwen_c_commit": commit,
          "state": "complete" if complete else "analysis_pending", "q_fill": None, "resolution": None, "q_late": None,
          "partial_analysis": bool(me_ok and (info["manifest"].get("status") != "complete"))}
    if complete:
        ev["q_fill"] = q1(info["analysis"], T_date, type_to_class, items)
    elif me_ok:
        ev["q_late"] = q1(info["analysis"], T_date, type_to_class, items)
        ev["resolution"] = {"outcome": "completed_late", "entry_session": first_open_after(info["finished"])}
    elif info and info["finished"] and info["me_status"] == "malformed":
        ev["resolution"] = {"outcome": "analysis_incomplete", "cause": "material_events malformed"}
    elif entry.get("state") == "analysis_incomplete":
        ev["resolution"] = {"outcome": "analysis_incomplete", "cause": f"map state analysis_incomplete: {entry.get('reason')}"}
    return ev


# ---------------------------------------------------------------- plans (what each series holds at the fill)

def plan_book(series, book, excluded, pre, ev):
    """The plan of F / FB / FQ / FQ_decisions_only: {"positions": {t: w}, "slots": {t: {...}}, "cash"} and its decisions.
    A decision is (ticker, action, rule, reason, flags, causes)."""
    held = {t for t in pre if t != "CASH"}
    plan, dec = {"positions": {}, "slots": {}, "cash": 0.0}, []
    for t in book:
        if series != "F" and t in excluded:
            dec.append((t, "operator_excluded", "E1", "operator_excluded_ticker", [], []))
            continue
        was = t in held
        n = ev.get(t) if series != "F" else None
        causes = []
        if n is not None and n["b1_restricted"]:
            causes.append("B1")
        if series in ("FQ", "FQ_decisions_only") and n["state"] == "complete" and n["q_fill"]["restricted"]:
            causes.append("Q1")
        pending = series == "FQ" and n["state"] != "complete"
        flags = (["partial_analysis"] if n is not None and n["partial_analysis"] and n["state"] == "complete" and series in ("FQ", "FQ_decisions_only") else [])
        why = "+".join(B1_NAME if c == "B1" else c for c in causes)
        if causes and was:
            plan["positions"][t] = 0.0
            dec.append((t, "hold", "E1", "restricted_incumbent_held_no_sale: " + why,
                        ["pending_reunderwriting"] + flags + (["analysis_pending"] if pending else []), causes))
        elif causes:
            dec.append((t, "new_entry_restricted", "E1", "restricted_new_entry: " + why, flags, causes))
        elif pending and was:
            plan["positions"][t] = 0.0
            dec.append((t, "hold", "A1S", "incumbent_held_analysis_pending_no_sale", ["analysis_pending"], []))
        elif pending:
            res = n["resolution"]
            kind = "incomplete" if res and res["outcome"] == "analysis_incomplete" else "pending"
            entry = res["entry_session"] if res and res["outcome"] == "completed_late" and not n["q_late"]["restricted"] else None
            plan["slots"][t] = {"weight": 0.0, "entry": entry, "kind": kind}
            dec.append((t, "analysis_pending", "A1S", "slot_held_as_cash_no_completed_run_at_fill_open", [], []))
        else:
            plan["positions"][t] = 0.0
            dec.append((t, "hold" if was else "enter", "A0", "in_A0_book", flags, []))
    for t in sorted(held - set(book)):
        dec.append((t, "exit", "E1", "left_A0_book", [], []))
    n = len(plan["positions"]) + len(plan["slots"])
    for t in plan["positions"]:
        plan["positions"][t] = 1.0 / n
    for s in plan["slots"].values():
        s["weight"] = 1.0 / n
    cash = 1.0 - sum(plan["positions"].values()) - sum(s["weight"] for s in plan["slots"].values())
    plan["cash"] = 0.0 if abs(cash) < 1e-12 else cash
    return plan, dec


# ---------------------------------------------------------------- one period of one series

def ret_of(t, px, F, exit_F, last_day):
    r, log = fl.period_return([t], px, F, exit_F, last_day)
    return r[t], log


def arm_step(pre, plan, px, F, exit_F, last_day):
    """The period: rebalance to the plan at the fill open (monthly_step), entries of pending slots at their later open, drift to the exit.
    Turnover is one-way from the drifted pre-trade weights, CASH excluded; a missing price is a 0.0 return (held as cash)."""
    pos, rets, events = plan["positions"], {}, []
    for t in pos:
        rets[t], log = ret_of(t, px, F, exit_F, last_day)
        events += log
    cash_target = plan["cash"] + sum(s["weight"] for s in plan["slots"].values())
    target = dict(pos)
    if cash_target > 1e-12:
        target["CASH"] = cash_target
    try:
        s = monthly_step(pre, rets, target)
    except ValueError as e:
        raise Stop(f"book accounting: {e}")
    gross, turnover = s["gross_ret"], s["turnover"]
    entered, cash, drag = {}, plan["cash"], {"pending": 0.0, "incomplete": 0.0}
    for t, sl in plan["slots"].items():
        d, r = sl["entry"], 0.0
        if d is not None and d <= last_day and (exit_F is None or d < exit_F):
            r, log = ret_of(t, px, d, exit_F, last_day)
            events += log
            entered[t] = (sl["weight"], r)
            gross += sl["weight"] * r
            turnover += 0.5 * sl["weight"]
        else:
            cash += sl["weight"]
        r_fill, _ = ret_of(t, px, F, exit_F, last_day)
        drag[sl["kind"]] += sl["weight"] * (r_fill - r)
    total = 1.0 + gross
    if total <= 0:
        raise Stop("a book is entirely lost; no valid next weight")
    post = {t: w * (1.0 + rets[t]) / total for t, w in pos.items()}
    post.update({t: w * (1.0 + r) / total for t, (w, r) in entered.items()})
    if cash > 1e-12:
        post["CASH"] = cash / total
    return {"gross": gross, "turnover": turnover, "post": post, "events": events, "rets": rets, "drag": drag,
            "n": len(pos) + len(entered), "n_cash_slots": len(plan["slots"]) - len(entered), "cash_weight": cash}


def period_record(rec, F, exit_F, last_day, step, spy, label, extra=None):
    g, to = step["gross"], step["turnover"]
    out = {"formation_T": rec["formation_T"], "fill": F.isoformat(), "exit": exit_F.isoformat() if exit_F else f"OPEN (marked {last_day})",
           "label": label, "n": step["n"], "n_cash_slots": step["n_cash_slots"], "cash_weight_at_fill": step["cash_weight"],
           "gross": g, "turnover_one_way": to, "cost_drag_20bp": to * 20 / 1e4,
           **{f"net_{c}bp": g - to * c / 1e4 for c in fl.COSTS_BP},
           "cash_drag_pending": step["drag"]["pending"], "cash_drag_incomplete": step["drag"]["incomplete"],
           "no_price_series": [{"ticker": e["ticker"], "flag": "no_price_series", "event": e["event"],
                                **({"date": e["date"]} if "date" in e else {})} for e in step["events"]], "spy": spy}
    if step["rets"]:
        out["best"], out["worst"] = max(step["rets"], key=step["rets"].get), min(step["rets"], key=step["rets"].get)
    out.update(extra or {})
    return out


def summarize(periods):
    """Cumulative gross/net, max drawdown, volatility and SPY excess over a list of period records."""
    def cum(vals):
        v = 1.0
        for x in vals:
            v *= 1.0 + x
        return v - 1.0

    def mdd(vals):
        eq, peak, worst = 1.0, 1.0, 0.0
        for x in vals:
            eq *= 1.0 + x
            peak = max(peak, eq)
            worst = min(worst, eq / peak - 1.0)
        return worst
    out = {"periods": len(periods), "cumulative_gross": cum([p["gross"] for p in periods]),
           "cumulative_spy": cum([p["spy"] for p in periods]), "turnover_one_way_sum": sum(p["turnover_one_way"] for p in periods),
           "cash_drag_pending_sum": sum(p["cash_drag_pending"] for p in periods),
           "cash_drag_incomplete_sum": sum(p["cash_drag_incomplete"] for p in periods),
           "max_drawdown_gross": mdd([p["gross"] for p in periods])}
    for c in fl.COSTS_BP:
        vals = [p[f"net_{c}bp"] for p in periods]
        out[f"cumulative_net_{c}bp"] = cum(vals)
        out[f"cumulative_net_{c}bp_excess_spy"] = cum(vals) - out["cumulative_spy"]
        out[f"max_drawdown_net_{c}bp"] = mdd(vals)
    nets = [p["net_20bp"] for p in periods]
    out["volatility_net_20bp"] = statistics.stdev(nets) if len(nets) >= 2 else "not_estimable"
    out["factor_adjusted"] = "not_estimable" if len(periods) < 12 else "not_computed"
    out["not_yet_validated"] = True
    return out


def universe_period(universe_dir, rec, F, exit_F, spy, pre):
    """WO_S1: one period of U, the equal-weight benchmark of the screener's investable universe at the formation (universe.py), on the
    same fill, exit and cost scenarios as the arms. Returns (period record, coverage row, drifted weights, inputs) or
    (None, reason, None, None) when the formation has no universe record or prices. A name with no bar is held as cash at 0%."""
    T = rec["formation_T"]
    try:
        urec, usha = uni.load_record(universe_dir, T)
        upx, ureceipt = uni.load_prices(universe_dir, T)
    except uni.UniverseError as e:
        raise Stop(str(e))
    if urec is None or upx is None:
        return None, "no universe record" if urec is None else "no universe price receipt", None, None
    if urec["output_commit"] != rec["output_commit"] or urec["fill_session"] != rec["fill_session"]:
        raise Stop(f"universe_{T}.json is for commit {urec['output_commit']}, not the formation's {rec['output_commit']}")
    names = urec["tickers"]
    ulast = date.fromisoformat(max(d for s in upx.values() for d in s))
    if not names or ulast < F:
        return None, "no universe names" if not names else f"universe prices end {ulast} before the fill {F}", None, None
    plan = {"positions": {t: 1.0 / len(names) for t in names}, "slots": {}, "cash": 0.0}
    step = arm_step(pre, plan, upx, F, exit_F, ulast)
    n_priced = sum(1 for t in names if F.isoformat() in upx.get(t, {}))
    extra = {"n_universe": len(names), "n_with_price_at_fill": n_priced, "universe_asof_price_date": ulast.isoformat()}
    cov = {"formation_T": T, "n_universe": len(names), "n_with_price_at_fill": n_priced, "U_coverage": n_priced / len(names)}
    return (period_record(rec, F, exit_F, ulast, step, spy, "universe_benchmark", extra), cov, step["post"],
            ({"sha256": usha, "n_universe": urec["n_universe"], "excluded_operator_count": urec["excluded_operator"]["count"],
              "field": urec["field"]}, ureceipt))


# ---------------------------------------------------------------- the stop rule

IGNORED_INPUTS = ("prices", "inputs_map")     # a new price fetch or a WO_O2 map update must not stop a decision already stored


def _norm(line):
    d = {k: v for k, v in line.items() if k not in ("engine_version", "engine_sha256")}
    if isinstance(d.get("inputs"), dict):
        d["inputs"] = {k: v for k, v in d["inputs"].items() if k not in IGNORED_INPUTS}
    return d


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= TOL
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def reconcile(path, name, new_lines):
    """The lines of `new_lines` not yet stored in path; a stored line that differs from its recomputation (or has none) stops."""
    path = Path(path)
    stored = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                l = json.loads(ln)
                k = KEYS[name](l)
                if k in stored:
                    raise Stop(f"{name}.jsonl: duplicate stored line {k}")
                stored[k] = l
    seen, fresh = set(), []
    for l in new_lines:
        k = KEYS[name](l)
        seen.add(k)
        if k not in stored:
            fresh.append(l)
        elif not same(_norm(stored[k]), _norm(json.loads(json.dumps(l)))):
            raise Stop(f"{name}.jsonl: stored line {k} differs from its recomputation; the ledger is append-only")
    for k in stored:
        if k not in seen:
            raise Stop(f"{name}.jsonl: stored line {k} has no recomputation (an input is missing or changed)")
    return fresh


def append_lines(path, lines):
    if lines:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            for l in lines:
                f.write(json.dumps(l, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- the engine

def stamp():
    return {"schema": SCHEMA, "engine_version": ENGINE_VERSION, "engine_sha256": ENGINE_SHA256}


def qwen_fields(info, rec):
    man, an = info["manifest"], info["analysis"] or {}
    return {"run_id": man.get("run_id"), "run_dir": info["run_dir"], "manifest_sha256": info["manifest_sha"],
            "analysis_sha256": info["analysis_sha"], "run_status": man.get("status"), "finished_at": man.get("finished_at"),
            "finished_at_clock": "self_claim_of_the_runner", "model": (man.get("model") or {}).get("tag"),
            "prompt_version": man.get("prompt_version"), "contract": man.get("contract"),
            "packet_builder_version": man.get("builder_version"),
            "task_statuses": {k: (v or {}).get("status") for k, v in (an.get("tasks") or {}).items()},
            "latency_hours_from_T": round((info["finished"] - parse_utc(rec["decision_time_utc"])).total_seconds() / 3600.0, 4)}


def action_line(rec, inputs, series, t, action, rule, reason, flags, pre, plan, prov, retro, causes=()):
    line = {**stamp(), "inputs": inputs, "kind": "at_fill_open", "formation_T": rec["formation_T"], "fill_session": rec["fill_session"],
            "ticker": t, "arm": series, "action": action, "rule": rule, "reason": reason, "flags": flags,
            "weight_before": pre.get(t, 0.0), "weight_target": plan["positions"].get(t, 0.0),
            "label": arm_label(series, rec["formation_T"], retro), **prov}
    if t in plan["slots"]:
        line["slot_weight"] = plan["slots"][t]["weight"]
    if causes:
        line["causes"] = list(causes)
    return line


def run(forward_dir, inputs_dir, ledger_dir, factor_loader=None, prices_dir=None, prereg_path=None, universe_dir=None):
    """Recompute everything from the inputs: (lines per file, marks). Writes nothing. universe_dir (WO_S1) adds the U benchmark to the marks."""
    forward_dir = Path(forward_dir)
    factor_loader = factor_loader or git_factor_scores
    prereg_raw = Path(prereg_path or PREREG_M3O).read_bytes()
    type_to_class = {v: k for k, v in json.loads(prereg_raw)["rules"]["Q1"]["event_types"].items()}
    compiled = baseline_b.rules()
    forms = load_formations(forward_dir)
    px, receipt = load_prices(prices_dir or forward_dir / "prices")
    last_day = date.fromisoformat(max(d for s in px.values() for d in s))
    base_inputs = {"prereg_m3o": sha256_bytes(prereg_raw), "prices": receipt["sha256"]}
    L = {k: [] for k in LINE_FILES}
    state = {}                               # group -> series -> drifted weights
    periods = {}                             # group -> series -> [period records]
    main_started = False
    u_state, u_periods, u_cov, u_broken, u_in, u_rec = {}, {}, {}, {}, {}, {}      # WO_S1, per group

    for i, (rec, line_sha) in enumerate(forms):
        T, F = rec["formation_T"], date.fromisoformat(rec["fill_session"])
        mp, mp_sha = load_map(inputs_dir, rec)
        retro = bool(mp and mp.get("label") == "retrospective")
        if mp is None:
            if main_started:
                raise Stop(f"{T}: no inputs map, but the contemporaneous series started at an earlier formation")
            continue                                          # before the first contemporaneous formation: nothing to compute
        group = f"retrospective_{T}" if retro else "main"
        main_started = main_started or not retro
        pre = state.setdefault(group, {s: {"CASH": 1.0} for s in ALL_SERIES})
        per = periods.setdefault(group, {s: [] for s in ALL_SERIES})
        exit_F = date.fromisoformat(forms[i + 1][0]["fill_session"]) if i + 1 < len(forms) else None
        T_date, fill_open = parse_utc(rec["decision_time_utc"]).date(), fl.open_utc(F)
        fs_raw = factor_loader(rec["output_commit"])
        fs = json.loads(fs_raw)["tickers"]
        if sorted(t for t, v in fs.items() if v.get("fct_band") == "research_now") != list(rec["book"]):
            raise Stop(f"{T}: research_now of factor_scores.json at {rec['output_commit']} is not the stored A0 book")
        inputs = {**base_inputs, "formation_line": line_sha, "factor_scores": sha256_bytes(fs_raw), "inputs_map": mp_sha}
        book, excluded = list(rec["book"]), fl.OPERATOR_EXCLUDED
        ev = {}
        for t in book:
            if t in excluded:
                continue
            if t not in (mp.get("names") or {}):
                raise Stop(f"{T}: inputs map has no entry for A0 name {t}")
            ev[t] = evaluate_name(t, mp["names"][t], rec, T_date, fill_open, compiled, type_to_class)
        spy, _ = ret_of("SPY", px, F, exit_F, last_day)

        held_prev = {s: {t for t in pre[s] if t != "CASH"} for s in SERIES}
        for t in sorted(set(book) | set().union(*held_prev.values())):
            v = fs.get(t) or {}
            L["factor"].append({**stamp(), "inputs": inputs, "formation_T": T, "ticker": t, "in_A0_book": t in book,
                                "band": v.get("fct_band"), "doors": v.get("fct_nominated_doors"), "rank": v.get("fct_rank"),
                                "veto": v.get("fct_veto"), "fct_flags": v.get("fct_flags"),
                                "held_at_prior_formation": {s: t in held_prev[s] for s in SERIES}})
        L["formations"].append({**stamp(), "inputs": inputs, "formation_T": T, "fill_session": rec["fill_session"],
                                "decision_time_utc": rec["decision_time_utc"], "run_id": rec["run_id"],
                                "output_commit": rec["output_commit"], "verifier_verdict": (rec.get("verifier") or {}).get("verdict"),
                                "book_size": len(book), "builder_version": mp.get("builder_version"), "group": group,
                                "a0_book_ref": {"file": "m3l_forward/formations.jsonl", "formation_line_sha256": line_sha,
                                                "book_sha256": sha256_bytes(json.dumps(book).encode("utf-8"))},
                                "label": arm_label("FQ", T, retro)})

        # qwen, verification and escalation lines (fill-open lines hold only what a later finish cannot change)
        for t, n in ev.items():
            info, comp = n["info"], n["state"] == "complete"
            prov_fill = {"qwen_c_commit": n["qwen_c_commit"] if comp else None, "builder_code": n["builder_code"]}
            qbase = {**stamp(), "formation_T": T, "ticker": t, "builder_version": mp.get("builder_version"),
                     "decision_time_utc": rec["decision_time_utc"], "inputs": {**inputs, "packet": n["packet_sha"]}, **prov_fill}
            vbase = {**stamp(), "formation_T": T, "ticker": t, "inputs": {**inputs, "packet": n["packet_sha"],
                                                                       "analysis": info["analysis_sha"] if comp else None}, **prov_fill}
            b = {"rule": B1_NAME, "evaluated": n["hits"] is not None, "restricted": n["b1_restricted"], "hits": n["hits"] or []}
            if n["hits"] is None:
                b["note"] = "no_packet: B1 not evaluated"
            if comp:
                L["qwen"].append({**qbase, "kind": "at_fill_open", "analysis_state": "complete",
                                  "flags": ["partial_analysis"] if n["partial_analysis"] else [], **qwen_fields(info, rec)})
            else:
                L["qwen"].append({**qbase, "kind": "at_fill_open", "analysis_state": "analysis_pending",
                                  "note": "no completed material_events run finished by the fill open"})
            L["verification"].append({**vbase, "kind": "at_fill_open", "b1": b,
                                      "q1": n["q_fill"] if comp else {"verdict": "analysis_pending"}})
            res, q = n["resolution"], n["q_fill"] if comp else n["q_late"]
            if res:
                prov_late = {"qwen_c_commit": n["qwen_c_commit"], "builder_code": n["builder_code"]}
                late = res["outcome"] == "completed_late"
                L["qwen"].append({**qbase, **prov_late, "kind": "completion", "analysis_state": res["outcome"],
                                  "flags": ["partial_analysis"] if n["partial_analysis"] else [],
                                  **({"entry_session": res["entry_session"].isoformat(), **qwen_fields(info, rec)} if late
                                     else {"cause": res["cause"]})})
                if late:
                    L["verification"].append({**vbase, **prov_late, "kind": "completion", "b1": b, "q1": n["q_late"],
                                              "inputs": {**vbase["inputs"], "analysis": info["analysis_sha"]}})
            if q and q["escalations"]:
                L["actions"].append({**stamp(), "inputs": inputs, "kind": "escalation", "formation_T": T, "fill_session": rec["fill_session"],
                                     "ticker": t, "arm": "FQ", "action": "escalation", "rule": "Q1",
                                     "reason": "+".join(sorted({e["reason"] for e in q["escalations"]})), "series_effect": "none",
                                     "queue": "3P reanalysis", "claims": q["escalations"], "label": arm_label("FQ", T, retro),
                                     "qwen_c_commit": n["qwen_c_commit"], "builder_code": n["builder_code"]})

        # the series
        for s in SERIES:
            plan, dec = plan_book(s, book, excluded, pre[s], ev)
            for (t, action, rule, reason, flags, causes) in dec:
                n = ev.get(t)
                prov = {} if s == "F" or n is None else {"qwen_c_commit": n["qwen_c_commit"] if n["state"] == "complete" else None,
                                                         "builder_code": n["builder_code"]}
                L["actions"].append(action_line(rec, inputs, s, t, action, rule, reason, flags, pre[s], plan, prov, retro, causes))
            for t, sl in plan["slots"].items():
                n, res = ev[t], ev[t]["resolution"]
                if res is None:
                    continue
                if res["outcome"] == "completed_late":
                    restricted = n["q_late"]["restricted"]
                    act, rule = ("new_entry_restricted", "Q1") if restricted else ("enter_after_pending", "A1S")
                    rsn = "Q1 restricted at completion; slot stays cash" if restricted else \
                        "entered at the first open after finished_at (self-claim clock)"
                else:
                    act, rule, rsn = "analysis_incomplete", "A1S", res["cause"] + "; slot stays cash to the next formation"
                line = action_line(rec, inputs, s, t, act, rule, rsn, [], pre[s], plan,
                                   {"qwen_c_commit": n["qwen_c_commit"], "builder_code": n["builder_code"]}, retro)
                line.update(kind="pending_resolution", weight_target=0.0, effective_session=res["entry_session"].isoformat()
                            if act == "enter_after_pending" else None)
                L["actions"].append(line)
            step = arm_step(pre[s], plan, px, F, exit_F, last_day)
            extra = {}
            if s != "F":
                extra["restriction_outcomes"] = [
                    {"ticker": t, "causes": c, "name_return": ret_of(t, px, F, exit_F, last_day)[0], "arm_gross": step["gross"]}
                    for (t, a, _, _, _, c) in dec if a == "new_entry_restricted"]
            per[s].append(period_record(rec, F, exit_F, last_day, step, spy, arm_label(s, T, retro), extra))
            pre[s] = step["post"]
        ex_book = [t for t in book if t not in excluded]
        ex_plan = {"positions": {t: 1.0 / len(ex_book) for t in ex_book}, "slots": {}, "cash": 0.0}
        step = arm_step(pre["F_ex_operator"], ex_plan, px, F, exit_F, last_day)
        per["F_ex_operator"].append(period_record(rec, F, exit_F, last_day, step, spy, "factor_only"))
        pre["F_ex_operator"] = step["post"]
        if universe_dir is not None and group not in u_broken:
            up, cov, post, uin = universe_period(universe_dir, rec, F, exit_F, spy, u_state.get(group, {"CASH": 1.0}))
            if up is None:
                u_broken[group] = {"formation_T": T, "reason": cov}           # the drift chain is broken: no U for this group
            else:
                u_state[group] = post
                u_periods.setdefault(group, []).append(up)
                u_cov.setdefault(group, []).append(cov)
                u_in[T], u_rec[T] = uin

    groups = {}
    for g, per in periods.items():
        sm = {s: summarize(p) for s, p in per.items() if p}
        cmp = {}
        for c in ("gross", "net_20bp"):
            key = "cumulative_" + c
            cmp.update({f"FB_minus_F_{c}": sm["FB"][key] - sm["F"][key],
                        f"FQ_decisions_only_minus_FB_{c}": sm["FQ_decisions_only"][key] - sm["FB"][key],
                        f"FQ_minus_FQ_decisions_only_{c}": sm["FQ"][key] - sm["FQ_decisions_only"][key]})
        groups[g] = {"series": {s: {"periods": p, "summary": sm[s]} for s, p in per.items() if p}, "comparisons": cmp}
        if g in u_broken:
            groups[g]["U_unavailable"] = u_broken[g]
        elif g in u_periods:
            sm_u = summarize(u_periods[g])
            groups[g]["series"]["U"] = {"periods": u_periods[g], "summary": sm_u}
            groups[g]["U_coverage"] = u_cov[g]
            for c in ("gross", "net_20bp"):
                groups[g]["comparisons"][f"F_minus_U_{c}"] = sm["F"]["cumulative_" + c] - sm_u["cumulative_" + c]
            if u_periods[g][-1]["universe_asof_price_date"] != last_day.isoformat():
                groups[g]["U_asof_mismatch"] = {"F_asof_price_date": last_day.isoformat(),
                                                "U_asof_price_date": u_periods[g][-1]["universe_asof_price_date"]}
    marks = {"schema": SCHEMA, "asof_price_date": last_day.isoformat(), "price_receipt": receipt, "groups": groups,
             "caveat": "paper only; Yahoo adjusted prices; FB, FQ and FQ_decisions_only are shadow measurement series, F is the paper book "
                       "of record; not_yet_validated: no skill is claimed"}
    if u_in:
        marks["universe_records"] = {T: u_in[T] for T in sorted(u_in)}
        marks["universe_receipts"] = {T: u_rec[T] for T in sorted(u_rec)}
    return L, marks


def write_ledger(L, marks, ledger_dir):
    """Reconcile every file first (any difference stops before anything is written), then append what is new."""
    ledger_dir = Path(ledger_dir)
    fresh = {k: reconcile(ledger_dir / f"{k}.jsonl", k, L[k]) for k in LINE_FILES}
    mp = ledger_dir / "marks" / f"{marks['asof_price_date']}.json"
    new_marks = True
    if mp.exists():
        old = json.loads(mp.read_text(encoding="utf-8"))
        if not same({k: v for k, v in old.items() if k not in ("price_receipt", "universe_receipts")},
                    json.loads(json.dumps({k: v for k, v in marks.items() if k not in ("price_receipt", "universe_receipts")}))):
            raise Stop(f"marks/{mp.name} differs from its recomputation; the ledger is append-only")
        new_marks = False
    for k in LINE_FILES:
        append_lines(ledger_dir / f"{k}.jsonl", fresh[k])
    if new_marks:
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(marks, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8", newline="\n")
    return {k: len(v) for k, v in fresh.items()}, new_marks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger-dir", default=str(BOOKS / "m3o" / "ledger"))
    ap.add_argument("--inputs-dir", default=str(BOOKS / "m3o" / "inputs"))
    ap.add_argument("--forward-dir", default=str(fl.HERE))
    ap.add_argument("--universe-dir", default=str(BOOKS / "m3o" / "universe_prices"))
    a = ap.parse_args()
    try:
        L, marks = run(a.forward_dir, a.inputs_dir, a.ledger_dir, universe_dir=a.universe_dir)
        if not marks["groups"]:
            print("no formation with an inputs map yet: nothing to compute")
            return
        counts, new_marks = write_ledger(L, marks, a.ledger_dir)
    except Stop as e:
        sys.exit(f"STOP: {e}")
    print("appended", counts, "marks written" if new_marks else "marks unchanged")
    for g, d in marks["groups"].items():
        for s, x in d["series"].items():
            sm = x["summary"]
            print(g, s, "periods", sm["periods"], "cum gross", round(sm["cumulative_gross"], 4), "net20",
                  round(sm["cumulative_net_20bp"], 4), "SPY", round(sm["cumulative_spy"], 4))


if __name__ == "__main__":
    main()

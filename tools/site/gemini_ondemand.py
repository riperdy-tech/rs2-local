"""gemini_ondemand.py - the screener list analysed with Gemini answering in Qwen's place (operator 2026-11-16).

    python tools/site/gemini_ondemand.py [--arm gemini|opus] work [--max-names N] [--no-publish]   # one worker per arm, no GPU
    python tools/site/gemini_ondemand.py [--arm gemini|opus] build | publish | status | meter

A name is analysed exactly as qwen_ondemand analyses it (the same packet builder, reading run, family, valuation at seeds
1000 and 3000, value of record and report), with one thing replaced in this process: the function that sends a request to
the model. It sends the same system and user messages to Gemini 4 Hydrogen at high effort through the `agy` command and
hands the reply back in Ollama's shape, so the parsing, the quote check, the valuation checks and the arithmetic are the
same code. No GPU is used. Everything is written under cache/gemini_site, cache/m3m and cache/m3q of THIS checkout.

Pacing: before every name and after any failed call the worker reads the account's own meter (`agy -p /usage`) and waits
for the reset when the five-hour or the weekly allowance left is under its floor. Thinking effort is never lowered.

Two arms share the list for the first fill (operator 2026-11-16: "consider using claude as well for a faster baseline
fill"): `gemini` (Gemini 4 Hydrogen through agy, from the top of the list) and `opus` (Claude Opus 5.5 through the Claude
Code command line on the Claude subscription, from the bottom). Both run at high effort with the same messages; a name is
claimed before it is started so the two never analyse the same one; each report records its model. Each arm paces itself
on its own account's meter. The opus arm leaves a small margin for the coordinating session on the same subscription.

Requests come first: the site's Analyze button and Telegram /analyze write qwen_ondemand's queue (cache/site/queue.jsonl of
the repository's main working tree); while the Qwen site worker is on hold these workers take them, oldest first, whatever
the name's age (operator 2026-11-16: the analysis is the cloud models' job).

List: research_now then watchlist by rank, operator-excluded names left out, a name re-analysed when its newest Gemini
analysis is older than REFRESH_DAYS (30: the backstop when nothing happened; operator 2026-11-16).

The verdict (verdict()) is the rule the operator ruled for Claude's valuation (stocks-workspace baselines/opus SPEC 4 and
5), applied to this valuation's own numbers: the expected value is the three values weighted by the valuation's own
probabilities, the expected return over 3 years is compared with the name's own required return, BUY needs 4 points a year
or more and both seeds reaching it, WATCH is above zero, AVOID is zero or less, NO_CALL when the name is not valued. (The
first rule, 2026-11-16 18:00, read BUY below the bear value and WATCH from bear to base; the bear value sits only 0 to
15% under the base, so WATCH never occurred in the first 28 names.) Paper only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import decided_financial  # noqa: E402
import decided_value  # noqa: E402
import decided_real_estate  # noqa: E402                       # WO_NC9c: registers the real-estate variant of decided_value
import qwen_ondemand as Q  # noqa: E402
import qwen_site  # noqa: E402
import why_losses  # noqa: E402
import interest_from_filing  # noqa: E402
from qwen_c import runner  # noqa: E402
from qwen_c.value import desk, run as vrun  # noqa: E402

PY = sys.executable
EFFORT = "high"                       # operator 2026-11-16: thinking effort is not negotiable
# floors: the share of an allowance left under which the arm waits. gemini: about one name's cost (operator 2026-11-16: no
# reserve needed). opus: the operator is not using Claude Code until the first fill is done (2026-11-16), so only what the
# coordinating session needs to keep supervising is left.
ARMS = {"gemini": {"model": "gemini-4-hydrogen-high", "floors": {"gemini-5h": 0.08, "gemini-weekly": 0.025}},
        "opus": {"model": "claude-opus-5-5", "floors": {"claude-5h": 0.10, "claude-weekly": 0.05}},
        # sonnet: the same route as opus with the smaller model, at the same effort (operator 2026-11-17: test whether it gets close
        # at less quota). Not scheduled; an arm only so a test runs the worker's own code.
        "sonnet": {"model": "claude-sonnet-5-5", "floors": {"claude-5h": 0.10, "claude-weekly": 0.05}}}
CLAUDE_ARMS = ("opus", "sonnet")      # answered through the Claude Code command line, paced on the Claude subscription's meter
ARM = "gemini"
GEM_MODEL = ARMS[ARM]["model"]
SITE = ROOT / "cache" / "gemini_site"
ONDEMAND = SITE / "ondemand"
REPORTS = SITE / "gemini_c_reports"
OVERLAY = SITE / "gemini_c_overlay.json"
CLAIMS = SITE / "claims"
LOCK = SITE / "worker.lock"
LOG = SITE / "worker.log"
USAGE = SITE / "usage.jsonl"
AGY_CWD = SITE / "agy_cwd"
CLAIM_STALE_HOURS = 3
SCHEMA = "gemini_c_site_v1"
REFRESH_DAYS = 30
RETRY_REFUSED_HOURS = 24
FLOORS = ARMS[ARM]["floors"]
SITE_FILES = ("public/data/gemini_c_overlay.json", "public/data/gemini_c_reports")
STATE = {"label": ""}
VALUE_METHOD = os.environ.get("VALUE_METHOD", "menu")      # WO_NC7: "menu" (default) or "decided" (the read decides the valuation inputs; operating and commodity names)
VALUE_METHODS = ("menu", "decided")


def decided():
    """True when this process values operating and commodity names by decided_value (VALUE_METHOD, or --value-method)."""
    if VALUE_METHOD not in VALUE_METHODS:
        raise ValueError(f"VALUE_METHOD {VALUE_METHOD!r} is not one of {VALUE_METHODS}")
    return VALUE_METHOD == "decided"


def agy_exe():
    p = os.environ.get("AGY_EXE") or shutil.which("agy") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")
    if not Path(p).exists():
        raise RuntimeError(f"agy not found (AGY_EXE, PATH, LOCALAPPDATA/agy/bin): {p}")
    return p


def set_arm(arm):
    """Selects the arm for this process: its model, its floors, and (not gemini) its own lock and usage file."""
    global ARM, GEM_MODEL, FLOORS, LOCK, USAGE
    ARM, GEM_MODEL, FLOORS = arm, ARMS[arm]["model"], ARMS[arm]["floors"]
    if arm != "gemini":
        LOCK, USAGE = SITE / f"worker_{arm}.lock", SITE / f"usage_{arm}.jsonl"
    else:
        LOCK, USAGE = SITE / "worker.lock", SITE / "usage.jsonl"


FALLBACK = {"gemini": "sonnet"}     # operator 2026-11-19: a name the Gemini worker cannot take because Gemini's allowance is under its floor goes to
#                                     Claude Sonnet (same messages, same checks; the report records the model). Sonnet under its own floor: wait, as before


def quota_low():
    """True when an allowance of the current arm is under its floor, or the meter cannot be read (never read as "there is room")."""
    try:
        m = meter()
        return any(m[k][0] < FLOORS[k] for k in FLOORS)
    except Exception:  # noqa: BLE001
        return True


def choose_arm(home):
    """Sets and returns the arm for the next name: `home`, or its FALLBACK when home's allowance is low and the fallback's is not."""
    set_arm(home)
    other = FALLBACK.get(home)
    if other is None or not quota_low():
        return home
    set_arm(other)
    if quota_low():
        set_arm(home)                       # both low: wait on the home arm's reset, as before
        return home
    log(f"{home} allowance is under its floor: this name goes to {other}")
    return other


def log(msg):
    SITE.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} [{ARM}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _agy(args, stdin=None, timeout=None):
    AGY_CWD.mkdir(parents=True, exist_ok=True)
    return subprocess.run([agy_exe(), *args], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(AGY_CWD), timeout=timeout)


def _claude(args, stdin=None, timeout=None):
    AGY_CWD.mkdir(parents=True, exist_ok=True)
    exe = os.environ.get("CLAUDE_EXE") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
    if not Path(exe).exists():
        raise RuntimeError(f"claude not found (CLAUDE_EXE, PATH, ~/.local/bin): {exe}")
    return subprocess.run([exe, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(AGY_CWD), timeout=timeout)


def meter_claude():
    """The Claude subscription's meter from the command line's own usage report (no tokens), as fractions LEFT."""
    import re
    out = _claude(["-p", "/usage", "--output-format", "json", "--no-session-persistence"], timeout=180).stdout
    text = json.loads(out[out.index("{"):])["result"]
    five = re.search(r"Current session:\s*(\d+)% used", text)
    week = re.search(r"Current week \(all models\):\s*(\d+)% used", text)
    return {"claude-5h": (1 - int(five.group(1)) / 100, None), "claude-weekly": (1 - int(week.group(1)) / 100, None)}


def meter():
    """{bucket id: (fraction of the allowance left, reset time ISO or None)} from the account's own usage report (no tokens)."""
    if ARM in CLAUDE_ARMS:
        return meter_claude()
    out = _agy(["-p", "/usage", "--output-format", "json"], timeout=180).stdout
    d = json.loads(out[out.index("{"):])
    return {b["id"]: (float(b["remaining_fraction"]), b.get("reset_time"))
            for g in d["command"]["data"]["groups"] for b in g["buckets"]}


def wait_for_quota():
    """Returns the meter once both Gemini allowances are at or above their floors; sleeps to the reset otherwise."""
    while True:
        try:
            m = meter()
            low = [(k, *m[k]) for k in FLOORS if m[k][0] < FLOORS[k]]
        except Exception as e:  # noqa: BLE001  an unreadable meter is never read as "there is room"
            log(f"meter unreadable ({type(e).__name__}: {str(e)[:120]}); waiting 10 minutes")
            time.sleep(600)
            continue
        if not low:
            return m
        k, left, reset = max(low, key=lambda x: x[2] or "")
        secs = 1800.0
        if reset:
            secs = (datetime.fromisoformat(reset.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() + 120
        log(f"quota: {k} has {left:.1%} left (floor {FLOORS[k]:.0%}), resets {reset}; waiting")
        time.sleep(min(max(secs, 120), 3600))


def _ask_gemini(text, timeout):
    """(result or None, detail): result = {status, response, usage{input_tokens, output_tokens, ...}}."""
    line = json.dumps({"event": "user", "message": {"content": text}}, ensure_ascii=False) + "\n"
    res = None
    r = _agy(["--model", GEM_MODEL, "--effort", EFFORT, "--sandbox", "--input-format", "stream-json", "--output-format",
              "stream-json", "-p", ""], stdin=line, timeout=timeout)
    for ln in (r.stdout or "").splitlines():
        if '"event":"result"' in ln:
            try:
                res = json.loads(ln)["result"]
            except ValueError:
                pass
    return res, f"agy: {(res or {}).get('error') or (r.stderr or '')[-300:]}"


def _ask_claude(text, timeout):
    """The same message to Claude Opus through the Claude Code command line: no tools, no settings, no hooks, no session kept."""
    r = _claude(["-p", "--model", GEM_MODEL, "--effort", EFFORT, "--system-prompt",
                 "You are an analyst. Do exactly what the message asks, in one reply.", "--tools", "", "--setting-sources", "",
                 "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence", "--output-format", "json"],
                stdin=text, timeout=timeout)
    try:
        d = json.loads(r.stdout[r.stdout.index("{"):])
    except ValueError:
        return None, f"claude: {(r.stderr or r.stdout or '')[-300:]}"
    u = d.get("usage") or {}
    ok = not d.get("is_error") and d.get("subtype") == "success"
    return ({"status": "SUCCESS" if ok else d.get("subtype") or "error", "response": d.get("result") or "",
             "usage": {"input_tokens": sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                                    "cache_read_input_tokens")),
                       "output_tokens": u.get("output_tokens"),
                       "thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
                       "cache_read_tokens": u.get("cache_read_input_tokens"), "stop_reason": d.get("stop_reason")}},
            f"claude: {d.get('api_error_status') or d.get('subtype')} {str(d.get('result'))[:200]}")


def gemini_call(body, url, timeout):
    """Stands in for runner.call: (kind, response in Ollama's shape, detail). A failed call is retried after the quota check, so
    an exhausted allowance is waited out and never recorded as a failed task."""
    parts = ["Answer in one reply. Do not call any tool, do not search, do not read or write files.\n"]
    for m in body["messages"]:
        parts.append(f"===== {m['role'].upper()} =====\n{m['content']}\n")
    line = "\n".join(parts)
    detail = ""
    for attempt in (1, 2, 3):
        t0 = time.time()
        res = None
        try:
            res, detail = (_ask_claude if ARM in CLAUDE_ARMS else _ask_gemini)(line, timeout)
        except subprocess.TimeoutExpired:
            detail = f"{ARM} call timed out"
        u = (res or {}).get("usage") or {}
        with USAGE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": Q.now_z(), "label": STATE["label"], "attempt": attempt, "status": (res or {}).get("status"),
                                "seconds": round(time.time() - t0, 1), "prompt_chars": len(line), **u}) + "\n")
        if res and res.get("status") == "SUCCESS" and (res.get("response") or "").strip():
            return "reply", {"message": {"role": "assistant", "content": res["response"]}, "done": True, "done_reason": "stop",
                             "prompt_eval_count": u.get("input_tokens"), "eval_count": u.get("output_tokens"),
                             "model": GEM_MODEL}, None
        log(f"{STATE['label']} call failed (attempt {attempt}): {detail[:200]}")
        time.sleep(60)
        wait_for_quota()
    return "infra_fatal", None, detail


def swap():
    """Gemini in Qwen's place, in this process only."""
    runner.call = gemini_call
    runner.gpu_preflight = lambda url: []
    via = "the Claude Code command line" if ARM in CLAUDE_ARMS else "agy"
    runner.model_show = lambda url: {"swapped_for": f"{GEM_MODEL} via {via}, effort {EFFORT}"}
    runner.ollama_raw.ollama_version = lambda base: f"not used ({ARM})"
    runner.MODEL = f"{GEM_MODEL} via {via}"
    if ARM != "gemini":                       # its own run folders: two processes never append to one run ledger
        runner.M3M_DIR = ROOT / "cache" / f"m3m_{ARM}"


def analyze(t, source):
    """One name end to end, as qwen_ondemand.analyze, in process; writes ondemand/<t>.json; returns its status."""
    import formation_value as FV
    commit, record = Q.verified_commit()
    T = Q.now_z()
    r = subprocess.run([PY, "-m", "qwen_c.packet", "--ticker", t, "--T", T, "--commit", commit, "--verified-record", record,
                        "--screener-repo", str(Q.book_paths.screener_repo()), "--online"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    pk = Q._json_tail(r.stdout)
    if r.returncode or not pk.get("packet"):
        out = (r.stderr or r.stdout).strip()
        return refusal(t, source, T, f"packet refused: {out.splitlines()[-1][:200] if out else r.returncode}")
    packet = pk["packet"]
    t0 = time.time()
    STATE["label"] = f"{t}:q1"
    q1 = runner.run(packet, seed=1000)
    log(f"{t} Q1 {q1.get('status')} {round(time.time() - t0)} s")
    pkj = json.loads(Path(packet).read_text(encoding="utf-8"))
    cik = pkj.get("cik")
    row = FV.stocks_rows(commit).get(t) or {}
    fam = FV.name_family(cik, datetime.fromisoformat(T.replace("Z", "+00:00"))) if cik else {"family": None}
    n = {"packet": packet, "packet_sha256": pk.get("packet_sha256"), "cik": cik, "sector": row.get("sector"),
         "market_cap": row.get("marketCap"), "family": fam.get("family")}
    if decided() and decided_real_estate.routes(fam):               # WO_NC9c: a real-estate name (not a mortgage REIT by the balance-sheet route) is valued by the decided method's real-estate variant
        n["family"] = decided_real_estate.FAMILY
    out_root = vrun.RUNS if ARM == "gemini" else ROOT / "cache" / f"m3q_{ARM}" / "runs"
    why, why_reason = None, None                  # WO_NC5: why a thin profit record is thin, asked once, before the two seeds (a base with a statutory tax fallback only)
    ifl, override = None, None                    # WO_NC8: the interest on borrowings from the filing text, asked once, only where the tagged interest gives a cost of debt outside the band
    prep = lambda **k: vrun.prepare(pkj, str(cik), str(n["sector"]), float(n["market_cap"] or 0), online=True, family=str(n["family"]), **({"real_estate": True} if n["family"] == decided_real_estate.FAMILY else {}), **k)[:2]  # noqa: E731
    try:
        try:
            f, b = prep()
        except desk.DeskRefusal as e:
            if e.code != "kd_out_of_band" or not getattr(e, "figures", None):
                raise
            STATE["label"] = f"{t}:interest_from_filing"
            raw = out_root / f"{pkj['ticker']}_{runner.t_compact(pkj['decision_time_utc'])}_{runner.sha256_bytes(Path(packet).read_bytes())[:12]}_interest_from_filing"
            ifl, override = interest_from_filing.ask(pkj, e.figures, raw)
            log(f"{t} interest from the filing: {ifl['status']}")
            if override is None:
                raise
            f, b = prep(interest_override=override)           # the band still applies to the new rate: outside it, this raises kd_out_of_band again
            ifl["kd_used"] = b["interest_from_filing"]["kd_used"]
        if b.get("tax_fallback"):
            STATE["label"] = f"{t}:why_losses"
            raw = out_root / f"{pkj['ticker']}_{runner.t_compact(pkj['decision_time_utc'])}_{runner.sha256_bytes(Path(packet).read_bytes())[:12]}_why_losses"
            why, why_reason = why_losses.ask(pkj, f, raw)
            log(f"{t} why losses: {why['cause']} {why_reason or 'valued'}")
    except desk.DeskRefusal as e:                 # the seeds record the same refusal
        if ifl and override is not None:
            ifl["kd_used"] = (getattr(e, "figures", None) or {}).get("kd")
    ov = {} if override is None else {"interest_override": override}      # WO_NC8: without it every call is exactly as before
    results = {}
    use_decided = decided() and (n["family"] in decided_value.FAMILIES + decided_financial.FAMILIES or n["family"] in decided_value.VARIANTS)      # WO_NC7, WO_NC9b: every other family keeps the menu; WO_NC9c: real estate
    an = decided_value.read_analysis(q1) if use_decided else None
    for seed in (() if why_reason else Q.SEEDS):
        STATE["label"] = f"{t}:value{seed}"
        if use_decided:
            res = (decided_financial if n["family"] in decided_financial.FAMILIES else decided_value).value(packet, str(cik), str(n["sector"]), float(n["market_cap"] or 0), family=str(n["family"]), analysis=an, seed=seed, out_root=out_root, **ov)
        else:
            res = vrun.value(packet, str(cik), str(n["sector"]), float(n["market_cap"] or 0), family=str(n["family"]), seed=seed, out_root=out_root, **ov)
        results[str(seed)] = res
        log(f"{t} value seed {seed} {res.get('status')} {res.get('reason') or ''}")
    if why_reason:
        results["loss_record"] = {"status": "no_call", "reason": why_reason}
    rep = Q.report(t, source, T, q1, n, results, commit, **ov)
    rep["model"] = GEM_MODEL
    if why:
        rep["loss_record"] = why
    if ifl:
        rep["interest_from_filing"] = ifl
    _write_report(rep)
    return "ok"


def refusal(t, source, T, why):
    _write_report({"ticker": t, "date": T, "source": "screener list refresh" if source == "list" else f"on request ({source})",
                   "model": GEM_MODEL, "analysis": "not run", "claims": None, "claims_supported": None, "in_code_book": False,
                   "qwen_book": None, "flags": [], "valued": False, "no_value_reason": why, "family": None, "tasks": {},
                   "valuation": None, "authority": "diagnostic: paper only, not investment advice"})
    log(f"{t} refused: {why}")
    return "refused"


def _write_report(rep):
    ONDEMAND.mkdir(parents=True, exist_ok=True)
    (ONDEMAND / f"{rep['ticker']}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")


# The verdict rule's two numbers are the Claude valuation arm's (baselines/opus calc.py H and BUY_ALPHA_PTS, SPEC 4 and 5,
# ruled by the operator); they are repeated here because nothing imports across repositories.
H_YEARS = 3
BUY_ALPHA_PTS = 4.0


def alpha_pts(value, price, ke):
    """Expected return a year over H_YEARS less the required return, in points: ((V x (1+ke)^H / P)^(1/H) - 1 - ke) x 100."""
    if value <= 0:
        return -100.0
    return ((value * (1 + ke) ** H_YEARS / price) ** (1 / H_YEARS) - 1 - ke) * 100


def value_meta(rep):
    """(required return, {bear, base, bull: probability}) from the name's stored valuation result, or (None, None)."""
    stem = f"{rep['ticker']}_{runner.t_compact(rep['date'])}_"
    dec = bool(rep.get("decided"))              # the runs of the report's own method first: a decided report beside an older menu run
    dirs = [d for root in sorted((ROOT / "cache").glob("m3q*")) for d in sorted((root / "runs").glob(stem + "*"))]
    for d in sorted(dirs, key=lambda d: ("_decided_" in d.name) != dec):
        f = d / "result.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            prob = (r.get("checks") or {}).get("prob")
            if str(r.get("status", "")).startswith("ok") and r.get("cost_of_equity") is not None and prob:
                return r["cost_of_equity"], prob
    return None, None


def pending_offer(rep):
    """The read's supported claim that an acquisition of the company itself is announced and pending (its `material_events` task, event type
    `acquisition_of_the_company`, status `announced_pending`), as {claim, date}, or None. Read from the name's stored read, as value_meta
    reads the stored valuation. Operator 2026-11-19: a company under a signed offer trades at the offer, so a verdict on its standalone
    value misleads; build() gives it no verdict and says why, and the value stays on the page."""
    stem = f"{rep['ticker']}_{runner.t_compact(rep['date'])}_"
    for root in sorted((ROOT / "cache").glob("m3m*")):
        for d in sorted((root / "runs").glob(stem + "*_1")):
            f = d / "analysis.json"
            if f.exists():
                claims = ((json.loads(f.read_text(encoding="utf-8")).get("tasks") or {}).get("material_events") or {}).get("claims") or []
                for c in claims:
                    if c.get("event_type") == "acquisition_of_the_company" and c.get("status") == "announced_pending" and c.get("support") == "supported":
                        return {"claim": c.get("claim"), "date": c.get("occurred_on")}
                return None
    return None


OFFER_REASON = "an offer to acquire the company is announced and pending: the price follows the offer's terms, not the company's standalone value"


def verdict(row, ke, prob):
    """(verdict, reason, alpha in points or None) in the quoted unit. A label, paper only."""
    if not row.get("valued"):
        return "NO_CALL", row.get("no_value_reason") or "not valued", None
    price = row.get("price_at_publish")
    vals = {k: row.get(f"value_{k}") for k in ("bear", "base", "bull")}
    if price is None or price <= 0 or any(v is None for v in vals.values()):
        return "NO_CALL", "no quoted price or market cap to compare the value with", None
    if ke is None or not prob:
        return "NO_CALL", "the valuation's required return or probabilities are not on record", None
    a = alpha_pts(sum(prob[k] * vals[k] for k in vals), price, ke)
    why = f"expected return {a:+.1f} points a year against the required return over {H_YEARS} years"
    if a <= 0:
        return "AVOID", why, a
    if a < BUY_ALPHA_PTS:
        return "WATCH", why + f" (BUY needs {BUY_ALPHA_PTS:g} or more)", a
    filed = (row.get("value_per_filed_share") or {}).get("base")
    k = vals["base"] / filed if filed else None                      # filed share -> quoted share, as quote_units scaled it
    seeds = [v for v in (row.get("seed_base") or {}).values() if v is not None]
    if k is None or len(seeds) < 2 or any(alpha_pts(v * k, price, ke) < BUY_ALPHA_PTS for v in seeds):
        return "WATCH", why + "; the two runs do not both reach BUY", a
    return "BUY", why, a


def verdict_differs_at_alt_tax_rate(row, ke, prob, v):
    """WO_NC3: whether the same verdict() on the values at the second rate of a statutory tax fallback gives a label other than `v`
    (the verdict at the filed rate); None when no second value was made. Annotation only: the label itself is unchanged."""
    tr = row.get("tax_range") or {}
    alt = tr.get("value_alt")
    if not alt:
        return None
    return verdict(dict(row, value_bear=alt["bear"], value_base=alt["base"], value_bull=alt["bull"],
                        value_per_filed_share=tr["value_per_filed_share_alt"], seed_base=tr["seed_base_alt"]), ke, prob)[0] != v


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def site_stem(t):
    """The published report's file name for a ticker. A ticker that is a Windows device name (CON, PRN, AUX, NUL, COMn, LPTn)
    cannot be added by git on Windows, so it is published with a trailing underscore; the site applies the same rule
    (lib/data-service.ts reportStem). Found 2026-11-16: one such name stopped every publish for three hours, unnoticed."""
    return f"{t}_" if t.upper() in WINDOWS_RESERVED else t


def fill_state(have):
    """(names on the list, how many of them have a report), or (None, None) when the list cannot be read."""
    try:
        names = Q.list_names()
    except Exception as e:  # noqa: BLE001  no verified screener run: the fill is then not called complete
        print(f"list unreadable: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return None, None
    return len(names), sum(t in have for t in names)


def overlay_row(row):
    """The overlay's row of a name: the row, with the decided method's detail (tens of kilobytes a name; the stock page reads it from the
    per-name report) cut to the two fields that say the name was valued by it."""
    d = row.get("decided")
    return dict(row, decided={k: d.get(k) for k in ("method", "version")}) if d else row


def build():
    rows = {}
    for p in sorted(ONDEMAND.glob("*.json")) if ONDEMAND.exists() else []:
        rep = json.loads(p.read_text(encoding="utf-8"))
        rows[rep["ticker"]] = ({k: v for k, v in rep.items() if k not in ("tasks", "valuation", "ticker", "authority")}, rep)
    s = json.loads((paths.resolve("screener_data_dir") / "stocks.json").read_text(encoding="utf-8"))
    s = s if isinstance(s, list) else s.get("stocks", s)
    qwen_site.quote_units(rows, {r["symbol"]: r for r in s if isinstance(r, dict) and r.get("symbol")})
    for row, rep in rows.values():
        ke, prob = value_meta(rep) if row.get("valued") else (None, None)
        v, why, a = verdict(row, ke, prob)
        offer = pending_offer(rep)
        if offer:                               # no verdict on a standalone value while the company is under offer; the value and alpha stay
            v, why = "NO_CALL", OFFER_REASON + (f" (on the value alone: {v}, {why})" if a is not None else "")
        for d in (row, rep):
            d.update(verdict=v, verdict_reason=why, alpha_pts=a, ke=ke, pending_offer=offer)
        if row.get("tax_range"):
            for d in (row, rep):
                d["verdict_differs_at_alt_tax_rate"] = verdict_differs_at_alt_tax_rate(row, ke, prob, v)
    if REPORTS.exists():
        shutil.rmtree(REPORTS)
    REPORTS.mkdir(parents=True)
    for t, (_, rep) in rows.items():
        (REPORTS / f"{site_stem(t)}.json").write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")
    counts = {k: sum(r["verdict"] == k for r, _ in rows.values()) for k in ("BUY", "WATCH", "AVOID", "NO_CALL")}
    listed, covered = fill_state(set(rows))
    ov = {"schema": SCHEMA, "generated_at": Q.now_z(), "model": GEM_MODEL, "effort": EFFORT, "count": len(rows),
          "valued_count": sum(bool(r["valued"]) for r, _ in rows.values()), "verdict_counts": counts,
          # the first fill is complete when every list name has a report (analysed, or refused and on retry): the screener's
          # Claude paper books then follow these verdicts (track_paper_portfolios.ai_verdicts; operator 2026-11-16)
          "list_names": listed, "list_covered": covered, "fill_complete": listed is not None and listed > 0 and covered == listed,
          "verdict_rule": f"Expected value = the bear, base and bull values weighted by the valuation's probabilities. BUY: its "
                          f"return over {H_YEARS} years is {BUY_ALPHA_PTS:g} points a year or more above the required return, in "
                          "both runs. WATCH: above zero. AVOID: zero or less. NO_CALL: not valued.",
          "note": "Gemini reading of SEC filings in the place of the local model; values per share from code using Gemini's "
                  "choices, where both seeds agree. Paper only, not investment advice.",
          "tickers": {t: overlay_row(r) for t, (r, _) in sorted(rows.items())}}
    OVERLAY.write_text(json.dumps(ov, indent=1, sort_keys=True), encoding="utf-8")
    print(f"built {len(rows)} names ({ov['valued_count']} valued) {counts}", flush=True)
    return ov


def _main_checkout():
    """The repository's main working tree: the publish lock is shared with qwen_site and the depth publisher there."""
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                       text=True, check=True)
    return Path(r.stdout.strip()).parent


def publish():
    """The two site files to stock-screener main through the dedicated publish clone, under the shared publish lock."""
    build()
    repo = paths.resolve("screener_publish_repo")
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)  # noqa: E731
    if "stock-screener" not in g("remote", "get-url", "origin").stdout:
        sys.exit("ABORT: the publish clone's origin is not stock-screener")
    qwen_site.LOCK = _main_checkout() / "cache" / "screener_publish.lock"
    if not qwen_site._lock():
        sys.exit("ABORT: screener_publish.lock held")
    try:
        if g("fetch", "origin", "main").returncode:
            sys.exit("ABORT: fetch failed")
        # qwen_site leaves its own files pending in the clone between its publishes; they are its to commit, not ours
        if g("status", "--porcelain", "--", ":!public/data/qwen_overlay.json", ":!public/data/m3o_books.json",
             ":!public/data/qwen_reports", *(f":!{p}" for p in SITE_FILES)).stdout.strip():
            sys.exit("ABORT: the publish clone has unexpected local changes")
        if g("checkout", "-B", "main", "origin/main").returncode:
            sys.exit("ABORT: could not reset the publish clone to origin/main")
        data = repo / "public" / "data"
        shutil.copyfile(OVERLAY, data / "gemini_c_overlay.json")
        if (data / "gemini_c_reports").exists():
            shutil.rmtree(data / "gemini_c_reports")
        shutil.copytree(REPORTS, data / "gemini_c_reports")
        for f in [data / "gemini_c_overlay.json", *sorted((data / "gemini_c_reports").glob("*.json"))]:
            json.loads(f.read_text(encoding="utf-8"))
        if (a := g("add", "-A", *SITE_FILES)).returncode:      # a failed add stages nothing and would read as "unchanged"
            sys.exit(f"ABORT: git add failed: {(a.stderr or a.stdout).strip()[:300]}")
        if g("diff", "--cached", "--check").returncode:
            sys.exit("ABORT: conflict markers in staged content")
        if g("diff", "--cached", "--quiet").returncode == 0:
            print("gemini site files unchanged: nothing to push", flush=True)
            return
        if g("-c", "commit.gpgsign=false", "commit", "-m", "gemini analysis: site update").returncode:
            sys.exit("ABORT: commit failed")
        for _ in range(5):
            g("fetch", "origin", "main")
            if g("rebase", "origin/main").returncode:
                g("rebase", "--abort")
                sys.exit("ABORT: rebase conflict against origin/main")
            if g("push", "origin", "main").returncode == 0:
                print("pushed gemini site files", g("rev-parse", "--short", "HEAD").stdout.strip(), flush=True)
                return
            time.sleep(4)
        sys.exit("ABORT: push failed after 5 attempts")
    finally:                                   # none of OUR files is left pending in the clone, whatever happened
        g("reset", "-q", "--", *SITE_FILES)
        g("checkout", "-q", "--", *SITE_FILES)
        g("clean", "-fdq", "--", *SITE_FILES)
        qwen_site.LOCK.unlink(missing_ok=True)


def last_analysed():
    """{ticker: newest Gemini analysis date}; a refusal counts as RETRY_REFUSED_HOURS old-age less (retried the next day)."""
    out = {}
    shift = timedelta(days=REFRESH_DAYS) - timedelta(hours=RETRY_REFUSED_HOURS)
    for p in ONDEMAND.glob("*.json") if ONDEMAND.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        date = d["date"]
        if d.get("analysis") == "not run":
            date = (datetime.fromisoformat(date.replace("Z", "+00:00")) - shift).isoformat()
        out[d["ticker"]] = date
    return out


def claim(t):
    """True when this process now holds name t (an exclusive file; a claim whose process is gone, or older than
    CLAIM_STALE_HOURS, is a dead worker's and is taken over)."""
    CLAIMS.mkdir(parents=True, exist_ok=True)
    p = CLAIMS / f"{t}.json"
    if p.exists():
        import formation_run as FR
        try:
            dead = not FR.pid_alive(int(json.loads(p.read_text(encoding="utf-8"))["pid"]))
        except (ValueError, KeyError, OSError):
            dead = False
        if dead or time.time() - p.stat().st_mtime > CLAIM_STALE_HOURS * 3600:     # its worker is gone, or it is too old
            p.unlink(missing_ok=True)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, json.dumps({"arm": ARM, "pid": os.getpid(), "at": Q.now_z()}).encode())
    os.close(fd)
    return True


def queue_file():
    """qwen_ondemand's request queue, in the repository's main working tree (where the site and the Telegram bot write it)."""
    return _main_checkout() / "cache" / "site" / "queue.jsonl"


def next_name():
    """(ticker, source, from_queue) claimed for this arm, or None: a queued request first (oldest first), then the next due list
    name: gemini from the top of the list, any other arm from the bottom."""
    for q in Q._jsonl(queue_file()):
        if claim(q["ticker"]):
            return q["ticker"], q.get("source") or "web", True
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).isoformat()
    seen = last_analysed()
    names = Q.list_names()
    for t in names if ARM == "gemini" else reversed(names):
        if seen.get(t, "") < cutoff and claim(t):
            return t, "list", False
    return None


def take_lock():
    import formation_run as FR
    if LOCK.exists():
        try:
            if FR.pid_alive(int(LOCK.read_text().strip())):
                return False
        except ValueError:
            pass
    SITE.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def work(max_names, do_publish):
    decided()                                   # WO_NC7: an unknown VALUE_METHOD stops the worker before it claims a name
    if not take_lock():
        print("another worker holds the lock", flush=True)
        return 0
    home, lock = ARM, LOCK                      # the scheduled arm and its lock (a name may go to the FALLBACK arm; the lock stays this one)
    try:
        swap()
        done = 0
        while max_names is None or done < max_names:
            choose_arm(home)
            before = wait_for_quota()       # before the name is claimed: a claim held through a long quota wait is taken over by another arm, and the name was then read twice (2026-11-18)
            nxt = next_name()
            if nxt is None:
                log("nothing to analyse")
                break
            t, source, queued = nxt
            log(f"{t} start ({source}) | left: " + ", ".join(f"{k} {before[k][0]:.1%}" for k in FLOORS))
            try:
                st = analyze(t, source)
            except Exception as e:  # noqa: BLE001  one name's failure is logged and the worker moves on
                st = refusal(t, source, Q.now_z(), f"pipeline error: {type(e).__name__}: {str(e)[:160]}")
            if queued:
                Q.QUEUE = queue_file()
                Q.pop(t)
            (CLAIMS / f"{t}.json").unlink(missing_ok=True)
            done += 1
            log(f"{t} {st}")
            if do_publish:
                try:
                    publish()
                except SystemExit as e:
                    log(f"publish failed: {e}")
        return 0
    finally:
        if lock.exists() and lock.read_text().strip() == str(os.getpid()):
            lock.unlink()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=sorted(ARMS), default="gemini")
    ap.add_argument("--value-method", choices=VALUE_METHODS, help="WO_NC7: the valuation method (default: the VALUE_METHOD environment variable, else menu)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    wk = sub.add_parser("work")
    wk.add_argument("--max-names", type=int)
    wk.add_argument("--no-publish", action="store_true")
    for c in ("build", "publish", "status", "meter"):
        sub.add_parser(c)
    a = ap.parse_args()
    set_arm(a.arm)
    VALUE_METHOD = a.value_method or VALUE_METHOD
    if a.cmd == "work":
        sys.exit(work(a.max_names, not a.no_publish))
    elif a.cmd == "build":
        build()
    elif a.cmd == "publish":
        publish()
    elif a.cmd == "meter":
        print(json.dumps(meter(), indent=1))
    else:
        seen = last_analysed()
        print("analysed:", len(seen), "| claimed:", len(list(CLAIMS.glob("*.json"))) if CLAIMS.exists() else 0,
              "| lock:", LOCK.read_text().strip() if LOCK.exists() else None)

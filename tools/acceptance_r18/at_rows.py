"""The acceptance tests that read only the day's rows (revision 18, brief section 6): pure functions of build_day.py's output, so each is
proved on written-down rows. The thin scripts at1d_*.py, at3_*.py, at4_*.py, at5_*.py, at6_*.py and at9_*.py load a day file and call these.

Every function returns {"at", "pass", "summary", ...counts}. With `names=False` (the 167) nothing carries a ticker.
"""
import statistics

PRINTED = ("used", "outside_fence_above", "outside_fence_below")

# the TASK bullet of brief section 3.2, verbatim
LEVEL_ANCHOR_BULLET = ("- Level anchor: the CONSENSUS-IMPLIED VALUE checks the level of your Base, not the direction of your call. It values "
                       "average performers close to their price, but by itself it is not evidence that a stock is cheap or expensive. Your call "
                       "rests on the economics you set out above. A Base far from the reference needs the reason DEFAULTS names; a Base close "
                       "to it needs no reason and earns no credit.")


# the TASK's item 6 of revision 19 (brief_rev19.md D2 c), verbatim: AT6 restated for revision 19's text (ruling 1 forces the restatement; recorded as such)
ITEM_6 = ("6. The desk also returns price_implied: for each judgment input (coe, growth_years_3_5, fade_years, terminal_g, terminal_ronic, year2_level), "
          "the value at which your Base would equal today's price with your other inputs unchanged, or \"not reachable\" when no value inside the input's "
          "bound does it. DEFAULTS prints the same at the default inputs. A verdict of undervalued or overvalued needs a stated disagreement with the price: "
          "in your answer run, pass crux, naming one to three of those inputs where your evidence says the price is wrong, each with your reason and at "
          "least one citation {source, date, quote} of this company's own evidence: DATA 3, DATA 4, DATA 5, DATA 6, GUIDANCE (the company's own release), "
          "or a page you fetched in this session that names the company, with the quote copied exactly. Code fills in your value and the price-implied "
          "value from that run. DEFAULTS, the base rates, the macro anchors, the CONSENSUS-IMPLIED VALUE, the sector bands, the consensus rows, the news "
          "list and the research briefs are context and never support a crux. Without a valid crux your verdict is HOLD, wherever your Base sits. "
          "Disagreeing with the analysts' targets is allowed when your evidence supports it. In SECTION 3, state each crux (the input, your number, the "
          "number the price implies, and the dated evidence) and argue the size of the disagreement, not only its sign. Also report the neutral reverse "
          "DCF's implied 10-year growth and the base-rate band it falls in. SECTION 0 and SECTION 12 state the verdict this item gives; where the system "
          "text says otherwise, this TASK takes precedence.")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _built(rows):
    return {k: r for k, r in rows.items() if r.get("error") is None}


def _k(key, names):
    return key if names else None


# ---- AT1d single source ----------------------------------------------------------------------------------------------------------

def at1d(rows, *, names=True):
    """The pack's printed reference = build(**reference_inputs(...)) to the cent, for every name (a name whose two values are both None
    agrees). A pack that FAILED TO BUILD is a failure of this test, counted and listed (`not_built`), never dropped. The independent call is
    build_day's `parity` (a fresh DataRoot, the files read again)."""
    n = same = not_built = 0
    bad, missing = [], 0
    for key, r in sorted(rows.items()):
        if r.get("error") is not None:
            not_built += 1
            bad.append((_k(key, names), "the pack did not build: " + str(r["error"])[:80]))
            continue
        par = r.get("parity")
        if par is None or "error" in par or "pack_value" not in par:
            missing += 1
            bad.append((_k(key, names), "no independent reference_inputs call: " + str((par or {}).get("error", "absent"))[:80]))
            continue
        n += 1
        a, b = par["pack_value"], par["ri_value"]
        if a is None and b is None:
            same += 1
        elif a is not None and b is not None and abs(a - b) < 0.005 and (r.get("printed_value") is None or abs(r["printed_value"] - a) < 0.005):
            same += 1
        else:
            bad.append((_k(key, names), f"pack {a} vs reference_inputs {b}"))
        if par.get("args_equal") is False:
            bad.append((_k(key, names), "the pack's build arguments differ from reference_inputs'"))
    ok = n > 0 and not bad
    return {"at": "AT1d single source", "pass": ok, "names": n, "agree_to_the_cent": same, "disagree_or_missing": len(bad), "not_built": not_built,
            "details": bad[:20],
            "summary": f"{same} of {n} names: the pack's reference equals build(**reference_inputs) to the cent; {len(bad)} problems "
                       f"({not_built} packs did not build)"}


# ---- AT3 coverage -----------------------------------------------------------------------------------------------------------------

def at3(rows18, rows16, *, names=True):
    """The share of names with a printed reference (status used or outside the fence; for revision 16, a printed value) is at least
    revision 16's share on the same names, minus 2 points. A name that did not build counts as having none."""
    keys = sorted(rows18)
    n = len(keys)
    p18 = sum(1 for k in keys if (rows18[k].get("error") is None and rows18[k].get("status") in PRINTED))
    p16 = sum(1 for k in keys if (k in rows16 and rows16[k].get("error") is None and rows16[k].get("printed_value") is not None))
    s18, s16 = (p18 / n, p16 / n) if n else (0.0, 0.0)
    ok = n > 0 and s18 >= s16 - 0.02
    return {"at": "AT3 coverage", "pass": ok, "names": n, "printed_rev18": p18, "printed_rev16": p16, "share_rev18": s18, "share_rev16": s16,
            "bar": "share rev18 >= share rev16 - 2 points", "names_only_in_rev16": sum(1 for k in keys if k not in rows16),
            "summary": f"revision 18 prints {p18}/{n} = {s18:.1%}, revision 16 {p16}/{n} = {s16:.1%}"}


# ---- AT4 no non-positive reference printed ---------------------------------------------------------------------------------------------------

def at4(rows, *, names=True):
    """No printed reference is at or below 0 (to the cent); a reference at or below 0 carries not_meaningful and prints no number."""
    printed = nonpos_printed = nonpos_ref = wrong_status = 0
    bad = []
    for key, r in sorted(_built(rows).items()):
        pv, ref = r.get("printed_value"), r.get("reference") or {}
        if pv is not None:
            printed += 1
            if not pv > 0:
                nonpos_printed += 1
                bad.append((_k(key, names), "a non-positive number is printed"))
        v = ref.get("value")
        if v is not None and not float(f"{v:.2f}") > 0:
            nonpos_ref += 1
            if r.get("status") != "not_meaningful" or pv is not None:
                wrong_status += 1
                bad.append((_k(key, names), f"a reference at or below zero has status {r.get('status')} and prints {pv}"))
    ok = not bad
    return {"at": "AT4 no non-positive reference printed", "pass": ok, "printed": printed, "printed_non_positive": nonpos_printed,
            "references_at_or_below_zero": nonpos_ref, "not_marked_not_meaningful": wrong_status, "details": bad[:20],
            "summary": f"{printed} printed, {nonpos_printed} non-positive printed; {nonpos_ref} references at or below zero, {wrong_status} not marked "
                       f"not_meaningful"}


# ---- AT5' level sanity: the median clause and the reviewer's gross-error read (revision 19, brief_rev19.md 10b; recorded as post-hoc) -------------------

AT5_MEDIAN_BAR = (0.70, 1.45)
READ_AT = "AT5 gross-error read"


def scale_risk(r):
    """True when a built name's reference is one the gross-error read must look at when it is extreme: it carries a shares warning, a share-scale gap
    (SECTION 2's SHARES ALERT, or the SCALE CORRUPTION note of its filed series) or is valued by the cash-only method."""
    f, ref, text = r.get("facts") or {}, r.get("reference") or {}, r.get("text") or ""
    return bool(f.get("shares_warning")) or "SHARES ALERT" in text or "SCALE CORRUPTION" in text or ref.get("method") == "cash_only"


# Revision 20 (brief_input_scope_fixes.md 9.3-9.4): the read file's version 2, and the hardened check. Every extreme is read; an entry is read
# only with both booleans and a basis holding a digit; an entry marking either error FAILS, required or not.
READ_VERSION = 2
READ_TOP_KEYS = ("at", "version", "day_file_sha256", "tree_commit", "reviewer", "written_at", "reads", "notes")
READ_TOP_REQUIRED = ("at", "version", "day_file_sha256", "tree_commit", "reviewer", "written_at", "reads")
READ_ENTRY_KEYS = ("unit_or_scale_error", "input_scope_error", "input_scope_category", "basis")
INPUT_SCOPE_CATEGORIES = ("nci", "customer_money", "vendor_revenue_basis", "other")


def parse_read(raw):
    """(read, duplicates): the read file's bytes parsed as JSON, and every key that appears twice in one object at any depth (9.4 (e): a
    duplicate key is a problem, and the ordinary parser keeps only the last). (None, []) when the bytes are not JSON."""
    import json
    dups = []

    def hook(pairs):
        seen = set()
        for k, _v in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return dict(pairs)
    try:
        return json.loads(raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) else raw, object_pairs_hook=hook), dups
    except ValueError:
        return None, []


def _entry_read(e):
    """True when an entry counts as read (9.4 (b)): both booleans, a `basis` string holding at least one digit, and, when it marks an input-scope
    error, a category of the closed list."""
    if not isinstance(e, dict):
        return False
    if not isinstance(e.get("unit_or_scale_error"), bool) or not isinstance(e.get("input_scope_error"), bool):
        return False
    basis = e.get("basis")
    if not (isinstance(basis, str) and any(ch.isdigit() for ch in basis)):
        return False
    return not (e["input_scope_error"] and e.get("input_scope_category") not in INPUT_SCOPE_CATEGORIES)


def read_problems(read, to_read, day_sha256=None, tree_commit=None, extremes=None, duplicates=()):
    """(unread, errors, problems), revision 20's hardened check (brief_input_scope_fixes.md 9.4). `read` is the reviewer's file as a dict (version 2,
    9.3: {"at": READ_AT, "version": 2, "day_file_sha256", "tree_commit", "reviewer", "written_at", "reads": {row key: {"unit_or_scale_error": bool,
    "input_scope_error": bool, "input_scope_category"?: nci | customer_money | vendor_revenue_basis | other, "basis": str}}, "notes"?});
    `to_read` the row keys the read must cover (every extreme, (a)); `extremes` the day's extremes (default `to_read`); `tree_commit` and
    `day_sha256` the day file's (g); `duplicates` the keys `parse_read` found twice (e).
    `unread`: required keys with no entry or an entry that is not read (b). `errors`: every key whose entry marks either error, required or not
    (c), with its kinds. `problems` (strings, no ticker): a wrong kind or version (h), a missing or unknown top-level key or entry key (f), a
    duplicate key (e), an entry for a row that is not an extreme of this day file (d), another day file or another tree (g)."""
    problems = []
    if not isinstance(read, dict) or read.get("at") != READ_AT or not isinstance(read.get("reads"), dict):
        return sorted(to_read), [], ["the gross-error read is not in the form the scripts take (see at5_level_sanity.py)"]
    if read.get("version") != READ_VERSION:
        problems.append(f"the gross-error read is version {read.get('version')!r}, not {READ_VERSION}")
    missing = [k for k in READ_TOP_REQUIRED if k not in read]
    if missing:
        problems.append("the gross-error read lacks " + ", ".join(missing))
    unknown = sorted(k for k in read if k not in READ_TOP_KEYS)
    if unknown:
        problems.append("the gross-error read has unknown top-level keys: " + ", ".join(unknown))
    if duplicates:
        problems.append(f"the gross-error read repeats {len(duplicates)} key(s) in one object")
    if day_sha256 is not None and read.get("day_file_sha256") != day_sha256:
        problems.append("the gross-error read was written for another day file")
    if tree_commit is None:
        problems.append("the day file records no tree commit to check the read's tree_commit against")
    elif read.get("tree_commit") != tree_commit:
        problems.append("the gross-error read was written for another tree commit")
    allowed = set(to_read if extremes is None else extremes)
    not_extreme = sum(1 for k in read["reads"] if k not in allowed)
    if not_extreme:
        problems.append(f"{not_extreme} entr{'y names a row' if not_extreme == 1 else 'ies name rows'} that is not an extreme of this day file")
    bad_entries = sum(1 for e in read["reads"].values() if isinstance(e, dict) and any(k not in READ_ENTRY_KEYS for k in e))
    if bad_entries:
        problems.append(f"{bad_entries} entr{'y has' if bad_entries == 1 else 'ies have'} unknown keys")
    unread = [k for k in sorted(to_read) if not _entry_read(read["reads"].get(k))]
    errors = []
    for k, e in sorted(read["reads"].items()):
        if not isinstance(e, dict):
            continue
        kinds = [x for x in ("unit_or_scale_error", "input_scope_error") if e.get(x) is True]
        if kinds:
            errors.append((k, kinds))
    return unread, errors, problems


def at5(rows, *, names=True, read=None, read_sha256=None, day_sha256=None, tree_commit=None, read_duplicates=()):
    """AT5', the operator's restatement of AT5 (brief_rev19.md 10b; post-hoc, recorded as such). Over the names with a printed reference and a price:
      - the median V/P lies in [0.70, 1.45] (a bar);
      - the share above 3x or below 1/3x is REPORTED with its census, never marked (the 10% clause is gone: it tested the dispersion of the generic
        engine ruling 1 froze); the census is counts only, no ticker: above, below, outside the analysts' fence, levels method, cash-only, shares flag;
      - the reviewer's gross-error read BINDS. Revision 20 (brief_input_scope_fixes.md 9.1-9.4, operator ruling (b): post-hoc, stricter): EVERY
        extreme is covered by the read (version 2), each with both booleans and a basis holding a digit, and no entry marks a unit or scale error or
        an input-scope error. `read` is the parsed read file, `read_sha256` the sha256 of the file as given (recorded in the result), `tree_commit` the
        day file's `meta.inputs.tree_commit` and `read_duplicates` the keys `parse_read` found twice. A missing read is PENDING, never PASS; so is a
        read that does not cover every extreme, one for another day file or tree, one with a duplicate, unknown or out-of-day key, or one that is not
        version 2 in the form the scripts take. An entry that marks either error FAILS, required or not."""
    vps, extremes = [], []
    census = {"above_3x": 0, "below_one_third": 0, "outside_the_fence": 0, "levels_method": 0, "cash_only": 0, "with_a_shares_flag": 0}
    for key, r in _built(rows).items():
        pv, px = r.get("printed_value"), r.get("price")
        if pv is not None and _num(px) and px > 0:
            vps.append(pv / px)
            v = pv / px
            if v > 3.0 or v < 1.0 / 3.0:
                extremes.append((key, r))
                census["above_3x" if v > 3.0 else "below_one_third"] += 1
                census["outside_the_fence"] += r.get("status") in ("outside_fence_above", "outside_fence_below")
                census["levels_method"] += (r.get("reference") or {}).get("method") == "levels"
                census["cash_only"] += (r.get("reference") or {}).get("method") == "cash_only"
                census["with_a_shares_flag"] += bool((r.get("facts") or {}).get("shares_warning"))
    if not vps:
        return {"at": "AT5 level sanity", "pass": False, "names": 0, "summary": "no name has a printed reference and a price"}
    med = statistics.median(vps)
    share = len(extremes) / len(vps)
    median_ok = AT5_MEDIAN_BAR[0] <= med <= AT5_MEDIAN_BAR[1]
    # revision 20 (9.4 (a)): every extreme is read, not only those `scale_risk` names (the count of those stays in the census)
    to_read = [k for k, _r in extremes]
    res = {"at": "AT5 level sanity", "restated_for": "revision 20 (AT5', post-hoc; every extreme read)", "names": len(vps), "median_vp": med,
           "median_ok": median_ok, "extreme": len(extremes), "extreme_share": share, "extreme_census": census,
           "extreme_with_scale_risk": sum(1 for _k, r in extremes if scale_risk(r)),
           "reported_not_marked": "the share above 3x or below 1/3x and its census", "bar": "median V/P in [0.70, 1.45]; the gross-error read binds",
           "gross_error_read_required_for": len(to_read), "gross_error_read_sha256": read_sha256 if read is not None else None}
    if read is None:
        unread, errors, problems = list(to_read), [], ["no gross-error read was supplied"]
    else:
        unread, errors, problems = read_problems(read, to_read, day_sha256, tree_commit=tree_commit, duplicates=read_duplicates)
    n_scale = sum(1 for _k, kinds in errors if "unit_or_scale_error" in kinds)
    n_scope = sum(1 for _k, kinds in errors if "input_scope_error" in kinds)
    res.update(gross_error_read_unread=len(unread), gross_error_read_unit_or_scale_errors=n_scale, gross_error_read_input_scope_errors=n_scope,
               gross_error_read_problems=problems)
    head = f"median V/P {med:.3f} over {len(vps)} names ({'in' if median_ok else 'OUTSIDE'} [0.70, 1.45]); {len(extremes)} ({share:.1%}) above 3x or below 1/3x (reported, not marked)"
    if not median_ok or errors:
        res["pass"] = False
        res["summary"] = head + "; " + ("the median clause FAILS" if not median_ok else
                                        f"the gross-error read marks {n_scale} unit or scale error(s) and {n_scope} input-scope error(s): FAIL")
    elif read is None or problems or unread:
        res["pass"], res["label"] = False, "PENDING"
        res["summary"] = (head + "; the gross-error read binds and is " + ("missing" if read is None else "not complete") +
                          f" ({len(unread)} of {len(to_read)} extremes unread)" +
                          ("; " + "; ".join(problems) if read is not None and problems else ""))
    else:
        res["pass"] = True
        res["summary"] = head + f"; the gross-error read covers all {len(to_read)} extremes: none a unit or scale error or an input-scope error"
    return res


# ---- AT6 fence, cap, text -----------------------------------------------------------------------------------------------------------------

def at6(rows, constants, *, names=True):
    """AT6, restated for revision 19's text (brief_rev19.md section 13; ruling 1 forces it, and it is recorded as a restatement): every
    outside-fence reference prints its value and flag; no base_year_capped stamp anywhere; the anchor-role sentence (D1's, as the tree under test
    holds it) is in every printed reference line; item 6 is in the TASK and the Level-anchor bullet is not; every pack's DEFAULTS carries the
    `price_implied` line; PACK_REVISION is 20 and FACTS_VERSION is 8 (restated for revision 20, brief_input_scope_fixes.md section 10 step 3:
    the input-scope text and facts; the rest of the test is unchanged).
    constants: {"PACK_REVISION", "FACTS_VERSION", "ANCHOR_ROLE", "TASK"} read from the tree under test (build_day records them)."""
    bad = []
    if constants.get("PACK_REVISION") != 20:
        bad.append((None, f"PACK_REVISION is {constants.get('PACK_REVISION')}, not 20"))
    if constants.get("FACTS_VERSION") != 8:
        bad.append((None, f"FACTS_VERSION is {constants.get('FACTS_VERSION')}, not 8"))
    task = constants.get("TASK") or ""
    item6_ok = ITEM_6 in task
    if not item6_ok:
        bad.append((None, "the TASK's item 6 (price_implied and the crux) is not present"))
    anchor_bullet_gone = LEVEL_ANCHOR_BULLET not in task and "Level anchor" not in task
    if not anchor_bullet_gone:
        bad.append((None, "the TASK still carries the Level anchor bullet"))
    role = constants.get("ANCHOR_ROLE") or ""
    printed = fenced = capped = no_pi_line = 0
    for key, r in sorted(_built(rows).items()):
        text, st = r.get("text") or "", r.get("status")
        lines = [l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE (reference" in l]
        if text and not any(l.startswith("- price_implied: ") for l in text.splitlines()):
            no_pi_line += 1
            bad.append((_k(key, names), "the DEFAULTS block has no price_implied line"))
        if st in PRINTED:
            printed += 1
            if not lines or not all(role and role in l for l in lines):
                bad.append((_k(key, names), "a printed reference line lacks the anchor-role sentence"))
        if st in ("outside_fence_above", "outside_fence_below"):
            fenced += 1
            pv = r.get("printed_value")
            line = lines[0] if lines else ""
            if pv is None or f"${pv:,.2f}" not in line or "outside the street-target fence [" not in line or "level check only" not in line:
                bad.append((_k(key, names), "an outside-fence reference does not print its value and flag"))
        stamps = list((r.get("reference") or {}).get("stamps") or []) + list(((r.get("facts") or {}).get("long_run") or {}).get("stamps") or [])
        if "base_year_capped" in text or any("base_year_capped" in str(s) for s in stamps) or (r.get("facts") or {}).get("base_year_cap"):
            capped += 1
            bad.append((_k(key, names), "a base_year_capped stamp is present"))
    ok = not bad
    return {"at": "AT6 fence, cap, text", "pass": ok, "printed_references": printed, "outside_fence": fenced, "base_year_capped": capped,
            "packs_without_the_price_implied_line": no_pi_line, "pack_revision": constants.get("PACK_REVISION"),
            "facts_version": constants.get("FACTS_VERSION"), "task_item_6_present": item6_ok, "level_anchor_bullet_absent": anchor_bullet_gone,
            "restated_for": "revision 20", "details": bad[:20],
            "summary": f"{printed} printed references ({fenced} outside the fence); {capped} capped; TASK item 6 {'present' if item6_ok else 'MISSING'}, "
                       f"Level anchor bullet {'absent' if anchor_bullet_gone else 'STILL PRESENT'}; {no_pi_line} packs without the price_implied line; "
                       f"PACK_REVISION {constants.get('PACK_REVISION')}, FACTS_VERSION {constants.get('FACTS_VERSION')}; {len(bad)} problems"}


# ---- AT9 cash term alive -------------------------------------------------------------------------------------------------------------------------

def at9(rows, *, names=True):
    """Among the non-financial names with a printed reference and a filed cash figure, the cash term applies to at least 90%; an unknown
    fiscal year end and a missing bill rate count against it (reported by stamp)."""
    pop = applies = 0
    against = {}
    for r in _built(rows).values():
        c = r.get("cash")
        if r.get("status") not in PRINTED or not c or c.get("financial") or not c.get("filed"):
            continue
        pop += 1
        if c.get("applies"):
            applies += 1
        else:
            for s in (c.get("stamps") or ["no cash-term stamp"]):
                against[s] = against.get(s, 0) + 1
    share = applies / pop if pop else 0.0
    ok = pop > 0 and share >= 0.90
    return {"at": "AT9 cash term alive", "pass": ok, "population": pop, "applies": applies, "share": share, "not_applied_by_stamp": against,
            "bar": "at least 90%", "summary": f"the cash term applies to {applies} of {pop} = {share:.1%}; not applied: {against}"}

"""Build the day's record for a list of names (revision 18 acceptance, amendment 2 point 4). Offline, no model.

  python build_day.py --tree <rs2 worktree at the final commit> --root <data root: enrich/ cache/ research/> --sd <screener data dir>
                      --mri <MRI anchors dir> --date YYYY-MM-DD --names <book list> --out <day.json> [--closure <artifact>]
                      [--dump-dir <packs>] [--enrich-label book|closure_enrich:<vintage>] [--anonymous]

For each name: the pack (build_pack, include_research=False), the reference exactly as `consensus_reference.build` returned it for the pack,
and - revision 18 only - an INDEPENDENT call of `reference_inputs` (the ledger's production wiring: a fresh DataRoot, the files read again)
then `build`, the cash-term state, whether the history holds a filed cash figure, and the enrich record's source, date and sha256.
`--tree` may be revision 16's tree (fee17cf): the independent call and the closure are then skipped, and the row carries the `build` call
revision 16 received (AT1b, AT3 read it).

`--anonymous` (the 167 untouched names): rows are keyed by a hash of the name, no ticker is printed, logged or written (progress prints
counters; an error is recorded by its class), and no pack text is written. `build_rows` returns the rows (pack text included) in memory
for AT8, which never writes them.
"""
import argparse
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402

PRINTED = ("used", "outside_fence_above", "outside_fence_below")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _key(t, anonymous):
    return hashlib.sha256(t.encode()).hexdigest()[:12] if anonymous else t


def build_rows(ns, names, *, keep_text=True, anonymous=False, progress=True, dump_dir=None, enrich_label="book"):
    """(rows {key: row}, meta) for `names` on the bootstrapped day `ns`. See the module docstring for a row."""
    cap, cref, rs2 = ns.cap, ns.cref, ns.rs2
    has_ri = hasattr(cap, "reference_inputs")
    calls = []
    orig_build = cref.build

    def recording(*a, **k):
        out = orig_build(*a, **k)
        calls.append({"args": a, "kwargs": k, "out": out})
        return out
    cref.build = recording
    wiring = None
    if has_ri:
        import depth_membership
        import reference_ledger as rl
        depth_membership._current_book = lambda factor_path=None: list(names)
        wiring = rl.production_adapters(ns.root, today=ns.fixed.date())
        wiring.pop("book", None)
        enrich_fetch_failed = rl.EnrichFetchFailed if hasattr(rl, "EnrichFetchFailed") else ()
    rows, errors, enrich_n, ages = {}, {}, {}, []
    sd = Path(ns.sd)
    try:
        for i, t in enumerate(names, 1):
            calls.clear()
            err, text, facts = None, "", None
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    pack = cap.build_pack(t, include_research=False)
                text, facts = str(pack), pack.facts
                if dump_dir is not None and not anonymous:
                    Path(dump_dir).mkdir(parents=True, exist_ok=True)
                    (Path(dump_dir) / f"{t}.md").write_text(text, encoding="utf-8")
            except Exception as e:
                err = type(e).__name__ if anonymous else f"{type(e).__name__}: {str(e)[:300]}"
                errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
            row = {"ticker": None if anonymous else t, "error": err, "revision": getattr(cap, "PACK_REVISION", None), "n_builds": len(calls)}
            ep = Path(ns.root) / "enrich" / f"{t}.json"
            if ep.exists():
                doc = rs2.load_json(ep) or {}
                row["enrich"] = {"source": enrich_label, "date": str(doc.get("_fetched_at"))[:10] if doc.get("_fetched_at") else None,
                                 "sha256": ac.sha256_file(ep), "error_record": rs2.enrich_fetch_error(doc) is not None}
                enrich_n[enrich_label] = enrich_n.get(enrich_label, 0) + 1
                age = cap._age_days(doc) if hasattr(cap, "_age_days") else None
                if age is not None:
                    ages.append(age)
            if err is None:
                sector, _industry = rs2.sector_lookup(t)
                fin = rs2.load_json(sd / "financials" / f"{t}.json") or {}
                row.update(sector=sector, price=fin.get("Price"), facts=facts, text_len=len(text),
                           status=facts.get("reference_status"), printed_value=facts.get("consensus_implied_value"))
                if keep_text:
                    row["text"] = text                       # in memory; main() drops it before anything anonymous is written
                if calls:
                    k, out = calls[-1]["kwargs"], calls[-1]["out"]
                    a = calls[-1]["args"] or (k.get("base_cf"), k.get("estimates"), k.get("coe"), k.get("terminal_g"), k.get("shares"),
                                              k.get("median_5y"))
                    ref = {kk: out.get(kk) for kk in ("value", "method", "reason", "levels", "range", "path", "c1", "c2", "stub_months", "stamps",
                                                      "long_run_path", "terminal_ronic", "ronic0", "wc", "base_cf", "cash", "interest_removed",
                                                      "margin_ratio", "m_long", "om_5", "flows", "levels_reason")}
                    ref.update(base_arg=a[0], coe=a[2], terminal_g=a[3], shares=a[4], median_5y=a[5], da=k.get("da"), capex=k.get("capex"),
                               record_R_tc=(k.get("record") or {}).get("R_tc"), unavailable_reason=k.get("unavailable_reason"),
                               estimates=a[1], levels_reason_arg=k.get("levels_reason"))
                    row["reference"] = ref
                else:
                    row["reference"] = None
                row["parity"] = None
                if has_ri:
                    try:
                        inputs = wiring["inputs_fn"](t)
                        out2 = orig_build(**inputs)
                        pk = calls[-1]["kwargs"] if calls else {}
                        row["parity"] = {"pack_value": calls[-1]["out"].get("value") if calls else None, "ri_value": out2.get("value"),
                                         "pack_called_build": bool(calls),
                                         "args_equal": all(pk.get(x) == inputs.get(x) for x in ("coe", "shares", "terminal_g", "median_5y", "da",
                                                                                              "capex", "stub_months", "levels_block", "base_ni",
                                                                                              "base_revenue", "base_cf")) if calls else None}
                        cash = inputs.get("cash") or {}
                        h = ns.cap.DataRoot().history(t)
                        yrs = [int(y) for y in h if str(y).isdigit()]
                        cash_row = (h.get(str(max(yrs))) or {}).get("cash") if yrs else None
                        row["cash"] = {"filed": _num(cash_row), "applies": bool(cash.get("applies")), "financial": bool(cash.get("financial")),
                                       "stamps": list(cash.get("stamps") or [])}
                    except enrich_fetch_failed as e:        # a failed fetch: the pack says so; there is no reference to compare
                        row["parity"] = {"pack_value": None, "ri_value": None, "pack_called_build": bool(calls), "args_equal": None,
                                         "enrich_fetch_failed": True}
                    except Exception as e:
                        row["parity"] = {"error": type(e).__name__ if anonymous else f"{type(e).__name__}: {str(e)[:200]}"}
            rows[_key(t, anonymous)] = row
            if progress:
                if anonymous:
                    if i % 25 == 0 or i == len(names):
                        print(f"[{i}/{len(names)}] built", flush=True)
                else:
                    print(f"[{i}/{len(names)}] {t}", row.get("error") or
                          f"ref={(row.get('reference') or {}).get('value')} status={row.get('status')}", flush=True)
    finally:
        cref.build = orig_build
    meta = {"n": len(rows), "errors_by_class": errors, "enrich_by_source": enrich_n,
            "enrich_age_days_max": max(ages) if ages else None, "enrich_age_days_over_45": sum(1 for a in ages if a > 45)}
    return rows, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--sd", required=True, type=Path)
    ap.add_argument("--mri", required=True, type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--names", required=True, type=Path)
    ap.add_argument("--names-sha256", default=None, help="refuse the list unless it has this sha256 (a prefix of 8+ characters)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--closure", default=None, type=Path)
    ap.add_argument("--dump-dir", default=None, type=Path)
    ap.add_argument("--enrich-label", default="book")
    ap.add_argument("--anonymous", action="store_true")
    a = ap.parse_args(argv)
    names = ac.load_names(a.names, a.names_sha256)
    ns = ac.bootstrap(a.tree, a.sd, a.mri, a.root, a.date, closure=a.closure)
    rows, meta = build_rows(ns, names, keep_text=True, anonymous=a.anonymous, dump_dir=a.dump_dir, enrich_label=a.enrich_label)
    if a.anonymous:
        for r in rows.values():
            r.pop("text", None)
    meta["constants"] = ac.constants(ns)
    meta["inputs"] = ac.inputs_record(ns, extra_files=[a.names] if not a.anonymous else [])
    meta["names_sha256"] = ac.sha256_file(a.names)
    if hasattr(ns.rs2, "reference_closure"):
        erp, asof, _prov = ns.rs2.reference_closure()
        meta["closure"] = {"erp": erp, "asof": asof}
    ac.write_result(a.out, {"meta": ac.jsonable(meta), "rows": ac.jsonable(rows)})
    print("->", a.out, "names:", meta["n"], "errors:", sum(meta["errors_by_class"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

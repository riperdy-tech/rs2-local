"""Addendum AD: the G5 re-check accepts a D-part citation exactly as the pipeline does, and the behaviour tool counts and gates a known run folder."""
import json
from pathlib import Path

from rebuild_harness.gate2 import behaviour, integrity

D_TEXT = ("[D1] Annual report (Form 10-K): business description, filed 2025-02-11\nWe operate a global network of routes.\n\n"
          "[D2] Earnings release (8-K, Item 2.02), filed 2025-10-09\nFor the December quarter, we expect total revenue growth of 2 percent to 4 percent.")
USER = ("Analysis date: 2025-10-31\n\n=== SECTION F: Filed financial history ===\nRevenue | 40,704.0\n\n=== SECTION D: Primary documents ===\n" + D_TEXT +
        "\n\n=== SECTION S: Company state ===\nSize: revenue 61,643.0\n\n=== SECTION R: Population priors ===\n[R g1] P50 4.0%\n")


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def _response(content, reasoning="x" * 1000, finish="stop"):
    return {"choices": [{"message": {"content": content, "reasoning_content": reasoning}, "finish_reason": finish}], "usage": {}}


def make_run(root: Path, key="2025-10-31_0000000001", *, d_part="D2", first_ok=True, p5_ok=True, unanchored=False, pct=70.0, width="normal"):
    run = root / "runs" / "2025-10-31" / key / "a01"
    run.mkdir(parents=True)
    quote = "we expect total revenue growth of 2 percent to 4 percent"
    entry = {"percentile": pct, "width": width, "reasons": ["guided growth"], "citations": [{"section": d_part, "quote": quote}]}
    p1 = {"inputs": {"g1": entry, "growth_persistence": entry}, "bull_case": {"text": "Up.", "citation": {"section": "S", "quote": "Size: revenue 61,643.0"}},
          "bear_case": {"text": "Down.", "citation": {"section": "F", "quote": "Revenue | 40,704.0"}}}
    _write(run / "01_P1_a1_request.json", {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": USER}]})
    _write(run / "01_P1_a1_response.json", _response(json.dumps(p1) if first_ok else json.dumps(p1)[:-1]))
    seq = 2
    if not first_ok:
        _write(run / "02_P1_a2_request.json", {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": USER}]})
        _write(run / "02_P1_a2_response.json", _response(json.dumps(p1)))
        seq = 3
    _write(run / f"0{seq}_P5_a1_request.json", {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "Analysis date: 2025-10-31\nP5"}]})
    _write(run / f"0{seq}_P5_a1_response.json", _response('{"inputs": {}}'))
    status = "unanchored" if unanchored else "anchored"
    pos = {"percentile": 50.0 if unanchored else pct, "width": "wide" if unanchored else width, "status": status, "source": "P1", "stamps": []}
    result = {"status": "ok", "family": "operating",
              "calls": [{"call": "P1", "ok": True, "retried": not first_ok, "issues": []}, {"call": "P5", "ok": p5_ok, "retried": False, "issues": []}],
              "pass1": {"positions": {"g1": pos, "growth_persistence": pos}}, "final": {"positions": {"g1": pos, "growth_persistence": pos}},
              "redteam": {"decisions": [{"input": "g1", "proposed": True, "accepted": True, "toward_price": True, "new_quote": False, "named_error": True}]}}
    _write(run / "result.json", result)
    _write(run / "run_manifest.json", {"asof": "2025-10-31"})
    job = {"integrity": integrity.verify_run_dir(run)}
    _write(run / "job.json", job)
    with open(root / "progress.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"key": key, "status": "ok"}) + "\n")
    return run


def test_integrity_accepts_the_d_part_citation_the_pipeline_accepted_and_refuses_a_wrong_part(tmp_path):
    ok = integrity.verify_run_dir(make_run(tmp_path / "a", d_part="D2"))
    assert ok["n_citations"] == 2 and ok["n_citations_failed"] == 0
    bad = integrity.verify_run_dir(make_run(tmp_path / "b", d_part="D1"))      # the quote is in D2, not D1
    # Addendum AJ.5 (operator 2026-10-12): verbatim in another part of the same section shown is a part-label error, reported, not a quote failure
    assert bad["n_citations_failed"] == 0 and bad["n_part_label_errors"] == 2 and {e["found_in"] for e in bad["part_label_errors"]} == {"D2"}


def test_behaviour_counts_a_known_run_and_the_gate_reads_it(tmp_path):
    make_run(tmp_path, "2025-10-31_0000000001", first_ok=True)
    make_run(tmp_path, "2025-10-31_0000000002", first_ok=False, p5_ok=False)
    make_run(tmp_path, "2025-10-31_0000000003", unanchored=True)
    m = behaviour.measure(tmp_path, leakage=False)
    assert m["n_with_model_calls"] == 3
    assert m["first_parse"]["P1"] == {"n": 3, "ok": 2, "share": 2 / 3}
    assert abs(m["unanchored_final"] - 2 / 6) < 1e-12 and abs(m["identical_to_code"] - 2 / 6) < 1e-12
    assert abs(m["p5_success"] - 2 / 3) < 1e-12
    assert m["redteam"]["toward_without_new_quote"] == 3 and m["redteam"]["with_named_error"] == 3
    g = behaviour.gate(m)
    assert g["verdict"] == "STOP" and g["passes"]["first_parse"] is False and g["passes"]["unanchored"] is False
    assert "reasoning" in g["not_evaluated"] and "leakage" in g["not_evaluated"]   # never silently passed


def test_behaviour_gate_passes_a_clean_run_and_pairs_reasoning_with_a_reference(tmp_path):
    for i in range(3):
        make_run(tmp_path / "now", f"2025-10-31_000000000{i}")
        make_run(tmp_path / "ref", f"2025-10-31_000000000{i}")
    m = behaviour.measure(tmp_path / "now")
    ref = behaviour.measure(tmp_path / "ref", leakage=False)
    assert m["leakage_violations"] == 0
    g = behaviour.gate(m, ref)
    assert g["reasoning_ratios"] == {"P1": 1.0, "P5": 1.0} and g["verdict"] == "PASS"
    half = dict(m, reasoning_chars={k: v // 2 for k, v in m["reasoning_chars"].items()})
    assert behaviour.gate(half, ref)["stops"]["reasoning"] is True

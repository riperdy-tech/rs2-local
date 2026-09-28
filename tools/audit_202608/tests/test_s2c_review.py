"""Reviewer's tests for the S2c review (2026-09-28), one or more per defect fixed or gap closed.

1. The revision-15 DEFAULTS reader never infers consensus_data_status from another key. An absent
   line is None (the build had inferred "ok" or "estimates_unavailable", both of which pass the gate),
   and "not available" is None, as for every other key of that reader.
2. That None fails the gate closed on gate_version 6.
3. The legacy reader returns None for a text with no SECTION 8 (the brief's sixth row).
4. An absent status on a gate_version 5 row gives exactly ["pre_v3.1_gates"]; the producer_class
   rule's boundary at gate_version 5, which the edited v5 test no longer pins, is pinned here.
5. The ::PACK DATA:: line comes before the first sample's output.
6. The battery refuses a frozen pack on reuse, not only on build, when its printed status is
   enrich_missing or stale (the E17 L2 packs were frozen before the pre-flight existed).
7. Reviewer ruling: "estimates_unavailable" fails the gate too, and the battery refuses it. The
   production enrich cache (rs2-local/enrich, fetched 2026-06 to 2026-08 by a fetcher without
   estimates) would give that status to 135 of the 176 book names; a failed fetch gives it as well.
   Only "ok" passes; an unknown status fails on any gate_version.
"""
import json
from pathlib import Path
import sys
import urllib.request

import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import depth_gates  # noqa: E402
import pack_facts  # noqa: E402
import tools.dispersion_battery as db  # noqa: E402

_DEFAULTS = """# DATA PACK - TST   (pack revision 15)

## DEFAULTS   [each desk input takes this value unless you pass another]
- shares_outstanding: <61,443,377> | SECTION 2
- consensus_implied_value: <58.92> (<used>) | the reference
{status_line}- revenue_cagr_5y_pct: <+9.1%> | the 5y CAGR
"""


def _defaults(status_line=""):
    return pack_facts.from_text(_DEFAULTS.format(status_line=status_line))


def test_defaults_block_without_a_status_line_is_none_not_inferred():
    f = _defaults()
    assert f["source"] == "defaults_block"
    assert f["consensus_implied_value"] == pytest.approx(58.92)
    assert f["consensus_data_status"] is None          # the build inferred "ok" here
    no_civ = pack_facts.from_text(_DEFAULTS.format(status_line="").replace(
        "- consensus_implied_value: <58.92> (<used>) | the reference\n", ""))
    assert no_civ["consensus_implied_value"] is None
    assert no_civ["consensus_data_status"] is None     # the build inferred "estimates_unavailable" here


def test_defaults_block_status_line_is_read_verbatim():
    assert _defaults("- consensus_data_status: <enrich_missing> | SECTION 8\n")[
        "consensus_data_status"] == "enrich_missing"
    assert _defaults("- consensus_data_status: <ok> | SECTION 8\n")["consensus_data_status"] == "ok"
    assert _defaults("- consensus_data_status: <not available> | SECTION 8\n")[
        "consensus_data_status"] is None


def _clean_v6(**over):
    v = {"direction": "undervalued", "gate_version": 6, "n_basis": 2, "fiduciary_verdict": "PASS",
         "kelly_fraction_pct": 5.0, "spread_pct": 10.0, "run_source": "orchestrator",
         "street_fence": {"low": 100.0, "high": 150.0}, "median_iv": 120.0, "mos_vs_base_pct": 20.0,
         "flags": [], "producer_class": {"status": "ok", "depleting": False},
         "consensus_data_status": "ok"}
    v.update(over)
    return v


def test_a_status_the_reader_could_not_find_fails_closed():
    assert depth_gates.assess(_clean_v6()) == (True, [])
    status = _defaults()["consensus_data_status"]
    ok, reasons = depth_gates.assess(_clean_v6(consensus_data_status=status))
    assert ok is False and reasons == ["consensus_data_unavailable"]


def test_legacy_text_without_section_8_is_none():
    text = "# DATA PACK - TST\n\n## SECTION 7 - FILING-DERIVED QUALITY MEASURES\n- nothing here\n"
    assert pack_facts.from_text(text)["consensus_data_status"] is None


def test_absent_status_on_gate_version_5_gives_only_pre_v31():
    v = _clean_v6(gate_version=5)
    del v["consensus_data_status"]
    assert depth_gates.assess(v) == (False, ["pre_v3.1_gates"])


def test_producer_rule_boundary_stays_at_gate_version_5():
    # test_depth_gates_v5's base row moved from gate_version 5 to GATE_VERSION with this change, so
    # nothing else pins the producer_class rule's boundary at 5 any more.
    v5 = _clean_v6(gate_version=5)
    del v5["producer_class"]
    assert depth_gates.assess(v5) == (False, ["pre_v3.1_gates", "depleting_producer_class_unavailable"])
    v4 = _clean_v6(gate_version=4)
    del v4["producer_class"]
    assert depth_gates.assess(v4) == (False, ["pre_v3.1_gates"])


MEMO = ("SECTION 0. EXECUTIVE VERDICT\n" + "\n".join(f"  detail line {n}." for n in range(400))
        + "\nSECTION 12. MACHINE CONTRACT\n```json:underwriting\n"
        '{"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0, "conviction_score": 10}\n```\n')


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False


def test_pack_data_line_precedes_the_first_sample(monkeypatch, tmp_path, screener_data_stub, capsys):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp(
        {"message": {"content": MEMO}, "done_reason": "stop", "eval_count": 5, "prompt_eval_count": 5}))
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    pack = "# DATA PACK - GEV\n\n## SECTION 8 - CONSENSUS & MULTIPLES\n" \
           "- CONSENSUS ESTIMATES: not available — stale (> 45 days)\n"
    (frozen / "_pack.md").write_text(pack, encoding="utf-8")   # no sidecar: the legacy reader decides
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
                                      "--no-early-stop", "--pack-file", str(frozen / "_pack.md"),
                                      "--out-dir", str(out)])
    cv.main()
    printed = capsys.readouterr().out
    assert "::PACK DATA:: stale" in printed
    assert "sample 1" in printed
    assert printed.index("::PACK DATA::") < printed.index("sample 1")
    doc = json.loads((next(out.glob("GEV_*")) / "consensus.json").read_text(encoding="utf-8"))
    assert doc["consensus_data_status"] == "stale" and doc["pack_facts_source"] == "text"


@pytest.mark.parametrize("line, status", [
    ("- CONSENSUS ESTIMATES: not available — enrich record missing", "enrich_missing"),
    ("- CONSENSUS ESTIMATES: not available — stale (> 45 days)", "stale"),
])
def test_battery_refuses_a_bad_frozen_pack_on_reuse(monkeypatch, tmp_path, line, status):
    pack_path = tmp_path / "XYZ" / "_pack.md"
    pack_path.parent.mkdir(parents=True)
    pack_path.write_text(f"# DATA PACK - XYZ\n\n## SECTION 8 - CONSENSUS & MULTIPLES\n{line}\n", encoding="utf-8")

    def _no_build(name):
        raise AssertionError("a frozen pack on disk must not be rebuilt")
    monkeypatch.setattr(cap, "build_pack", _no_build)
    with pytest.raises(SystemExit) as exc:
        db.build_frozen_pack("XYZ", pack_path)
    assert f"XYZ: cannot reuse frozen pack with consensus_data_status='{status}'" in str(exc.value)


def test_battery_reuses_a_good_frozen_pack(monkeypatch, tmp_path):
    pack_path = tmp_path / "XYZ" / "_pack.md"
    pack_path.parent.mkdir(parents=True)
    text = ("# DATA PACK - XYZ\n\n## SECTION 8 - CONSENSUS & MULTIPLES\n"
            "- CONSENSUS ESTIMATES   [yfinance, fetched 2026-09-27; sell-side estimates, not company guidance]\n")
    pack_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(cap, "build_pack", lambda name: (_ for _ in ()).throw(AssertionError("rebuilt")))
    assert db.build_frozen_pack("XYZ", pack_path) == (text, True)


@pytest.mark.parametrize("status", ["estimates_unavailable", "enrich_missing", "stale", "point_in_time",
                                    "unknown_value"])
def test_only_ok_passes_on_any_gate_version(status):
    for gv in (5, 6):
        ok, reasons = depth_gates.assess(_clean_v6(gate_version=gv, consensus_data_status=status))
        assert ok is False and "consensus_data_unavailable" in reasons
    assert depth_gates.assess(_clean_v6(consensus_data_status="ok")) == (True, [])


def test_battery_refuses_estimates_unavailable_on_build_and_reuse(monkeypatch, tmp_path):
    facts = pack_facts.empty()
    facts["consensus_data_status"] = "estimates_unavailable"
    monkeypatch.setattr(cap, "build_pack", lambda name: cap.PackText("fake pack", facts=facts))
    built = tmp_path / "A" / "_pack.md"
    with pytest.raises(SystemExit) as exc:
        db.build_frozen_pack("XYZ", built)
    assert "cannot build frozen pack with consensus_data_status='estimates_unavailable'" in str(exc.value)
    assert not built.exists()
    reused = tmp_path / "B" / "_pack.md"
    reused.parent.mkdir(parents=True)
    reused.write_text("# DATA PACK - XYZ\n\n## SECTION 8 - CONSENSUS & MULTIPLES\n"
                      "- CONSENSUS ESTIMATES: not available \u2014 yfinance estimates unavailable\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        db.build_frozen_pack("XYZ", reused)
    assert "cannot reuse frozen pack with consensus_data_status='estimates_unavailable'" in str(exc.value)

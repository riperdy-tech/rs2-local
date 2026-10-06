"""Pack v2: sections from the point-in-time data only, nothing about price or availability, the acceptance cutoff on documents (placeholder priors: test-only)."""
import inspect

import pytest

from valuation.common import build_state
from valuation.muse import leakage_audit, pack_v2
from valuation.muse.documents import eligibility
from valuation.muse.tests import fixtures as fx


def pack(asof=fx.ASOF, documents=None, quarters=None, family="operating", **kw):
    pit = fx.make_pit(asof=asof, **kw)
    st = build_state(pit)
    ps = fx.LabeledPlaceholderPriors().for_company(family, st, pit.asof)
    return pack_v2.build_pack(pit, family, fx.IDENTITY, ps, state=st, documents=documents, quarters=quarters), pit


def test_header_is_the_date_the_name_the_family_and_the_industry_and_nothing_else():
    p, _ = pack(documents=fx.docs())
    assert p.header == "Analysis date: 2026-04-15\nCompany: Synthetic Co (SYN)\nFamily: operating\nIndustry: Test industry"


def test_f_holds_ten_years_of_filed_values_and_no_provenance():
    p, pit = pack()
    lines = p.sections["F"].split("\n")
    assert lines[1].count("|") == 10 and "2016-12-31" in lines[1] and "2025-12-31" in lines[1]
    assert any(l.startswith("Revenue | ") for l in lines)
    assert "ACC-" not in p.sections["F"] and "10-K" not in p.sections["F"]          # the appendix is not in the section
    assert {"field": "revenue", "period_end": "2025-12-31"}.items() <= next(r for r in p.provenance if r["field"] == "revenue" and r["period_end"] == "2025-12-31").items()
    assert next(r for r in p.provenance if r["period_end"] == "2025-12-31")["accession"] == "ACC-2025-12-31"


def test_a_filing_after_T_changes_nothing():
    a, _ = pack(asof="2025-04-15")                       # FY2025's report (filed 2026-03-01) does not exist yet
    b, _ = pack(asof="2025-04-15", years=9)              # a company that never filed it
    assert a.sections["F"] == b.sections["F"] and a.sections["S"] == b.sections["S"] and a.r == b.r
    assert "2025-12-31" not in a.sections["F"]


def test_q_is_built_only_with_a_quarter_source_and_the_manifest_says_so():
    p0, _ = pack()
    assert "Q" not in p0.sections and any("section Q absent" in s for s in p0.manifest["stamps"])
    p1, _ = pack(quarters=fx.quarters())
    assert "2025-09-30" in p1.sections["Q"] and "410.0" in p1.sections["Q"]
    late = fx.quarters()
    late.rows[0]["filed"], late.rows[0]["accepted_at"] = "2026-04-15", "2026-04-15T20:00:01.000Z"
    p2, _ = pack(quarters=late)
    assert "Q" not in p2.sections and p2.manifest["quarters"]["dropped_after_cutoff"]


def test_d_items_accepted_after_the_16h00_et_cutoff_are_dropped_and_recorded():
    p, _ = pack(documents=fx.docs(filed_after=True))
    assert "Late release text" not in p.sections["D"]
    assert [i["accession"] for i in p.manifest["documents"]["dropped_after_cutoff"]] == ["ACC-8K-LATE"]
    assert p.sections["D"].startswith("[D1] Annual report (Form 10-K): business description, filed 2026-02-28")


@pytest.mark.parametrize("accepted,filed,expected", [
    ("2026-04-15T19:59:59.000Z", "2026-04-15", "ok"),         # 15:59:59 EDT
    ("2026-04-15T20:00:00.000Z", "2026-04-15", "ok"),         # 16:00:00 EDT exactly
    ("2026-04-15T20:00:01.000Z", "2026-04-15", "invalid"),
    (None, "2026-04-14", "ok"),
    (None, "2026-04-15", "ambiguous"),
    (None, "2026-04-16", "invalid"),
])
def test_eligibility_follows_the_shared_layers_rule(accepted, filed, expected):
    assert eligibility(accepted, filed, "2026-04-15") == expected


def test_the_winter_cutoff_is_21h00_utc():
    assert eligibility("2026-01-15T20:59:59.000Z", "2026-01-15", "2026-01-15") == "ok"
    assert eligibility("2026-01-15T21:00:01.000Z", "2026-01-15", "2026-01-15") == "invalid"


def test_the_builder_cannot_carry_a_price_and_no_section_outside_d_holds_forbidden_wording():
    params = set(inspect.signature(pack_v2.build_pack).parameters)
    assert not {p for p in params if any(w in p for w in ("price", "cap", "return", "target", "consensus", "news", "valuation"))}
    p, _ = pack(documents=fx.docs(), quarters=fx.quarters())
    asof = leakage_audit.date.fromisoformat(fx.ASOF)
    bad = []
    for name, text in {**{k: v for k, v in p.sections.items() if k != "D"}, **p.r}.items():
        bad += leakage_audit.scan_text(text, asof, name, pass1=True)
    assert bad == []
    assert "replay" not in (p.header + "".join(p.sections.values()) + "".join(p.r.values())).lower()


def test_r_holds_the_prior_and_the_mechanical_baseline_per_input():
    p, _ = pack()
    assert list(p.r) == ["g1", "growth_persistence", "margin_target", "margin_retention", "ronic", "g_terminal"]
    assert "Mechanical baseline (trailing 3-year compound growth)" in p.r["g1"]
    assert "P5" in p.r["g1"] and "P95" in p.r["g1"] and "~" in p.r["g1"]               # P5/P95 are extrapolated for a P10/P50/P90 prior
    assert "Mechanical baseline" not in p.r["ronic"]


def test_each_prompt_sees_only_its_sections():
    p, _ = pack(documents=fx.docs(), quarters=fx.quarters())
    assert set(p.sections_for("P1", ["g1", "growth_persistence"])) == {"F", "Q", "D", "S", "R"}
    assert set(p.sections_for("P3", ["ronic"])) == {"F", "D", "S", "R"}
    assert set(p.sections_for("P5")) == {"S", "R"} and set(p.sections_for("P6")) == {"S", "R"}
    r = p.sections_for("P2", ["margin_target"])["R"]
    assert "[R margin_target]" in r and "[R g1]" not in r


def test_state_section_has_the_spec_items():
    p, _ = pack()
    s = p.sections["S"]
    for key in ("Size:", "Growth delivered:", "Operating margin:", "deviation", "Cyclicality score:", "Return on capital:"):
        assert key in s
    pf, _ = pack(family="financial", sic="6021")
    assert "Return on tangible equity" in pf.sections["S"]
    assert list(pf.r) == ["g1", "growth_persistence", "rote_target", "rote_retention", "g_terminal"]

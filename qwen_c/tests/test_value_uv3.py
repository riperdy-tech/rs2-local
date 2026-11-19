"""WO_UV3 part B: figures read from the inline XBRL of the newest annual filing, on small synthetic documents only.
For each reading: the accepted case, every refusal (a check that fails leaves the old refusal standing), and that a company that needs none is
unchanged and the document is not even read."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_facts import T, fy
from qwen_c.tests.test_value_inputs import base, series
from qwen_c.value import desk, facts, inputs, ix_figures, ixbrl

ACC, OLD = "0001-26-000010", "0001-25-000010"
UNITS = ('<xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
         '<xbrli:unit id="CNY"><xbrli:measure>iso4217:CNY</xbrli:measure></xbrli:unit>'
         '<xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>'
         '<xbrli:unit id="eps"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>'
         '<xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>')
YEARS = ("2023", "2024", "2025")


def ctx(cid, start, end, dims=()):
    members = "".join(f'<xbrldi:explicitMember dimension="{a}">{m}</xbrldi:explicitMember>' for a, m in dims)
    seg = f"<xbrli:segment>{members}</xbrli:segment>" if members else ""
    per = f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>" if start else f"<xbrli:instant>{end}</xbrli:instant>"
    return f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>{seg}</xbrli:entity><xbrli:period>{per}</xbrli:period></xbrli:context>'


def year_ctx(prefix="c", dims=()):
    return "".join(ctx(f"{prefix}{y}", f"{y}-01-01", f"{y}-12-31", dims) for y in YEARS)


def nf(name, c, text, unit="USD", dec="-3", scale="3", fmt="ixt:num-dot-decimal", sign=None):
    s = ' sign="-"' if sign else ""
    return (f'<ix:nonFraction name="{name}" contextRef="{c}" unitRef="{unit}" decimals="{dec}" scale="{scale}" format="{fmt}"{s}>{text}</ix:nonFraction>')


def cells(name, vals, shown="out", prefix="c", **kw):
    """The three year cells of one statement row: None is a blank cell (no tag); shown "out" prints in parentheses."""
    out = []
    for y, v in zip(YEARS, vals):
        if v is None:
            out.append("<td></td>")
            continue
        t = nf(name, f"{prefix}{y}", f"{abs(v):,}" if v != 0 else "-", fmt="ixt:fixed-zero" if v == 0 else "ixt:num-dot-decimal", **kw)
        out.append(f"<td>({t})</td>" if shown == "out" and v != 0 else f"<td>{t}</td>")
    return "<tr><td>label</td>" + "".join(out) + "</tr>"


def document(*parts, extra_ctx=""):
    return f"<html><body><xbrli:resources>{UNITS}{year_ctx()}{extra_ctx}</xbrli:resources>{''.join(parts)}</body></html>"


def cash_flow(lines, op=(500, 500, 500), tot=None):
    """A cash-flow table: an operating subtotal, the investing lines [(tag, [v23, v24, v25] or with None blanks, "out" | "in")], the investing
    subtotal (computed from the lines unless `tot` gives it), a financing line after it. Values in thousands."""
    rows = [cells("us-gaap:NetCashProvidedByUsedInOperatingActivities", op, "in")]
    for tag, vals, shown in lines:
        rows.append(cells(tag, vals, shown))
    if tot is None:
        tot = [sum((-v if shown == "out" else v) for _, vs, shown in lines for v in [vs[i]] if v is not None) for i in range(3)]
    sub = ["<tr><td>Net cash used in investing</td>"]
    for y, t in zip(YEARS, tot):
        s = nf("us-gaap:NetCashProvidedByUsedInInvestingActivities", f"c{y}", f"{abs(t):,}", sign=t < 0)
        sub.append(f"<td>({s})</td>" if t < 0 else f"<td>{s}</td>")
    rows.append("".join(sub) + "</tr>")
    rows.append(cells("us-gaap:PaymentsOfDividends", [10, 10, 10]))
    return "<table>" + "".join(rows) + "</table>"


def source(html, report="2025-12-31", acc=ACC):
    return ix_figures.Source(ixbrl.parse(html), acc, "10-K", "2026-02-20", report, "https://www.sec.gov/Archives/edgar/data/1/x/x.htm")


# ---- the reader ---------------------------------------------------------------------------------------------------------------------------

def test_scale_and_sign_come_from_the_tags_attributes():
    d = ixbrl.parse(document(nf("a:X", "c2025", "1,234.5", scale="3"), nf("a:Y", "c2025", "7", scale="6", sign=True), nf("a:Z", "c2025", "9", scale="0")))
    got = {f.name: f.value for f in d.facts}
    assert got == {"a:X": 1234500.0, "a:Y": -7e6, "a:Z": 9.0}


def test_a_tagged_dash_is_a_filed_zero_and_an_unknown_format_or_odd_text_is_unreadable_never_guessed():
    d = ixbrl.parse(document(nf("a:X", "c2025", "-", fmt="ixt:fixed-zero"), nf("a:Y", "c2025", "&#8212;", fmt="ixt-sec:zerodash"),
                             nf("a:W", "c2025", "1 234", fmt="ixt:numspacedot"), nf("a:V", "c2025", "n/a"), nf("a:U", "c2025", "5", scale="x")))
    assert {f.name: f.value for f in d.facts} == {"a:X": 0.0, "a:Y": 0.0} and d.unreadable == 3


def test_a_comma_decimal_number_reads_by_its_format_and_a_nil_fact_is_not_a_value():
    d = ixbrl.parse(document(nf("a:X", "c2025", "1.234,5", fmt="ixt:num-comma-decimal", scale="0"),
                             '<ix:nonFraction name="a:N" contextRef="c2025" unitRef="USD" xsi:nil="true"/>'))
    assert [(f.name, f.value) for f in d.facts] == [("a:X", 1234.5)]


def test_a_tag_nested_in_another_reads_the_printed_text_once():
    inner = nf("a:X", "c2025", "841,176")
    d = ixbrl.parse(document(inner.replace(">841,176<", f">{inner}<")))
    assert [(f.name, f.value) for f in d.facts] == [("a:X", 841176000.0)]


def test_context_period_unit_dimension_row_table_and_parentheses_are_read():
    html = document(f"<table><tr><td>({nf('a:X', 'd2025', '0.67', unit='eps', dec='2', scale='0')})</td></tr></table>"
                    f"<table><tr><td>{nf('a:Y', 'c2025', '5')}</td></tr></table>",
                    extra_ctx=ctx("d2025", "2025-01-01", "2025-12-31", [("us-gaap:StatementClassOfStockAxis", "us-gaap:CommonClassBMember")]))
    x, y = ixbrl.parse(html).facts
    assert (x.unit, x.dims, x.start, x.end, x.decimals, x.neg) == ("USD/shares", (("us-gaap:StatementClassOfStockAxis", "us-gaap:CommonClassBMember"),),
                                                                    "2025-01-01", "2025-12-31", 2, True)
    assert x.table != y.table and y.neg is False and y.unit == "USD" and y.decimals == -3


# ---- reading 1: a year companyfacts has not ingested ---------------------------------------------------------------------------------

def subs_new(report="2025-12-31", primary="x.htm"):
    rows = [(OLD, "10-K", "2025-02-21", "2025-02-21T16:05:00.000Z", "2024-12-31"), (ACC, "10-K", "2026-02-20", "2026-02-20T16:05:00.000Z", report)]
    cols = list(zip(*rows))
    return {"filings": {"recent": {"accessionNumber": list(cols[0]), "form": list(cols[1]), "filingDate": list(cols[2]),
                                   "acceptanceDateTime": list(cols[3]), "reportDate": list(cols[4]), "primaryDocument": [primary, primary]}}}


def cf_old(**tags):
    rows = lambda vs: [fy(e, v, OLD, filed="2025-02-21") for e, v in zip(("2023-12-31", "2024-12-31"), vs)]     # noqa: E731
    return {"facts": {"us-gaap": {t: {"units": {u: rows(v)}} for t, (u, v) in tags.items()}}}


def doc_new(rev=(100_000, 120_000, 150_000), ni=(8_000, 10_000, 12_000), pri_rev=None):
    """thousands: three years of revenue and net income, plain contexts"""
    parts = [f"<table>{cells('us-gaap:Revenues', rev, 'in')}{cells('us-gaap:NetIncomeLoss', ni, 'in')}</table>"]
    return document(*parts)


def annual(cf, doc, report="2025-12-31", loader_calls=None, **kw):
    def loader():
        if loader_calls is not None:
            loader_calls.append(1)
        return source(doc, report)
    return facts.annual_facts(cf, subs_new(report), T, ix=loader, **kw)


def test_a_year_companyfacts_lacks_is_read_when_the_prior_year_column_agrees():
    out = annual(cf_old(Revenues=("USD", (100e6, 120e6)), NetIncomeLoss=("USD", (8e6, 10e6))), doc_new())
    rev = {v["end"]: v for v in out["revenue"]["values"]}
    assert rev["2025-12-31"]["value"] == 150e6 and rev["2025-12-31"]["tag"] == "Revenues" and rev["2025-12-31"]["accn"] == ACC
    assert rev["2025-12-31"]["stamp"] == f"ix_read:revenue:{ACC}:us-gaap:Revenues"
    assert out["net_income"]["values"][-1]["value"] == 12e6 and out["_ix"]["read"] == {"new_year": ["revenue", "net_income"]} and out["_ix"]["accession"] == ACC
    assert out["_stale"] == {}


def test_a_prior_year_column_that_does_not_match_companyfacts_leaves_the_year_unread():
    out = annual(cf_old(Revenues=("USD", (100e6, 121e6))), doc_new())             # 120 in the filing, 121 in companyfacts
    assert out["revenue"]["values"][-1]["end"] == "2024-12-31" and "_ix" in out and out["_ix"]["read"] == {}


def test_the_match_is_to_the_rounding_of_the_printed_figure():
    assert annual(cf_old(Revenues=("USD", (100e6, 120e6 + 400))), doc_new())["revenue"]["values"][-1]["end"] == "2025-12-31"          # printed in thousands: 500 allowed
    assert annual(cf_old(Revenues=("USD", (100e6, 120e6 + 600))), doc_new())["revenue"]["values"][-1]["end"] == "2024-12-31"


def test_a_tag_companyfacts_does_not_carry_for_the_prior_year_cannot_be_verified_and_is_not_read():
    out = annual(cf_old(Revenues=("USD", (100e6, 120e6))), doc_new())             # no NetIncomeLoss in companyfacts at all
    assert "net_income" not in out and out["_absent"]["net_income"]


def test_a_unit_other_than_the_listed_one_is_not_read():
    html = document(f"<table>{cells('us-gaap:Revenues', (100_000, 120_000, 150_000), 'in', unit='CNY')}</table>")
    assert annual(cf_old(Revenues=("USD", (100e6, 120e6))), html)["revenue"]["values"][-1]["end"] == "2024-12-31"


def test_a_dimensioned_fact_is_not_a_year_of_the_company():
    html = document(f"<table>{cells('us-gaap:Revenues', (100_000, 120_000, 150_000), 'in', prefix='m')}</table>",
                    extra_ctx=year_ctx("m", [("us-gaap:StatementBusinessSegmentsAxis", "a:SegMember")]))
    assert annual(cf_old(Revenues=("USD", (100e6, 120e6))), html)["revenue"]["values"][-1]["end"] == "2024-12-31"


def test_two_values_for_one_year_are_ambiguous_and_not_read():
    html = document(f"<table>{cells('us-gaap:Revenues', (100_000, 120_000, 150_000), 'in')}</table>"
                    f"<table>{cells('us-gaap:Revenues', (100_000, 120_000, 151_000), 'in')}</table>")
    assert annual(cf_old(Revenues=("USD", (100e6, 120e6))), html)["revenue"]["values"][-1]["end"] == "2024-12-31"


def test_a_year_companyfacts_carries_is_never_replaced_and_the_document_is_not_read_when_nothing_is_missing():
    calls = []
    cf_all = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fy("2024-12-31", 120e6, OLD, filed="2025-02-21"), fy("2025-12-31", 149e6, ACC)]}},
                                    "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fy("2025-12-31", 10.0, ACC)]}}}}}
    out = annual(cf_all, doc_new(), loader_calls=calls)
    assert out["revenue"]["values"][-1]["value"] == 149e6 and calls == [] and "_ix" not in out


def test_without_a_loader_nothing_is_read():
    out = facts.annual_facts(cf_old(Revenues=("USD", (100e6, 120e6))), subs_new(), T)
    assert out["revenue"]["values"][-1]["end"] == "2024-12-31" and "_ix" not in out


def test_a_document_that_is_not_the_newest_report_is_not_used():
    assert annual(cf_old(Revenues=("USD", (100e6, 120e6))), doc_new(), report="2024-12-31")["revenue"]["values"][-1]["end"] == "2024-12-31"


def test_load_returns_none_when_the_document_is_not_in_the_store(tmp_path):
    from datetime import datetime, timezone
    row = subs_new()
    assert ix_figures.load("1", row, datetime(2026, 12, 1, tzinfo=timezone.utc), online=False, root=tmp_path) is None
    assert ix_figures.document_url("0000000001", {"accession": ACC, "primary_document": "x.htm"}) == f"https://www.sec.gov/Archives/edgar/data/1/{ACC.replace('-', '')}/x.htm"


# ---- reading 2: capital spending under a company's own tags -----------------------------------------------------------------------------

VESSELS = [("x:InvestmentsInVessels", [100, 60, 111], "out"), ("x:InvestmentInVesselsUnderConstruction", [0, 90, 199], "out"),
           ("x:ProceedsFromSaleOfVessels", [0, 0, 143], "in")]


def capex_out(have=None, lines=VESSELS, tag="T", **kw):
    """(the series after the reading, the years read) for a cash-flow table of `lines`; `have`: {end: value} companyfacts already carries under `tag`"""
    out = {"capex": {"tags": [], "values": [{"end": e, "start": None, "value": v, "tag": tag, "form": "10-K"} for e, v in (have or {}).items()]}}
    if not out["capex"]["values"]:
        del out["capex"]
    got = ix_figures.fill_capex(out, {}, source(document(cash_flow(lines, **kw))), 8)
    return out, got


def test_capital_spending_lines_add_to_the_filed_subtotal_and_are_read_with_their_tags():
    out, got = capex_out()
    vals = {v["end"]: v["value"] for v in out["capex"]["values"]}
    assert got == ["2023-12-31", "2024-12-31", "2025-12-31"] and vals == {"2023-12-31": 100e3, "2024-12-31": 150e3, "2025-12-31": 310e3}
    assert out["capex"]["values"][-1]["stamp"] == f"ix_read:capex:{ACC}:x:InvestmentInVesselsUnderConstruction+x:InvestmentsInVessels"
    assert out["capex"]["values"][-1]["tag"] == "InvestmentInVesselsUnderConstruction+InvestmentsInVessels"


def test_the_words_of_a_tag_decide_whether_a_line_is_capital_spending():
    ok = ("x:PaymentsForVesselsUnderConstruction", "x:InvestmentsInVessels", "x:PaymentsToAcquireVessels", "us-gaap:PaymentsToAcquireProductiveAssets",
          "x:PurchaseOfOtherPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
          "x:PaymentsToAcquirePropertyPlantAndEquipmentAndVesselsIncludingAttachedTimeCharterAgreements")
    no = ("x:PaymentsForInvestmentsInLeasebackVesselsInvestingActivities", "x:PaymentsForDryDockExpenses", "us-gaap:PaymentsToAcquireEquityMethodInvestments",
          "x:ProceedsFromSaleOfVessels", "x:PaymentsForVesselsRelatedPartyLoans", "us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired", "x:Vessels", "x:PaymentsOfDividends")
    assert all(ix_figures.is_capex_tag(n) for n in ok) and not any(ix_figures.is_capex_tag(n) for n in no)


def test_a_line_that_is_not_capital_spending_does_not_count_but_the_section_still_has_to_add_up():
    lines = VESSELS + [("x:PaymentsForInvestmentsInLeasebackVesselsInvestingActivities", [5, 5, 5], "out")]
    out, got = capex_out(lines=lines)
    assert out["capex"]["values"][0]["value"] == 100e3 and len(got) == 3                    # the leaseback line is in the sum check, not in the capex
    assert capex_out(tot=[-1, -1, -1])[1] == []                                               # a subtotal the lines do not add to: nothing is read


def test_a_year_whose_section_does_not_add_up_is_not_read_but_the_others_are():
    out, got = capex_out(tot=[-100, -150, -999])
    assert got == ["2023-12-31", "2024-12-31"]


def test_a_blank_cell_of_a_capital_spending_row_is_not_read_as_zero():
    lines = [("x:PaymentsForVesselsAndVesselsUnderConstruction", [None, None, 40], "out"), ("x:PaymentsForDryDockExpenses", [3, 11, 3], "out")]
    out, got = capex_out(lines=lines)
    assert got == ["2025-12-31"] and [v["end"] for v in out["capex"]["values"]] == ["2025-12-31"]


def test_a_tagged_dash_is_a_filed_zero_for_the_year():
    out, got = capex_out(lines=[("x:PaymentsForVesselsUnderConstruction", [0, 7, 9], "out")])
    assert out["capex"]["values"][0]["value"] == 0.0 and len(got) == 3


def test_a_capital_spending_line_printed_as_a_receipt_is_not_read():
    assert capex_out(lines=[("x:PaymentsForVesselsUnderConstruction", [5, 5, 5], "in")])[1] == []


def test_capex_the_feed_files_under_another_tag_is_not_pooled_with_the_filings_years():
    """WO_UV5: one source for every pooled year. The feed's narrower figure of a year the filing does not show, and of a year it does, are both dropped."""
    out, got = capex_out(have={"2021-12-31": 1.0, "2024-12-31": 7.0})
    assert got == ["2023-12-31", "2025-12-31"]
    assert {v["end"]: v["value"] for v in out["capex"]["values"]} == {"2023-12-31": 100e3, "2024-12-31": 150e3, "2025-12-31": 310e3}
    assert all(v["stamp"].startswith("ix_read:capex:") for v in out["capex"]["values"])


def test_a_note_names_the_years_read_and_the_feed_years_dropped():
    note = {}
    out = {"capex": {"tags": ["T"], "values": [{"end": "2021-12-31", "start": None, "value": 1.0, "tag": "T", "form": "10-K"}]}}
    ix_figures.fill_capex(out, {}, source(document(cash_flow(VESSELS))), 8, note)
    assert note == {"capex": {"read": ["2023-12-31", "2024-12-31", "2025-12-31"], "dropped": ["2021-12-31"]}}


ONE_LINE = [("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", [100, 60, 111], "out")]
SAME = "PaymentsToAcquirePropertyPlantAndEquipment"


def test_feed_years_under_the_very_tag_of_the_filings_one_line_are_the_same_concept_and_stay():
    out, got = capex_out(have={"2021-12-31": 7.0, "2022-12-31": 9.0}, lines=ONE_LINE, tag=SAME)
    vals = {v["end"]: v["value"] for v in out["capex"]["values"]}
    assert got == ["2023-12-31", "2024-12-31", "2025-12-31"] and vals == {"2021-12-31": 7.0, "2022-12-31": 9.0, "2023-12-31": 100e3, "2024-12-31": 60e3, "2025-12-31": 111e3}


def test_a_same_tag_feed_figure_that_disagrees_with_the_filing_rejects_the_reading():
    out, got = capex_out(have={"2023-12-31": 7.0}, lines=ONE_LINE, tag=SAME)                 # 7 against the filing's 100,000
    assert got == [] and [v["value"] for v in out["capex"]["values"]] == [7.0]
    out, got = capex_out(have={"2024-12-31": 60e3, "2021-12-31": 1.0}, lines=ONE_LINE, tag=SAME)      # agrees to the dollar
    assert got == ["2023-12-31", "2025-12-31"] and {v["end"]: v["value"] for v in out["capex"]["values"]}["2024-12-31"] == 60e3
    assert out["capex"]["values"][0]["value"] == 1.0


def test_a_filing_with_two_capital_spending_lines_is_never_the_same_concept_as_one_feed_tag():
    two = ONE_LINE + [("x:PaymentsForVesselsUnderConstruction", [1, 2, 3], "out")]
    out, got = capex_out(have={"2021-12-31": 7.0}, lines=two, tag=SAME)
    assert got == ["2023-12-31", "2024-12-31", "2025-12-31"] and "2021-12-31" not in {v["end"] for v in out["capex"]["values"]}


def test_a_statement_with_no_operating_subtotal_before_the_investing_one_is_not_read():
    html = document("<table>" + "".join(cells(t, v, s) for t, v, s in VESSELS) + cells("us-gaap:NetCashProvidedByUsedInInvestingActivities", [-100, -150, -167], "out") + "</table>")
    assert ix_figures.fill_capex({}, {}, source(html), 8) == []


def five_years(tag, unit="USD", v=5e6):
    return {"units": {unit: [fy(f"{y}-12-31", v, ACC) for y in range(2021, 2026)]}}


def whole_cf(**missing):
    t = {"Revenues": five_years("Revenues", v=100e6), "PaymentsToAcquirePropertyPlantAndEquipment": five_years("x"), "DepreciationAndAmortization": five_years("x"),
         "WeightedAverageNumberOfDilutedSharesOutstanding": five_years("x", "shares", 10.0)}
    return {"facts": {"us-gaap": {k: v for k, v in t.items() if k not in missing}}}


def test_the_document_is_never_read_when_the_series_the_valuation_needs_are_whole():
    calls = []
    out = facts.annual_facts(whole_cf(), subs_new(report="2025-12-31"), T, substitute_items=True, ix=lambda: calls.append(1))
    assert calls == [] and "_ix" not in out


def test_the_document_is_read_once_for_all_the_readings_when_capex_and_d_and_a_are_lacking():
    calls = []
    facts.annual_facts(whole_cf(PaymentsToAcquirePropertyPlantAndEquipment=1, DepreciationAndAmortization=1), subs_new(), T, substitute_items=True,
                       ix=lambda: calls.append(1))
    assert calls == [1]
    calls.clear()
    facts.annual_facts(whole_cf(PaymentsToAcquirePropertyPlantAndEquipment=1), subs_new(), T, substitute_items=False, ix=lambda: calls.append(1))
    assert calls == []                                                                        # the financial route reads no capital spending


def mixed_capex(feed_tag, n_feed=2, line="x:PaymentsForVesselsUnderConstruction"):
    st = f"ix_read:capex:{ACC}:{line}"
    vals = [{"end": e, "value": 5.0, "tag": feed_tag, "form": "10-K"} for e in ti.ENDS[:n_feed]]
    vals += [{"end": e, "value": 6.0, "tag": line.split(":")[-1], "form": "10-K", "stamp": st} for e in ti.ENDS[n_feed:]]
    return st, ti.facts(capex={"tags": [], "values": vals})


def test_a_series_of_the_filings_years_only_carries_its_stamp_and_a_company_with_nothing_read_none():
    st, f = mixed_capex("x", n_feed=0)
    assert st in base(f)["stamps"] and not any(s.startswith("ix_") for s in base()["stamps"])


def test_a_pooled_series_that_mixes_the_filings_years_with_another_tag_is_refused_as_an_assertion():
    """WO_UV5: the facts build no such series; if one reaches the engine it is refused, not flagged."""
    st, f = mixed_capex(SAME)
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == "ix_series_mixed"


def test_feed_years_under_the_tag_of_the_filings_one_line_are_not_a_mix():
    st, f = mixed_capex(SAME, line=f"us-gaap:{SAME}")
    assert st in base(f)["stamps"]


def test_a_filing_covering_fewer_years_than_the_pool_needs_refuses_and_says_so():
    """WO_UV5: the filing's own columns hold 2 years, the engine pools at least MIN_POOL_YEARS: the refusal names the filing's columns."""
    st, f = mixed_capex("x", n_feed=3)
    f["capex"]["values"] = f["capex"]["values"][3:]
    f["_ix"] = {"url": "u", "accession": ACC, "read": {"capex": ti.ENDS[3:]}, "version": "v",
                "single_source": {"capex": {"read": ti.ENDS[3:], "dropped": ti.ENDS[:3]}}}
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    msg = str(e.value)
    assert e.value.code == "history_short" and "at least 3 are needed" in msg and "capex is taken from the filing's own columns only (2 fiscal years" in msg and ti.ENDS[0] in msg


def test_the_whole_chain_gives_the_filings_years_only_and_the_engine_pools_them():
    """facts.annual_facts -> inputs.base: companyfacts holds a narrower capex tag for older years, the filing the statement's lines for three."""
    cf = whole_cf(PaymentsToAcquirePropertyPlantAndEquipment=1, DepreciationAndAmortization=1)
    cf["facts"]["us-gaap"]["PaymentsToAcquireOtherPropertyPlantAndEquipment"] = {"units": {"USD": [fy("2021-12-31", 1e3, OLD, filed="2025-02-21")]}}
    out = facts.annual_facts(cf, subs_new(), T, substitute_items=True, ix=lambda: source(document(cash_flow(VESSELS))))
    assert [v["end"] for v in out["capex"]["values"]] == ["2023-12-31", "2024-12-31", "2025-12-31"] and out["_ix"]["single_source"]["capex"]["dropped"] == ["2021-12-31"]


# ---- reading 3: D&A filed with one segment ----------------------------------------------------------------------------------------------

SEG = [("us-gaap:StatementBusinessSegmentsAxis", "a:OneSegmentMember")]


def da_doc(vals, dims=SEG, extra=""):
    body = f"<table>{cells('us-gaap:DepreciationAndAmortization', vals, 'in', prefix='s')}</table>"
    return document(body, extra_ctx=year_ctx("s", dims) + extra)


def da_out(am=(23_845e3, 23_845e3, 23_845e3), da=(514e3, 267e3), tag="Depreciation"):
    ends = ("2023-12-31", "2024-12-31")
    out = {"da": {"tags": [tag], "values": [{"end": e, "start": None, "value": v, "tag": tag, "form": "10-K"} for e, v in zip(ends, da)]},
           "amortization": {"tags": ["AmortizationOfIntangibleAssets"], "values": [{"end": e, "start": None, "value": v, "tag": "AmortizationOfIntangibleAssets"}
                                                                                for e, v in zip(("2023-12-31", "2024-12-31", "2025-12-31"), am)]}}
    return out


def test_one_segment_da_is_read_when_the_earlier_years_net_of_amortization_equal_the_filed_depreciation():
    out = da_out()
    got = ix_figures.fill_da(out, {}, source(da_doc((24_359, 24_112, 25_335))), facts.DA_EXCLUDES_AMORTIZATION, 8)
    assert got == ["2025-12-31"] and out["da"]["values"][-1]["value"] == 25_335e3 and out["da"]["values"][-1]["tag"] == "DepreciationAndAmortization"
    assert out["da"]["values"][-1]["stamp"].startswith(f"ix_read:da:{ACC}:us-gaap:DepreciationAndAmortization[us-gaap:StatementBusinessSegmentsAxis=a:OneSegmentMember]")


def test_one_segment_da_that_does_not_reconcile_with_the_filed_depreciation_is_not_read():
    assert ix_figures.fill_da(da_out(), {}, source(da_doc((24_359, 24_500, 25_335))), facts.DA_EXCLUDES_AMORTIZATION, 8) == []
    assert ix_figures.fill_da(da_out(da=()), {}, source(da_doc((24_359, 24_112, 25_335))), facts.DA_EXCLUDES_AMORTIZATION, 8) == []      # nothing to verify against


def test_da_with_two_members_or_with_a_changing_member_is_not_read():
    two = da_doc((24_359, 24_112, 25_335)).replace("</body>", cells("us-gaap:DepreciationAndAmortization", (1, 1, 1), "in", prefix="t") + "</body>")
    two = two.replace("</xbrli:resources>", year_ctx("t", [("us-gaap:StatementBusinessSegmentsAxis", "a:OtherMember")]) + "</xbrli:resources>")
    assert ix_figures.fill_da(da_out(), {}, source(two), facts.DA_EXCLUDES_AMORTIZATION, 8) == []


def test_da_already_filed_for_every_year_the_filing_shows_is_not_read_again():
    out = da_out()
    out["da"]["values"].append({"end": "2025-12-31", "start": None, "value": 1.0, "tag": "Depreciation", "form": "10-K"})
    assert ix_figures.fill_da(out, {}, source(da_doc((24_359, 24_112, 25_335))), facts.DA_EXCLUDES_AMORTIZATION, 8) == []
    assert out["da"]["values"][-1]["value"] == 1.0


def test_da_read_from_the_filing_holds_the_filings_years_only():
    """WO_UV5: the earlier years' depreciation under another tag (checked, as the filing shows them) and a year the filing does not show are not pooled with it."""
    out, note = da_out(), {}
    out["da"]["values"].insert(0, {"end": "2022-12-31", "start": None, "value": 500e3, "tag": "Depreciation", "form": "10-K"})
    got = ix_figures.fill_da(out, {}, source(da_doc((24_359, 24_112, 25_335))), facts.DA_EXCLUDES_AMORTIZATION, 8, note)
    assert got == ["2025-12-31"]
    assert {v["end"]: v["value"] for v in out["da"]["values"]} == {"2023-12-31": 24_359e3, "2024-12-31": 24_112e3, "2025-12-31": 25_335e3}
    assert out["da"]["tags"] == ["DepreciationAndAmortization"]
    assert note == {"da": {"read": ["2023-12-31", "2024-12-31", "2025-12-31"], "dropped": ["2022-12-31"]}}


# ---- reading 4: class-of-stock share counts ---------------------------------------------------------------------------------------------

CLASS = "us-gaap:StatementClassOfStockAxis"


def share_doc(members, end="2025"):
    """members: {name: (shares, eps or None)} as facts with the class dimension"""
    parts, cx = [], ""
    for i, (m, (sh, eps)) in enumerate(members.items()):
        cx += ctx(f"k{i}", f"{end}-01-01", f"{end}-12-31", [(CLASS, f"us-gaap:{m}")])
        parts.append(nf("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", f"k{i}", f"{sh:,}", unit="shares", scale="3"))
        if eps is not None:
            parts.append(nf("us-gaap:EarningsPerShareDiluted", f"k{i}", f"{eps}", unit="eps", dec="2", scale="0"))
    return document("<table><tr><td>" + "</td><td>".join(parts) + "</td></tr></table>", extra_ctx=cx)


def test_a_member_with_its_eps_and_the_sum_of_members_with_one_eps_are_the_candidates():
    c = ix_figures.share_candidates(ixbrl.parse(share_doc({"CommonStockMember": (841_176, 0.67), "CommonClassBMember": (54_745, 0.67)})), "2025-12-31")
    assert [(x["members"], x["shares"], x["eps"]) for x in c] == [(["us-gaap:CommonClassBMember"], 54_745e3, 0.67), (["us-gaap:CommonStockMember"], 841_176e3, 0.67),
                                                                  (["us-gaap:CommonClassBMember", "us-gaap:CommonStockMember"], 895_921e3, 0.67)]


def test_members_with_different_eps_or_none_give_no_sum_and_a_member_without_eps_is_no_candidate():
    c = ix_figures.share_candidates(ixbrl.parse(share_doc({"A": (1_900_000, 12.32), "B": (4_000, 19.1)})), "2025-12-31")
    assert [x["members"] for x in c] == [["us-gaap:A"], ["us-gaap:B"]]
    assert ix_figures.share_candidates(ixbrl.parse(share_doc({"A": (1_900_000, None)})), "2025-12-31") == []


def no_shares(**over):
    f = ti.facts(**over)
    f.pop("diluted_shares"), f.pop("eps_diluted")
    return f


def with_candidates(f, cands, end="2025-12-31"):
    f["_ix_shares"] = {"end": end, "accession": ACC, "url": "u", "candidates": cands}
    return f


NI = 10.4          # ti.facts' base-year net income


def test_a_class_count_that_reconciles_with_its_own_eps_is_the_diluted_count_and_is_stamped():
    f = with_candidates(no_shares(), [{"members": ["us-gaap:CommonStockMember"], "shares": 10.0, "eps": 1.04}])
    b = base(f)
    assert b["shares"] == 10.0 and f"shares_from_ix_class_members:{ACC}:CommonStockMember" in b["stamps"] and "shares_reconciled_with_class_eps" in b["stamps"]


def test_the_sum_of_members_is_used_where_one_member_alone_does_not_reconcile():
    f = with_candidates(no_shares(), [{"members": ["us-gaap:A"], "shares": 8.0, "eps": 1.04},
                                      {"members": ["us-gaap:A", "us-gaap:B"], "shares": 10.0, "eps": 1.04}])
    assert base(f)["shares"] == 10.0


def test_no_count_that_reconciles_means_the_old_refusal_stands():
    f = with_candidates(no_shares(), [{"members": ["us-gaap:A"], "shares": 8.0, "eps": 1.04}])
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == "shares_unavailable"


def test_two_different_counts_that_both_reconcile_are_ambiguous_and_not_read():
    f = with_candidates(no_shares(), [{"members": ["us-gaap:A"], "shares": 10.0, "eps": 1.04}, {"members": ["us-gaap:B"], "shares": 10.3, "eps": 1.01}])
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == "shares_unavailable"


def test_a_count_that_reconciles_only_after_the_thousands_rescale_is_not_used():
    f = with_candidates(no_shares(), [{"members": ["us-gaap:A"], "shares": 0.01, "eps": 1.04}])        # 10.4 / 0.01 is 1040; x1000 would be 1.04
    with pytest.raises(desk.DeskRefusal):
        base(f)


def test_candidates_of_another_year_are_not_used_and_a_filed_count_comes_first():
    f = with_candidates(no_shares(), [{"members": ["us-gaap:A"], "shares": 10.0, "eps": 1.04}], end="2024-12-31")
    with pytest.raises(desk.DeskRefusal):
        base(f)
    g = with_candidates(ti.facts(), [{"members": ["us-gaap:A"], "shares": 99.0, "eps": 1.04}])
    assert base(g)["shares"] == 10.0 and not any(s.startswith("shares_from_ix") for s in base(g)["stamps"])


def test_the_period_end_count_of_the_old_path_comes_before_a_class_count():
    f = no_shares()
    f["shares_period_end"], f["eps_diluted"] = series([10.0], tag="CommonStockSharesOutstanding"), series([1.04])
    b = base(with_candidates(f, [{"members": ["us-gaap:A"], "shares": 99.0, "eps": 1.0}]))
    assert b["shares"] == 10.0 and not any(s.startswith("shares_from_ix") for s in b["stamps"])


def test_the_document_is_not_read_for_a_count_the_old_path_can_prove():
    cf = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fy("2024-12-31", 120e6, OLD, filed="2025-02-21"), fy("2025-12-31", 150e6, ACC)]}},
                                "CommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 10.0, "accn": ACC, "form": "10-K", "filed": "2026-02-20", "fp": "FY"}]}},
                                "EarningsPerShareDiluted": {"units": {"USD/shares": [fy("2025-12-31", 1.0, ACC)]}}}}}
    calls = []
    out = facts.annual_facts(cf, subs_new(), T, ix=lambda: calls.append(1))
    assert calls == [] and "_ix_shares" not in out


def test_share_candidates_reach_the_facts_only_where_the_base_year_has_no_diluted_count():
    cf = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fy("2024-12-31", 120e6, OLD, filed="2025-02-21"), fy("2025-12-31", 150e6, ACC)]}}}}}
    out = facts.annual_facts(cf, subs_new(), T, ix=lambda: source(share_doc({"CommonStockMember": (841_176, 0.67)})))
    assert out["_ix_shares"]["end"] == "2025-12-31" and out["_ix_shares"]["candidates"][0]["shares"] == 841_176e3
    cf["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": [fy("2025-12-31", 10.0, ACC)]}}
    assert "_ix_shares" not in facts.annual_facts(cf, subs_new(), T, ix=lambda: source(share_doc({"CommonStockMember": (841_176, 0.67)})))


def test_the_versions_are_bumped():
    assert facts.FACTS_VERSION == "m3q.facts.v16" and inputs.INPUTS_VERSION == "m3q.inputs.v20" and ix_figures.IX_FIGURES_VERSION.startswith("m3q.ix_figures.v2")

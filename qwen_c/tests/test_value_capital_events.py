"""WO_NC10 Part A: facts.capital_events, the year-to-date capital events of the latest 10-Q effective at T (acquisitions, buybacks, share issues,
disposals, and the cover-page share count). Synthetic companyfacts; the function is called by nothing in the menu path."""
from datetime import datetime, timezone

from qwen_c.value import facts
from qwen_c.tests.test_value_ytd import FILINGS, K24, Q1, Q2, Q3, T, fact, subs

FY0 = "2024-12-31"
S, E3 = "2025-01-01", "2025-09-30"


def rev(accn=Q3, end=E3, start=S, val=360.0):
    return fact(start, end, val, accn)


def cf(rows):
    """rows: {(taxonomy, tag): [facts]} plus the revenue rows of the 10-Qs."""
    g = {}
    for (tax, tag), rs in rows.items():
        unit = "shares" if tag == "EntityCommonStockSharesOutstanding" else "USD"
        g.setdefault(tax, {})[tag] = {"units": {unit: rs}}
    return {"facts": g}


def base_rows(extra=None):
    r = {("us-gaap", "Revenues"): [rev(Q1, "2025-03-31", S, 110.0), rev(Q2, "2025-06-30", S, 230.0), rev()]}
    r.update(extra or {})
    return r


def cover(val, accn=Q3):
    f = {"end": "2025-10-24", "val": val, "accn": accn, "form": "10-Q", "filed": FILINGS[accn][1]}
    return f


def test_every_event_and_the_cover_share_count_come_from_the_latest_10q_with_tag_accession_and_period():
    c = cf(base_rows({("us-gaap", "PaymentsToAcquireBusinessesNetOfCashAcquired"): [fact(S, E3, 30.0, Q3), fact(S, "2025-06-30", 10.0, Q2)],
                        ("us-gaap", "PaymentsForRepurchaseOfCommonStock"): [fact(S, E3, 5.0, Q3)],
                        ("us-gaap", "ProceedsFromIssuanceOfCommonStock"): [fact(S, E3, 1.0, Q3)],
                        ("us-gaap", "ProceedsFromDivestitureOfBusinesses"): [fact(S, E3, 2.0, Q3)],
                        ("dei", "EntityCommonStockSharesOutstanding"): [cover(9_900_000.0), cover(10_100_000.0, Q2)]}))
    ce = facts.capital_events(c, T, FY0, subs())
    assert ce["found"] and ce["absent"] is None and (ce["accn"], ce["start"], ce["end"], ce["quarter"]) == (Q3, S, E3, 3)
    assert {k: v["value"] for k, v in ce["events"].items()} == {"acquisitions_paid": 30.0, "buybacks_paid": 5.0, "shares_issued_proceeds": 1.0, "disposals_received": 2.0}
    a = ce["events"]["acquisitions_paid"]
    assert (a["tag"], a["accn"], a["start"], a["end"], a["form"]) == ("us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired", Q3, S, E3, "10-Q") and a["stamp"] is None
    assert ce["absent_events"] == {} and ce["shares_outstanding"]["value"] == 9_900_000.0 and ce["shares_outstanding"]["accn"] == Q3 and ce["shares_absent"] is None


def test_a_concept_not_filed_is_absent_with_its_reason_not_zero():
    ce = facts.capital_events(cf(base_rows({("us-gaap", "PaymentsForRepurchaseOfCommonStock"): [fact(S, E3, 5.0, Q3)]})), T, FY0, subs())
    assert ce["events"]["buybacks_paid"]["value"] == 5.0 and ce["events"]["acquisitions_paid"] is None
    assert set(ce["absent_events"]) == {"acquisitions_paid", "shares_issued_proceeds", "disposals_received"}
    assert Q3 in ce["absent_events"]["acquisitions_paid"] and ce["shares_outstanding"] is None and "no cover-page share count" in ce["shares_absent"]


def test_the_gross_acquisition_tag_is_used_only_where_the_net_one_is_not_filed_and_is_stamped():
    gross = cf(base_rows({("us-gaap", "PaymentsToAcquireBusinessesGross"): [fact(S, E3, 31.0, Q3)]}))
    a = facts.capital_events(gross, T, FY0, subs())["events"]["acquisitions_paid"]
    assert a["value"] == 31.0 and a["tag"].endswith("PaymentsToAcquireBusinessesGross") and a["stamp"] == "acquisitions_paid_gross_of_cash_acquired"
    both = cf(base_rows({("us-gaap", "PaymentsToAcquireBusinessesGross"): [fact(S, E3, 31.0, Q3)],
                           ("us-gaap", "PaymentsToAcquireBusinessesNetOfCashAcquired"): [fact(S, E3, 30.0, Q3)]}))
    assert facts.capital_events(both, T, FY0, subs())["events"]["acquisitions_paid"]["value"] == 30.0


def test_a_filed_zero_is_a_value():
    ce = facts.capital_events(cf(base_rows({("us-gaap", "PaymentsForRepurchaseOfCommonStock"): [fact(S, E3, 0.0, Q3)]})), T, FY0, subs())
    assert ce["events"]["buybacks_paid"] is not None and ce["events"]["buybacks_paid"]["value"] == 0.0 and "buybacks_paid" not in ce["absent_events"]


def test_the_filing_is_the_one_ytd_picks_a_10q_effective_after_T_is_not_used_and_a_period_not_starting_after_the_base_year_is_not_read():
    c = cf(base_rows({("us-gaap", "PaymentsForRepurchaseOfCommonStock"): [fact(S, E3, 5.0, Q3), fact(S, "2025-06-30", 3.0, Q2),
                                                                           fact("2024-01-01", "2024-09-30", 99.0, Q3)]}))
    late = dict(FILINGS, **{Q3: ("10-Q", "2025-11-03", "2025-11-03T21:00:00.000Z")})
    ce = facts.capital_events(c, T, FY0, subs(late))
    assert (ce["accn"], ce["end"]) == (Q2, "2025-06-30") and ce["events"]["buybacks_paid"]["value"] == 3.0
    assert facts.capital_events(c, T, FY0, subs())["events"]["buybacks_paid"]["value"] == 5.0           # the prior-year leg (99) is never taken


def test_no_10q_of_year_1_means_not_found_with_the_reason():
    ce = facts.capital_events(cf({("us-gaap", "Revenues"): [fact("2024-01-01", "2024-12-31", 400.0, K24)]}), T, FY0, subs())
    assert ce["found"] is False and ce["absent"] == "no 10-Q of year 1 effective at T" and ce["events"] == {}
    early = facts.capital_events(cf(base_rows()), datetime(2025, 2, 1, tzinfo=timezone.utc), FY0, subs())
    assert early["found"] is False


def test_two_different_values_under_one_tag_are_ambiguous_and_two_class_counts_are_not_summed():
    c = cf(base_rows({("us-gaap", "PaymentsForRepurchaseOfCommonStock"): [fact(S, E3, 5.0, Q3), fact(S, E3, 6.0, Q3)],
                        ("dei", "EntityCommonStockSharesOutstanding"): [cover(9_000_000.0), cover(1_000_000.0)]}))
    ce = facts.capital_events(c, T, FY0, subs())
    assert ce["events"]["buybacks_paid"] is None and "two different values" in ce["absent_events"]["buybacks_paid"]
    assert ce["shares_outstanding"] is None and "different counts" in ce["shares_absent"]


def test_without_submissions_the_filed_date_decides_what_was_effective():
    c = cf(base_rows({("us-gaap", "PaymentsForRepurchaseOfCommonStock"): [fact(S, E3, 5.0, Q3)]}))
    ce = facts.capital_events(c, T, FY0)
    assert ce["found"] and ce["events"]["buybacks_paid"]["stamp"] == "acceptance_by_filed_date"

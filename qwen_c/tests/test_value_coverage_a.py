"""Coverage A (2026-11-07): a diluted share count filed in thousands is rescaled only where the rescaled count reconciles with filed
diluted EPS; parent equity is the filed total only where no NCI fact of any kind is filed."""
import pytest

from qwen_c.value import facts, inputs
from qwen_c.value.desk import DeskRefusal


def _f(**series):
    return {k: {"tags": ["t"], "values": [{"end": e, "value": v, "tag": "t"} for e, v in vals.items()]} for k, vals in series.items()}


def test_shares_filed_in_thousands_rescaled_when_eps_reconciles():
    f = _f(eps_diluted={"2026-04-30": 0.41})
    stamps = []
    assert inputs.check_shares(f, "2026-04-30", 1.848e7, 44930.0, stamps, "NI") == pytest.approx(4.493e7)
    assert stamps == ["shares_filed_scale_x1e+03_eps_reconciled"]


def test_shares_in_scale_untouched():
    f = _f(eps_diluted={"2025-12-31": 2.0})
    stamps = []
    assert inputs.check_shares(f, "2025-12-31", 2.0e8, 1.0e8, stamps, "NI") == 1.0e8
    assert stamps == []


def test_shares_off_by_seven_percent_still_refused():
    f = _f(eps_diluted={"2025-12-26": 1.68})                  # an if-converted diluted EPS (CHEF): not a scale slip
    with pytest.raises(DeskRefusal) as e:
        inputs.check_shares(f, "2025-12-26", 7.236e7, 4.6e7, [], "NI")
    assert e.value.code == "shares_scale_unverified"


def test_no_eps_filed_stamped():
    stamps = []
    assert inputs.check_shares(_f(), "2025-12-31", 1.0, 2.0, stamps, "NI") == 2.0
    assert stamps == ["shares_unreconciled_no_eps"]


def _derive(out):
    out.setdefault("pretax_income", {"tags": ["t"], "values": [{"end": "2025-09-30", "value": 1.0, "tag": "t"}]})
    facts._derive(out, {}, {"facts": {}}, set(), set(), None, 8)
    return {v["end"]: (v["value"], v["stamp"]) for v in out.get("equity", {}).get("values", [])}


def _total(**ends):
    return {"tags": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
            "values": [{"end": e, "value": v, "tag": "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"}
                       for e, v in ends.items()]}


def test_total_equity_is_parent_when_no_nci_fact_filed():
    eq = _derive({"equity_incl_nci": _total(**{"2024-09-30": 39.14e9, "2025-09-30": 37.91e9})})
    assert eq == {"2024-09-30": (39.14e9, "equity_total_no_nci_filed"), "2025-09-30": (37.91e9, "equity_total_no_nci_filed")}


def test_total_equity_not_taken_when_nci_income_filed():
    out = {"equity_incl_nci": _total(**{"2025-09-30": 10.0}),
           "nci_income": {"tags": ["t"], "values": [{"end": "2025-09-30", "value": 3.0, "tag": "t"}]}}
    assert _derive(out) == {}

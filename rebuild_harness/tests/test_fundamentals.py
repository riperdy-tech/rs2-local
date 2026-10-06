from rebuild_harness import fundamentals as F


def row(**k):
    base = {"revenue": 100.0, "operating_income": 20.0, "pretax_income": 20.0, "tax_provision": 4.0, "equity": 80.0, "debt_lt_noncurrent": 30.0,
            "debt_current": 5.0, "cash": 20.0, "gross_profit": 50.0, "total_assets": 150.0, "capex": 5.0, "da": 4.0, "current_assets": 60.0,
            "current_liabilities": 25.0}
    base.update(k)
    return base


def test_operating_margin_and_zero_is_a_value():
    assert F.operating_margin(row()) == 0.2
    assert F.operating_margin(row(operating_income=0.0)) == 0.0
    assert F.operating_margin(row(operating_income=None)) is None
    assert F.operating_margin(row(revenue=0.0)) is None


def test_tax_default_is_stamped_and_zero_tax_is_a_value():
    assert F.tax_rate(row()) == (0.2, False)
    assert F.tax_rate(row(tax_provision=0.0)) == (0.0, False)
    assert F.tax_rate(row(tax_provision=None)) == (0.21, True)
    assert F.tax_rate(row(tax_provision=-5.0)) == (0.0, False)


def test_roc_needs_every_term_and_a_positive_capital():
    r = row()
    assert F.invested_capital(r) == 80 + 35 - 20
    assert abs(F.return_on_capital(r) - 16.0 / 95.0) < 1e-12
    assert F.return_on_capital(row(debt_current=None, debt_lt_noncurrent=None)) is None      # a filer that tags no debt line is not assumed to have none
    assert F.invested_capital(row(debt_current=None)) == 80 + 30 - 20                       # one missing component counts 0 (the repository's F4 rule)
    # separately filed short-term borrowings add to the current portion only when it is a current-portion-of-long-term-debt tag
    r2 = row(short_term_borrowings_separate=10.0)
    assert F.total_debt(r2, "DebtCurrent") == 35.0 and F.total_debt(r2, "LongTermDebtCurrent") == 45.0 and F.total_debt(r2) == 35.0
    assert F.return_on_capital(row(equity=-100.0)) is None
    assert F.return_on_capital(row(cash=0.0)) is not None                 # cash of zero is a value


def test_reinvestment_rate():
    prev = row(current_assets=50.0, current_liabilities=25.0)
    r = row()
    nwc1, nwc0 = (60 - 20) - (25 - 5), (50 - 20) - (25 - 5)
    assert abs(F.reinvestment_rate(r, prev) - (5 - 4 + (nwc1 - nwc0)) / 16.0) < 1e-12
    assert F.reinvestment_rate(r, None) is None
    assert F.reinvestment_rate(row(operating_income=-1.0), prev) is None


def test_gross_profitability():
    assert F.gross_profitability(row()) == 50.0 / 150.0
    assert F.gross_profitability(row(gross_profit=0.0)) == 0.0

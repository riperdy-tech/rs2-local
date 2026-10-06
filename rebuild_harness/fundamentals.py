"""Fundamental measures computed from one fiscal-year row (and the year before it).  The same functions measure a yardstick (the base year) and
an outcome (a later year as first filed), so a forecast is always compared with a number on the same definition.

0.0 is a value: every test is `is None` / `is_num`, never truthiness.  A measure that cannot be computed is None; nothing is defaulted except
the one declared tax default, which is stamped.
"""
import sys
from pathlib import Path

for _p in (str(Path(__file__).resolve().parents[1] / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import throughcycle_record as tcr   # the repository's single owner of the short-term-debt netting (F4)

from valuation.pit_data import is_num

TAX_DEFAULT = 0.21      # throughcycle_record.TAX_DEFAULT: used (and stamped) only when the filed rate cannot be computed
TAX_MAX = 0.35


def tax_rate(row):
    """(rate, stamped): tax_provision / pretax_income clipped to [0, TAX_MAX]; TAX_DEFAULT with stamped=True when it cannot be computed."""
    pretax, tax = row.get("pretax_income"), row.get("tax_provision")
    if not is_num(pretax) or not is_num(tax) or pretax == 0:
        return TAX_DEFAULT, True
    return min(TAX_MAX, max(0.0, tax / pretax)), False


def operating_margin(row):
    """operating income / revenue (revenue must be positive)."""
    oi, rev = row.get("operating_income"), row.get("revenue")
    if not is_num(oi) or not is_num(rev) or not rev > 0:
        return None
    return oi / rev


def nopat(row):
    """(operating income x (1 - tax rate), tax default used)."""
    oi = row.get("operating_income")
    if not is_num(oi):
        return None, False
    t, stamped = tax_rate(row)
    return oi * (1.0 - t), stamped


def total_debt(row, dc_tag=None):
    """Interest-bearing debt excluding leases: long-term debt (noncurrent) + short-term debt counted once (throughcycle_record.short_term_debt: the
    current portion, plus the separately filed short-term borrowings only when the current portion is a current-portion-of-long-term-debt tag and
    the two differ).  `dc_tag` is the tag the year's current debt came from (the cell's tag).  None when no debt line at all is filed: a filer that
    tags no debt is not assumed to have none."""
    lt = row.get("debt_lt_noncurrent")
    if not is_num(lt):
        lt = row.get("lt_debt")
    if not is_num(lt) and not is_num(row.get("debt_current")) and not is_num(row.get("short_term_borrowings_separate")):
        return None
    return (lt if is_num(lt) else 0.0) + tcr.short_term_debt(row, dc_tag)


def invested_capital(row, dc_tag=None):
    """Equity + debt - cash - short-term investments (a missing short-term investment counts 0; equity, debt and cash are required)."""
    eq, cash, d = row.get("equity"), row.get("cash"), total_debt(row, dc_tag)
    if not is_num(eq) or not is_num(cash) or d is None:
        return None
    sti = row.get("st_investments")
    return eq + d - cash - (sti if is_num(sti) else 0.0)


def return_on_capital(row, dc_tag=None):
    """NOPAT / invested capital (end of year); None unless both exist and the capital is positive."""
    n, _ = nopat(row)
    ic = invested_capital(row, dc_tag)
    if n is None or ic is None or not ic > 0:
        return None
    return n / ic


def gross_profitability(row):
    """Gross profit / total assets (Novy-Marx)."""
    gp, ta = row.get("gross_profit"), row.get("total_assets")
    if not is_num(gp) or not is_num(ta) or not ta > 0:
        return None
    return gp / ta


def operating_nwc(row):
    """(current assets - cash - short-term investments) - (current liabilities - current debt); every term but short-term investments required."""
    ca, cash, cl, dc = row.get("current_assets"), row.get("cash"), row.get("current_liabilities"), row.get("debt_current")
    if not (is_num(ca) and is_num(cash) and is_num(cl) and is_num(dc)):
        return None
    sti = row.get("st_investments")
    return (ca - cash - (sti if is_num(sti) else 0.0)) - (cl - dc)


def reinvestment_rate(row, prev_row):
    """(capex - D&A + change in operating NWC) / NOPAT.  Needs NOPAT > 0, capex, D&A and the operating NWC of this and the previous year."""
    n, _ = nopat(row)
    cx, da = row.get("capex"), row.get("da")
    if n is None or not n > 0 or not is_num(cx) or not is_num(da) or prev_row is None:
        return None
    w1, w0 = operating_nwc(row), operating_nwc(prev_row)
    if w1 is None or w0 is None:
        return None
    return (cx - da + (w1 - w0)) / n


def measures(row, prev_row=None, dc_tag=None):
    """{revenue, operating_margin, roc, reinvestment_rate, gross_profitability}: the fundamentals a forecast is scored on."""
    rev = row.get("revenue")
    return {"revenue": float(rev) if is_num(rev) and rev > 0 else None,
            "operating_margin": operating_margin(row),
            "roc": return_on_capital(row, dc_tag),
            "reinvestment_rate": reinvestment_rate(row, prev_row),
            "gross_profitability": gross_profitability(row)}


FORECAST_MEASURES = ("revenue", "operating_margin", "roc", "reinvestment_rate")

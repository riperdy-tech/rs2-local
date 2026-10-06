"""The validation harness of the valuation rebuild (SPEC_rebuild.md section 6; task T-harness).

Extends the earlier backtest harness (`backtest_phase2`, whose metric primitives are reused): any list of valuation dates, an information set
strictly as of each date from the shared point-in-time layer (`valuation.pit_data`), total-return excess outcomes at 3/6/12/24/36 months,
first-filed fundamental outcomes, yardsticks, a pluggable engine interface, the metrics of section 6, date-block bootstrap intervals and
the holdout lock.  Offline: nothing here opens a socket, a model or a GPU.
"""

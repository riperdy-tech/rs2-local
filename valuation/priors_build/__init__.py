"""priors_build - the measurement scripts behind valuation/priors.py (SPEC_rebuild.md section 4, Addenda A-D; brief T-priors).

Offline: no network, no model, no GPU.  Reads the point-in-time store written by `valuation.pit_data` (SEC companyfacts per filing) and writes
vintages under C:/Users/riper/stocks/stocks-workspace/data/priors/<vintage>/.  See PRIORS_REPORT.md for what is measured and what the data cannot say.
"""

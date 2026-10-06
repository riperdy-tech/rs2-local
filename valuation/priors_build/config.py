"""Paths, vintages and the few stated conventions of the priors build.  Nothing here is tuned to a result."""
import os
from datetime import date, timedelta
from pathlib import Path

WORKSPACE = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks")) / "stocks-workspace"
# the compact companyfacts store (one gz json per CIK, written by valuation.pit_data.PitData.build_company); read-only here
STORE_DIR = Path(os.environ.get("PRIORS_STORE_DIR", str(WORKSPACE / "scratch" / "rev23" / "harness_smoke" / "store_all")))
ZIP_PATH = Path(os.environ.get("PRIORS_COMPANYFACTS_ZIP", str(Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks")) / "stock-screener" / "companyfacts.zip")))
CIK_MAP = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks")) / "screener-publish" / "public" / "data" / "cik_map.json"
INDNAME_CSV = WORKSPACE / "data" / "damodaran" / "csv" / "datasets_indname__2_By_company_name.csv"
RAW_PRICES = WORKSPACE / "data" / "priors" / "_inputs" / "prices_monthly_raw.json"
# priors v2 (Addendum H) is built into its own folder; the version-1 folder `data/priors` is kept as it was (nothing is ever deleted)
DATA_DIR = Path(os.environ.get("PRIORS_DATA_DIR", str(WORKSPACE / "data" / "priors_v2")))
INPUTS_DIR = WORKSPACE / "data" / "priors" / "_inputs"

PRIORS_VERSION = "2"      # 2: Addendum H (family_not_built for pre-profit and utilities; roic3; the roic_level table; correlations on the level variables)
# a vintage Y is cut at Dec 31 of year Y: the layer is asked for the state at the NEXT day, so that every filing used was filed strictly before it
# (companyfacts carries filing dates only; with no acceptance timestamp a filing on the cut date is AMBIGUOUS and unused).  A valuation date T uses
# the latest vintage whose cut date is not after T.
VINTAGE_YEARS = tuple(range(2012, 2026))
REPORT_VINTAGES = (2016, 2020, 2022, 2024, 2025)
DEV_LAST_YEAR = 2022               # Addendum B 9 / C 11: the cyclicality weights are fitted on development years only
MAX_K = 10                         # outcome horizon in years
MIN_N = 50                         # a cell with fewer observations is merged with its neighbour (brief)
QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
CEASED_MONTHS = 18                 # a company whose last periodic filing is this much older than the newest filing in the archive: "ceased filing" (hindsight label, reporting only)


def cut_date(vintage_year: int) -> str:
    """The date handed to the layer for vintage Y: Jan 1 of Y+1 (filings filed on or before Dec 31 of Y are eligible)."""
    return date(vintage_year + 1, 1, 1).isoformat()


def vintage_for(asof) -> int:
    """The latest vintage usable at valuation date `asof`: year(asof) - 1 (its cut date, Jan 1 of year(asof), is not after asof)."""
    d = asof if isinstance(asof, date) else date.fromisoformat(str(asof)[:10])
    return d.year - 1


def vintage_dir(vintage_year: int) -> Path:
    return DATA_DIR / str(vintage_year)

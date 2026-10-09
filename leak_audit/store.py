"""Read-only access to the point-in-time store (harness_smoke/store_all) without the PitData price machinery."""
import gzip, json
from pathlib import Path
from datetime import date
from valuation.pit_data import CompanyPit

STORE = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\harness_smoke\store_all")

def company(cik):
    p = STORE / f"{str(cik).zfill(10)}.json.gz"
    if not p.is_file():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return CompanyPit(json.load(f))

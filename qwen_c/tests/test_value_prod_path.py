"""CROSS_CHECK_Q ruling 4 / PREREG_q3_fade v1.3: the production path (facts -> inputs.base -> forecast.assemble -> desk) against the true
value of simulated firms, for an ideal analyst who cites the capex plan. fixtures_value/prod_path.json is written by stocks-workspace
scratch/rev23/terminal_d2/gen_prod_path_fixture.py."""
import json
from pathlib import Path

import pytest

from qwen_c.value import desk, forecast, inputs

FIX = json.loads((Path(__file__).resolve().parent / "fixtures_value" / "prod_path.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(FIX))
def test_production_path_within_3pct_of_truth(name):
    c = FIX[name]
    b = dict(inputs.base(c["facts"], market_cap=c["market_cap"], bill_rate=0.0), stub_days=0)
    bar = forecast.record_bar(b["record"]["op_margin"])
    v = desk.value_operating(forecast.assemble(c["scenario"], b, bar, r=c["r"]))
    assert abs(v["value_per_share"] / c["truth"] - 1) <= 0.03

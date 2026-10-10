"""Addendum AD.10: the company's common stock is the first of its tickers in SEC's order, never the largest "price x common shares" (a preferred won that)."""
import json

from rebuild_harness import gate1_run as g


class Pit:
    def __init__(self, prices, shares=151e6):
        self.prices, self.shares = prices, shares

    def tickers_for(self, cik):
        return list(self.prices)

    def market_cap(self, cik, d, t):
        p = self.prices[t]
        return {"price": p, "market_cap": None if p is None else p * self.shares, "flags": [], "reason": None}


def test_the_sec_order_picks_the_common_share_over_a_high_priced_preferred(tmp_path, monkeypatch):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"fields": ["cik", "name", "ticker", "exchange"],
                             "data": [[1109354, "BRUKER CORP", "BRKR", "Nasdaq"], [1109354, "BRUKER CORP", "BRKRP", "Nasdaq"]]}), encoding="utf-8")
    monkeypatch.setattr(g, "SEC_TICKERS", f)
    monkeypatch.setattr(g, "_SEC_ORDER", None)
    t, mc, dup = g._best_ticker(Pit({"BRKRP": 316.25, "BRKR": 38.94}), "0001109354", "2025-10-31")
    assert t == "BRKR" and mc["price"] == 38.94 and dup == 1 and any("ticker_common_by_sec_order" in x for x in mc["flags"])
    t2, _mc, _ = g._best_ticker(Pit({"BRKRP": 316.25, "BRKR": None}), "0001109354", "2025-10-31")
    assert t2 == "BRKRP"                                                               # the common has no price: the old rule, flagged
    t3, mc3, _ = g._best_ticker(Pit({"XYZ": 10.0, "XYZP": 25.0}), "0000000099", "2025-10-31")
    assert t3 == "XYZP" and any("ticker_not_in_sec_list" in x for x in mc3["flags"])  # not listed by SEC: old rule, flagged

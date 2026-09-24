"""A consensus period with 0 analysts prints as not available, never as $0.000B."""
import capability_test as cap


def test_zero_analyst_period_is_absent(screener_data_stub, monkeypatch):
    real_load = cap.rs2_data.load_json

    def fake_load(path):
        if str(path).replace("\\", "/").endswith("enrich/GEV.json"):
            return {"_fetched_at": "2026-09-24T00:00:00+00:00", "estimates": {
                "0y": {"revenue": {"avg": 7.57e8, "low": 7.57e8, "high": 7.57e8, "analysts": 1, "growth": -0.2},
                       "eps": {"avg": 1.40, "low": 1.23, "high": 1.79, "analysts": 5, "growth": 1.1}},
                "+1y": {"revenue": {"avg": 0.0, "low": 0.0, "high": 0.0, "analysts": 0, "growth": None},
                        "eps": {"avg": 1.77, "low": 1.49, "high": 1.99, "analysts": 5, "growth": 0.27}}}}
        return real_load(path)

    monkeypatch.setattr(cap.rs2_data, "load_json", fake_load)
    pack = cap.build_pack("GEV")
    row = next(l for l in pack.splitlines() if l.startswith("| next FY"))
    assert "$0.000B" not in row
    assert "$1.77" in row

"""WO_NC7: the shadow run (decided_shadow.py): stored names, resumability, one call at a time, the quota floor, the table, nothing written outside
its own folder. Synthetic data only; the model call and the arm's meter are stubbed, every folder is a temp dir."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decided_shadow as S  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import test_decided_value as T  # noqa: E402
from qwen_c.value import checks, desk  # noqa: E402

STEM = "TEST_20261118T000000Z_abc123"
DATE = "2026-11-18T00:00:00Z"
FLOORS = {"claude-5h": 0.10, "claude-weekly": 0.05}


def store_of(tmp_path):
    """A stored list: TEST (read, routed), FIN (financial), IDLE (not run), NOREAD (routed, no stored read), and their stored menu result."""
    st = tmp_path / "store"
    for t, fam, an in (("TEST", "operating", "complete"), ("FIN", "financial", "complete"), ("IDLE", None, "not run"), ("NOREAD", "operating", "complete")):
        rep = {"ticker": t, "date": DATE, "analysis": an, "family": fam, "screener_commit": "abc", "valued": True, "no_value_reason": None,
               "equity_value": 5.0e7, "filed_shares": 1.0e7, "value_per_filed_share": {"bear": 4.0, "base": 5.0, "bull": 6.0}, "seed_base": {"1000": 5.0, "3000": 5.0}}
        (st / "gemini_site" / "ondemand").mkdir(parents=True, exist_ok=True)
        (st / "gemini_site" / "ondemand" / f"{t}.json").write_text(json.dumps(rep), encoding="utf-8")
    d = st / "m3m_sonnet" / "runs" / f"{STEM}_1"
    d.mkdir(parents=True)
    (d / "packet.json").write_text(json.dumps(T.PK), encoding="utf-8")
    (d / "analysis.json").write_text(json.dumps(T.AN), encoding="utf-8")
    m = st / "m3q_sonnet" / "runs" / f"{STEM}_1000"
    m.mkdir(parents=True)
    (m / "result.json").write_text(json.dumps({"status": "ok", "cost_of_equity": 0.09, "checks": {"prob": checks.PROB}}), encoding="utf-8")
    return st


def snapshot(root):
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())


def arrange(tmp_path, monkeypatch, replies=(), meter=0.9):
    st = store_of(tmp_path)
    packet, b, bar, sent, prepared = T.arrange(tmp_path, monkeypatch, replies)
    for name in ("SITE", "LOG", "AGY_CWD", "USAGE", "LOCK", "ARM", "GEM_MODEL", "FLOORS"):       # the shadow redirects these: restored after the test
        monkeypatch.setattr(G, name, getattr(G, name))
    monkeypatch.setattr(G, "FLOORS", FLOORS)
    monkeypatch.setattr(G, "set_arm", lambda arm: None)
    monkeypatch.setattr(G, "swap", lambda: None)
    metered = []
    monkeypatch.setattr(G, "meter", lambda: metered.append(1) or {k: (meter, None) for k in FLOORS})
    monkeypatch.setattr(S, "screener_row", lambda commit, t: {"price": 10.0, "marketCap": 1.0e8, "sector": "Industrials"})
    return st, tmp_path / "out", sent, metered, prepared


def go(st, out, *extra):
    return S.main(["--arm", "sonnet", "--store", str(st), "--out", str(out), *extra])


def test_only_a_routed_name_with_a_stored_read_is_taken(tmp_path, monkeypatch):
    st, out, *_ = arrange(tmp_path, monkeypatch)
    assert [(r["ticker"], d.name) for r, d in S.stored_names(st)] == [("TEST", f"{STEM}_1")]
    assert S.stored_meta(st, S.stored_names(st)[0][0]) == (0.09, checks.PROB)


def test_a_dry_run_lists_and_writes_nothing(tmp_path, monkeypatch, capsys):
    st, out, sent, metered, _ = arrange(tmp_path, monkeypatch)
    before = snapshot(st)
    assert go(st, out, "--dry-run") == 0
    assert "TEST operating to run" in capsys.readouterr().out and sent == [] and metered == [] and not out.exists() and snapshot(st) == before


def test_a_run_writes_the_two_runs_and_the_table_only_under_its_own_folder_and_stops_nothing(tmp_path, monkeypatch):
    st, out, sent, metered, prepared = arrange(tmp_path, monkeypatch, [T.reply(), T.reply(**{"inputs.long_run_op_margin": 0.12, "inputs.terminal_growth": 0.025})])
    before = snapshot(st)
    assert go(st, out) == 0
    assert len(sent) == 2 and len(metered) == 2 and snapshot(st) == before                                  # one call at a time, the meter before each, nothing stored touched
    assert prepared[0]["online"] is False and prepared[0]["allow_after_T"] is True and prepared[0]["root"] is None and prepared[0]["family"] == "operating"
    names = sorted(p.parent.name for p in (out / "runs").glob("*/result.json"))
    assert len(names) == 2 and names[0].startswith("TEST_20261118T000000Z_") and names[0].endswith("_decided_1000") and names[1].endswith("_decided_3000")
    (row,) = json.loads((out / "shadow_table.json").read_text(encoding="utf-8"))
    assert {"ticker", "family", "price", "old", "old_verdict", "valued", "new", "new_verdict", "run_gap", "flags", "value_at_old_defaults", "ke_old", "ke_new", "reason"} == set(row)
    assert row["ticker"] == "TEST" and row["old"] == {"bear": 4.0, "base": 5.0, "bull": 6.0} and row["valued"] is True and row["ke_old"] == 0.09 and row["ke_new"] == T.C.R
    assert set(row["new"]) == {"bear", "base", "bull"} and row["new_verdict"] in ("BUY", "WATCH", "AVOID") and row["old_verdict"] in ("BUY", "WATCH", "AVOID")
    assert 0 < row["run_gap"] < 1 and row["flags"][0].startswith("run 1000: ") and row["value_at_old_defaults"] is not None
    assert "| TEST |" in (out / "shadow_table.md").read_text(encoding="utf-8")
    assert all(p.is_relative_to(out) for p in out.rglob("*")) and not (out / "shadow.lock").exists()


def test_it_is_resumable_a_run_on_disk_is_not_asked_again(tmp_path, monkeypatch):
    st, out, sent, metered, _ = arrange(tmp_path, monkeypatch, [T.reply(), T.reply()])
    go(st, out)
    first = (out / "shadow_table.json").read_text(encoding="utf-8")
    assert go(st, out) == 0 and len(sent) == 2 and len(metered) == 2                                         # no new call, no new meter read
    assert (out / "shadow_table.json").read_text(encoding="utf-8") == first


def test_it_stops_before_a_call_when_the_arms_meter_is_under_its_floor(tmp_path, monkeypatch, capsys):
    st, out, sent, metered, _ = arrange(tmp_path, monkeypatch, [T.reply()], meter=0.04)
    assert go(st, out) == 3 and sent == [] and "stopped before TEST seed 1000" in capsys.readouterr().out
    assert not list(out.glob("runs/*/result.json")) and json.loads((out / "shadow_table.json").read_text(encoding="utf-8")) == []


def test_a_failed_call_stops_with_4_keeps_the_finished_run_and_the_next_invocation_does_only_the_rest(tmp_path, monkeypatch):
    st, out, sent, metered, _ = arrange(tmp_path, monkeypatch, [T.reply(), ("infra_fatal", "down")])
    assert go(st, out) == 4 and len(list(out.glob("runs/*_decided_1000/result.json"))) == 1 and not list(out.glob("runs/*_decided_3000/result.json"))
    sent2 = T.stub(monkeypatch, [T.reply()])
    assert go(st, out) == 0 and len(sent2) == 1 and len(list(out.glob("runs/*/result.json"))) == 2
    assert json.loads((out / "shadow_table.json").read_text(encoding="utf-8"))[0]["valued"] is True


def test_a_name_the_code_refuses_is_in_the_table_with_its_reason_and_costs_no_call(tmp_path, monkeypatch):
    st, out, sent, metered, _ = arrange(tmp_path, monkeypatch, [T.reply()])
    monkeypatch.setattr(S.D.vrun, "prepare", lambda *a, **k: (_ for _ in ()).throw(desk.DeskRefusal("tax_unavailable", "x")))
    assert go(st, out) == 0 and sent == []
    (row,) = json.loads((out / "shadow_table.json").read_text(encoding="utf-8"))
    assert row["valued"] is False and row["new"] is None and row["new_verdict"] is None and "no usable tax rate" in row["reason"]
    assert "not valued" in (out / "shadow_table.md").read_text(encoding="utf-8")


def test_max_names_and_the_ticker_filter(tmp_path, monkeypatch):
    st, out, sent, metered, _ = arrange(tmp_path, monkeypatch, [T.reply(), T.reply()])
    assert go(st, out, "--tickers", "OTHER") == 0 and sent == []
    assert go(st, out, "--max-names", "0") == 0 and sent == [] and json.loads((out / "shadow_table.json").read_text(encoding="utf-8")) == []
    assert go(st, out, "--tickers", "TEST", "--max-names", "1") == 0 and len(sent) == 2


def test_a_name_stored_as_family_not_built_is_taken_as_real_estate_only_when_the_stored_documents_route_it(tmp_path, monkeypatch):
    """WO_NC9c: the shadow reaches REITs through decided_real_estate.routes on the stored SEC documents; every other not-built name stays out."""
    st = store_of(tmp_path)
    stem = "REIT_20261118T000000Z_abc123"
    rep = {"ticker": "REIT", "date": DATE, "analysis": "complete", "family": "family_not_built", "valued": False}
    (st / "gemini_site" / "ondemand" / "REIT.json").write_text(json.dumps(rep), encoding="utf-8")
    d = st / "m3m_sonnet" / "runs" / f"{stem}_1"
    d.mkdir(parents=True)
    (d / "packet.json").write_text(json.dumps(dict(T.PK, ticker="REIT")), encoding="utf-8")
    (d / "analysis.json").write_text(json.dumps(T.AN), encoding="utf-8")
    seen = []
    monkeypatch.setattr(S, "real_estate_family", lambda pk, raw: seen.append(raw) or True)
    got = {r["ticker"]: r["family"] for r, _ in S.stored_names(st, tmp_path / "raw")}
    assert got["REIT"] == "real_estate" and got["TEST"] == "operating" and seen == [tmp_path / "raw"]
    monkeypatch.setattr(S, "real_estate_family", lambda pk, raw: False)
    assert "REIT" not in {r["ticker"] for r, _ in S.stored_names(st)}

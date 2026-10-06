"""Shared test helpers: revision trees extracted from git, a worker runner, and synthetic companies."""
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
BASELINE_REV, CANDIDATE_REV = "fee17cf", "ac68e25"


def extract_tools(rev, dest):
    """`git archive <rev> tools/` into dest (a tree holding just tools/): the revision's code, byte for byte, in a throwaway dir."""
    data = subprocess.run(["git", "archive", "--format=tar", rev, "tools"], cwd=HARNESS_ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        tf.extractall(dest)
    return Path(dest)


def run_worker(arm, tree, job, tmp):
    tmp = Path(tmp)
    jp, op = tmp / f"job_{arm}.json", tmp / f"out_{arm}.json"
    jp.write_text(json.dumps(job), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "backtest_phase2.arm_worker", "--arm", arm, "--tree", str(tree), "--job", str(jp), "--out", str(op)],
                       cwd=HARNESS_ROOT, capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(op.read_text(encoding="utf-8"))


def _env():
    import os
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def company(years=range(2010, 2021), revenue0=1000.0, growth=0.05, margin=0.15, tax=0.25, da_frac=0.03, capex_frac=0.04,
            shares=100.0, cash=0.0, interest=0.0, amort=0.0, equity_frac=0.5, trend=0.0, om_noise=None):
    """A smooth synthetic company: rows by fiscal year with every field the arms and the record read."""
    rows = {}
    for i, y in enumerate(years):
        rev = revenue0 * (1 + growth) ** i
        om = margin + trend * i + (om_noise[i % len(om_noise)] if om_noise else 0.0)
        oi = om * rev
        pretax = oi + cash * 0.0 + 0.0
        ni = (oi + interest_income(cash, interest)) * (1 - tax)
        rows[str(y)] = {"revenue": rev, "operating_income": oi, "net_income": ni, "pretax_income": oi + interest_income(cash, interest),
                        "tax_provision": (oi + interest_income(cash, interest)) * tax, "da": da_frac * rev, "capex": capex_frac * rev,
                        "amortization_intangibles": amort, "interest_expense": 0.0, "equity": equity_frac * rev, "goodwill": 0.0,
                        "intangibles_ex_goodwill": 0.0, "cash": cash, "st_investments": None, "lt_investments": None,
                        "lt_debt": 0.0, "debt_lt_noncurrent": 0.0, "debt_current": 0.0, "short_term_borrowings_separate": None,
                        "current_assets": 0.3 * rev + cash, "current_liabilities": 0.2 * rev, "shares_diluted": shares}
    return rows


def interest_income(cash, y):
    return cash * y


def nm_of(rows, L=2020, shares=100.0, m=0.05, sector="Industrials", y_L=0.0, stub=6.0, untagged=("goodwill", "intangibles_ex_goodwill", "amortization_intangibles")):
    return {"cik": "0000000001", "rows": rows, "L": L, "stub_months": stub, "untagged": list(untagged), "dc_tags": {}, "shares": shares,
            "m": m, "sector": sector, "y_L": y_L, "adjL": 1.0}

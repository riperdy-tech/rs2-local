"""Test doubles for the gate-2 runner: a synthetic environment (the Muse layer's own fixtures), a fake server, a fake GPU probe and a clock.  TEST-ONLY: nothing here is a
valuation, the priors and the rates are the repository's labelled placeholders, and the model is the scripted mock of valuation/muse/tests/fixtures.py."""
from __future__ import annotations

import json
from typing import Callable, List, Optional

from rebuild_harness.gate2 import config
from rebuild_harness.gate2 import env as env_mod
from rebuild_harness.gate2 import sample as sample_mod
from valuation.muse.runner import MuseTransportError
from valuation.muse.tests import fixtures as fx

# dates after the fixtures' filings (the 10-K was filed 2026-02-28, the earnings release 2026-02-20, the 10-Q 2025-11-05)
TEST_DATES = ("2026-04-30", "2026-06-30")


def make_sample(n_per_date: int = 3, dates=TEST_DATES) -> dict:
    fams = ["operating", "operating", "financial", "commodity"]
    entries = {}
    for d in dates:
        entries[d] = [{"cik": f"{i + 1:010d}", "ticker": f"T{i + 1}", "family": fams[i % len(fams)]} for i in range(n_per_date)]
    return {"seed": config.SEED, "per_date": n_per_date, "dates": list(dates), "entries": entries}


class FakeEnv:
    """company_inputs(job) from the Muse fixtures: a synthetic company at the job's date; `refuse` / `boom` name ciks that are refused / raise."""

    def __init__(self, refuse=(), boom=()):
        self.refuse, self.boom, self.calls = set(refuse), set(boom), []

    def company_inputs(self, job):
        cik = str(job["cik"]).zfill(10)
        self.calls.append((job["date"], cik))
        if cik in self.boom:
            raise RuntimeError("synthetic failure in the environment")
        if cik in self.refuse:
            return env_mod.Refusal("refused", ["no_price_or_market_cap: synthetic"])
        pit = fx.make_pit(asof=job["date"], sic={"operating": "3674", "financial": "6021", "commodity": "1311"}[job["family"]], ticker=job.get("ticker") or "SYN")
        ident = dict(fx.IDENTITY, ticker=job.get("ticker") or "SYN")
        return env_mod.CompanyInputs(cik=cik, ticker=ident["ticker"], date=job["date"], family=job["family"], pit=pit, identity=ident, priors=fx.LabeledPlaceholderPriors(),
                                     disc_factory=fx.disc_factory, price_info={"price": fx.PRICE_SENTINEL, "market_cap": fx.MCAP_SENTINEL, "currency": "USD"},
                                     industry_context=fx.INDUSTRY_CONTEXT, documents=fx.docs(), quarters=fx.quarters(), seed=11, llm_seed=11, corr=None,
                                     stamps=["synthetic"], extra={"price_date": job["date"], "price_quality": "verified"})


class FakeServer:
    """The seams of Gate2Server that the runner uses; counts starts and stops."""
    endpoint = "http://127.0.0.1:8080"

    def __init__(self):
        self.up = False
        self.starts = 0
        self.stops = 0
        self.refuse_start: Optional[str] = None

    def is_up(self):
        return self.up

    def ensure_up(self):
        if self.up:
            return {"pid": 1, "vram_loaded_mib": 22000, "window": config.CONTEXT}
        if self.refuse_start:
            raise RuntimeError(self.refuse_start)
        self.up = True
        self.starts += 1
        return {"pid": 1, "vram_loaded_mib": 22000, "window": config.CONTEXT}

    def stop(self, timeout=180.0):
        if self.up:
            self.up = False
            self.stops += 1
        return True, "stopped"

    def our_pids(self):
        return [1] if self.up else []

    def our_vram_mib(self):
        return 22000 if self.up else None


class FakeProbe:
    """gpu.Probe stand-in: `busy` is a function (call number) -> a reason code or None."""

    def __init__(self, scenario: Callable[[int], Optional[str]] = lambda n: None):
        self.scenario, self.n = scenario, 0
        self.log: List[str] = []

    def _mode(self):
        return self.scenario(self.n)

    def ollama_loaded(self):
        self.n += 1
        return ["some-other-model"] if self._mode() == "ollama" else []

    def compute_apps(self):
        return [(4242, "game.exe")] if self._mode() == "app" else []

    def used_mib(self):
        return 9000 if self._mode() == "vram" else 800

    def pid_alive(self, pid):
        return False


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 7.0
        return self.t


class Flaky:
    """Wraps a client: raises MuseTransportError on the calls numbered in `fail_on` (1-based), counting every call."""

    def __init__(self, inner, fail_on=(), exc=None):
        self.inner, self.fail_on, self.n, self.exc = inner, set(fail_on), 0, exc

    def chat(self, request):
        self.n += 1
        if self.n in self.fail_on:
            raise self.exc or MuseTransportError("cannot reach http://127.0.0.1:8080: ConnectionRefusedError()")
        return self.inner.chat(request)

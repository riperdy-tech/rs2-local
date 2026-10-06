import json
import subprocess
from pathlib import Path

import pytest

from rebuild_harness import holdout


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


class FakeEngine:
    def __init__(self, name, files):
        self.engine_name, self.frozen_files = name, files

    def __call__(self, *a, **k):
        return {}


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "eng.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (r / "helper.py").write_text("X = 1\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "engine")
    return r


@pytest.fixture
def inputs(tmp_path):
    """Small stand-ins for everything a freeze names besides the code: a store, a price file, a Damodaran folder with a manifest, a priors folder with two vintages, the crosswalk, the
    headers, the configuration and the seeds."""
    import hashlib
    d = tmp_path / "data"
    (d / "store").mkdir(parents=True)
    (d / "store" / "0000000001.json.gz").write_bytes(b"store-1")
    (d / "store" / "0000000002.json.gz").write_bytes(b"store-2")
    (d / "prices.json").write_text('{"prices": {}}', encoding="utf-8")
    (d / "damodaran").mkdir()
    (d / "damodaran" / "betas.xls").write_bytes(b"betas")
    (d / "damodaran" / "MANIFEST.json").write_text(json.dumps({"files": {"betas.xls": {"sha256": hashlib.sha256(b"betas").hexdigest(), "bytes": 5}}}), encoding="utf-8")
    for y in ("2019", "2020"):
        (d / "priors" / y).mkdir(parents=True)
        (d / "priors" / y / "tables.json").write_text(json.dumps({"y": y}), encoding="utf-8")
    (d / "crosswalk.json").write_text('{"by_sic4": {}}', encoding="utf-8")
    (d / "headers.csv").write_text("cik,accession" + chr(10), encoding="utf-8")
    return {"store": d / "store", "prices": d / "prices.json", "damodaran": d / "damodaran", "priors": d / "priors", "crosswalk": d / "crosswalk.json", "headers": d / "headers.csv",
            "config": {"n_draws": 2000, "invalid_draw_max": 0.05}, "seeds": {"bootstrap": 20261007}}


def test_window_classification():
    assert holdout.classify("2017-01-01") == "development" and holdout.classify("2022-12-31") == "development"
    assert holdout.classify("2023-01-01") == "holdout" and holdout.classify("2024-12-31") == "holdout"
    assert holdout.classify("2016-06-30") == "outside_development_and_holdout" and holdout.classify("2025-10-31") == "outside_development_and_holdout"
    assert holdout.touches_holdout(["2022-12-30", "2023-06-30", "2024-01-02"]) == ["2023-06-30", "2024-01-02"]


def test_development_dates_need_no_freeze(repo):
    e = FakeEngine("e", [repo / "eng.py"])
    info = holdout.enforce(["2017-06-30", "2022-06-30"], [e], None)
    assert info["holdout_dates"] == [] and info["frozen"] == {}


def test_a_holdout_date_without_a_freeze_file_is_refused(repo, tmp_path):
    e = FakeEngine("e", [repo / "eng.py"])
    with pytest.raises(holdout.HoldoutRefused, match="no freeze file"):
        holdout.enforce(["2018-06-30", "2023-06-30"], [e], None)
    with pytest.raises(holdout.HoldoutRefused, match="no freeze file"):
        holdout.enforce(["2023-06-30"], [e], tmp_path / "missing.json")


def test_a_frozen_engine_passes_and_the_run_is_recorded_once(repo, tmp_path, inputs):
    e = FakeEngine("e", [repo / "eng.py", repo / "helper.py"])
    fz = tmp_path / "freeze.json"
    holdout.write_freeze(fz, [e], repo=repo, inputs=inputs)
    info = holdout.enforce(["2023-06-30", "2024-06-28"], [e], fz, repo=repo, inputs=inputs)
    assert info["frozen"]["e"] == git(repo, "rev-parse", "HEAD")
    with pytest.raises(holdout.HoldoutRefused, match="run once"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs)
    holdout.enforce(["2023-06-30"], [e], fz, repo=repo, allow_rerun=True, inputs=inputs)


def test_an_engine_edited_after_the_freeze_is_refused(repo, tmp_path, inputs):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    holdout.write_freeze(fz, [e], repo=repo, inputs=inputs)
    (repo / "eng.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="changed after the freeze"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs)


def test_a_commit_that_does_not_hold_the_file_is_refused(repo, tmp_path, inputs):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    doc = holdout.write_freeze(fz, [e], repo=repo, inputs=inputs)
    # the working file is changed AND the freeze re-hashed to match, but the named commit still holds the old content
    (repo / "eng.py").write_text("def f():\n    return 3\n", encoding="utf-8")
    doc["engines"]["e"]["files"]["eng.py"] = holdout.sha256_file(repo / "eng.py")
    fz.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="does not hold the frozen file"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs)


def test_a_commit_that_is_not_an_ancestor_of_head_is_refused(repo, tmp_path, inputs):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    doc = holdout.write_freeze(fz, [e], repo=repo, inputs=inputs)
    doc["engines"]["e"]["git_commit"] = "0" * 40
    fz.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="not an ancestor"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs)


def test_an_engine_missing_from_the_freeze_or_with_an_unlisted_file_is_refused(repo, tmp_path, inputs):
    e = FakeEngine("e", [repo / "eng.py"])
    other = FakeEngine("other", [repo / "eng.py"])
    fz = tmp_path / "freeze.json"
    holdout.write_freeze(fz, [e], repo=repo, inputs=inputs)
    with pytest.raises(holdout.HoldoutRefused, match="does not name engine 'other'"):
        holdout.enforce(["2023-06-30"], [e, other], fz, repo=repo, inputs=inputs)
    wider = FakeEngine("e", [repo / "eng.py", repo / "helper.py"])
    with pytest.raises(holdout.HoldoutRefused, match="does not list helper.py"):
        holdout.enforce(["2023-06-30"], [wider], fz, repo=repo, inputs=inputs)


def test_an_engine_with_no_declared_files_cannot_be_frozen(repo, tmp_path, inputs):
    e = FakeEngine("e", [])
    with pytest.raises(holdout.HoldoutRefused, match="no frozen_files"):
        holdout.write_freeze(tmp_path / "f.json", [e], repo=repo, inputs=inputs)


def test_a_refusal_happens_before_any_data_is_opened(tmp_path):
    """run_harness.run calls the lock first: a holdout date with no freeze raises before the data root is touched."""
    from rebuild_harness import engines, run_harness

    class Boom:
        price_source = None

        def __getattr__(self, name):
            raise AssertionError("the data layer was touched before the lock answered")

    with pytest.raises(holdout.HoldoutRefused):
        run_harness.run(["2023-06-30"], ["1"], [engines.earnings_yield], Boom(), tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ---- Addendum J10: the freeze names the data, the configuration, the seeds and the packages as well as the code ----------------------------------------------

def _freeze(repo, tmp_path, inputs, name="freeze.json"):
    e = FakeEngine("e", [repo / "eng.py"])
    fz = tmp_path / name
    doc = holdout.write_freeze(fz, [e], repo=repo, inputs=inputs)
    return e, fz, doc


def test_the_freeze_contents_name_every_input_by_hash(repo, tmp_path, inputs):
    import hashlib
    e, fz, doc = _freeze(repo, tmp_path, inputs)
    c = json.loads(fz.read_text(encoding="utf-8"))["contents"]
    assert set(holdout.CONTENT_KEYS) <= set(c)
    assert c["code_commit"] == git(repo, "rev-parse", "HEAD")
    lines = "\n".join(f"{n}\t{len(b)}\t{hashlib.sha256(b).hexdigest()}" for n, b in (("0000000001.json.gz", b"store-1"), ("0000000002.json.gz", b"store-2")))
    assert c["point_in_time_store"] == {"tree_sha256": hashlib.sha256(lines.encode()).hexdigest(), "n_files": 2, "bytes": 14}
    assert c["price_snapshot"]["sha256"] == hashlib.sha256(b'{"prices": {}}').hexdigest() and c["price_snapshot"]["kind"] == "file"
    assert c["damodaran"]["files"] == {"betas.xls": hashlib.sha256(b"betas").hexdigest()} and len(c["damodaran"]["manifest_sha256"]) == 64
    assert set(c["priors"]["vintages"]) == {"2019", "2020"} and c["priors"]["n_files"] == 2 and len(c["priors"]["tree_sha256"]) == 64
    assert len(c["industry_crosswalk"]["sha256"]) == 64 and len(c["sic_headers"]["sha256"]) == 64
    assert c["config"] == {"invalid_draw_max": 0.05, "n_draws": 2000} and c["seeds"] == {"bootstrap": 20261007}
    assert c["packages"]["python"].count(".") == 2 and "numpy" in c["packages"]
    info = holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs)
    assert info["contents_verified"] is True and holdout.enforce(["2022-06-30"], [e], None)["contents_verified"] is False


def test_a_freeze_cannot_be_written_without_its_contents(repo, tmp_path, inputs):
    e = FakeEngine("e", [repo / "eng.py"])
    with pytest.raises(holdout.HoldoutRefused, match="no `inputs` given"):
        holdout.write_freeze(tmp_path / "f.json", [e], repo=repo)
    assert not (tmp_path / "f.json").exists()
    for k in ("store", "prices", "damodaran", "priors", "crosswalk", "config", "seeds"):
        with pytest.raises(holdout.HoldoutRefused, match=k):
            holdout.write_freeze(tmp_path / "g.json", [e], repo=repo, inputs={x: v for x, v in inputs.items() if x != k})
    no_vint = dict(inputs, priors=tmp_path / "data" / "store")
    with pytest.raises(holdout.HoldoutRefused, match="vintage"):
        holdout.write_freeze(tmp_path / "h.json", [e], repo=repo, inputs=no_vint)
    assert holdout.write_freeze(tmp_path / "ok.json", [e], repo=repo, inputs=dict(inputs, headers=None))["contents"]["sic_headers"] is None


def test_a_holdout_run_that_states_no_inputs_or_whose_freeze_has_no_contents_is_refused(repo, tmp_path, inputs):
    e, fz, doc = _freeze(repo, tmp_path, inputs)
    with pytest.raises(holdout.HoldoutRefused, match="must state its inputs"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo)
    old = {k: v for k, v in doc.items() if k != "contents"}
    fz2 = tmp_path / "old.json"
    fz2.write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(holdout.HoldoutRefused, match="no `contents`"):
        holdout.enforce(["2023-06-30"], [e], fz2, repo=repo, inputs=inputs, record=False)
    for k in holdout.CONTENT_KEYS:
        part = json.loads(json.dumps(doc))
        del part["contents"][k]
        fz3 = tmp_path / f"part_{k}.json"
        fz3.write_text(json.dumps(part), encoding="utf-8")
        with pytest.raises(holdout.HoldoutRefused, match=k):
            holdout.enforce(["2023-06-30"], [e], fz3, repo=repo, inputs=inputs, record=False)


def test_every_changed_input_is_refused_by_name(repo, tmp_path, inputs):
    e, fz, doc = _freeze(repo, tmp_path, inputs)

    def refused(match, mutate, inp=None):
        undo = mutate()
        try:
            with pytest.raises(holdout.HoldoutRefused, match=match):
                holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inp or inputs, record=False)
        finally:
            undo()

    store = inputs["store"]

    def edit_store():
        (store / "0000000001.json.gz").write_bytes(b"changed")
        return lambda: (store / "0000000001.json.gz").write_bytes(b"store-1")
    refused("`point_in_time_store`", edit_store)

    def add_store():
        (store / "0000000003.json.gz").write_bytes(b"x")
        return lambda: (store / "0000000003.json.gz").unlink()
    refused("`point_in_time_store`", add_store)

    def edit_price():
        inputs["prices"].write_text('{"prices": {"A": {}}}', encoding="utf-8")
        return lambda: inputs["prices"].write_text('{"prices": {}}', encoding="utf-8")
    refused("`price_snapshot`", edit_price)

    def edit_dam():
        (inputs["damodaran"] / "betas.xls").write_bytes(b"BETAS")
        return lambda: (inputs["damodaran"] / "betas.xls").write_bytes(b"betas")
    refused("manifest says", edit_dam)

    def edit_priors():
        p = inputs["priors"] / "2020" / "tables.json"
        p.write_text('{"y": "changed"}', encoding="utf-8")
        return lambda: p.write_text('{"y": "2020"}', encoding="utf-8")
    refused("`priors`", edit_priors)

    def edit_cross():
        inputs["crosswalk"].write_text('{"by_sic4": {"1": 1}}', encoding="utf-8")
        return lambda: inputs["crosswalk"].write_text('{"by_sic4": {}}', encoding="utf-8")
    refused("`industry_crosswalk`", edit_cross)

    def edit_headers():
        inputs["headers"].write_text("cik,accession" + chr(10) + "1,2" + chr(10), encoding="utf-8")
        return lambda: inputs["headers"].write_text("cik,accession" + chr(10), encoding="utf-8")
    refused("`sic_headers`", edit_headers)
    refused("`config`", lambda: (lambda: None), dict(inputs, config={"n_draws": 2000, "invalid_draw_max": 0.10}))
    refused("`seeds`", lambda: (lambda: None), dict(inputs, seeds={"bootstrap": 1}))
    refused("`sic_headers`", lambda: (lambda: None), dict(inputs, headers=None))


def test_a_changed_package_version_or_a_new_commit_is_refused(repo, tmp_path, inputs, monkeypatch):
    e, fz, doc = _freeze(repo, tmp_path, inputs)
    real = holdout.package_versions()
    monkeypatch.setattr(holdout, "package_versions", lambda names=holdout.PACKAGES: dict(real, numpy="0.0.1"))
    with pytest.raises(holdout.HoldoutRefused, match="`packages`"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs, record=False)
    monkeypatch.undo()
    (repo / "helper.py").write_text("X = 2" + chr(10), encoding="utf-8")                   # a new commit on top of the frozen one: the contents name the commit they were frozen at
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "later")
    with pytest.raises(holdout.HoldoutRefused, match="`code_commit`"):
        holdout.enforce(["2023-06-30"], [e], fz, repo=repo, inputs=inputs, record=False)


def test_the_tree_hash_ignores_order_and_catches_a_rename_and_an_empty_file(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "sub").mkdir(parents=True)
    (a / "x.txt").write_bytes(b"1")
    (a / "sub" / "y.txt").write_bytes(b"2")
    (b / "sub" / "y.txt").write_bytes(b"2")                      # created in the other order
    (b / "x.txt").write_bytes(b"1")
    assert holdout.tree_hash(a) == holdout.tree_hash(b) and holdout.tree_hash(a)["n_files"] == 2
    (b / "x.txt").rename(b / "z.txt")
    assert holdout.tree_hash(a)["tree_sha256"] != holdout.tree_hash(b)["tree_sha256"]
    (b / "z.txt").rename(b / "x.txt")
    (b / "empty.txt").write_bytes(b"")
    assert holdout.tree_hash(a)["tree_sha256"] != holdout.tree_hash(b)["tree_sha256"]
    with pytest.raises(holdout.HoldoutRefused):
        holdout.tree_hash(tmp_path / "nowhere")


def test_a_development_run_writes_no_file_and_needs_no_freeze(tmp_path):
    e = FakeEngine("e", [])
    before = set(tmp_path.iterdir())
    assert holdout.enforce(["2020-01-31", "2022-12-31"], [e], None)["contents_verified"] is False
    assert set(tmp_path.iterdir()) == before

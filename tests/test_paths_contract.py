"""The STOCKS_ROOT path contract (paths.py).

These tests pin the four properties that make the planned folder move a configuration change
rather than a code change:

  1. resolution is a NO-OP against the current layout - the probe returns exactly the paths that
     were hardcoded in config.json before 2026-09-22;
  2. a per-key environment variable is honoured VERBATIM and never probed or second-guessed;
  3. the probe accepts the post-move SIBLING layout as well as the current nested one, which is
     what allows the move to happen with no edit here;
  4. an unresolvable root RAISES and names every candidate, rather than degrading into a path
     that does not exist. That last one is the important one: a silently-wrong screener_data_dir
     reads as a book with no names in it, which the pipeline cannot distinguish from an empty
     watchlist.

Every test drives resolution through a tmp_path and an explicit environment, so none of them
depends on this machine's real layout.
"""

import json

import pytest

import paths


# ---- 1. no-op against the layout that exists today -------------------------------------------

def test_the_current_nested_layout_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREENER_DATA_DIR", raising=False)
    monkeypatch.delenv("MRI_OUTPUTS_DIR", raising=False)
    monkeypatch.delenv("MRI_ANCHORS_DIR", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))

    (tmp_path / "Stock Screener" / "Stock Screener" / "public" / "data").mkdir(parents=True)
    (tmp_path / "Stock Screener" / "Macro Regime Indicator" / "outputs").mkdir(parents=True)
    (tmp_path / "screener-publish").mkdir()

    assert paths.resolve("screener_data_dir") == (
        tmp_path / "Stock Screener" / "Stock Screener" / "public" / "data")
    assert paths.resolve("mri_outputs_dir") == (
        tmp_path / "Stock Screener" / "Macro Regime Indicator" / "outputs")
    assert paths.resolve("screener_publish_repo") == tmp_path / "screener-publish"


def test_anchors_default_to_the_mri_outputs_directory(tmp_path, monkeypatch):
    """The anchors are additive artifacts written BESIDE the other MRI outputs."""
    monkeypatch.delenv("MRI_ANCHORS_DIR", raising=False)
    monkeypatch.delenv("MRI_OUTPUTS_DIR", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))
    outputs = tmp_path / "macro-regime-indicator" / "outputs"
    outputs.mkdir(parents=True)

    assert paths.resolve("anchors_dir") == outputs
    assert paths.resolve("anchors_dir") == paths.resolve("mri_outputs_dir")


# ---- 2. environment overrides win, and are taken literally -----------------------------------

def test_env_override_is_used_verbatim_even_when_it_does_not_exist(tmp_path, monkeypatch):
    """An operator who names a path means it. A typo must fail at the consumer, loudly, not be
    silently replaced by a probe hit - that would hide the typo behind plausible data."""
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))
    (tmp_path / "stock-screener" / "public" / "data").mkdir(parents=True)
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path / "typo" / "nowhere"))

    assert paths.resolve("screener_data_dir") == tmp_path / "typo" / "nowhere"


def test_env_override_beats_a_value_pinned_in_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path / "from_env"))
    pinned = {"screener_data_dir": str(tmp_path / "from_config")}

    assert paths.resolve("screener_data_dir", pinned) == tmp_path / "from_env"


def test_a_pinned_config_value_beats_the_probe(tmp_path, monkeypatch):
    """Kept so a machine with an unusual layout can still pin a path the old way."""
    monkeypatch.delenv("SCREENER_DATA_DIR", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))
    (tmp_path / "stock-screener" / "public" / "data").mkdir(parents=True)
    pinned = {"screener_data_dir": str(tmp_path / "pinned")}

    assert paths.resolve("screener_data_dir", pinned) == tmp_path / "pinned"


def test_an_empty_or_null_config_value_does_not_count_as_pinned(tmp_path, monkeypatch):
    """config.json ships these keys as null. `null` and `""` mean "resolve it", not "use ''"."""
    monkeypatch.delenv("SCREENER_DATA_DIR", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))
    probe_hit = tmp_path / "stock-screener" / "public" / "data"
    probe_hit.mkdir(parents=True)

    for pinned in ({"screener_data_dir": None}, {"screener_data_dir": ""},
                   {"screener_data_dir": "   "}):
        assert paths.resolve("screener_data_dir", pinned) == probe_hit


def test_anchors_dir_reads_its_own_variable_before_the_shared_one(tmp_path, monkeypatch):
    monkeypatch.setenv("MRI_OUTPUTS_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MRI_ANCHORS_DIR", str(tmp_path / "calibration_run"))

    assert paths.resolve("anchors_dir") == tmp_path / "calibration_run"
    assert paths.resolve("mri_outputs_dir") == tmp_path / "outputs"


# ---- 3. the post-move layout resolves with no code change ------------------------------------

def test_the_post_move_sibling_layout_resolves(tmp_path, monkeypatch):
    for var in ("SCREENER_DATA_DIR", "MRI_OUTPUTS_DIR", "MRI_ANCHORS_DIR",
                "SCREENER_PUBLISH_REPO"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))

    (tmp_path / "stock-screener" / "public" / "data").mkdir(parents=True)
    (tmp_path / "macro-regime-indicator" / "outputs").mkdir(parents=True)
    (tmp_path / "screener-publish").mkdir()

    assert paths.resolve("screener_data_dir") == tmp_path / "stock-screener" / "public" / "data"
    assert paths.resolve("mri_outputs_dir") == (
        tmp_path / "macro-regime-indicator" / "outputs")
    assert paths.resolve("screener_publish_repo") == tmp_path / "screener-publish"


def test_the_nested_layout_wins_while_both_exist(tmp_path, monkeypatch):
    """During the move both spellings can be on disk. The current one is listed first and wins, so
    a half-finished move never silently reads a freshly-created empty sibling."""
    monkeypatch.delenv("SCREENER_DATA_DIR", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))
    nested = tmp_path / "Stock Screener" / "Stock Screener" / "public" / "data"
    nested.mkdir(parents=True)
    (tmp_path / "stock-screener" / "public" / "data").mkdir(parents=True)

    assert paths.resolve("screener_data_dir") == nested


# ---- 4. an unresolvable location is fatal and self-explaining ---------------------------------

def test_an_unresolvable_key_raises_and_names_every_candidate(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREENER_DATA_DIR", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))

    with pytest.raises(FileNotFoundError) as excinfo:
        paths.resolve("screener_data_dir")

    msg = str(excinfo.value)
    assert "SCREENER_DATA_DIR" in msg
    assert str(tmp_path) in msg
    assert "Stock Screener" in msg and "stock-screener" in msg
    assert "do not guess" in msg


def test_required_false_returns_none_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREENER_PUBLISH_REPO", raising=False)
    monkeypatch.setenv("STOCKS_ROOT", str(tmp_path))

    assert paths.resolve("screener_publish_repo", required=False) is None


# ---- load_config ------------------------------------------------------------------------------

def test_load_config_overlays_all_four_keys_as_strings(tmp_path, monkeypatch):
    for key, var in (("screener_data_dir", "SCREENER_DATA_DIR"),
                     ("screener_publish_repo", "SCREENER_PUBLISH_REPO"),
                     ("mri_outputs_dir", "MRI_OUTPUTS_DIR")):
        monkeypatch.setenv(var, str(tmp_path / key))
    monkeypatch.delenv("MRI_ANCHORS_DIR", raising=False)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "screener_data_dir": None, "screener_publish_repo": None,
        "mri_outputs_dir": None, "anchors_dir": None, "depth_samples": 3,
    }), encoding="utf-8")

    cfg = paths.load_config(cfg_path)

    for key in ("screener_data_dir", "screener_publish_repo", "mri_outputs_dir", "anchors_dir"):
        assert isinstance(cfg[key], str) and cfg[key]
    assert cfg["depth_samples"] == 3, "non-path settings must pass through untouched"
    assert cfg["anchors_dir"] == cfg["mri_outputs_dir"]


def test_load_config_tolerates_a_byte_order_mark(tmp_path, monkeypatch):
    """config.json has carried a BOM at times; json.loads rejects one, so the reader uses
    utf-8-sig. A commit subject in this repo's own history carries a stray BOM for the same
    reason - the tooling that writes these files is not consistent about it."""
    for var in ("SCREENER_DATA_DIR", "SCREENER_PUBLISH_REPO", "MRI_OUTPUTS_DIR"):
        monkeypatch.setenv(var, str(tmp_path / "x"))
    monkeypatch.delenv("MRI_ANCHORS_DIR", raising=False)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"depth_samples": 3}).encode("utf-8"))

    assert paths.load_config(cfg_path)["depth_samples"] == 3


def test_stocks_root_defaults_to_the_repo_parent(monkeypatch):
    """The default is today's location, which is what makes this contract a no-op on arrival."""
    monkeypatch.delenv("STOCKS_ROOT", raising=False)

    assert paths.stocks_root() == paths.HERE.parent

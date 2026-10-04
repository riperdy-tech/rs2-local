"""Muse integration, M1 and M10: the config keys, and production's values unchanged.

The expected values are written out here from brief_muse_integration.md (M1) and P7's registration, not read back from
the module that consumes them, so a drifted pin fails here."""
import json
from pathlib import Path

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))

EXPECTED_LLAMACPP = {
    "build": "b11272",
    "server_exe": "C:\\Users\\riper\\models\\llamacpp\\b11272\\llama-server.exe",
    "build_manifest_sha256": "79472cf31743b42fa5056bf89025ee284b7835a05e56e49e3fcb34381416f02c",
    "model_path": "C:\\Users\\riper\\models\\muse\\Muse-Glimmer-30B-UD-Q5_K_M.gguf",
    "model_sha256": "27c27bc0cc2591344a9ef977d57aa79a9d36ddebee59660bd2abbf738f940f5b",
    "drafter_path": "C:\\Users\\riper\\models\\dflash\\Muse-Glimmer-30B-DFlash2-Q8_0.gguf",
    "drafter_sha256": "b13b6783ca118ab09bd598ab6a17d1742775b5c86c41bb77e78d6c30837f923d",
    "host": "127.0.0.1",
    "port": 8080,
    "server_cmdline_sha256": "87f5b5780514d2e516f7f69c5c78c280ac563991ca32efd4404fb7c98dd0f1a7",
    "system_file": "charters/SYSTEM_muse_v33.txt",
    "system_sha256": "decd1a19c8fd4fc8ee9ed90817c88034962bee772b58340704272efea50a45df",
    "model_tag": "muse-glimmer-30b-ud-q5km-dflash2-n15-charter-v3.3",
    "upstream_timeout_s": 3600,
    "load_timeout_s": 300,
    "vram_loaded_mib_band": None,
}


def test_the_llamacpp_block_is_exactly_m1s_keys_and_values():
    assert CONFIG["llamacpp"] == EXPECTED_LLAMACPP


def test_the_llamacpp_block_keeps_m1s_key_order():
    assert list(CONFIG["llamacpp"]) == list(EXPECTED_LLAMACPP)


def test_production_stays_on_ollama_with_its_model_unchanged():
    assert CONFIG["depth_provider"] == "ollama"
    assert CONFIG["depth_model"] == "rs2-analyst-deep-mtp5-v33"
    assert CONFIG["research_model"] == "rs2-research"          # the research helper stays on Ollama under both providers
    assert CONFIG["depth_ctx"] == 98304                          # the window the server's -c is pinned to
    assert CONFIG["vram_unload_timeout_s"] == 180                # M3's stop() wait


def test_the_band_is_unset_until_the_m9_preflight_measures_it():
    assert CONFIG["llamacpp"]["vram_loaded_mib_band"] is None


def test_the_new_keys_carry_notes_in_the_files_convention():
    assert isinstance(CONFIG["_depth_provider_note"], str) and CONFIG["_depth_provider_note"]
    assert isinstance(CONFIG["_llamacpp_note"], str) and CONFIG["_llamacpp_note"]


def test_the_model_tag_is_not_an_ollama_model_name_in_the_config():
    ollama_names = {CONFIG["depth_model"], CONFIG["research_model"], CONFIG["model"]}
    ollama_names |= set(CONFIG.get("model_v31_candidate", {}).values())
    assert CONFIG["llamacpp"]["model_tag"] not in ollama_names

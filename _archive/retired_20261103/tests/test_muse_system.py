"""Muse integration, M4 / M8 item 5 (file part): the SYSTEM text the llamacpp provider injects.

charters/SYSTEM_muse_v33.txt is b"Reasoning strength: xhigh\n" plus the SYSTEM block of the v33 Modelfile, LF only.
The pins below are written out from brief_muse_integration.md and P7's registration."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_muse_system as mms  # noqa: E402

SYSTEM_FILE = ROOT / "charters" / "SYSTEM_muse_v33.txt"
PREFIX = b"Reasoning strength: xhigh\n"
FILE_BYTES, FILE_SHA = 17081, "decd1a19c8fd4fc8ee9ed90817c88034962bee772b58340704272efea50a45df"
BLOCK_BYTES, BLOCK_SHA = 17055, "ff033c2519528445a1f2e56a797746524d64bff7d65e5a31612be35d6cbdfc22"   # the Ollama v33 system layer AT10 pinned
P7_V32_BYTES, P7_V32_SHA = 16444, "f7f7a0d172aa68d7f0c2be1fbc9fe18cbf45772df310b1cf2c5a528467672155"  # SP/p7_serving/SYSTEM_muse_v32.txt


def sha(b):
    return hashlib.sha256(b).hexdigest()


def test_the_file_is_the_pinned_bytes():
    raw = SYSTEM_FILE.read_bytes()
    assert len(raw) == FILE_BYTES and sha(raw) == FILE_SHA


def test_the_file_is_the_prefix_then_the_v33_block_lf_only():
    raw = SYSTEM_FILE.read_bytes()
    assert raw.startswith(PREFIX) and b"\r" not in raw
    block = raw[len(PREFIX):]
    assert len(block) == BLOCK_BYTES and sha(block) == BLOCK_SHA


def test_the_block_is_the_modelfiles_system_text_byte_for_byte():
    # extracted here by a different route from the generator's: split on the two triple-quote fences
    text = (ROOT / "RS2-Analyst-Deep-MTP5-v33.Modelfile").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert text.count('SYSTEM """') == 1 and text.count('"""') == 2
    i = text.index('SYSTEM """') + len('SYSTEM """')
    assert SYSTEM_FILE.read_bytes()[len(PREFIX):] == text[i:text.index('"""', i)].encode("utf-8")


def test_the_generator_reproduces_the_file_on_disk():
    assert mms.build() == SYSTEM_FILE.read_bytes()
    assert mms.main(["--check"]) == 0


def test_the_same_construction_on_v32_reproduces_p7s_file_byte_for_byte():
    b = mms.build(ROOT / "RS2-Analyst-Deep-MTP5-v32.Modelfile")
    assert len(b) == P7_V32_BYTES and sha(b) == P7_V32_SHA


def test_a_crlf_modelfile_and_an_lf_modelfile_generate_the_same_bytes(tmp_path):
    src = (ROOT / "RS2-Analyst-Deep-MTP5-v33.Modelfile").read_bytes().replace(b"\r\n", b"\n")
    (tmp_path / "lf.Modelfile").write_bytes(src)
    (tmp_path / "crlf.Modelfile").write_bytes(src.replace(b"\n", b"\r\n"))
    assert mms.build(tmp_path / "lf.Modelfile") == mms.build(tmp_path / "crlf.Modelfile") == SYSTEM_FILE.read_bytes()


@pytest.mark.parametrize("text", ["FROM x\n", 'SYSTEM """a"""\nSYSTEM """b"""\n'])
def test_the_generator_refuses_anything_but_exactly_one_system_block(text):
    with pytest.raises(ValueError):
        mms.system_block(text.encode("utf-8"))


def test_check_fails_when_the_file_differs(tmp_path, monkeypatch):
    other = tmp_path / "SYSTEM_muse_v33.txt"
    other.write_bytes(SYSTEM_FILE.read_bytes() + b" ")
    monkeypatch.setattr(mms, "OUT", other)
    assert mms.main(["--check"]) == 1


def test_git_keeps_the_file_byte_exact_on_every_checkout():
    """With autocrlf on Windows a text file is checked out as CRLF and the pinned sha256 would not hold; .gitattributes
    marks the pinned text files binary."""
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    out = subprocess.run(["git", "check-attr", "text", "--", "charters/SYSTEM_muse_v33.txt"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    assert out.strip().endswith("text: unset"), out


def test_the_configs_pins_are_this_files():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["llamacpp"]
    assert cfg["system_file"] == "charters/SYSTEM_muse_v33.txt" and cfg["system_sha256"] == FILE_SHA
    assert (ROOT / cfg["system_file"]).read_bytes() == SYSTEM_FILE.read_bytes()


def test_the_prefix_is_not_part_of_the_charter_the_qwen_model_sees():
    # the Ollama v33 Modelfile's SYSTEM block does not start with the prefix: Qwen's TEMPLATE carries its own preamble
    block = mms.system_block((ROOT / "RS2-Analyst-Deep-MTP5-v33.Modelfile").read_bytes())
    assert not block.startswith(PREFIX) and re.match(rb"\xe2\x95\x90", block)

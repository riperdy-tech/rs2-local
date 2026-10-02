#!/usr/bin/env python3
"""make_muse_system.py - generate charters/SYSTEM_muse_v33.txt, the SYSTEM text of the llamacpp provider
(brief_muse_integration.md M4).

The file is exactly  b"Reasoning strength: xhigh\n"  followed by the SYSTEM block of
RS2-Analyst-Deep-MTP5-v33.Modelfile, LF line endings only, no other change: 17,081 bytes, sha256
decd1a19c8fd4fc8ee9ed90817c88034962bee772b58340704272efea50a45df (the block alone is 17,055 bytes, sha256 ff033c25..., byte-equal
to the Ollama v33 system layer). The prefix is Muse's reasoning-strength switch; in the Qwen model the TEMPLATE's own
preamble plays that role. Neither is part of the charter's text. P7's SYSTEM_muse_v32.txt is the same construction on the
v32 Modelfile (a test reproduces it byte for byte).

A Modelfile checked out with CRLF line endings (git's autocrlf on Windows) is read as LF: only CRLF pairs are converted.
A charter change is a versioned decision (workspace non-negotiable 7): it makes a NEW Modelfile tag and a NEW
SYSTEM_muse_v3N.txt, never an edit of this one.

    python tools/make_muse_system.py            write charters/SYSTEM_muse_v33.txt, print its size and sha256
    python tools/make_muse_system.py --check    exit 1 unless the file on disk is what the Modelfile generates
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PREFIX = b"Reasoning strength: xhigh\n"
MODELFILE = HERE / "RS2-Analyst-Deep-MTP5-v33.Modelfile"
OUT = HERE / "charters" / "SYSTEM_muse_v33.txt"
_BLOCK = re.compile(r'^SYSTEM\s+"""(.*?)"""', re.S | re.M)


def system_block(modelfile_bytes):
    """The SYSTEM block of a Modelfile as UTF-8 bytes with LF line endings. Exactly one block, or ValueError."""
    text = modelfile_bytes.decode("utf-8").replace("\r\n", "\n")
    found = _BLOCK.findall(text)
    if len(found) != 1:
        raise ValueError(f"expected exactly one SYSTEM triple-quoted block, found {len(found)}")
    return found[0].encode("utf-8")


def build(modelfile=MODELFILE):
    """The bytes of the Muse SYSTEM file for a Modelfile."""
    return PREFIX + system_block(Path(modelfile).read_bytes())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    want = build()
    sha = hashlib.sha256(want).hexdigest()
    if a.check:
        have = OUT.read_bytes() if OUT.exists() else None
        if have != want:
            print(f"{OUT} is not what {MODELFILE.name} generates (generated sha256 {sha})")
            return 1
        print(f"ok {OUT} bytes={len(want)} sha256={sha}")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(want)
    print(f"{OUT} bytes={len(want)} sha256={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

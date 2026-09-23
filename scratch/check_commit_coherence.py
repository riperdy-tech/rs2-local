"""Would a scoped commit pass its own tests?

Checks whether the files INSIDE a proposed commit are self-consistent, given that tests being
committed depend on files the scope EXCLUDES.

The concrete worry: `tools/audit_202608/tests/test_charter_single_source.py` (new, untracked)
asserts three things about files outside the chosen scope:
  * `api_chat.CHARTER == prompts/charter_v3.0.md`   -> prompts/ is UNTRACKED
  * `deep_api_run._rs2_framework() == Modelfile SYSTEM block` -> the Modelfile is MODIFIED
  * `import api_chat`                                -> api_chat.py is MODIFIED

If those excluded files are needed for the tests to pass, then a commit of the source changes
alone is a commit that fails its own suite on a fresh checkout.

Run:  python scratch/check_commit_coherence.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BASE = "HEAD"


def show(rev_path):
    p = subprocess.run(["git", "show", rev_path], cwd=HERE, capture_output=True)
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", errors="replace")


def system_block(text):
    if not text or 'SYSTEM """' not in text:
        return None
    body = text.split('SYSTEM """', 1)[1]
    return body.split('"""', 1)[0].replace("\r\n", "\n").strip("\n")


def norm(text):
    return (text or "").replace("\r\n", "\n").strip()


def main():
    charter_path = HERE / "prompts" / "charter_v3.0.md"
    print("=== runtime dependency ===")
    print(f"  prompts/charter_v3.0.md exists on disk : {charter_path.exists()}")
    tracked = subprocess.run(["git", "ls-files", "prompts"], cwd=HERE,
                             capture_output=True, text=True).stdout.strip()
    print(f"  tracked under prompts/                 : {tracked or '(nothing)'}")

    if not charter_path.exists():
        print("\nCANNOT CHECK: charter file missing.")
        return 2
    charter = norm(charter_path.read_text(encoding="utf-8", errors="replace"))
    print(f"  charter length                         : {len(charter)} chars")

    print("\n=== Modelfile: would the COMMITTED version agree with the charter? ===")
    wf_model = (HERE / "RS2-Analyst-Deep-MTP5.Modelfile").read_text(
        encoding="utf-8-sig", errors="replace")
    wf_sys = norm(system_block(wf_model))
    head_model = show(f"{BASE}:RS2-Analyst-Deep-MTP5.Modelfile")
    head_sys = norm(system_block(head_model)) if head_model else None

    print(f"  working tree Modelfile SYSTEM == charter : {wf_sys == charter}")
    print(f"  HEAD Modelfile SYSTEM        == charter : {head_sys == charter}")
    if head_sys is not None and wf_sys is not None and head_sys != wf_sys:
        print(f"  -> HEAD and working Modelfiles DIFFER ({len(head_sys)} vs {len(wf_sys)} chars)")

    print("\n=== api_chat.py: would the COMMITTED version satisfy the test? ===")
    head_chat = show(f"{BASE}:api_llm/api_chat.py") or ""
    for label, text in (("HEAD", head_chat),
                        ("working", (HERE / "api_llm" / "api_chat.py").read_text(
                            encoding="utf-8", errors="replace"))):
        has_charter = 'CHARTER = ROOT / "prompts" / "charter_v3.0.md"' in text
        rs2txt = "RS2.txt" in text and 'CHARTER = ROOT / "RS2.txt"' in text
        print(f"  {label:<8} CHARTER->charter_v3.0.md: {has_charter:<5}  CHARTER->RS2.txt: {rs2txt}")

    print("\n=== VERDICT ===")
    blockers = []
    if wf_sys != charter:
        blockers.append("working Modelfile SYSTEM block does not match the charter")
    if head_sys != charter:
        blockers.append(
            f"{BASE} Modelfile SYSTEM block does NOT match the charter -> a commit that "
            "excludes the Modelfile would FAIL test_charter_single_source.py on checkout")
    if not tracked:
        blockers.append(
            "prompts/charter_v3.0.md is UNTRACKED -> a commit referencing it ships a runtime "
            "path with no file behind it (the exact bug the census was written for)")
    if 'CHARTER = ROOT / "prompts" / "charter_v3.0.md"' not in head_chat:
        blockers.append(
            f"{BASE} api_chat.py does not point at the charter -> a commit that excludes "
            "api_chat.py would FAIL test_charter_single_source.py on checkout")

    if blockers:
        print("  SCOPE IS NOT SELF-CONSISTENT:")
        for b in blockers:
            print(f"    - {b}")
        return 1
    print("  Scope is self-consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

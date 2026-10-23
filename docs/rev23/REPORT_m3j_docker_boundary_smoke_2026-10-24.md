# Milestone 3J — Docker OS-boundary smoke and fresh-run promotion blockers

**Date:** 2026-10-24 KST · **Verdict: disposable SYNTHETIC container-boundary test PASSED; production scorer runtime and fresh PIT data are NOT approved or tested.** No portfolio/trading action, broker integration, Qwen GPU or deployment.

## 1. What was established from the actual Windows PC

A read-only runtime probe confirmed Docker Engine/Server **29.6.2, Linux backend**, and an already present local `python:3.12-slim` image. The operating bridge runs under the current Windows account with `os_isolated=false`; that bridge itself is **not** a sandbox. We therefore ran precisely **one disposable Linux Docker container** (`--rm` and `--pull never`) using the existing local image, and explicitly configured:

- `--network none` — no external network route.
- `--read-only` — read-only root filesystem.
- `--user 65534:65534`, `--cap-drop ALL`, `--security-opt no-new-privileges`.
- `--pids-limit 32 --memory 256m --cpus 0.5`.
- `--tmpfs /tmp:rw,noexec,nosuid,size=16m`.
- **Only** the one harmless scratch test script `m3j_sandbox_probe.py` bind-mounted at `/probe.py` **read-only** and one dedicated scratch output folder writable at `/out`. **No production repository, shared secrets, Docker socket, live prices, trading system or model was mounted into the container.**

The script attempted only harmless negative-control operations: write to an unmounted root path, overwrite its read-only script path, connect to `1.1.1.1:443` (network blocked), and write its outcome to the one allowed `/out` directory. It did **not** import or invoke the scorer.

## 2. Actual Docker run and independently checked output

The Docker CLI exited **0** and returned `boundary_probe_passed=true`. An actual created file was read at:

`stocks-workspace/scratch/baselineA/m3j_boundary_output_20261024/boundary.json`

Observed contents (UTC **2026-10-23T17:13:55.989703+00:00**, 2026-10-24 02:13:55 KST):

| Verified observation | Actual |
|---|---|
| Container UID / GID | `65534 / 65534` (not root) |
| Effective capabilities | `0000000000000000` (none) |
| Root filesystem | read-only |
| Bound source script | read-only |
| Root escape-write attempt | denied: Linux errno `30` (`EROFS`) |
| Script write attempt | denied: Linux errno `30` (`EROFS`) |
| External TCP attempt | denied: Linux errno `101` (`ENETUNREACH`) |
| Production filesystem directly mounted under probed host paths | false |
| Scratch-only output | successfully written |
| Producer / model / broker invoked | false / false / false |

Original output file SHA256: `912d85fc5750cbcbda2dfa7493f644ec5c4bf93b1f096992c9976790303ad618`.

The separate Windows-host `m3j_verify_boundary.py` verifier read that output, checked schema, Linux refusal error codes, non-root UID/GID, capability flags, root/code read-only status and no producer/broker/model invocation. It returned **`synthetic_boundary_smoke_verified=true`** and `check_errors=[]`, `fresh_pit_inputs_ready=false`, `model_release_blocked=true`.

**Cross-platform correction during the test:** initial Windows verifier had mistakenly used *Windows* Python `errno.ENETUNREACH=10051` when reading the *Linux* container code `101`, causing a false negative. This was corrected to explicit **Linux** denial numbers in the verifier, plus a regression test that rejects a Windows 10051 code from the Linux probe. The independent real-record recheck then passed. The original Docker output was not overwritten to make it pass.

## 3. Scripts and tests

Scratch-only files added:
- `m3j_sandbox_probe.py`: synthetic harmless in-container file/network boundary attempts and one JSON output; refuses success if any prohibited operation succeeds.
- `m3j_verify_boundary.py`: separate fail-closed Windows-friendly **Linux errno** result checker, never authorizes a scorer run.
- `m3j_test_verify_boundary.py`: deterministic mocked validation tests for root user, enabled capabilities, bad schema, rogue mount, network escape, writable root/code, and producer/model use.

**M3J verifier unit tests: 11/11 PASS**. Whole isolated milestone-3 scratch test suite **174/174 PASS** under Windows Python 3.12. The actual Docker container was separately run once and its generated output independently verified. The regular unit tests did not launch Docker or the production scorer.

## 4. What this DOES NOT prove

- This **one benign synthetic probe** verifies that the *specific tested container options* enforced several OS boundaries on that test. It is **not a hostile-container penetration test or exhaustive proof** against every container escape, bind-mount resolution, privilege escalation, Docker daemon access, outbound DNS route or dynamic Python import. The Windows Docker daemon itself can run privileged containers; the current Windows bridge has broader machine privileges.
- We have **not copied or mounted the 8 production scorer modules and inputs into a runtime test**, have not executed or dry-run the real scorer, and have not validated all `peer_paths`, `depth_overlay`, `MRI_OUTPUTS_DIR`, previous `factor_scores.json`, `.env` and broker-related imports under confinement. Their earlier static analysis still requires review.
- The local production scorer inputs identified by 3H were ~185–210 hours old. Merely repackaging those inputs into Docker would not establish their as-of publication, freshness, up-to-date prices, SEC/issuer identity or any true event. No *current* PIT source run was prepared.
- No positive/negative independently adjudicated corporate event opportunity set exists. The external design cross-check is outstanding, as are Qwen performance and incremental portfolio-risk tests.
- A1's locked 1.60x annual turnover gate remains **failed**. The untouched revision-26 valuation holdout remains untouched.

## 5. Next specific safe work item

Create a **non-running, scratch-only Docker execution specification** that rejects mounts outside a designated scratch root, verifies immutable source hashes, pins exactly the 8 local script dependencies plus original previous-book and MRI/overlay inputs, rejects symbolic/reparse links and external peer-path resolution, and insists on a fresh source-origin/PIT manifest. Demonstrate failure on stale inputs and mutation of original code. Only after these tests and a complete source freshness gate pass would it make sense to evaluate an isolated production scorer run **without** Qwen or trading authority.

Do not start/stop Docker services or unrelated existing containers, configure system-wide firewall/ACL rules, touch publisher writes, invoke `run_chain` or lift `KIS_HALT`/`DEPTH_PAUSED`. Docker smoke success is not user/operator or external-review approval of paper-vs-live investment operations.

**Milestone 3J OS-boundary probe PASS; Milestone 3 end-to-end Qwen risk benefit still OPEN and UNMEASURED.**

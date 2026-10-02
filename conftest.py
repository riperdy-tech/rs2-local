"""conftest.py — suite-level guard against writing into production cache/.

B2 (Phase 1 approval review, fix list): the canonical test invocation is
`pytest tests tools/audit_202608/tests`, and this file sits at their common ancestor so it loads
for both. The review measured that tests/test_factor_guard.py's od.main() tests wrote a real
wrong-engine row into cache/depth_membership.jsonl and appended to cache/depth_orchestrate.log —
production state consumed by real capital allocation. Those tests are now isolated (redirect
LOG/STATE, stub the network- and file-scanning calls), but this fixture is the backstop for every
test, present and future: any test that leaves so much as one file under cache/ with a changed
mtime, or added/removed, fails loudly instead of corrupting production state silently.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
# Revision 18: the closure's raw consensus batch (cache/closure_enrich/<vintage>/, ~1,700 files) is raw data, not state a test may
# touch, and statting it twice per test made the suite many times slower. The per-test guard skips that subtree; the session
# guard below checks every vintage against its manifest.json (file list and sha256) at the start and the end of the session, and
# compares a listing of the WHOLE subtree (subfolders such as a failed attempt moved aside, and any file at the batch folder's root).
BATCH_ROOT = "closure_enrich"


def _snapshot():
    if not CACHE.exists():
        return {}
    out = {}
    for dirpath, dirnames, filenames in os.walk(CACHE):
        if Path(dirpath) == CACHE and BATCH_ROOT in dirnames:
            dirnames.remove(BATCH_ROOT)          # never descended into: listing ~1,700 files twice per test is what made the suite slow
        for name in filenames:
            p = Path(dirpath) / name
            out[str(p.relative_to(CACHE))] = p.stat().st_mtime_ns
    return out


def closure_enrich_tree(cache_dir):
    """{relative path: (kind, size, mtime_ns)} of EVERYTHING under cache_dir/closure_enrich - every file and every folder at any depth: a
    vintage's records and manifest, a failed attempt moved aside (`_attempt*_broken_session/`), and any file or folder at the root of the
    batch folder. The per-test guard never descends into it; the session guard compares this listing at the start and the end."""
    root = Path(cache_dir) / BATCH_ROOT
    out = {}
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            p = Path(dirpath) / name
            out[p.relative_to(root).as_posix() + "/"] = ("dir", 0, 0)
        for name in filenames:
            p = Path(dirpath) / name
            st = p.stat()
            out[p.relative_to(root).as_posix()] = ("file", st.st_size, st.st_mtime_ns)
    return out


def compare_closure_enrich_tree(before, after):
    """Problems (a list of strings, empty when the two listings are equal): the entries added, removed or changed anywhere under
    cache/closure_enrich between `before` and `after` (names are paths inside the batch folder; they hold no ticker list of ours)."""
    problems = []
    for rel in sorted(set(after) - set(before)):
        problems.append(f"{rel} was added")
    for rel in sorted(set(before) - set(after)):
        problems.append(f"{rel} was removed")
    for rel in sorted(set(before) & set(after)):
        if before[rel] != after[rel]:
            problems.append(f"{rel} was changed")
    return problems


def verify_batch_vintages(cache_dir):
    """Problems (a list of strings, empty when clean) found by checking every cache_dir/closure_enrich/<vintage>/ against its
    manifest.json: a folder holding records but no manifest, a file the manifest does not list, a listed file that is missing,
    a file whose sha256 differs, and a manifest whose own hash (over the sorted per-file hashes) differs. Subfolders (for example
    a failed attempt moved aside) are not part of the vintage."""
    root = Path(cache_dir) / BATCH_ROOT
    problems = []
    if not root.is_dir():
        return problems
    for vdir in sorted(p for p in root.iterdir() if p.is_dir()):
        on_disk = {p.name for p in vdir.glob("*.json") if p.name != "manifest.json"}
        man_path = vdir / "manifest.json"
        if not man_path.exists():
            if on_disk:
                problems.append(f"{vdir.name}: records but no manifest.json")
            continue
        try:
            man = json.loads(man_path.read_text(encoding="utf-8"))
            listed = man["file_sha256"]
        except (ValueError, KeyError):
            problems.append(f"{vdir.name}: manifest.json is unreadable")
            continue
        for name in sorted(on_disk - set(listed)):
            problems.append(f"{vdir.name}: {name} is not in the manifest")
        for name in sorted(set(listed) - on_disk):
            problems.append(f"{vdir.name}: {name} is in the manifest but missing")
        for name in sorted(on_disk & set(listed)):
            if hashlib.sha256((vdir / name).read_bytes()).hexdigest() != listed[name]:
                problems.append(f"{vdir.name}: {name} differs from its manifest sha256")
        own = hashlib.sha256("".join(f"{k}:{v}" + chr(10) for k, v in sorted(listed.items())).encode()).hexdigest()
        if own != man.get("manifest_sha256"):
            problems.append(f"{vdir.name}: the manifest's own hash does not match its file hashes")
    return problems


@pytest.fixture(autouse=True, scope="session")
def _batch_vintages_must_match_their_manifests():
    start = verify_batch_vintages(CACHE)
    if start:
        pytest.fail("cache/closure_enrich does not match its manifest at session start: " + "; ".join(start[:6]), pytrace=False)
    tree_before = closure_enrich_tree(CACHE)
    yield
    end = verify_batch_vintages(CACHE)
    if end:
        pytest.fail("a test altered cache/closure_enrich (it no longer matches its manifest): " + "; ".join(end[:6]), pytrace=False)
    # the manifest check covers only the vintages' *.json records; the whole subtree is guarded here (a subfolder such as a failed
    # attempt moved aside, and any file at the root of the batch folder)
    tree_changed = compare_closure_enrich_tree(tree_before, closure_enrich_tree(CACHE))
    if tree_changed:
        pytest.fail("a test altered cache/closure_enrich: " + "; ".join(tree_changed[:6]), pytrace=False)


@pytest.fixture(autouse=True)
def _cache_must_stay_untouched():
    before = _snapshot()
    yield
    after = _snapshot()
    if after != before:
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(p for p in (set(after) & set(before)) if after[p] != before[p])
        pytest.fail(
            "test wrote into production cache/ — added=" + repr(added) +
            " removed=" + repr(removed) + " mtime-changed=" + repr(changed) +
            ". Redirect the module's LOG/STATE/etc. to tmp_path instead of letting it touch "
            "the real cache/ directory.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _risk_bucket_is_deterministic_in_tests(monkeypatch):
    """P4.9/C1 — depth_pipeline.band_verdict() calls risk_bucket(), which reads the MRI shock
    register LIVE off disk (CONFIG["mri_outputs_dir"]/shock_register.json) to see whether
    elevated_volatility_ahead is active right now. A test must never depend on that: today's
    real reading changes with market conditions, so an un-mocked band_verdict() test would pass
    or fail depending on the state of the world outside the test, not on the code under test.

    Every test defaults to the neutral, non-restricting reading ('full', None) — exactly as if
    the risk component were absent from the P4.9 min(). A test that wants to exercise the risk
    component itself (an active flag capping to 'half', or an unreadable register producing
    None + risk_flag_unavailable) re-applies its own `monkeypatch.setattr(dp, "risk_bucket", ...)`
    in its own body, which simply overrides this default for that one test.
    """
    import depth_pipeline as dp
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("full", None))


@pytest.fixture(autouse=True)
def _isolate_sec_guidance_in_tests(monkeypatch, tmp_path):
    """P4 D4b: Isolate sec_guidance caches from production cache/ and disable unmocked network calls in tests."""
    import urllib.error
    import sec_guidance
    import depth_triggers
    monkeypatch.setattr(sec_guidance, "SEC_8K_CACHE", tmp_path / "sec_8k")
    monkeypatch.setattr(sec_guidance, "SUB_CACHE", tmp_path / "sec_submissions")
    monkeypatch.setattr(depth_triggers, "SUB_CACHE", tmp_path / "sec_submissions")

    def _no_network_urlopen(*args, **kwargs):
        raise urllib.error.URLError("Network disabled in tests")

    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", _no_network_urlopen)


@pytest.fixture(autouse=True)
def _world_news_is_unreachable_by_default(tmp_path, monkeypatch):
    """P4 D10 — every `capability_test.build_pack()` call now asks `world_news.digest()` for
    SECTION 1.6's WORLD NEWS block, which resolves the real macro-regime-indicator repo and, in
    live mode, does a real `git fetch`/`git show` against it plus a write to
    cache/world_news_digest.json. A test must never depend on any of that: today's real feed
    changes, an offline sandbox has no network, and an un-mocked write would trip
    `_cache_must_stay_untouched` above exactly like the depth-membership row B2 already found.

    Every test defaults to no resolvable MRI repo, which makes digest() return None — the pack's
    own honest "not available" line — with no network call and no file I/O outside tmp_path. A
    test that wants to exercise the real WORLD NEWS block re-applies its own
    `monkeypatch.setattr(world_news, ...)` in its own body (see
    tools/audit_202608/tests/test_world_news.py), which simply overrides this default for that one
    test.
    """
    import world_news
    monkeypatch.setattr(world_news, "_mri_repo", lambda: None)
    monkeypatch.setattr(world_news, "CACHE_PATH", tmp_path / "world_news_digest.json")


@pytest.fixture(autouse=True)
def _company_news_reads_no_articles_in_tests(monkeypatch):
    """E11: company_news reads the top stories over the network; tests never do."""
    import company_news
    monkeypatch.setattr(company_news, "_read_article", lambda url, title, name_token: (None, None))


@pytest.fixture(autouse=True)
def _company_news_returns_empty_by_default(monkeypatch):
    """P4 Item 2 — tests default to company_news.fetch returning an empty result
    with no network and no cache write unless a test overrides it."""
    import company_news
    monkeypatch.setattr(company_news, "fetch", lambda company, ticker: {
        "ticker": str(ticker).upper(),
        "company": company,
        "date": "2026-09-24",
        "rows": [],
        "unresponsive_engines": [],
        "errors": [],
    })


@pytest.fixture(autouse=True)
def _catalyst_research_returns_no_brief_by_default(monkeypatch):
    """P4 Item 4 — an autouse fixture (next to the existing ones) makes catalyst_research.run
    return a fixed 'no brief' result with no model call and no cache write unless a test overrides it."""
    import catalyst_research
    monkeypatch.setattr(catalyst_research, "run", lambda ticker, force=False: {
        "ticker": str(ticker).upper(),
        "asof": "2026-09-24",
        "model": "rs2-analyst-deep-mtp5",
        "narrative": None,
        "bear_narrative": None,
        "events": [],
        "open_questions": [],
        "flags": ["too_few_events"],
        "pages_read": 0,
        "search_calls": 0,
        "elapsed_s": 0.0,
        "error": "no brief",
    })



@pytest.fixture(autouse=True)
def _no_model_json_fix_in_tests(monkeypatch):
    """catalyst_research._llm_fix_json calls the real model. No test may reach it by accident; a
    test that needs it replaces this stub."""
    import catalyst_research

    def _refuse(*a, **k):
        raise RuntimeError("no model calls in tests")
    monkeypatch.setattr(catalyst_research, "_llm_fix_json", _refuse)


@pytest.fixture(autouse=True)
def _bill_rate_is_deterministic_in_tests(monkeypatch):
    """Revision 18 (brief 1.3) - capability_test.build_pack prices the interest on a company's cash with
    rs2_data.bill_rate_mean, which reads MRI's raw FRED store off disk. A test must never depend on that store: today's
    file changes with every refresh and exists only on this machine. Every test defaults to "no bill rate available" (the
    stamped, no-cash-term reading); a test that wants the cash term passes its own rate by re-applying
    `monkeypatch.setattr(rs2_data, "bill_rate_mean", ...)` in its own body."""
    import rs2_data
    monkeypatch.setattr(rs2_data, "bill_rate_mean", lambda start, end: (None, "stubbed in tests: no MRI store"))


@pytest.fixture(autouse=True)
def _reference_closure_is_deterministic_in_tests(monkeypatch):
    """Revision 18 (brief 1.6) - the pack's cost of equity is rf_eff + loading x the closure premium, read from
    rs2_data.reference_closure() (cache/reference_closure.json), which exists only after tools/reference_closure.py --build. A
    test must not depend on that artifact or its date. Every test defaults to a closure premium equal to the MRI anchor's own
    mature premium (what the pack used before revision 18), dated inside the staleness window; a test of the accessor or the
    closure's own consequences re-applies its own `monkeypatch.setattr(rs2_data, "reference_closure", ...)`."""
    import rs2_data

    def _stub(path=None):
        erp, _src = rs2_data.anchor_mature_erp()
        if erp is None:
            return None, None, "stubbed in tests: no MRI premium to stand in"
        return erp, "2026-09-20", {"stub": "tests"}
    monkeypatch.setattr(rs2_data, "reference_closure", _stub)

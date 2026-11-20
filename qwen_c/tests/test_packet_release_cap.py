"""NC10b: the release cap is an optional parameter. Default 14,000 (Qwen's packets, byte-identical); the cloud workers pass 60,000."""
import sec_primary
from qwen_c import packet
from qwen_c.tests.test_packet import AREL, base, documents, eightk_txt, make_store, paras, world  # noqa: F401  (world is a fixture)

LONG = "<html><body><p>Test Co Reports Results</p><p>RELEASE_START revenue was $1,234.5 million.</p>" + paras("rel", 30000) + "</body></html>"


def long_store(tmp_path, world):
    docs = documents()
    docs[f"{base(AREL)}/{AREL}.txt"] = eightk_txt(AREL, [("8-K", "f8k.htm", "<p>Item 2.02 Results.</p>"), ("EX-99.1", "ex991.htm", LONG)])
    return make_store(tmp_path / "long_store", docs)


def build(world, store, **kw):
    return packet.build("TEST", "2026-10-28T20:00:00Z", world["commit"], online=False, verified_record=world["record"],
                        screener_repo_path=world["repo"], store_root=store, **kw)


def release(pk):
    [e] = [e for e in pk["evidence"] if e["kind"] == "release"]
    return e["text"]


def test_default_packet_is_byte_identical_whether_the_cap_is_left_out_or_is_todays_value(tmp_path, world):
    store = long_store(tmp_path, world)
    default, explicit_none = build(world, store), build(world, store, release_cap=None)
    assert packet.RELEASE_CAP == 14_000 and packet.canonical_bytes(default) == packet.canonical_bytes(explicit_none)
    assert len(release(default)) <= 14_000 and sec_primary.OMIT_RE.search(release(default))        # the fixture release really is cut at the default
    assert not any(a.startswith("release_truncated") for a in default["annotations"])              # no new annotation on the default path
    same = build(world, store, release_cap=14_000)
    assert [e["text"] for e in same["evidence"]] == [e["text"] for e in default["evidence"]]       # the same text at the same cap
    assert [e["fact_id"] for e in same["evidence"]] == [e["fact_id"] for e in default["evidence"]]


def test_a_larger_cap_keeps_the_whole_release_and_a_cut_at_a_chosen_cap_is_annotated(tmp_path, world):
    store = long_store(tmp_path, world)
    big = build(world, store, release_cap=60_000)
    assert len(release(big)) > 14_000 and not sec_primary.OMIT_RE.search(release(big))
    assert not any(a.startswith("release_truncated") for a in big["annotations"])                  # fits: nothing to flag
    cut = build(world, store, release_cap=20_000)
    assert sec_primary.OMIT_RE.search(release(cut)) and f"release_truncated: {AREL} cut at 20000 characters" in cut["annotations"]
    assert [e["kind"] for e in big["evidence"]] == [e["kind"] for e in cut["evidence"]]            # only the release's text differs


def test_the_command_line_passes_the_cap_through(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(packet, "build", lambda *a, **k: seen.update(k) or {"evidence": [], "annotations": [], "excluded": [], "ticker": "X",
                                                                           "decision_time_utc": "2026-10-28T20:00:00Z"})
    monkeypatch.setattr(packet, "save", lambda pk: tmp_path / "x.json")
    monkeypatch.setattr(packet, "packet_sha256", lambda pk: "0")
    packet.main(["--ticker", "X", "--T", "2026-10-28T20:00:00Z", "--commit", "c", "--verified-record", "r"])
    assert seen["release_cap"] is None
    packet.main(["--ticker", "X", "--T", "2026-10-28T20:00:00Z", "--commit", "c", "--verified-record", "r", "--release-cap", "60000"])
    assert seen["release_cap"] == 60_000

"""replay: the M-P4 pack replay gate (SPEC §7). Offline, over test_packet's synthetic store and throwaway screener repository."""
import hashlib
import json

import pytest

from qwen_c import packet, replay, sec_store
from qwen_c.tests.test_packet import A801, SUBS_URL, base, build, documents, tenk_html, world  # noqa: F401 (world: fixture)


@pytest.fixture
def saved(world):
    pk = build(world)
    path = packet.save(pk, world["tmp"] / "packets")
    return world, pk, path


def rp(w, path):
    return replay.replay(path, store_root=w["store"], screener_repo_path=w["repo"])


def test_replay_of_a_stored_packet_is_byte_identical(saved):
    w, pk, path = saved
    res = rp(w, path)
    assert res == {"identical": True, "first_diff": None, "stored_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "rebuilt_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_replay_reads_only_the_pinned_bytes_after_the_store_moves_on(saved):
    w, pk, path = saved
    subs = json.loads(documents()[SUBS_URL])
    subs["filings"]["recent"]["form"][0] = "10-K"                   # a later fetch of the submissions JSON says something else
    sec_store._store(w["store"], SUBS_URL, json.dumps(subs).encode(), 200, "test")
    assert packet.canonical_bytes(build(w)) != path.read_bytes()    # an unpinned offline build now differs ...
    assert rp(w, path)["identical"] is True                          # ... the replay, pinned, does not


def test_tampered_stored_bytes_raise_store_corrupt(saved):
    w, pk, path = saved
    (w["store"] / hashlib.sha256(tenk_html()).hexdigest()).write_bytes(b"tampered")
    with pytest.raises(sec_store.StoreCorrupt):
        rp(w, path)


def test_a_missing_raw_input_raises_not_in_store(saved):
    w, pk, path = saved
    url = f"{base(A801)}/{A801}.txt"
    sha = next(r["sha256"] for r in pk["raw_inputs"] if r["url"] == url)
    (w["store"] / sha).unlink()
    with pytest.raises(sec_store.NotInStore):
        rp(w, path)


def test_an_input_the_packet_did_not_pin_raises_not_in_store(saved):
    w, pk, path = saved
    pk["raw_inputs"] = [r for r in pk["raw_inputs"] if not r["url"].endswith(f"{A801}.txt")]
    p2 = w["tmp"] / "unpinned" / path.name
    p2.parent.mkdir()
    p2.write_bytes(packet.canonical_bytes(pk))
    with pytest.raises(sec_store.NotInStore):
        rp(w, p2)


def test_an_edited_packet_is_not_identical_and_names_the_first_difference(saved):
    w, pk, path = saved
    pk["evidence"][5]["text"] = pk["evidence"][5]["text"].replace("Item 1A", "Item 1A (edited)", 1)
    path.write_bytes(packet.canonical_bytes(pk))
    res = rp(w, path)
    assert res["identical"] is False and res["first_diff"]["path"] == "$.evidence[5].text"


def test_a_non_canonical_stored_file_is_not_identical(saved):
    w, pk, path = saved
    path.write_bytes(json.dumps(pk, sort_keys=True, ensure_ascii=False, indent=1).encode("utf-8"))
    res = rp(w, path)
    assert res["identical"] is False and res["first_diff"]["path"] is None and "canonical" in res["first_diff"]["reason"]


def test_a_packet_for_an_excluded_ticker_is_refused_on_replay(saved):
    w, pk, path = saved
    pk["ticker"] = "MOV"
    path.write_bytes(packet.canonical_bytes(pk))
    with pytest.raises(packet.PacketRefused) as e:
        rp(w, path)
    assert e.value.code == "ticker_excluded"


def test_cli_replays_every_packet_and_fails_on_any_difference(saved, monkeypatch, capsys):
    w, pk, path = saved
    monkeypatch.setattr(sec_store, "RAW_DIR", w["store"])
    monkeypatch.setattr(packet, "screener_repo", lambda: w["repo"])
    d = str(path.parent)
    assert replay.main(["--dir", d]) == 0
    line = json.loads(capsys.readouterr().out.strip())
    assert line["packet"] == path.name and line["identical"] is True
    other = dict(pk, annotations=pk["annotations"] + ["forged"])
    (path.parent / "TEST_20261028T200001Z.json").write_bytes(packet.canonical_bytes(other))
    assert replay.main(["--dir", d]) == 1
    out = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert [o["identical"] for o in out] == [True, False]
    assert replay.main(["--dir", str(w["tmp"] / "empty")]) == 1


def test_replay_reruns_the_run_time_check_on_the_pinned_verified_row(saved):
    # CROSS_CHECK_M 2.1 / 5.1: the row is pinned in the header, and replay checks it against T again
    w, pk, path = saved
    pk["screener"]["verified_row"]["run_updated_at"] = "2026-10-28T20:00:01Z"
    path.write_bytes(packet.canonical_bytes(pk))
    with pytest.raises(packet.PacketRefused) as e:
        rp(w, path)
    assert e.value.code == "verified_run_after_T"


def test_a_packet_without_a_pinned_verified_row_is_refused_on_replay(saved):
    w, pk, path = saved
    pk["screener"]["verified_run_id"] = pk["screener"].pop("verified_row")["run_id"]     # the m3m.packet.builder.v1 header
    path.write_bytes(packet.canonical_bytes(pk))
    with pytest.raises(packet.PacketRefused) as e:
        rp(w, path)
    assert e.value.code == "verified_run_time_missing"


def test_a_changed_builder_source_is_not_identical_on_replay(saved, tmp_path, monkeypatch):
    # CROSS_CHECK_M 5.3: the builder's code is part of what replay reproduces
    w, pk, path = saved
    other = tmp_path / "packet_edited.py"
    other.write_bytes(packet.BUILDER_FILES[0][1].read_bytes() + b"# edited\n")
    monkeypatch.setattr(packet, "BUILDER_FILES", (("packet.py", other),) + packet.BUILDER_FILES[1:])
    res = rp(w, path)
    assert res["identical"] is False and res["first_diff"]["path"] == "$.builder_code.packet.py"

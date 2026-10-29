"""sec_store: the raw SEC store (SPEC §2). Offline: urlopen is stubbed; nothing touches the network or the repository's cache/."""
import hashlib
import io
import json
import urllib.error

import pytest

from qwen_c import sec_store
from sec_guidance import UA

ARCH = "https://www.sec.gov/Archives/edgar/data/123/000000012326000001/doc.htm"
SUBS = "https://data.sec.gov/submissions/CIK0000000123.json"


class _Resp(io.BytesIO):
    def __init__(self, data, url, status=200):
        super().__init__(data)
        self._url, self.status = url, status

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def net(monkeypatch):
    """A stub SEC: url -> bytes, or an int HTTP status to fail with. Records every request and its headers."""
    served, calls = {}, []

    def urlopen(req, timeout=None):
        calls.append((req.full_url, dict(req.header_items())))
        v = served[req.full_url]
        if isinstance(v, int):
            raise urllib.error.HTTPError(req.full_url, v, "stub", {}, None)
        if isinstance(v, tuple):
            return _Resp(v[0], v[1])
        return _Resp(v, req.full_url)
    monkeypatch.setattr(sec_store.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sec_store.time, "sleep", lambda s: None)
    return served, calls


def test_offline_miss_raises_not_in_store(tmp_path):
    with pytest.raises(sec_store.NotInStore):
        sec_store.get(ARCH, online=False, root=tmp_path)


def test_online_fetch_stores_bytes_and_a_full_receipt(tmp_path, net):
    served, calls = net
    served[ARCH] = b"<html>filing</html>"
    assert sec_store.get(ARCH, online=True, root=tmp_path) == b"<html>filing</html>"
    sha = hashlib.sha256(b"<html>filing</html>").hexdigest()
    assert (tmp_path / sha).read_bytes() == b"<html>filing</html>"
    (rec,) = [json.loads(l) for l in (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rec["url"] == ARCH and rec["sha256"] == sha and rec["bytes"] == 19 and rec["status"] == 200
    assert rec["user_agent"] == UA["User-Agent"] and rec["fetched_at"].endswith("Z")
    assert calls[0][1].get("User-agent") == UA["User-Agent"]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]


def test_archive_hit_is_served_from_the_store_without_a_request(tmp_path, net):
    served, calls = net
    served[ARCH] = b"v1"
    sec_store.get(ARCH, online=True, root=tmp_path)
    served[ARCH] = b"v2"
    assert sec_store.get(ARCH, online=True, root=tmp_path) == b"v1"
    assert sec_store.get(ARCH, online=False, root=tmp_path) == b"v1"
    assert len(calls) == 1


def test_submissions_are_fetched_again_on_every_online_get_each_a_new_receipt(tmp_path, net):
    served, calls = net
    served[SUBS] = b'{"day": 1}'
    sec_store.get(SUBS, online=True, root=tmp_path)
    served[SUBS] = b'{"day": 2}'
    assert sec_store.get(SUBS, online=True, root=tmp_path) == b'{"day": 2}'
    assert len(calls) == 2
    recs = [json.loads(l) for l in (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["sha256"] for r in recs] == [hashlib.sha256(b'{"day": 1}').hexdigest(), hashlib.sha256(b'{"day": 2}').hexdigest()]
    assert sec_store.get(SUBS, online=False, root=tmp_path) == b'{"day": 2}'          # offline: the latest receipt
    assert sec_store.get_pinned(SUBS, recs[0]["sha256"], root=tmp_path) == b'{"day": 1}'   # a pinned older copy stays readable


def test_non_200_raises_fetch_failed_and_stores_nothing(tmp_path, net):
    served, _ = net
    served[ARCH] = 404
    with pytest.raises(sec_store.FetchFailed) as e:
        sec_store.get(ARCH, online=True, root=tmp_path)
    assert e.value.status == 404
    assert not (tmp_path / "receipts.jsonl").exists()


def test_only_https_sec_hosts_are_allowed(tmp_path, net):
    for bad in ("https://example.com/x", "http://www.sec.gov/Archives/x", "https://sec.gov.evil.com/x", "https://data.sec.gov.example/x"):
        with pytest.raises(ValueError):
            sec_store.get(bad, online=True, root=tmp_path)
    assert net[1] == []


def test_a_redirect_off_sec_is_refused(tmp_path, net):
    served, _ = net
    served[ARCH] = (b"x", "https://example.com/elsewhere")
    with pytest.raises(ValueError):
        sec_store.get(ARCH, online=True, root=tmp_path)
    assert not (tmp_path / "receipts.jsonl").exists()


def test_throttle_spaces_requests_at_least_0_15_s(tmp_path, monkeypatch):
    sleeps, clock = [], [100.0]
    monkeypatch.setattr(sec_store.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sec_store.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(sec_store.urllib.request, "urlopen", lambda req, timeout=None: _Resp(b"x" + req.full_url.encode(), req.full_url))
    monkeypatch.setattr(sec_store, "_last_request", [100.0])
    sec_store.get(ARCH, online=True, root=tmp_path)
    assert sec_store.THROTTLE_S >= 0.15 and sleeps and sleeps[0] == pytest.approx(sec_store.THROTTLE_S)


def test_tampered_bytes_raise_store_corrupt(tmp_path, net):
    served, _ = net
    served[ARCH] = b"original"
    sec_store.get(ARCH, online=True, root=tmp_path)
    sha = hashlib.sha256(b"original").hexdigest()
    (tmp_path / sha).write_bytes(b"tampered")
    with pytest.raises(sec_store.StoreCorrupt):
        sec_store.get(ARCH, online=False, root=tmp_path)
    with pytest.raises(sec_store.StoreCorrupt):
        sec_store.get_pinned(ARCH, sha, root=tmp_path)


def test_a_torn_receipt_line_is_store_corrupt(tmp_path, net):
    served, _ = net
    served[ARCH] = b"a"
    sec_store.get(ARCH, online=True, root=tmp_path)
    with open(tmp_path / "receipts.jsonl", "ab") as fh:
        fh.write(b'{"url": "https://www.sec.gov/x", "sha2')
    with pytest.raises(sec_store.StoreCorrupt):
        sec_store.get(ARCH, online=False, root=tmp_path)


def test_get_pinned_needs_the_url_bound_to_that_sha(tmp_path, net):
    served, _ = net
    served[ARCH] = b"a"
    sec_store.get(ARCH, online=True, root=tmp_path)
    sha = hashlib.sha256(b"a").hexdigest()
    assert sec_store.get_pinned(ARCH, sha, root=tmp_path) == b"a"
    with pytest.raises(sec_store.NotInStore):
        sec_store.get_pinned(ARCH, "0" * 64, root=tmp_path)
    with pytest.raises(sec_store.NotInStore):
        sec_store.get_pinned(ARCH.replace("doc.htm", "other.htm"), sha, root=tmp_path)
    (tmp_path / sha).unlink()
    with pytest.raises(sec_store.NotInStore):
        sec_store.get_pinned(ARCH, sha, root=tmp_path)


def test_an_existing_sha_is_never_rewritten(tmp_path, net):
    served, _ = net
    other = ARCH.replace("doc.htm", "copy.htm")
    served[ARCH] = served[other] = b"same bytes"
    sec_store.get(ARCH, online=True, root=tmp_path)
    sha = hashlib.sha256(b"same bytes").hexdigest()
    before = (tmp_path / sha).stat().st_mtime_ns
    sec_store.get(other, online=True, root=tmp_path)
    assert (tmp_path / sha).stat().st_mtime_ns == before
    assert len((tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    (tmp_path / sha).write_bytes(b"corrupted")
    served[SUBS] = b"same bytes"                         # a new fetch of the same bytes meets a corrupt copy: an error, never a repair
    with pytest.raises(sec_store.StoreCorrupt):
        sec_store.get(SUBS, online=True, root=tmp_path)

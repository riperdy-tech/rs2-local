"""Backtest registration section 4.1 / 14 step 4: the point-in-time cut of companyfacts.zip.

For each valuation date T, copy the SEC companyfacts archive keeping only the facts with `filed <= T`
(ISO dates compare as strings; a fact with no `filed` cannot be shown to have existed on T and is dropped and
counted).  One cut zip per T, plus a small side file per T with what the harness needs and the extractor does not
emit: whether the company had filed a 10-K by T, the latest cover-page share count (dei
EntityCommonStockSharesOutstanding, every entry of the latest filing date), and the annual share-count facts
(with their filing dates) of the last two years.

OFFLINE: the socket module is blocked before anything else runs.  No return, no price, no model.

  python cut_zips.py --zip companyfacts.zip --out-dir <dir> [--dates 2016-06-30 ...] [--workers 15]
"""
import argparse
import json
import socket
import struct
import time
import zlib
import zipfile
from datetime import date, timedelta
from multiprocessing import Pool
from pathlib import Path


class _Blocked(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("Socket access blocked in this step")


def _no_net(*a, **k):
    raise RuntimeError("Network access blocked in this step")


socket.socket = _Blocked
socket.getaddrinfo = _no_net
socket.create_connection = _no_net

DATES = ["2016-06-30", "2017-06-30", "2018-06-29", "2019-06-28", "2020-06-30", "2021-06-30", "2022-06-30", "2023-06-30"]
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F")
SHARE_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic",
              "WeightedAverageShares", "AdjustedWeightedAverageShares")
_DOS_TIME, _DOS_DATE = 0, ((2026 - 1980) << 9) | (10 << 5) | 1   # a fixed stamp: the cut is reproducible byte for byte


def _dur_days(v):
    s, e = v.get("start"), v.get("end")
    if not s or not e:
        return None
    try:
        return (date.fromisoformat(e) - date.fromisoformat(s)).days
    except ValueError:
        return None


def cut_member(obj, T):
    """(filtered object, side dict or None, (kept, dropped, dropped_no_filed)) for one company's object and cut date T."""
    keep = dropped = no_filed = 0
    out_facts = {}
    k10 = False
    cover_all = []
    dil = []
    t_date = date.fromisoformat(T)
    horizon = (t_date - timedelta(days=730)).isoformat()
    for tax, body in (obj.get("facts") or {}).items():
        out_body = {}
        for concept, cb in (body or {}).items():
            units_out = {}
            for unit, vals in ((cb or {}).get("units") or {}).items():
                kept = []
                for v in vals:
                    f = v.get("filed")
                    if not f:
                        no_filed += 1
                        dropped += 1
                        continue
                    if f > T:
                        dropped += 1
                        continue
                    kept.append(v)
                    keep += 1
                    form = v.get("form")
                    if form in ("10-K", "10-K/A"):
                        k10 = True
                    if tax == "dei" and concept == "EntityCommonStockSharesOutstanding":
                        cover_all.append(v)
                    elif concept in SHARE_TAGS and unit == "shares" and form in ANNUAL_FORMS and (v.get("end") or "") >= horizon:
                        d = _dur_days(v)
                        if d is not None and 350 <= d <= 380:
                            dil.append([concept, v.get("start"), v.get("end"), v.get("val"), f, form])
                if kept:
                    units_out[unit] = kept
            if units_out:
                out_body[concept] = dict(cb, units=units_out)
        out_facts[tax] = out_body
    cover = []
    if cover_all:
        last = max(v["filed"] for v in cover_all)
        cover = [[v.get("end"), v.get("val"), v.get("accn"), v.get("form"), v["filed"]] for v in cover_all if v["filed"] == last]
    filtered = {k: v for k, v in obj.items() if k != "facts"}
    filtered["facts"] = out_facts
    side = {"k10": k10, "cover": cover, "dil": dil} if (k10 or cover or dil) else None
    return filtered, side, (keep, dropped, no_filed)


def work(args):
    zip_path, names, dates = args
    z = zipfile.ZipFile(zip_path)
    res = []
    for n in names:
        raw = z.read(n)
        obj = json.loads(raw)
        per = {}
        for T in dates:
            filt, side, counts = cut_member(obj, T)
            data = json.dumps(filt, separators=(",", ":")).encode("utf-8")
            co = zlib.compressobj(6, zlib.DEFLATED, -15)
            comp = co.compress(data) + co.flush()
            per[T] = (comp, zlib.crc32(data) & 0xFFFFFFFF, len(data), side, counts)
        res.append((n, str(obj.get("cik", "")).zfill(10), per))
    return res


class RawZipWriter:
    """Minimal deflate zip writer taking pre-compressed members (names ASCII; fewer than 65535 entries; under 4 GB)."""

    def __init__(self, path):
        self.f = open(path, "wb")
        self.entries = []

    def add(self, name, comp, crc, usize):
        nb = name.encode("ascii")
        off = self.f.tell()
        self.f.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, _DOS_TIME, _DOS_DATE, crc, len(comp), usize, len(nb), 0))
        self.f.write(nb)
        self.f.write(comp)
        self.entries.append((nb, crc, len(comp), usize, off))

    def close(self):
        start = self.f.tell()
        for nb, crc, cs, us, off in self.entries:
            self.f.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 8, _DOS_TIME, _DOS_DATE, crc, cs, us,
                                     len(nb), 0, 0, 0, 0, 0, off))
            self.f.write(nb)
        size = self.f.tell() - start
        n = len(self.entries)
        assert n < 65535 and self.f.tell() < 2 ** 32
        self.f.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, n, n, size, start, 0))
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="*", default=DATES)
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--limit", type=int, default=None, help="smoke run: only the first N members")
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    names = [i.filename for i in zipfile.ZipFile(a.zip).infolist() if i.filename.endswith(".json")]
    if a.limit:
        names = names[: a.limit]
    chunks = [(str(a.zip), names[i:i + 40], a.dates) for i in range(0, len(names), 40)]
    writers = {T: RawZipWriter(a.out_dir / f"cut_{T}.zip") for T in a.dates}
    sides = {T: {} for T in a.dates}
    counts = {T: [0, 0, 0, 0] for T in a.dates}     # kept, dropped (filed after T or no filed), dropped for no filed, members
    t0 = time.time()
    done = 0
    with Pool(a.workers) as pool:
        for part in pool.imap(work, chunks):
            for n, cik, per in part:
                for T, (comp, crc, usize, side, cn) in per.items():
                    writers[T].add(n, comp, crc, usize)
                    if side is not None:
                        sides[T][cik] = side
                    c = counts[T]
                    c[0] += cn[0]
                    c[1] += cn[1]
                    c[2] += cn[2]
                    c[3] += 1
                done += 1
            if done % 2000 < 40:
                print(f"{done}/{len(names)} members, {time.time() - t0:.0f}s", flush=True)
    for T, w in writers.items():
        w.close()
        (a.out_dir / f"side_{T}.json").write_text(json.dumps(sides[T], separators=(",", ":")), encoding="utf-8")
    (a.out_dir / "cut_counts.json").write_text(json.dumps(
        {T: {"facts_kept": c[0], "facts_dropped_filed_after_T_or_missing": c[1], "facts_dropped_no_filed_date": c[2], "members": c[3]}
         for T, c in counts.items()}, indent=1), encoding="utf-8")
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

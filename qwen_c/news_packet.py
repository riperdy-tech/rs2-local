"""news_packet.py - press reports as evidence items of a packet (WO_HM2b; SPEC_holdings_monitor_v2.md section 2 point 2).

`build(..., news_file=path)` is `packet.build` plus the rows of a news file, added as evidence items of kind `news`. It lives in its own
module on purpose: packet.BUILDER_FILES pins the sha256 of packet.py into the header of every packet (`builder_code`), so any edit of
packet.py would move the bytes and the sha256 of every packet, news or not. packet.py, sec_primary.py and sec_guidance.py are not touched;
a packet built without a news file is the dict `packet.build` returns, unchanged, and `python -m qwen_c.packet` is unchanged.

THE NEWS FILE. {"ticker", "T", "rows": [{"title", "url", "publisher", "date" or "first_seen", "found_by", "text", "text_sha256"}]}.
`date` is a day (YYYY-MM-DD) or an ISO time with a zone; `first_seen` is an ISO time with a zone; `date` wins when both are present.
A day is read as the END of that day in UTC (the latest the report could have been public), except the day of T itself, which is read
as T: a search engine gives a report's day and not its hour, the monitor hands over only rows it has already gathered, and its gather
runs at 21:00 UTC, so a refusal of T's own day would refuse the reports of the hours after the US close, the ones that matter most
(coordinator's audit, 2026-11-11). A row dated a later day than T is refused. `text_sha256` is the sha256 of the row's text as UTF-8.

THE ITEM. kind `news`; title; form, period and accepted_raw none; effective_at the row's time (UTC, Z); source {"label": "secondary",
"publisher", "url"}; raw_sha256 the row's text_sha256; found_by; text the row's text, as given. ids N1, N2, ... in the file's order, after
every item of the SEC packet. The SEC items are never touched: no cut, no reorder, no id change.

NEWS_CAP is a budget of its own for the text of all news items together, outside packet.TOTAL_CAP. A row that does not fit what is left is
cut at a sentence end (marker included in the budget) and annotated `news_cut`; every later row is left out and annotated
`news_left_out`. A row that cannot be cut to at least packet.MIN_TRIMMED characters at a sentence end is left out too.

REFUSALS (packet.PacketRefused, the whole file): news_file_unreadable, news_file_malformed, news_ticker_mismatch, news_row_no_text,
news_text_sha_mismatch, news_row_date_unreadable, news_row_after_T. Every row is checked, including one that is then left out.

THE PACKET. `news_builder` (NEWS_BUILDER) and `news` {file_sha256, rows_in_file, rows_used, rows_left_out} are new top-level fields; a
packet built without a news file has neither. `builder_version` and `builder_code` are those of packet.build.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import sec_primary

from qwen_c import packet as _packet
from qwen_c.packet import PacketRefused

NEWS_BUILDER = "m3p.news.v1"
NEWS_CAP = 24_000                  # DESIGN (WO_HM2b): characters of news text in all, outside packet.TOTAL_CAP
NEWS_DIR = _packet.PACKETS_DIR / "news"    # a news packet has the file name of the SEC-only packet of the same T, so it goes beside, not in, packets/

_SENTENCE_END = re.compile(r"[.!?][\"')\]”’]*(?=\s|$)")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_news_file(path):
    """(the file's parsed object, the sha256 of its bytes). Raises PacketRefused news_file_unreadable / news_file_malformed."""
    try:
        raw = Path(path).read_bytes()
        obj = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as e:
        raise PacketRefused("news_file_unreadable", f"{path}: {type(e).__name__}: {e}") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("ticker"), str) or not isinstance(obj.get("rows"), list):
        raise PacketRefused("news_file_malformed", "the news file is not an object with a ticker and a list of rows")
    if any(not isinstance(r, dict) for r in obj["rows"]):
        raise PacketRefused("news_file_malformed", "a row of the news file is not an object")
    return obj, hashlib.sha256(raw).hexdigest()


def _row_time(row, n, T):
    """The row's effective time, an aware UTC datetime. `date` wins over `first_seen`. A day is the end of that day in UTC; the day of T
    itself is T (see the module docstring)."""
    v = row.get("date") if row.get("date") not in (None, "") else row.get("first_seen")
    if not isinstance(v, str) or not v.strip():
        raise PacketRefused("news_row_date_unreadable", f"row {n}: no date and no first_seen")
    v = v.strip()
    try:
        if _DAY.match(v):
            d = date.fromisoformat(v)
            return T if d == T.date() else datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise PacketRefused("news_row_date_unreadable", f"row {n}: {v!r} is not a day or an ISO time ({e})") from e
    if dt.tzinfo is None:
        raise PacketRefused("news_row_date_unreadable", f"row {n}: {v!r} has no zone")
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def _cut_at_sentence(text, room):
    """`text` cut at the last sentence end that leaves the OMIT marker inside `room` characters, marker included; None when no sentence end
    leaves packet.MIN_TRIMMED characters."""
    k = room - (len(sec_primary.OMIT.format(n=len(text))) + 1)
    ends = [m.end() for m in _SENTENCE_END.finditer(text[:max(k, 0)])]
    if not ends or ends[-1] < _packet.MIN_TRIMMED:
        return None
    kept = text[:ends[-1]].rstrip()
    return kept + "\n" + sec_primary.OMIT.format(n=len(text) - len(kept))


def add_news(pk, news, file_sha256):
    """`pk` (a packet dict of packet.build) with the rows of `news` (load_news_file's object) as items N1..; a new dict, `pk` unchanged."""
    ticker = str(pk.get("ticker") or "").strip().upper()
    if news["ticker"].strip().upper() != ticker:
        raise PacketRefused("news_ticker_mismatch", f"the news file is for {news['ticker']!r}, the packet for {ticker!r}")
    T = _packet.parse_T(pk["decision_time_utc"])
    rows = news["rows"]
    for n, r in enumerate(rows, 1):
        text = r.get("text")
        if not isinstance(text, str) or not text.strip():
            raise PacketRefused("news_row_no_text", f"row {n} has no text")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != r.get("text_sha256"):
            raise PacketRefused("news_text_sha_mismatch", f"row {n}: the text does not hash to its text_sha256")
        if _row_time(r, n, T) > T:
            raise PacketRefused("news_row_after_T", f"row {n} is dated {_packet._z(_row_time(r, n, T))}, after T {_packet._z(T)}")
    items, notes, stop = [], [], False
    room = NEWS_CAP
    for n, r in enumerate(rows, 1):
        text, cut = r["text"], False
        if not stop and len(text) > room:
            stop = True                                  # this row is cut or left out, and every later row is left out
            text, cut = _cut_at_sentence(text, room), True
        elif stop:
            text = None
        if text is None:
            notes.append(f"news_left_out: row {n} of {len(rows)} (news over {NEWS_CAP} characters)")
            continue
        if cut:
            notes.append(f"news_cut: row {n} of {len(rows)} to {len(text)} of {len(r['text'])} characters (news over {NEWS_CAP} characters)")
        room -= len(text)
        items.append({"kind": "news", "name": "news", "title": r.get("title"),
                      "source": {"label": "secondary", "publisher": r.get("publisher"), "url": r.get("url")}, "form": None, "period": None,
                      "accepted_raw": None, "effective_at": _packet._z(_row_time(r, n, T)), "raw_sha256": r["text_sha256"],
                      "found_by": r.get("found_by"), "text": text, "fact_id": f"N{len(items) + 1}"})
    out = dict(pk)
    out["evidence"] = list(pk["evidence"]) + items
    out["annotations"] = list(pk["annotations"]) + notes
    out["news_builder"] = NEWS_BUILDER
    out["news"] = {"file_sha256": file_sha256, "rows_in_file": len(rows), "rows_used": len(items), "rows_left_out": len(rows) - len(items)}
    return out


def build(ticker, T, screener_commit, *, news_file=None, **kwargs):
    """packet.build(ticker, T, screener_commit, **kwargs), with the news file's rows added when `news_file` is given. Without it the
    result is packet.build's, unchanged. The news file is read and checked for its shape before any SEC document is fetched."""
    news = None
    if news_file is not None:
        news = load_news_file(news_file)
    pk = _packet.build(ticker, T, screener_commit, **kwargs)
    return pk if news is None else add_news(pk, news[0], news[1])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build one m3m.packet.v1 packet, optionally with the rows of a news file as evidence items, "
                                             "into cache/m3m/packets/news/ (with --news-file) or cache/m3m/packets/ (without)")
    ap.add_argument("--news-file", help="a news file (see the module docstring); without it this is `python -m qwen_c.packet`")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--T", required=True, help="decision time, ISO with a zone (e.g. 2026-10-29T00:00:00Z), or 'now'")
    ap.add_argument("--commit", required=True, help="the screener output commit (regime archival: the frame commit)")
    ap.add_argument("--regime", choices=_packet.REGIMES, default=_packet.REGIME_VERIFIED)
    ap.add_argument("--verified-record", help="a check_new_runs out/check_<utc>.json (required for regime verified, refused for archival)")
    ap.add_argument("--screener-repo", help="the screener repository to read through git")
    ap.add_argument("--cik", help="the CIK, for an archival frame commit whose cik_map.json lacks the ticker")
    ap.add_argument("--online", action="store_true", help="fetch what the store lacks from SEC")
    a = ap.parse_args(argv)
    if a.regime == _packet.REGIME_VERIFIED and not a.verified_record:
        ap.error("--verified-record is required for --regime verified")
    T = datetime.now(timezone.utc).replace(microsecond=0) if a.T == "now" else a.T
    pk = build(a.ticker, T, a.commit, news_file=a.news_file, online=a.online, verified_record=a.verified_record,
               screener_repo_path=a.screener_repo, regime=a.regime, cik=a.cik)
    path = _packet.save(pk, NEWS_DIR if a.news_file else None)
    print(json.dumps({"packet": str(path), "packet_sha256": _packet.packet_sha256(pk), "evidence": [e["fact_id"] for e in pk["evidence"]],
                      "annotations": pk["annotations"], "excluded": pk["excluded"], **({"news": pk["news"]} if "news" in pk else {})}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

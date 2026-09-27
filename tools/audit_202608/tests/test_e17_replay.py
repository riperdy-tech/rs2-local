"""Replays of the three recorded desk-closure samples (E17, Phase 4)."""
import io
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at

E17_DIR = Path(__file__).resolve().parent / "fixture_data" / "e17"


def _body(n):
    blocks = "".join(f"#{i:07d}#" + "x" * 991 for i in range(0, n, 1000))
    return blocks[:n]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run_fixture_replay(fixture_name, tmp_path):
    fx = json.loads((E17_DIR / fixture_name).read_text(encoding="utf-8"))
    calls = fx["calls"]
    turn_plan = []
    k = 0
    for n in fx["turns"]:
        turn_plan.append(calls[k:k + n])
        k += n

    pages = {}
    first_outcome = {}
    for c in calls:
        if c["tool"] == "fetch_page" and c["url"] not in first_outcome and c["outcome"]["kind"] != "e16_note":
            first_outcome[c["url"]] = c["outcome"]
            o = c["outcome"]
            if o.get("served_url"):
                pages[o["served_url"]] = o["chars"]

    searches = {c["query"]: c["results"] for c in calls if c["tool"] == "search_web"}
    pending_alt = []

    turn_i = {"n": 0}
    recorded_model_msgs = []

    def router(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "11434" in url:
            body_json = json.loads(req.data.decode("utf-8"))
            recorded_model_msgs.append(body_json)
            i = turn_i["n"]
            turn_i["n"] += 1
            plan = turn_plan[i] if i < len(turn_plan) else []
            tcs = []
            for c in plan:
                if c["tool"] == "search_web":
                    args = {"query": c["query"], "why": c.get("why", "")}
                elif c["tool"] == "fetch_page":
                    args = {"url": c["url"]}
                else:
                    args = {"price": 1.0}
                tcs.append({"function": {"name": c["tool"], "arguments": args}})
            msg = {"role": "assistant", "content": "" if tcs else "R" * 6000, "tool_calls": tcs}
            return _Resp(json.dumps({"message": msg, "done_reason": "stop", "prompt_eval_count": 1000,
                                     "eval_count": 10}).encode())

        if url.startswith(at.SEARX):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [""])[0]
            if q in searches:
                res = [{"title": r["title"], "url": r["url"], "content": r["snippet"]} for r in searches[q]]
            else:
                res = [{"title": t, "url": u, "content": ""} for u, t in pending_alt[-1:]]
            return _Resp(json.dumps({"results": res}).encode())

        if url in pages and url not in first_outcome:
            return _Resp(("<html><body><p>" + _body(pages[url]) + "</p></body></html>").encode())

        o = first_outcome.get(url)
        if o is None:
            raise AssertionError(f"unexpected request {url}")
        kind = o["kind"]
        if kind == "masked":
            raise AssertionError(f"masked URL must never be requested: {url}")
        if kind == "page":
            return _Resp(("<html><body><p>" + _body(o["chars"]) + "</p></body></html>").encode())
        if kind == "alternate":
            pending_alt.append((o["served_url"], o.get("alt_title") or ""))
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        if kind == "corrected":
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if kind == "http_error":
            raise urllib.error.HTTPError(url, o["code"], "err", {}, None)
        if kind == "timeout":
            raise urllib.error.URLError("The read operation timed out")
        raise AssertionError(f"request for {kind} {url}")

    orig_urlopen = at.urllib.request.urlopen
    orig_dispatch = at.dispatch_tool
    at.urllib.request.urlopen = router

    desk_iter = iter([c for c in calls if c["tool"] == "run_financial_model"])

    def dispatch(name, args, **kw):
        if name == "run_financial_model":
            c = next(desk_iter)
            if c["desk"] == "validation_error":
                return {"error": "missing", "validation_error": True}
            return {"dcf_model": {"per_share_iv": c["base_per_share_iv"]}}
        return orig_dispatch(name, args, **kw)

    at.dispatch_tool = dispatch
    try:
        rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, verbose=False)
        snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
        return snap, meta, recorded_model_msgs, calls
    finally:
        at.urllib.request.urlopen = orig_urlopen
        at.dispatch_tool = orig_dispatch


def _assert_first_page_services(snap, calls, fixture_name):
    seen_urls = set()
    for rec, c in zip(snap, calls):
        if c["tool"] != "fetch_page":
            continue
        o = c["outcome"]
        if o.get("served_url") and o["served_url"] not in seen_urls:
            seen_urls.add(o["served_url"])
            ci = c["i"]
            assert rec.get("url") == o["served_url"], f"{fixture_name} call {ci} url mismatch"
            assert rec.get("chars") == o["chars"], f"{fixture_name} call {ci} chars mismatch"


def _assert_no_audit_keys_in_model_messages(msgs):
    for body in msgs:
        for m in body.get("messages", []):
            if m.get("role") == "tool":
                content = m.get("content", "")
                assert "_audit" not in content


def test_replay_ugi(tmp_path):
    fx_name = "replay_UGI_20260925_080045_s1.json"
    snap, meta, msgs, calls = run_fixture_replay(fx_name, tmp_path)

    # 1. First page services
    _assert_first_page_services(snap, calls, fx_name)

    # 2. Desk facts
    assert snap[6]["desk_budget"] == "0 of 5 desk runs used"
    assert snap[7]["desk_budget"] == "1 of 5 desk runs used"
    assert snap[8]["desk_budget"] == "2 of 5 desk runs used"
    assert snap[9]["desk_budget"] == "3 of 5 desk runs used"
    assert snap[11]["desk_budget"] == "4 of 5 desk runs used"
    assert snap[12]["desk_budget"] == "5 of 5 desk runs used"
    assert snap[12]["desk_closed"] == at.DESK_CLOSED_RUNS.format(cap=5)
    for i in range(13, 27):
        assert snap[i].get("desk") == at.DESK_CLOSED_LINE, f"call {i+1} missing desk"
    for i in list(range(0, 6)) + [10]:
        assert "desk" not in snap[i]

    # 3. Searches: 1-6 and 11
    search_idxs = [0, 1, 2, 3, 4, 5, 10]
    expected_served = [4, 4, 3, 4, 4, 3, 3]
    expected_aside = [2, 2, 3, 2, 2, 3, 3]
    for idx, s, a in zip(search_idxs, expected_served, expected_aside):
        assert snap[idx]["n_results"] == s
        assert snap[idx]["set_aside"]["count"] == a

    # 4. Fetches:
    assert snap[13]["part"] == 1 and snap[13]["parts"] == 2 and "blog.ugies.com" in snap[13]["url"]
    assert snap[14]["part"] == 1 and snap[14]["parts"] == 5
    assert snap[15]["part"] == 2 and snap[15]["parts"] == 5 and snap[15]["same_page_as"] == "call 15" and "note" in snap[15]
    assert snap[16]["part"] == 1 and snap[16]["parts"] == 1
    assert "refused: this address contains" in snap[17]["error"]
    for i in (18, 21, 25, 26):
        assert "already fetched in this sample:" in snap[i]["note"]
    assert snap[19]["part"] == 3 and snap[19]["parts"] == 5
    assert snap[20]["part"] == 1 and snap[20]["parts"] == 1
    assert "This page is a single part, served to you at call 21; this is request 2 for it" in snap[22]["note"]
    assert snap[23]["part"] == 2 and snap[23]["parts"] == 2
    assert snap[24]["part"] == 4 and snap[24]["parts"] == 5

    # 5. Counts
    assert meta["research_calls"] == 21
    assert meta["repeat_calls"] == 5

    # 6. Audit keys kept out
    _assert_no_audit_keys_in_model_messages(msgs)


def test_replay_aph(tmp_path):
    fx_name = "replay_APH_20260925_183541_s1.json"
    snap, meta, msgs, calls = run_fixture_replay(fx_name, tmp_path)

    # 1. First page services
    _assert_first_page_services(snap, calls, fx_name)

    # 2. Desk facts
    assert snap[0]["desk_budget"] == "1 of 5 desk runs used"
    assert snap[1]["desk_budget"] == "2 of 5 desk runs used"
    assert snap[3]["desk_budget"] == "3 of 5 desk runs used"
    assert snap[4]["desk_budget"] == "4 of 5 desk runs used"
    assert snap[5]["desk_budget"] == "5 of 5 desk runs used"
    assert snap[5]["desk_closed"] == at.DESK_CLOSED_RUNS.format(cap=5)
    for i in range(6, 30):
        assert snap[i].get("desk") == at.DESK_CLOSED_LINE
    assert "desk" not in snap[2]

    # 3. Searches
    assert snap[2]["n_results"] == 3
    assert snap[2]["set_aside"]["count"] == 3
    assert snap[2]["set_aside"]["hosts"] == ["bing.com"]
    assert snap[6]["n_results"] == 3
    assert snap[6].get("deduplicated_from") is not None or snap[6].get("cache_hit") is True

    # 4. Fetches
    assert snap[7]["part"] == 1 and snap[7]["parts"] == 14
    assert snap[8]["part"] == 1 and snap[8]["parts"] == 1
    assert snap[9]["part"] == 1 and snap[9]["parts"] == 1
    assert snap[10]["part"] == 1 and snap[10]["parts"] == 1
    for i in range(11, 30):
        req_num = i - 11 + 2
        assert f"this is request {req_num} for it" in snap[i]["note"]

    # 5. Counts
    assert meta["research_calls"] == 25
    assert meta["repeat_calls"] == 20

    # 6. Audit keys kept out
    _assert_no_audit_keys_in_model_messages(msgs)


def test_replay_fix(tmp_path):
    fx_name = "replay_FIX_20260925_053027_s1.json"
    snap, meta, msgs, calls = run_fixture_replay(fx_name, tmp_path)

    # 1. First page services
    _assert_first_page_services(snap, calls, fx_name)

    # 2. Desk facts
    for i in range(1, 6):
        assert snap[i]["desk_budget"] == f"{i} of 5 desk runs used"
    assert snap[5]["desk_closed"] == at.DESK_CLOSED_RUNS.format(cap=5)
    for i in range(6, 10):
        assert snap[i].get("desk") == at.DESK_CLOSED_LINE

    # 3. Searches
    assert snap[0]["n_results"] == 4
    assert snap[0]["set_aside"]["count"] == 2
    assert snap[6].get("deduplicated_from") is not None or snap[6].get("cache_hit") is True

    # 4. Fetches
    assert snap[7]["part"] == 1 and snap[7]["parts"] == 3

    # 5. Counts
    assert meta["research_calls"] == 5
    assert meta["repeat_calls"] == 1

    # 6. Audit keys kept out
    _assert_no_audit_keys_in_model_messages(msgs)


def format_replay_table(fixture_name, snap):
    lines = [
        f"### Replay: {fixture_name}",
        "| call | tool | part/parts or note | desk_budget/desk |",
        "|---|---|---|---|",
    ]
    for i, c in enumerate(snap):
        tool = c["tool"]
        part_col = "-"
        if tool == "fetch_page":
            if c.get("error"):
                part_col = f"error: {c['error'][:45]}"
            elif c.get("part") is not None and c.get("parts") is not None:
                p_str = f"part {c['part']} of {c['parts']}"
                if c.get("same_page_as"):
                    p_str += f" ({c['same_page_as']})"
                if c.get("served_again"):
                    p_str += " (served_again)"
                if c.get("note"):
                    p_str += f" (note: {c['note'][:30]}...)"
                part_col = p_str
            elif c.get("find"):
                part_col = f"find '{c['find']}' ({c.get('matches', 0)} matches)"
            elif c.get("note"):
                # 50 characters cut "... served to you at call " just before the call number (review 2026-09-27)
                part_col = f"note: {c['note'][:110]}"
        elif tool == "search_web":
            s_str = f"served {c.get('n_results', 0)}"
            if c.get("set_aside"):
                s_str += f", {c['set_aside']['count']} set aside"
            if c.get("deduplicated_from") or c.get("cache_hit") or c.get("dedup"):
                s_str += " (dup)"
            part_col = s_str
        elif tool == "run_financial_model":
            if c.get("error"):
                part_col = f"rejected ({c['error'][:30]})"
            elif c.get("dcf_model"):
                part_col = f"valid (IV={c['dcf_model'].get('per_share_iv')})"
            else:
                part_col = "valid"

        desk_info = []
        if c.get("desk_budget"):
            desk_info.append(c["desk_budget"])
        if c.get("desk_closed"):
            desk_info.append("CLOSED")
        if c.get("desk"):
            desk_info.append("desk_closed_line")
        desk_col = "; ".join(desk_info) if desk_info else "-"

        lines.append(f"| {i+1} | {tool} | {part_col} | {desk_col} |")
    return "\n".join(lines)


if __name__ == "__main__":
    import tempfile
    for name in ("replay_UGI_20260925_080045_s1.json", "replay_APH_20260925_183541_s1.json", "replay_FIX_20260925_053027_s1.json"):
        with tempfile.TemporaryDirectory() as td:
            snap, meta, msgs, calls = run_fixture_replay(name, Path(td))
            print(format_replay_table(name, snap))
            print()

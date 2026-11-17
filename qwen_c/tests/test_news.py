"""WO_HM2b: news items in the reading packet. Synthetic company and publishers only; no network, no model.

Two halves. (1) The byte-identity contract: a packet with no news item is read, rendered and valued exactly as before. The pins below were
computed from the code of af4bf77 (before this change) over the fixtures_b packet, so a drift in tasks.py, packet.py or contract.py shows
here; the existing pins (test_tasks.PINS, test_value_task, test_packet) are untouched. (2) The news path itself."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import sec_primary
from qwen_c import contract, news_packet, packet, runner, tasks
from qwen_c.news_packet import PacketRefused
from qwen_c.value import desk, run

FIX = Path(__file__).resolve().parent / "fixtures_b"
ACME = json.loads((FIX / "packet_acme.json").read_text(encoding="utf-8"))
T = ACME["decision_time_utc"]                                            # 2026-10-29T13:00:00Z

# sha256 of json.dumps(tasks.messages(task, ACME, PRIOR), sort_keys=True, ensure_ascii=False) at af4bf77
PRIOR = {"decision_time_utc": "2026-07-01T00:00:00Z", "tasks_used": ["growth_thesis", "risks"],
         "growth_thesis": [{"claim": "Revenue grew.", "fact_ids": ["P1"], "support": "supported"},
                           {"claim": "x", "fact_ids": [], "support": "quote_not_found"}],
         "risks": [{"claim": "Backlog risk.", "fact_ids": ["P1", "P2"], "support": "supported"}]}
MESSAGES_AF4BF77 = {
    "business_model": "49602d1d97bfdbb81933e9d115f5bc44779f006057212f3a2e745c11cf079aa9",
    "financial_health": "7bd1b196c12a400d48a1ff1c425f7ea02cb2d1a7ebc5a81b82f2f5b2c4982ca4",
    "competitive_position": "3fc9953c19d2ded8decf5703c714a35d21d2c292274f33b3baa5fc807f7340dc",
    "growth_thesis": "b48a1240627722c75075235f119f3dd8f98b16dd87983b273311af795498d09c",
    "risks": "19fa721ea30c43e327fd939a82e5f494980283199baddf1955b60b050063d2b0",
    "thesis_change": "05ce931ab2938f1fbc129504171af575befe4fdf96722ffe1f2be415ad5e728a",
    "unresolved_questions": "1fc39019ba8cf6e94cd1de8a68ad4069ff5eb2425b88629afca602895272a1e2",
    "material_events": "afd04f2de5a73a4a039e6a797eace92a74ec07e0ee74be662ed06585c320684e",
}
RISKS_RETRY_AF4BF77 = "2b3689f7c890c8e4afe62a3fb0a481a695e55d6f4f15740b5a045ce8b2a83c8f"
ACME_PACKET_SHA256_AF4BF77 = "9dd6a281124125a23be093bac21e6dd98737f4e40281c84e9076e4d681055c59"


def h(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def prior_for(task):
    return PRIOR if task == "thesis_change" else None


# ---------------------------------------------------------------- (1) a packet with no news item does not move

@pytest.mark.parametrize("task", tasks.TASKS)
def test_the_messages_of_every_reading_task_are_those_of_af4bf77_without_news(task):
    assert h(tasks.messages(task, ACME, prior_for(task))) == MESSAGES_AF4BF77[task]


def test_the_retry_message_and_the_packet_bytes_are_those_of_af4bf77():
    assert h(tasks.messages("risks", ACME, None, retry=True)) == RISKS_RETRY_AF4BF77
    assert packet.packet_sha256(ACME) == ACME_PACKET_SHA256_AF4BF77


def test_prompt_version_is_not_moved():
    assert tasks.PROMPT_VERSION == "m3m.prompt.v3"


def test_the_news_sentence_is_not_in_any_message_of_a_packet_without_news():
    for task in tasks.TASKS:
        assert tasks.NEWS_SENTENCE not in tasks.messages(task, ACME, prior_for(task))[1]["content"]


def test_a_build_without_a_news_file_returns_the_dict_of_packet_build_itself(monkeypatch):
    seen = {}

    def fake(ticker, T_, commit, **kw):
        seen.update(args=(ticker, T_, commit), kw=kw)
        return ACME
    monkeypatch.setattr(packet, "build", fake)
    got = news_packet.build("ACME", T, "c0ffee", online=False, verified_record=[], regime="verified")
    assert got is ACME and seen == {"args": ("ACME", T, "c0ffee"), "kw": {"online": False, "verified_record": [], "regime": "verified"}}
    assert "news" not in got and "news_builder" not in got


def test_the_news_module_is_outside_the_pinned_builder_files():
    """builder_code hashes packet.py, sec_primary.py and sec_guidance.py into every packet: the news code must live elsewhere."""
    pinned = {Path(p).resolve() for _, p in packet.BUILDER_FILES}
    assert Path(news_packet.__file__).resolve() not in pinned
    assert Path(packet.__file__).resolve() in pinned


def test_the_system_text_the_valuation_call_shares_is_unchanged():
    assert hashlib.sha256(tasks.SYSTEM.encode("utf-8")).hexdigest() == "1fc6498c1385bb51257e77c8d1e20b9eb732bf576650bf19142df8b8d170324c"


# ---------------------------------------------------------------- (2) the news file and the items

def row(n=1, text=None, **over):
    text = text if text is not None else f"Northwind Pumps said on the day that it signed a supply agreement number {n}. The agreement runs two years."
    r = {"title": f"Northwind Pumps signs agreement {n}", "url": f"https://news.example.test/a{n}", "publisher": "Example Wire",
         "date": "2026-10-28", "found_by": "category:contract", "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    r.update(over)
    return r


def write(tmp_path, rows, ticker="ACME", name="news.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"ticker": ticker, "T": T, "rows": rows}), encoding="utf-8")
    return p


def add(tmp_path, rows, **kw):
    p = write(tmp_path, rows, **kw)
    obj, sha = news_packet.load_news_file(p)
    return news_packet.add_news(ACME, obj, sha), sha


def test_each_row_becomes_one_item_after_every_sec_item(tmp_path):
    pk, sha = add(tmp_path, [row(1), row(2)])
    n = len(ACME["evidence"])
    assert pk["evidence"][:n] == ACME["evidence"]                        # no SEC item cut, moved or renumbered
    assert [e["fact_id"] for e in pk["evidence"][n:]] == ["N1", "N2"]
    e = pk["evidence"][n]
    r = row(1)
    assert e == {"kind": "news", "name": "news", "title": r["title"], "source": {"label": "secondary", "publisher": "Example Wire",
                 "url": r["url"]}, "form": None, "period": None, "accepted_raw": None, "effective_at": "2026-10-28T23:59:59Z",
                 "raw_sha256": r["text_sha256"], "found_by": "category:contract", "text": r["text"], "fact_id": "N1"}
    assert pk["news_builder"] == "m3p.news.v1" == news_packet.NEWS_BUILDER
    assert pk["news"] == {"file_sha256": sha, "rows_in_file": 2, "rows_used": 2, "rows_left_out": 0}
    assert pk["builder_version"] == ACME["builder_version"] and pk["annotations"] == ACME["annotations"]


def test_nothing_but_the_news_fields_the_evidence_and_the_notes_differs_from_the_packet_without_news(tmp_path):
    pk, _ = add(tmp_path, [row(1)])
    keep = lambda d: {k: v for k, v in d.items() if k not in ("evidence", "news", "news_builder")}
    assert keep(pk) == keep(ACME)


def test_the_input_packet_is_not_changed(tmp_path):
    before = copy.deepcopy(ACME)
    add(tmp_path, [row(1)])
    assert ACME == before


def test_the_file_hash_is_the_sha256_of_its_bytes(tmp_path):
    p = write(tmp_path, [row(1)])
    assert news_packet.load_news_file(p)[1] == hashlib.sha256(p.read_bytes()).hexdigest()


def test_a_packet_with_news_loads_in_the_runner_and_the_ids_are_unique(tmp_path):
    pk, _ = add(tmp_path, [row(1), row(2)])
    p = tmp_path / "pk.json"
    p.write_bytes(packet.canonical_bytes(pk))
    loaded, _src = runner.load_packet(p)
    assert [e["fact_id"] for e in loaded["evidence"]][-2:] == ["N1", "N2"]


@pytest.mark.parametrize("code,rows,ticker", [
    ("news_ticker_mismatch", [row(1)], "OTHER"),
    ("news_row_no_text", [row(1, text="", text_sha256=hashlib.sha256(b"").hexdigest())], "ACME"),
    ("news_row_no_text", [{**row(1), "text": None}], "ACME"),
    ("news_text_sha_mismatch", [row(1, text_sha256="0" * 64)], "ACME"),
    ("news_row_after_T", [row(1), row(2, date="2026-10-30")], "ACME"),                       # row 2 only: the file is refused
    ("news_row_after_T", [row(1, date=None, first_seen="2026-10-29T13:00:01Z")], "ACME"),
    ("news_row_date_unreadable", [row(1, date=None)], "ACME"),
    ("news_row_date_unreadable", [row(1, date="yesterday")], "ACME"),
    ("news_row_date_unreadable", [row(1, date=None, first_seen="2026-10-28T10:00:00")], "ACME"),       # no zone
])
def test_the_file_is_refused_with_a_code(tmp_path, code, rows, ticker):
    p = write(tmp_path, rows, ticker=ticker)
    obj, sha = news_packet.load_news_file(p)
    with pytest.raises(PacketRefused) as e:
        news_packet.add_news(ACME, obj, sha)
    assert e.value.code == code


def test_a_row_that_would_be_left_out_is_still_checked(tmp_path):
    big = "A sentence of filler text. " * 1000
    with pytest.raises(PacketRefused) as e:
        add(tmp_path, [row(1, text=big), row(2, text=big), row(3, text="x", text_sha256="1" * 64)])
    assert e.value.code == "news_text_sha_mismatch"


@pytest.mark.parametrize("body", ["not json", "[]", json.dumps({"ticker": "ACME"}), json.dumps({"ticker": "ACME", "rows": [1]})])
def test_a_malformed_file_is_refused(tmp_path, body):
    p = tmp_path / "bad.json"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(PacketRefused) as e:
        news_packet.load_news_file(p)
    assert e.value.code in ("news_file_unreadable", "news_file_malformed")


def test_an_unreadable_file_is_refused(tmp_path):
    with pytest.raises(PacketRefused) as e:
        news_packet.load_news_file(tmp_path / "missing.json")
    assert e.value.code == "news_file_unreadable"


def test_dates_a_day_is_end_of_day_utc_a_time_with_a_zone_is_converted_and_date_wins(tmp_path):
    pk, _ = add(tmp_path, [row(1, date=None, first_seen="2026-10-28T20:30:00+09:00"),
                           row(2, date="2026-10-27", first_seen="2026-10-28T00:00:00Z")])
    got = [e["effective_at"] for e in pk["evidence"][-2:]]
    assert got == ["2026-10-28T11:30:00Z", "2026-10-27T23:59:59Z"]


def test_a_row_dated_the_day_of_T_is_taken_and_counts_at_T_and_is_newer_than_a_prior_run_of_that_day(tmp_path):
    pk, _ = add(tmp_path, [row(1, date="2026-10-29"), row(2, date="2026-10-28")])            # T is 2026-10-29T13:00:00Z
    assert [e["effective_at"] for e in pk["evidence"][-2:]] == [T, "2026-10-28T23:59:59Z"]
    assert tasks.effective_after(pk, "2026-10-29T09:00:00Z")[-1:] == ["N1"]                  # a run earlier that day did not read it


def test_a_row_exactly_at_T_is_not_after_T(tmp_path):
    pk, _ = add(tmp_path, [row(1, date=None, first_seen=T)])
    assert pk["evidence"][-1]["effective_at"] == T


# ---- the news budget

SENT = "Northwind Pumps reported another development today. "          # 51 characters


def test_news_has_its_own_budget_and_never_touches_an_sec_item(tmp_path):
    sec = copy.deepcopy(ACME)
    sec["evidence"][2]["text"] = "x" * (packet.TOTAL_CAP + 5_000)         # the SEC part is over TOTAL_CAP's reach: still not cut by news
    obj = {"ticker": "ACME", "rows": [row(1, text=SENT * 100), row(2, text=SENT * 100)]}
    got = news_packet.add_news(sec, obj, "f" * 64)
    assert got["evidence"][:len(sec["evidence"])] == sec["evidence"]
    assert sum(len(e["text"]) for e in got["evidence"] if e["kind"] == "news") <= news_packet.NEWS_CAP
    assert news_packet.NEWS_CAP == 24_000 and news_packet.NEWS_CAP != packet.TOTAL_CAP


def test_a_row_over_what_is_left_is_cut_at_a_sentence_end_and_later_rows_are_left_out(tmp_path):
    rows = [row(1, text=SENT * 200), row(2, text=SENT * 200), row(3, text=SENT * 200), row(4, text=SENT * 10), row(5, text=SENT * 10)]
    pk, _ = add(tmp_path, rows)
    news = [e for e in pk["evidence"] if e["kind"] == "news"]
    assert [e["fact_id"] for e in news] == ["N1", "N2", "N3"]
    assert len(news[0]["text"]) == 200 * len(SENT) and len(news[1]["text"]) == 200 * len(SENT)
    cut = news[2]["text"]
    body, marker = cut.rsplit("\n", 1)
    assert body.endswith(".") and sec_primary.OMIT_RE.fullmatch(marker)
    assert marker == sec_primary.OMIT.format(n=200 * len(SENT) - len(body))
    assert sum(len(e["text"]) for e in news) <= news_packet.NEWS_CAP
    notes = pk["annotations"][len(ACME["annotations"]):]
    assert notes == [f"news_cut: row 3 of 5 to {len(cut)} of {200 * len(SENT)} characters (news over 24000 characters)",
                     "news_left_out: row 4 of 5 (news over 24000 characters)", "news_left_out: row 5 of 5 (news over 24000 characters)"]
    assert pk["news"]["rows_in_file"] == 5 and pk["news"]["rows_used"] == 3 and pk["news"]["rows_left_out"] == 2


def test_a_cut_row_keeps_what_the_quote_check_needs_from_its_kept_part(tmp_path):
    pk, _ = add(tmp_path, [row(1, text=SENT * 600)])
    cut = pk["evidence"][-1]["text"]
    assert contract.quote_found(SENT.strip(), [cut])
    assert not contract.quote_found(cut.rsplit("\n", 1)[1], [cut])         # the omission marker is never a quote


def test_a_row_with_no_sentence_end_to_cut_at_is_left_out(tmp_path):
    pk, _ = add(tmp_path, [row(1, text=SENT * 100), row(2, text="word " * 30_000)])
    assert [e["fact_id"] for e in pk["evidence"] if e["kind"] == "news"] == ["N1"]
    assert pk["annotations"][-1] == "news_left_out: row 2 of 2 (news over 24000 characters)"


def test_a_row_that_fits_exactly_is_kept_whole(tmp_path):
    pk, _ = add(tmp_path, [row(1, text="B" * 23_999 + "."), row(2)])
    news = [e for e in pk["evidence"] if e["kind"] == "news"]
    assert len(news[0]["text"]) == 24_000 and [e["fact_id"] for e in news] == ["N1"]
    assert pk["annotations"][-1] == "news_left_out: row 2 of 2 (news over 24000 characters)"


def test_an_empty_row_list_adds_nothing_but_records_the_file(tmp_path):
    pk, sha = add(tmp_path, [])
    assert pk["evidence"] == ACME["evidence"] and pk["news"] == {"file_sha256": sha, "rows_in_file": 0, "rows_used": 0, "rows_left_out": 0}


def test_build_with_a_news_file_reads_the_file_before_any_packet_work(tmp_path, monkeypatch):
    monkeypatch.setattr(packet, "build", lambda *a, **k: pytest.fail("packet.build was called"))
    with pytest.raises(PacketRefused) as e:
        news_packet.build("ACME", T, "c0ffee", news_file=tmp_path / "missing.json", online=False)
    assert e.value.code == "news_file_unreadable"


def test_build_and_the_cli_with_a_news_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(packet, "build", lambda *a, **k: copy.deepcopy(ACME))
    monkeypatch.setattr(news_packet, "NEWS_DIR", tmp_path / "out")
    p = write(tmp_path, [row(1)])
    assert news_packet.main(["--ticker", "ACME", "--T", T, "--commit", "c0ffee", "--verified-record", "x.json", "--news-file", str(p)]) == 0
    out = json.loads(capsys.readouterr().out)
    saved = Path(out["packet"])
    assert saved.parent == tmp_path / "out" and out["evidence"][-1] == "N1" and out["news"]["rows_used"] == 1
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == out["packet_sha256"]


# ---- what the model is told

def with_news(tmp_path):
    return add(tmp_path, [row(1), row(2)])[0]


def test_a_news_item_is_rendered_with_its_secondary_source(tmp_path):
    pk = with_news(tmp_path)
    text = tasks.render_packet(pk)
    r = row(1)
    assert (f"[N1] kind: news | title: {r['title']} | form: not stated | period: not stated | effective: 2026-10-28T23:59:59Z | "
            f"source: press report (secondary): Example Wire, {r['url']}\n{r['text']}") in text
    assert "EVIDENCE ITEMS: %d" % (len(ACME["evidence"]) + 2) in text
    for e in ACME["evidence"]:
        assert tasks.render_item(e) in text                              # every SEC item renders as before
    assert "news_" not in text and "found_by" not in text and "category:contract" not in text


def test_a_source_without_the_secondary_label_renders_as_before():
    assert tasks._source({"accession": "A-1", "url": "u"}) == "SEC accession A-1, u"
    assert tasks._source({"git_commit": "c", "path": "p"}) == "screener git c:p"
    assert tasks._source({"label": "secondary", "publisher": None, "url": "u"}) == "press report (secondary): not stated, u"


@pytest.mark.parametrize("task", ["material_events", "thesis_change"])
def test_the_one_sentence_ends_the_instruction_of_two_tasks_when_the_packet_holds_news(tmp_path, task):
    pk = with_news(tmp_path)
    without = tasks.messages(task, ACME, prior_for(task))[1]["content"]
    got = tasks.messages(task, pk, prior_for(task))[1]["content"]
    assert got.endswith("\n" + tasks.NEWS_SENTENCE)
    assert tasks.NEWS_SENTENCE == ("Items of kind news are press reports, not company filings. An event or change they report may be "
                                   "claimed: cite the news item, quote it exactly, and say in confidence_basis that the source is a press report.")
    assert got.count(tasks.NEWS_SENTENCE) == 1
    assert tasks.messages(task, pk, prior_for(task))[0] == tasks.messages(task, ACME, prior_for(task))[0]   # the system text is shared
    plain = tasks.thesis_change_instruction if task == "thesis_change" else (lambda p, q: tasks.INSTRUCTIONS[task])
    assert tasks.instruction(task, pk, prior_for(task)) == plain(pk, PRIOR) + "\n" + tasks.NEWS_SENTENCE   # the instruction as before, then the sentence
    assert tasks.instruction(task, ACME, prior_for(task)) == plain(ACME, PRIOR) and without.endswith(plain(ACME, PRIOR))


@pytest.mark.parametrize("task", [t for t in tasks.TASKS if t not in ("material_events", "thesis_change")])
def test_no_other_task_is_told_anything_new(tmp_path, task):
    pk = with_news(tmp_path)
    user = tasks.messages(task, pk)[1]["content"]
    assert user == tasks.render_packet(pk) + "\n\n" + tasks.INSTRUCTIONS[task]
    assert tasks.NEWS_SENTENCE not in user


def test_thesis_change_counts_a_news_item_dated_after_the_prior_as_newer(tmp_path):
    pk = with_news(tmp_path)
    assert tasks.effective_after(pk, "2026-07-01T00:00:00Z")[-2:] == ["N1", "N2"]
    assert "N1" not in tasks.effective_after(pk, "2026-10-28T23:59:59Z")


# ---- the quote check treats a news item like a filing item

def claim(ids, quote, text="Northwind Pumps signed a supply agreement."):
    return {"claim": text, "fact_ids": ids, "quotes": [quote], "numbers": [], "confidence_basis": "stated in a press report"}


def test_a_claim_citing_a_news_item_is_supported_when_its_quote_is_in_the_news_text(tmp_path):
    pk = with_news(tmp_path)
    got = contract.check_claim(claim(["N1"], "The agreement runs two years."), contract.evidence_texts(pk), "ACME")
    assert got == {"support": "supported", "support_failures": []}


def test_a_quote_not_in_the_news_text_is_unsupported(tmp_path):
    pk = with_news(tmp_path)
    got = contract.check_claim(claim(["N1"], "The agreement runs ten years."), contract.evidence_texts(pk), "ACME")
    assert got["support"] == "quote_not_found" and got["support_failures"] == [{"check": "quote_not_found", "detail": "The agreement runs ten years."}]


def test_a_quote_of_one_news_item_does_not_support_a_claim_citing_another(tmp_path):
    pk = add(tmp_path, [row(1), row(2, text="Northwind Pumps announced a second thing. It is unrelated.")])[0]
    got = contract.check_claim(claim(["N1"], "It is unrelated."), contract.evidence_texts(pk), "ACME")
    assert got["support"] == "quote_not_found"


def test_a_claim_citing_a_filing_and_a_news_item_is_checked_against_both(tmp_path):
    pk = with_news(tmp_path)
    texts = contract.evidence_texts(pk)
    ok = contract.check_claim(claim(["P2", "N1"], "The agreement runs two years."), texts, "ACME")
    assert ok["support"] == "supported"
    both = {**claim(["P2", "N1"], "Gross margin was 31.2%."), "quotes": ["Gross margin was 31.2%.", "The agreement runs two years."]}
    assert contract.check_claim(both, texts, "ACME")["support"] == "supported"
    bad = {**both, "quotes": ["Gross margin was 31.2%.", "The agreement runs ten years."]}
    got = contract.check_claim(bad, texts, "ACME")
    assert got["support"] == "quote_not_found" and [f["detail"] for f in got["support_failures"]] == ["The agreement runs ten years."]


def test_a_news_item_in_check_task_is_cited_like_any_item(tmp_path):
    pk = with_news(tmp_path)
    c = {**claim(["N2"], "The agreement runs two years."), "event_type": "other_material_event", "status": "announced_pending",
         "occurred_on": "not stated"}
    got = contract.check_task("material_events", {"task": "material_events", "claims": [c], "unknowns": []}, pk)
    assert got["status"] == "ok" and [x["support"] for x in got["claims"]] == ["supported"]


def test_a_news_figure_must_be_printed_in_the_cited_news_item(tmp_path):
    pk = add(tmp_path, [row(1, text="Northwind Pumps will pay $40 million for a rival. The deal is pending.")])[0]
    c = {"claim": "Northwind Pumps will pay $40 million for a rival.", "fact_ids": ["N1"], "quotes": ["The deal is pending."],
         "numbers": ["$40 million"], "confidence_basis": "stated in a press report"}
    assert contract.check_claim(c, contract.evidence_texts(pk), "ACME")["support"] == "supported"
    assert contract.check_claim({**c, "numbers": ["$50 million"]}, contract.evidence_texts(pk), "ACME")["support"] == "number_not_found"


# ---------------------------------------------------------------- the valuation refuses news

def test_the_valuation_call_refuses_a_packet_with_news_items_before_any_model_call(tmp_path, monkeypatch):
    pk = with_news(tmp_path)
    p = tmp_path / "pk.json"
    p.write_bytes(packet.canonical_bytes(pk))

    def boom(*a, **k):
        raise AssertionError("reached past the refusal")
    monkeypatch.setattr(run, "prepare", boom)
    monkeypatch.setattr(run, "_one_call", boom)
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=tmp_path / "runs", url="http://x")
    assert res["status"] == "no_call" and res["reason"] == "news_items_not_valued"
    assert (next((tmp_path / "runs").iterdir()) / "result.json").is_file()


def test_the_valuation_call_still_prepares_a_packet_without_news(tmp_path, monkeypatch):
    p = tmp_path / "pk.json"
    p.write_bytes(packet.canonical_bytes(ACME))

    def refuse(*a, **k):
        raise desk.DeskRefusal("history_short", "stub")
    monkeypatch.setattr(run, "prepare", refuse)
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=tmp_path / "runs", url="http://x")
    assert res["status"] == "no_call" and res["reason"] == "history_short"

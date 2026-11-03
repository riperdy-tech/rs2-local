"""F_SPEC_valuation_menu §1 (F1): sentence IDs. The splitter's rules on hand cases, and pinned on a fixed packet of E3 filing text
(fixtures_value/sentences_packet.json: windows of the IRWD, TASK, RNG and MATX packets of 2026-11-01 and one statement)."""
import hashlib
import json
from pathlib import Path

import pytest

from qwen_c import tasks
from qwen_c.value import sentences

PK = json.loads((Path(__file__).resolve().parent / "fixtures_value" / "sentences_packet.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("line,want", [
    ("Revenue grew 5.2% in 2025. Margins held.", ["Revenue grew 5.2% in 2025.", "Margins held."]),
    ("Acme, Inc. (the Company) sells in the U.S. and abroad.", ["Acme, Inc. (the Company) sells in the U.S. and abroad."]),
    ("GAAP diluted EPS of $6.50. GAAP net income rose.", ["GAAP diluted EPS of $6.50.", "GAAP net income rose."]),
    ("See Note No. 4 and Mr. Smith's letter. J. Doe signed it.", ["See Note No. 4 and Mr. Smith's letter.", "J. Doe signed it."]),
    ("“We grew.” Sales rose 3%.", ["“We grew.”", "Sales rose 3%."]),
    ("Item 2. Results of operations follow.", ["Item 2.", "Results of operations follow."]),
    ("Revenue | $100 | $90. Next | 3", ["Revenue | $100 | $90. Next | 3"]),          # a table row is one sentence
    ("​", []), ("   ", []),                                                   # no letter or digit: no sentence
    ("margin of 3.5%, up from 3.1% last year", ["margin of 3.5%, up from 3.1% last year"]),
])
def test_split_rules(line, want):
    assert sentences.split_line(line) == want


def test_ids_number_over_the_whole_item_and_carry_the_items_metadata():
    ids = sentences.index([{"fact_id": "P4", "kind": "release", "period": "2026-02-01", "form": "8-K", "text": "One. Two.\n​\nThree."},
                           {"fact_id": "F1", "kind": "statement", "period": "2025-12-31", "text": "Revenue | 1 | 2\nCost | 1 | 1"},
                           {"fact_id": "S0", "kind": "screener_row", "text": "symbol: T"}])
    assert list(ids) == ["P4.s1", "P4.s2", "P4.s3", "F1", "S0"]
    assert ids["P4.s3"] == {"fact_id": "P4", "kind": "release", "period": "2026-02-01", "form": "8-K", "text": "Three.", "sentence": True}
    assert ids["F1"]["sentence"] is False and "P4" not in ids                  # a prose item is cited by its sentences only


def test_marked_rendering_keeps_every_line_and_the_text():
    item = {"fact_id": "P4", "kind": "release", "text": "One. Two.\n​\nThree."}
    assert sentences.marked(item) == "<1> One. <2> Two.\n​\n<3> Three."
    pk = sentences.marked_packet({"evidence": [item, {"fact_id": "F1", "kind": "statement", "text": "A | 1"}]})
    assert pk["evidence"][1]["text"] == "A | 1" and "<1>" not in tasks.render_item(pk["evidence"][1])


def test_pinned_on_the_fixed_packet():
    ids = sentences.index(PK["evidence"])
    assert sum(1 for v in ids.values() if v["sentence"]) == 93
    assert ids["TASK_P6.s15"]["text"].startswith("We are also increasing the bottom end of our revenue guidance by $10 million")
    assert ids["TASK_P6.s15"]["text"].endswith("an Adjusted EBITDA margin of approximately 19%.")
    assert ids["RNG_P7.s3"]["text"] == "Subscriptions revenue up 6.0%, above high end of guidance, with record GAAP and non-GAAP margins"
    assert ids["RNG_P7.s13"]["text"] == "•GAAP diluted EPS of $6.50."
    assert "Raises total revenue guidance to $460 - $485 million" in ids["IRWD_P6.s5"]["text"]
    assert ids["MATX_P4.s14"]["text"].startswith("For the full year 2026, the Company expects to make capital expenditure payments")
    assert ids["IRWD_F1"]["kind"] == "statement" and not ids["IRWD_F1"]["sentence"]
    marked = json.dumps(sentences.marked_packet(PK)["evidence"], sort_keys=True).encode()
    assert hashlib.sha256(marked).hexdigest() == "f44da27ce87ceab60930ab586fcdaaed1885477e98055423dfeb4d040a17f801", \
        "the splitter changed: bump SENTENCES_VERSION and re-pin"


def test_every_sentence_is_printed_after_its_marker():
    pk = sentences.marked_packet(PK)
    text = "\n".join(e["text"] for e in pk["evidence"])
    for sid, v in sentences.index(PK["evidence"]).items():
        if v["sentence"]:
            assert f"<{sid.rsplit('.s', 1)[1]}> {v['text']}" in text

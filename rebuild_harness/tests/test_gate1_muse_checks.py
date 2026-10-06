"""The pure helpers of the Muse-side checks: the name as of T from the former-name history, the descriptive extraction flags, the report rendering."""
from rebuild_harness import gate1_muse_checks as mc


def test_name_as_of_T_from_the_former_name_history():
    subs = {"name": "NEWCO INC", "formerNames": [{"name": "OLDCO LTD", "from": "1999-01-01T00:00:00.000Z", "to": "2020-06-15T00:00:00.000Z"},
                                                 {"name": "OLDEST", "from": "1990-01-01T00:00:00.000Z", "to": "1998-12-31T00:00:00.000Z"}]}
    assert mc.name_asof(subs, "2019-12-31") == ("OLDCO LTD", "as_of_T")
    assert mc.name_asof(subs, "2021-01-31") == ("NEWCO INC", "as_of_T")
    assert mc.name_asof({"name": "SAME INC", "formerNames": []}, "2019-12-31") == ("SAME INC", "as_of_T")
    gap = {"name": "NEWCO INC", "formerNames": [{"name": "OLDCO LTD", "from": "2001-01-01T00:00:00.000Z", "to": "2010-01-01T00:00:00.000Z"}]}
    assert mc.name_asof(gap, "2022-01-01")[1] == "as_of_T"
    gap2 = {"name": "NEWCO INC", "formerNames": [{"name": "A", "from": "2001-01-01T00:00:00.000Z", "to": "2005-01-01T00:00:00.000Z"},
                                                 {"name": "B", "from": "2008-01-01T00:00:00.000Z", "to": "2012-01-01T00:00:00.000Z"}]}
    assert mc.name_asof(gap2, "2006-06-01") == ("NEWCO INC", "current_record")        # T falls in a gap of the history: the name cannot be certified as of T


def test_extraction_flags_are_descriptive():
    assert "short" in mc.extraction_flags("We make widgets.", "annual_business")
    f = mc.extraction_flags("OPERATIONS The following discussion should be read " + "x" * 2000 + " Item 7A. Quantitative", "annual_mdna_outlook")
    assert "head_looks_like_a_wrapped_heading_fragment" in f and "next_item_heading_in_tail" in f and "short" not in f
    assert "table_of_contents_marker_in_head" in mc.extraction_flags("Table of Contents " + "x" * 3000, "annual_business")
    assert any(x.startswith("omission_markers:") for x in mc.extraction_flags("a [… 1,930 characters omitted …] b" + "x" * 3000, "annual_business"))
    assert mc.extraction_flags("Overview. We design and sell products. " + "x" * 3000, "annual_business") == []


def test_render_extraction_lists_every_row():
    summary = {"fetch": "no network: caches only", "extraction": [{"date": "2019-12-31", "ticker": "AAA", "family_at_T": "operating", "extraction": {
        "notes": ["n"], "item_1_business": {"found": True, "chars": 2000, "head": "h", "tail": "t", "form": "10-K", "accession": "a", "filed": "2019-02-01", "flags": []},
        "item_7_mdna": {"found": False}}}, {"date": "2019-12-31", "ticker": "BBB", "error": "x"}]}
    md = mc.render_extraction(summary)
    assert "| 2019-12-31 | AAA | operating | 2000 [] | NOT FOUND  |" in md and "BBB" not in md.split("## Heads")[0]

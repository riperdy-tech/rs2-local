"""ix_figures.py - figures read from the inline XBRL of the newest annual filing, where companyfacts lacks them (WO_UV3 part B, RR_UV1 P1).

companyfacts holds only the us-gaap, ifrs-full, dei and srt taxonomies, no fact with a dimension, and lags behind filings. The filing's own
main document (read by ixbrl.parse) holds all of them. Four readings, each used ONLY where the valuation would otherwise be refused for that
figure, never in place of a figure companyfacts carries, and each USED only after a second filed figure agrees:

 1. fill_new_year  a fiscal year the newest annual filing reports that companyfacts has not ingested (the filing is later than the facts):
                   every concept of facts.CONCEPTS, under its own listed tag, from the filing's undimensioned facts. Verified per tag by the
                   filing's prior-year column of the SAME tag against companyfacts' value for that year (a tag with no companyfacts value for the
                   prior year cannot be verified and is not read).
 2. fill_capex     capital spending filed under a company's own (extension) tags: the lines of the cash-flow statement's investing section whose
                   tag names a payment to acquire vessels, property, plant or equipment (CAPEX_WORDS). Verified by the investing section's own
                   arithmetic: every line of the section, as printed, adds to the filed subtotal within the rounding of the printed figures;
                   and against companyfacts' capital spending wherever it also has a year the filing shows.
 3. fill_da        depreciation and amortization filed only with a segment dimension (one member): verified by the prior-year column, net of
                   the amortization, against companyfacts' depreciation for that year.
 4. share_candidates  the diluted weighted-average share count by class of stock, with the diluted EPS of the same class. Not a series: inputs
                   proves each candidate with check_shares against the class's own EPS and uses one that reconciles.

One source per pooled series (WO_UV5): where a reading 2 or 3 supplies capex or D&A, every pooled year of that concept comes from the filing's own
columns. The feed's figures for the same years or for older years are a narrower tag against the statement's line (or a total against a segment's), so they
are not pooled with the filing's: they are dropped, and the engine then refuses the name if the filing's columns hold fewer than the pool's minimum
(inputs.MIN_POOL_YEARS) of years. A feed year under the SAME tag as the filing's one line (same member) is the same concept: it is kept, and must
agree with the filing where both show the year.

Tolerance, everywhere: the rounding of the printed figures (decimals attribute): one printed figure is off by at most half a unit, so a sum of n
figures by n/2 units (the rule inputs.senior_debt already uses). No other threshold exists here; where a figure cannot be verified it is not used.
A cell the filer left untagged is blank, never 0 (a tagged "-" is a filed 0). Every value read is stamped
`ix_read:<concept>:<accession>:<tag>` and a share count `shares_from_ix_class_members:...` in inputs.
"""
import re
from dataclasses import dataclass

from qwen_c import packet, sec_store
from qwen_c.value import ixbrl

IX_FIGURES_VERSION = "m3q.ix_figures.v2"   # v2 WO_UV5: a pooled series read from the filing comes from the filing's columns alone
STAMP = "ix_read"
SHARES_STAMP = "shares_from_ix_class_members"
ANNUAL_DAYS = (350, 380)         # facts.py: a fiscal year
CLASS_AXIS = "StatementClassOfStockAxis"

# Capital spending lines of the cash-flow statement, by the words of the tag name: a payment word and an asset word, and nothing else. A tag with
# any other word (Leaseback, DryDock, Securities, Business, Subsidiaries, Proceeds, Sale, ...) is not read: the line is then not capital spending
# for this reading, and the investing arithmetic still holds without it.
PAYMENT_WORDS = {"Payments", "Payment", "Purchase", "Purchases", "Investment", "Investments", "Additions", "Addition", "Acquire", "Acquisition",
                 "Acquisitions", "Expenditure", "Expenditures"}
ASSET_WORDS = {"Vessel", "Vessels", "Property", "Plant", "Equipment", "Aircraft", "Rig", "Rigs", "Fleet", "Ship", "Ships", "Productive", "Assets"}
FILLER_WORDS = {"To", "For", "Of", "In", "And", "Other", "Under", "Construction", "Including", "Attached", "Time", "Charter", "Agreements", "Classified",
                "As", "Investing", "Activities", "Capital", "Newbuilding", "Newbuildings", "Advances"}
CAPEX_WORDS = PAYMENT_WORDS | ASSET_WORDS | FILLER_WORDS
_WORD = re.compile(r"[A-Z][a-z0-9]*|[A-Z]+(?![a-z])")
OPERATING_TOTAL = re.compile(r"(NetCash.*Operating|CashFlowsFromUsedIn.*Operating)")
INVESTING_TOTAL = re.compile(r"(NetCash.*Investing|CashFlowsFromUsedIn.*Investing)")


@dataclass
class Source:
    """The newest annual filing's parsed main document and what identifies it."""
    doc: object
    accession: str
    form: str
    filed: str
    report_date: str
    url: str


def filing_row(subs, T):
    """The newest annual filing effective by T that names a period and a primary document (facts.latest_annual_period's choice), or None."""
    from qwen_c.value.facts import ANNUAL_FORMS
    rows = [r for r in packet._filing_rows(subs) if r["form"] in ANNUAL_FORMS and r["effective"] and r["effective"] <= T and r.get("report_date")]
    rows = [r for r in rows if r["report_date"] == max(x["report_date"] for x in rows)]
    return max(rows, key=lambda r: (r["accepted"], r["accession"]), default=None) if rows else None


def document_url(cik, row):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{row['accession'].replace('-', '')}/{row['primary_document']}"


def load(cik, subs, T, *, online, root=None):
    """The Source of the newest annual filing, read through sec_store, or None when there is no such filing or its document is not in the store
    (and, offline, cannot be fetched): the readings below are then not made, and the old refusals stand."""
    row = filing_row(subs, T)
    if row is None or not row.get("primary_document"):
        return None
    url = document_url(cik, row)
    try:
        html = sec_store.get(url, online=online, root=root).decode("utf-8", "ignore")
    except (sec_store.StoreError, ValueError):
        return None
    return Source(ixbrl.parse(html), row["accession"], row["form"], row["filed"], row["report_date"], url)


# ---------------------------------------------------------------------------------------------------------------- helpers
def _is_flow(f):
    d = ixbrl.duration_days(f)
    return f.start is not None and d is not None and ANNUAL_DAYS[0] <= d <= ANNUAL_DAYS[1]


def _in_kind(f, kind):
    return _is_flow(f) if kind == "flow" else f.start is None


def _unit_ok(f, unit):
    return f.unit == unit


def _half_unit(dec):
    """Half the unit a figure printed with `decimals` is rounded to (0 when it is exact or the precision is not stated)."""
    return 0.5 * 10.0 ** (-dec) if dec is not None else 0.0


def _coarsest(facts):
    """The decimals of the coarsest-printed of the facts (None when any is exact or states no precision: no rounding is allowed)."""
    ds = [f.decimals for f in facts]
    return None if any(d is None for d in ds) else min(ds)


def _unique(facts):
    """The one value the facts agree on, or None when they differ (a figure stated twice with the same value is one figure)."""
    vals = {f.value for f in facts}
    return next(iter(vals)) if len(vals) == 1 else None


def _prior_end(target, ends):
    """The end among `ends` that closes the fiscal year before `target` (350 to 380 days earlier), or None."""
    from datetime import date
    t = date.fromisoformat(target)
    c = [e for e in ends if ANNUAL_DAYS[0] <= (t - date.fromisoformat(e)).days <= ANNUAL_DAYS[1]]
    return max(c) if c else None


def _value(src, concept, end, start, value, tag, stamp_tag):
    return {"end": end, "start": start, "value": value, "tag": tag, "accn": src.accession, "form": src.form, "filed": src.filed,
            "stamp": f"{STAMP}:{concept}:{src.accession}:{stamp_tag}"}


def _add(out, absent, concept, vals, years):
    d = out.setdefault(concept, {"tags": [], "values": []})
    d["values"] = sorted(d["values"] + vals, key=lambda v: v["end"])[-years:]
    d["tags"] = sorted({v["tag"] for v in d["values"]})
    absent.pop(concept, None)


def _replace(out, absent, concept, vals, keep, years):
    """WO_UV5: the series of `concept` becomes `vals` (read from the filing) plus the feed's own values `keep` (the same concept), the latest `years`."""
    out[concept] = {"tags": [], "values": []}
    _add(out, absent, concept, list(vals) + list(keep), years)


def _same_tag_as(concept, tag, names):
    """Whether the feed's `tag` (a local name, as the facts store it) is the one filed line `names` holds: a single tag, undimensioned, the same name."""
    from qwen_c.value.facts import CONCEPTS, ITEM_SUBSTITUTES
    if len(names) != 1:
        return False
    full = {f"{tax}:{t}" for tax, t, _ in CONCEPTS[concept][1] if t == tag}
    full |= {f"{tax}:{t}" for tax, t, _, _ in ITEM_SUBSTITUTES.get(concept, []) if t == tag}
    return next(iter(names)) in full


# ---------------------------------------------------------------------------------------------------------------- 1. a year not ingested
def fill_new_year(out, absent, src, cf_value, concepts, max_concepts, years):
    """Reading 1. The fiscal year `src.report_date` is the newest annual report and `out` ends earlier. For each concept, the first listed tag
    (the facts' priority; for max_concepts the largest verified value) whose undimensioned fact for that year is read, once the same tag's
    prior-year column agrees with companyfacts' value (cf_value(taxonomy, tag, unit, kind, end)) within the rounding of the printed figure.
    Returns the concepts read."""
    target, done = src.report_date, []
    byname = {}
    for f in src.doc.facts:
        if not f.dims:
            byname.setdefault(f.name, []).append(f)
    for concept, (kind, tags) in concepts.items():
        if target in {v["end"] for v in (out.get(concept) or {}).get("values", [])}:
            continue
        verified = []
        for pri, (tax, tag, unit) in enumerate(tags):
            fs = [f for f in byname.get(f"{tax}:{tag}", []) if _in_kind(f, kind) and _unit_ok(f, unit)]
            cur = [f for f in fs if f.end == target]
            prior = _prior_end(target, {f.end for f in fs})
            if not cur or prior is None:
                continue
            v, p = _unique(cur), _unique([f for f in fs if f.end == prior])
            ref = cf_value(tax, tag, unit, kind, prior)
            if v is None or p is None or ref is None or abs(p - ref) > _half_unit(_coarsest([f for f in fs if f.end == prior])):
                continue
            verified.append((pri, v, cur[0], tax, tag))
        if verified:
            pri, v, f, tax, tag = (max(verified, key=lambda x: (x[1], -x[0])) if concept in max_concepts else min(verified, key=lambda x: x[0]))
            _add(out, absent, concept, [_value(src, concept, target, f.start, v, tag, f"{tax}:{tag}")], years)
            done.append(concept)
    return done


# ---------------------------------------------------------------------------------------------------------------- 2. capital spending
def _words(local):
    return _WORD.findall(local)


def is_capex_tag(name):
    """Whether the tag (prefix:LocalName) names a payment to acquire vessels, property, plant or equipment, by the words of CAPEX_WORDS only."""
    w = _words(name.split(":")[-1])
    s = set(w)
    return bool(w) and s <= CAPEX_WORDS and bool(s & PAYMENT_WORDS) and bool(s & ASSET_WORDS)


def investing_section(doc):
    """[(table, first row, subtotal row)] of every cash-flow table with an investing subtotal after an operating subtotal. The section is the
    rows strictly between the two; its facts are the undimensioned annual ones."""
    inv = [f for f in doc.facts if not f.dims and f.row is not None and INVESTING_TOTAL.search(f.name) and _is_flow(f)]
    out = []
    for t in sorted({f.table for f in inv}):
        ir = min(f.row for f in inv if f.table == t)
        ops = [f.row for f in doc.facts if f.table == t and not f.dims and f.row is not None and f.row < ir and OPERATING_TOTAL.search(f.name) and _is_flow(f)]
        if ops:
            out.append((t, max(ops), ir))
    return out


def _shown(f):
    """The figure's contribution to a subtotal as printed: negative in parentheses, else positive (whatever the tag's sign says)."""
    return -abs(f.value) if f.neg else abs(f.value)


def fill_capex(out, absent, src, keep, note=None):
    """Reading 2. Capital spending, from the fiscal years of the newest filing's cash-flow statement. Used only for a statement where, for each year
    read, (a) every investing line adds to the filed subtotal within the rounding of the printed figures, (b) every capital-spending row has a tagged
    cell for the year (an untagged cell is blank: the year is not read), (c) each such line is printed as a payment (or is a tagged 0), and (d) where
    `out` carries capex for a year the filing shows under the SAME tag as the filing's one line, the two agree within the rounding. It is used only
    where it adds a year `out` lacks. WO_UV5: the series then holds the filing's years only (every pooled year of one concept from one source);
    the feed's years under another tag are dropped, those under the same tag stay. Returns the years read. `keep`: how many fiscal years a series
    keeps. `note`, if given, receives {"capex": {"read": [...], "dropped": [...]}} for the refusal's wording."""
    have = {v["end"]: v for v in (out.get("capex") or {}).get("values", [])}
    for table, lo, hi in investing_section(src.doc):
        rows = {}
        for f in src.doc.facts:
            if f.table == table and f.row is not None and lo < f.row < hi and not f.dims and _is_flow(f):
                rows.setdefault(f.row, []).append(f)
        sub = [f for f in src.doc.facts if f.table == table and f.row == hi and not f.dims and _is_flow(f)]
        cap_rows = {r: fs for r, fs in rows.items() if any(is_capex_tag(f.name) for f in fs)}
        if not cap_rows:
            continue
        years, names_all = {}, set()
        for s in sub:
            col = [f for fs in rows.values() for f in fs if (f.start, f.end) == (s.start, s.end)]
            tol = (len(col) + 1) / 2 * max(_half_unit(f.decimals) * 2 for f in col + [s]) if col else 0.0
            if abs(sum(_shown(f) for f in col) - _shown(s)) > tol:
                continue                                                  # the section does not add up for this year: not read
            cells = {r: [f for f in fs if (f.start, f.end) == (s.start, s.end) and is_capex_tag(f.name)] for r, fs in cap_rows.items()}
            if any(len(c) != 1 for c in cells.values()):
                continue                                                  # a blank cell (or two figures) in a capital-spending row
            cells = {r: c[0] for r, c in cells.items()}
            if any(f.value != 0 and not f.neg for f in cells.values()):
                continue                                                  # a capital-spending line printed as a receipt
            total = sum(abs(f.value) for f in cells.values())
            names_all |= {f.name for f in cells.values()}
            years[s.end] = (s.start, total, sorted({f.name for f in cells.values()}), tol)
        if not years:
            continue
        same = {e: v for e, v in have.items() if _same_tag_as("capex", v["tag"], names_all)}          # the feed's years that are the filing's own line
        if any(e in years and abs(v["value"] - years[e][1]) > years[e][3] for e, v in same.items()):
            continue                                                      # a same-tag figure that disagrees with the filing: the whole reading is rejected
        if not [e for e in years if e not in have]:
            continue
        dropped = sorted(e for e in have if e not in same and e not in years)
        _replace(out, absent, "capex", [_value(src, "capex", e, st, tot, "+".join(n.split(":")[-1] for n in names), "+".join(names))
                                        for e, (st, tot, names, _) in sorted(years.items()) if e not in same], list(same.values()), keep)
        if note is not None:
            note["capex"] = {"read": sorted(years), "dropped": dropped}
        return [e for e in sorted(years) if e not in have]
    return []


# ---------------------------------------------------------------------------------------------------------------- 3. depreciation and amortization with one segment
def fill_da(out, absent, src, excludes, keep, note=None):
    """Reading 3. us-gaap:DepreciationAndAmortization filed only with one dimension member (a company with one reportable segment files its total
    that way). Read when for every earlier year the filing shows that `out` also carries (at least one) the figure, net of the filed amortization,
    equals `out`'s depreciation net of the same amortization (`excludes`: the D&A tags that already exclude amortization) within the rounding of the
    printed figures, and it adds a year `out` lacks. One member only, the same in every year. WO_UV5: the series then holds the filing's years only
    (the feed's years are a different quantity from a segment's total, whatever the arithmetic of the years that were checked). Returns the years read;
    `note` as for fill_capex."""
    name = "us-gaap:DepreciationAndAmortization"
    by_end = {}
    for f in src.doc.facts:
        if f.name == name and f.unit == "USD" and _is_flow(f) and len(f.dims) == 1:
            by_end.setdefault(f.end, []).append(f)
    members = {f.dims for fs in by_end.values() for f in fs}
    if len(members) != 1 or any(_unique(fs) is None for fs in by_end.values()):
        return []
    da = {v["end"]: v for v in (out.get("da") or {}).get("values", [])}
    am = {v["end"]: v["value"] for v in (out.get("amortization") or {}).get("values", [])}
    seen = 0
    for e, fs in by_end.items():
        if e in da and e in am:
            cf_org = da[e]["value"] - (0.0 if da[e]["tag"] in excludes else am[e])
            if abs((_unique(fs) - am[e]) - cf_org) > _half_unit(_coarsest(fs)) * 2:
                return []
            seen += 1
    new = [e for e in by_end if e not in da]
    if not seen or not new:
        return []
    dim = "+".join(f"{a}={m}" for a, m in next(iter(members)))
    _replace(out, absent, "da", [_value(src, "da", e, fs[0].start, _unique(fs), "DepreciationAndAmortization", f"{name}[{dim}]") for e, fs in sorted(by_end.items())], [], keep)
    if note is not None:
        note["da"] = {"read": sorted(by_end), "dropped": sorted(e for e in da if e not in by_end)}
    return sorted(new)


# ---------------------------------------------------------------------------------------------------------------- 4. class-of-stock share counts
def share_candidates(doc, end):
    """The ways the diluted weighted-average share count of the fiscal year `end` can be read from the class-of-stock members, each with the EPS
    it is to be proven against: [{"members": [...], "shares": n, "eps": x}]. A single member with both its shares and its diluted EPS; and the sum
    of every member that files shares, where each of them files the same diluted EPS (a sum has one EPS to answer to). A member without an EPS is
    not a candidate (nothing proves it). Only contexts whose one dimension is the class of stock are read."""
    def by_member(name, unit):
        got = {}
        for f in doc.facts:
            if (f.name == name and f.end == end and _is_flow(f) and f.unit == unit and len(f.dims) == 1 and f.dims[0][0].split(":")[-1] == CLASS_AXIS):
                got.setdefault(f.dims[0][1], []).append(f)
        return {m: _unique(fs) for m, fs in got.items()}
    sh = {m: v for m, v in by_member("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", "shares").items() if v is not None and v > 0}
    eps = {m: v for m, v in by_member("us-gaap:EarningsPerShareDiluted", "USD/shares").items() if v is not None}
    out = [{"members": [m], "shares": sh[m], "eps": eps[m]} for m in sorted(sh) if m in eps and eps[m] != 0]
    if len(sh) > 1 and all(m in eps for m in sh) and len({eps[m] for m in sh}) == 1 and eps[next(iter(sh))] != 0:
        out.append({"members": sorted(sh), "shares": sum(sh.values()), "eps": eps[next(iter(sh))]})
    return out

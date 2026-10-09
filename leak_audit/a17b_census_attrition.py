"""Check 12 (continued): attrition of the census inside the engine - census records by status against the survivors' (differential refusal of the names that left)."""
import gzip, json, collections
from leak_audit import lib
cs, sv = collections.Counter(), collections.Counter()
cs_reason, sv_reason = collections.Counter(), collections.Counter()
for d in lib.DATES:
    with gzip.open(lib.RUN / f"records_{d}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            c = r.get("survivorship") is not None
            key = (r["status"], r.get("mcap_group"))
            (cs if c else sv)[key] += 1
            if r["status"] != "valued":
                (cs_reason if c else sv_reason)[str((r.get("reasons") or [""])[0])[:60]] += 1
def summ(c):
    tot = sum(c.values())
    return {"total": tot, "by_status": {f"{k[0]}|{k[1]}": v for k, v in c.most_common(12)}}
out = {"census": summ(cs), "other_records": summ(sv), "census_top_refusal_reasons": cs_reason.most_common(8), "other_top_refusal_reasons": sv_reason.most_common(8)}
print(json.dumps(out, indent=1))
lib.dump(out, "a17b_census_attrition.json")

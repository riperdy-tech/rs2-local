"""Reproduce the registered H1/H2 on the stored rows with the registered code (999 draws), as the anchor for every variant."""
import time
from leak_audit import lib
t=time.time()
panel=lib.load_panel()
rows=lib.load_rows(panel)
print(len(rows), time.time()-t)
sc=lib.key_map(panel,"s_cfg")
fn=lambda r: sc.get(r["_k"])
res=lib.bars(rows, fn, n_boot=999)
print(lib.fmt(res), time.time()-t)
res0=lib.bars(rows, fn, n_boot=0)
print(lib.fmt(res0), time.time()-t)
lib.dump({"baseline_999":res,"baseline_point":res0},"a00_baseline.json")

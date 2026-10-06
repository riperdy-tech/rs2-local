"""Backtest registration sections 4.9, 5, 12: the extractor's universe, the labels, and the census universe.

Reads today's screener labels (stocks.json symbols, cik_map.json, stocks.csv sector, financials/<T>.json FX flag) and the
167-name exclusion list.  The 167 names are used only as a set to exclude: neither the names nor any company of theirs
(any ticker sharing a CIK) is written to any output, and nothing here prints a name.  Only counts are printed.

Writes under --out-dir:
  stocks_ex167.json       [{"symbol": ...}] for the extractor (symbols without '.', the 167 and their companies removed)
  labels.json             {ticker: {"cik", "sector", "fx"}} for the kept symbols ("fx" is the screener FX flag; null = USD)
  stocks_census.json / cik_map_census.json   pseudo-tickers "C<cik>" for every company in the zip that no kept symbol covers
                          (and that is not an excluded company), for the survivorship census.  Counts only are ever reported.
"""
import argparse
import csv
import json
import zipfile
from pathlib import Path


def read_json(p):
    with open(p, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screener-data", required=True, type=Path)
    ap.add_argument("--untouched", required=True, type=Path)
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    sd = a.screener_data
    stocks = read_json(sd / "stocks.json")
    cik_map = read_json(sd / "cik_map.json")["map"]
    untouched = {l.strip().upper() for l in a.untouched.read_text(encoding="utf-8").splitlines() if l.strip()}
    symbols = [s["symbol"] for s in stocks if s.get("symbol") and "." not in s["symbol"]]
    ex_tickers = {t for t in symbols if t.upper() in untouched}
    ex_ciks = {cik_map[t] for t in untouched if t in cik_map} | {cik_map[t] for t in ex_tickers if t in cik_map}
    kept = [t for t in symbols if t not in ex_tickers and cik_map.get(t) not in ex_ciks]
    sector = {}
    with open(sd / "stocks.csv", "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        sc = next(c for c in r.fieldnames if c.lower() == "sector")
        syc = next(c for c in r.fieldnames if c.lower() == "symbol")
        for row in r:
            sym = (row.get(syc) or "").upper()
            if sym:
                sector[sym] = row.get(sc)
    labels, no_fin = {}, 0
    for t in kept:
        p = sd / "financials" / f"{t}.json"
        fx, has = None, True
        try:
            fin = read_json(p)
            fx = fin.get("FX")
        except (OSError, json.JSONDecodeError):
            has, no_fin = False, no_fin + 1
        labels[t] = {"cik": cik_map.get(t), "sector": sector.get(t.upper()), "fx": fx, "has_financials_file": has}
    (a.out_dir / "stocks_ex167.json").write_text(json.dumps([{"symbol": t} for t in kept]), encoding="utf-8")
    (a.out_dir / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    zip_ciks = {i.filename[3:13] for i in zipfile.ZipFile(a.zip).infolist() if i.filename.startswith("CIK") and i.filename.endswith(".json")}
    kept_ciks = {cik_map[t] for t in kept if t in cik_map}
    census = sorted(zip_ciks - kept_ciks - ex_ciks)
    (a.out_dir / "stocks_census.json").write_text(json.dumps([{"symbol": f"C{c}"} for c in census]), encoding="utf-8")
    (a.out_dir / "cik_map_census.json").write_text(json.dumps({"map": {f"C{c}": c for c in census}}), encoding="utf-8")
    print(f"symbols without '.': {len(symbols)}; excluded tickers: {len(ex_tickers)} (list size {len(untouched)}); "
          f"excluded companies (CIKs): {len(ex_ciks)}; kept symbols: {len(kept)}; kept with a CIK: {sum(1 for t in kept if t in cik_map)}; "
          f"no financials file: {no_fin}; zip companies: {len(zip_ciks)}; census companies: {len(census)}")
    print("untouched tickers present in cik_map:", sum(1 for t in untouched if t in cik_map), "of", len(untouched))


if __name__ == "__main__":
    main()

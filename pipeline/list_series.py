"""
List every Kalshi series in a category with total volume and fee type, sorted by volume.
Standard library only.

    python3 pipeline/list_series.py              # Sports (default)
    python3 pipeline/list_series.py --category Sports --top 60

Output: series_<category>.csv  (ticker, title, volume, fee_type, fee_multiplier, frequency, tags)
fee_type 'quadratic' means makers pay no fee; 'quadratic_with_maker_fees' means they do.
"""
import argparse
import csv
import json
import urllib.parse
import urllib.request

BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]


def get(path, params):
    last = None
    for base in BASES:
        try:
            url = base + path + "?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
    raise RuntimeError(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="Sports")
    ap.add_argument("--top", type=int, default=50)
    a = ap.parse_args()
    data = get("/series", {"category": a.category, "include_volume": "true"})
    rows = []
    for s in data.get("series", []):
        try:
            vol = float(s.get("volume_fp") or s.get("volume") or 0)
        except ValueError:
            vol = 0.0
        rows.append({"ticker": s.get("ticker", ""), "title": s.get("title", ""), "volume": vol,
                     "fee_type": s.get("fee_type", ""), "fee_multiplier": s.get("fee_multiplier", ""),
                     "frequency": s.get("frequency", ""), "tags": "|".join(s.get("tags") or [])})
    rows.sort(key=lambda r: -r["volume"])
    out = f"series_{a.category.lower().replace(' ', '_')}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()) if rows else ["ticker"])
        w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} series in '{a.category}', saved to {out}\n")
    print(f"{'ticker':32s} {'volume (M)':>11s}  {'fee_type':28s} title")
    for r in rows[:a.top]:
        print(f"{r['ticker']:32s} {r['volume']/1e6:11.1f}  {r['fee_type']:28s} {r['title'][:50]}")


if __name__ == "__main__":
    main()

"""Market-maker backtest on Kalshi tennis trades.
For every trade, the maker is the person whose resting order got hit. We measure the maker's P&L
per contract at +1/+5/+15/+60 minutes (vs the mid price) and at settlement.
Positive = providing liquidity made money after getting run over by price moves.
Streams the big trades file in chunks (low memory). Writes maker_summary.txt.
usage: python3 maker_test.py bt_trades.csv bt_candles.csv bt_markets.csv
"""
import sys
import numpy as np
import pandas as pd

trades_path, cand_path, mkt_path = sys.argv[1:4]
import os, pickle
OUT_PKL = sys.argv[4] if len(sys.argv) > 4 else None
CACHE = os.path.join(os.path.dirname(os.path.abspath(OUT_PKL or "x")), "book_cache.pkl")
TOUR = {"KXITFMATCH": "ITF men", "KXITFWMATCH": "ITF women", "KXATPMATCH": "ATP",
        "KXATPCHALLENGERMATCH": "Challenger", "KXWTAMATCH": "WTA"}
H = [1, 5, 15, 60]

m = pd.read_csv(mkt_path, usecols=["ticker", "result", "close_time"]).drop_duplicates("ticker").set_index("ticker")
res = (m.result == "yes").astype(float).to_dict()
month = pd.to_datetime(m.close_time, utc=True).dt.strftime("%Y-%m").to_dict()

if os.path.exists(CACHE):
    book = pickle.load(open(CACHE, "rb"))
else:
  print("loading candles...", flush=True)
  c = pd.read_csv(cand_path, usecols=["ticker", "end_ts", "bid", "ask", "volume"],
                  dtype={"ticker": "category", "end_ts": "int64", "bid": "float32", "ask": "float32", "volume": "float32"})
  c = c.dropna(subset=["bid", "ask"]).sort_values(["ticker", "end_ts"]).drop_duplicates(["ticker", "end_ts"], keep="last")
  book = {}
  for t, g in c.groupby("ticker", observed=True):
      ts = g.end_ts.values
      mid = ((g.bid.values + g.ask.values) / 2).astype("float64")
      spr = (g.ask.values - g.bid.values).astype("float64")
      # in-play start (same heuristic as before) on a 1-min grid
      full = pd.DataFrame({"mid": mid, "spr": spr, "vol": g.volume.values}, index=ts)
      grid = np.arange(ts[0], ts[-1] + 60, 60)
      f = full.reindex(grid)
      f[["mid", "spr"]] = f[["mid", "spr"]].ffill()
      f["vol"] = f.vol.fillna(0)
      act = (f.vol > 0).astype(int)
      fa = act[::-1].rolling(10, min_periods=1).sum()[::-1]
      fm = f.mid.diff().abs()[::-1].rolling(10, min_periods=1).max()[::-1]
      ok = ((fa >= 5) & (fm >= 0.03) & (f.spr <= 0.15)).values
      start = grid[np.argmax(ok)] if ok.any() else None
      book[t] = (ts, mid, spr, start)
  del c
  pickle.dump(book, open(CACHE, "wb"))
print(f"candles for {len(book)} markets", flush=True)

agg = {}


def add(key, w, cols):
    a = agg.setdefault(key, np.zeros(len(cols) + 1))
    a[0] += w.sum()
    for i, v in enumerate(cols):
        a[i + 1] += np.nansum(w * v)


COLS = ["edge0"] + [f"m{h}" for h in H] + ["settle", "fee"]
n = 0
for chunk in pd.read_csv(trades_path, chunksize=2_000_000,
                         usecols=["ticker", "created_time", "yes_price", "count", "taker_outcome_side"]):
    chunk = chunk.dropna(subset=["yes_price", "count"])
    chunk["t"] = pd.to_datetime(chunk.created_time, utc=True, format="ISO8601").astype("int64") // 10**9
    for t, g in chunk.groupby("ticker"):
        if t not in book or t not in res:
            continue
        ts, mid, spr, start = book[t]
        tt = g.t.values
        p = g.yes_price.values.astype(float)
        w = g["count"].values.astype(float)
        sgn = np.where(g.taker_outcome_side.values == "yes", -1.0, 1.0)  # maker is long YES when taker bought NO
        i0 = np.searchsorted(ts, tt, side="right") - 1
        valid = i0 >= 0
        if not valid.any():
            continue
        i0c = np.clip(i0, 0, len(ts) - 1)
        mid0 = mid[i0c]
        vals = [sgn * (mid0 - p)]  # spread captured vs mid at the time
        for h in H:
            j = np.clip(np.searchsorted(ts, tt + h * 60, side="right") - 1, 0, len(ts) - 1)
            vals.append(sgn * (mid[j] - p))
        vals.append(sgn * (res[t] - p))
        vals.append(0.0175 * p * (1 - p))  # maker fee where charged (25% of taker)
        vals = [np.where(valid, v, np.nan) for v in vals]
        tour = TOUR.get(t.split("-")[0], t.split("-")[0])
        phase = np.where(start is None, "unknown", np.where(tt < (start or 0), "pre-match", "in-play"))
        pb = np.digitize(p, [0.1, 0.25, 0.5, 0.75, 0.9])
        pb_lbl = np.array(["<10c", "10-25c", "25-50c", "50-75c", "75-90c", ">90c"])[pb]
        sz = np.array(["<10", "10-100", "100-1000", "1000+"])[np.digitize(w, [10, 100, 1000])]
        mo = month.get(t, "?")
        df = pd.DataFrame({"ph": phase, "pb": pb_lbl, "sz": sz})
        for k, idx in df.groupby(["ph", "pb", "sz"]).indices.items():
            ww = w[idx]; vv = [v[idx] for v in vals]
            for key in (("ALL",), ("tour", tour), ("phase", k[0]), ("tour x phase", tour, k[0]),
                        ("price", k[1]), ("taker size", k[2]), ("month", mo)):
                add(key, ww, vv)
    n += len(chunk)
    print(f"  processed {n:,} trades", flush=True)

if OUT_PKL:
    pickle.dump(agg, open(OUT_PKL, "wb"))
    print("saved", OUT_PKL)
    sys.exit(0)
rows = []
for k, a in agg.items():
    r = {"group": " | ".join(map(str, k)), "contracts": a[0]}
    for i, cname in enumerate(COLS):
        r[cname] = a[i + 1] / a[0] * 100  # cents per contract
    rows.append(r)
out = pd.DataFrame(rows).sort_values("group")
out["settle_net_fee"] = out.settle - out.fee
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)
txt = ("Maker P&L in CENTS PER CONTRACT, contract-weighted.\n"
       "edge0 = spread captured vs mid at fill. mH = P&L marked to mid H minutes later. settle = held to result.\n"
       "fee = maker fee if the series charges one (0.0175*p*(1-p)); many tennis series charge makers 0.\n\n"
       + out.round(3).to_string(index=False))
open("maker_summary.txt", "w").write(txt)
print(txt)

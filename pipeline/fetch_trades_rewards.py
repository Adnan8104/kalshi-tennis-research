"""
Download (1) every trade on the tennis markets in bt_markets.csv and (2) Kalshi's liquidity
reward programs, to backtest a market-making bot. Standard library only, resumable.

Run in the same folder as bt_markets.csv (after fetch_all_tennis.py has finished):
    python3 fetch_trades_rewards.py

Outputs:
    bt_trades.csv       every trade: time, price, size, which side was the taker
    bt_incentives.csv   liquidity reward programs (all statuses)
"""
import csv
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]
WORKERS = 4
TRADE_FILE, INC_FILE, DONE_FILE = "bt_trades.csv", "bt_incentives.csv", "bt_trades_done.txt"
TRADE_COLS = ["ticker", "created_time", "yes_price", "count", "taker_outcome_side", "taker_book_side", "taker_side"]
lock = threading.Lock()


def get(path, params=None):
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    last = None
    for base in BASES:
        for attempt in range(6):
            try:
                req = urllib.request.Request(base + path + query, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (400, 404):
                    break
                time.sleep(min(2 ** attempt, 20) if e.code == 429 else 1)
            except Exception as e:
                last = e
                time.sleep(1 + attempt)
    raise RuntimeError(f"{path}: {last}")


def pages(path, params, key):
    cursor = ""
    while True:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        data = get(path, p)
        for row in data.get(key, []):
            yield row
        cursor = data.get("cursor") or data.get("next_cursor") or ""
        if not cursor:
            break


def trades_for(ticker):
    for path in ("/markets/trades", "/historical/trades"):
        try:
            rows = list(pages(path, {"ticker": ticker, "limit": 1000}, "trades"))
        except RuntimeError:
            continue
        if rows:
            out = []
            for t in rows:
                price = t.get("yes_price_dollars", t.get("yes_price"))
                try:
                    price = float(price)
                    price = price / 100 if price > 1.0001 else price
                except (TypeError, ValueError):
                    price = ""
                out.append({"ticker": ticker, "created_time": t.get("created_time", ""), "yes_price": price,
                            "count": t.get("count_fp", t.get("count", "")),
                            "taker_outcome_side": t.get("taker_outcome_side", ""),
                            "taker_book_side": t.get("taker_book_side", ""), "taker_side": t.get("taker_side", "")})
            return out
    return []


def main():
    # 1) reward programs
    try:
        progs = list(pages("/incentive_programs", {"status": "all", "type": "liquidity", "limit": 10000}, "incentive_programs"))
        if progs:
            keys = sorted({k for p in progs for k in p})
            with open(INC_FILE, "w", newline="") as f:
                w = csv.DictWriter(f, keys); w.writeheader(); w.writerows(progs)
        print(f"reward programs saved: {len(progs)}")
    except RuntimeError as e:
        print(f"reward programs failed: {e}")

    # 2) trades
    with open("bt_markets.csv", newline="") as f:
        tickers = [r["ticker"] for r in csv.DictReader(f)]
    done = set(open(DONE_FILE).read().split()) if os.path.exists(DONE_FILE) else set()
    todo = [t for t in tickers if t not in done]
    print(f"{len(tickers)} markets, {len(todo)} still to download")
    new = not os.path.exists(TRADE_FILE)
    tf, df = open(TRADE_FILE, "a", newline=""), open(DONE_FILE, "a")
    w = csv.DictWriter(tf, TRADE_COLS)
    if new:
        w.writeheader()
    n, t0 = 0, time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(trades_for, t): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"  {t}: {e}")
                continue
            with lock:
                w.writerows(rows)
                df.write(t + "\n")
                n += 1
                if n % 100 == 0 or n == len(todo):
                    tf.flush(); df.flush()
                    rate = n / max(time.time() - t0, 1)
                    print(f"  {n}/{len(todo)} done (~{(len(todo) - n) / rate / 60:.0f} min left)")
    tf.close(); df.close()
    print(f"Finished. Files: {TRADE_FILE}, {INC_FILE}")


if __name__ == "__main__":
    main()

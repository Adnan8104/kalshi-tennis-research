"""
Download 1-minute price history for EVERY settled Kalshi tennis singles match since a date,
so we can backtest the "fade the drop after it settles" rule on thousands of matches.

Standard library only. Resumable: rerun the same command and it skips matches already saved.

Usage:
    python3 fetch_all_tennis.py                 # default: matches since 2026-06-01
    python3 fetch_all_tennis.py --since 2026-01-01

Outputs (current folder):
    bt_markets.csv   one row per match (one side's market; the other side is the mirror)
    bt_candles.csv   1-minute bid/ask/last/volume for each match
"""
import argparse
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASES = ["https://api.elections.kalshi.com/trade-api/v2", "https://external-api.kalshi.com/trade-api/v2"]
SERIES = ["KXITFMATCH", "KXITFWMATCH", "KXATPMATCH", "KXWTAMATCH", "KXATPCHALLENGERMATCH"]
WINDOW_HOURS = 12      # candles pulled for the 12h before the market closed (pre-match + match)
WORKERS = 4
MKT_FILE, CANDLE_FILE = "bt_markets.csv", "bt_candles.csv"
MKT_COLS = ["ticker", "event_ticker", "series", "title", "yes_sub_title", "close_time", "result", "rules_primary"]
CANDLE_COLS = ["ticker", "end_ts", "bid", "ask", "price_close", "volume"]
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
                if e.code == 404:
                    break
                time.sleep(min(2 ** attempt, 20) if e.code == 429 else 1)
            except Exception as e:
                last = e
                time.sleep(1 + attempt)
    raise RuntimeError(f"{path}: {last}")


def ts(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def paginate(path, params):
    cursor = ""
    while True:
        p = dict(params, limit=1000)
        if cursor:
            p["cursor"] = cursor
        data = get(path, p)
        for m in data.get("markets", []):
            yield m
        cursor = data.get("cursor") or ""
        if not cursor:
            break


def list_markets(series, since_ts):
    found = {}
    try:
        for m in paginate("/markets", {"series_ticker": series, "status": "settled", "min_settled_ts": since_ts}):
            found[m["ticker"]] = (m, False)
    except RuntimeError as e:
        print(f"  live list failed for {series}: {e}")
    try:
        for m in paginate("/historical/markets", {"series_ticker": series}):
            if m.get("close_time") and ts(m["close_time"]) >= since_ts:
                found.setdefault(m["ticker"], (m, True))
    except RuntimeError as e:
        print(f"  historical list failed for {series}: {e}")
    # one market per match: the other player's market is the mirror image
    per_event = {}
    for t in sorted(found):
        m, hist = found[t]
        if m.get("result") not in ("yes", "no"):
            continue
        per_event.setdefault(m.get("event_ticker", t), (m, hist))
    return list(per_event.values())


def num(x):
    if x in (None, ""):
        return ""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return round(v / 100, 4) if v > 1.0001 else v


def field(c, group, key="close"):
    g = c.get(group) or {}
    return num(g.get(key, g.get(f"{key}_dollars")))


def fetch_one(m, hist, series):
    t = m["ticker"]
    end = ts(m["close_time"])
    start = end - WINDOW_HOURS * 3600
    paths = [f"/historical/markets/{t}/candlesticks", f"/series/{series}/markets/{t}/candlesticks"]
    if not hist:
        paths.reverse()
    for p in paths:
        try:
            data = get(p, {"start_ts": start, "end_ts": end, "period_interval": 1})
        except RuntimeError:
            continue
        cs = data.get("candlesticks", [])
        if cs:
            return [{"ticker": t, "end_ts": c.get("end_period_ts"), "bid": field(c, "yes_bid"),
                     "ask": field(c, "yes_ask"), "price_close": field(c, "price"),
                     "volume": c.get("volume", c.get("volume_fp", ""))} for c in cs]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-06-01")
    args = ap.parse_args()
    since_ts = int(datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc).timestamp())

    done = set()
    if os.path.exists(MKT_FILE):
        with open(MKT_FILE, newline="") as f:
            done = {r["ticker"] for r in csv.DictReader(f)}
    new_files = not os.path.exists(MKT_FILE)
    mf = open(MKT_FILE, "a", newline="")
    cf = open(CANDLE_FILE, "a", newline="")
    mw, cw = csv.DictWriter(mf, MKT_COLS), csv.DictWriter(cf, CANDLE_COLS)
    if new_files:
        mw.writeheader(); cw.writeheader()

    todo = []
    for s in SERIES:
        ms = list_markets(s, since_ts)
        left = [(m, h, s) for m, h in ms if m["ticker"] not in done]
        print(f"{s}: {len(ms)} settled matches since {args.since}, {len(left)} still to download")
        todo.extend(left)

    n = 0
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(fetch_one, m, h, s): (m, s) for m, h, s in todo}
        for fut in as_completed(futs):
            m, s = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"  {m['ticker']}: {e}")
                continue
            with lock:
                cw.writerows(rows)
                mw.writerow({"ticker": m["ticker"], "event_ticker": m.get("event_ticker", ""), "series": s,
                             "title": m.get("title", ""), "yes_sub_title": m.get("yes_sub_title", ""),
                             "close_time": m.get("close_time", ""), "result": m.get("result", ""),
                             "rules_primary": m.get("rules_primary", "")})
                n += 1
                if n % 50 == 0 or n == len(todo):
                    mf.flush(); cf.flush()
                    rate = n / max(time.time() - t0, 1)
                    print(f"  {n}/{len(todo)} done (~{(len(todo) - n) / rate / 60:.0f} min left)")
    mf.close(); cf.close()
    print(f"Finished. Files: {MKT_FILE}, {CANDLE_FILE}")


if __name__ == "__main__":
    main()

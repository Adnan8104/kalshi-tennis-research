"""
Pull market info + 1-minute price history for every tennis market in your Kalshi
realized P&L export. Uses Kalshi's public market-data endpoints (no API key needed).

Usage:
    python3 pull_kalshi_tennis.py realized_pnl_2026-01-01_2027-01-01.csv

Outputs (in the current folder):
    tennis_markets.csv  one row per market: title, players, tournament, open/close, result
    tennis_candles.csv  1-minute candles: bid/ask/last price and volume
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASES = [
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://external-api.kalshi.com/trade-api/v2",
]
TENNIS_SERIES = {
    "KXITFMATCH", "KXITFWMATCH", "KXITFDOUBLES", "KXWTAMATCH",
    "KXATPMATCH", "KXATPCHALLENGERMATCH",
}
CHUNK_SECONDS = 6 * 3600  # request candles in 6-hour windows


def get(path, params=None):
    """GET a JSON path, trying each base URL, with a few retries."""
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    last_err = None
    for base in BASES:
        for attempt in range(4):
            try:
                req = urllib.request.Request(base + path + query, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 404:
                    break  # not on this endpoint / base, try next
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                time.sleep(1)
            except Exception as e:  # network hiccup
                last_err = e
                time.sleep(1)
    raise RuntimeError(f"{path}: {last_err}")


def iso_to_ts(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def fetch_market(ticker):
    for path in (f"/historical/markets/{ticker}", f"/markets/{ticker}"):
        try:
            data = get(path)
            return data.get("market", data), path.startswith("/historical")
        except RuntimeError:
            continue
    return None, False


def fetch_candles(ticker, series, start, end, historical):
    paths = [f"/historical/markets/{ticker}/candlesticks", f"/series/{series}/markets/{ticker}/candlesticks"]
    if not historical:
        paths.reverse()
    for path in paths:
        out = []
        try:
            t = start
            while t < end:
                t2 = min(t + CHUNK_SECONDS, end)
                data = get(path, {"start_ts": t, "end_ts": t2, "period_interval": 1})
                out.extend(data.get("candlesticks", []))
                t = t2
                time.sleep(0.15)
            if out:
                return out
        except RuntimeError:
            continue
    return []


def val(x):
    """Candle fields can be dollar strings, cent ints, or nested dicts; return dollars as float."""
    if x is None or x == "":
        return ""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return v / 100 if v > 1.0001 else v


def pick(c, group, field):
    g = c.get(group) or {}
    for key in (field, f"{field}_dollars"):
        if key in g:
            return val(g[key])
    return ""


def main(path):
    tickers = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = row.get("market_ticker") or ""
            if t and t.split("-")[0] in TENNIS_SERIES and t not in tickers:
                tickers.append(t)
    print(f"{len(tickers)} tennis markets found")

    mrows, crows = [], []
    for i, t in enumerate(tickers, 1):
        series = t.split("-")[0]
        m, historical = fetch_market(t)
        if not m:
            print(f"[{i}/{len(tickers)}] {t}: market info not found, skipping")
            continue
        mrows.append({
            "ticker": t, "event_ticker": m.get("event_ticker", ""), "title": m.get("title", ""),
            "yes_sub_title": m.get("yes_sub_title", ""), "open_time": m.get("open_time", ""),
            "close_time": m.get("close_time", ""), "result": m.get("result", ""),
            "rules_primary": m.get("rules_primary", ""),
        })
        start = iso_to_ts(m["open_time"]) if m.get("open_time") else None
        end = iso_to_ts(m["close_time"]) if m.get("close_time") else None
        if not (start and end):
            continue
        candles = fetch_candles(t, series, start, end, historical)
        for c in candles:
            price = c.get("price") or {}
            crows.append({
                "ticker": t, "end_ts": c.get("end_period_ts"),
                "yes_bid_close": pick(c, "yes_bid", "close"), "yes_ask_close": pick(c, "yes_ask", "close"),
                "price_close": pick(c, "price", "close"), "price_mean": pick(c, "price", "mean"),
                "price_high": pick(c, "price", "high"), "price_low": pick(c, "price", "low"),
                "volume": c.get("volume", c.get("volume_fp", "")),
            })
        print(f"[{i}/{len(tickers)}] {t}: {len(candles)} candles")

    with open("tennis_markets.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(mrows[0].keys()) if mrows else ["ticker"])
        w.writeheader(); w.writerows(mrows)
    with open("tennis_candles.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(crows[0].keys()) if crows else ["ticker"])
        w.writeheader(); w.writerows(crows)
    print(f"Done: tennis_markets.csv ({len(mrows)} markets), tennis_candles.csv ({len(crows)} candles)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 pull_kalshi_tennis.py <realized_pnl_csv>")
    main(sys.argv[1])

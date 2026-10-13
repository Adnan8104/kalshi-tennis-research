"""Backtest 'fade the drop after it settles' on Kalshi tennis 1-min candles.

usage: backtest.py candles.csv markets.csv out_trades.csv
Accepts either column naming (bid/ask or yes_bid_close/yes_ask_close).
Entry uses the NEXT minute's quote after the signal (no lookahead). Hold to settlement
unless a take-profit variant is chosen. Fixed $10 stake per trade, Kalshi taker fee
ceil(0.07*C*P*(1-P)) to the cent, maker fee assumed 0 (optimistic).
"""
import math
import re
import sys
import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 300)

cand_path, mkt_path, out_path = sys.argv[1:4]
c = pd.read_csv(cand_path).rename(columns={"yes_bid_close": "bid", "yes_ask_close": "ask"})
m = pd.read_csv(mkt_path)
m = m.drop_duplicates("ticker").set_index("ticker")
STAKE = 10.0


def fee(contracts, p):
    return math.ceil(0.07 * contracts * p * (1 - p) * 100 - 1e-9) / 100


def meta(t):
    r = m.loc[t]
    s = t.split("-")[0]
    rp = str(r.get("rules_primary", ""))
    mm = re.search(r"in the 2026 (.+?) (Round [Oo]f \d+|Quarterfinal|Semifinal|Final|Qualif)", rp)
    tour = mm.group(1) if mm else ""
    if s == "KXATPMATCH": level = "ATP"
    elif s == "KXWTAMATCH": level = "WTA"
    elif s == "KXATPCHALLENGERMATCH": level = "Challenger"
    else:
        lv = re.match(r"([MW]\d+)", tour)
        level = lv.group(1) if lv else "ITF other"
    gender = "W" if s in ("KXITFWMATCH", "KXWTAMATCH") or level.startswith("W") else "M"
    return level, gender


def grid(g):
    g = g.sort_values("end_ts").drop_duplicates("end_ts", keep="last")
    g = g[(g.bid.notna()) & (g.ask.notna())]
    if len(g) < 20:
        return None
    idx = pd.to_datetime(g.end_ts, unit="s", utc=True)
    s = pd.DataFrame({"bid": g.bid.values, "ask": g.ask.values, "vol": g.volume.fillna(0).values}, index=idx)
    full = s.reindex(pd.date_range(idx.min(), idx.max(), freq="1min"))
    full[["bid", "ask"]] = full[["bid", "ask"]].ffill()
    full["vol"] = full.vol.fillna(0)
    return full.dropna()


def inplay_start(full):
    mid = (full.bid + full.ask) / 2
    active = (full.vol > 0).astype(int)
    fa = active[::-1].rolling(10, min_periods=1).sum()[::-1]
    fm = mid.diff().abs()[::-1].rolling(10, min_periods=1).max()[::-1]
    ok = (fa >= 5) & (fm >= 0.03) & ((full.ask - full.bid) <= 0.15)
    return int(np.argmax(ok.values)) if ok.any() else None


def simulate(bid, ask, start, result, drop, mode, cap, tp, lo=0.05):
    """bid/ask arrays for ONE player. returns trade dict or None."""
    mid = (bid + ask) / 2
    pre = mid[start - 1] if start > 0 else mid[0]
    n = len(mid)
    trig = None
    for i in range(start + 1, n - 2):
        if trig is None and mid[i] <= pre - drop:
            trig = i
        if trig is None:
            continue
        if mode == "settled":
            ok = (mid[i] - mid[max(i - 15, 0)] > -0.05) and (mid[i] >= mid[i - 1])
        elif mode == "knife":
            ok = True
        else:
            ok = True
        if not ok:
            continue
        j = i + 1  # execute next minute
        a, b = ask[j], bid[j]
        if not (lo <= a <= cap) or (a - b) > 0.06:
            if mode == "knife":
                return None
            continue
        if mid[j] > pre - drop / 2:  # recovered most of the way before we got in; skip
            return None
        out = {"i": j, "pre": pre, "entry_ask": a, "entry_bid": b, "minutes_in": j - start}
        # exits
        exit_px, exit_kind = result, "settle"
        if tp:
            for k in range(j + 1, n):
                if bid[k] >= a + tp:
                    exit_px, exit_kind = bid[k], "tp"
                    break
        out["exit_px"], out["exit_kind"] = exit_px, exit_kind
        return out
    return None


rng = np.random.default_rng(3)
trades = []
VARIANTS = []
for drop in (0.10, 0.15, 0.20, 0.25):
    VARIANTS.append(("settled", drop, 0.80, None))
VARIANTS += [("knife", 0.15, 0.80, None), ("settled", 0.15, 0.80, 0.10), ("settled", 0.15, 0.95, None)]
VARIANTS = [(mo, d, cap, tp, 0.05) for mo, d, cap, tp in VARIANTS]
VARIANTS += [("settled", 0.15, 0.65, None, 0.20), ("knife", 0.15, 0.65, None, 0.20)]

n_match = 0
for t, g in c.groupby("ticker"):
    if t not in m.index or m.loc[t, "result"] not in ("yes", "no"):
        continue
    full = grid(g)
    if full is None:
        continue
    st = inplay_start(full)
    if st is None or st < 5 or st > len(full) - 30:
        continue
    n_match += 1
    level, gender = meta(t)
    res_yes = 1.0 if m.loc[t, "result"] == "yes" else 0.0
    close_day = full.index[-1].tz_convert("America/New_York").date()
    bid, ask = full.bid.values, full.ask.values
    sides = {"yes": (bid, ask, res_yes), "no": (1 - ask, 1 - bid, 1 - res_yes)}
    # baseline: buy each side at a random in-play minute
    for side, (b, a, r) in sides.items():
        k = rng.integers(st + 1, len(full) - 2)
        if 0.05 <= a[k] <= 0.80 and a[k] - b[k] <= 0.06:
            trades.append({"ticker": t, "side": side, "variant": "baseline random in-play", "entry_ask": a[k], "entry_bid": b[k],
                           "exit_px": r, "exit_kind": "settle", "pre": (b[st - 1] + a[st - 1]) / 2, "minutes_in": k - st,
                           "level": level, "gender": gender, "day": close_day})
    for mode, drop, cap, tp, lo in VARIANTS:
        name = f"{mode} drop>={int(drop*100)}c cap{int(cap*100)}" + (f" min{int(lo*100)}" if lo > 0.05 else "") + (f" tp+{int(tp*100)}c" if tp else "")
        for side, (b, a, r) in sides.items():
            tr = simulate(b, a, st, r, drop, mode, cap, tp, lo)
            if tr:
                tr.update({"ticker": t, "side": side, "variant": name, "level": level, "gender": gender, "day": close_day})
                trades.append(tr)

x = pd.DataFrame(trades)


def pnl(row, maker):
    p = row.entry_bid if maker else row.entry_ask
    p = max(p, 0.01)
    C = STAKE / p
    f_in = 0 if maker else fee(C, p)
    f_out = fee(C, row.exit_px) if row.exit_kind == "tp" else 0
    return C * (row.exit_px - p) - f_in - f_out


x["pnl_taker"] = x.apply(lambda r: pnl(r, False), axis=1)
x["pnl_maker"] = x.apply(lambda r: pnl(r, True), axis=1)
x["win"] = x.exit_px > x.entry_ask
x.to_csv(out_path, index=False)


def boot(d, col):
    g = d.groupby("ticker")[col].sum().values
    if len(g) < 5:
        return np.nan, np.nan, np.nan
    b = np.array([g[rng.integers(0, len(g), len(g))].sum() for _ in range(3000)]) / (STAKE * len(d))
    return np.percentile(b, 2.5), np.percentile(b, 97.5), (b > 0).mean()


def table(d, by):
    rows = []
    for k, s in d.groupby(by, observed=True):
        lo, hi, p = boot(s, "pnl_taker")
        rows.append({by if isinstance(by, str) else "group": k, "trades": len(s), "matches": s.ticker.nunique(),
                     "win%": s.win.mean(), "avg_entry": s.entry_ask.mean(),
                     "roi_taker": s.pnl_taker.sum() / (STAKE * len(s)), "CI_lo": lo, "CI_hi": hi, "P(>0)": p,
                     "roi_maker*": s.pnl_maker.sum() / (STAKE * len(s))})
    return pd.DataFrame(rows).round(3)


print(f"matches usable: {n_match}  date range: {x.day.min()} to {x.day.max()}")
print("roi = return per $ staked, held to settlement unless tp. CI/P(>0) = match-level bootstrap on taker roi.")
print("maker* assumes you get filled at the bid with no fee: optimistic upper bound.\n")
print(table(x, "variant").to_string(index=False))

x["period"] = np.where(pd.to_datetime(x.day) < pd.Timestamp("2026-09-01"), "1 train Jun-Aug", "2 test Sep-Oct")
for per, d in x.groupby("period"):
    for gen, dd in d.groupby("gender"):
        print(f"\n===== {per} | {gen} =====")
        print(table(dd, "variant").to_string(index=False))
main = x[x.variant == "settled drop>=15c cap80"].copy()
if len(main):
    main["month"] = pd.to_datetime(main.day).dt.to_period("M").astype(str)
    main["entry_bucket"] = pd.cut(main.entry_ask, [0, .2, .35, .5, .65, .8])
    main["pre_role"] = np.where(main.pre >= 0.5, "dropped player was pre-match fav", "dropped player was pre-match dog")
    main["when"] = pd.cut(main.minutes_in, [0, 30, 60, 90, 1e9], labels=["0-30m", "30-60m", "60-90m", "90m+"])
    for by in ["month", "gender", "level", "pre_role", "entry_bucket", "when"]:
        print(f"\n--- main rule (settled, 15c, cap 80c) by {by} ---")
        print(table(main, by).to_string(index=False))

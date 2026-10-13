"""Swing test: after the drop signal, does the price bounce enough to sell for a profit?
No holding to settlement. Buy at the ask, sell at the bid (taker both ways, fees both ways),
or the maker version: buy at the bid, sell at the ask, no fees (optimistic upper bound).
"""
import math
import sys
import numpy as np
import pandas as pd

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2], "/dev/null"]
src = open(sys.argv[0].replace("swing.py", "backtest.py")).read()
src = src.split("rng = np.random.default_rng(3)")[0]  # reuse helpers only
exec(src)

pd.set_option("display.width", 250)


def signals(bid, ask, start, drop, mode):
    mid = (bid + ask) / 2
    pre = mid[start - 1]
    trig = None
    for i in range(start + 1, len(mid) - 2):
        if trig is None and mid[i] <= pre - drop:
            trig = i
        if trig is None:
            continue
        if mode == "settled" and not ((mid[i] - mid[max(i - 15, 0)] > -0.05) and mid[i] >= mid[i - 1]):
            continue
        j = i + 1
        if 0.20 <= ask[j] <= 0.80 and ask[j] - bid[j] <= 0.06:
            return j
        return None
    return None


rows = []
for t, g in c.groupby("ticker"):
    if t not in m.index or m.loc[t, "result"] not in ("yes", "no"):
        continue
    full = grid(g)
    if full is None:
        continue
    st = inplay_start(full)
    if st is None or st < 5 or st > len(full) - 30:
        continue
    level, gender = meta(t)
    day = full.index[-1].tz_convert("America/New_York").date()
    b0, a0 = full.bid.values, full.ask.values
    for side, (bid, ask) in {"yes": (b0, a0), "no": (1 - a0, 1 - b0)}.items():
        for mode in ("settled", "knife", "random"):
            if mode == "random":
                j = int(np.random.default_rng(abs(hash(t + side)) % 2**32).integers(st + 1, len(full) - 2))
                if not (0.20 <= ask[j] <= 0.80 and ask[j] - bid[j] <= 0.06):
                    continue
            else:
                j = signals(bid, ask, st, 0.15, mode)
                if j is None:
                    continue
            n = len(bid)
            mid = (bid + ask) / 2
            r = {"ticker": t, "side": side, "mode": mode, "gender": gender, "day": day,
                 "ask0": ask[j], "bid0": bid[j], "mid0": mid[j]}
            for k in (5, 15, 30):
                jj = min(j + k, n - 1)
                r[f"mid_move_{k}"] = mid[jj] - mid[j]
                r[f"best_bid_{k}"] = bid[j + 1:jj + 1].max() if jj > j else bid[j]
                r[f"best_ask_{k}"] = ask[j + 1:jj + 1].max() if jj > j else ask[j]
                r[f"bid_at_{k}"] = bid[jj]
            # take-profit swing strategies: sell at bid once bid >= ask0 + tp, else sell at bid after 30 min
            for tp in (0.03, 0.05, 0.10):
                ex = None
                for kk in range(j + 1, min(j + 31, n)):
                    if bid[kk] >= ask[j] + tp:
                        ex = bid[kk]; break
                r[f"tp{int(tp*100)}_hit"] = ex is not None
                r[f"tp{int(tp*100)}_exit"] = ex if ex is not None else bid[min(j + 30, n - 1)]
                # maker version: buy at bid, sell at ask when ask >= bid0 + tp, else sell at bid after 30 (taker exit)
                exm = None
                for kk in range(j + 1, min(j + 31, n)):
                    if ask[kk] >= bid[j] + tp:
                        exm = bid[j] + tp; break
                r[f"mk_tp{int(tp*100)}_exit"] = exm if exm is not None else bid[min(j + 30, n - 1)]
                r[f"mk_tp{int(tp*100)}_hit"] = exm is not None
            rows.append(r)

x = pd.DataFrame(rows)
x["period"] = np.where(pd.to_datetime(x.day) < pd.Timestamp("2026-09-01"), "Aug", "Sep-Oct")


def fee_pc(p):  # per-contract taker fee, $10-stake rounding ignored
    return 0.07 * p * (1 - p)


out = []
for (mode, per), d in x.groupby(["mode", "period"]):
    row = {"mode": mode, "period": per, "trades": len(d), "avg_ask": d.ask0.mean(),
           "avg spread": (d.ask0 - d.bid0).mean()}
    for k in (5, 15, 30):
        row[f"mid move +{k}m"] = d[f"mid_move_{k}"].mean()
    for tp in (3, 5, 10):
        ex = d[f"tp{tp}_exit"]
        pnl = ex - d.ask0 - fee_pc(d.ask0) - fee_pc(ex)
        row[f"taker tp{tp}c roi"] = (pnl / d.ask0).mean()
        row[f"tp{tp} hit%"] = d[f"tp{tp}_hit"].mean()
        exm = d[f"mk_tp{tp}_exit"]
        pnlm = exm - d.bid0 - np.where(d[f"mk_tp{tp}_hit"], 0, fee_pc(exm))
        row[f"maker tp{tp}c roi*"] = (pnlm / d.bid0.clip(lower=0.01)).mean()
    out.append(row)
res = pd.DataFrame(out).round(3)
print("mid move = how far the fair price moved after entry (cents/100). Positive = bounced.")
print("taker tpX = buy at ask, sell at bid when +X over cost or after 30 min, fees both ways.")
print("maker tpX* = buy at bid, sell at bid+X via resting order, else dump at bid after 30 min. Optimistic.\n")
print(res[["mode", "period", "trades", "avg_ask", "avg spread", "mid move +5m", "mid move +15m", "mid move +30m"]].to_string(index=False))
print()
print(res[["mode", "period", "tp3 hit%", "taker tp3c roi", "tp5 hit%", "taker tp5c roi", "tp10 hit%", "taker tp10c roi"]].to_string(index=False))
print()
print(res[["mode", "period", "maker tp3c roi*", "maker tp5c roi*", "maker tp10c roi*"]].to_string(index=False))

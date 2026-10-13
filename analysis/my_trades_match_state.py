import re
import sys
import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)

pnl_path, cand_path, mkt_path, out_path = sys.argv[1:5]
TENNIS = {"KXITFMATCH", "KXITFWMATCH", "KXITFDOUBLES", "KXWTAMATCH", "KXATPMATCH", "KXATPCHALLENGERMATCH"}

f = pd.read_csv(pnl_path)
f = f[(f.type == "trade") & f.market_ticker.str.split("-").str[0].isin(TENNIS)].copy()
f["ot"] = pd.to_datetime(f.open_timestamp, utc=True)
f["ct"] = pd.to_datetime(f.close_timestamp, utc=True)
f["cost"] = f.quantity_fp * f.entry_price_dollars
f["net"] = f.realized_pnl_with_fees_dollars
f["gross"] = f.realized_pnl_without_fees_dollars
f["sold"] = f.close_fees_dollars > 0

m = pd.read_csv(mkt_path)
def parse(r):
    rp = r.rules_primary or ""
    mm = re.search(r"in the 2026 (.+?) (Round [Oo]f \d+|Quarterfinal|Semifinal|Final|Qualif\w*.*?)(?: after|$)", rp)
    tour = mm.group(1) if mm else ""
    rnd = mm.group(2) if mm else ""
    s = r.ticker.split("-")[0]
    if s in ("KXATPMATCH",): level = "ATP"
    elif s == "KXWTAMATCH": level = "WTA"
    elif s == "KXATPCHALLENGERMATCH": level = "Challenger"
    else:
        lv = re.match(r"([MW]\d+)", tour)
        level = lv.group(1) if lv else "ITF"
    gender = "W" if (s == "KXITFWMATCH" or s == "KXWTAMATCH" or level.startswith("W")) else "M"
    return pd.Series({"tournament": tour, "round": rnd, "level": level, "gender": gender, "player": r.yes_sub_title})
m = pd.concat([m, m.apply(parse, axis=1)], axis=1).set_index("ticker")

c = pd.read_csv(cand_path)
c["mid"] = (c.yes_bid_close + c.yes_ask_close) / 2
c["spread"] = c.yes_ask_close - c.yes_bid_close

series = {}
starts = {}
for t, g in c.groupby("ticker"):
    g = g.sort_values("end_ts").drop_duplicates("end_ts", keep="last")
    idx = pd.to_datetime(g.end_ts, unit="s", utc=True)
    s = pd.DataFrame({"mid": g.mid.values, "bid": g.yes_bid_close.values, "ask": g.yes_ask_close.values,
                      "vol": g.volume.values, "spread": g.spread.values}, index=idx)
    full = s.reindex(pd.date_range(idx.min(), idx.max(), freq="1min")).ffill()
    full["vol"] = s.vol.reindex(full.index).fillna(0)
    # in-play start: first minute where the next 10 minutes have >=5 traded minutes and the mid moves >= 3c
    active = (full.vol > 0).astype(int)
    fwd_active = active[::-1].rolling(10, min_periods=1).sum()[::-1]
    move = full.mid.diff().abs()
    fwd_move = move[::-1].rolling(10, min_periods=1).max()[::-1]
    cand = full.index[(fwd_active >= 5) & (fwd_move >= 0.03) & (full.spread <= 0.15)]
    starts[t] = cand[0] if len(cand) else pd.NaT
    series[t] = full

def at(t, ts, col="mid"):
    s = series.get(t)
    if s is None:
        return np.nan
    sub = s.loc[:ts]
    return sub[col].iloc[-1] if len(sub) else np.nan

rows = []
for _, r in f.iterrows():
    t = r.market_ticker
    if t not in series:
        continue
    ts = r.ot.floor("min")
    st = starts[t]
    pre = at(t, st - pd.Timedelta(minutes=1)) if pd.notna(st) else np.nan
    mid0 = at(t, ts)
    ask0 = at(t, ts, "ask")
    bid0 = at(t, ts, "bid")
    d = {
        "ticker": t, "ot": r.ot, "qty": r.quantity_fp, "entry": r.entry_price_dollars, "cost": r.cost,
        "net": r.net, "gross": r.gross, "sold": r.sold, "exit": r.exit_price_dollars,
        "mid0": mid0, "bid0": bid0, "ask0": ask0, "spread0": ask0 - bid0, "pre": pre,
        "min_in": (ts - st).total_seconds() / 60 if pd.notna(st) else np.nan,
        "mom5": mid0 - at(t, ts - pd.Timedelta(minutes=5)),
        "mom15": mid0 - at(t, ts - pd.Timedelta(minutes=15)),
        "result": 1.0 if m.loc[t, "result"] == "yes" else 0.0,
    }
    for k in (5, 15, 30, 60):
        d[f"mk{k}"] = at(t, ts + pd.Timedelta(minutes=k)) - r.entry_price_dollars
    d["mk_settle"] = d["result"] - r.entry_price_dollars
    for col in ("tournament", "round", "level", "gender", "player"):
        d[col] = m.loc[t, col]
    rows.append(d)

x = pd.DataFrame(rows)
x["dev_pre"] = x.mid0 - x.pre
x["phase"] = pd.cut(x.min_in, [-1e9, 0, 30, 60, 90, 1e9], labels=["pre-match", "0-30m", "30-60m", "60-90m", "90m+"])
x["pre_role"] = np.where(x.pre >= 0.5, "pre-match fav", "pre-match dog")
x["situation"] = np.select(
    [x.min_in <= 0, x.dev_pre <= -0.15, x.dev_pre >= 0.15],
    ["pre-match", "bought after player fell 15c+ from pre-match", "bought after player rose 15c+ from pre-match"],
    default="near pre-match price (in-play)")
x["momentum"] = np.select([x.mom15 <= -0.05, x.mom15 >= 0.05], ["falling (last 15m)", "rising (last 15m)"], default="flat")
x["fill_vs_book"] = np.select([x.entry >= x.ask0 - 0.005, x.entry <= x.bid0 + 0.005], ["at/above ask", "at/below bid"], default="inside spread")
x["size"] = pd.cut(x.cost, [0, 25, 50, 100, 1e6], labels=["<$25", "$25-50", "$50-100", "$100+"])
x.to_csv(out_path, index=False)

def w(a, wt):
    ok = ~np.isnan(a)
    return np.average(a[ok], weights=wt[ok]) if ok.any() else np.nan

def summ(by):
    g = x.groupby(by, observed=True)
    out = g.apply(lambda d: pd.Series({
        "fills": len(d), "matches": d.ticker.nunique(), "risked": d.cost.sum(), "net": d.net.sum(),
        "roi": d.net.sum() / d.cost.sum(),
        "mk5": w(d.mk5.values, d.qty.values), "mk15": w(d.mk15.values, d.qty.values),
        "mk30": w(d.mk30.values, d.qty.values), "mk_settle": w(d.mk_settle.values, d.qty.values),
    }), include_groups=False)
    return out.round(3)

print(f"fills matched: {len(x)} / {len(f)}; matches {x.ticker.nunique()}; in-play start found for {pd.Series(starts).notna().sum()} / {len(starts)}")
print("\nMarkout = mid price N minutes after your entry minus what you paid (per contract, qty-weighted). Positive = market moved your way.\n")
for by in ["phase", "situation", "momentum", "pre_role", "fill_vs_book", "size", "level", "gender"]:
    print(f"=== by {by} ===")
    print(summ(by)); print()
print("=== situation x momentum ===")
print(summ(["situation", "momentum"]))
print("\n=== overall ===")
print(summ(lambda i: "all"))
print("\nentry minus ask (qty-w):", round(w((x.entry - x.ask0).values, x.qty.values), 4), " median spread at entry:", x.spread0.median())

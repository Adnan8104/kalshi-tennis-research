import sys
import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 200)

df = pd.read_csv(sys.argv[1])
credits = df[df.type == "credit"]
d = df[df.type == "trade"].copy()
d["ot"] = pd.to_datetime(d.open_timestamp, utc=True).dt.tz_convert("America/New_York")
d["ct"] = pd.to_datetime(d.close_timestamp, utc=True).dt.tz_convert("America/New_York")
d["series"] = d.market_ticker.str.split("-").str[0]
cat_map = {
    "KXITFMATCH": "Tennis ITF", "KXITFWMATCH": "Tennis ITF", "KXITFDOUBLES": "Tennis ITF",
    "KXWTAMATCH": "Tennis ATP/WTA/Chall", "KXATPMATCH": "Tennis ATP/WTA/Chall",
    "KXATPCHALLENGERMATCH": "Tennis ATP/WTA/Chall",
    "KXMVESPORTSMULTIGAMEEXTENDED": "Parlays", "KXMVECROSSCATEGORY": "Parlays",
    "KXNPBGAME": "NPB baseball",
}
d["cat"] = d.series.map(cat_map).fillna(d.series.apply(lambda s: "World Cup" if s.startswith("KXWC") or s == "KXMENWORLDCUP" else "Other"))
d["cost"] = d.quantity_fp * d.entry_price_dollars
d["fees"] = d.open_fees_dollars + d.close_fees_dollars
d["gross"] = d.realized_pnl_without_fees_dollars
d["net"] = d.realized_pnl_with_fees_dollars
d["sold_early"] = d.close_fees_dollars > 0
d["hold_min"] = (d.ct - d.ot).dt.total_seconds() / 60
# fee rate relative to Kalshi's p(1-p) formula
d["fee_coef"] = d.open_fees_dollars / (d.quantity_fp * d.entry_price_dollars * (1 - d.entry_price_dollars))

print("=== TOTALS ===")
print(f"trade rows {len(d)}, markets {d.market_ticker.nunique()}, credits ${credits.realized_pnl_with_fees_dollars.sum():.2f}")
print(f"gross {d.gross.sum():.2f}  fees {d.fees.sum():.2f}  net {d.net.sum():.2f}  total risked {d.cost.sum():.2f}")

# Position level: aggregate per market+side
pos = d.groupby(["market_ticker", "side"]).agg(
    cat=("cat", "first"), qty=("quantity_fp", "sum"), cost=("cost", "sum"),
    gross=("gross", "sum"), fees=("fees", "sum"), net=("net", "sum"),
    ot=("ot", "min"), ct=("ct", "max"), sold_early=("sold_early", "mean"),
    n_rows=("gross", "size"),
).reset_index()
pos["avg_entry"] = pos.cost / pos.qty
pos["ret_gross"] = pos.gross / pos.cost
pos["ret_net"] = pos.net / pos.cost
pos = pos.sort_values("ct").reset_index(drop=True)
print(f"positions {len(pos)}")

print("\n=== BY CATEGORY (positions) ===")
g = pos.groupby("cat").agg(n=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"),
                            fees=("fees", "sum"), net=("net", "sum"))
g["gross_roi"] = g.gross / g.risked
g["net_roi"] = g.net / g.risked
print(g.sort_values("risked", ascending=False).round(3))

print("\n=== TIMELINE ===")
pos["cum_net"] = pos.net.cumsum()
peak_i = pos.cum_net.idxmax()
print(f"peak cum net {pos.cum_net.max():.2f} at {pos.ct[peak_i]} after {peak_i+1} positions; final {pos.cum_net.iloc[-1]:.2f}; trough {pos.cum_net.min():.2f}")
pos["month"] = pos.ct.dt.to_period("M")
m = pos.groupby("month").agg(n=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"), fees=("fees", "sum"), net=("net", "sum"))
m["avg_bet"] = m.risked / m.n
print(m.round(2))
pos["day"] = pos.ct.dt.date
dd = pos.groupby("day").agg(n=("net", "size"), risked=("cost", "sum"), net=("net", "sum"), cats=("cat", lambda x: ",".join(sorted(set(x)))))
dd["cum"] = dd.net.cumsum()
print(dd.round(2))

print("\n=== SKILL TEST: settled-only calibration (rows held to settlement, qty weighted) ===")
s = d[~d.sold_early & d.exit_price_dollars.isin([0, 1])].copy()
s["bucket"] = pd.cut(s.entry_price_dollars, [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0])
cal = s.groupby("bucket", observed=True).apply(lambda x: pd.Series({
    "rows": len(x), "markets": x.market_ticker.nunique(), "contracts": x.quantity_fp.sum(),
    "avg_entry": np.average(x.entry_price_dollars, weights=x.quantity_fp),
    "win_rate_w": np.average(x.exit_price_dollars, weights=x.quantity_fp),
    "gross": x.gross.sum(), "net": x.net.sum()}))
print(cal.round(3))

print("\n=== SKILL TEST: position-level gross ROI bootstrap ===")
rng = np.random.default_rng(0)
for label, sub in [("all", pos), ("tennis ITF", pos[pos.cat == "Tennis ITF"]), ("parlays", pos[pos.cat == "Parlays"]),
                   ("non-parlay", pos[pos.cat != "Parlays"])]:
    gsum = sub.gross.values; c = sub.cost.values
    boots = []
    for _ in range(5000):
        i = rng.integers(0, len(sub), len(sub))
        boots.append(gsum[i].sum() / c[i].sum())
    boots = np.array(boots)
    nb = []
    ns = sub.net.values
    for _ in range(5000):
        i = rng.integers(0, len(sub), len(sub))
        nb.append(ns[i].sum() / c[i].sum())
    nb = np.array(nb)
    print(f"{label:12s} n={len(sub):3d} grossROI={gsum.sum()/c.sum():+.3f} CI95=[{np.percentile(boots,2.5):+.3f},{np.percentile(boots,97.5):+.3f}] P(gross>0)={np.mean(boots>0):.2f} | netROI={ns.sum()/c.sum():+.3f} CI95=[{np.percentile(nb,2.5):+.3f},{np.percentile(nb,97.5):+.3f}]")

print("\n=== SOLD EARLY vs HELD (rows) ===")
x = d.groupby("sold_early").agg(rows=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"), fees=("fees", "sum"), net=("net", "sum"))
x["gross_roi"] = x.gross / x.risked; x["net_roi"] = x.net / x.risked
print(x.round(3))
e = d[d.sold_early]
print("sold early: avg exit-entry per contract (qty-w):", round(np.average(e.exit_price_dollars - e.entry_price_dollars, weights=e.quantity_fp), 4),
      " share of sells at a profit:", round((e.exit_price_dollars > e.entry_price_dollars).mean(), 3))

print("\n=== ENTRY PRICE BUCKETS (positions, all) ===")
pos["pb"] = pd.cut(pos.avg_entry, [0, .15, .3, .45, .6, .75, 1.0])
b = pos.groupby("pb", observed=True).agg(n=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"), fees=("fees", "sum"), net=("net", "sum"))
b["gross_roi"] = b.gross / b.risked; b["net_roi"] = b.net / b.risked; b["fee_pct_risk"] = b.fees / b.risked
print(b.round(3))

print("\n=== SIZE BUCKETS (positions) ===")
pos["sb"] = pd.qcut(pos.cost, 4)
b = pos.groupby("sb", observed=True).agg(n=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"), net=("net", "sum"))
b["gross_roi"] = b.gross / b.risked; b["net_roi"] = b.net / b.risked
print(b.round(3))

print("\n=== HOLD TIME (rows) ===")
d["hb"] = pd.cut(d.hold_min, [-1, 15, 60, 180, 600, 1e7])
b = d.groupby("hb", observed=True).agg(rows=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"), net=("net", "sum"))
b["gross_roi"] = b.gross / b.risked
print(b.round(3))

print("\n=== HOUR OF DAY ET (positions by open) ===")
pos["hr"] = pd.cut(pos.ot.dt.hour, [-1, 5, 9, 13, 17, 21, 24], labels=["0-5", "6-9", "10-13", "14-17", "18-21", "22-23"])
b = pos.groupby("hr", observed=True).agg(n=("net", "size"), risked=("cost", "sum"), gross=("gross", "sum"), net=("net", "sum"))
b["gross_roi"] = b.gross / b.risked
print(b.round(3))

print("\n=== TILT: positions opened within 60 min after a losing close ===")
closes = pos[["ct", "net"]].sort_values("ct")
def after_loss(t):
    prev = closes[(closes.ct < t) & (closes.ct > t - pd.Timedelta(minutes=60))]
    return (prev.net < 0).any()
pos["after_loss"] = pos.ot.apply(after_loss)
b = pos.groupby("after_loss").agg(n=("net", "size"), risked=("cost", "sum"), avg_bet=("cost", "mean"), gross=("gross", "sum"), net=("net", "sum"))
b["gross_roi"] = b.gross / b.risked
print(b.round(3))

print("\n=== FEES ===")
print("fee coef quantiles (open fee / (C*p*(1-p))):", d.fee_coef.quantile([.05, .25, .5, .75, .95]).round(4).to_dict())
print("fees as % of gross absolute pnl:", round(d.fees.sum() / d.gross.abs().sum(), 3))

print("\n=== BIGGEST WINS / LOSSES (positions) ===")
cols = ["market_ticker", "side", "cat", "avg_entry", "qty", "cost", "net", "ct"]
print(pos.nlargest(10, "net")[cols].round(2))
print(pos.nsmallest(10, "net")[cols].round(2))

print("\n=== MULTI-ROW MARKETS (scalping?) ===")
mr = pos[pos.n_rows >= 5][["market_ticker", "cat", "n_rows", "cost", "gross", "fees", "net", "sold_early"]]
print(mr.round(2))

pos.to_csv(sys.argv[2], index=False)

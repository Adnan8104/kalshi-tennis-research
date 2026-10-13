"""Render the two README charts into results/figures/ from the numbers in results/*.txt."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = os.path.join(os.path.dirname(__file__), "..", "results", "figures")
os.makedirs(OUT, exist_ok=True)
BLUE, ORANGE = "#2a78d6", "#eb6834"
SURF, T1, T2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"
W = 0.36


def style(ax, fig):
    fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID); ax.tick_params(colors=T2, length=0)
    ax.yaxis.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)


# maker P&L by tour (results/maker_results.txt)
tours = ["ATP", "WTA", "ITF men", "ITF women", "Challenger"]
m15 = [0.477, 0.465, 0.053, 0.161, 0.041]
settle = [2.241, 1.195, 0.062, -0.065, -0.820]
x = np.arange(len(tours))
fig, ax = plt.subplots(figsize=(8, 4.4), dpi=160); style(ax, fig)
b1 = ax.bar(x - W / 2 - 0.01, m15, W, color=BLUE, label="Marked 15 min after fill")
b2 = ax.bar(x + W / 2 + 0.01, settle, W, color=ORANGE, label="Held to settlement (net of maker fee)")
ax.axhline(0, color=T2, lw=1)
for bars, vals in ((b1, m15), (b2, settle)):
    for r, v in zip(bars, vals):
        ax.text(r.get_x() + r.get_width() / 2, v + (0.06 if v >= 0 else -0.06), f"{v:+.2f}",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5, color=T1)
ax.set_xticks(x); ax.set_xticklabels(tours, color=T1)
ax.set_ylabel("Maker P&L, cents per contract", color=T2)
ax.set_title("Liquidity providers profit on ATP/WTA, not ITF/Challenger\n34M Kalshi tennis trades, Aug 5 to Oct 13, 2026",
             loc="left", color=T1, fontsize=11)
ax.legend(frameon=False, labelcolor=T1, fontsize=9, loc="upper right")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "maker_pnl_by_tour.png"), facecolor=SURF)

# ladder hit rates (results/ladder_results.txt)
lad = ["20¢→40¢", "20¢→45¢", "30¢→50¢", "45¢→65¢", "60¢→80¢"]
hit = [42.6, 37.4, 52.2, 62.7, 70.8]
fair = [51.5, 45.8, 60.4, 69.3, 74.9]
roi = [-19.6, -19.8, -15.8, -10.8, -6.1]
x = np.arange(len(lad))
fig, ax = plt.subplots(figsize=(8, 4.4), dpi=160); style(ax, fig)
b1 = ax.bar(x - W / 2 - 0.01, fair, W, color=BLUE, label="Fair hit rate (entry ÷ target)")
b2 = ax.bar(x + W / 2 + 0.01, hit, W, color=ORANGE, label="Actual hit rate (buy ask, sell bid)")
for bars, vals in ((b1, fair), (b2, hit)):
    for r, v in zip(bars, vals):
        ax.text(r.get_x() + r.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=8.5, color=T1)
ax.set_xticks(x); ax.set_xticklabels([f"{l}\nROI {q:+.0f}%" for l, q in zip(lad, roi)], color=T1, fontsize=9)
ax.set_ylabel("Share of trades hitting target", color=T2); ax.set_ylim(0, 90)
ax.set_title("Price ladders: spread and fees push every target below break-even\n~13,000 trades per ladder, all Kalshi tennis singles",
             loc="left", color=T1, fontsize=11)
ax.legend(frameon=False, labelcolor=T1, fontsize=9, loc="upper left")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "ladder_hit_rates.png"), facecolor=SURF)
print("saved figures to", os.path.abspath(OUT))

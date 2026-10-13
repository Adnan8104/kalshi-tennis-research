import sys, numpy as np, pandas as pd
sys.argv=[sys.argv[0], sys.argv[1], sys.argv[2], "/dev/null"]
exec(open(sys.argv[0].replace("ladder.py","backtest.py")).read().split("rng = np.random.default_rng(3)")[0])
fee=lambda p: 0.07*p*(1-p)
TOUR={'KXITFMATCH':'ITF men','KXITFWMATCH':'ITF women','KXATPMATCH':'ATP+Chall','KXATPCHALLENGERMATCH':'ATP+Chall','KXWTAMATCH':'WTA'}
LADDERS=[(0.20,0.40),(0.20,0.45),(0.30,0.50),(0.45,0.65),(0.60,0.80)]
rows=[]
for t,g in c.groupby("ticker"):
    if t not in m.index or m.loc[t,"result"] not in ("yes","no"): continue
    full=grid(g)
    if full is None: continue
    st=inplay_start(full)
    if st is None or st<5 or st>len(full)-30: continue
    ry=1.0 if m.loc[t,"result"]=="yes" else 0.0
    b0,a0=full.bid.values,full.ask.values
    for side,(bid,ask,res) in {"yes":(b0,a0,ry),"no":(1-a0,1-b0,1-ry)}.items():
        for lo,hi in LADDERS:
            idx=np.where((ask[st:]>=lo-0.02)&(ask[st:]<=lo+0.02)&((ask[st:]-bid[st:])<=0.06))[0]
            if not len(idx): continue
            j=st+idx[0]; e=ask[j]
            hit=np.where(bid[j+1:]>=hi)[0]
            ex=bid[j+1+hit[0]] if len(hit) else res
            pnl=ex-e-fee(e)-(fee(ex) if len(hit) else 0)
            rows.append({"tour":TOUR.get(t.split("-")[0]),"day":full.index[-1].date(),"ladder":f"buy ~{int(lo*100)}c, sell at {int(hi*100)}c","entry":e,"target":hi,"hit":len(hit)>0,"roi":pnl/e})
x=pd.DataFrame(rows)
x["fair_hit%"]=x.entry/x.target
r=x.groupby("ladder").agg(trades=("roi","size"),avg_entry=("entry","mean"),hit_rate=("hit","mean"),fair_hit=("fair_hit%","mean"),roi_after_fees=("roi","mean")).round(3)
print(r.to_string())

x["period"]=np.where(pd.to_datetime(x.day)<pd.Timestamp("2026-09-01"),"Aug","Sep-Oct")
print()
print(x.groupby(["ladder","period"]).agg(trades=("roi","size"),hit_rate=("hit","mean"),fair_hit=("fair_hit%","mean"),roi=("roi","mean")).round(3).to_string())
print()
print(x.groupby(["ladder","tour"]).agg(trades=("roi","size"),hit_rate=("hit","mean"),fair_hit=("fair_hit%","mean"),roi=("roi","mean")).round(3).to_string())

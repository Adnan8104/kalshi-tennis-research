import sys, pickle, glob, numpy as np, pandas as pd
H=[1,5,15,60]; COLS=["edge0"]+[f"m{h}" for h in H]+["settle","fee"]
agg={}
for f in sorted(glob.glob(sys.argv[1])):
    for k,a in pickle.load(open(f,"rb")).items():
        agg[k]=agg.get(k,0)+a
rows=[]
for k,a in agg.items():
    r={"group":" | ".join(map(str,k)),"contracts_M":a[0]/1e6}
    for i,c in enumerate(COLS): r[c]=a[i+1]/a[0]*100
    rows.append(r)
out=pd.DataFrame(rows).sort_values("group"); out["settle_net_fee"]=out.settle-out.fee
pd.set_option("display.width",250); pd.set_option("display.max_rows",300)
txt="Maker P&L in CENTS PER CONTRACT (contract-weighted). edge0=spread captured vs mid at fill; mH=marked to mid H min later; settle=held to result; fee=maker fee where charged.\n\n"+out.round(3).to_string(index=False)
open("maker_summary.txt","w").write(txt); print(txt)

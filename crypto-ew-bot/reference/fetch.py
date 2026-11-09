import json, sys, time, urllib.request
def get(inst, tf, n=900):
    out={}; end=None
    while len(out)<n:
        u=f"https://api.crypto.com/exchange/v1/public/get-candlestick?instrument_name={inst}&timeframe={tf}&count=300"
        if end: u+=f"&end_ts={end}"
        d=json.load(urllib.request.urlopen(u,timeout=15))["result"]["data"]
        if not d: break
        new=0
        for c in d:
            if c["t"] not in out: out[c["t"]]=c; new+=1
        if new==0: break
        end=min(c["t"] for c in d)-1
    rows=sorted(out.values(),key=lambda c:c["t"])
    return [[c["t"],float(c["o"]),float(c["h"]),float(c["l"]),float(c["c"]),float(c["v"])] for c in rows]
for s in ["BTC","ETH","SOL"]:
    for tf,n in [("30m",1000),("4h",600)]:
        r=get(f"{s}_USD",tf,n); json.dump(r,open(f"data/{s}_{tf}.json","w"))
        print(s,tf,len(r),time.strftime('%m-%d %H:%M',time.gmtime(r[0][0]/1000)),"->",time.strftime('%m-%d %H:%M',time.gmtime(r[-1][0]/1000)),r[-1][4])

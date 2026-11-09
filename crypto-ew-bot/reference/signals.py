import json
eurusd = 66615.32/74232.54   # EUR per USD from Crypto.com BTC_EUR / BTC_USD (last close)
RISK = 0.0075                # 0.75 % of trading capital per trade
coins = {
 # big rally low/high (daily), current-leg A/B for C-target, flush low, bounce high, plan levels
 "BTC": dict(r0=57737.07, r1=87427.66, A0=None, low=73325.70, bounce=74716.56,
             entry=73900, stop=72400, t1=75600, t2=76900),
 "ETH": dict(r0=1504.64, r1=2807.53, A0=(2807.53,2171.66,2447.95,0.618), low=2056.84, bounce=2137.22,
             entry=2090, stop=1990, t1=2200, t2=2280),
 "SOL": dict(r0=60.10, r1=124.95, A0=(98.06,89.12,96.43,1.272), low=84.92, bounce=86.97,
             entry=85.60, stop=83.40, t1=88.80, t2=91.40),
}
out={"eurusd":round(eurusd,4),"risk":RISK,"coins":{}}
tot=0
for s,c in coins.items():
    rng=c["r1"]-c["r0"]
    fib={k:round(c["r1"]-k*rng,2) for k in (0.5,0.618,0.786)}
    retr_now=(c["r1"]-c["low"])/rng
    ctgt=None
    if c["A0"]:
        a,b,B,k=c["A0"]; ctgt=round(B-k*(a-b),2)
    bounce618=round(c["bounce"]-0.618*(c["bounce"]-c["low"]),2)
    d=c["entry"]-c["stop"]
    rr1=(c["t1"]-c["entry"])/d; rr2=(c["t2"]-c["entry"])/d
    pos_pct=RISK/(d/c["entry"])          # position value as share of capital
    tot+=pos_pct
    out["coins"][s]=dict(**{k:c[k] for k in ("entry","stop","t1","t2","low","bounce")},
        fib_rally=fib, retr_now=round(retr_now,3), c_target=ctgt, bounce_618=bounce618,
        stop_dist_pct=round(d/c["entry"]*100,2), rr1=round(rr1,2), rr2=round(rr2,2),
        rr_avg=round((rr1+rr2)/2,2), pos_pct=round(pos_pct*100,1),
        eur={k:round(c[k]*eurusd,2) for k in ("entry","stop","t1","t2")})
    print(f"{s}: rally fib50/61.8/78.6={fib}  low retraces {retr_now:.1%}  C-target={ctgt}  bounce61.8%={bounce618}")
    print(f"     entry {c['entry']} stop {c['stop']} ({d/c['entry']:.2%})  T1 {c['t1']} ({rr1:.2f}R)  T2 {c['t2']} ({rr2:.2f}R)  position = {pos_pct:.1%} of capital  EUR={out['coins'][s]['eur']}")
out["total_exposure_pct"]=round(tot*100,1)
print(f"total exposure {tot:.1%} of capital, max loss if all 3 stop out: {3*RISK:.2%}")
# example for 1000 EUR capital
ex={}
for s,c in out["coins"].items():
    val=1000*c["pos_pct"]/100; ex[s]=dict(eur=round(val,2), units=round(val/c["eur"]["entry"],6), risk_eur=round(1000*RISK,2))
out["example_1000"]=ex; print("per 1000 EUR:",ex)
json.dump(out,open("signals.json","w"),indent=1)

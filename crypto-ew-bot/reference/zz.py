import json, time, sys
def zigzag(rows, pct):
    piv=[]; trend=None; ext_i=0
    hi=lambda i:rows[i][2]; lo=lambda i:rows[i][3]
    cand_h=0; cand_l=0
    for i in range(1,len(rows)):
        if trend in (None,'up'):
            if hi(i)>=hi(cand_h): cand_h=i
            if trend=='up' and lo(i)<=hi(cand_h)*(1-pct):
                piv.append(('H',cand_h,hi(cand_h))); trend='down'; cand_l=i
        if trend in (None,'down'):
            if lo(i)<=lo(cand_l): cand_l=i
            if trend=='down' and hi(i)>=lo(cand_l)*(1+pct):
                piv.append(('L',cand_l,lo(cand_l))); trend='up'; cand_h=i
        if trend is None:
            if hi(i)>=lo(cand_l)*(1+pct): piv.append(('L',cand_l,lo(cand_l))); trend='up'; cand_h=i
            elif lo(i)<=hi(cand_h)*(1-pct): piv.append(('H',cand_h,hi(cand_h))); trend='down'; cand_l=i
    last = ('H',cand_h,hi(cand_h)) if trend=='up' else ('L',cand_l,lo(cand_l))
    piv.append(last+('open',))
    return piv
def atr(rows,n=14):
    tr=[max(r[2]-r[3],abs(r[2]-p[4]),abs(r[3]-p[4])) for p,r in zip(rows,rows[1:])]
    return sum(tr[-n:])/n
ts=lambda t:time.strftime('%m-%d %H:%M',time.gmtime(t/1000))
for s in sys.argv[1:]:
    for tf,pct in [("4h",0.06),("30m",0.02)]:
        rows=json.load(open(f"data/{s}_{tf}.json"))
        p=zigzag(rows,pct)[-12:]
        print(f"\n{s} {tf} zz{pct*100:.0f}% ATR14={atr(rows):.2f} last={rows[-1][4]}")
        prev=None
        for x in p:
            ch=f"{(x[2]/prev-1)*100:+.1f}%" if prev else ""
            print(f"  {x[0]} {ts(rows[x[1]][0])} {x[2]:.2f} {ch} {x[3] if len(x)>3 else ''}"); prev=x[2]

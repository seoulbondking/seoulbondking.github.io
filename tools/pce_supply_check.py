"""근원 PCE 공급 기여 — '코로나 이전 대비 얼마나 높은가'를 판단하는 점검표.

    python tools/pce_supply_check.py

SF 연준 Shapiro 분해(us_pce_sd)의 근원 PCE 월간연율 기여도(%p)를 쓴다.
  1) 수준   : 3개월 평균 vs 2015~19 평균. 차이를 2015~19 의 3MMA 표준편차로 나눈 z
  2) 지속성 : 3MMA 가 2015~19 평균 + 1σ 를 몇 달 연속 넘었나
  3) 구성   : 같은 기간 수요 기여도 — 둘 다 높으면 공급충격만이 아니다
  4) 원인   : 브렌트 전년비(0~12개월 시차)와의 상관 — 2015~19·2021~ 구간을 따로 본다
월간연율 단월은 매우 출렁인다(σ 약 1%p). 판단은 3MMA 와 지속성으로 한다.
"""
import json, os, sys, statistics as st
sys.stdout.reconfigure(encoding='utf-8')
D = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')


def load(fn):
    d = json.load(open(os.path.join(D, fn), encoding='utf-8'))
    return {s['name']: {p['d'][:7]: p['v'] for p in s['data']} for s in d['series']}


S = load('us_pce_sd.json')
sup, dem, amb = (S[f'근원 월간연율 · {k}'] for k in ('공급', '수요', '모호'))
ms = sorted(sup)


def ma3(m):
    out = {}
    for i in range(2, len(ms)):
        v = [m.get(ms[i - k]) for k in range(3)]
        if None not in v: out[ms[i]] = sum(v) / 3
    return out


s3, d3, a3 = ma3(sup), ma3(dem), ma3(amb)
base = [k for k in s3 if '2015-01' <= k <= '2019-12']
for nm, m3, m1 in (('공급', s3, sup), ('수요', d3, dem), ('모호', a3, amb)):
    mu = st.mean(m3[k] for k in base); sd = st.pstdev(m3[k] for k in base)
    mu1 = st.mean(m1[k] for k in base)
    last = ms[-1]
    run = 0
    for k in reversed(ms):
        if k in m3 and m3[k] > mu + sd: run += 1
        else: break
    print(f'[{nm}] 2015~19 평균 {mu1:.2f}%p (3MMA σ {sd:.2f}) · 최근 3MMA {m3[last]:.2f} → 차이 {m3[last]-mu:+.2f}%p, z {(m3[last]-mu)/sd:+.1f} · 평균+1σ 초과 연속 {run}개월')
print()
print('월     공급  공급3M  수요  수요3M  모호  근원합(월간연율)')
for k in ms[-12:]:
    print(f'{k}  {sup[k]:5.2f}  {s3[k]:5.2f}  {dem[k]:5.2f}  {d3[k]:5.2f}  {amb[k]:5.2f}  {sup[k]+dem[k]+amb[k]:5.2f}')

# 브렌트 전년비 시차 상관 (공급 3MMA 와)
O = load('us_oil.json')['브렌트유']
by = {k: (O[k] / O[f'{int(k[:4])-1}{k[4:]}'] - 1) * 100 for k in O if f'{int(k[:4])-1}{k[4:]}' in O}


def addm(k, n):
    y, m = int(k[:4]), int(k[5:7]) + n
    y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f'{y:04d}-{m:02d}'


def corr(a, b):
    ma, mb = st.mean(a), st.mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) * st.pstdev(a) * st.pstdev(b))


print('\n브렌트 전년비(t−L) vs 근원 공급 기여 3MMA(t) 상관')
for lo, hi, lab in (('2001-01', '2019-12', '2001~19'), ('2021-01', ms[-1], '2021~ ')):
    row = []
    for L in (0, 3, 6, 9, 12):
        ks = [k for k in s3 if lo <= k <= hi and addm(k, -L) in by]
        row.append(f'L{L:>2}: {corr([s3[k] for k in ks], [by[addm(k, -L)] for k in ks]):+.2f}')
    print(' ', lab, ' · '.join(row))

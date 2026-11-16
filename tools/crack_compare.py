"""크랙스프레드 정의 비교 — 정의(디젤 vs 난방유, WTI vs 브렌트, 3-2-1 vs 휘발유 단독)에 따라
같은 달 값이 얼마나 달라지는지 본다. FRED 일별 → 월평균, $/gal.

    python tools/crack_compare.py            # 주요 시점 표
키는 .env 의 FRED_API_KEY (출력하지 않는다).
"""
import json, os, sys, urllib.request
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
for line in open(os.path.join(os.path.dirname(__file__), '..', '.env'), encoding='utf-8'):
    if '=' in line and not line.startswith('#'):
        k, v = line.strip().split('=', 1); os.environ.setdefault(k, v.strip().strip('"'))
KEY = os.environ['FRED_API_KEY']


def monthly(sid):
    u = (f'https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={KEY}'
         f'&file_type=json&frequency=m&aggregation_method=avg&observation_start=1986-01-01')
    obs = json.load(urllib.request.urlopen(u, timeout=60))['observations']
    return {o['date'][:7]: float(o['value']) for o in obs if o['value'] != '.'}


W, B = monthly('DCOILWTICO'), monthly('DCOILBRENTEU')
G, D, H = monthly('DGASNYH'), monthly('DDFUELNYH'), monthly('DHOILNYH')
GG = monthly('DGASUSGULF')
DEF = {
    '3-2-1 NYH ULSD·WTI (매크로박스)': lambda m: (2 * G[m] + D[m]) / 3 - W[m] / 42,
    '3-2-1 NYH 난방유·WTI': lambda m: (2 * G[m] + H[m]) / 3 - W[m] / 42,
    '3-2-1 NYH ULSD·브렌트': lambda m: (2 * G[m] + D[m]) / 3 - B[m] / 42,
    '3-2-1 NYH 난방유·브렌트': lambda m: (2 * G[m] + H[m]) / 3 - B[m] / 42,
    '휘발유 NYH − WTI': lambda m: G[m] - W[m] / 42,
    '휘발유 걸프 − WTI': lambda m: GG[m] - W[m] / 42,
}
MS = ['1990-01', '1998-12', '2005-09', '2007-05', '2012-09', '2020-04', '2022-06', '2022-10',
      '2025-10', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11']
print('정의'.ljust(30), *[m[2:].replace('-', '.').rjust(6) for m in MS])
for nm, f in DEF.items():
    row = []
    for m in MS:
        try: row.append(f'{f(m):6.2f}')
        except KeyError: row.append('     -')
    print(nm.ljust(30), *row)
# 난방유·디젤 시계열이 언제 끊기는지
print('\n난방유 마지막', max(H), '· ULSD 처음', min(D), '· 휘발유 NYH 처음', min(G))

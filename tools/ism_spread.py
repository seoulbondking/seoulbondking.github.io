"""ISM 제조업 신규주문 − 재고 스프레드가 PMI 를 앞서는지 확인한다.

시장에서 흔히 쓰는 '신규주문 − 재고'(고객 재고 아님)를 세 가지 형태로 만들어
k개월 뒤 PMI 변화와의 상관을 본다.
  NO-INV  차이 (포인트)      — 가장 흔한 형태
  NO/INV  비율               — 50 근처 확산지수라 차이와 거의 같은 정보
  NO-PMI  신규주문 − PMI     — 비교용
'단순 상관'은 PMI 평균회귀에 섞이므로 현재 PMI 수준을 통제한 회귀 계수(t값)도 함께 낸다.

사용: python tools/ism_spread.py [시작월 YYYY-MM]
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
START = sys.argv[1] if len(sys.argv) > 1 else "2008-01"

V = {}
with (ROOT / "data" / "us_ism.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["survey"] == "mfg":
            V.setdefault(r["item"], {})[r["month"]] = float(r["value"])
NO, INV, PMI = V["New Orders"], V["Inventories"], V["Manufacturing PMI"]
ms = sorted(m for m in set(NO) & set(INV) & set(PMI) if m >= START)
no = np.array([NO[m] for m in ms]); inv = np.array([INV[m] for m in ms]); pmi = np.array([PMI[m] for m in ms])
sp = no - inv
print(f"표본 {ms[0]} ~ {ms[-1]} ({len(ms)}개월)")
print(f"NO-INV  평균 {sp.mean():.1f}  표준편차 {sp.std():.1f}  최근 {ms[-1]} {sp[-1]:.1f}")
print("\n최근 12개월   신규주문  재고  스프레드  PMI")
for i in range(-12, 0):
    print(f"  {ms[i]}    {no[i]:5.1f}  {inv[i]:5.1f}  {sp[i]:6.1f}  {pmi[i]:5.1f}")


def ols_t(y, X):
    X = np.column_stack([np.ones(len(y))] + X)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    s2 = e @ e / (len(y) - X.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return b[1], b[1] / se[1]   # 첫 설명변수의 계수·t값 (중첩 표본이라 t는 과대 — 참고용)


print("\nk개월 뒤 PMI 변화 (PMI[t+k] − PMI[t])")
print("  k   상관 NO-INV  NO/INV  NO-PMI   |  PMI 수준 통제 시 NO-INV 계수 (t)")
for k in (1, 3, 6, 9, 12):
    y = pmi[k:] - pmi[:-k]
    c = lambda x: np.corrcoef(x[:-k], y)[0, 1]
    b, t = ols_t(y, [sp[:-k], pmi[:-k]])
    print(f"  {k:2d}   {c(sp):6.2f}   {c(no / inv):6.2f}  {c(no - pmi):6.2f}   |  {b:6.3f} ({t:5.1f})")

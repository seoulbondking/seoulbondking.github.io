"""PCE 가중치 확인용 1회성 스크립트 (BEA U20405).

    python tools/bea_pce_weights.py

PPI 의 'PCE 연결 항목'이 근원 PCE 에서 몇 %를 차지하는지 뽑아 본다.
PPI 표에 비중·기여도 열을 붙이기 전에, BEA 줄 이름과 합계가 맞는지 먼저 확인하는 용도다.

왜 필요한가
    지금 'PCE 연결 항목' 표는 "뭐가 얼마나 움직였나"만 보여준다. 8월처럼
    항공 +4.2% / 병원 +0.5% 가 같이 나오면 어느 쪽이 중요한지 표로는 안 보인다.
    병원은 근원 PCE 의 약 9%, 항공은 약 1% 라 기여도가 자릿수로 다르다.

주의
    PPI 와 PCE 의 분류가 1:1 이 아니다. PPI 는 병원을 입원·외래로 나누지만
    PCE 는 hospitals 한 덩어리라, 두 PPI 행이 같은 비중을 공유한다.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fetchers import bea

# PPI 항목 → PCE 줄 이름(U20405 LineDescription). 여러 줄이면 합산한다.
GROUPS = {
    "병원 (입원·외래 공통)": ["Nonprofit hospitals' services to households",
                              "Government hospitals", "Proprietary hospitals"],
    "의사 진료": ["Physician services"],
    "재택·호스피스 간호": ["Home health care"],
    "요양시설": ["Nonprofit nursing homes' services to households",
                 "Proprietary and government nursing homes"],
    "항공요금": ["Air transportation"],
    "자산관리 수수료": ["Portfolio management and investment advice services"],
}
# 근원 = 전체 − 식품 − 에너지. 아래 이름으로 빼낸다.
TOTAL = "Personal consumption expenditures"
FOOD = ["Food and beverages purchased for off-premises consumption"]
ENERGY = ["Gasoline and other energy goods", "Electricity and gas"]


def norm(s):
    import re
    s = re.sub(r"\([^)]*\d[^)]*\)", " ", (s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def main():
    # .env 로드 (fetch.py 와 같은 방식)
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    key = os.environ.get("BEA_API_KEY", "").strip()
    if not key:
        sys.exit("BEA_API_KEY 가 없습니다 (.env 확인)")

    rows = bea.request_table(key, "NIUnderlyingDetail", "U20405", "M", "ALL")
    # {정규화이름: {날짜: 값}}
    by_name = {}
    for r in rows:
        nm = norm(r.get("LineDescription"))
        d = bea._to_date(r.get("TimePeriod", ""))
        v = bea._num(r.get("DataValue"))
        if nm and d and v is not None:
            by_name.setdefault(nm, {})[d] = v
    if not by_name:
        sys.exit("U20405 에서 데이터를 읽지 못했습니다.")

    last = max(d for m in by_name.values() for d in m)
    print(f"기준월 {last}  (U20405, 명목 PCE, 십억달러 연율)\n")

    def amount(names):
        tot, miss = 0.0, []
        for n in names:
            m = by_name.get(norm(n))
            if m is None or last not in m:
                miss.append(n)
            else:
                tot += m[last]
        return tot, miss

    total, m0 = amount([TOTAL])
    food, m1 = amount(FOOD)
    ener, m2 = amount(ENERGY)
    missing = m0 + m1 + m2
    core = total - food - ener
    print(f"  전체 PCE {total:10,.1f}")
    print(f"  − 식품   {food:10,.1f}")
    print(f"  − 에너지 {ener:10,.1f}")
    print(f"  = 근원   {core:10,.1f}\n")

    print(f"  {'항목':22} {'금액':>10} {'근원 대비':>9}")
    for label, names in GROUPS.items():
        amt, miss = amount(names)
        missing += miss
        w = amt / core * 100 if core else 0
        print(f"  {label:22} {amt:10,.1f} {w:8.2f}%")

    if missing:
        print("\n  ⚠ 이름을 못 찾은 줄 (BEA 표기가 다를 수 있음):")
        for n in dict.fromkeys(missing):
            print(f"      {n}")
        print("  → U20405 의 비슷한 줄을 찾아 GROUPS 를 고치세요. 후보:")
        for n in dict.fromkeys(missing):
            k = norm(n).split()[0]
            cand = [x for x in by_name if k in x][:4]
            print(f"      {n} ~ {cand}")


if __name__ == "__main__":
    main()

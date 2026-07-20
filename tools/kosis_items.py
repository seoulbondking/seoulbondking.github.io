"""KOSIS 통계표에 어떤 항목(ITM)이 있는지 나열하는 도구.

통계청 공표 기여도(전년동월비 기여도 등)가 어느 표·항목에 있는지 찾을 때 사용.

사용법 (PC의 venv 파이썬):
    python tools/kosis_items.py                # 품목성질별 표 (DT_1J22002)
    python tools/kosis_items.py DT_1J22003     # 다른 표 지정
    python tools/kosis_items.py DT_1J22003 101 # 표 + orgId 지정

최근 1개월 데이터를 itmId=ALL 로 조회해 ITM_ID / ITM_NM 목록을 출력한다.
'기여도' 항목이 보이면 그 ITM_ID 를 indicators.yaml 에 쓰면 된다.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
BASE = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


def load_dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main():
    load_dotenv()
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        sys.exit("KOSIS_API_KEY 가 없습니다 (.env 확인)")

    tbl = sys.argv[1] if len(sys.argv) > 1 else "DT_1J22002"
    org = sys.argv[2] if len(sys.argv) > 2 else "101"

    # 표마다 분류축(objL) 개수가 달라서 여러 조합을 시도
    obj_variants = [
        {"objL1": "ALL", "objL2": "ALL"},
        {"objL1": "T10 ", "objL2": "ALL"},
        {"objL1": "ALL"},
        {"objL1": "ALL", "objL2": "ALL", "objL3": "ALL"},
        {"objL1": "0 "},
    ]
    # 최근 3개월 중 데이터가 있는 달을 찾아 조회
    today = date.today().replace(day=1)
    data = None
    for back in range(1, 4):
        m = today - timedelta(days=1)
        for _ in range(back - 1):
            m = m.replace(day=1) - timedelta(days=1)
        prd = f"{m.year}{m.month:02d}"
        base_params = {
            "method": "getList", "apiKey": key, "format": "json", "jsonVD": "Y",
            "prdSe": "M", "startPrdDe": prd, "endPrdDe": prd,
            "itmId": "ALL",
            "outputFields": "TBL_NM OBJ_NM NM ITM_NM UNIT_NM PRD_DE ",
            "orgId": org, "tblId": tbl,
        }
        for ov in obj_variants:
            r = requests.get(BASE, params={**base_params, **ov}, timeout=60)
            data = r.json()
            if isinstance(data, list) and data:
                print(f"(조회 성공: {prd}, objL 조합 {ov})")
                break
        if isinstance(data, list) and data:
            break
    else:
        sys.exit(f"조회 실패: {data}")

    print(f"\n표: {data[0].get('TBL_NM')} ({tbl}) · 시점 {data[0].get('PRD_DE')}\n")
    seen = {}
    for row in data:
        iid = row.get("ITM_ID", "")
        nm = row.get("ITM_NM", "")
        unit = row.get("UNIT_NM", "")
        c1 = row.get("C1_NM", "")
        if iid not in seen:
            seen[iid] = (nm, unit, c1, row.get("DT"))
    print(f"{'ITM_ID':12s} {'항목명':28s} {'단위':8s} 예시값")
    for iid, (nm, unit, c1, v) in seen.items():
        mark = "  ← 기여도!" if "기여" in nm else ""
        print(f"{iid:12s} {nm:28s} {unit:8s} {c1}={v}{mark}")


if __name__ == "__main__":
    main()

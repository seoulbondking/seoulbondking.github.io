"""부동산원 R-ONE 통계표의 지역 분류(CLS_ID) 목록 조회 도구.

사용법:
    python tools/reb_cls.py                    # 주간 아파트 매매가격지수 표
    python tools/reb_cls.py T247713133046872   # 다른 통계표 ID 지정

CLS_ID 없이 최근 데이터를 조회해서 응답에 나오는 모든 지역 분류를 나열한다.
결과를 보고 indicators.yaml 의 cls_ids 에 원하는 지역을 추가하면 된다.
"""
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
BASE_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"


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
    key = os.environ.get("REB_API_KEY", "").strip()
    if not key:
        sys.exit("REB_API_KEY 가 없습니다 (.env 확인)")

    statbl_id = sys.argv[1] if len(sys.argv) > 1 else "T244183132827305"
    start = f"{date.today().year}01"   # 올해 데이터만 (분류 나열 목적)

    found = {}
    for page in range(1, 11):          # 최대 10페이지(10,000행)
        params = {
            "KEY": key, "pIndex": str(page), "pSize": "1000",
            "STATBL_ID": statbl_id, "DTACYCLE_CD": "WK",
            "START_WRTTIME": start,
        }
        resp = requests.get(BASE_URL, params=params, timeout=60)
        root = ET.fromstring(resp.content)
        rows = root.findall(".//row")
        if not rows:
            if page == 1:
                msg = (root.findtext(".//message") or root.findtext(".//MESSAGE") or "").strip()
                print("응답에 데이터가 없습니다.", msg)
            break
        for r in rows:
            cid = (r.findtext("CLS_ID") or "").strip()
            nm = (r.findtext("CLS_NM") or "").strip()
            itm = (r.findtext("ITM_NM") or "").strip()
            iid = (r.findtext("ITM_ID") or "").strip()
            if cid:
                found.setdefault(cid, [nm, set()])[1].add(f"{iid}:{itm}")
        if len(rows) < 1000:
            break

    print(f"\n통계표 {statbl_id} — 지역 분류 {len(found)}개\n")
    print(f"{'CLS_ID':10s} {'지역명':16s} 항목(ITM)")
    for cid in sorted(found):
        nm, itms = found[cid]
        print(f"{cid:10s} {nm:16s} {' / '.join(sorted(itms))}")


if __name__ == "__main__":
    main()

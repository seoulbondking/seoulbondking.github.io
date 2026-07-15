"""부동산원 R-ONE OpenAPI 수집기 (주간 아파트 지수 등).

API 키는 환경변수 REB_API_KEY 로 전달합니다.
응답은 XML이며, 시리즈명은 응답의 CLS_NM(지역명)을 그대로 사용합니다.
"""
import os
import re
import calendar
import xml.etree.ElementTree as ET
from datetime import date

import requests

BASE_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"


class RebError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("REB_API_KEY", "").strip()
    if not key:
        raise RebError(
            "환경변수 REB_API_KEY 가 없습니다. "
            "로컬: .env 파일 / GitHub: Actions Secret 등록"
        )
    return key


def _to_date(row, cycle: str = "WK") -> str | None:
    """시점 필드를 'YYYY-MM-DD'로 변환.

    주간(WK) 통계의 WRTTIME_IDTFR_ID는 'YYYYWW'(연도+주차, 예: 202413 = 2024년 13주차)
    형식이므로 해당 주 월요일 날짜로 변환한다. 월간은 'YYYYMM' → 월말일.
    """
    digits = re.sub(r"\D", "", row.findtext("WRTTIME_IDTFR_ID") or "")
    if len(digits) >= 8:                           # YYYYMMDD
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) == 6:
        y, n = int(digits[:4]), int(digits[4:6])
        if cycle == "WK":                          # YYYYWW → 해당 주 월요일
            try:
                return date.fromisocalendar(y, n, 1).isoformat()
            except ValueError:
                pass
        elif 1 <= n <= 12:                         # YYYYMM → 월말일
            return f"{y}-{n:02d}-{calendar.monthrange(y, n)[1]:02d}"
    # 폴백: WRTTIME_DESC '2024년 01월 1주' / '2024년 01월'
    m = re.search(r"(\d{4})\D+(\d{1,2})\s*월(?:\D+(\d{1,2})\s*주)?",
                  row.findtext("WRTTIME_DESC") or "")
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            return None
        if m.group(3):                             # N주 → 대략적인 날짜
            day = min((int(m.group(3)) - 1) * 7 + 1, calendar.monthrange(y, mo)[1])
            return f"{y}-{mo:02d}-{day:02d}"
        return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
    return None


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 정의 하나 → 시리즈 목록 (kosis/ecos 와 동일 형식)."""
    key = _api_key()
    p = indicator["params"]
    start_year = indicator.get("_start_year") \
        or date.today().year - indicator.get("lookback_years", 5)

    series = []
    for cls_id in p["cls_ids"]:
        params = {
            "KEY": key,
            "pIndex": "1",
            "pSize": "1000",
            "STATBL_ID": p["statbl_id"],
            "DTACYCLE_CD": p.get("cycle", "WK"),
            "CLS_ID": str(cls_id),
            "ITM_ID": p.get("itm_id", "10001"),
            "START_WRTTIME": f"{start_year}01",
        }
        resp = requests.get(BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        rows = root.findall(".//row")
        if not rows:
            msg = (root.findtext(".//message") or root.findtext(".//MESSAGE")
                   or root.findtext(".//RESULT/MESSAGE") or "row 없음")
            print(f"  [reb {p['statbl_id']}/{cls_id}] 데이터 없음: {msg.strip()}")
            continue

        name = (rows[0].findtext("CLS_NM") or str(cls_id)).strip()
        cycle = p.get("cycle", "WK")
        pts = []
        for row in rows:
            d = _to_date(row, cycle)
            try:
                v = float(row.findtext("DTA_VAL"))
            except (TypeError, ValueError):
                continue
            if d:
                pts.append({"d": d, "v": v})
        if pts:
            series.append({"name": name, "data": sorted(pts, key=lambda x: x["d"])})

    if not series:
        raise RebError("수집된 시리즈가 없습니다 (API 키·파라미터 확인)")
    return series

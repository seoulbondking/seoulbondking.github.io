"""부동산원 R-ONE OpenAPI 수집기 (주간 아파트 지수 등).

API 키는 환경변수 REB_API_KEY 로 전달합니다.
응답은 XML이며, CLS_ID(지역 코드) 기준으로 저장하므로 이름이 같은 지역
(서울 중구 vs 부산 중구 등)이 서로 섞이지 않습니다.
"""
import os
import re
import calendar
import xml.etree.ElementTree as ET
from datetime import date, timedelta

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

    주간(WK)의 WRTTIME_IDTFR_ID는 'YYYYWW'(연도+주차) 형식이므로 해당 주 월요일로,
    월간은 'YYYYMM' → 월말일로 변환한다.
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
        if m.group(3):
            day = min((int(m.group(3)) - 1) * 7 + 1, calendar.monthrange(y, mo)[1])
            return f"{y}-{mo:02d}-{day:02d}"
        return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
    return None


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 정의 하나 → 시리즈 목록 (kosis/ecos 와 동일 형식)."""
    key = _api_key()
    p = indicator["params"]
    cycle = p.get("cycle", "WK")
    start_year = indicator.get("_start_year") \
        or date.today().year - indicator.get("lookback_years", 5)

    # cls_ids 를 지정하면 그 지역만, 없으면 통계표의 모든 지역을 수집.
    # CLS_ID 기준 저장 → 이름이 같은 지역이 섞이지 않는다.
    cls_ids = p.get("cls_ids")
    by_cid: dict[str, dict] = {}   # CLS_ID → {name, pts}

    # 페이지 상한. 여기에 걸리면 응답이 잘린 것이므로 조용히 넘어가지 않고 멈춘다.
    #   2026-09-18 실제 사고: 주간 아파트(239개 지역 × 약 90주 ≈ 21,500행)가 옛 상한
    #   20페이지(20,000행)를 넘겨, 뒤쪽 92개 지역만 최신 주차를 못 받고 잘렸다.
    #   값이 그럴듯해서 화면에서는 '전국만 갱신된' 것처럼 보였다.
    MAX_PAGES = 60

    def collect(params):
        for page in range(1, MAX_PAGES + 1):
            params["pIndex"] = str(page)
            resp = requests.get(BASE_URL, params=params, timeout=60)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            rows = root.findall(".//row")
            if not rows:
                if page == 1:
                    msg = (root.findtext(".//message") or root.findtext(".//MESSAGE")
                           or root.findtext(".//RESULT/MESSAGE") or "row 없음")
                    print(f"  [reb {p['statbl_id']}] 데이터 없음: {msg.strip()}")
                return
            for row in rows:
                cid = (row.findtext("CLS_ID") or "").strip()
                name = (row.findtext("CLS_NM") or cid).strip()
                d = _to_date(row, cycle)
                try:
                    v = float(row.findtext("DTA_VAL"))
                except (TypeError, ValueError):
                    continue
                if cid and d:
                    rec = by_cid.setdefault(cid, {"name": name, "pts": []})
                    rec["pts"].append({"d": d, "v": v})
            if len(rows) < 1000:
                return
        raise RebError(
            f"'{p['statbl_id']}' 응답이 {MAX_PAGES}페이지({MAX_PAGES * 1000}행)를 넘었습니다. "
            "조회 구간이 너무 넓어 뒤쪽 지역이 잘립니다 — "
            "indicators.yaml 에서 lookback_weeks 를 줄이거나 MAX_PAGES 를 늘리세요.")

    # 조회 시작 시점.
    #   주간은 지역 수가 많아(239개) 연 단위로 잡으면 금세 수만 행이 된다.
    #   증분 수집이면 lookback_weeks 만큼만 거슬러 받는다 — 나머지는 아카이브가 들고 있다.
    #   전체 재수집(--full, 아카이브 없음)일 때는 무시하고 연 단위로 통째로 받는다.
    lookback_weeks = p.get("lookback_weeks")
    if cycle == "WK" and lookback_weeks and indicator.get("_has_archive") \
            and not indicator.get("_full"):
        iso = (date.today() - timedelta(weeks=int(lookback_weeks))).isocalendar()
        start_wrttime = f"{iso[0]}{iso[1]:02d}"
    else:
        start_wrttime = f"{start_year}01"

    base = {
        "KEY": key, "pSize": "1000",
        "STATBL_ID": p["statbl_id"], "DTACYCLE_CD": cycle,
        "ITM_ID": p.get("itm_id", "10001"),
        "START_WRTTIME": start_wrttime,
    }
    if cls_ids:
        for cid in cls_ids:
            collect({**base, "CLS_ID": str(cid)})
    else:
        collect(dict(base))              # CLS_ID 생략 → 전 지역

    # 이름이 여러 CLS_ID 에 걸치면(중구·동구 등) 이름 뒤에 [CLS_ID] 를 붙여 구분
    name_count: dict[str, int] = {}
    for rec in by_cid.values():
        name_count[rec["name"]] = name_count.get(rec["name"], 0) + 1

    series = []
    for cid, rec in by_cid.items():
        nm = rec["name"]
        if name_count.get(nm, 0) > 1:
            nm = f"{nm} [{cid}]"
        series.append({
            "name": nm,
            "cid": cid,
            "data": sorted(rec["pts"], key=lambda x: x["d"]),
        })
    if not series:
        raise RebError("수집된 시리즈가 없습니다 (API 키·파라미터 확인)")

    # 잘림 재발 감지 — 최신 시점의 지역 수가 직전 시점보다 확 적으면 응답이 덜 온 것이다.
    # 값 자체는 멀쩡해 보여서 화면에서는 '일부 지역만 갱신된' 것처럼 나타난다.
    # 발표 중이라 실제로 덜 나온 경우도 같은 모양이므로, 막지 말고 눈에 띄게 알린다.
    cov: dict[str, int] = {}
    for s in series:
        for pt in s["data"]:
            cov[pt["d"]] = cov.get(pt["d"], 0) + 1
    ds = sorted(cov)
    if len(ds) >= 2:
        newest, prev = ds[-1], ds[-2]
        if cov[newest] < cov[prev] * 0.9:
            print(f"  ⚠ [reb {p['statbl_id']}] {newest} 지역 {cov[newest]}개 "
                  f"(직전 {prev} 은 {cov[prev]}개) — 응답이 잘렸거나 발표가 진행 중입니다. "
                  "잠시 뒤 다시 수집하면 채워집니다.")
    return series

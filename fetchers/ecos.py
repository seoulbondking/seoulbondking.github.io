"""ECOS(한국은행 경제통계시스템) OpenAPI 수집기.

API 키는 환경변수 ECOS_API_KEY 로 전달합니다.

indicators.yaml 에서의 사용 예:
  - id: kr_household_credit
    name: 가계신용 (용도별)
    source: ecos
    unit: 십억원
    freq: Q                  # ECOS cycle 로도 사용 (A/Q/M)
    lookback_years: 15
    params:
      stat_code: "151Y004"
      # item_codes: ["FME"]  # 특정 항목만 필요할 때 (생략하면 전체)
"""
import os
import calendar
from datetime import date

import requests

BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
PAGE_SIZE = 1000


class EcosError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("ECOS_API_KEY", "").strip()
    if not key:
        raise EcosError(
            "환경변수 ECOS_API_KEY 가 없습니다. "
            "로컬: .env 파일 / GitHub: Actions Secret 등록"
        )
    return key


def _period_range(cycle: str, start_year: int) -> tuple[str, str]:
    """ECOS 기간 표기: A='2024', Q='2024Q1', M='202401'."""
    today = date.today()
    if cycle == "Q":
        q = (today.month - 1) // 3 + 1
        return f"{start_year}Q1", f"{today.year}Q{q}"
    if cycle == "M":
        return f"{start_year}01", f"{today.year}{today.month:02d}"
    if cycle == "A":
        return str(start_year), str(today.year)
    raise EcosError(f"지원하지 않는 cycle: {cycle} (A/Q/M 만 지원)")


def _to_date(time_str: str, cycle: str) -> str:
    """ECOS TIME 코드 → 'YYYY-MM-DD' (기간 말일)."""
    time_str = str(time_str)
    year = int(time_str[:4])
    if cycle == "Q":                      # '2024Q1'
        month = int(time_str[-1]) * 3
    elif cycle == "M":                    # '202401'
        month = int(time_str[4:6])
    else:                                 # 'A': '2024'
        month = 12
    last = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-{last:02d}"


def _fetch_rows(key: str, stat_code: str, cycle: str,
                start: str, end: str, item_code: str | None) -> list[dict]:
    """한 (통계코드, 항목코드) 조합의 전체 행을 페이지네이션으로 수집."""
    path = f"{stat_code}/{cycle}/{start}/{end}"
    if item_code:
        path += f"/{item_code}"
    base = f"{BASE_URL}/{key}/json/kr"

    # 1단계: 전체 건수 확인
    first = requests.get(f"{base}/1/1/{path}", timeout=60).json()
    if "StatisticSearch" not in first:
        # ECOS는 오류 시 {"RESULT": {"CODE": ..., "MESSAGE": ...}} 반환
        raise EcosError(f"ECOS API 오류 ({stat_code}/{item_code}): {first}")
    total = int(first["StatisticSearch"]["list_total_count"])

    # 2단계: 1000행 단위로 전체 수집
    rows = []
    for s in range(1, total + 1, PAGE_SIZE):
        e = min(s + PAGE_SIZE - 1, total)
        chunk = requests.get(f"{base}/{s}/{e}/{path}", timeout=60).json()
        if "StatisticSearch" in chunk:
            rows.extend(chunk["StatisticSearch"]["row"])
    return rows


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 정의 하나 → 시리즈 목록 (kosis.fetch 와 동일 형식)."""
    key = _api_key()
    cycle = indicator["freq"]
    start_year = indicator.get("_start_year") \
        or date.today().year - indicator.get("lookback_years", 10)
    start, end = _period_range(cycle, start_year)
    p = indicator["params"]
    item_codes = p.get("item_codes") or [None]

    all_rows = []
    for code in item_codes:
        all_rows.extend(_fetch_rows(key, p["stat_code"], cycle, start, end, code))

    # 시리즈명 = ITEM_NAME1 [+ ITEM_NAME2 가 여럿이면 병기]
    name2s = {r.get("ITEM_NAME2") for r in all_rows if r.get("ITEM_NAME2")}
    multi2 = len(name2s) > 1

    series: dict[str, list] = {}
    for r in all_rows:
        name = (r.get("ITEM_NAME1") or "값").strip()
        if multi2 and r.get("ITEM_NAME2"):
            name = f"{name} · {r['ITEM_NAME2'].strip()}"
        try:
            value = float(r["DATA_VALUE"])
        except (KeyError, TypeError, ValueError):
            continue
        series.setdefault(name, []).append(
            {"d": _to_date(r["TIME"], cycle), "v": value}
        )

    return [
        {"name": name, "data": sorted(points, key=lambda pt: pt["d"])}
        for name, points in series.items()
    ]

"""BLS(미국 노동통계국) OpenAPI v2 수집기.

API 키는 환경변수 BLS_API_KEY 로 전달합니다.

indicators.yaml 사용 예:
  - id: us_labor
    name: 미국 고용지표 (비율)
    source: bls
    unit: '%'
    freq: M
    start_year: 2005
    refetch_years: 2
    params:
      series:                     # 시리즈코드: 표시이름
        LNS14000000: 실업률
        LNS13327709: U-6 실업률
"""
import os
import calendar
from datetime import date

import requests

URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
# 등록키: 50시리즈·20년 / 무키: 25시리즈·10년
LIMITS = {True: (50, 20), False: (25, 10)}


class BlsError(RuntimeError):
    pass


def _to_date(year: str, period: str) -> str | None:
    """BLS year+period → 'YYYY-MM-DD'(기간 말일). 월(M01~M12)·분기(Q01~Q04)만."""
    y = int(year)
    if period.startswith("M"):
        m = int(period[1:])
        if m > 12:                 # M13 = 연평균 → 제외
            return None
    elif period.startswith("Q"):
        m = int(period[1:]) * 3
    else:
        return None                # 반기·연간 등 제외
    last = calendar.monthrange(y, m)[1]
    return f"{y}-{m:02d}-{last:02d}"


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _run(codes, start_year, end_year, key):
    """key 유무에 맞는 한도로 전 구간 수집. 실패 메시지는 BlsError로 던짐."""
    max_series, max_years = LIMITS[bool(key)]
    y_start = start_year if key else max(start_year, end_year - (max_years - 1))
    collected = {c: {} for c in codes}
    y0 = y_start
    while y0 <= end_year:
        y1 = min(y0 + max_years - 1, end_year)
        for cc in _chunks(codes, max_series):
            payload = {"seriesid": cc, "startyear": str(y0), "endyear": str(y1)}
            if key:
                payload["registrationkey"] = key
            resp = requests.post(URL, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "REQUEST_SUCCEEDED":
                raise BlsError("; ".join(data.get("message", []) or [str(data.get("status"))]))
            for s in data["Results"]["series"]:
                sid = s["seriesID"]
                for row in s.get("data", []):
                    d = _to_date(row["year"], row["period"])
                    if d is None:
                        continue
                    try:
                        collected[sid][d] = float(str(row["value"]).replace(",", ""))
                    except (KeyError, TypeError, ValueError):
                        continue
        y0 = y1 + 1
    return collected


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 하나 → 시리즈 목록 (kosis/ecos 와 동일 형식).

    등록키(BLS_API_KEY)가 있으면 20년까지, 무효/없으면 무키 모드(최근 10년)로 자동 폴백.
    """
    key = os.environ.get("BLS_API_KEY", "").strip()
    p = indicator["params"]
    series = p["series"]
    codes = list(series.keys())
    names = series if isinstance(series, dict) else {c: c for c in series}
    start_year = int(indicator.get("_start_year")
                     or date.today().year - indicator.get("lookback_years", 20))
    end_year = date.today().year

    try:
        collected = _run(codes, start_year, end_year, key)
    except BlsError as e:
        if key and "invalid" in str(e).lower():
            print(f"  [bls {indicator.get('id', '?')}] 등록키 무효 → 무키 모드(최근 10년)로 재시도")
            collected = _run(codes, start_year, end_year, "")
        else:
            raise BlsError(f"BLS API 오류: {e}")

    return [
        {"name": names[c], "data": [{"d": d, "v": v}
                                    for d, v in sorted(collected[c].items())]}
        for c in codes
    ]

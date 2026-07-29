"""FRED(세인트루이스 연준) API 수집기 — 유가·환율·미국 금리 등 일별 시장데이터.

API 키는 환경변수 FRED_API_KEY 로 전달합니다.

indicators.yaml 사용 예:
  - id: mkt_oil
    name: 국제유가
    source: fred
    unit: 달러/배럴
    freq: D
    start_year: 2013
    merge_always: true
    params:
      series:                    # FRED 시리즈ID: 표시이름
        DCOILBRENTEU: 브렌트유
        DCOILWTICO: WTI
"""
import os
from datetime import date

import requests

URL = "https://api.stlouisfed.org/fred/series/observations"


class FredError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise FredError("환경변수 FRED_API_KEY 가 없습니다. (.env 또는 Actions Secret)")
    return key


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 하나 → 시리즈 목록 (kosis/ecos 와 동일 형식)."""
    key = _api_key()
    p = indicator["params"]
    series = p["series"]
    names = series if isinstance(series, dict) else {c: c for c in series}

    start_year = indicator.get("_start_year") or indicator.get("start_year") \
        or date.today().year - indicator.get("lookback_years", 15)
    start = f"{int(start_year)}-01-01"

    out = []
    for sid, label in names.items():
        try:
            r = requests.get(URL, params={
                "series_id": sid, "api_key": key, "file_type": "json",
                "observation_start": start,
            }, timeout=60)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [fred {indicator.get('id','?')}] {sid} 실패(무시): {e}")
            continue
        if "observations" not in data:
            print(f"  [fred] {sid} 응답 오류(무시): {str(data)[:120]}")
            continue
        pts = []
        for o in data["observations"]:
            v = o.get("value")
            if v in (None, "", "."):        # FRED 결측치는 '.'
                continue
            try:
                pts.append({"d": o["date"], "v": float(v)})
            except (KeyError, ValueError):
                continue
        if pts:
            out.append({"name": label, "data": sorted(pts, key=lambda x: x["d"])})

    if not out:
        raise FredError("FRED 응답에서 데이터를 얻지 못했습니다 (시리즈ID/키 확인)")
    return out

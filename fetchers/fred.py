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
from datetime import date, timedelta

import requests

URL = "https://api.stlouisfed.org/fred/series/observations"


def _period_end(d: str, freq: str) -> str:
    """FRED 는 월·분기 관측치를 기간 '첫날'로 준다 (2026년 8월 → 2026-08-01).

    BLS·BEA 수집기는 월말(2026-08-31)로 맞춰 두었으므로, 그대로 섞으면
    같은 달인데 날짜가 달라 대시보드 가로축에서 두 칸으로 갈라진다.
    """
    if freq not in ("M", "Q", "A"):
        return d
    try:
        y, m, _ = (int(x) for x in d.split("-"))
    except ValueError:
        return d
    if freq == "Q":
        m = ((m - 1) // 3) * 3 + 3
    elif freq == "A":
        m = 12
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


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
    # 시리즈별 단위 환산 배수. FRED 는 같은 표라도 단위가 섞인다.
    #   예) WRESBAL·RRPONTSYD 는 십억달러인데 WTREGEN 은 '백만달러'라 1000배 크다.
    #       params.scale: {WTREGEN: 0.001} 로 수집 단계에서 맞춰 둔다.
    scale = p.get("scale") or {}
    freq = indicator.get("freq", "D")

    start_year = indicator.get("_start_year") or indicator.get("start_year") \
        or date.today().year - indicator.get("lookback_years", 15)
    start = f"{int(start_year)}-01-01"

    out = []
    for sid, label in names.items():
        try:
            q = {"series_id": sid, "api_key": key, "file_type": "json",
                 "observation_start": start}
            # 일별 계열을 월별로 받고 싶을 때: params.frequency: m (+ aggregation_method)
            #   FRED 가 서버에서 집계해 주므로 같은 달에 여러 점이 생기지 않는다.
            if p.get("frequency"):
                q["frequency"] = p["frequency"]
                q["aggregation_method"] = p.get("aggregation_method", "avg")
            r = requests.get(URL, params=q, timeout=60)
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
                pts.append({"d": _period_end(o["date"], freq),
                            "v": float(v) * float(scale.get(sid, 1))})
            except (KeyError, ValueError):
                continue
        if pts:
            out.append({"name": label, "data": sorted(pts, key=lambda x: x["d"])})

    if not out:
        raise FredError("FRED 응답에서 데이터를 얻지 못했습니다 (시리즈ID/키 확인)")
    return out

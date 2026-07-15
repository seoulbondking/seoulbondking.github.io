"""KOSIS(국가통계포털) OpenAPI 수집기.

API 키는 환경변수 KOSIS_API_KEY 로 전달합니다 (코드에 하드코딩 금지).
"""
import os
import calendar
from datetime import date

import requests

BASE_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
OUTPUT_FIELDS = "TBL_NM OBJ_NM NM ITM_NM UNIT_NM PRD_SE PRD_DE LST_CHN_DE "


class KosisError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        raise KosisError(
            "환경변수 KOSIS_API_KEY 가 없습니다. "
            "로컬: .env 파일 또는 set KOSIS_API_KEY=... / GitHub: Actions Secret 등록"
        )
    return key


def _period_range(freq: str, start_year: int) -> tuple[str, str]:
    """freq(Q/M)에 맞는 startPrdDe, endPrdDe 문자열 생성."""
    today = date.today()
    if freq == "Q":
        end_q = (today.month - 1) // 3 + 1
        return f"{start_year}01", f"{today.year}0{end_q}"
    return f"{start_year}01", f"{today.year}{today.month:02d}"


def _to_date(prd_de: str, freq: str) -> str:
    """KOSIS PRD_DE('20241' 분기 / '202401' 월) → 'YYYY-MM-DD' (기간 말일)."""
    year = int(prd_de[:4])
    rest = int(prd_de[4:])
    if freq == "Q":
        month = rest * 3
    else:
        month = rest
    last = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-{last:02d}"


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 의 지표 정의 하나를 받아 시리즈 목록을 반환.

    반환 형식: [{"name": 시리즈명, "data": [{"d": "YYYY-MM-DD", "v": 값}, ...]}, ...]
    """
    freq = indicator["freq"]
    start_year = indicator.get("_start_year") \
        or date.today().year - indicator.get("lookback_years", 10)
    start, end = _period_range(freq, start_year)

    params = {
        "method": "getList",
        "apiKey": _api_key(),
        "format": "json",
        "jsonVD": "Y",
        "prdSe": freq,
        "startPrdDe": start,
        "endPrdDe": end,
        "outputFields": OUTPUT_FIELDS,
        **indicator["params"],
    }
    resp = requests.get(BASE_URL, params=params, timeout=60)
    resp.raise_for_status()
    rows = resp.json()

    # KOSIS는 오류 시 dict({"err": ..., "errMsg": ...})를 반환
    if isinstance(rows, dict):
        raise KosisError(f"KOSIS API 오류: {rows}")

    # 시리즈명 = 분류명(C1_NM) [+ 항목명(ITM_NM) 이 여럿이면 병기]
    itm_names = {r.get("ITM_NM") for r in rows}
    multi_itm = len(itm_names) > 1

    # 같은 이름이 서로 다른 분류코드(C1)로 중복되면 코드로 구분
    # (예: GDP 통계에서 '(재화)F.O.B. 기준'이 수출/수입 하위에 각각 존재)
    name_codes: dict[str, set] = {}
    for r in rows:
        nm = r.get("C1_NM") or r.get("ITM_NM") or "값"
        name_codes.setdefault(nm, set()).add(r.get("C1", ""))
    dup_names = {nm for nm, codes in name_codes.items() if len(codes) > 1}

    series: dict[str, list] = {}
    for r in rows:
        name = r.get("C1_NM") or r.get("ITM_NM") or "값"
        if name in dup_names:
            name = f"{name} [{r.get('C1', '')}]"
        if multi_itm:
            name = f"{name} · {r.get('ITM_NM')}"
        try:
            value = float(r["DT"])
        except (KeyError, TypeError, ValueError):
            continue
        series.setdefault(name, []).append(
            {"d": _to_date(r["PRD_DE"], freq), "v": value}
        )

    return [
        {"name": name, "data": sorted(points, key=lambda p: p["d"])}
        for name, points in series.items()
    ]

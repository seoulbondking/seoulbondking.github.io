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
    today = date.today()

    def prd(y, last_of_year):
        """연도 y의 시작/끝 기간 코드 (올해면 현재 시점까지)."""
        if not last_of_year:
            return f"{y}01"
        if y >= today.year:
            return (f"{today.year}0{(today.month - 1) // 3 + 1}" if freq == "Q"
                    else f"{today.year}{today.month:02d}")
        return f"{y}04" if freq == "Q" else f"{y}12"

    base_params = {
        "method": "getList",
        "apiKey": _api_key(),
        "format": "json",
        "jsonVD": "Y",
        "prdSe": freq,
        "outputFields": OUTPUT_FIELDS,
        **indicator["params"],
    }

    def get_range(y0, y1):
        """y0~y1 구간 수집. 40,000셀 초과(err 31)면 반으로 쪼개 재귀."""
        resp = requests.get(BASE_URL, params={
            **base_params, "startPrdDe": prd(y0, False), "endPrdDe": prd(y1, True),
        }, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            if str(data.get("err", "")).strip() == "31" and y1 > y0:
                mid = (y0 + y1) // 2
                print(f"  [kosis {indicator['id']}] 셀 한도 초과 → {y0}~{mid} / {mid+1}~{y1} 분할")
                return get_range(y0, mid) + get_range(mid + 1, y1)
            raise KosisError(f"KOSIS API 오류: {data}")
        return data

    rows = get_range(start_year, today.year)

    # 시리즈명 = 가장 깊은 분류명 (objL2 를 쓰면 C2_NM, 없으면 C1_NM)
    def deepest(r, suffix="_NM"):
        for k in ("C4", "C3", "C2", "C1"):
            v = r.get(k + suffix)
            if v:
                return v.strip() if suffix == "_NM" else v
        return None

    itm_names = {r.get("ITM_NM") for r in rows}
    multi_itm = len(itm_names) > 1

    # 같은 이름이 서로 다른 분류코드로 중복되면 코드로 구분
    name_codes: dict[str, set] = {}
    for r in rows:
        nm = deepest(r) or r.get("ITM_NM") or "값"
        name_codes.setdefault(nm, set()).add(deepest(r, "") or "")
    dup_names = {nm for nm, codes in name_codes.items() if len(codes) > 1}

    series: dict[str, list] = {}
    for r in rows:
        name = deepest(r) or r.get("ITM_NM") or "값"
        if name in dup_names:
            name = f"{name} [{deepest(r, '') or ''}]"
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

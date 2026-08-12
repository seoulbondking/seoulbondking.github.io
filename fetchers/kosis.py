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
    """freq(H/Q/M)에 맞는 startPrdDe, endPrdDe 문자열 생성."""
    today = date.today()
    if freq == "H":                      # 반기 (지역별고용조사 등): '20261'=상반기
        return f"{start_year}1", f"{today.year}{1 if today.month <= 6 else 2}"
    if freq == "Q":
        end_q = (today.month - 1) // 3 + 1
        return f"{start_year}01", f"{today.year}0{end_q}"
    return f"{start_year}01", f"{today.year}{today.month:02d}"


def _to_date(prd_de: str, freq: str) -> str:
    """KOSIS PRD_DE → 'YYYY-MM-DD' (기간 말일).

    '20241'=분기 · '202401'=월 · '20261'=반기(H, 1=상반기→6월말, 2=하반기→12월말)
    """
    year = int(prd_de[:4])
    rest = int(prd_de[4:])
    if freq == "H":
        month = 6 if rest == 1 else 12
    elif freq == "Q":
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
        if freq == "H":                              # 반기: '20261'/'20262'
            if not last_of_year:
                return f"{y}1"
            return f"{y}{1 if (y >= today.year and today.month <= 6) else 2}"
        if not last_of_year:
            return f"{y}01"
        if y >= today.year:
            return (f"{today.year}0{(today.month - 1) // 3 + 1}" if freq == "Q"
                    else f"{today.year}{today.month:02d}")
        return f"{y}04" if freq == "Q" else f"{y}12"

    # params.tables : 산업분류 개편 등으로 통계표가 갈린 계열을 이어 붙인다.
    #   예) 사업체노동력조사 임금 = 2020~2025 는 10차(MON051), 2026~ 은 11차(MON054)
    #   각 항목은 base 파라미터를 덮어쓰며, from/to 로 그 표의 수록 연도를 제한한다.
    #     tables:
    #       - {tblId: DT_118N_MON051, objL1: "...10S0 ", to: 2025}
    #       - {tblId: DT_118N_MON054, objL1: "...11S0 ", from: 2026}
    #   시리즈명이 같으면 자동으로 한 계열로 합쳐진다.
    p = dict(indicator["params"])
    segments = p.pop("tables", None) or [{}]
    # code_suffix: 시리즈명 뒤에 분류코드를 ' [코드]' 로 항상 붙인다.
    #   산업 대/중/소분류처럼 코드 자릿수로 계층을 알아내야 할 때 쓴다.
    #   대시보드의 baseName() 이 ' [..]' 를 떼어내므로 표시에는 지장이 없다.
    code_suffix = bool(p.pop("code_suffix", False))
    # name_axes: 분류축이 둘 이상일 때 이름을 'C1_NM · C2_NM' 으로 합친다.
    #   기본(deepest)은 가장 깊은 축 하나만 써서, 연령×활동상태처럼 두 축이 다 필요한
    #   표에서는 이름이 겹쳐 시리즈가 뭉개진다.
    name_axes = bool(p.pop("name_axes", False))

    base_params = {
        "method": "getList",
        "apiKey": _api_key(),
        "format": "json",
        "jsonVD": "Y",
        "prdSe": freq,
        **p,
    }
    # outputFields 를 지정하면 분류'명'만 오고 분류'코드'(C1/C2…)가 빠진다.
    # code_suffix 를 쓸 때는 필드를 제한하지 않아 코드까지 받는다.
    if not code_suffix:
        base_params["outputFields"] = OUTPUT_FIELDS

    def get_range(y0, y1, seg):
        """y0~y1 구간 수집. 40,000셀 초과(err 31)면 반으로 쪼개 재귀."""
        resp = requests.get(BASE_URL, params={
            **base_params, **{k: v for k, v in seg.items() if k not in ("from", "to")},
            "startPrdDe": prd(y0, False), "endPrdDe": prd(y1, True),
        }, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            if str(data.get("err", "")).strip() == "31" and y1 > y0:
                mid = (y0 + y1) // 2
                print(f"  [kosis {indicator['id']}] 셀 한도 초과 → {y0}~{mid} / {mid+1}~{y1} 분할")
                return get_range(y0, mid, seg) + get_range(mid + 1, y1, seg)
            raise KosisError(f"KOSIS API 오류: {data}")
        return data

    rows = []
    for seg in segments:
        y0 = max(start_year, int(seg.get("from", start_year)))
        y1 = min(today.year, int(seg.get("to", today.year)))
        if y0 > y1:
            continue
        try:
            got = get_range(y0, y1, seg)
        except KosisError as e:
            # 표가 여러 개일 때 하나가 비어도 나머지는 살린다 (개편 직후 등)
            if len(segments) == 1:
                raise
            print(f"  [kosis {indicator['id']}] {seg.get('tblId', '?')} {y0}~{y1} 건너뜀: {e}")
            continue
        if len(segments) > 1:
            print(f"  [kosis {indicator['id']}] {seg.get('tblId', '?')} {y0}~{y1} → {len(got)}행")
        rows += got

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

    # 값이 실제로 여러 개인 축만 이름에 넣는다 (한 값으로 고정한 축은 군더더기)
    axes = [k for k in ("C1", "C2", "C3", "C4")
            if len({r.get(k + "_NM") for r in rows if r.get(k + "_NM")}) > 1] if name_axes else []
    series: dict[str, list] = {}
    for r in rows:
        name = (" · ".join((r.get(k + "_NM") or "").strip() for k in axes if r.get(k + "_NM"))
                if axes else None) or deepest(r) or r.get("ITM_NM") or "값"
        if code_suffix or (not axes and name in dup_names):
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

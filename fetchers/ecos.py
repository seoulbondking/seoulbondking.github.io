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
ITEM_URL = "https://ecos.bok.or.kr/api/StatisticItemList"
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


def fetch_item_meta(key: str, stat_code: str) -> dict:
    """StatisticItemList 로 항목 가중치·계층 수집.

    반환: {"weights": {항목명: 가중치}, "top_level": [총지수 직속 대분류명, ...]}
    가중치는 매년 개편되며 최신 공표 가중치를 그대로 사용한다(하드코딩 불필요).
    실패해도 데이터 수집을 막지 않도록 호출부에서 예외를 흡수한다.
    """
    rows = []
    base = f"{ITEM_URL}/{key}/json/kr"
    first = requests.get(f"{base}/1/1/{stat_code}", timeout=60).json()
    if "StatisticItemList" not in first:
        raise EcosError(f"ECOS 항목목록 오류 ({stat_code}): {first}")
    total = int(first["StatisticItemList"]["list_total_count"])
    for s in range(1, total + 1, PAGE_SIZE):
        e = min(s + PAGE_SIZE - 1, total)
        chunk = requests.get(f"{base}/{s}/{e}/{stat_code}", timeout=60).json()
        if "StatisticItemList" in chunk:
            rows.extend(chunk["StatisticItemList"]["row"])

    weights, by_code, parent = {}, {}, {}
    for r in rows:
        nm = (r.get("ITEM_NAME") or "").strip()
        code = (r.get("ITEM_CODE") or "").strip()
        if not nm or not code:
            continue
        by_code[code] = nm
        parent[code] = (r.get("P_ITEM_CODE") or "").strip()
        try:
            weights[nm] = float(r["WGT"])
        except (KeyError, TypeError, ValueError):
            pass

    # 총지수(가중치 최대·최상위) 직속 자식 = 대분류
    total_code = None
    for code, nm in by_code.items():
        if nm == "총지수":
            total_code = code
            break
    if total_code is None and weights:
        # 이름이 '총지수'가 아니면 가중치 최대 항목을 총계로 간주
        top_nm = max(weights, key=weights.get)
        total_code = next((c for c, n in by_code.items() if n == top_nm), None)
    top_codes = [c for c, p in parent.items()
                 if p == total_code and by_code[c] != "총지수"]
    top_level = [by_code[c] for c in top_codes]
    children: dict[str, list] = {}
    for c, p in parent.items():
        if c != total_code:
            children.setdefault(p, []).append(c)
    return {"weights": weights, "top_level": top_level,
            "total_code": total_code, "top_codes": top_codes,
            "name_of": by_code, "children": children}


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 정의 하나 → 시리즈 목록 (kosis.fetch 와 동일 형식)."""
    key = _api_key()
    meta = None
    if indicator.get("with_weights"):
        try:
            meta = fetch_item_meta(key, indicator["params"]["stat_code"])
            indicator["_weights_meta"] = meta
        except Exception as e:  # 가중치 실패는 무시 (데이터는 계속 수집)
            print(f"  [ecos {indicator['id']}] 가중치 수집 실패(무시): {e}")
    cycle = indicator["freq"]
    start_year = indicator.get("_start_year") \
        or date.today().year - indicator.get("lookback_years", 10)
    start, end = _period_range(cycle, start_year)
    p = indicator["params"]
    item_codes = p.get("item_codes") or [None]
    # 기본분류(수백 품목)는 계층 레벨(levels)만큼만 수집 — 총지수 + 대분류(+중분류)
    #   levels=1: 총지수+대분류 / levels=2: +중분류. (top_level_only == levels=1)
    levels = indicator.get("levels") or (1 if indicator.get("top_level_only") else 0)
    if levels and meta and meta.get("children"):
        name_of = meta["name_of"]; children = meta["children"]; tc = meta["total_code"]
        codes = [tc]
        parents = {}                      # 항목명 → 상위 항목명 (트리 구성용)
        level_of = {"총지수": 0}
        l1 = children.get(tc, [])
        l1_names = {name_of[c] for c in l1}
        for c in l1:
            codes.append(c); parents[name_of[c]] = "총지수"; level_of[name_of[c]] = 1
        if levels >= 2:
            for c1 in l1:
                # 중분류 후보: 대분류의 자식. 단 동명 패스스루 노드는 그 자식으로 대체(평탄화)
                mid = []
                for c2 in children.get(c1, []):
                    if name_of[c2] == name_of[c1]:      # 동명 패스스루 → 한 단계 내려감
                        mid.extend(children.get(c2, []))
                    else:
                        mid.append(c2)
                for c3 in mid:
                    nm3 = name_of[c3]
                    if nm3 == name_of[c1] or nm3 == "총지수" or nm3 in l1_names:
                        continue
                    codes.append(c3); parents[nm3] = name_of[c1]; level_of[nm3] = 2
        item_codes = codes
        keep = {name_of[c] for c in codes}
        meta["weights"] = {n: w for n, w in (meta.get("weights") or {}).items() if n in keep}
        meta["parents"] = parents
        meta["level_of"] = level_of
    # 대용량 메타(name_of/children)는 payload에 싣지 않도록 제거
    if meta:
        meta.pop("name_of", None); meta.pop("children", None)
        meta.pop("total_code", None); meta.pop("top_codes", None)

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

"""CFTC 투기적 포지션 수집기 — COT(Commitments of Traders) 주간 보고.

엔캐리 분석의 세 번째 동인이다. IMF 논문 'Anatomy of Sudden Yen Appreciations'
는 급격한 엔 절상을 ① 미일 2년물 금리차 축소 ② VIX 상승 ③ 캐리 포지션 청산
세 가지로 설명하는데, ③의 대리변수로 쓰이는 게 CME 엔 선물의
비상업(non-commercial = 투기) 순포지션이다.

  순포지션 = 투기 롱 − 투기 숏
  음수(순매도)가 클수록 '엔을 빌려 다른 자산에 넣은' 포지션이 쌓였다는 뜻이고,
  이게 되감기면(숏커버) 엔이 급등한다.

공개 API (Socrata, 키 불필요):
  https://publicreporting.cftc.gov/resource/6dca-aqww.json
  화요일 기준 · 금요일 공표.

indicators.yaml 예:
  - id: mkt_cot_jpy
    name: 엔 투기포지션 (CFTC)
    source: cftc
    freq: W
    merge_always: true
    params:
      contracts:
        "097741": 엔          # JAPANESE YEN - CME
"""
from datetime import date

import requests

URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAGE = 5000
DEFAULT = {"097741": "엔"}


class CftcError(RuntimeError):
    pass


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse(rows: list[dict], label: str) -> list[dict]:
    """COT 레코드 → 시리즈 목록. 수집과 분리해 테스트할 수 있게 한다."""
    acc = {f"{label} 투기 순포지션": {}, f"{label} 투기 롱": {},
           f"{label} 투기 숏": {}, f"{label} 미결제약정": {}}
    for r in rows:
        d = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
        if len(d) != 10:
            continue
        lo = _num(r.get("noncomm_positions_long_all"))
        sh = _num(r.get("noncomm_positions_short_all"))
        oi = _num(r.get("open_interest_all"))
        if lo is not None and sh is not None:
            acc[f"{label} 투기 순포지션"][d] = lo - sh
            acc[f"{label} 투기 롱"][d] = lo
            acc[f"{label} 투기 숏"][d] = sh
        if oi is not None:
            acc[f"{label} 미결제약정"][d] = oi
    return [{"name": n, "data": [{"d": d, "v": v} for d, v in sorted(m.items())]}
            for n, m in acc.items() if m]


def _fetch_contract(code: str, start: str) -> list[dict]:
    """한 계약의 레코드를 페이지 단위로 모두 받는다."""
    out, off = [], 0
    while True:
        r = requests.get(URL, timeout=90, headers=UA, params={
            "cftc_contract_market_code": code,
            "$limit": PAGE, "$offset": off,
            "$order": "report_date_as_yyyy_mm_dd",
            "$where": f"report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'",
            "$select": ("report_date_as_yyyy_mm_dd,noncomm_positions_long_all,"
                        "noncomm_positions_short_all,open_interest_all"),
        })
        r.raise_for_status()
        js = r.json()
        out.extend(js)
        if len(js) < PAGE:
            return out
        off += PAGE


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 하나 → 시리즈 목록 (다른 수집기와 동일 형식)."""
    p = indicator.get("params") or {}
    contracts = p.get("contracts") or DEFAULT
    iid = indicator.get("id", "?")
    start_year = indicator.get("_start_year") or indicator.get("start_year") \
        or date.today().year - indicator.get("lookback_years", 15)
    start = f"{int(start_year)}-01-01"

    out = []
    for code, label in contracts.items():
        try:
            rows = _fetch_contract(str(code), start)
        except Exception as e:      # 계약 하나가 막혀도 나머지는 살린다
            print(f"  [cftc {iid}] {code}({label}) 실패(건너뜀): {str(e)[:150]}")
            continue
        got = parse(rows, label)
        if got:
            span = got[0]["data"][0]["d"] + " ~ " + got[0]["data"][-1]["d"]
            print(f"  [cftc {iid}] {code}({label}) → 시리즈 {len(got)}개, "
                  f"주간 {len(got[0]['data'])}건 ({span})")
        out.extend(got)
    if not out:
        raise CftcError(f"CFTC 응답이 비었습니다 ({iid}). 계약코드를 확인하세요.")
    return out

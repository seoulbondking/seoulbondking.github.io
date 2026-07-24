"""FREESIS(금융투자협회 자유통계) 수집기 — 펀드·투자일임·투자자예탁금.

FreeSIS 웹앱의 조회 엔드포인트(getMetaDataList.do)에 dmSearch JSON을 POST하면
JSON으로 응답한다. 공식 공개 API는 아니지만 날짜 범위를 한 번에 받을 수 있다.

수집 항목 (12개, 잔액):
  펀드/일임 11종 (설정원본·계약금액) : 공모/사모/일임 × 국내/해외 × 채권/MMF/주식
  투자자예탁금 1종

indicators.yaml 예:
  - id: kr_fund_flow
    name: 자금흐름 (펀드·예탁금)
    source: freesis
    unit: 조원
    freq: D
    lookback_days: 20          # 최근 N일 (첫 백필 시 크게)
    refetch_years: 0
    params: {}
"""
import os
from datetime import date, timedelta

import requests

META_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
INIT_URL = ("https://freesis.kofia.or.kr/stat/FreeSIS.do"
            "?parentDivId=MSIS40100000000000&serviceId=STATFND0100100260")

# 유형별기간설정 응답 컬럼(TMPV*) → 자산유형
COL = {"date": "TMPV1", "주식": "TMPV2", "채권": "TMPV5", "단기금융": "TMPV7", "합계": "TMPV15"}


class FreesisError(RuntimeError):
    pass


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": INIT_URL,
        "Origin": "https://freesis.kofia.or.kr",
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
    })
    try:
        s.get(INIT_URL, timeout=15)   # 쿠키 획득 (실패해도 진행)
    except Exception:
        pass
    return s


def _payload_fund(start, end, region, pub_priv):
    """펀드(설정원본). region 1=국내/4=해외, pub_priv 1=공모/2=사모."""
    return {"dmSearch": {
        "tmpV40": "100000000", "tmpV41": "1",
        "tmpV30": start, "tmpV31": end,
        "tmpV6": "1", "tmpV10": "0",
        "tmpV4": region, "tmpV7": pub_priv,
        "tmpV5": "", "tmpV11": "",
        "OBJ_NM": "STATFND0100100020BO",
    }}


def _payload_disc(start, end, region):
    """투자일임(계약금액). region 1=국내/2=해외."""
    return {"dmSearch": {
        "tmpV40": "100000000", "tmpV41": "1",
        "tmpV30": start, "tmpV31": end,
        "tmpV101": "1", "tmpV10": "0",
        "tmpV102": region, "tmpV11": "",
        "OBJ_NM": "STATFND0100100270BO",
    }}


def _payload_deposit(start, end):
    """증시자금추이 — 투자자예탁금."""
    return {"dmSearch": {
        "tmpV40": "1000000", "tmpV41": "1",
        "tmpV1": "D", "tmpV45": start, "tmpV46": end,
        "OBJ_NM": "STATSCU0100000060BO",
    }}


def _records(session, payload):
    """POST → 레코드(dict) 리스트."""
    resp = session.post(META_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    return next((v for v in data.values() if isinstance(v, list)), [])


def _to_date(s):
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s.replace("/", "-")


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 하나 → 시리즈 목록 (kosis/ecos 와 동일 형식)."""
    lookback = indicator.get("lookback_days", 20)
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=lookback)).strftime("%Y%m%d")
    s = _session()

    # 펀드/일임 원본 6개 호출 → {소스키: {date: {자산유형: 값}}}
    calls = {
        "펀드_공모_국내": _payload_fund(start, end, "1", "1"),
        "펀드_공모_해외": _payload_fund(start, end, "4", "1"),
        "펀드_사모_국내": _payload_fund(start, end, "1", "2"),
        "펀드_사모_해외": _payload_fund(start, end, "4", "2"),
        "일임_국내": _payload_disc(start, end, "1"),
        "일임_해외": _payload_disc(start, end, "2"),
    }
    src = {}
    for key, pl in calls.items():
        rows = _records(s, pl)
        by_date = {}
        for r in rows:
            d = _to_date(r.get(COL["date"]))
            by_date[d] = {typ: _num(r.get(code)) for typ, code in COL.items() if typ != "date"}
        src[key] = by_date

    # 11개 조합 (표시명, 소스키, 자산유형)
    combos = [
        ("공모 국내 채권", "펀드_공모_국내", "채권"),
        ("사모 국내 채권", "펀드_사모_국내", "채권"),
        ("일임 국내 채권", "일임_국내", "채권"),
        ("공모 국내 MMF", "펀드_공모_국내", "단기금융"),
        ("사모 국내 MMF", "펀드_사모_국내", "단기금융"),
        ("공모 국내 주식", "펀드_공모_국내", "주식"),
        ("공모 해외 주식", "펀드_공모_해외", "주식"),
        ("사모 국내 주식", "펀드_사모_국내", "주식"),
        ("사모 해외 주식", "펀드_사모_해외", "주식"),
        ("일임 국내 주식", "일임_국내", "주식"),
        ("일임 해외 주식", "일임_해외", "주식"),
    ]
    series = []
    for name, key, typ in combos:
        by_date = src.get(key, {})
        pts = [{"d": d, "v": vals.get(typ)} for d, vals in sorted(by_date.items()) if vals.get(typ) is not None]
        if pts:
            series.append({"name": name, "data": pts})

    # 투자자예탁금
    dep_rows = _records(s, _payload_deposit(start, end))
    dep = []
    for r in dep_rows:
        d = _to_date(r.get("TMPV1"))
        v = _num(r.get("TMPV2"))
        if v is not None:
            dep.append({"d": d, "v": v})
    if dep:
        series.append({"name": "고객예탁금", "data": sorted(dep, key=lambda p: p["d"])})

    if not series:
        raise FreesisError("FREESIS 응답에서 데이터를 얻지 못했습니다 (엔드포인트/파라미터 확인)")
    return series

"""BEA(미국 경제분석국) API 수집기 — NIPA 계정 (PCE 물가·실질소비·개인소득 등).

API 키는 환경변수 BEA_API_KEY 로 전달합니다. (https://apps.bea.gov/API/signup/)

FRED 대신 BEA 를 직접 부르는 이유:
  · FRED 는 BEA 표의 '일부 줄'만 별칭으로 올려둔다. 세부 항목은 대부분 없다.
  · FRED 별칭은 SA/NSA 구분이 이름에 드러나지 않아 섞이기 쉽다
    (예: PPIDGS 는 계절조정, PPIFDG 는 원계열 — 철자가 비슷하다).
  · BEA 는 표 하나를 통째로 주므로 계층·줄 순서가 원본 그대로 보존된다.

두 데이터셋을 쓴다:
  NIPA               — 표준 NIPA 표 (T20804 = 월별 PCE 물가지수, 주요 유형별)
  NIUnderlyingDetail — 세부 표 (U20404 = 월별 PCE 물가지수, 품목별 100줄 이상)

indicators.yaml 사용 예:
  - id: us_pce
    name: 미국 PCE
    source: bea
    unit: 지수
    freq: M
    start_year: 2010
    params:
      tables:
        - table: T20804                  # dataset 생략 시 NIPA
          prefix: "물가"                  # 시리즈명 앞에 붙일 꼬리표 (선택)
        - dataset: NIUnderlyingDetail
          table: U20404
          lines: [1, 2, 3, 24, 25]       # 줄번호로 추리기 (생략 = 전체)

계층 표기:
  BEA 는 LineDescription 앞의 공백으로 계층을 나타낸다. 공백은 파일에 담으면
  깨지기 쉬우므로 '· ' 반복으로 바꿔 이름에 심는다 (예: '· · 내구재').
  fetch.py 의 merge_series 는 이름을 키로 쓰므로 이 표기가 계속 유지된다.
"""
import os
import re
from datetime import date

import requests

URL = "https://apps.bea.gov/api/data/"
INDENT = 4          # BEA LineDescription 의 한 단계 들여쓰기 폭(공백 수)


class BeaError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("BEA_API_KEY", "").strip()
    if not key:
        raise BeaError("환경변수 BEA_API_KEY 가 없습니다. (.env 에 BEA_API_KEY=... 추가)")
    return key


def _to_date(period: str) -> str | None:
    """BEA TimePeriod → 'YYYY-MM-DD'(기간 말일). 월(2026M06)·분기(2026Q2)·연(2026)."""
    period = (period or "").strip()
    m = re.fullmatch(r"(\d{4})M(\d{2})", period)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"(\d{4})Q(\d)", period):
        y, q = int(period[:4]), int(period[5])
        mo = q * 3
    elif re.fullmatch(r"\d{4}", period):
        y, mo = int(period), 12
    else:
        return None
    if not 1 <= mo <= 12:
        return None
    nxt = date(y + (mo == 12), (mo % 12) + 1, 1)          # 다음 달 1일
    return date.fromordinal(nxt.toordinal() - 1).isoformat()   # → 이번 달 말일


def _num(s):
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if t in ("", "...", "(NA)", "(D)"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def request_table(key: str, dataset: str, table: str, freq: str, year: str = "ALL") -> list[dict]:
    """표 하나를 통째로 받아 행 리스트를 돌려준다."""
    r = requests.get(URL, params={
        "UserID": key, "method": "GetData", "datasetname": dataset,
        "TableName": table, "Frequency": freq, "Year": year,
        "ResultFormat": "JSON",
    }, timeout=90)
    r.raise_for_status()
    js = r.json()
    api = js.get("BEAAPI") or {}
    # 오류는 두 자리 중 하나에 담겨 온다
    err = api.get("Error") or (api.get("Results") or {}).get("Error")
    if err:
        raise BeaError(f"BEA 오류 ({dataset}/{table}): {str(err)[:200]}")
    res = api.get("Results") or {}
    if isinstance(res, list):                      # 표를 여러 개 물으면 리스트로 온다
        rows = []
        for x in res:
            rows.extend(x.get("Data") or [])
        return rows
    return res.get("Data") or []


def parse(rows: list[dict], prefix: str = "", lines=None) -> list[dict]:
    """BEA 행 리스트 → 시리즈 목록. 수집과 분리해 저장된 응답으로 테스트할 수 있게 한다."""
    want = None if lines is None else {int(x) for x in lines}
    order: list[str] = []
    acc: dict[str, dict] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            ln = int(r.get("LineNumber"))
        except (TypeError, ValueError):
            continue
        if want is not None and ln not in want:
            continue
        raw = r.get("LineDescription") or ""
        # BEA 웹 화면과 달리 API 의 LineDescription 에는 들여쓰기가 없는 경우가 많다.
        #   있으면 계층으로 살리고, 없으면 그냥 이름만 쓴다(계층은 화면 쪽에서 정의).
        depth = (len(raw) - len(raw.lstrip(" "))) // INDENT
        name = ("· " * depth) + raw.strip()
        if prefix:
            name = f"{prefix} · {name}"
        d = _to_date(r.get("TimePeriod"))
        v = _num(r.get("DataValue"))
        if not name or d is None or v is None:
            continue
        if name not in acc:
            acc[name] = {"name": name, "pts": {}, "line": ln}
            order.append(name)
        acc[name]["pts"][d] = v
    order.sort(key=lambda n: acc[n]["line"])        # 표에 적힌 줄 순서 유지
    out = []
    for n in order:
        pts = acc[n]["pts"]
        if pts:
            out.append({"name": n, "data": [{"d": d, "v": pts[d]} for d in sorted(pts)]})
    return out


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 정의 하나 → 시리즈 목록 (다른 수집기와 동일 형식)."""
    key = _api_key()
    p = indicator.get("params") or {}
    freq = {"M": "M", "Q": "Q", "A": "A"}.get(indicator.get("freq", "M"), "M")
    tables = p.get("tables") or [{
        "dataset": p.get("dataset"), "table": p.get("table"),
        "prefix": p.get("prefix"), "lines": p.get("lines"),
    }]
    start_year = indicator.get("_start_year") or indicator.get("start_year") \
        or date.today().year - indicator.get("lookback_years", 15)

    series: list[dict] = []
    for t in tables:
        dataset = t.get("dataset") or "NIPA"
        table = t.get("table")
        if not table:
            raise BeaError(f"[{indicator['id']}] params.tables 에 table 이 없습니다.")
        # 표 하나가 실패해도 나머지는 살린다 (월별 제공이 없는 표가 섞일 수 있다)
        try:
            rows = request_table(key, dataset, table, freq)
        except Exception as e:
            print(f"  [bea {indicator['id']}] {dataset}/{table} 실패(건너뜀): {str(e)[:160]}")
            continue
        got = parse(rows, t.get("prefix") or "", t.get("lines"))
        # 시작연도 이전은 버린다 (BEA 는 Year=ALL 로만 안정적으로 응답한다)
        cut = f"{int(start_year)}-01-01"
        for s in got:
            s["data"] = [x for x in s["data"] if x["d"] >= cut]
        got = [s for s in got if s["data"]]
        print(f"  [bea {indicator['id']}] {dataset}/{table} → 시리즈 {len(got)}개"
              + (f" (줄 {len(t['lines'])}개 지정)" if t.get("lines") else ""))
        series.extend(got)

    if not series:
        raise BeaError(f"BEA 응답이 비었습니다 ({indicator['id']}). 표 이름·주기를 확인하세요.")
    return series

"""KRX Data Marketplace OpenAPI 수집기 (지수).

    https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd   (KOSPI 시리즈 일별시세)

이 API는 **기준일자(basDd) 하루치**만 돌려준다. 2010-01-04 부터 제공되므로 전 구간을
받으려면 영업일 수만큼(약 4,100회) 호출해야 한다. 그래서:

  * 이미 받아둔 날짜는 건너뛴다 (docs/data/<id>.json 아카이브 활용, merge_always)
  * 한 번 실행에 max_calls 회까지만 호출하고 멈춘다 → 여러 번 나눠 받으면 된다
  * 주말은 아예 호출하지 않는다 (공휴일은 빈 응답이 오므로 '조회함' 표시만 남긴다)

인증키는 환경변수 KRX_API_KEY 로 전달한다 (코드·yaml 에 절대 하드코딩 금지).
    .env 파일에  KRX_API_KEY=발급받은키   한 줄 추가

indicators.yaml 예:
    params:
      path: idx/kospi_dd_trd
      index_name: 코스피          # IDX_NM 이 이 값인 행만 사용
      fields: {종가: CLSPRC_IDX}  # 시리즈명: 응답필드
      start: "2010-01-04"
      max_calls: 400
"""
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
BASE = "https://data-dbg.krx.co.kr/svc/apis/"


class KrxError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("KRX_API_KEY", "").strip()
    if not k:
        raise KrxError(
            "환경변수 KRX_API_KEY 가 없습니다. .env 파일에 KRX_API_KEY=... 한 줄을 추가하세요. "
            "(openapi.krx.co.kr → 마이페이지 → API 인증키 신청)")
    return k


def _have(indicator_id: str) -> set:
    """이미 받아둔 기준일자 집합 (재실행 시 건너뛰기용)."""
    p = DATA / f"{indicator_id}.json"
    if not p.exists():
        return set()
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    got = set()
    for s in payload.get("series", []):
        for pt in s.get("data", []):
            got.add(pt["d"])
    # 조회했지만 값이 없던 날(휴장일)도 기록해 두면 매번 다시 때리지 않는다
    got |= set(payload.get("_checked", []))
    return got


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params", {}) or {}
    path = p.get("path", "idx/kospi_dd_trd")
    idx_nm = p.get("index_name", "코스피")
    fields = p.get("fields") or {"종가": "CLSPRC_IDX"}
    max_calls = int(p.get("max_calls", 400))
    pause = float(p.get("pause", 0.12))
    start = p.get("start", "2010-01-04")

    y0, m0, d0 = (int(x) for x in str(start).split("-"))
    cur = date(y0, m0, d0)
    end = date.today()
    # --full 이면 이미 받은 날짜도 무시하고 처음부터 다시 받는다 (아카이브 복구용)
    have = set() if indicator.get("_full") else _have(indicator["id"])

    todo = []
    while cur <= end:
        if cur.weekday() < 5 and cur.isoformat() not in have:   # 주말 제외
            todo.append(cur)
        cur += timedelta(days=1)
    if not todo:
        print(f"  [krx] {indicator['id']}: 새로 받을 날짜 없음 (보유 {len(have)}일)")
        # 조회완료 목록을 그대로 넘겨줘야 fetch.py 가 _checked 를 잃지 않는다
        indicator["_krx_checked"] = sorted(have)
        return []

    hdr = {"AUTH_KEY": _key()}
    url = BASE + path.lstrip("/")
    series = {nm: {} for nm in fields}
    checked, ok, empty, fail = [], 0, 0, 0

    for i, d in enumerate(todo[:max_calls]):
        ds = d.strftime("%Y%m%d")
        try:
            r = requests.get(url, headers=hdr, params={"basDd": ds}, timeout=30)
            if r.status_code == 401 or r.status_code == 403:
                raise KrxError(
                    f"인증 실패({r.status_code}). 인증키가 맞는지, 해당 서비스에 "
                    "'API 이용신청'이 승인됐는지 확인하세요. (서비스별로 따로 신청해야 합니다)")
            r.raise_for_status()
            rows = (r.json() or {}).get("OutBlock_1") or []
        except KrxError:
            raise
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"  [krx] {ds} 실패: {e}")
            if fail > 20:
                raise KrxError(f"연속 실패가 많아 중단합니다 ({fail}건). 마지막 오류: {e}")
            continue

        checked.append(d.isoformat())
        hit = [x for x in rows if str(x.get("IDX_NM", "")).strip() == idx_nm]
        if not hit:
            empty += 1
            continue
        row = hit[0]
        iso = d.isoformat()
        for nm, fld in fields.items():
            v = str(row.get(fld, "")).replace(",", "").strip()
            try:
                series[nm][iso] = float(v)
            except ValueError:
                pass
        ok += 1
        if pause:
            time.sleep(pause)

    left = max(0, len(todo) - max_calls)
    print(f"  [krx] {indicator['id']}: 호출 {len(todo[:max_calls])}회 "
          f"(수집 {ok} · 휴장 {empty} · 실패 {fail}) · 남은 날짜 {left}일")
    if left:
        print(f"  [krx] 다시 실행하면 이어서 받습니다 (한 번에 {max_calls}일씩)")

    indicator["_krx_checked"] = sorted(set(_have(indicator["id"])) | set(checked))
    return [{"name": n, "data": [{"d": k, "v": v} for k, v in sorted(vals.items())]}
            for n, vals in series.items() if vals]

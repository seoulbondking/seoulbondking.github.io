"""미 재무부 Fiscal Data 수집기 — 유통국채 잔액(MSPD)과 TGA 잔고(DTS).

https://api.fiscaldata.treasury.gov/services/api/fiscal_service/ · 키 불필요.

QRA(분기 리펀딩) 를 읽는 데 필요한 '실적' 쪽을 받는다. QRA 가 발표하는 **추정치**
(다음 분기 순발행 전망, 분기말 TGA 가정, 입찰규모 변경표)는 보도자료 본문이라
정형 API 가 없다 — 그건 이 수집기의 범위 밖이다.

  v1/debt/mspd/mspd_table_1            월말 유통국채 잔액, 종류별
  v1/accounting/dts/operating_cash_balance   일별 TGA 잔고

**함정 하나.** DTS 의 값은 컬럼 이름과 어긋난다. `close_today_bal` 은 지금 전부 null 이고
실제 값은 **어느 행이든 `open_today_bal`** 에 들어 있다. 마감잔고인지 개시잔고인지는
컬럼이 아니라 `account_type` 이 구분한다("… (TGA) Closing Balance"). 컬럼 이름만 믿고
close_today_bal 을 쓰면 전 구간이 비어서 들어온다.

단위는 둘 다 백만달러다. 화면 단위(십억달러)로 바꿔서 내보낸다.
"""
from datetime import date

import requests

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
TIMEOUT = 90
PAGE = 10000
MIL_TO_BN = 1000.0

# MSPD 유통국채 종류 → 화면 이름. Federal Financing Bank(35억달러)는 뺀다.
MSPD_CLASS = {
    "Bills": "Bills",
    "Notes": "Notes",
    "Bonds": "Bonds",
    "Treasury Inflation-Protected Securities": "TIPS",
    "Floating Rate Notes": "FRN",
}


class FiscalDataError(RuntimeError):
    pass


def _f(x):
    try:
        return float(x) if x not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _get_all(session, path, fields, start):
    """날짜 필터 + 페이지네이션. 응답이 크므로 필요한 컬럼만 받는다."""
    out, page = [], 1
    while True:
        r = session.get(f"{BASE}/{path}", timeout=TIMEOUT, params={
            "fields": ",".join(fields),
            "filter": f"record_date:gte:{start}",
            "sort": "record_date",
            "page[size]": PAGE, "page[number]": page,
        })
        r.raise_for_status()
        body = r.json()
        rows = body.get("data") or []
        out.extend(rows)
        meta = body.get("meta") or {}
        if page >= int(meta.get("total-pages") or 1) or not rows:
            break
        page += 1
    return out


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params") or {}
    start_year = int(indicator.get("_start_year") or p.get("start_year") or 2010)
    start = f"{start_year}-01-01"

    s = requests.Session()
    s.headers.update({"Accept": "application/json",
                      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    # ── 유통국채 잔액 (월말)
    rows = _get_all(s, "v1/debt/mspd/mspd_table_1",
                    ["record_date", "security_type_desc", "security_class_desc", "total_mil_amt"],
                    start)
    byClass, total = {k: {} for k in MSPD_CLASS.values()}, {}
    for r in rows:
        d, v = r.get("record_date"), _f(r.get("total_mil_amt"))
        if not d or v is None:
            continue
        if r.get("security_type_desc") == "Total Marketable":
            total[d] = v / MIL_TO_BN
        elif r.get("security_type_desc") == "Marketable":
            ko = MSPD_CLASS.get(r.get("security_class_desc"))
            if ko:
                byClass[ko][d] = v / MIL_TO_BN

    series = []
    for ko in MSPD_CLASS.values():
        pts = [{"d": d, "v": round(v, 1)} for d, v in sorted(byClass[ko].items())]
        if pts:
            series.append({"name": f"유통잔액 · {ko}", "data": pts})
    if total:
        series.append({"name": "유통잔액 · 합계",
                       "data": [{"d": d, "v": round(v, 1)} for d, v in sorted(total.items())]})
        # Bill 비중 — QRA 논의의 중심. TBAC 은 대략 15~20% 를 권고해 왔다.
        bills = byClass["Bills"]
        pct = [{"d": d, "v": round(bills[d] / total[d] * 100, 2)}
               for d in sorted(total) if d in bills and total[d]]
        if pct:
            series.append({"name": "Bill 비중", "data": pct})
    print(f"  [fiscaldata {indicator['id']}] MSPD 월말 {len(total)}개월"
          + (f" ({min(total)} ~ {max(total)})" if total else ""))

    # ── TGA 잔고 (일별). 값은 open_today_bal, 구분은 account_type (위 주석 참고)
    dts = _get_all(s, "v1/accounting/dts/operating_cash_balance",
                   ["record_date", "account_type", "open_today_bal"], start)
    tga = {}
    for r in dts:
        if "closing balance" not in (r.get("account_type") or "").lower():
            continue
        v = _f(r.get("open_today_bal"))
        if v is not None:
            tga[r["record_date"]] = round(v / MIL_TO_BN, 1)
    if tga:
        series.append({"name": "TGA 잔고",
                       "data": [{"d": d, "v": v} for d, v in sorted(tga.items())]})
        print(f"  [fiscaldata {indicator['id']}] TGA {len(tga)}일 "
              f"({min(tga)} ~ {max(tga)}, 최신 {tga[max(tga)]:,.0f}B)")
    else:
        print(f"  [fiscaldata {indicator['id']}] [warn] TGA 를 못 찾았습니다 — "
              "account_type 문구가 바뀌었는지 확인하세요")

    if not series:
        raise FiscalDataError("Fiscal Data 응답이 비었습니다. 엔드포인트 경로를 확인하세요.")
    return series


if __name__ == "__main__":   # python -m fetchers.fiscaldata
    for x in fetch({"id": "probe", "params": {"start_year": 2024}}):
        print(f"{x['name']:<20} {len(x['data']):>5}개  "
              f"{x['data'][0]['d']} ~ {x['data'][-1]['d']}  최신 {x['data'][-1]['v']:,}")

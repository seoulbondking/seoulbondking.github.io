"""뉴욕 연은 가계부채·신용 보고서(Quarterly Report on Household Debt and Credit) 수집기.

키 불필요. 분기 보고서의 원자료 엑셀을 통째로 읽는다 (약 1MB, 매번 전체 수집).
  https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/xls/HHD_C_Report_<YYYY>Q<n>.xlsx
  - 분기 종료 후 약 5~6주 뒤 공표 (2026Q3 → 2026년 11월). 최신 파일을 찾으려고
    이번 분기부터 거꾸로 몇 분기를 시도한다.
  - 자료: New York Fed Consumer Credit Panel / Equifax (신용기록 표본, 계절조정 없음)

읽는 시트 (시트 이름은 보고서 쪽번호라 보고서 개편 때 바뀔 수 있다 → 제목으로 찾는다)
  Total Debt Balance and Its Composition            잔액 · <종류>            조달러
  Percent of Balance 90+ Days Delinquent by Loan Type 90일+ 잔액비중 · <종류>  %
  New Seriously Delinquent Balances by Loan Type    신규 90일+ 이행률 · <종류> %  (연율, 4분기 이동합)
  Transition into Serious Delinquency (90+) [for X] by Age
                                                    연령별 90일+ 이행률 · <상품> · <연령>  %
      — '연체 잔액 중 이번에 90일 이상 연체로 넘어간 비율'의 4분기 이동합 (=연간 비율).
        기사에서 "70세 이상 심각 연체 급증"이라고 하는 지표가 이것(카드).
행 라벨은 '26:Q3' 또는 '00:Q1' 형식 → 분기말 날짜.
"""
import io
import re
from datetime import date

import requests

URL = "https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/xls/HHD_C_Report_{q}.xlsx"
UA = {"User-Agent": "Mozilla/5.0 (macro-dashboard)"}

TYPE_KO = {"MORTGAGE": "주담대", "HE REVOLVING": "홈에쿼티", "HELOC": "홈에쿼티", "AUTO LOAN": "자동차",
           "AUTO": "자동차", "CREDIT CARD": "카드", "CC": "카드", "STUDENT LOAN": "학자금",
           "OTHER": "기타", "TOTAL": "전체", "ALL": "전체"}
AGE_PRODUCT = {None: "전체", "MORTGAGES": "주담대", "AUTO LOANS": "자동차",
               "CREDIT CARDS": "카드", "STUDENT LOANS": "학자금"}


class HhdcError(RuntimeError):
    pass


def _candidates(n=6):
    t = date.today()
    y, q = t.year, (t.month - 1) // 3 + 1
    for _ in range(n):
        yield f"{y}Q{q}"
        q -= 1
        if q == 0:
            y, q = y - 1, 4


def _download():
    for q in _candidates():
        r = requests.get(URL.format(q=q), headers=UA, timeout=60)
        if r.status_code == 200 and "spreadsheet" in r.headers.get("content-type", ""):
            return q, r.content
    raise HhdcError("뉴욕 연은 HHDC 엑셀을 찾지 못했습니다 (최근 6분기 시도)")


def _qend(lab):
    m = re.fullmatch(r"\s*(\d{2}):Q([1-4])\s*", str(lab))
    if not m:
        return None
    y = 2000 + int(m.group(1))
    mo = int(m.group(2)) * 3
    return f"{y}-{mo:02d}-{[31, 30, 30, 31][int(m.group(2)) - 1]}"


def _table(ws):
    """시트에서 헤더 행(분기 라벨 바로 위)과 데이터 행을 찾아 {열이름: [(날짜, 값)]} 로 돌려준다."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    first = next((i for i, r in enumerate(rows) if r and _qend(r[0])), None)
    if first is None or first == 0:
        return {}
    head = rows[first - 1]
    out = {}
    for j, h in enumerate(head[1:], start=1):
        if not isinstance(h, str) or not h.strip() or h.strip().lower().startswith(("note", "source", "return")):
            continue
        pts = []
        for r in rows[first:]:
            d = _qend(r[0]) if r else None
            if not d:
                continue
            v = r[j] if j < len(r) else None
            if isinstance(v, (int, float)):
                pts.append({"d": d, "v": float(v)})
        if pts:
            out[h.strip()] = pts
    return out


def _title(ws):
    for r in ws.iter_rows(max_row=3, values_only=True):
        for c in r:
            if isinstance(c, str) and c.strip():
                return c.strip()
    return ""


def fetch(indicator: dict) -> list[dict]:
    import openpyxl
    q, blob = _download()
    print(f"  [nyfed_hhdc] {q} 보고서")
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    out, seen = [], set()

    def add(name, pts):
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "data": pts})

    for ws in wb.worksheets:
        t = _title(ws)
        tl = t.lower()
        if tl.startswith("total debt balance and its composition"):
            kind, pre = "type", "잔액"
        elif tl.startswith("percent of balance 90+ days delinquent by loan type"):
            kind, pre = "type", "90일+ 잔액비중"
        elif tl.startswith("new seriously delinquent"):
            kind, pre = "type", "신규 90일+ 이행률"
        elif tl.startswith("transition into serious delinquency (90+)") and tl.endswith("by age"):
            m = re.search(r"for (.+?) by age", tl)
            prod = AGE_PRODUCT.get(m.group(1).upper() if m else None)
            if prod is None:
                continue
            kind, pre = "age", f"연령별 90일+ 이행률 · {prod}"
        else:
            continue
        for col, pts in _table(ws).items():
            if kind == "type":
                ko = TYPE_KO.get(col.upper())
                if ko:
                    add(f"{pre} · {ko}", pts)
            else:
                c = "전체" if col.lower() == "all" else col
                add(f"{pre} · {c}", pts)

    need = ["90일+ 잔액비중 · 카드", "연령별 90일+ 이행률 · 카드 · 70+", "연령별 90일+ 이행률 · 전체 · 18-29"]
    miss = [n for n in need if n not in seen]
    if miss:
        raise HhdcError(f"HHDC 엑셀 구조가 바뀐 것 같습니다 — 없는 계열: {miss}")
    return out

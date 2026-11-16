"""EIA 소매 휘발유·디젤 가격 구성 수집기 — "What we pay for in a gallon".

EIA Gasoline and Diesel Fuel Update 의 Pump Components History 표를 그대로 읽는다.
키가 필요 없고, API 가 아니라 HTML 표다 (EIA open data API 에는 이 분해가 없다).

  휘발유  https://www.eia.gov/petroleum/gasdiesel/gaspump_hist.php     (2000-01 ~)
  디젤    https://www.eia.gov/petroleum/gasdiesel/dieselpump_hist.php  (2002-05 ~)

표 열: Mon-yr · Retail Price ($/gal) · Refining % · Distribution & Marketing % · Taxes % · Crude Oil %
  - 비중(%)만 공표하므로 $/gal = 소매가 × 비중 / 100 으로 바꾼다.
    네 비중의 합이 반올림 때문에 100 ± 0.1 정도 어긋난다 — 그만큼 합계가 소매가와 다르다.
  - 원유 = 정유사 원유 도입단가(refiner acquisition cost, 국산·수입 가중평균). WTI 가 아니다.
  - 정제 = 도매가(rack) − 원유, 유통·마케팅 = 소매가 − 도매가 − 세금, 세금 = 연방 + 주 평균.
  - 월 표기가 섞여 온다: 'Aug-26', 'July-24', 'Sept-21'. 앞 세 글자로 월을 읽는다.
  - 공표는 2~3개월 늦다 (2026-11 기준 최신 2026-08).

── dnav 모드 (params.dnav) ──────────────────────────────────────
EIA 석유 통계(dnav) 의 표 다운로드 XLS 를 읽는다. 키 불필요.
  https://www.eia.gov/dnav/pet/xls/<파일>.xls  — 'Data N' 시트, 1행 Sourcekey, 2행 이름, 3행부터 데이터
  날짜는 엑셀 일련번호. 월별은 그달 15일로 와서 월말로 바꾼다. 주별은 주 마지막 날(금요일) 그대로.
  예) PET_PNP_UNC_DCU_NUS_M : 정제 투입·운영가능/가동/유휴 능력·가동률 (월, 1985~)
      PET_PNP_WIUP_DCU_NUS_W : 정제 투입·가동률 (주, 1982~)
  params:
    dnav:
      PET_PNP_UNC_DCU_NUS_M: {MOPUEUS2: 가동률, MOCIDUS2: 유휴 정제능력}

indicators.yaml 예:
  - id: us_pump
    name: 미국 휘발유·디젤 소매가 구성 (EIA)
    source: eia
    freq: M
    always_full: true
    params:
      products: {gas: 휘발유, diesel: 디젤}
"""
import html
import re
from datetime import date, timedelta

import requests

URLS = {
    "gas": "https://www.eia.gov/petroleum/gasdiesel/gaspump_hist.php",
    "diesel": "https://www.eia.gov/petroleum/gasdiesel/dieselpump_hist.php",
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
# 표 열 순서 → 화면 이름
COLS = [("소매가", None), ("정제", 2), ("유통·마케팅", 3), ("세금", 4), ("원유", 5)]


class EiaError(RuntimeError):
    pass


def _month_end(lbl: str) -> str | None:
    """'Aug-26' / 'July-24' / 'Sept-21' → '2026-08-31'."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\.?-(\d{2})\s*", lbl or "")
    if not m:
        return None
    mo = MONTHS.get(m.group(1)[:3].lower())
    if not mo:
        return None
    y = 2000 + int(m.group(2))
    nxt = date(y + (mo == 12), mo % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def parse(text: str, label: str) -> list[dict]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S)
    data = {k: {} for k, _ in COLS}
    head_ok = False
    for r in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        if len(cells) < 6:
            continue
        if cells[0].lower().startswith("mon"):
            # 열 순서가 바뀌면 조용히 틀린 값을 만들게 된다 — 머리글을 확인한다
            h = [c.lower() for c in cells]
            want = ["retail", "refining", "distribution", "taxes", "crude"]
            if not all(w in h[i + 1] for i, w in enumerate(want)):
                raise EiaError(f"머리글이 바뀌었다: {cells}")
            head_ok = True
            continue
        d = _month_end(cells[0])
        price = _num(cells[1])
        if not d or price is None:
            continue
        data["소매가"][d] = price
        for nm, i in COLS[1:]:
            pct = _num(cells[i])
            if pct is not None:
                data[nm][d] = round(price * pct / 100, 4)
    if not head_ok:
        raise EiaError("표 머리글을 찾지 못했다 (페이지 구조 변경?)")
    out = []
    for nm, _ in COLS:
        if data[nm]:
            out.append({"name": f"{label} · {nm}",
                        "data": [{"d": d, "v": v} for d, v in sorted(data[nm].items())]})
    return out


DNAV = "https://www.eia.gov/dnav/pet/xls/{}.xls"


def parse_dnav(content: bytes, keys: dict, monthly: bool) -> list[dict]:
    import xlrd   # EIA dnav 는 구형 .xls 라 openpyxl 로는 못 연다
    book = xlrd.open_workbook(file_contents=content)
    found = {}
    for sh in book.sheets():
        if not sh.name.lower().startswith("data") or sh.nrows < 4:
            continue
        hdr = [str(sh.cell_value(1, c)).strip() for c in range(sh.ncols)]
        for c, k in enumerate(hdr):
            if k not in keys:
                continue
            pts = {}
            for r in range(3, sh.nrows):
                dv, v = sh.cell_value(r, 0), sh.cell_value(r, c)
                if dv in ("", None) or v in ("", None):
                    continue
                d = xlrd.xldate_as_datetime(dv, book.datemode).date()
                if monthly:
                    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
                    d = nxt - timedelta(days=1)
                pts[d.isoformat()] = float(v)
            found[k] = {"name": keys[k], "data": [{"d": d, "v": v} for d, v in sorted(pts.items())]}
    miss = [k for k in keys if k not in found]
    if miss:
        raise EiaError(f"Sourcekey 를 찾지 못했다: {miss}")
    return [found[k] for k in keys]


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 하나 → 시리즈 목록 (다른 수집기와 동일 형식)."""
    p = indicator.get("params") or {}
    iid = indicator.get("id", "?")
    if p.get("dnav"):
        out = []
        for fn, keys in p["dnav"].items():
            r = requests.get(DNAV.format(fn), headers=UA, timeout=90)
            r.raise_for_status()
            got = parse_dnav(r.content, keys, fn.upper().endswith("_M"))
            s0 = got[0]["data"]
            print(f"  [eia {iid}] {fn} → 시리즈 {len(got)}개 ({s0[0]['d']} ~ {s0[-1]['d']})")
            out.extend(got)
        return out
    products = p.get("products") or {"gas": "휘발유", "diesel": "디젤"}
    out = []
    for key, label in products.items():
        url = URLS.get(key)
        if not url:
            raise EiaError(f"알 수 없는 제품 '{key}' (가능: {', '.join(URLS)})")
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        got = parse(r.text, label)
        n = len(got[0]["data"]) if got else 0
        span = f"{got[0]['data'][0]['d']} ~ {got[0]['data'][-1]['d']}" if n else "-"
        print(f"  [eia {iid}] {label} → {n}개월 ({span})")
        out.extend(got)
    if not out:
        raise EiaError("받은 데이터가 없다")
    return out

"""애틀랜타 연준 GDPNow 수집기.

https://www.atlantafed.org/research-and-data/data/gdpnow
분기 실질 GDP 성장률(전기비 연율)을 매 영업일 다시 추정해 발표한다. BEA 속보치가
나오기 전에 그 분기 성장률이 얼마로 찍힐지 미리 보는 용도다.

공개 API 는 없고, 모형 전체를 담은 스프레드시트 하나를 공개한다(10MB 남짓).
  {URL}
그 안에서 두 시트만 쓴다.
  TrackingArchives  빈티지별 성장률 (전기비 연율, %)
  ContribArchives   빈티지별 성장 기여도 (%p)
두 시트 모두 A열 = 추정한 날(빈티지), B열 = 대상 분기말, C열부터 항목이다.

파일이 크므로 data/ 에 받아 두고 Last-Modified 로 갱신 여부만 확인한다.
(.gitignore 의 data/*.xlsx 에 이미 걸린다)

내보내는 계열 — 클리블랜드 물가 나우캐스트(fetchers/clevelandfed.py)와 같은 구성이다.
  {항목}                     분기말 날짜 · 그 분기의 마지막 빈티지 값
  기여도 · {항목}             분기말 날짜 · 같은 기준의 기여도
  실제 (BEA 속보치)           분기말 날짜 · 확정 후 채워지는 실제값
  빈티지 · {2026 Q3} · {항목}  일별 · 최근 vintage_quarters 개 분기만

빈티지를 최근 것만 남기는 이유는 크기다. 44개 분기를 전부 일별로 담으면 파일이
수 MB 가 된다 — 화면에서 실제로 훑어보는 건 최근 몇 분기다.

indicators.yaml 예:
    params:
      vintage_quarters: 8
      items: ["GDP Nowcast", "PCE", "Final Sales to Private Domestic Purchasers"]
"""
import calendar
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl
import requests

URL = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/cqer/"
       "researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx")
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "GDPTrackingModelDataAndForecasts.xlsx"
GROWTH_SHEET, CONTRIB_SHEET = "TrackingArchives", "ContribArchives"
# Archives 는 '끝난 분기'만 담는다. 진행 중인 분기는 TrackingHistory 에 가로로 들어 있다.
#   r2 = "Evolution of GDP nowcast and components for 2025q2"  ← 대상 분기
#   r1 3열~ = 빈티지 날짜,  B열 = "1-Personal consumption expenditures (PCE)"
HIST_SHEET = "TrackingHistory"
COL_DATE, COL_QTR = 0, 1
HEADLINE = "GDP Nowcast"
ACTUAL = "Advance Estimate From BEA"
# 기본으로 담을 항목. 지정하지 않으면 이 목록을 쓴다.
#   미국 GDP 화면(us_gdp)과 같은 이름을 골라 두 화면을 나란히 읽을 수 있게 했다.
DEFAULT_ITEMS = [
    HEADLINE, "PCE", "PCE Goods", "PCE Services",
    "GPDI", "Fixed Investment", "Residential",
    "Government", "Exports", "Imports",
    "Final Sales", "Final Sales to Domestic Purchasers",
    "Final Sales to Private Domestic Purchasers",
]


class GdpNowError(RuntimeError):
    pass


# 애틀랜타 연준은 기본 User-Agent 를 막는다(짧은 차단 페이지가 대신 온다).
# 브라우저 UA 를 붙이고, 받은 게 진짜 xlsx 인지 zip 매직으로 확인한다.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
ZIP_MAGIC = b"PK\x03\x04"


def _local_copy() -> Path | None:
    """수동으로 받아 둔 파일을 찾는다 (다운로드가 막힐 때의 대비책)."""
    for d in (ROOT / "data", Path.home() / "Desktop" / "Macro" / "gdpnow",
              Path.home() / "Desktop" / "Macro"):
        p = d / CACHE.name
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    return None


def _download(max_age_h: float) -> Path:
    """캐시가 낡았을 때만 내려받는다. 서버가 304 를 주면 그대로 쓴다."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": UA, "Accept": "*/*",
               "Referer": "https://www.atlantafed.org/research-and-data/data/gdpnow"}
    if CACHE.exists():
        age_h = (time.time() - CACHE.stat().st_mtime) / 3600
        if age_h < max_age_h:
            print(f"  [gdpnow] 캐시 사용 ({age_h:.1f}시간 전 · {CACHE.stat().st_size/1e6:.1f}MB)")
            return CACHE
        headers["If-Modified-Since"] = datetime.fromtimestamp(
            CACHE.stat().st_mtime, timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    try:
        r = requests.get(URL, headers=headers, timeout=180, stream=True)
    except Exception as e:
        return _fallback(f"내려받기 실패({type(e).__name__})")
    if r.status_code == 304:
        print("  [gdpnow] 서버 기준 변경 없음(304) — 캐시 사용")
        os.utime(CACHE, None)
        return CACHE
    if r.status_code != 200:
        return _fallback(f"HTTP {r.status_code}")

    tmp = CACHE.with_suffix(".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    size = tmp.stat().st_size
    head = tmp.read_bytes()[:4] if size < 4 else open(tmp, "rb").read(4)
    # xlsx 는 zip 이다. 차단 페이지·리다이렉트 HTML 을 캐시에 덮어쓰면 다음 실행까지
    # 망가진 파일을 들고 있게 되므로, 검증을 통과할 때만 교체한다.
    if head != ZIP_MAGIC or size < 1_000_000:
        ctype = r.headers.get("content-type", "?")
        peek = tmp.read_bytes()[:200].decode("utf-8", "replace").replace("\n", " ")
        tmp.unlink(missing_ok=True)
        print(f"  [gdpnow] 엑셀이 아닌 응답 ({size:,}바이트 · {ctype})")
        print(f"           앞부분: {peek[:160]}")
        return _fallback("엑셀이 아닌 응답")
    tmp.replace(CACHE)
    print(f"  [gdpnow] 내려받음 {CACHE.stat().st_size/1e6:.1f}MB")
    return CACHE


def _fallback(why: str) -> Path:
    """다운로드가 안 되면 캐시 → 수동 사본 순으로 물러선다."""
    if CACHE.exists() and CACHE.stat().st_size > 1_000_000:
        print(f"  [gdpnow] {why} — 기존 캐시를 쓴다")
        return CACHE
    loc = _local_copy()
    if loc:
        print(f"  [gdpnow] {why} — 수동 사본 사용: {loc}")
        return loc
    raise GdpNowError(
        f"GDPNow 스프레드시트를 받지 못했습니다 ({why}).\n"
        f"  브라우저로 {URL} 를 받아\n"
        f"  {CACHE} 에 두고 다시 실행하세요.")


def _read(ws, items: set):
    """시트 → {(빈티지, 분기말): {항목: 값}}. 항목 이름은 헤더 그대로."""
    it = ws.iter_rows(values_only=True)
    hdr = next(it, ())
    cols = {j: str(h).strip() for j, h in enumerate(hdr)
            if h is not None and str(h).strip() in items}
    if not cols:
        raise GdpNowError(f"'{ws.title}' 에서 대상 열을 찾지 못했습니다")
    out = {}
    for row in it:
        if not row or row[COL_DATE] is None or row[COL_QTR] is None:
            continue
        try:
            vin = row[COL_DATE].date().isoformat()
            qtr = row[COL_QTR].date().isoformat()
        except AttributeError:
            continue
        rec = {}
        for j, nm in cols.items():
            v = row[j] if j < len(row) else None
            if isinstance(v, (int, float)):
                rec[nm] = float(v)
        if rec:
            out[(vin, qtr)] = rec
    return out


def _hist_name(raw: str) -> str:
    """'7-               Equipment**' → 'Equipment'. Archives 쪽 이름에 맞춘다."""
    s = re.sub(r"^\s*\d+-\s*", "", str(raw or "")).strip()
    s = s.replace("**", "").strip()
    # Archives 는 약어를 쓴다
    return {"Personal consumption expenditures (PCE)": "PCE",
            "Gross Private Domestic Investment (GPDI)": "GPDI",
            "Government expenditures": "Government",
            "State and Local": "S&L"}.get(s, s)


def _read_history(ws, items: set):
    """진행 중인 분기 시트(가로 배열) → (분기말, {(빈티지, 항목): 값})."""
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 3:
        return None, {}
    m = re.search(r"(\d{4})\s*q\s*([1-4])", str(rows[1][0] or ""), re.I)
    if not m:
        return None, {}
    y, q = int(m.group(1)), int(m.group(2))
    mo = q * 3
    qtr = date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()

    dates = {}                                  # 열idx → 빈티지 날짜
    for j, c in enumerate(rows[0]):
        if j >= 2 and hasattr(c, "date"):
            dates[j] = c.date().isoformat()
    out = {}
    for r in rows[2:]:
        nm = _hist_name(r[1] if len(r) > 1 else "")
        if nm not in items:
            continue
        for j, d in dates.items():
            v = r[j] if j < len(r) else None
            if isinstance(v, (int, float)):
                out[(d, nm)] = float(v)
    return qtr, out


# 갱신 한 번마다 'GDP 가 얼마 움직였고 어느 항목에서 왔는지 + 원인 지표'.
#   ChangeInContributions 시트가 그걸 그대로 담고 있다 (1939행 × 12열).
#     0 날짜 · 1 대상분기 · 2~7 항목별 기여도 변화 · 8 GDP 변화 · 9 GDP · 10 직전 · 11 발표
CHG_SHEET = "ChangeInContributions"
CHG_PARTS = [(2, "소비"), (3, "설비투자"), (4, "주거"), (5, "재고"), (6, "순수출"), (7, "정부")]


def _read_changes(ws, qtr: str):
    """{빈티지: {'d': GDP변화, 'rel': 원인지표, 'parts': [(항목, 변화)…]}} — 해당 분기만."""
    out = {}
    for r in ws.iter_rows(min_row=3, values_only=True):
        if not r or r[0] is None or r[1] is None:
            continue
        try:
            vin, q = r[0].date().isoformat(), r[1].date().isoformat()
        except AttributeError:
            continue
        if q != qtr:
            continue
        parts = [(nm, float(r[i])) for i, nm in CHG_PARTS
                 if i < len(r) and isinstance(r[i], (int, float))]
        out[vin] = {
            "d": float(r[8]) if isinstance(r[8], (int, float)) else None,
            "rel": str(r[11]).strip() if len(r) > 11 and r[11] else "",
            "parts": parts,
        }
    return out


def _qlabel(qtr: str) -> str:
    y, m = int(qtr[:4]), int(qtr[5:7])
    return f"{y} Q{(m - 1) // 3 + 1}"


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params") or {}
    items = list(p.get("items") or DEFAULT_ITEMS)
    want = set(items) | {ACTUAL}
    nq = int(p.get("vintage_quarters", 8))
    path = _download(float(p.get("max_age_hours", 6)))

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sn in (GROWTH_SHEET, CONTRIB_SHEET):
        if sn not in wb.sheetnames:
            raise GdpNowError(f"시트 없음: {sn} (있는 시트 {len(wb.sheetnames)}개)")
    grow = _read(wb[GROWTH_SHEET], want)
    ctb = _read(wb[CONTRIB_SHEET], set(items))

    if not grow:
        raise GdpNowError("TrackingArchives 에서 데이터를 읽지 못했습니다")

    # 진행 중인 분기를 얹는다. Archives 에는 끝난 분기까지만 들어 있어서,
    # 이걸 빼면 화면에 '지금 보고 있는 분기'가 안 나온다.
    cur_q = None
    if HIST_SHEET in wb.sheetnames:
        cur_q, hist = _read_history(wb[HIST_SHEET], want)
        if cur_q:
            for (vin, nm), v in hist.items():
                grow.setdefault((vin, cur_q), {})[nm] = v
            print(f"  [gdpnow] 진행 분기 {_qlabel(cur_q)} 빈티지 "
                  f"{len({v for v, _ in hist})}개 추가")
    quarters = sorted({q for _v, q in grow})
    recent = set(quarters[-nq:])

    # 분기말 = 그 분기의 마지막 빈티지 값. 빈티지가 날짜순이라 max 로 고른다.
    last_of: dict[str, tuple] = {}
    for (vin, qtr) in grow:
        if qtr not in last_of or vin > last_of[qtr][0]:
            last_of[qtr] = (vin, qtr)

    ser: dict[str, dict] = {}
    def put(name, d, v):
        if v is not None:
            ser.setdefault(name, {})[d] = v

    for qtr, key in last_of.items():
        rec = grow.get(key, {})
        for nm in items:
            put(nm, qtr, rec.get(nm))
        put("실제 (BEA 속보치)", qtr, rec.get(ACTUAL))
        crec = ctb.get(key, {})
        for nm in items:
            put(f"기여도 · {nm}", qtr, crec.get(nm))

    # 빈티지 추이 — 최근 분기만
    for (vin, qtr), rec in grow.items():
        if qtr not in recent:
            continue
        for nm in items:
            put(f"빈티지 · {_qlabel(qtr)} · {nm}", vin, rec.get(nm))

    out = [{"name": n, "data": [{"d": d, "v": v} for d, v in sorted(m.items())]}
           for n, m in ser.items() if m]

    # 진행 분기의 갱신 사유 — 값이 아니라 주석이라 별도 계열(notes)로 붙인다.
    if cur_q and CHG_SHEET in wb.sheetnames:
        ch = _read_changes(wb[CHG_SHEET], cur_q)
        if ch:
            out.append({"name": f"사유 · {_qlabel(cur_q)}", "notes": [
                {"d": d, "chg": c["d"], "rel": c["rel"], "parts": c["parts"]}
                for d, c in sorted(ch.items())]})
            print(f"  [gdpnow] 갱신 사유 {len(ch)}건 ({_qlabel(cur_q)})")
    if not out:
        raise GdpNowError("내보낼 계열이 없습니다 (items 이름을 확인하세요)")
    print(f"  [gdpnow] 분기 {len(quarters)}개 · 빈티지 {len(grow)}개 → 시리즈 {len(out)}개"
          f" (빈티지 추이는 최근 {nq}분기)")

    # 낡은 파일을 쓰고 있는지 알린다.
    #   캐시 신선도를 파일 수정시각으로만 보면, 수동으로 옮겨 둔 옛 파일이
    #   '방금 받은 것'처럼 보여 몇 분기 전 데이터를 계속 내보내게 된다.
    #   (2026-09-21 실제 사고: 테스트로 복사해 둔 2025-05 파일이 캐시로 잡혔다)
    newest = max(quarters)
    today = date.today()
    behind = (today.year - int(newest[:4])) * 4 + (today.month - 1) // 3 - (int(newest[5:7]) - 1) // 3
    if behind >= 2:
        print(f"  ⚠ [gdpnow] 최신 분기가 {_qlabel(newest)} 입니다 — 오늘 기준 {behind}분기 뒤처집니다.")
        print(f"     {path} 가 낡았을 수 있습니다. 지우고 다시 실행하면 새로 받습니다.")
    return out

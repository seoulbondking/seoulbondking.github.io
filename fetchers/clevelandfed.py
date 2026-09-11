"""클리블랜드 연준 인플레이션 나우캐스트 수집기.

https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting
매 영업일 CPI·근원CPI·PCE·근원PCE 의 '현재 달' 물가를 추정해 발표한다.
BLS/BEA 공표 전에 그 달 물가가 얼마로 나올지 미리 보는 용도다.

공개 API 는 없고, 페이지가 차트를 그릴 때 부르는 JSON 을 그대로 받는다. 키는 필요 없다.
  {BASE}/nowcast_month.json      전월비 %
  {BASE}/nowcast_year.json       전년동월비 %
  {BASE}/nowcast_quarter.json    분기 연율 %

파일 구조 (FusionCharts 설정 배열):
  [ {chart:{subcaption:"2026-9"},               # 대상 월 (분기 파일은 "2026:Q3")
     categories:[{category:[{label:"09/01"},…]}],  # 빈티지 날짜 = 나우캐스트를 만든 날
     dataset:[{seriesname:"CPI Inflation", data:[{value:"0.36"},…]}, …]}, … ]

  · 대상 월 하나에 차트 하나. 2013-07 부터 159개.
  · dataset 은 나우캐스트 4종 + 확정 후 채워지는 'Actual…' 4종 (분기 파일엔 Actual 없음).
  · **label 에 연도가 없다.** 'MM/DD' 뿐이라 대상 월에서 되짚어야 한다 (_vintage_dates).
  · categories 에 `vline:true` 인 항목(발표일 표시선)이 섞여 있는데 **data 인덱스를
    차지하지 않는다.** 이걸 빼지 않고 인덱스를 맞추면 값이 하루씩 밀린다.

내보내는 계열:
  {기준} · {측정치} 나우캐스트   월말 날짜 · 그 달의 마지막 빈티지 값
  {기준} · {측정치} 실제         월말 날짜 · 확정치
  빈티지 · {기준} · {대상월} · {측정치}   일별 · 최근 vintage_months 개 대상월만

빈티지를 최근 것만 남기는 이유는 크기다. 159개월 전부를 일별로 담으면 파일이
수 MB 가 된다 — 화면에서 실제로 훑어보는 건 최근 1년치다.
"""
import calendar
import re
from datetime import date

import requests

BASE = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting"
BASIS = {"month": "전월비", "year": "전년동월비", "quarter": "분기연율"}
MEAS = {
    "CPI Inflation": "CPI",
    "Core CPI Inflation": "근원 CPI",
    "PCE Inflation": "PCE",
    "Core PCE Inflation": "근원 PCE",
}
ACTUAL = {f"Actual {k}": v for k, v in MEAS.items()}
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
TIMEOUT = 60


class ClevelandError(RuntimeError):
    pass


def _month_end(y: int, m: int) -> str:
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def _target(sub: str) -> tuple[int, int] | None:
    """'2026-9' 또는 '2026:Q3' → (연, 대상 월). 분기는 분기 마지막 달로 본다."""
    sub = (sub or "").strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", sub)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{4}):Q([1-4])$", sub)
    if m:
        return int(m.group(1)), int(m.group(2)) * 3
    return None


def _vintage_dates(labels: list[tuple[int, int]], ty: int, tm: int) -> list[str]:
    """'MM/DD' 라벨에 연도를 붙인다.

    라벨에 연도가 없다. 나우캐스트는 대상 월 2~3개월 전에 시작해 발표(대상 월
    다음 달 중순)까지 이어지므로, 첫 라벨의 월이 대상 월보다 한참 뒤면 전년도다.
    이후로는 월 숫자가 작아질 때마다 해를 하나 올린다.
    """
    if not labels:
        return []
    first = labels[0][0]
    diff = first - tm
    y = ty - 1 if diff > 6 else (ty + 1 if diff < -6 else ty)
    out, prev = [], first
    for mm, dd in labels:
        if mm < prev:
            y += 1
        prev = mm
        out.append(f"{y:04d}-{mm:02d}-{dd:02d}")
    return out


def parse_chart(entry: dict) -> dict | None:
    """차트 설정 하나 → {'ty','tm','dates':[…], 'vals':{시리즈명: [값|None]}}.

    수집과 분리해 두어 저장된 응답으로 테스트할 수 있게 한다.
    """
    tgt = _target(((entry or {}).get("chart") or {}).get("subcaption", ""))
    if not tgt:
        return None
    ty, tm = tgt
    cats = (((entry.get("categories") or [{}])[0]).get("category")) or []
    labels = []
    for c in cats:
        if not isinstance(c, dict) or c.get("vline"):     # 발표일 표시선은 data 를 안 쓴다
            continue
        m = DATE_RE.match(str(c.get("label", "")).strip())
        if m:
            labels.append((int(m.group(1)), int(m.group(2))))
    dates = _vintage_dates(labels, ty, tm)
    if not dates:
        return None

    vals = {}
    for ds in entry.get("dataset") or []:
        if not isinstance(ds, dict):
            continue
        name = (ds.get("seriesname") or "").strip()
        row = []
        for i in range(len(dates)):
            pt = (ds.get("data") or [{}] * len(dates))
            v = pt[i].get("value") if i < len(pt) and isinstance(pt[i], dict) else None
            try:
                row.append(float(v) if v not in (None, "") else None)
            except (TypeError, ValueError):
                row.append(None)
        vals[name] = row
    return {"ty": ty, "tm": tm, "dates": dates, "vals": vals}


def _last(row: list) -> float | None:
    for v in reversed(row or []):
        if v is not None:
            return v
    return None


def _get(session: requests.Session, key: str) -> list:
    url = f"{BASE}/nowcast_{key}.json"
    r = session.get(url, params={"sc_lang": "en"}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ClevelandError(f"{url}: 배열이 아닌 응답 ({type(data).__name__})")
    return data


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params") or {}
    which = p.get("files") or ["year", "month"]
    keep = int(p.get("vintage_months", 12))

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting",
    })

    series: list[dict] = []
    for key in which:
        basis = BASIS.get(key, key)
        charts = [c for c in (parse_chart(e) for e in _get(s, key)) if c]
        if not charts:
            print(f"  [clevelandfed {indicator['id']}] {key}: 파싱된 차트 없음")
            continue
        charts.sort(key=lambda c: (c["ty"], c["tm"]))

        # ① 대상 월별 최종 나우캐스트 · 확정치
        for table, tag in ((MEAS, "나우캐스트"), (ACTUAL, "실제")):
            for raw, ko in table.items():
                pts = []
                for c in charts:
                    v = _last(c["vals"].get(raw))
                    if v is not None:
                        pts.append({"d": _month_end(c["ty"], c["tm"]), "v": v})
                if pts:
                    series.append({"name": f"{basis} · {ko} {tag}", "data": pts})

        # ② 최근 대상 월의 일별 빈티지 경로
        for c in charts[-keep:]:
            tlab = f"{c['ty']:04d}-{c['tm']:02d}"
            for raw, ko in MEAS.items():
                row = c["vals"].get(raw) or []
                pts = [{"d": d, "v": v} for d, v in zip(c["dates"], row) if v is not None]
                if pts:
                    series.append({"name": f"빈티지 · {basis} · {tlab} · {ko}", "data": pts})

        span = f"{charts[0]['ty']}-{charts[0]['tm']:02d} ~ {charts[-1]['ty']}-{charts[-1]['tm']:02d}"
        print(f"  [clevelandfed {indicator['id']}] {key:<8} 대상 {len(charts)}개 ({span})"
              f" · 최신 빈티지 {charts[-1]['dates'][-1]}")

    if not series:
        raise ClevelandError(
            "나우캐스트 응답이 비었습니다. 페이지가 부르는 JSON 경로가 바뀌었을 수 있습니다 "
            "— 브라우저 개발자도구 Network 에서 nowcast_*.json 을 확인하세요."
        )
    return series


if __name__ == "__main__":   # python -m fetchers.clevelandfed  → 구조 확인
    got = fetch({"id": "probe", "params": {"vintage_months": 1}})
    for x in got[:12]:
        print(f"{x['name']:<40} {len(x['data']):>4}점  "
              f"{x['data'][0]['d']} ~ {x['data'][-1]['d']}  최신 {x['data'][-1]['v']:.3f}")
    print(f"... 총 {len(got)}개 계열")

"""일본 재무성(MOF) 국채 금리 수집기 — JGB 만기별 일별 금리.

엔캐리 분석의 핵심 재료다. 미일 2년물 금리차를 보려면 일본 2년물이 필요한데
FRED 에는 일본 10년물(OECD)만 있고 2년물이 없다. MOF 가 1974년부터 만기별
일별 금리를 CSV 로 공개하므로 그걸 직접 받는다.

  현재연도  .../interest_rate/jgbcme.csv
  전체이력  .../interest_rate/historical/jgbcme_all.csv   (1974~)

일본어판(jgbcm.csv)은 Shift-JIS 에 날짜가 화력(R8.9.1)이라 파싱이 지저분하다.
영문판(jgbcme.csv)은 ASCII 에 날짜가 2026/9/1 이라 그대로 쓸 수 있다.

indicators.yaml 예:
  - id: mkt_jgb
    name: 일본 국채금리
    source: mof
    freq: D
    merge_always: true
    params:
      tenors: {"2Y": "일본 국채 2년", "10Y": "일본 국채 10년"}
"""
import csv
import io
import re
from datetime import date

import requests

BASE = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
CUR = BASE + "jgbcme.csv"
ALL = BASE + "historical/jgbcme_all.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DEFAULT_TENORS = {"2Y": "일본 국채 2년", "10Y": "일본 국채 10년"}


class MofError(RuntimeError):
    pass


def _to_date(s: str) -> str | None:
    """'2026/9/1' → '2026-09-01'."""
    m = re.fullmatch(r"\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*", s or "")
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _num(v):
    t = str(v or "").strip()
    if t in ("", "-", "*"):          # 휴장일은 '-' 로 온다
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse(text: str, tenors: dict) -> list[dict]:
    """CSV 본문 → 시리즈 목록. 수집과 분리해 저장된 응답으로 테스트할 수 있게 한다."""
    rows = list(csv.reader(io.StringIO(text)))
    # 헤더 줄을 찾는다 ('Date,1Y,2Y,...'). 위에 제목 줄이 하나 있다.
    hi = next((i for i, r in enumerate(rows)
               if r and r[0].strip().lower() == "date"), None)
    if hi is None:
        raise MofError("CSV 에서 헤더(Date,1Y,2Y,...) 를 찾지 못했습니다.")
    head = [c.strip() for c in rows[hi]]
    pos = {h: i for i, h in enumerate(head)}
    miss = [t for t in tenors if t not in pos]
    if miss:
        raise MofError(f"CSV 에 없는 만기: {miss} (헤더: {head[:6]}…)")
    acc = {name: [] for name in tenors.values()}
    for r in rows[hi + 1:]:
        if not r or len(r) < 2:
            continue
        d = _to_date(r[0])
        if d is None:
            continue
        for ten, name in tenors.items():
            v = _num(r[pos[ten]]) if pos[ten] < len(r) else None
            if v is not None:
                acc[name].append({"d": d, "v": v})
    return [{"name": n, "data": sorted(acc[n], key=lambda p: p["d"])}
            for n in tenors.values() if acc[n]]


def _get(url: str) -> str:
    r = requests.get(url, timeout=90, headers=UA)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 하나 → 시리즈 목록 (다른 수집기와 동일 형식)."""
    p = indicator.get("params") or {}
    tenors = p.get("tenors") or DEFAULT_TENORS
    iid = indicator.get("id", "?")
    # 전체 이력은 1974년부터라 3MB 가까이 된다. 아카이브가 있으면 올해분만 받는다.
    want_all = bool(indicator.get("_full")) or not indicator.get("_has_archive", True)
    urls = [ALL, CUR] if want_all else [CUR]
    out, seen = [], set()
    for u in urls:
        try:
            got = parse(_get(u), tenors)
        except Exception as e:
            print(f"  [mof {iid}] {u.rsplit('/', 1)[-1]} 실패: {str(e)[:150]}")
            continue
        n = sum(len(s["data"]) for s in got)
        span = min(s["data"][0]["d"] for s in got) + " ~ " + max(s["data"][-1]["d"] for s in got)
        print(f"  [mof {iid}] {u.rsplit('/', 1)[-1]} → 시리즈 {len(got)}개, 관측치 {n}개 ({span})")
        for s in got:
            if s["name"] in seen:                     # 같은 이름이면 뒤엣것을 덧씌운다
                tgt = next(x for x in out if x["name"] == s["name"])
                m = {q["d"]: q["v"] for q in tgt["data"]}
                m.update({q["d"]: q["v"] for q in s["data"]})
                tgt["data"] = [{"d": d, "v": v} for d, v in sorted(m.items())]
            else:
                out.append(s)
                seen.add(s["name"])
    if not out:
        raise MofError(f"MOF 응답이 비었습니다 ({iid}).")
    return out

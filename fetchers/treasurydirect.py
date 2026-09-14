"""미 재무부 국채 입찰 수집기 (TreasuryDirect Auction Query API).

https://www.treasurydirect.gov/auctions/ 가 쓰는 공개 API 를 그대로 부른다. 키 불필요.

  /TA_WS/securities/search?format=json&startDate=&endDate=&dateFieldName=auctionDate
      과거 입찰 결과. 2010년부터 있고 한 번에 5,700건까지 받아진다.
  /TA_WS/securities/upcoming?format=json     앞으로 예정된 입찰 (조건 미확정 포함)
  /TA_WS/securities/announced?format=json&days=N   발표된 입찰 (발행액 확정)

명목 이표물만 받는다. Bill 은 건수가 3배인데 금리 이야기에는 덜 쓰여 뺐고,
TIPS·FRN 도 뺐다 — 둘은 별도 타입이 아니라 Note/Bond 안에서 tips='Yes' /
floatingRate='Yes' 플래그로 구분된다. 실질금리·스프레드를 따로 볼 일이 생기면
params 에 include_tips: true 를 주면 다시 들어온다 (라벨에 ' TIPS'·' FRN' 이 붙는다).

**테일은 이 API 로 못 만든다.** 테일 = 낙찰금리 − WI(when-issued) 금리인데 WI 호가가
없다. 대신 응찰률·간접비중을 같은 만기 직전 회차들과 비교하는 게 대체재다 (화면에서 계산).

내보내는 계열 — 두 종류가 섞여 있다.
  ① 차트용 시계열: '10Y · 응찰률' 처럼 만기별 지표. d=입찰일, v=값
  ② 표용 원자료:  '입찰 결과' / '입찰 예정'. 점마다 d·v 외에 만기·CUSIP·낙찰금리 등
     추가 필드를 달았다. 일반 지표 화면은 d·v 만 보므로 무시되고, 전용 화면만 읽는다.

간접·직접·딜러 비중의 분모는 **총 낙찰액(totalAccepted)** 이다. 재무부 결과표와 같은
기준이라 발표 숫자와 바로 대조된다 (경쟁입찰 낙찰액으로 나누면 살짝 커진다).
"""
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

BASE = "https://www.treasurydirect.gov/TA_WS/securities"
TIMEOUT = 90
CHUNK_YEARS = 4          # search 를 한 번에 부를 연수 (응답이 너무 커지지 않게)
BN = 1e9                 # 달러 → 십억달러


class TreasuryDirectError(RuntimeError):
    pass


def _f(x):
    try:
        return float(x) if x not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _d(x):
    """'2026-09-10T00:00:00' → '2026-09-10'."""
    s = (x or "").strip()
    return s[:10] if len(s) >= 10 else None


def term_label(rec: dict) -> str | None:
    """'30-Year' → '30Y'. 재발행은 originalSecurityTerm 으로 원래 만기에 묶는다.

    securityTerm 을 쓰면 재발행이 '29-Year 11-Month' 로 따로 떨어져 나가
    같은 30년물 입찰이 두 계열로 갈린다.
    """
    t = (rec.get("originalSecurityTerm") or rec.get("securityTerm") or "").strip()
    m = re.match(r"^(\d+)-Year$", t)
    lab = f"{m.group(1)}Y" if m else None
    if not lab:
        m = re.match(r"^(\d+)-Week$", t)
        lab = f"{m.group(1)}W" if m else None
    if not lab:
        m = re.match(r"^(\d+)-Year\s+(\d+)-Month$", t)      # 이례적인 만기는 반올림해 묶는다
        if m:
            y = int(m.group(1)) + (1 if int(m.group(2)) >= 6 else 0)
            lab = f"{y}Y"
    if not lab:
        return None
    if (rec.get("tips") or "").lower() == "yes":
        lab += " TIPS"
    elif (rec.get("floatingRate") or "").lower() == "yes":
        lab += " FRN"
    return lab


def _row(rec: dict) -> dict | None:
    """입찰 한 건 → 표에 쓸 얇은 점. 원본 90개 필드 중 12개만 남긴다."""
    d = _d(rec.get("auctionDate"))
    lab = term_label(rec)
    if not d or not lab:
        return None
    acc = _f(rec.get("totalAccepted"))
    share = lambda k: (round(_f(rec.get(k)) / acc * 100, 2)
                       if acc and _f(rec.get(k)) is not None else None)
    off = _f(rec.get("offeringAmount"))
    out = {
        "d": d,
        "v": round(off / BN, 3) if off else None,      # 발행액(십억달러) — 차트 기본값
        "t": lab,
        "ty": rec.get("securityType"),
        "cusip": rec.get("cusip"),
        "iss": _d(rec.get("issueDate")),
        "mat": _d(rec.get("maturityDate")),
    }
    if (rec.get("reopening") or "").lower() == "yes":
        out["re"] = 1
    btc, hy = _f(rec.get("bidToCoverRatio")), _f(rec.get("highYield"))
    if btc is not None:
        out["btc"] = round(btc, 3)
    if hy is not None:
        out["hy"] = round(hy, 4)
    tot = _f(rec.get("totalTendered"))
    if tot:
        out["tend"] = round(tot / BN, 3)
    if acc:
        out["acc"] = round(acc / BN, 3)
        out["ind"] = share("indirectBidderAccepted")
        out["dir"] = share("directBidderAccepted")
        out["pd"] = share("primaryDealerAccepted")
    return out


# ── 분기 리펀딩(QRA)이 내놓는 '잠정 입찰 일정표'
#   https://home.treasury.gov/system/files/221/TentativeAuctionScheduleQ32026.xml
#   약 6개월 앞까지 **날짜만** 준다 — 발행액은 없다. 규모는 발표(announced) 전까지
#   알 수 없어서, 화면에서 직전 동일만기 규모로 이월하고 '추정'으로 표시한다.
#   파일명이 분기 태그(Q3 2026)라 최근 분기부터 거꾸로 찾아본다.
SCHED_URL = "https://home.treasury.gov/system/files/221/TentativeAuctionSchedule{tag}.xml"


def _schedule(session, today):
    tags, q, y = [], (today.month - 1) // 3 + 1, today.year
    for _ in range(3):                       # 이번 분기 → 직전 → 그 전
        tags.append(f"Q{q}{y}")
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    for tag in tags:
        url = SCHED_URL.format(tag=tag)
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                print(f"  [treasurydirect] 일정표 {tag}: HTTP {r.status_code}")
                continue
            # BOM('﻿')이 붙어 오면 ET.fromstring 이 그대로 터진다. 앞쪽 공백·BOM 을 걷어낸다.
            txt = r.text.lstrip("﻿ \t\r\n")
            root = ET.fromstring(txt)
        except (requests.RequestException, ET.ParseError) as e:
            print(f"  [treasurydirect] 일정표 {tag}: {type(e).__name__} {e}")
            continue
        out = []
        for e in root.iter("AuctionCalendarDate"):
            g = lambda k: (e.findtext(k) or "").strip()
            out.append({
                "originalSecurityTerm": g("SecurityTermWeekYear"),
                "securityType": g("SecurityType").title(),      # NOTE → Note
                "tips": g("TIPS"), "floatingRate": g("FloatingRate"),
                "reopening": "Yes" if g("ReOpeningIndicator") == "Y" else "No",
                "auctionDate": g("AuctionDate"), "issueDate": g("SettlementDate"),
                "announcementDate": g("AnnouncementDate"),
            })
        name = root.findtext("AuctionCalendarName") or tag
        return out, name.strip(), root.findtext("EndDate")
    return [], None, None


def _get(session, path, **params):
    params["format"] = "json"
    r = session.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise TreasuryDirectError(f"{path}: 배열이 아닌 응답 ({type(data).__name__})")
    return data


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params") or {}
    start_year = int(indicator.get("_start_year") or p.get("start_year") or 2010)
    want_tips = bool(p.get("include_tips"))
    today = date.today()

    def skip(rec):
        if rec.get("securityType") == "Bill":
            return True
        if want_tips:
            return False
        return ((rec.get("tips") or "").lower() == "yes"
                or (rec.get("floatingRate") or "").lower() == "yes")

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.treasurydirect.gov/auctions/",
    })

    # ── 과거 결과 (연도 구간을 나눠서)
    seen, hist = set(), []
    y = start_year
    while y <= today.year:
        z = min(y + CHUNK_YEARS - 1, today.year)
        rows = _get(s, "search", startDate=f"{y}-01-01",
                    endDate=f"{z}-12-31" if z < today.year else today.isoformat(),
                    dateFieldName="auctionDate")
        got = 0
        for rec in rows:
            if skip(rec):
                continue
            key = (rec.get("cusip"), _d(rec.get("auctionDate")))
            if key in seen:
                continue          # 재발행이 여러 구간에 걸쳐 중복으로 올 수 있다
            r = _row(rec)
            if r:
                seen.add(key); hist.append(r); got += 1
        print(f"  [treasurydirect {indicator['id']}] {y}~{z}: 이표물 {got}건 (원자료 {len(rows)}건)")
        y = z + 1
    if not hist:
        raise TreasuryDirectError(
            "입찰 결과를 받지 못했습니다. treasurydirect.gov 의 TA_WS 경로가 바뀌었는지 확인하세요.")
    hist.sort(key=lambda r: (r["d"], r["t"]))

    # ── 예정 — upcoming 에는 발행액이 없을 수 있어 announced 로 채운다
    up = {}
    for rec in _get(s, "upcoming"):
        if skip(rec):
            continue
        r = _row(rec)
        if r:
            up[r["cusip"]] = r
    for rec in _get(s, "announced", days=60):
        if skip(rec):
            continue
        r = _row(rec)
        if not r or r["d"] < today.isoformat():
            continue
        cur = up.get(r["cusip"])
        if cur is None or (cur.get("v") is None and r.get("v") is not None):
            up[r["cusip"]] = r
    # ── QRA 잠정 일정표로 예정을 6개월까지 늘린다. 발행액이 없으므로 직전 동일만기
    #    규모를 이월하고 est=1 로 찍는다 — 화면이 확정치와 구분해 보여준다.
    sched, schedName, schedEnd = _schedule(s, today)
    lastAmt = {}
    for r in hist:                                   # 만기별 최근 발행액
        if r.get("v") is not None:
            lastAmt[r["t"]] = r["v"]
    have = {(r["d"], r["t"]) for r in up.values()}
    added = 0
    for rec in sched:
        if skip(rec):
            continue
        r = _row(rec)
        if not r or r["d"] < today.isoformat() or (r["d"], r["t"]) in have:
            continue
        r["cusip"] = None                            # 아직 배정 전이다
        if r.get("v") is None and r["t"] in lastAmt:
            r["v"] = lastAmt[r["t"]]
            r["est"] = 1                             # 이월한 추정 규모
        up[f"sched|{r['d']}|{r['t']}"] = r
        added += 1
    plan = sorted(up.values(), key=lambda r: (r["d"], r["t"]))
    print(f"  [treasurydirect {indicator['id']}] 예정 {len(plan)}건"
          + (f" ({plan[0]['d']} ~ {plan[-1]['d']})" if plan else "")
          + (f" · 일정표 '{schedName}' 에서 {added}건 추가 (~{schedEnd}, 규모는 직전 회차 이월)"
             if schedName else " · [warn] QRA 잠정 일정표를 못 받았습니다"))

    series = [
        {"name": "입찰 결과", "data": hist},
        {"name": "입찰 예정", "data": plan},
    ]

    # ── 만기별 지표 시계열 (차트용). 값이 있는 만기만 만든다.
    METRICS = [("btc", "응찰률"), ("ind", "간접비중"), ("hy", "낙찰금리"), ("v", "발행액")]
    # 명목물 먼저 짧은 만기 순, 그다음 TIPS·FRN
    tkey = lambda t: (1 if ('TIPS' in t or 'FRN' in t) else 0, int(re.match(r"\d+", t).group()))
    terms = sorted({r["t"] for r in hist}, key=tkey)
    for t in terms:
        rows = [r for r in hist if r["t"] == t]
        for key, ko in METRICS:
            pts = [{"d": r["d"], "v": r[key]} for r in rows if r.get(key) is not None]
            if pts:
                series.append({"name": f"{t} · {ko}", "data": pts})
    print(f"  [treasurydirect {indicator['id']}] 결과 {len(hist)}건 · 만기 {len(terms)}종 "
          f"({hist[0]['d']} ~ {hist[-1]['d']})")
    return series


if __name__ == "__main__":   # python -m fetchers.treasurydirect
    got = fetch({"id": "probe", "params": {"start_year": 2024}})
    for x in got[:6]:
        print(f"{x['name']:<18} {len(x['data']):>5}건  {x['data'][0]['d']} ~ {x['data'][-1]['d']}")
    print(f"... 총 {len(got)}개 계열")

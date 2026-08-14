"""통계청 나우캐스트 포털 수집기 — 주간 속보성 지표.

포털(data.kostat.go.kr/nowcast)이 화면을 그릴 때 쓰는 내부 엔드포인트를 그대로 호출한다.
공식 공개 API는 아니고 인증키도 필요 없다. 응답이 JSON이라 그대로 파싱한다.

  POST /nowcast/listIndcrDataAjax.do
    indcr_id : 지표 번호 (1 = 신용카드이용금액)
    wklId    : 비교 시점(주 단위). 0=2020년 1월 기준 / 1=지난주 / 4=4주전 / 52=52주전(YoY)
    val1, cd2, val2, mode : 세분류·지역 (전체면 빈 문자열)
    initId   : 화면 초기 지표 id (indcr_id 와 같게 보낸다)
  응답 {"data":[{"BASE_DT": 에폭ms, "INDCR_VL": 소수}], "info":[{"KO_INDCR_NM": 지표명}], ...}

주의:
  · INDCR_VL 은 비율이라 100을 곱해야 %가 된다.
  · 신용카드이용금액의 출처는 **신한카드 단일사 표본**이다. 여신금융협회 전체 집계
    (ECOS 601Y003 / KOSIS 435)와는 모집단이 달라 같은 계열로 이어 붙이면 안 된다.
  · 주간이라 명절·요일 배열에 크게 흔들린다. 포털도 4주 이동평균을 함께 보여준다.
  · 속보치라 최근 1~2주는 확정치가 아니다. 다음 수집 때 값이 바뀐다.

indicators.yaml 예:
  - id: kr_card_weekly
    name: 신용카드이용금액 (주간, 나우캐스트)
    source: nowcast
    unit: '%'
    freq: W
    params:
      indcr_id: 1
      wkl_ids: [52, 4, 1, 0]      # 받아올 비교시점들 (생략하면 [52])
"""
import time
from datetime import datetime, timezone, timedelta

import requests

BASE = "https://data.kostat.go.kr/nowcast"
DATA_URL = f"{BASE}/listIndcrDataAjax.do"
INFO_URL = f"{BASE}/listIndcrInfoAjax.do"

# 업종분류 축 (cd2) 과 그 값(val2). 포털 화면에서 확인한 코드다.
#   COICOP 대분류를 따르며, 신용카드이용금액(indcr_id=1)은 7개 업종만 제공한다.
SECTOR_AXIS = "A00029"
SECTORS = {
    "01": "식료품·음료",
    "03": "의류·신발",
    "06": "보건",
    "09": "오락·스포츠·문화",
    "10": "교육서비스",
    "111": "음식·음료서비스",
    "112": "숙박서비스",
}

# wklId → 시리즈명에 붙일 꼬리표
WKL_LABEL = {
    0: "2020년 1월 대비",
    1: "전주 대비",
    4: "4주 전 대비",
    52: "전년 동주 대비",
}

KST = timezone(timedelta(hours=9))


class NowcastError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{BASE}/main.do?initId=1",
        "Origin": "https://data.kostat.go.kr",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })
    # 세션 쿠키를 먼저 받아둔다 (일부 WAS가 첫 POST를 거른다)
    try:
        s.get(f"{BASE}/main.do?initId=1", timeout=30)
    except requests.RequestException:
        pass
    return s


def _to_date(epoch_ms) -> str:
    """에폭 밀리초 → 'YYYY-MM-DD' (KST 기준 날짜)."""
    return datetime.fromtimestamp(int(epoch_ms) / 1000, KST).strftime("%Y-%m-%d")


def list_indicators() -> list[tuple[int, str]]:
    """포털이 제공하는 지표 (id, 이름) 목록. 새 지표를 붙일 때 참고용."""
    s = _session()
    r = s.post(INFO_URL, data={}, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if isinstance(rows, dict):
        rows = list(rows.values())
    out = []
    for x in rows:
        if isinstance(x, dict) and x.get("INDCR_ID") is not None:
            out.append((int(x["INDCR_ID"]), (x.get("KO_INDCR_NM") or "").strip()))
    return sorted(out)


def parse(payload: dict, wkl_id: int, fallback_name: str = "", prefix: str = "") -> dict | None:
    """응답 JSON 하나 → {"name":…, "data":[{"d":…,"v":…}]}. 데이터가 없으면 None.

    수집과 분리해 두어 저장된 응답으로 단위 테스트할 수 있게 한다.
    """
    rows = (payload or {}).get("data") or []
    info = (payload or {}).get("info") or []
    name = ""
    if info and isinstance(info[0], dict):
        name = (info[0].get("KO_INDCR_NM") or "").strip()
    name = name or fallback_name or "값"
    if prefix:
        name = f"{prefix} · {name}"

    points = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        v, d = r.get("INDCR_VL"), r.get("BASE_DT")
        if v is None or d is None:
            continue
        try:
            points.append({"d": _to_date(d), "v": float(v) * 100})   # 비율 → %
        except (TypeError, ValueError, OSError):
            continue
    if not points:
        return None
    points.sort(key=lambda p: p["d"])
    label = WKL_LABEL.get(wkl_id, f"{wkl_id}주 전 대비")
    return {"name": f"{name} · {label}", "data": points}


def to_index(series0: dict) -> dict | None:
    """'2020년 1월 대비 변화율(%)' 계열 → 수준 지수 (2020년 1월 = 100).

    포털은 변화율만 주지만 wklId=0 은 고정 기준(2020년 1월) 대비 누적 변화율이라
    지수로 되돌릴 수 있다.  I_t = 100 × (1 + v_t/100)

    지수로 바꿔 두면 3개월(13주) 이동평균이나 월별 집계처럼
    포털이 제공하지 않는 기간 묶음을 직접 계산할 수 있다.
    (검증: 이 지수에서 다시 뽑은 전주비·4주비·전년동주비가 원본과
     최대 오차 0.09%p, 평균 0.0002%p 로 일치한다 — 원자료 반올림 수준)
    """
    if not series0:
        return None
    pts = [{"d": p["d"], "v": 100.0 * (1.0 + p["v"] / 100.0)} for p in series0["data"]]
    if not pts:
        return None
    name = series0["name"].split(" · ")[0]
    return {"name": f"{name} · 지수 (2020년 1월=100)", "data": pts}


def fetch(indicator: dict) -> list[dict]:
    """indicators.yaml 지표 정의 하나 → 시리즈 목록 (다른 수집기와 동일 형식)."""
    p = indicator.get("params") or {}
    indcr_id = int(p.get("indcr_id", 1))
    wkl_ids = p.get("wkl_ids") or [52]
    # wklId=0 이 있으면 지수 계열을 하나 더 만들어 붙인다 (params.index: false 로 끔)
    want_index = p.get("index", True) and 0 in [int(w) for w in wkl_ids]
    val1 = p.get("val1", "")
    # 업종별: sectors: true 면 SECTORS 전체, 리스트면 그 코드만. 생략하면 전체(합계) 하나.
    sec = p.get("sectors")
    if sec is True:
        targets = [(SECTOR_AXIS, code, nm) for code, nm in SECTORS.items()]
    elif isinstance(sec, (list, tuple)):
        targets = [(SECTOR_AXIS, c, SECTORS.get(c, c)) for c in sec]
    else:
        targets = [(p.get("cd2", ""), p.get("val2", ""), "")]

    s = _session()
    series: list[dict] = []
    for cd2, val2, secName in targets:
        for w in wkl_ids:
            body = {
                "indcr_id": indcr_id, "val1": val1, "cd2": cd2, "val2": val2,
                "wklId": int(w), "mode": "", "initId": str(indcr_id),
            }
            try:
                r = s.post(DATA_URL, data=body, timeout=60)
                r.raise_for_status()
                payload = r.json() if r.text.strip() else {}
            except (requests.RequestException, ValueError) as e:
                print(f"  [nowcast {indicator['id']}] {secName or '전체'} wklId={w} 실패(건너뜀): {e}")
                continue
            got = parse(payload, int(w), prefix=secName)
            if got is None:
                print(f"  [nowcast {indicator['id']}] {secName or '전체'} wklId={w} 데이터 없음")
                continue
            print(f"  [nowcast {indicator['id']}] {(secName or '전체'):<16} wklId={w} → "
                  f"{len(got['data'])}주 ({got['data'][0]['d']} ~ {got['data'][-1]['d']})")
            series.append(got)
            time.sleep(0.3)

    if not series:
        raise NowcastError(
            f"나우캐스트 응답이 비었습니다 (indcr_id={indcr_id}). "
            "포털 화면이 열리는지, 엔드포인트가 바뀌지 않았는지 확인하세요."
        )
    if want_index:
        extra = []
        for x in [y for y in series if y["name"].endswith(WKL_LABEL[0])]:
            idx = to_index(x)
            if idx:
                print(f"  [nowcast {indicator['id']}] 지수 복원 · {idx['name']} → "
                      f"{len(idx['data'])}주 (최신 {idx['data'][-1]['v']:.1f})")
                extra.append(idx)
        series += extra
    return series


if __name__ == "__main__":   # python -m fetchers.nowcast  → 지표 목록 출력
    for i, nm in list_indicators():
        print(f"{i:>4}  {nm}")

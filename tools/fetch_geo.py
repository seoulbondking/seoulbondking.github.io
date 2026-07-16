"""행정구역 경계(GeoJSON)를 내려받아 대시보드용 docs/geo/geo.js 로 저장.

지도 드릴다운에 필요한 계층:
  - 전국 17개 시·도
  - 서울 25개 자치구 (권역별 색칠 → 자치구 색칠)
  - 인천 자치구 / 경기 시·군

출처: southkorea/southkorea-maps (KOSTAT 2018, MIT 라이선스)
사용법 (PC의 venv 파이썬):
  python tools/fetch_geo.py
결과: docs/geo/geo.js  (window.__GEO__ = { sido, seoul, incheon, gyeonggi })
"""
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
OUT = ROOT / "docs" / "geo"
BASE = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2018/json"
PROV_URL = f"{BASE}/skorea-provinces-2018-geo.json"
MUNI_URL = f"{BASE}/skorea-municipalities-2018-geo.json"

# 시·도 코드(앞 2자리) → 데이터에서 쓰는 짧은 이름
SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
    "51": "강원", "43": "충북", "44": "충남", "45": "전북", "52": "전북",
    "46": "전남", "47": "경북", "48": "경남", "50": "제주",
}


# 시·도 정식명 → 데이터 약칭
SIDO_NAME = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산",
    "세종특별자치시": "세종", "경기도": "경기",
    "강원도": "강원", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남",
    "제주특별자치도": "제주", "제주도": "제주",
}


def short_name(nm: str, code: str = "") -> str:
    """시·도 정식명을 데이터 약칭으로. 코드(앞2자리)를 우선 사용."""
    nm = (nm or "").strip()
    if nm in SIDO_NAME:
        return SIDO_NAME[nm]
    if code[:2] in SIDO:
        return SIDO[code[:2]]
    # 접미사 제거 폴백
    return re.sub(r"(특별자치도|특별자치시|특별시|광역시|특별자치|자치도|자치시)$", "", nm)


def get(url):
    print(f"다운로드: {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.json()


def prop_name(props: dict) -> str:
    for k in ("name", "NAME_2", "NAME_1", "sggnm", "adm_nm"):
        if props.get(k):
            return props[k]
    return ""


def prop_code(props: dict) -> str:
    # 'code'(예: '11010')만 엄격히 사용. 다른 필드는 뒤죽박죽이라 쓰지 않음.
    v = props.get("code")
    if v is None:
        v = props.get("adm_cd") or props.get("SIG_CD")
    return str(v) if v is not None else ""


def strip_islands(feat, east_lon=130.3, west_lon=125.7):
    """멀리 떨어진 섬 폴리곤 제거:
    - 동쪽(경도 > east_lon): 울릉도·독도
    - 서쪽(경도 최대값 < west_lon): 백령도·연평도·신안 서부 등 서해 도서
    본토(경계가 west_lon~east_lon 사이)는 유지.
    """
    def keep_poly(poly):
        lons = [pt[0] for ring in poly for pt in ring]
        if not lons:
            return False
        return not (min(lons) > east_lon or max(lons) < west_lon)

    g = feat.get("geometry") or {}
    t = g.get("type")
    if t == "Polygon":
        return feat if keep_poly(g["coordinates"]) else None
    if t == "MultiPolygon":
        keep = [poly for poly in g["coordinates"] if keep_poly(poly)]
        if not keep:
            return None
        g["coordinates"] = keep
    return feat


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prov = get(PROV_URL)
    muni = get(MUNI_URL)

    # 시·도: 이름 정규화 (코드 우선) + 울릉도·독도 제거
    sido_feats = []
    for f in prov["features"]:
        nm = short_name(prop_name(f["properties"]), prop_code(f["properties"]))
        f["properties"] = {"name": nm}
        if strip_islands(f) is not None:
            sido_feats.append(f)

    # 경기·인천 시군구 이름 (코드가 안 맞을 때 이름으로 분류). 시·군 + 일반구 포함.
    GYEONGGI_NAMES = set(
        "수원시 성남시 고양시 용인시 부천시 안산시 안양시 남양주시 화성시 평택시 의정부시 시흥시 파주시 "
        "김포시 광명시 광주시 군포시 오산시 이천시 양주시 안성시 구리시 포천시 의왕시 하남시 여주시 동두천시 "
        "과천시 양평군 가평군 연천군 "
        "장안구 권선구 팔달구 영통구 수정구 중원구 분당구 만안구 동안구 상록구 단원구 덕양구 일산동구 일산서구 "
        "처인구 기흥구 수지구 원미구 소사구 오정구".split())
    INCHEON_NAMES = set("남동구 부평구 계양구 연수구 미추홀구 강화군 옹진구 중구 동구 서구".split())

    all_counts = {}    # 진단용: 시·도별 개수
    none_samples = []  # 진단용: 미분류(None) 피처 원본 속성
    buckets = {"서울": [], "인천": [], "경기": []}
    for f in muni["features"]:
        props = f["properties"]
        code = prop_code(props)
        nm = prop_name(props).strip()
        short = nm.split()[-1] if " " in nm else nm
        first = nm.split()[0] if " " in nm else nm
        sido = SIDO.get(code[:2])
        if sido not in buckets:   # 코드로 서울/인천/경기 아니면 이름으로 재판정
            if short in GYEONGGI_NAMES or first in GYEONGGI_NAMES:
                sido = "경기"
            elif code[:2] != "11" and (short in INCHEON_NAMES) and code[:2] in ("28", ""):
                sido = "인천"
        all_counts[sido] = all_counts.get(sido, 0) + 1
        if sido is None and len(none_samples) < 8:
            none_samples.append({"code": code, "name": nm, "props": dict(props)})
        if sido in buckets:
            if "울릉" in nm or "독도" in nm:
                continue
            f["properties"] = {"name": short, "full": nm, "code": code}
            if strip_islands(f) is not None:
                buckets[sido].append(f)

    geo = {
        "sido": {"type": "FeatureCollection", "features": sido_feats},
        "seoul": {"type": "FeatureCollection", "features": buckets["서울"]},
        "incheon": {"type": "FeatureCollection", "features": buckets["인천"]},
        "gyeonggi": {"type": "FeatureCollection", "features": buckets["경기"]},
    }
    body = json.dumps(geo, ensure_ascii=False, separators=(",", ":"))
    (OUT / "geo.js").write_text("window.__GEO__=" + body + ";", encoding="utf-8")
    print(f"\n저장: {OUT / 'geo.js'}")
    print(f"  시·도 {len(sido_feats)} · 서울 {len(buckets['서울'])} "
          f"· 인천 {len(buckets['인천'])} · 경기 {len(buckets['경기'])}")
    # 진단: 시·도별 시군구 개수 (경기가 0이면 코드/이름 매칭 문제)
    print("  [진단] 원본 시군구 분류:",
          {k: v for k, v in sorted(all_counts.items(), key=lambda x: str(x[0]))})
    if not buckets["경기"]:
        print("  ⚠ 경기 0건. 미분류(None) 피처 원본 속성 샘플 ↓ (이걸 보고 매칭 보정)")
        for s in none_samples:
            print("     ", s["name"], "| code:", s["code"], "| props keys:", list(s["props"].keys()))
            print("        props:", {k: s["props"][k] for k in list(s["props"])[:6]})


if __name__ == "__main__":
    main()

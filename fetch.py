"""indicators.yaml 에 정의된 모든 지표를 수집해 docs/data/*.json 으로 저장.

사용법:
    python fetch.py              # 전체 수집 (증분)
    python fetch.py kr_gdp_real  # 특정 지표만
    python fetch.py --full       # 아카이브 무시하고 처음부터 전체 재수집

증분 수집:
    yaml 에 start_year 를 지정한 지표는 첫 실행에서 그 해부터 전체를 받아
    docs/data/<id>.json 에 아카이브하고, 이후 실행은 최근 refetch_years
    (기본 2년)만 다시 받아 기존 데이터에 병합한다 (통계 개정 반영).

API 키: 환경변수 또는 이 폴더의 .env 파일 (KOSIS_API_KEY=...)
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from fetchers import (bea, pce_diffusion, kosis, ecos, reb, bls, freesis, bok, seibro, fred, infomax,
                      acm, krx, ecos_xlsx, nowcast)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "docs" / "data"

# 소스 이름 → fetch 함수. 새 소스(fred, bls...)는 여기에 등록.
SOURCES = {
    "kosis": kosis.fetch,
    "ecos": ecos.fetch,
    "reb": reb.fetch,
    "bls": bls.fetch,
    "freesis": freesis.fetch,
    "bok": bok.fetch,
    "seibro": seibro.fetch,
    "fred": fred.fetch,
    "infomax": infomax.fetch,
    "acm": acm.fetch,
    "krx": krx.fetch,
    "ecos_xlsx": ecos_xlsx.fetch,
    "nowcast": nowcast.fetch,
    "bea": bea.fetch,
    "pce_diffusion": pce_diffusion.fetch,
}

KST = timezone(timedelta(hours=9))


def load_dotenv():
    """같은 폴더의 .env 파일을 환경변수로 로드.

    .env 값이 항상 우선한다(기존 OS 환경변수에 옛 키가 남아 있어도 .env로 덮어씀).
    단, 따옴표는 벗겨낸다. GitHub Actions엔 .env가 없어 Secrets 환경변수가 그대로 쓰인다.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def merge_series(old_series: list, new_series: list) -> list:
    """아카이브 시리즈에 신규 수집분을 병합 (같은 날짜는 신규 값으로 갱신).

    시리즈 구성은 신규 수집 기준 — 이름이 바뀐 옛 시리즈는 버린다.
    """
    old_map = {
        s["name"]: {p["d"]: p["v"] for p in s["data"]} for s in old_series
    }
    merged = []
    for s in new_series:
        pts = old_map.get(s["name"], {})
        pts.update({p["d"]: p["v"] for p in s["data"]})
        merged.append({
            "name": s["name"],
            "data": [{"d": d, "v": v} for d, v in sorted(pts.items())],
        })
    return merged


def derive_annual(base_payload: dict) -> list:
    """분기 시리즈를 연도별 합산해 연간 시리즈 생성 (4개 분기가 모두 있는 해만)."""
    series = []
    for s in base_payload["series"]:
        by_year: dict[str, list] = {}
        for p in s["data"]:
            by_year.setdefault(p["d"][:4], []).append(p["v"])
        data = [
            {"d": f"{y}-12-31", "v": round(sum(vs), 1)}
            for y, vs in sorted(by_year.items()) if len(vs) == 4
        ]
        if data:
            series.append({"name": s["name"], "data": data})
    return series


def archive_start_year(payload: dict) -> int | None:
    """아카이브 JSON에서 가장 이른 관측 연도."""
    try:
        return min(
            int(s["data"][0]["d"][:4]) for s in payload["series"] if s["data"]
        )
    except (KeyError, ValueError):
        return None


ALERT_TAIL_DAYS = 20      # 알림 계산에 필요한 최근 영업일 수 (5영업일 변동 + 여유)
# 알림 배지가 보는 지표. 일별 지표를 전부 담으면 금리 커브까지 딸려와 120KB 가 된다.
# 대시보드 index.html 의 FUND_ALERTS 가 쓰는 지표만 여기 적는다.
ALERT_INDICATORS = ["kr_fund_flow", "kr_repo_flow", "kr_bank_flow"]


def write_alert_tail(all_indicators: list[dict]) -> None:
    """알림용 '최근 며칠' 요약 파일 하나 (docs/data/alerts.js).

    대시보드 좌측 메뉴의 알림 배지는 첫 화면부터 떠야 하는데, 그러자고
    kr_fund_flow.js(2015년 백필 뒤 1.2MB)를 통째로 받는 건 낭비다.
    꼬리만 잘라 담으면 10KB 남짓이라 부담이 없다.
    """
    tail = {}
    for ind in all_indicators:
        if ind["id"] not in ALERT_INDICATORS:
            continue
        path = DATA_DIR / f"{ind['id']}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for s in payload.get("series", []):
            if s.get("data"):
                tail[s["name"]] = s["data"][-ALERT_TAIL_DAYS:]
    body = json.dumps({
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "days": ALERT_TAIL_DAYS,
        "series": tail,
    }, ensure_ascii=False)
    (DATA_DIR / "alerts.js").write_text(
        f"window.__MACRO_ALERTS__={body};", encoding="utf-8")
    print(f"[ok]   alerts.js: 시리즈 {len(tail)}개 × 최근 {ALERT_TAIL_DAYS}영업일"
          f" ({len(body.encode('utf-8')) / 1024:.1f}KB)")


def main():
    load_dotenv()
    config = yaml.safe_load((ROOT / "indicators.yaml").read_text(encoding="utf-8"))
    all_indicators = config["indicators"]     # 메뉴 목록은 항상 전체 기준
    indicators = all_indicators

    args = sys.argv[1:]
    force_full = "--full" in args
    only = {a for a in args if not a.startswith("--")}
    if only:
        indicators = [i for i in all_indicators if i["id"] in only]
        if not indicators:
            sys.exit(f"indicators.yaml 에 해당 id가 없습니다: {only}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    catalog, failures = [], []

    this_year = datetime.now(KST).year
    for ind in indicators:
        out_path = DATA_DIR / f"{ind['id']}.json"
        incremental = False

        if ind["source"] == "derived":
            # 파생 지표: 다른 지표의 아카이브에서 계산 (예: 분기 → 연간 합산)
            base_path = DATA_DIR / f"{ind['params']['from']}.json"
            try:
                base = json.loads(base_path.read_text(encoding="utf-8"))
                series = derive_annual(base)
            except Exception as e:
                print(f"[fail] {ind['id']}: 기반 지표({ind['params']['from']}) 오류 - {e}")
                failures.append(ind["id"])
                continue
            ind["_start_year"] = archive_start_year({"series": series}) or "-"
        else:
            fetch_fn = SOURCES.get(ind["source"])
            if fetch_fn is None:
                print(f"[skip] {ind['id']}: 알 수 없는 source '{ind['source']}'")
                continue

            # 수집 시작 연도 결정: 아카이브가 있으면 최근만(증분), 없으면 전체
            target_start = ind.get("start_year") or this_year - ind.get("lookback_years", 10)
            old = None
            if not force_full and out_path.exists():
                try:
                    old = json.loads(out_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    old = None
            # 아카이브가 설정된 시작연도보다 늦게 시작하면 (예: 2011 > 2000) 전체 재수집
            incremental = old is not None and (archive_start_year(old) or 9999) <= target_start
            ind["_start_year"] = (
                this_year - ind.get("refetch_years", 2) if incremental else target_start
            )
            ind["_full"] = force_full      # 수집기가 '이미 받은 날짜 건너뛰기'를 무시할 수 있게

            try:
                series = fetch_fn(ind)
            except Exception as e:  # 한 지표 실패가 전체를 막지 않도록
                print(f"[fail] {ind['id']}: {e}")
                failures.append(ind["id"])
                continue

            # merge_always: 일별 소스(FREESIS 등)는 최근치만 받아도 항상 아카이브에 병합
            if incremental or (ind.get("merge_always") and old is not None):
                # 새로 받은 게 없으면(예: KRX '남을 날짜 0일') 아카이브를 그대로 둔다.
                # merge_series 는 신규 목록 기준이라 빈 결과가 오면 아카이브가 통째로 지워진다.
                if not series and old.get("series"):
                    print(f"  [keep] {ind['id']}: 신규 수집 0건 — 기존 아카이브 유지")
                    series = old["series"]
                    if old.get("_checked"):
                        ind["_krx_checked"] = old["_checked"]
                else:
                    series = merge_series(old["series"], series)

        # series_first 에 지정된 항목(총계 등)을 맨 앞으로 정렬
        pinned = ind.get("series_first", [])
        if pinned:
            def sort_key(s, pinned=pinned):
                return pinned.index(s["name"]) if s["name"] in pinned else len(pinned)
            series = sorted(series, key=sort_key)

        payload = {
            "id": ind["id"],
            "name": ind["name"],
            "unit": ind.get("unit", ""),
            "freq": ind["freq"],
            "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
            "series": series,
        }
        # ECOS 가중치·대분류 (with_weights 지표) — 대시보드 기여도 계산용
        meta = ind.get("_weights_meta")
        if meta:
            payload["weights"] = meta.get("weights")
            payload["top_level"] = meta.get("top_level")
            if meta.get("parents"):
                payload["parents"] = meta["parents"]      # 항목명 → 상위 항목명 (트리)
            if meta.get("level_of"):
                payload["level_of"] = meta["level_of"]     # 항목명 → 계층 레벨
        if ind.get("_acm_meta"):
            payload["acm"] = ind["_acm_meta"]                      # ACM 추정 진단 (주성분·지속성·적합도)
        if ind.get("_krx_checked"):
            payload["_checked"] = ind["_krx_checked"]              # KRX 조회 완료일 (휴장일 재조회 방지)
        body = json.dumps(payload, ensure_ascii=False)
        out_path.write_text(body, encoding="utf-8")
        # 더블클릭(file://)으로도 대시보드가 열리도록 JS 버전도 함께 저장
        (DATA_DIR / f"{ind['id']}.js").write_text(
            f"window.__MACRO__=window.__MACRO__||{{}};window.__MACRO__[{json.dumps(ind['id'])}]={body};",
            encoding="utf-8",
        )
        n_points = sum(len(s["data"]) for s in series)
        tag = f"증분 {ind['_start_year']}~" if incremental else f"전체 {ind['_start_year']}~"
        print(f"[ok]   {ind['id']}: 시리즈 {len(series)}개, 관측치 {n_points}개 ({tag})")

    # 대시보드 메뉴 목록: 항상 전체 지표 기준으로, 데이터 파일이 있는 것만 수록.
    # (일부만 수집해도 메뉴가 갱신되고, 이번에 실패해도 기존 지표는 유지된다)
    catalog = [
        {"id": i["id"], "name": i["name"], "freq": i["freq"], "unit": i.get("unit", "")}
        for i in all_indicators if (DATA_DIR / f"{i['id']}.json").exists()
    ]
    cat_body = json.dumps(catalog, ensure_ascii=False)
    (DATA_DIR / "index.json").write_text(cat_body, encoding="utf-8")
    (DATA_DIR / "index.js").write_text(
        f"window.__MACRO_INDEX__={cat_body};", encoding="utf-8"
    )
    print(f"[ok]   index.json: 지표 {len(catalog)}개")
    write_alert_tail(all_indicators)

    if failures:
        print(f"\n⚠ 실패한 지표: {failures}")
        print("  (기존 데이터는 그대로 유지됩니다. 국내 API가 해외 IP를 차단하면"
              " GitHub Actions에서 KOSIS·부동산원이 실패할 수 있습니다.)")
        # 전부 실패했을 때만 오류로 종료 → 일부만 실패하면 성공분은 커밋되도록
        if len(failures) >= len(indicators):
            sys.exit(1)


if __name__ == "__main__":
    main()

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

from fetchers import kosis, ecos

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "docs" / "data"

# 소스 이름 → fetch 함수. 새 소스(fred, bls...)는 여기에 등록.
SOURCES = {
    "kosis": kosis.fetch,
    "ecos": ecos.fetch,
}

KST = timezone(timedelta(hours=9))


def load_dotenv():
    """같은 폴더의 .env 파일을 환경변수로 로드 (이미 있으면 유지)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


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


def archive_start_year(payload: dict) -> int | None:
    """아카이브 JSON에서 가장 이른 관측 연도."""
    try:
        return min(
            int(s["data"][0]["d"][:4]) for s in payload["series"] if s["data"]
        )
    except (KeyError, ValueError):
        return None


def main():
    load_dotenv()
    config = yaml.safe_load((ROOT / "indicators.yaml").read_text(encoding="utf-8"))
    indicators = config["indicators"]

    args = sys.argv[1:]
    force_full = "--full" in args
    only = {a for a in args if not a.startswith("--")}
    if only:
        indicators = [i for i in indicators if i["id"] in only]
        if not indicators:
            sys.exit(f"indicators.yaml 에 해당 id가 없습니다: {only}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    catalog, failures = [], []

    this_year = datetime.now(KST).year
    for ind in indicators:
        fetch_fn = SOURCES.get(ind["source"])
        if fetch_fn is None:
            print(f"[skip] {ind['id']}: 알 수 없는 source '{ind['source']}'")
            continue

        # 수집 시작 연도 결정: 아카이브가 있으면 최근만(증분), 없으면 전체
        target_start = ind.get("start_year") or this_year - ind.get("lookback_years", 10)
        out_path = DATA_DIR / f"{ind['id']}.json"
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

        try:
            series = fetch_fn(ind)
        except Exception as e:  # 한 지표 실패가 전체를 막지 않도록
            print(f"[fail] {ind['id']}: {e}")
            failures.append(ind["id"])
            continue

        if incremental:
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

    # 대시보드가 읽는 지표 목록 (전체 수집일 때만 갱신)
    if not only:
        catalog = [
            {"id": i["id"], "name": i["name"], "freq": i["freq"], "unit": i.get("unit", "")}
            for i in indicators if i["id"] not in failures
        ]
        cat_body = json.dumps(catalog, ensure_ascii=False)
        (DATA_DIR / "index.json").write_text(cat_body, encoding="utf-8")
        (DATA_DIR / "index.js").write_text(
            f"window.__MACRO_INDEX__={cat_body};", encoding="utf-8"
        )
        print(f"[ok]   index.json: 지표 {len(catalog)}개")

    if failures:
        sys.exit(f"실패한 지표: {failures}")


if __name__ == "__main__":
    main()

"""기관RP(REPO) 과거 잔고 수동 백필.

SEIBro는 최근 며칠치만 제공하므로, 직접 구한 과거 잔고를 CSV로 넣어
docs/data/kr_repo_flow.json 아카이브에 병합한다. 이후 자동수집(fetch.py)은
이 과거치를 보존하고 최근분만 갱신한다(merge_always).

CSV 형식 (헤더 있어도 됨, 구분자 , 또는 탭):
    날짜,잔고
    2026-01-02,915000
    2026/01/03,916200
    20260106,914800
  - 날짜: YYYY-MM-DD / YYYY/MM/DD / YYYYMMDD / 2026.01.02 모두 허용
  - 잔고: SEIBro에 지금 뜨는 값과 '같은 단위'로 (콤마 있어도 됨)

사용:
    python tools/backfill_repo.py 과거REPO.csv
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
JSON_PATH = DATA / "kr_repo_flow.json"


def _unquote(s):
    return str(s).strip().strip('"').strip("'").strip()


def norm_date(s: str):
    m = re.match(r"\s*(\d{4})[.\-/]?(\d{1,2})[.\-/]?(\d{1,2})", _unquote(s))
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def num(s):
    t = _unquote(s).replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python tools/backfill_repo.py <과거REPO.csv>   (열: 날짜, 잔고)")
    src = Path(sys.argv[1])
    if not src.exists():
        sys.exit(f"파일 없음: {src}")

    rows = {}
    for line in src.read_text(encoding="utf-8-sig").splitlines():
        # 첫 구분자까지가 날짜, 나머지가 값(값 안의 천단위 콤마 보존)
        m = re.match(r"\s*([^,\t;]+)[,\t;]\s*(.+)", line)
        if not m:
            continue
        d, v = norm_date(m.group(1)), num(m.group(2))
        if d and v is not None:
            rows[d] = v
    if not rows:
        sys.exit("CSV에서 (날짜, 잔고)를 못 읽었습니다. 형식을 확인하세요.")

    if JSON_PATH.exists():
        payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    else:
        payload = {"id": "kr_repo_flow", "name": "자금흐름 REPO (SEIBro)",
                   "unit": "억원", "freq": "D", "updated_at": "manual", "series": []}

    ser = next((s for s in payload["series"] if s["name"] == "기관RP"), None)
    if ser is None:
        ser = {"name": "기관RP", "data": []}
        payload["series"].append(ser)

    merged = {p["d"]: p["v"] for p in ser["data"]}
    added = sum(1 for d in rows if d not in merged)
    merged.update(rows)                      # 같은 날짜는 CSV 값으로 갱신
    ser["data"] = [{"d": d, "v": v} for d, v in sorted(merged.items())]

    body = json.dumps(payload, ensure_ascii=False)
    JSON_PATH.write_text(body, encoding="utf-8")
    (DATA / "kr_repo_flow.js").write_text(
        f'window.__MACRO__=window.__MACRO__||{{}};window.__MACRO__[{json.dumps("kr_repo_flow")}]={body};',
        encoding="utf-8")
    print(f"기관RP 백필 완료: CSV {len(rows)}개(신규 {added}) 병합 → "
          f"총 {len(ser['data'])}개 · 범위 {ser['data'][0]['d']} ~ {ser['data'][-1]['d']}")


if __name__ == "__main__":
    main()

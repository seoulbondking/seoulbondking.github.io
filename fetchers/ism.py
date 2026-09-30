"""ISM 제조업·서비스 PMI — data/us_ism.csv 를 읽는다.

ismworld.org 는 reCAPTCHA 로 막혀 있어 여기서 직접 받지 않는다. 발표가 나면
브라우저로 보고서를 열어 표를 뽑고 tools/ism_add.py 로 CSV 에 넣는다.
  제조업  .../ism-pmi-reports/pmi/{month}/        매달 첫 영업일
  서비스  .../ism-pmi-reports/services/{month}/   매달 셋째 영업일
공개 페이지는 최근 2개월치 보고서뿐이다. 과거 시계열은 그때그때 쌓아야 한다.

CSV: month,survey,item,value   (survey = mfg | svc, item = ISM 영문 항목명)
  '… PMI Consensus' 는 investing.com 발표 이력의 예상치(컨센서스)다. ISM 원문에는 없다.
  2008-06 ~ 2025-07 헤드라인도 investing.com '처음 발표된 값'으로 채웠다
  (원본: data/us_ism_investing_mfg.csv). ISM 원문 값은 계절조정 개정이 반영돼 ±0.2 쯤 다르다.
내보내는 계열 이름: '제조업 · 신규주문' 처럼 '{조사} · {한글 항목}'.
"""
import calendar
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "us_ism.csv"

SURVEY = {"mfg": "제조업", "svc": "서비스"}
# ISM 항목명 → 한글. 순서가 곧 화면 순서다.
ITEMS = {
    "mfg": [
        ("Manufacturing PMI", "PMI"),
        ("Manufacturing PMI Consensus", "PMI 컨센서스"),
        ("New Orders", "신규주문"),
        ("Production", "생산"),
        ("Employment", "고용"),
        ("Supplier Deliveries", "공급자 배송"),
        ("Inventories", "재고"),
        ("Customers' Inventories", "고객 재고"),
        ("Prices", "가격"),
        ("Backlog of Orders", "수주잔고"),
        ("New Export Orders", "신규 수출주문"),
        ("Imports", "수입"),
    ],
    "svc": [
        ("Services PMI", "PMI"),
        ("Services PMI Consensus", "PMI 컨센서스"),
        ("Business Activity", "사업활동"),
        ("New Orders", "신규주문"),
        ("Employment", "고용"),
        ("Supplier Deliveries", "공급자 배송"),
        ("Inventories", "재고"),
        ("Prices", "가격"),
        ("Backlog of Orders", "수주잔고"),
        ("New Export Orders", "신규 수출주문"),
        ("Imports", "수입"),
        ("Inventory Sentiment", "재고 체감"),
    ],
}


class IsmError(RuntimeError):
    pass


def _month_end(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    return f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


def fetch(ind: dict) -> list[dict]:
    path = Path(ind.get("params", {}).get("path") or CSV_PATH)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise IsmError(f"{path} 가 없습니다 — tools/ism_add.py 로 먼저 넣어 주세요")

    vals: dict[tuple[str, str], dict[str, float]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            vals.setdefault((r["survey"], r["item"]), {})[r["month"]] = float(r["value"])

    series = []
    for sv, items in ITEMS.items():
        for en, ko in items:
            got = vals.pop((sv, en), None)
            if not got:
                continue
            series.append({
                "name": f"{SURVEY[sv]} · {ko}",
                "data": [{"d": _month_end(ym), "v": v} for ym, v in sorted(got.items())],
            })
    if vals:
        print(f"  [ism] 목록에 없는 항목(무시): {sorted(k for k in vals)}")

    last = max(p["d"] for s in series for p in s["data"])
    print(f"  [ism] {path.name} → 시리즈 {len(series)}개 · 최신 {last[:7]}")
    return series

"""금융취약성지수(FVI)·금융불안지수(FSI) — data/kr_fvi.csv (+ kr_fvi_manual.csv)

두 지수는 ECOS 에 없다. 금융안정보고서(6·12월) 첨부 '그림 원본데이터' 엑셀을
tools/bok_fsr_import.py 로 kr_fvi.csv 에 옮기고, 그 사이(3·9월 '금융안정 상황')에
나온 값은 kr_fvi_manual.csv 에 손으로 적는다. 같은 (날짜, 항목)이면 보고서 값이 이긴다.

  FVI          분기, 2008~ (2025년 12월 개편: 신용·자산가격·금융기관 복원력 64개 지표)
  FVI (2000~)  분기, 2000~ — 위와 겹치는 구간은 값이 같다
  FSI (월)     월, 2008~ (2023년 12월 개편: 20개 지표, 주의 12 · 위기 24)
  FSI (분기)·국고채 3년 (분기)   2000~
  인상후 · {부문}  기준금리 인상 후 h0~h8 분기 FVI 부문별 반응 (한은 시산) — 날짜 아님
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["FVI", "FVI (2000~)", "FSI (월)", "FSI (분기)", "국고채 3년 (분기)"]


class FsrError(RuntimeError):
    pass


def _read(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {(r["date"], r["item"]): float(r["value"]) for r in csv.DictReader(f)}


def fetch(ind: dict) -> list[dict]:
    p = ind.get("params", {})
    main = _read(ROOT / p.get("path", "data/kr_fvi.csv"))
    if not main:
        raise FsrError("data/kr_fvi.csv 가 없습니다 — tools/bok_fsr_import.py 를 먼저 실행하세요")
    manual = _read(ROOT / p.get("manual", "data/kr_fvi_manual.csv"))
    added = {k: v for k, v in manual.items() if k not in main}
    vals = {**added, **main}
    items = sorted({i for _, i in vals}, key=lambda i: (ORDER.index(i) if i in ORDER else 99, i))
    series = [{"name": i, "data": [{"d": d, "v": v} for (d, it), v in sorted(vals.items()) if it == i]}
              for i in items]
    # 손으로 넣은 점은 따로도 내보낸다 — 화면에서 '잠정' 표시를 붙이려고
    if added:
        series.append({"name": "FVI · 수동", "data": [{"d": d, "v": v} for (d, i), v in sorted(added.items()) if i == "FVI"]})
    last = max(d for d, i in vals if i == "FVI")
    print(f"  [fsr] 시리즈 {len(series)}개 · FVI 최신 {last}"
          + (f" (수동 {len(added)}건 포함)" if added else ""))
    return series

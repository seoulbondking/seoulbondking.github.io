"""인포맥스 ISM 엑셀 → data/us_ism.csv (헤드라인 + 세부항목 전 기간).

인포맥스 엑셀 구조: 1행 조회조건, 2행 지표코드, 3행 지표명, 4행 '현재가', 5행부터 월말 날짜 내림차순.
열은 이름이 아니라 **지표코드**로 찾는다 (엑셀에서 열 순서를 바꿔도 안전).

주의 — 서비스는 날짜가 한 달 밀려 있다.
  인포맥스는 제조업을 '대상월' 말일에, 서비스를 '발표월' 말일에 찍는다.
  (2026-10-31 행의 서비스 54.9 = ISM 9월 서비스 보고서. ISM 원문·investing 와 대조해 확인)
  그래서 서비스만 한 달 당겨서 넣는다.

ISM 원문(웹 보고서)이 우선이라는 원칙에 따라 기본은 덮어쓴다. 인포맥스 값은 ISM 이
매년 1월 계절조정을 고친 '현재 값'이라 investing.com '처음 발표된 값'보다 정확하다.
컨센서스('… PMI Consensus')는 인포맥스에 없으므로 건드리지 않는다.

사용:
    python tools/ism_from_infomax.py                 # 미리보기 (차이만 출력, 저장 안 함)
    python tools/ism_from_infomax.py --apply         # CSV 에 반영
    python tools/ism_from_infomax.py 파일.xlsx --apply
"""
import sys
from collections import Counter
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ism_add import ROOT, load, save  # noqa: E402

DEFAULT_XLSX = ROOT / "ISM인포맥스.xlsx"

# 지표코드 → (조사, ISM 항목명)
CODES = {
    "131001": ("mfg", "Manufacturing PMI"),
    "701959": ("mfg", "New Orders"),
    "701960": ("mfg", "Production"),
    "701961": ("mfg", "Employment"),
    "701962": ("mfg", "Supplier Deliveries"),
    "701963": ("mfg", "Inventories"),
    "701964": ("mfg", "Customers' Inventories"),
    "701965": ("mfg", "Prices"),
    "701966": ("mfg", "Backlog of Orders"),
    "701967": ("mfg", "Imports"),
    "701968": ("mfg", "New Export Orders"),
    "131002": ("svc", "Services PMI"),
    "802626": ("svc", "New Orders"),
    "802627": ("svc", "Business Activity"),
    "802628": ("svc", "Employment"),
    "802629": ("svc", "Supplier Deliveries"),
    "802630": ("svc", "Inventories"),
    "802631": ("svc", "Inventory Sentiment"),
    "802632": ("svc", "Prices"),
    "802633": ("svc", "Backlog of Orders"),
    "802634": ("svc", "Imports"),
    "802635": ("svc", "New Export Orders"),
}
SHIFT = {"mfg": 0, "svc": -1}       # 서비스는 발표월 → 대상월


def _ym(d, shift):
    y, m = d.year, d.month + shift
    if m < 1:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def read(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    cols = {}
    for j, c in enumerate(rows[1]):
        c = str(c).strip() if c is not None else ""
        if c in CODES and c not in cols:          # 뒤쪽 보조 열(중복 코드)은 무시
            # 첫 지표의 코드는 날짜 열(A) 머리에 찍히고 값은 B 열에 있다
            cols[c] = 1 if j == 0 else j
    miss = [c for c in CODES if c not in cols]
    if miss:
        sys.exit(f"엑셀에 지표코드가 없습니다: {miss}")
    out = {}
    for r in rows[4:]:
        d = r[0]
        if not hasattr(d, "year"):
            continue
        for c, j in cols.items():
            v = r[j]
            if v is None or v == "":
                continue
            sv, item = CODES[c]
            out[(_ym(d, SHIFT[sv]), sv, item)] = f"{float(v):g}"
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    src = Path(args[0]) if args else DEFAULT_XLSX
    new = read(src)
    rows = load()

    added, changed = Counter(), []
    for k, v in new.items():
        if k not in rows:
            added[k[1]] += 1
        elif float(rows[k]) != float(v):
            changed.append((k, rows[k], v))

    for sv in ("mfg", "svc"):
        ms = sorted(k[0] for k in new if k[1] == sv)
        print(f"[infomax] {sv}: {ms[0]} ~ {ms[-1]} ({len(set(ms))}개월) · 새로 {added[sv]}건")
    big = [c for c in changed if abs(float(c[1]) - float(c[2])) > 0.5]
    print(f"[infomax] 기존 값과 다름 {len(changed)}건 (0.5p 넘는 것 {len(big)}건)")
    for (ym, sv, item), a, b in sorted(big)[:30]:
        print(f"  {ym} {sv} {item}: {a} → {b}")

    if not apply:
        print("\n미리보기입니다. 반영하려면 --apply")
        return
    rows.update(new)
    save(rows)
    print(f"저장: data/us_ism.csv ({len(rows)}행)")


if __name__ == "__main__":
    main()

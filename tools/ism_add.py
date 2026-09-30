"""ISM PMI 보고서 값을 data/us_ism.csv 에 병합한다.

ISM(ismworld.org)은 reCAPTCHA 로 막혀 있어 fetch.py 가 직접 받을 수 없다.
발표가 나면 브라우저로 보고서 페이지를 열어 표를 뽑고, 이 도구로 CSV 에 넣는다.
fetch.py us_ism 은 그 CSV 만 읽는다 (fetchers/ism.py).

입력 줄 형식 (브라우저 추출 결과 그대로):
    2026-08,Manufacturing PMI,54.6
    2026-08,New Orders,53.7

사용:
    python tools/ism_add.py mfg 추출.txt      # 제조업
    python tools/ism_add.py svc 추출.txt      # 서비스
    python tools/ism_add.py mfg 추출.txt --keep   # 이미 있는 값은 건드리지 않음
    (파일 대신 - 를 주면 표준입력)

--keep: investing.com 발표 이력처럼 '처음 발표된 값'으로 빈 달만 채울 때 쓴다.
  ISM 원문의 과거치는 계절조정 개정이 반영된 값이라 그쪽이 우선이다.

같은 (월, 조사, 항목)이 이미 있으면 새 값으로 덮어쓴다. ISM 은 매년 1월
계절조정 계수를 바꿔 과거치를 고치므로, 나중에 연 페이지 값이 더 정확하다.
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "us_ism.csv"
SURVEYS = {"mfg", "svc"}
FIELDS = ["month", "survey", "item", "value"]
LINE_RE = re.compile(r"^\s*(\d{4}-\d{2})\s*,\s*(.+?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def load() -> dict:
    rows = {}
    if CSV_PATH.exists():
        with CSV_PATH.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["month"], r["survey"], r["item"])] = r["value"]
    return rows


def save(rows: dict) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    order = sorted(rows, key=lambda k: (k[1], k[2], k[0]))
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for k in order:
            w.writerow([*k, rows[k]])


def main():
    args = [a for a in sys.argv[1:] if a != "--keep"]
    keep = "--keep" in sys.argv[1:]
    if len(args) != 2 or args[0] not in SURVEYS:
        sys.exit("사용: python tools/ism_add.py mfg|svc 파일(또는 -) [--keep]")
    survey, src = args
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")

    rows = load()
    added = changed = kept = 0
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        ym, item, val = m.groups()
        item = item.replace("®", "").replace("’", "'").strip()
        key = (ym, survey, item)
        if key not in rows:
            added += 1
        elif keep:
            kept += 1
            continue
        elif float(rows[key]) != float(val):
            changed += 1
            print(f"  [수정] {ym} {survey} {item}: {rows[key]} → {val}")
        rows[key] = val
    save(rows)
    months = sorted({k[0] for k in rows if k[1] == survey})
    print(f"[ism] {survey}: 추가 {added} · 수정 {changed}"
          f"{f' · 유지 {kept}' if keep else ''} · 수록 {months[0]}~{months[-1]}"
          f" ({len(months)}개월) → {CSV_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

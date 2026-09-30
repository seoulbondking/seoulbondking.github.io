"""investing.com 발표 이력(원본 CSV) → tools/ism_add.py 입력 줄.

data/us_ism_investing_{mfg,svc}.csv  (ref_month,release_date,actual,forecast)
  actual    처음 발표된 값 → 'Manufacturing PMI' / 'Services PMI'  (--keep 으로 빈 달만)
  forecast  컨센서스      → '… PMI Consensus'

사용:  python tools/ism_from_investing.py svc
"""
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = {"mfg": "Manufacturing PMI", "svc": "Services PMI"}
# 서비스 2008-01 이전 6행은 예상치가 없고 발표일이 전부 1일로 찍혀 있다.
# 기준월을 믿기 어려워 넣지 않는다.
MIN_MONTH = {"mfg": "2008-06", "svc": "2008-02"}


def main():
    sv = sys.argv[1] if len(sys.argv) > 1 else ""
    if sv not in NAME:
        sys.exit("사용: python tools/ism_from_investing.py mfg|svc")
    src = ROOT / "data" / f"us_ism_investing_{sv}.csv"
    rows = [r for r in csv.DictReader(src.open(encoding="utf-8"))
            if r["ref_month"] >= MIN_MONTH[sv]]
    act = "\n".join(f"{r['ref_month']},{NAME[sv]},{r['actual']}" for r in rows if r["actual"])
    con = "\n".join(f"{r['ref_month']},{NAME[sv]} Consensus,{r['forecast']}"
                    for r in rows if r["forecast"])
    add = [sys.executable, str(ROOT / "tools" / "ism_add.py"), sv, "-"]
    subprocess.run(add + ["--keep"], input=act, text=True, encoding="utf-8", check=True)
    subprocess.run(add, input=con, text=True, encoding="utf-8", check=True)


if __name__ == "__main__":
    main()

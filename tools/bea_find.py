"""BEA 표 찾기 — indicators.yaml 에 넣기 전에 표 이름과 줄 구성을 확인하는 용도.

샌드박스에서는 apps.bea.gov 가 막혀 있어 반드시 JM PC 에서 실행해야 한다.

사용법:
    python tools/bea_find.py --tables                 # NIPA 표 목록
    python tools/bea_find.py --tables --detail        # NIUnderlyingDetail 표 목록
    python tools/bea_find.py --tables PCE             # 이름에 'PCE' 가 든 표만
    python tools/bea_find.py T20804                   # 그 표의 줄 구성(계층 그대로)
    python tools/bea_find.py U20404 --detail          # 세부 데이터셋의 표
    python tools/bea_find.py T20804 --freq Q          # 분기로

인증키는 .env 의 BEA_API_KEY 를 쓴다.
"""
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
URL = "https://apps.bea.gov/api/data/"


def load_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BEA_API_KEY") and "=" in line:
                return line.partition("=")[2].strip().strip('"').strip("'")
    k = os.environ.get("BEA_API_KEY", "").strip()
    if not k:
        sys.exit("BEA_API_KEY 가 없습니다. .env 에 BEA_API_KEY=... 한 줄을 추가하세요.")
    return k


def get(key: str, **params):
    params.update({"UserID": key, "ResultFormat": "JSON"})
    r = requests.get(URL, params=params, timeout=90)
    r.raise_for_status()
    api = r.json().get("BEAAPI") or {}
    err = api.get("Error") or (api.get("Results") or {}).get("Error")
    if err:
        sys.exit(f"BEA 오류: {str(err)[:400]}")
    return api.get("Results") or {}


def list_tables(key: str, dataset: str, needle: str = ""):
    res = get(key, method="GetParameterValues", datasetname=dataset,
              ParameterName="TableName")
    rows = res.get("ParamValue") or []
    n = 0
    for r in rows:
        name = r.get("TableName") or r.get("Key") or ""
        desc = r.get("Description") or ""
        if needle and needle.lower() not in (name + " " + desc).lower():
            continue
        print(f"{name:<16} {desc}")
        n += 1
    print(f"\n{dataset}: {n}개 표" + (f" ('{needle}' 필터)" if needle else ""))


def show_table(key: str, dataset: str, table: str, freq: str):
    res = get(key, method="GetData", datasetname=dataset, TableName=table,
              Frequency=freq, Year="ALL")
    data = res.get("Data") or []
    if not data:
        sys.exit("데이터가 비었습니다. 표 이름 또는 주기를 확인하세요.")
    seen, periods = {}, set()
    for r in data:
        try:
            ln = int(r["LineNumber"])
        except (TypeError, ValueError, KeyError):
            continue
        periods.add(r.get("TimePeriod"))
        if ln not in seen:
            seen[ln] = r.get("LineDescription") or ""
    ps = sorted(p for p in periods if p)
    unit = (data[0].get("CL_UNIT") or "") + " " + (data[0].get("UNIT_MULT") or "")
    print(f"{dataset} / {table} · 주기 {freq} · 기간 {ps[0]} ~ {ps[-1]} · 단위 {unit.strip()}")
    print(f"줄 {len(seen)}개 (들여쓰기 = 계층)\n")
    for ln in sorted(seen):
        print(f"{ln:>4}  {seen[ln]}")
    print("\nindicators.yaml 예:")
    print("      tables:")
    print(f"        - dataset: {dataset}")
    print(f"          table: {table}")
    print(f"          lines: [{', '.join(str(x) for x in sorted(seen)[:6])}, ...]")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    detail = "--detail" in args
    dataset = "NIUnderlyingDetail" if detail else "NIPA"
    freq = "M"
    if "--freq" in args:
        i = args.index("--freq")
        freq = args[i + 1]
        del args[i:i + 2]
    args = [a for a in args if a != "--detail"]
    key = load_key()
    if args and args[0] == "--tables":
        list_tables(key, dataset, args[1] if len(args) > 1 else "")
    elif args:
        show_table(key, dataset, args[0], freq)
    else:
        sys.exit(__doc__)

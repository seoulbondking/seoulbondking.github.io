"""KOSIS 통계표의 항목(ITM)·분류(OBJ) 메타를 조회하는 도구.

statisticsParameterData.do 는 데이터 조회라 itmId/objL 조합이 안 맞으면
err 21 이 난다. 반면 메타 조회는 표 코드만 있으면 되므로 항상 통한다.
새 표를 붙이기 전에 이걸로 ITM_ID / 분류코드를 먼저 확인한다.

사용법:
    python tools/kosis_meta.py DT_118N_MON051          # orgId 기본 118
    python tools/kosis_meta.py DT_1J22002 101
    python tools/kosis_meta.py DT_118N_MON051 118 --raw
"""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
# 메타 조회 엔드포인트 후보 (KOSIS 가 개편되며 경로가 갈렸다)
ENDPOINTS = [
    "https://kosis.kr/openapi/statisticsData.do",
    "https://kosis.kr/openapi/Param/statisticsParameterData.do",
]


def load_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("KOSIS_API_KEY") and "=" in line:
                return line.partition("=")[2].strip().strip('"').strip("'")
    k = os.environ.get("KOSIS_API_KEY", "").strip()
    if not k:
        sys.exit("KOSIS_API_KEY 가 없습니다 (.env 확인)")
    return k


def get_meta(key, org, tbl, typ):
    """type=ITM(항목) / OBJ(분류) 메타. 되는 엔드포인트를 찾아 반환."""
    last = None
    for ep in ENDPOINTS:
        p = {"method": "getMeta", "apiKey": key, "format": "json", "jsonVD": "Y",
             "orgId": org, "tblId": tbl, "type": typ}
        try:
            r = requests.get(ep, params=p, timeout=60)
            d = r.json()
        except Exception as e:
            last = f"{ep}: {e}"
            continue
        if isinstance(d, list) and d:
            return d, ep
        last = f"{ep}: {d}"
    return None, last


def show(rows, typ):
    keys = set()
    for r in rows:
        keys |= set(r.keys())
    # 표시에 쓸 만한 열만 추린다 (KOSIS 응답 필드명이 표마다 조금씩 다르다)
    def pick(r, *names):
        for n in names:
            if r.get(n):
                return str(r[n])
        return ""
    if typ == "ITM":
        print(f"\n항목(ITM) {len(rows)}개")
        print(f"  {'ITM_ID':<24}{'항목명':<28}단위")
        for r in rows:
            print(f"  {pick(r,'ITM_ID'):<24}{pick(r,'ITM_NM','ITM_NM_ENG'):<28}"
                  f"{pick(r,'UNIT_NM','UNIT_NM_ENG')}")
    else:
        # 분류는 OBJ_ID(축) 별로 묶어서 보여준다
        by = {}
        for r in rows:
            by.setdefault((pick(r, 'OBJ_ID'), pick(r, 'OBJ_NM')), []).append(r)
        for (oid, onm), lst in by.items():
            print(f"\n분류축 {oid} — {onm}  ({len(lst)}개)")
            for r in lst[:30]:
                lv = pick(r, 'OBJ_ID_LVL', 'LVL')
                print(f"  {pick(r,'ITM_ID','OBJ_ITM_ID','C1'):<18}"
                      f"{'·' * (int(lv) - 1 if lv.isdigit() and int(lv) > 0 else 0)}"
                      f"{pick(r,'ITM_NM','OBJ_ITM_NM','C1_NM')}")
            if len(lst) > 30:
                print(f"  ... {len(lst) - 30}개 더")
    print(f"\n(사용 가능한 응답 필드: {', '.join(sorted(keys))})")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv
    if not args:
        sys.exit(__doc__)
    tbl = args[0]
    org = args[1] if len(args) > 1 else "118"
    key = load_key()

    for typ in ("ITM", "OBJ"):
        rows, info = get_meta(key, org, tbl, typ)
        if rows is None:
            print(f"[{typ}] 조회 실패 — {info}")
            continue
        print(f"[{typ}] 조회 성공 ({info})")
        if raw:
            print(json.dumps(rows[:3], ensure_ascii=False, indent=2))
        else:
            show(rows, typ)


if __name__ == "__main__":
    main()

"""KOSIS 통계표 목록을 훑어 이름으로 표를 찾는 도구.

kosis_meta.py 는 표 코드를 이미 알아야 쓸 수 있다. 이 도구는 반대로
기관(orgId) 아래 통계표 목록을 재귀로 내려가며 이름에 키워드가 든 표를 찾는다.

사용법:
    python tools/kosis_search.py 사업체노동력          # orgId 기본 118
    python tools/kosis_search.py 임금 118
    python tools/kosis_search.py 구인 118
    python tools/kosis_search.py 사업체노동력 118 --depth 4
    python tools/kosis_search.py --probe 118           # 목록 API 응답 구조만 확인

주의: 목록이 커서 몇십 초 걸릴 수 있다. KOSIS 는 해외 IP 를 막으므로 JM PC 에서 실행.
"""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LIST_URL = "https://kosis.kr/openapi/statisticsList.do"


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


def call(key, **extra):
    p = {"method": "getList", "apiKey": key, "format": "json", "jsonVD": "Y", **extra}
    try:
        r = requests.get(LIST_URL, params=p, timeout=60)
        d = r.json()
    except Exception as e:
        return None, str(e)
    if isinstance(d, dict):
        return None, str(d)
    return d, None


def find_root(key, org):
    """기관 아래 최상위 목록을 얻는 파라미터 조합을 찾는다 (KOSIS 문서가 조합마다 다르다)."""
    tries = [
        {"vwCd": "MT_OTITLE", "parentListId": f"{org}_"},
        {"vwCd": "MT_OTITLE", "parentListId": org},
        {"vwCd": "MT_OTITLE", "parentListId": "", "orgId": org},
        {"vwCd": "MT_ZTITLE", "parentListId": "A"},
    ]
    for t in tries:
        rows, err = call(key, **t)
        if rows:
            return rows, t
    return None, tries


def walk(key, vw, list_id, depth, seen, hits, word, path=""):
    if depth < 0 or list_id in seen:
        return
    seen.add(list_id)
    rows, err = call(key, vwCd=vw, parentListId=list_id)
    if not rows:
        return
    for r in rows:
        nm = (r.get("LIST_NM") or r.get("TBL_NM") or "").strip()
        here = f"{path} > {nm}" if path else nm
        tbl = r.get("TBL_ID")
        if tbl:
            if word in nm or word in here:
                hits.append((tbl, r.get("ORG_ID", ""), here))
        else:
            lid = r.get("LIST_ID")
            if lid:
                walk(key, vw, lid, depth - 1, seen, hits, word, here)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    depth = 3
    if "--depth" in sys.argv:
        depth = int(sys.argv[sys.argv.index("--depth") + 1])
    key = load_key()

    if "--probe" in sys.argv:
        org = args[0] if args else "118"
        rows, used = find_root(key, org)
        if not rows:
            print("목록 조회 실패. 시도한 조합:")
            for t in used:
                print("  ", t)
            return
        print(f"성공 조합: {used}\n응답 {len(rows)}건 · 첫 3건:")
        print(json.dumps(rows[:3], ensure_ascii=False, indent=2))
        return

    if not args:
        sys.exit(__doc__)
    word = args[0]
    org = args[1] if len(args) > 1 else "118"

    rows, used = find_root(key, org)
    if not rows:
        print("기관 목록을 열지 못했습니다. 시도한 조합:")
        for t in used:
            print("  ", t)
        sys.exit("KOSIS 사이트에서 표를 직접 찾아 OpenAPI URL 을 받아오세요.")
    vw = used.get("vwCd", "MT_OTITLE")
    print(f"'{word}' 검색 (orgId={org}, 조합={used}, 깊이={depth})\n")

    hits, seen = [], set()
    for r in rows:
        nm = (r.get("LIST_NM") or r.get("TBL_NM") or "").strip()
        if r.get("TBL_ID"):
            if word in nm:
                hits.append((r["TBL_ID"], r.get("ORG_ID", ""), nm))
        elif r.get("LIST_ID"):
            walk(key, vw, r["LIST_ID"], depth, seen, hits, word, nm)

    if not hits:
        print("일치하는 통계표가 없습니다. --depth 를 올리거나 키워드를 줄여보세요.")
        return
    print(f"{len(hits)}건\n")
    print(f"{'tblId':<22}{'orgId':<8}경로")
    for tbl, o, path in hits:
        print(f"{tbl:<22}{o:<8}{path}")


if __name__ == "__main__":
    main()

"""KOSIS OpenAPI URL 을 그대로 넣어 무슨 데이터가 나오는지 확인하는 도구.

KOSIS 사이트에서 'OpenAPI' 버튼으로 뽑은 URL 은 그 표에 맞는 파라미터 조합이
이미 들어 있다. 그 URL 을 그대로 쓰되 인증키만 .env 값으로 바꿔 호출하고,
항목(ITM)·분류(C1~C3)·시점을 정리해 보여준다.

사용법:
    python tools/kosis_probe.py "https://kosis.kr/openapi/...전체URL..."
    python tools/kosis_probe.py "URL" --prdSe M          # 월 단위로 바꿔 조회
    python tools/kosis_probe.py "URL" --prdSe M --n 6    # 최근 6개 시점
    python tools/kosis_probe.py "URL" --raw              # 원본 JSON 1건 출력

URL 은 반드시 큰따옴표로 감싸세요 (& 때문에 명령이 잘립니다).
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


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


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    url = args[0]
    prd_se = None
    n = 3
    raw = "--raw" in args
    if "--prdSe" in args:
        prd_se = args[args.index("--prdSe") + 1]
    if "--n" in args:
        n = int(args[args.index("--n") + 1])

    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    q["apiKey"] = load_key()
    q["format"] = "json"
    q["jsonVD"] = "Y"
    if prd_se:
        q["prdSe"] = prd_se
        # 기간 지정이 섞여 있으면 최근 N개 방식과 충돌한다 — 정리
        q.pop("startPrdDe", None)
        q.pop("endPrdDe", None)
    q["newEstPrdCnt"] = str(n)

    print(f"조회: orgId={q.get('orgId')} tblId={q.get('tblId')} "
          f"prdSe={q.get('prdSe')} 최근 {n}개 시점")
    r = requests.get(BASE, params=q, timeout=60)
    try:
        data = r.json()
    except json.JSONDecodeError:
        sys.exit(f"JSON 아님 (앞 300자): {r.text[:300]}")

    if isinstance(data, dict):
        sys.exit(f"KOSIS 오류: {data}\n"
                 "  err 21 = 파라미터 조합 오류. prdSe 를 Y↔M 으로 바꾸거나 "
                 "itmId/objL 을 KOSIS 사이트에서 다시 뽑아보세요.")
    if not data:
        sys.exit("빈 응답입니다.")

    if raw:
        print(json.dumps(data[0], ensure_ascii=False, indent=2))
        return

    print(f"\n표: {data[0].get('TBL_NM')}  ·  행 {len(data)}건\n")

    prds = sorted({r_.get("PRD_DE") for r_ in data})
    print(f"시점: {', '.join(prds)}\n")

    # 항목(ITM) 목록
    items = {}
    for r_ in data:
        iid = r_.get("ITM_ID", "")
        if iid not in items:
            items[iid] = (r_.get("ITM_NM", ""), r_.get("UNIT_NM", ""))
    print(f"항목 {len(items)}개")
    print(f"  {'ITM_ID':<22}{'항목명':<24}단위")
    for iid, (nm, unit) in items.items():
        print(f"  {iid:<22}{nm:<24}{unit}")

    # 분류축(C1~C3)
    for lvl in ("C1", "C2", "C3"):
        vals = {}
        for r_ in data:
            if r_.get(lvl):
                vals.setdefault(r_[lvl], r_.get(lvl + "_NM", ""))
        if vals:
            axis = data[0].get("C1_OBJ_NM") if lvl == "C1" else ""
            print(f"\n분류 {lvl} ({axis or '?'}) — {len(vals)}개")
            for k, v in list(vals.items())[:25]:
                print(f"  {k:<16}{v}")
            if len(vals) > 25:
                print(f"  ... {len(vals) - 25}개 더")

    # 최신 시점 샘플값
    last = prds[-1]
    print(f"\n{last} 값 (분류 첫 항목 기준)")
    c1_first = data[0].get("C1")
    for r_ in data:
        if r_.get("PRD_DE") == last and r_.get("C1") == c1_first:
            print(f"  {r_.get('ITM_NM',''):<24}{r_.get('DT','')} {r_.get('UNIT_NM','')}")


if __name__ == "__main__":
    main()

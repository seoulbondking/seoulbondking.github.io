"""ECOS 통계표 코드 찾기.

indicators.yaml 에 새 지표를 넣기 전에 stat_code / item_code 를 확인하는 용도.
샌드박스에서는 ECOS 가 막혀 있어 반드시 JM PC 에서 실행해야 한다.

사용법:
    python tools/ecos_find.py 교역조건          # 통계표 이름으로 검색
    python tools/ecos_find.py 수출물가
    python tools/ecos_find.py --items 402Y014   # 그 통계표의 항목(item_code) 목록
    python tools/ecos_find.py --items 402Y014 2  # 2단계(하위분류)까지

인증키는 .env 의 ECOS_API_KEY 를 쓴다.
"""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://ecos.bok.or.kr/api"


def load_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ECOS_API_KEY") and "=" in line:
                return line.partition("=")[2].strip().strip('"').strip("'")
    k = os.environ.get("ECOS_API_KEY", "").strip()
    if not k:
        sys.exit("ECOS_API_KEY 가 없습니다. .env 에 ECOS_API_KEY=... 한 줄을 추가하세요.")
    return k


def get(path: str):
    r = requests.get(f"{BASE}/{path}", timeout=30)
    r.raise_for_status()
    d = r.json()
    if "RESULT" in d:                      # 오류 응답
        sys.exit(f"ECOS 오류: {d['RESULT'].get('MESSAGE')}")
    return d


def search(key: str, word: str):
    """통계표 목록에서 이름에 word 가 들어간 표를 찾는다."""
    rows = []
    start = 1
    while True:                            # 목록이 길어 페이지로 끊어 받는다
        d = get(f"StatisticTableList/{key}/json/kr/{start}/{start + 999}")
        blk = d.get("StatisticTableList", {})
        rows += blk.get("row", [])
        total = int(blk.get("list_total_count", 0))
        start += 1000
        if start > total:
            break
    hit = [r for r in rows if word in (r.get("STAT_NAME") or "")]
    if not hit:
        print(f"'{word}' 를 이름에 포함한 통계표가 없습니다. (전체 {len(rows)}개 조회)")
        return
    print(f"'{word}' 검색 결과 {len(hit)}건\n")
    print(f"{'통계표코드':<12}{'주기':<8}{'수록기간':<22}통계표명")
    for r in hit:
        cyc = r.get("CYCLE") or "-"
        span = f"{r.get('START_TIME') or '?'}~{r.get('END_TIME') or '?'}"
        # STAT_NAME 은 '대분류 > 중분류 > 표이름' 형태라 마지막 조각만 보여준다
        nm = (r.get("STAT_NAME") or "").split(">")[-1].strip()
        print(f"{r.get('STAT_CODE',''):<12}{cyc:<8}{span:<22}{nm}")


def items(key: str, stat_code: str, level: int = 1):
    d = get(f"StatisticItemList/{key}/json/kr/1/1000/{stat_code}")
    rows = d.get("StatisticItemList", {}).get("row", [])
    rows = [r for r in rows if int(r.get("GRP_LVL") or 1) <= level]
    print(f"{stat_code} 항목 {len(rows)}건 (레벨 {level} 이하)\n")
    print(f"{'item_code':<14}{'레벨':<6}{'주기':<6}{'수록기간':<22}항목명")
    for r in rows:
        span = f"{r.get('START_TIME') or '?'}~{r.get('END_TIME') or '?'}"
        print(f"{r.get('ITEM_CODE',''):<14}{r.get('GRP_LVL',''):<6}"
              f"{r.get('CYCLE',''):<6}{span:<22}{r.get('ITEM_NAME','')}")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    key = load_key()
    if args[0] == "--items":
        if len(args) < 2:
            sys.exit("사용법: python tools/ecos_find.py --items <통계표코드> [레벨]")
        items(key, args[1], int(args[2]) if len(args) > 2 else 1)
    else:
        search(key, args[0])


if __name__ == "__main__":
    main()

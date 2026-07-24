"""SEIBro(예탁결제원) 기관RP 수집기 — Node/Playwright 스크래퍼 래퍼.

SEIBro RP 시장현황은 JS 렌더라 파이썬 단독 수집이 어렵다.
scripts/fetch_seibro_repo.js (Playwright) 를 subprocess로 실행해 JSON을 받는다.

사전 준비(로컬 1회):
    npm install playwright
    npx playwright install chromium

Playwright/Node 가 없으면 SeibroError 를 던지고, fetch.py 는 이 지표만
실패 처리하고 나머지는 계속 진행한다(자금흐름 REPO 섹터만 비게 됨).
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "fetch_seibro_repo.js"


class SeibroError(RuntimeError):
    pass


def fetch(indicator: dict) -> list[dict]:
    node = os.environ.get("NODE_BIN") or shutil.which("node")
    if not node:
        raise SeibroError("node 를 찾을 수 없습니다. Node.js + Playwright 설치 필요 "
                          "(npm install playwright && npx playwright install chromium)")
    if not SCRIPT.exists():
        raise SeibroError(f"스크립트 없음: {SCRIPT}")

    limit = int(indicator.get("seibro_limit", 30))
    try:
        proc = subprocess.run([node, str(SCRIPT), "--limit", str(limit)],
                              capture_output=True, text=True, timeout=150)
    except subprocess.TimeoutExpired:
        raise SeibroError("SEIBro 스크래핑 시간 초과(150s)")
    if proc.returncode != 0:
        raise SeibroError(f"스크래퍼 오류: {proc.stderr.strip() or proc.returncode}")

    try:
        rows = json.loads(proc.stdout.strip() or "[]")
    except json.JSONDecodeError:
        raise SeibroError(f"스크래퍼 JSON 파싱 실패: {proc.stdout[:200]}")

    data = [{"d": r["date"], "v": r["balance"]}
            for r in rows if r.get("date") and r.get("balance") is not None]
    if not data:
        raise SeibroError("SEIBro 응답이 비었습니다 (페이지 구조 변경 가능)")
    return [{"name": "기관RP", "data": sorted(data, key=lambda p: p["d"])}]

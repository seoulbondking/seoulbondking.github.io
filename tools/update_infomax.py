"""인포맥스 금리 엑셀 자동 갱신 (Windows 전용).

    python tools/update_infomax.py            # 점검만 (기본) — 아무것도 안 고침
    python tools/update_infomax.py --write    # stack 에 붙여넣고 저장
    python tools/update_infomax.py --write --fetch   # 저장 후 fetch.py kr_yield 까지

하는 일
    ① 열려 있는 엑셀에 붙거나 새로 띄워 워크북을 연다
    ② 재계산 → 인포맥스(IMDH)가 값을 채울 때까지 기다린다
    ③ 금리raw 의 정렬이 맞는지 검사한다   ← 여기서 대부분 걸린다
    ④ 금리stack 에 없는 신규 날짜만 맨 위에 삽입해 값으로 넣는다
    ⑤ 저장하고, 원하면 fetch.py 까지 돌린다

왜 ③ 이 필요한가
    raw 의 '일자' 열은 IMDH("IR","BONDKSDCAL08") = 영업일 달력이라 오늘을 바로 내놓는데,
    값 블록 IMDH("IR","BONDAVG01") 은 그날 민평이 고시되기 전까지 짧다. 둘 다 맨 윗행부터
    채워지므로 값이 k개 모자란 블록은 통째로 k칸 밀린 채 '그럴듯한 숫자'로 들어온다.
    밀린 블록은 가장 오래된 쪽에 빈칸이 남으므로 그걸로 잡는다.
    (2026-09-16 실제 사례: CD 만 09-16 이 나와 있고 국고·크레딧 전 블록이 1칸 밀림)

    stack 은 정렬이 맞는 순간 값으로 굳힌 스냅샷이다. 그래서 '붙여넣기'는 귀찮은 절차가
    아니라 정합성 안전장치다. 이 스크립트는 그 검사를 사람 대신 할 뿐, 없애지 않는다.

주의
    · 인포맥스 애드인이 설치·로그인돼 있어야 한다. 없으면 #N/A 가 되고 ③ 에서 멈춘다.
    · 쓰기 전에 워크북을 통째로 백업한다 (data/_backup/).
    · 정렬이 어긋나면 저장하지 않는다. 보통 19시 이후나 다음 날 아침이면 풀린다.
"""
import argparse
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fetchers.infomax import _find_file          # 엑셀 경로 탐색 규칙을 공유한다

RAW, STACK = "금리raw", "금리stack"
RAW_GROUP_ROW, STACK_GROUP_ROW = 3, 2            # 그룹명이 있는 행 (세부는 +1, 데이터는 +2)
CHECK_TAIL = 10                                   # 정렬 검사에 쓸 최근 영업일 수
POLL_SEC, POLL_MAX = 2.0, 60                      # 재계산 대기: 2초 간격, 최대 60초
EXCEL_EPOCH = date(1899, 12, 30)                  # 엑셀 serial 0 일


def d2s(serial):
    """엑셀 serial → 'YYYY-MM-DD'. Value2 는 날짜를 숫자로 주므로 시간대 문제가 없다."""
    if not isinstance(serial, (int, float)):
        return None
    return (EXCEL_EPOCH + timedelta(days=int(serial))).isoformat()


def block(ws, r1, c1, r2, c2):
    """시트 구간을 tuple of tuples 로. 한 번에 읽어야 COM 왕복이 안 늘어난다."""
    return ws.Range(ws.Cells(r1, c1), ws.Cells(r2, c2)).Value2


def read_sheet(ws, group_row, max_rows):
    """(헤더키 리스트, [(날짜, [값...]), ...]) 를 돌려준다. 시트는 최신순 정렬."""
    last_col = ws.Cells(group_row + 1, ws.Columns.Count).End(-4159).Column   # xlToLeft
    grp = block(ws, group_row, 1, group_row, last_col)[0]
    sub = block(ws, group_row + 1, 1, group_row + 1, last_col)[0]
    keys, cur = [], ""
    for g, s in zip(grp, sub):
        if g:
            cur = str(g).strip()
        keys.append(f"{cur}|{str(s).strip() if s else ''}")

    first = group_row + 2
    raw = block(ws, first, 1, first + max_rows - 1, last_col)
    rows = []
    for r in raw:
        d = d2s(r[0])
        if not d:
            break                                  # 날짜가 끊기면 데이터 끝
        rows.append((d, list(r)))
    return keys, rows, last_col


def shifted_columns(keys, rows):
    """값이 날짜보다 밀린 열을 찾는다. 최신행에 값이 있는데 과거행이 비면 밀린 것."""
    if len(rows) < 3:
        return {}
    win = rows[:CHECK_TAIL]                        # 최신순이므로 앞쪽이 최근
    bad = {}
    for c in range(1, len(keys)):
        if win[0][1][c] is None:
            continue                               # 최신조차 없으면 아직 미고시 — 밀림 아님
        gap = 0
        for d, vals in reversed(win):              # 오래된 쪽부터 연속 결측
            if vals[c] is not None:
                break
            gap += 1
        if gap:
            bad[keys[c]] = gap
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="stack 에 붙여넣고 저장")
    ap.add_argument("--fetch", action="store_true", help="저장 후 fetch.py kr_yield 실행")
    ap.add_argument("--wait", type=int, default=POLL_MAX, help="재계산 대기 상한(초)")
    args = ap.parse_args()

    try:
        import win32com.client as win32
    except ImportError:
        sys.exit("pywin32 가 필요합니다:  pip install pywin32")

    path = _find_file({})
    print(f"대상 파일: {path}")

    try:                                            # 이미 열려 있으면 그 인스턴스에 붙는다
        xl = win32.GetActiveObject("Excel.Application")
        print("  실행 중인 엑셀에 연결")
    except Exception:
        xl = win32.Dispatch("Excel.Application")
        print("  엑셀 새로 실행")
    xl.Visible = True                               # 애드인이 뜨는지 눈으로 볼 수 있게

    wb = next((w for w in xl.Workbooks if Path(w.FullName) == path), None)
    if wb is None:
        wb = xl.Workbooks.Open(str(path))
        print("  워크북 열기")
    else:
        print("  이미 열려 있는 워크북 사용")

    wsr, wss = wb.Worksheets(RAW), wb.Worksheets(STACK)

    # ── 재계산 후 정렬이 맞을 때까지 대기 ──────────────────────────
    xl.Calculate()
    waited, bad = 0, None
    while True:
        keys_r, rows_r, ncol_r = read_sheet(wsr, RAW_GROUP_ROW, CHECK_TAIL + 5)
        bad = shifted_columns(keys_r, rows_r)
        if not bad or waited >= args.wait:
            break
        print(f"  대기 {waited:>3}s — 밀린 열 {len(bad)}개")
        time.sleep(POLL_SEC)
        waited += POLL_SEC
        xl.Calculate()

    if not rows_r:
        sys.exit("금리raw 에서 데이터를 읽지 못했습니다.")
    print(f"  금리raw 최신 {rows_r[0][0]} · {len(rows_r)}일 · {ncol_r}열")

    if bad:
        print(f"\n⚠ 정렬이 어긋나 있습니다 ({len(bad)}개 열). 저장하지 않습니다.")
        for k, g in list(sorted(bad.items()))[:8]:
            print(f"    {k}: {g}칸 밀림")
        if len(bad) > 8:
            print(f"    ... 외 {len(bad) - 8}개")
        print("  그날 금리가 전부 고시된 뒤(보통 19시 이후 또는 다음 날 아침) 다시 실행하세요.")
        sys.exit(1)
    print("  정렬 OK")

    # ── 헤더가 같은지 확인 (열 구성이 바뀌면 위치 복사가 위험하다) ──
    keys_s, rows_s, ncol_s = read_sheet(wss, STACK_GROUP_ROW, 5)
    n = min(ncol_r, ncol_s)
    # A열(일자)은 건너뛴다 — raw 는 그 자리에 IMDH 수식이 걸쳐 있어 그룹명처럼 읽힌다
    mism = [i for i in range(1, n) if keys_r[i] != keys_s[i]]
    if mism:
        print(f"\n⚠ 두 시트의 열 구성이 다릅니다 ({len(mism)}개). 저장하지 않습니다.")
        for i in mism[:5]:
            print(f"    {i + 1}번째 열: raw={keys_r[i]!r}  stack={keys_s[i]!r}")
        sys.exit(1)

    newest_stack = rows_s[0][0] if rows_s else "0000-00-00"
    fresh = [(d, v) for d, v in rows_r if d > newest_stack]
    fresh.sort(key=lambda x: x[0])                  # 오래된 것부터 넣어야 stack 이 최신순 유지
    print(f"  금리stack 최신 {newest_stack} · 추가할 날짜 {len(fresh)}일"
          f"{' (' + ', '.join(d for d, _ in fresh) + ')' if fresh else ''}")

    if not fresh:
        print("\n새로 넣을 날짜가 없습니다.")
        return
    # 넣을 행에 빈칸이 있으면 그날은 아직 덜 나온 것 — 통째로 보류한다
    holes = [d for d, v in fresh if any(x is None for x in v[1:n])]
    if holes:
        print(f"\n⚠ {', '.join(holes)} 행에 빈 값이 있습니다. 저장하지 않습니다.")
        sys.exit(1)

    if not args.write:
        print("\n점검 모드입니다. 실제로 넣으려면 --write 를 붙이세요.")
        return

    # ── 백업 후 삽입 ────────────────────────────────────────────
    bk = path.parent / "_backup"
    bk.mkdir(exist_ok=True)
    dest = bk / f"{path.stem}_{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    wb.Save()                                       # 열린 변경분을 먼저 디스크에 반영
    shutil.copy2(path, dest)
    print(f"  백업 {dest.name}")

    first = STACK_GROUP_ROW + 2                     # stack 데이터 첫 행
    wss.Rows(f"{first}:{first + len(fresh) - 1}").Insert()
    wss.Range(wss.Cells(first, 1), wss.Cells(first + len(fresh) - 1, n)).Value2 = \
        tuple(tuple(v[:n]) for _, v in reversed(fresh))   # 최신이 위로 오게 뒤집어 넣는다
    wb.Save()
    print(f"  금리stack 에 {len(fresh)}일 추가 후 저장")

    if args.fetch:
        print()
        subprocess.run([sys.executable, str(ROOT / "fetch.py"), "kr_yield"], cwd=ROOT)


if __name__ == "__main__":
    main()

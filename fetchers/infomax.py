"""인포맥스 금리 엑셀 수집기 (로컬 파일).

data/인포맥스 금리.xlsx 의 stack 시트를 읽어 시리즈로 변환한다.
API가 아니라 로컬 파일이므로, 엑셀을 새로 내려받아 덮어쓰면 다음 fetch에 반영된다.

시트 구조 (2행=그룹명, 3행=세부명, 4행부터 데이터, A열=일자):
    금리stack       : 국고채권/통안증권/회사채… × 만기(3월이하·3년이하·10년이하…)
    기준금리stack   : 한국:기준금리 / 미국:기준금리 상단 / 한국:BEI 10년 …

indicators.yaml 예:
    params:
      sheet: 금리stack
      groups: ["국고채권", "통안증권"]     # 생략 시 전체
      flat: false                          # true면 그룹명만으로 시리즈명 구성
"""
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
# 파일명이 '인포맥스 금리*.xlsx' 이면 모두 후보로 보고 **가장 최근에 수정된 것**을 쓴다.
# (엑셀이 열려 있어 덮어쓰기가 안 될 때 새 이름으로 떨궈도 자동 인식되도록)
SEARCH_DIRS = [
    ROOT / "data",
    ROOT,
    Path.home() / "Desktop" / "Macro",
]
PATTERN = "인포맥스 금리*.xlsx"


class InfomaxError(RuntimeError):
    pass


def _find_file(indicator: dict) -> Path:
    custom = indicator.get("params", {}).get("path")
    if custom:
        # 상대경로는 저장소 기준으로 푼다 (fetch.py 를 어디서 실행하든 같게 동작하도록)
        cand = Path(custom)
        if not cand.is_absolute():
            cand = ROOT / custom
        if cand.exists():
            return cand
        raise InfomaxError(f"params.path 파일이 없습니다: {cand}")
    found = []
    for d in SEARCH_DIRS:
        if d.is_dir():
            found += [p for p in d.glob(PATTERN) if p.is_file() and not p.name.startswith("~$")]
    if not found:
        raise InfomaxError(
            "인포맥스 금리 엑셀을 찾을 수 없습니다. "
            f"다음 폴더 중 하나에 '{PATTERN}' 형태로 두세요: "
            + ", ".join(str(d) for d in SEARCH_DIRS))
    return max(found, key=lambda p: p.stat().st_mtime)


def _to_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    m = re.match(r"(\d{4})[-./]?(\d{1,2})[-./]?(\d{1,2})", s)
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# 만기 표기 정리: '3년이하(당일)' → '3년', '대표수익률' → ''
def _tenor(s: str) -> str:
    t = re.sub(r"\((당일|적용일)\)", "", str(s)).strip()
    t = re.sub(r"이하$", "", t).strip()
    return "" if t in ("대표수익률", "현재가") else t


def _fetch_flat(ws, p) -> list[dict]:
    """헤더가 한 줄인 시트 (IRS_stack·환율_raw·스프레드 등).

    params:
        header_row: 시리즈명이 있는 행 번호(1부터). 그 다음 행부터 데이터.
        only:  가져올 시리즈명 목록 (생략 시 전체)
        rename: {원본명: 표시명}
    """
    hr = int(p["header_row"])
    only = set(p.get("only") or [])
    rename = p.get("rename") or {}
    rows = list(ws.iter_rows(values_only=True))
    if hr > len(rows):
        raise InfomaxError(f"header_row {hr} 가 시트 범위를 벗어납니다 ({len(rows)}행)")
    hdr = rows[hr - 1]
    cols = []
    for j, v in enumerate(hdr):
        if j == 0 or v is None:
            continue
        nm = str(v).strip()
        if nm in ("일자", "Date"):
            continue
        if only and nm not in only:
            continue
        cols.append((j, rename.get(nm, nm)))
    if not cols:
        raise InfomaxError(f"헤더행 {hr} 에서 대상 열을 찾지 못했습니다 (only={sorted(only)})")
    data = {nm: {} for _j, nm in cols}
    for row in rows[hr:]:
        if not row or row[0] is None:
            continue
        d = _to_date(row[0])
        if not d:
            continue
        for j, nm in cols:
            if j < len(row):
                v = _num(row[j])
                if v is not None:
                    data[nm][d] = v
    return [{"name": n, "data": [{"d": d, "v": v} for d, v in sorted(vals.items())]}
            for n, vals in data.items() if vals]


def _read_stacked(ws, p, sheet: str, want: set, flat: bool):
    """2단 헤더(그룹/세부) 시트를 {시리즈명: {날짜: 값}} 로 읽는다.

    group_row : 그룹명이 있는 행(1부터). 세부명은 그 다음 행, 데이터는 그 다음 행부터.
        금리stack  1행 공백 · 2행 그룹 · 3행 세부 · 4행~ 데이터        → 2 (기본)
        금리raw    1행 열번호 · 2행 조회조건 · 3행 그룹 · 4행 세부 · 5행~ → 3
    """
    gr = int(p.get("group_row", 2))
    rows = ws.iter_rows(values_only=True)
    header = [next(rows, ()) for _ in range(gr + 1)]
    grp_row, sub_row = header[gr - 1], header[gr]

    cur = ""
    cols = []                              # (열idx, 시리즈명)
    for i, (g, s) in enumerate(zip(grp_row, sub_row)):
        if g:
            cur = str(g).strip()
        if i == 0 or not s:
            continue
        if want and cur not in want:
            continue
        name = cur if flat else (f"{cur} {_tenor(s)}".strip() if _tenor(s) else cur)
        cols.append((i, name))
    if not cols:
        raise InfomaxError(f"'{sheet}'에서 대상 열을 찾지 못했습니다 (groups={sorted(want)})")

    # recent_rows: 위에서 N행만 읽고 끊는다. stack 은 최신순(내림차순) 정렬이라
    # 위쪽이 최근이고, merge_always 로 과거는 JSON 아카이브가 들고 있으므로
    # 매번 4,100행 × 263열을 다시 파싱할 이유가 없다. (20MB 엑셀 읽기가 통째로 준다)
    limit = p.get("recent_rows")
    data = {name: {} for _, name in cols}
    dates = []
    for row in rows:
        if not row or row[0] is None:
            continue
        d = _to_date(row[0])
        if not d:
            continue
        dates.append(d)
        for i, name in cols:
            if i < len(row):
                v = _num(row[i])
                if v is not None:
                    data[name][d] = v
        if limit and len(dates) >= limit:
            # 정렬이 오름차순이면 위쪽은 '가장 오래된' 구간이라 최근치를 통째로
            # 놓친다. 조용히 틀리느니 멈춘다.
            if len(dates) >= 2 and dates[0] < dates[-1]:
                raise InfomaxError(
                    f"'{sheet}' 가 오름차순 정렬입니다. recent_rows 는 최신순(내림차순)"
                    " 시트에서만 쓸 수 있습니다 — 인포맥스 조회조건의 sort 를 D 로 두거나"
                    " recent_rows 를 빼세요.")
            break
    return data, cols, sorted(set(dates))


def _shifted_groups(data, dates, tail=10):
    """값이 날짜보다 몇 칸 밀린 블록을 찾는다.

    raw 는 '일자' 열과 값 블록이 서로 다른 IMDH 호출인데 둘 다 맨 윗행부터 채워진다.
    그날 고시가 그룹마다 다른 시각에 나오므로, 값이 k개 모자란 블록은 통째로 k칸
    밀린 채 '그럴듯한 숫자'로 들어온다. 밀린 블록은 가장 오래된 쪽에 빈칸이 남는다.

    최근 tail 일만 본다. 전 구간을 보면 '그 시리즈가 나중에 생긴 것'(예: 카드채는
    2009년엔 없다)까지 밀림으로 잡아 버린다. 그리고 창의 오래된 쪽에서 '연속으로'
    비어 있는 칸만 센다 — 중간 구멍은 휴장·호가 없음이지 밀림이 아니다.
    """
    win = dates[-tail:]
    if len(win) < 3:
        return {}
    out = {}
    for name, vals in data.items():
        if not vals or win[-1] not in vals:
            continue
        gap = 0
        for d in win:                       # 오래된 쪽부터 연속 결측 세기
            if d in vals:
                break
            gap += 1
        if gap:
            out[name] = gap
    return out


def fetch(indicator: dict) -> list[dict]:
    path = _find_file(indicator)
    p = dict(indicator.get("params", {}))
    sheet = p.get("sheet", "금리stack")
    want = set(p.get("groups") or [])
    flat = bool(p.get("flat"))
    # python fetch.py --full 이면 전 이력을 다시 읽는다 (아카이브를 새로 만들 때)
    if indicator.get("_full"):
        p.pop("recent_rows", None)

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        raise InfomaxError(f"시트 없음: {sheet} (있는 시트: {wb.sheetnames})")
    ws = wb[sheet]

    if p.get("header_row"):                     # 단일 헤더 레이아웃
        out = _fetch_flat(ws, p)
        if not out:
            raise InfomaxError(f"'{sheet}'에서 데이터를 읽지 못했습니다")
        print(f"  [infomax] {path.name} · {sheet} → 시리즈 {len(out)}개")
        return out

    data, cols, dates = _read_stacked(ws, p, sheet, want, flat)

    # ① 밀린 블록 탐지 — raw 시트 하나만 봐도 잡힌다 (대조 시트 불필요)
    if p.get("check_shift"):
        sh = _shifted_groups(data, dates)
        if sh:
            ex = sorted(sh.items())[:5]
            raise InfomaxError(
                f"'{sheet}' 에서 {len(sh)}개 열의 값이 날짜보다 밀려 있습니다. "
                f"조회 구간 {dates[0]}~{dates[-1]} 중 최신일 값은 있는데 과거일이 비어 "
                "있습니다 — 그 그룹의 당일 금리가 아직 고시되지 않았다는 뜻입니다.\n    "
                + "\n    ".join(f"{n}: {g}칸 밀림" for n, g in ex)
                + ("\n    ..." if len(sh) > 5 else "")
                + "\n  그날 금리가 전부 고시된 뒤(보통 19시 이후 또는 다음 날 아침) "
                  "엑셀을 갱신·저장하고 다시 실행하세요.")

    # raw 시트 정합성 검사 (verify_sheet 를 준 경우).
    #   raw 는 '일자' 열과 값 열이 서로 다른 IMDH 호출이고 둘 다 맨 윗행부터 채워진다.
    #   그날 고시가 열마다 다른 시각에 나오므로, 값이 하나 적은 블록은 통째로 한 칸
    #   밀린 채 그럴듯한 숫자로 들어온다 (2026-09-16 실제 사례: 국고 블록만 밀림).
    #   stack 은 정렬이 맞는 순간 값으로 굳힌 스냅샷이라 이걸 기준으로 대조한다.
    vs = p.get("verify_sheet")
    if vs:
        if vs not in wb.sheetnames:
            raise InfomaxError(f"대조 시트 없음: {vs}")
        vp = dict(p, group_row=p.get("verify_group_row", 2))
        vdata, _, _ = _read_stacked(wb[vs], vp, vs, want, flat)
        bad = []
        for name, vals in data.items():
            ref = vdata.get(name) or {}
            for d, v in vals.items():
                if d in ref and abs(v - ref[d]) > 1e-9:
                    bad.append(f"{name} {d}: {sheet}={v} vs {vs}={ref[d]}")
        if bad:
            raise InfomaxError(
                f"'{sheet}' 가 '{vs}' 와 겹치는 날짜에서 어긋납니다 ({len(bad)}건).\n    "
                + "\n    ".join(bad[:5]) + ("\n    ..." if len(bad) > 5 else "")
                + f"\n  {sheet} 가 밀렸거나 {vs} 붙여넣기가 어긋난 상태입니다. "
                  "둘 중 어느 쪽인지는 ECOS(kr_yield_daily) 국고채 3년과 대조하면 갈립니다.")

    out = [{"name": n, "data": [{"d": d, "v": v} for d, v in sorted(vals.items())]}
           for n, vals in data.items() if vals]
    if not out:
        raise InfomaxError(f"'{sheet}'에서 데이터를 읽지 못했습니다")

    # 인포맥스 애드인이 안 붙은 채로 저장된 파일이면 수식이 #N/A 로 남아 값이 비어 온다.
    # 그대로 통과시키면 merge_series 가 '신규 수집분'에 없는 시리즈를 아카이브에서 지워
    # 멀쩡한 과거 데이터까지 날아간다. 그래서 여기서 막는다.
    #   판정: 열의 절반 이상이 비어 있으면 갱신 실패로 본다.
    filled = len(out)
    if filled < len(cols) / 2:
        raise InfomaxError(
            f"'{sheet}' 대상 열 {len(cols)}개 중 {filled}개에만 값이 있습니다. "
            "엑셀을 열어 인포맥스 애드인이 값을 채운 뒤 저장했는지 확인하세요 "
            "(#N/A 상태로 저장하면 이렇게 됩니다).")

    last_d = max(d for vals in data.values() if vals for d in vals)
    on_last = sum(1 for vals in data.values() if last_d in vals)
    print(f"  [infomax] {path.name} · {sheet} → 시리즈 {filled}개 "
          f"· 최신 {last_d} ({on_last}/{filled}개 열)")
    return out

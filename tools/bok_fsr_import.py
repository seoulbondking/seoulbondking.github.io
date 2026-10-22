"""한은 금융안정보고서 '그림 원본데이터' 엑셀 → data/kr_fvi.csv

금융취약성지수(FVI)·금융불안지수(FSI)는 ECOS 에 없고 보고서(6월·12월)에만 실린다.
보고서 첨부의 '그림 원본데이터' 엑셀(시트 186개)에서 필요한 표를 찾아 CSV 로 옮긴다.
fetch.py kr_fvi 는 이 CSV 만 읽는다 (fetchers/bokfsr.py).

  받는 곳: 한국은행 보도자료 또는 KDI 경제정보센터
           (예: eiec.kdi.re.kr/policy/materialView.do?num=283152 — 2026년 6월판)
           첨부 중 .xlsx 가 그림 원본데이터다.

시트 이름(<개관 1>, <그림Ⅱ-1-26> …)은 호마다 바뀌므로 '머리글 글자'로 찾는다.
  · 머리글에 FSI·FVI 가 함께 있고 FVI 가 'x.x/4' 분기 → FVI(분기)·FSI(월)
  · 'FSI(좌축)·FVI(좌축)·국고채금리' → 2000년부터 분기 FSI·FVI·국고채 3년
  · '기준금리 인상 이후 FVI 변화' → 인상 후 8분기 부문별 반응 (h0~h8)

CSV: date,item,value   date = 분기말/월말 (YYYY-MM-DD) 또는 h0~h8
보고서 사이(3월·9월 '금융안정 상황')에 나온 값은 data/kr_fvi_manual.csv 에 손으로 적는다
(같은 형식). 이 도구는 manual 파일을 건드리지 않는다.

사용:  python tools/bok_fsr_import.py data/bok_fsr_202606_figdata.xlsx
"""
import calendar
import csv
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "kr_fvi.csv"


def qend(s):
    """'2026.1/4' → '2026-03-31'"""
    m = re.match(r"^\s*(\d{4})\.([1-4])/4\s*$", str(s))
    if not m:
        return None
    y, q = int(m.group(1)), int(m.group(2))
    mo = q * 3
    return f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"


def mend(v):
    """2008.1 / 2008.10 / '2008.10' → 월말. 엑셀 숫자라 10월이 2008.1 로 뭉개질 수 있어
    앞 행과의 연속성으로 바로잡는다 (호출부에서 처리)."""
    m = re.match(r"^\s*(\d{4})\.(\d{1,2})\s*$", str(v))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def rows_of(ws):
    return [list(r) for r in ws.iter_rows(values_only=True)]


def head_text(rows, n=6):
    return " ".join(str(v) for r in rows[:n] for v in r if v is not None)


def main():
    if len(sys.argv) != 2:
        sys.exit("사용: python tools/bok_fsr_import.py 그림원본데이터.xlsx")
    wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
    out = {}          # (date, item) → value
    found = []

    for ws in wb.worksheets:
        rows = rows_of(ws)
        h = head_text(rows)
        # ① FSI(월) + FVI(분기) — 개관 그림
        if "금융불안지수(FSI)" in h and "금융취약성지수(FVI)" in h:
            hdr = next(r for r in rows if "금융취약성지수(FVI)" in r)
            ci_fvi = hdr.index("금융취약성지수(FVI)")
            ci_fsi = hdr.index("금융불안지수(FSI)")
            prev = None
            n1 = n2 = 0
            for r in rows[rows.index(hdr) + 2:]:
                if len(r) > ci_fvi and qend(r[ci_fvi - 1]) and isinstance(r[ci_fvi], (int, float)):
                    out[(qend(r[ci_fvi - 1]), "FVI")] = r[ci_fvi]; n1 += 1
                ym = mend(r[ci_fsi - 1]) if len(r) > ci_fsi else None
                if ym and isinstance(r[ci_fsi], (int, float)):
                    y, mo = ym
                    # 2008.10 이 숫자 2008.1 로 들어오면 앞 달(9월) 다음이므로 10월로 본다
                    if prev and (y, mo) <= prev:
                        y, mo = (prev[0], prev[1] + 1) if prev[1] < 12 else (prev[0] + 1, 1)
                    prev = (y, mo)
                    d = f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
                    out[(d, "FSI (월)")] = r[ci_fsi]; n2 += 1
            found.append(f"{ws.title}: FVI {n1}분기 · FSI {n2}개월")
        # ② 2000년~ 분기 FSI·FVI·국고채 3년
        elif "FSI(좌축)" in h and "FVI(좌축)" in h and "국고채" in h:
            hdr = next(r for r in rows if "FVI(좌축)" in r)
            c = {k: hdr.index(k) for k in hdr if isinstance(k, str)}
            cg = next(i for k, i in c.items() if k.startswith("국고채"))
            n = 0
            for r in rows[rows.index(hdr) + 2:]:
                d = qend(r[0]) if r else None
                if not d:
                    continue
                for k, item in ((c["FSI(좌축)"], "FSI (분기)"), (c["FVI(좌축)"], "FVI (2000~)"),
                                (cg, "국고채 3년 (분기)")):
                    if isinstance(r[k], (int, float)):
                        out[(d, item)] = r[k]
                n += 1
            found.append(f"{ws.title}: 2000~ 분기 {n}개")
        # ③ 기준금리 인상 후 부문별 FVI 반응
        elif "기준금리 인상 이후 FVI 변화" in h:
            hdr = next(r for r in rows if r and r[0] == "항목")
            cols = [(i, v) for i, v in enumerate(hdr) if isinstance(v, str) and v != "항목"]
            n = 0
            for r in rows[rows.index(hdr) + 1:]:
                lab = str(r[0] or "")
                m = re.match(r"^(?:t=0|\+(\d)분기)$", lab)
                if not m:
                    continue
                hq = f"h{m.group(1) or 0}"
                for i, nm in cols:
                    if isinstance(r[i], (int, float)):
                        out[(hq, f"인상후 · {nm}")] = r[i]
                n += 1
            found.append(f"{ws.title}: 금리 인상 후 반응 {n}분기")

    if not found:
        sys.exit("FSI·FVI 표를 찾지 못했습니다 — 엑셀 구조를 확인하세요")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "item", "value"])
        for (d, item) in sorted(out, key=lambda k: (k[1], k[0])):
            w.writerow([d, item, out[(d, item)]])
    for s in found:
        print("  [fsr]", s)
    fvi = sorted(d for d, i in out if i == "FVI")
    print(f"[ok] {OUT.relative_to(ROOT)} · {len(out)}행 · FVI {fvi[0]} ~ {fvi[-1]}")


if __name__ == "__main__":
    main()

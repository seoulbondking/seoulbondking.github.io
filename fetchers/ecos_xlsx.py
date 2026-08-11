"""ECOS 다운로드 엑셀 수집기 (가로형).

ECOS 화면에서 받은 엑셀은 한 행이 하나의 계열이고 열이 기간인 '가로형'이다.
또 스타일 정의가 openpyxl 과 맞지 않아 로드가 실패하는 경우가 있어, xlsx(zip) 안의
XML 을 직접 읽는다.

    r1:  통계표 | 코드(계정항목) | 계정항목 | 단위 | 변환 | 2010/01 | 2010/02 | ...
    r2:  6.3. 경제심리지수 | E1000 | 경제심리지수(원계열) | | 원자료 | 114.5 | ...

API 로 못 받는(또는 기간이 짧은) 계열을 손으로 받아 채울 때 쓴다.

indicators.yaml 예:
    params:
      file: 경제심리지수.xlsx
      header_row: 1        # 기간이 적힌 행 (1부터)
      name_col: 3          # 시리즈명이 있는 열 (1부터)
      first_data_col: 6    # 첫 기간 열
"""
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class EcosXlsxError(RuntimeError):
    pass


def _find(name: str) -> Path:
    for d in (ROOT / "data", ROOT, Path.home() / "Desktop" / "Macro"):
        p = d / name
        if p.exists():
            return p
    raise EcosXlsxError(f"엑셀을 찾을 수 없습니다: {name} (data/ 폴더에 두세요)")


def _period_to_date(s: str) -> str | None:
    """'2010/01' · '2010.01' · '201001' · '2010/1Q' → 기간 말일 ISO."""
    t = str(s).strip()
    m = re.match(r"^(\d{4})[/.\-]?(\d{1,2})Q$", t, re.I)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        mo = q * 3
    else:
        m = re.match(r"^(\d{4})[/.\-]?(\d{1,2})$", t)
        if not m:
            m2 = re.match(r"^(\d{4})$", t)
            if m2:
                return f"{m2.group(1)}-12-31"
            return None
        y, mo = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        return None
    last = [31, 29 if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0 else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    return f"{y:04d}-{mo:02d}-{last:02d}"


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params", {}) or {}
    path = _find(p.get("file") or f"{indicator['id']}.xlsx")
    hr = int(p.get("header_row", 1))
    ncol = int(p.get("name_col", 3))
    first = int(p.get("first_data_col", 6))
    only = set(p.get("only") or [])

    z = zipfile.ZipFile(path)
    sst = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(f"{NS}si"):
            sst.append("".join(t.text or "" for t in si.iter(f"{NS}t")))

    def cv(c):
        t = c.get("t")
        if t == "inlineStr":
            return "".join(x.text or "" for x in c.iter(f"{NS}t"))
        v = c.find(f"{NS}v")
        if v is None or v.text is None:
            return None
        return sst[int(v.text)] if t == "s" else v.text

    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        raise EcosXlsxError("워크시트를 찾지 못했습니다")
    root = ET.fromstring(z.read(sheets[0]))
    rows = root.findall(f".//{NS}row")
    if len(rows) < hr + 1:
        raise EcosXlsxError(f"행이 부족합니다 ({len(rows)}행)")

    def cells(row):
        """열 위치(A1 참조)를 지켜 리스트로 편다 — 빈 칸이 있어도 어긋나지 않게."""
        out = []
        for c in row.findall(f"{NS}c"):
            ref = c.get("r") or ""
            m = re.match(r"([A-Z]+)", ref)
            if m:
                idx = 0
                for ch in m.group(1):
                    idx = idx * 26 + (ord(ch) - 64)
                while len(out) < idx - 1:
                    out.append(None)
            out.append(cv(c))
        return out

    head = cells(rows[hr - 1])
    dates = [(j, _period_to_date(v)) for j, v in enumerate(head) if j >= first - 1 and v]
    dates = [(j, d) for j, d in dates if d]
    if not dates:
        raise EcosXlsxError(f"헤더행 {hr} 에서 기간을 읽지 못했습니다: {head[first-1:first+3]}")

    series = []
    for row in rows[hr:]:
        c = cells(row)
        if len(c) < ncol:
            continue
        nm = (c[ncol - 1] or "").strip()
        if not nm or (only and nm not in only):
            continue
        data = []
        for j, d in dates:
            if j < len(c) and c[j] not in (None, ""):
                try:
                    data.append({"d": d, "v": float(str(c[j]).replace(",", ""))})
                except ValueError:
                    pass
        if data:
            series.append({"name": nm, "data": data})
    if not series:
        raise EcosXlsxError("데이터 행을 읽지 못했습니다")
    print(f"  [ecos_xlsx] {path.name} → 시리즈 {len(series)}개 "
          f"({series[0]['data'][0]['d']} ~ {series[0]['data'][-1]['d']})")
    return series

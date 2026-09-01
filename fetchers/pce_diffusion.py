"""PCE 물가 확산도 — 세부 품목 중 일정 기준을 넘는 품목의 비중.

BEA 세부표 두 개를 짝으로 받아 계산한다.
  U20404  Price Indexes for PCE by Type of Product (월)   — 품목별 물가지수
  U20405  Personal Consumption Expenditures by Type (월)  — 품목별 명목 지출액(가중치)

만드는 값:
  각 말단 품목의 k개월 연율 상승률이 임계치(기본 3%)를 넘는 품목의 비중.
  가중(지출 기준)과 단순(품목 수 기준) 둘 다 낸다 — 기사·리포트마다 기준이 달라서다.

    연율화:  (지수_t / 지수_{t-k})^(12/k) − 1
    k=12 면 지수가 1 이라 YoY 와 완전히 같다.

말단 품목 판별 (중요):
  BEA API 의 LineDescription 에는 들여쓰기가 없어 상위 집계와 말단이 구분되지 않는다.
  섞어 세면 같은 품목을 여러 번 세게 되므로, **명목 지출액의 가법성**으로 트리를 복원한다.
    "어떤 줄의 값 = 바로 뒤 연속한 줄들의 합" 이면 그 줄은 부모다.
  'Less:' 로 시작하는 줄은 차감 항목이라 부호를 뒤집어 더한다.
  복원 후 남는 잎만 센다. 2026-08 기준 200개 안팎이 나오면 정상이다.

indicators.yaml 사용 예:
  - id: us_pce_diffusion
    name: 미국 PCE 물가 확산도
    source: pce_diffusion
    unit: '%'
    freq: M
    start_year: 1998
    params:
      thresholds: [3, 2]        # 임계치(%) — 생략하면 [3]
      windows: [3, 6, 12]       # 연율 창(개월) — 생략하면 [3, 6, 12]
"""
import csv
import os
import re
from datetime import date
from pathlib import Path

from . import bea

# 클리블랜드 연준 절사평균 PCE 의 구성품목표 (200개).
#   https://www.clevelandfed.org/indicators-and-data/median-pce-inflation
#   품목 이름이 BEA U20404 의 LineDescription 과 같은 표기라 그대로 대조된다.
#   이 파일이 있으면 품목 집합을 여기서 정한다 — 가법성 추론보다 훨씬 정확하다.
COMPONENTS_CSV = Path(__file__).resolve().parent.parent / "data" / "cleveland_pce_components.csv"

PRICE_TABLE = "U20404"
NOMINAL_TABLE = "U20405"
TOL = 0.005          # 가법성 판정 허용 오차 (0.5%)


class DiffusionError(RuntimeError):
    pass


def _norm(s: str) -> str:
    """이름 대조용 정규화 — 대소문자·공백·괄호주석·구두점 차이를 흡수한다."""
    s = (s or "").lower()
    # 숫자가 든 괄호는 BEA 의 줄 참조다 — '(65)', '(parts of 31 and 32)'.
    # 반면 '(fresh)' 처럼 뜻이 담긴 괄호는 남겨야 다른 품목과 구분된다.
    s = re.sub(r"\([^)]*\d[^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def load_components(path=COMPONENTS_CSV):
    """구성품목 CSV → [(원문이름, 정규화이름)]. 없으면 None."""
    if not os.path.exists(path):
        return None
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            nm = (r.get("Component") or "").strip()
            if nm:
                out.append((nm, _norm(nm)))
    return out or None


def match_components(nominal, comps):
    """구성품목 목록 ↔ BEA 줄번호 대조 → (줄번호 목록, 못 찾은 이름 목록).

    같은 정규화 이름이 여러 줄에 걸리면(집계행과 말단이 동명인 경우) 뒤쪽 줄을 쓴다.
    BEA 표는 상위 집계가 먼저 오고 세부가 뒤에 오기 때문이다.
    """
    by_norm = {}
    for ln, e in nominal.items():
        by_norm.setdefault(_norm(e["name"]), []).append(ln)
    picked, missing = [], []
    for orig, key in comps:
        hit = by_norm.get(key)
        if hit:
            picked.append(max(hit))
        else:
            missing.append(orig)
    return sorted(set(picked)), missing


def _rows_by_line(rows):
    """BEA 행 → {줄번호: {"name":…, "by_date":{날짜: 값}}}"""
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            ln = int(r.get("LineNumber"))
        except (TypeError, ValueError):
            continue
        d = bea._to_date(r.get("TimePeriod"))
        v = bea._num(r.get("DataValue"))
        if d is None or v is None:
            continue
        e = out.setdefault(ln, {"name": (r.get("LineDescription") or "").strip(),
                                "by_date": {}})
        e["by_date"][d] = v
    return out


def find_leaves(nominal, ref_dates, span=80):
    """명목 지출액의 가법성으로 트리를 복원하고 말단 줄번호 목록을 돌려준다.

    부모의 값 = '직속 자식들'의 합이다. 자식은 저마다 subtree 를 거느리므로 단순히
    뒤 줄들을 이어 더하면 손자까지 섞여 안 맞는다. 재귀로 자식 하나를 파싱한 뒤
    그 subtree 끝으로 건너뛰며 더한다.

    ※ 한 달만 보면 우연히 합이 맞는 조합이 걸린다(예: 35 − 5 = 30).
      그래서 **여러 달에서 동시에 성립**할 때만 부모로 인정한다. 우연이 여러 달
      연속으로 맞을 확률은 사실상 0 이다.
    ※ 'Less:' 줄은 음수라, 합이 목표를 넘었다고 중간에 끊으면 뒤따르는 차감 항목을
      놓친다. 조기 중단 없이 span 줄까지 훑는다.

    수집과 분리해 두어 저장된 응답으로 테스트할 수 있게 한다.
    """
    if isinstance(ref_dates, str):
        ref_dates = [ref_dates]
    lines0 = sorted(nominal)
    vec, sign = {}, {}
    for ln in lines0:
        bd = nominal[ln]["by_date"]
        vs = [bd.get(d) for d in ref_dates]
        if any(v is None for v in vs):
            continue
        # 'Less:' 항목은 차감 — 부모 합을 맞추려면 음수로 다뤄야 한다
        neg = nominal[ln]["name"].lower().startswith("less:")
        vec[ln] = [(-abs(v) if neg else v) for v in vs]
        sign[ln] = -1 if neg else 1
    lines = [ln for ln in lines0 if ln in vec]
    if not lines:
        raise DiffusionError(f"{ref_dates} 에 명목 지출액이 없습니다.")

    nd = len(ref_dates)
    def close(acc, tgt):
        return all(abs(acc[k] - tgt[k]) <= TOL * max(abs(tgt[k]), 1e-9) for k in range(nd))

    memo = {}

    def parse(i, hi):
        """lines[i] 를 뿌리로 하는 subtree → (subtree 마지막 인덱스, 자식 인덱스들)"""
        if (i, hi) in memo:
            return memo[(i, hi)]
        tgt = vec[lines[i]]
        res = (i, [])
        if any(abs(t) > 1e-9 for t in tgt):
            acc, kids, j = [0.0] * nd, [], i + 1
            lim = min(hi, i + span)
            while j <= lim:
                end, _ = parse(j, hi)
                cv = vec[lines[j]]
                acc = [acc[k] + cv[k] for k in range(nd)]
                kids.append(j)
                if close(acc, tgt):
                    res = (end, kids)
                    break
                j = end + 1
        memo[(i, hi)] = res
        return res

    leaves, i, hi = [], 0, len(lines) - 1
    while i <= hi:
        end, kids = parse(i, hi)
        if kids:
            stack = list(kids)
            while stack:
                c = stack.pop(0)
                _e2, k2 = parse(c, hi)
                if k2:
                    stack = k2 + stack
                else:
                    leaves.append(lines[c])
            i = end + 1
        else:
            leaves.append(lines[i])
            i += 1
    return sorted(set(leaves)), vec, sign


def compute(price, nominal, thresholds, windows, start_year):
    """가격·명목 표 → 확산도 시리즈 목록."""
    # 가중치·트리 판정에 쓸 기준월 = 명목 표의 마지막 달
    all_dates = sorted({d for e in nominal.values() for d in e["by_date"]})
    if not all_dates:
        raise DiffusionError("명목 표에 날짜가 없습니다.")
    # 프로브(트리 판정에 쓰는 기준월) 는 **최근 10년 안에서** 고른다.
    #   find_leaves 는 프로브 전부에 값이 있는 줄만 본다. 옛 시점을 프로브에 넣으면
    #   그때 없던 품목(인터넷 접속·스트리밍·휴대전화 등)이 통째로 탈락해
    #   '오늘의 확산도'에서까지 빠져 버린다. 최근 구간으로 잡아야 현행 바구니가 산다.
    #   4개 시점이면 우연 매칭 방지 효과는 그대로다.
    recent = [d for d in all_dates if d >= f"{int(all_dates[-1][:4]) - 10}-01-01"] or all_dates
    probe = sorted({recent[-1], recent[len(recent) // 3], recent[len(recent) * 2 // 3],
                    recent[0]})
    # ① 클리블랜드 연준 구성품목표가 있으면 그걸 정답지로 쓴다 (권장).
    comps = load_components()
    if comps:
        leaves, missing = match_components(nominal, comps)
        leaves = [ln for ln in leaves if ln in price]
        print(f"  [pce_diffusion] 구성품목표 {len(comps)}개 중 {len(leaves)}개 대조 성공")
        if missing:
            print(f"  [pce_diffusion] 못 찾은 품목 {len(missing)}개: "
                  + ", ".join(missing[:8]) + (" …" if len(missing) > 8 else ""))
    else:
        # ② 없으면 명목 지출액의 가법성으로 트리를 복원해 말단을 추론한다.
        leaves, _, sign = find_leaves(nominal, probe)
        leaves = [ln for ln in leaves if ln in price and sign.get(ln, 1) > 0]
        print(f"  [pce_diffusion] 구성품목표 없음 → 가법성 추론 "
              f"(기준월 {', '.join(probe)})")
    if len(leaves) < 50:
        raise DiffusionError(
            f"품목이 {len(leaves)}개뿐입니다 — 대조/판정이 실패했을 수 있습니다.")

    pdates = sorted({d for ln in leaves for d in price[ln]["by_date"]})
    cut = f"{int(start_year)}-01-01"
    series = []
    for k in windows:
        rates = {}          # 날짜 → [(줄번호, 연율)]
        for i, d in enumerate(pdates):
            if i < k:
                continue
            d0 = pdates[i - k]
            got = []
            for ln in leaves:
                a = price[ln]["by_date"].get(d)
                b = price[ln]["by_date"].get(d0)
                if a is None or b is None or b <= 0:
                    continue
                got.append((ln, ((a / b) ** (12.0 / k) - 1) * 100))
            if got:
                rates[d] = got
        for th in thresholds:
            wpts, cpts = [], []
            for d in sorted(rates):
                if d < cut:
                    continue
                got = rates[d]
                wtot = wover = 0.0
                for ln, r in got:
                    w = nominal[ln]["by_date"].get(d)
                    if w is None or w <= 0:
                        continue
                    wtot += w
                    if r > th:
                        wover += w
                if wtot:
                    wpts.append({"d": d, "v": wover / wtot * 100})
                n = len(got)
                if n:
                    cpts.append({"d": d, "v": sum(1 for _, r in got if r > th) / n * 100})
            lbl = f"{th}% 초과 비중 · {k}개월" + ("" if k == 12 else " 연율")
            if wpts:
                series.append({"name": lbl + " (지출가중)", "data": wpts})
            if cpts:
                series.append({"name": lbl + " (품목수)", "data": cpts})
        # 그 달에 실제로 계산에 들어간 품목 수 — 분모가 시간에 따라 변하는 걸 드러낸다.
        #   옛 시점일수록 아직 없던 품목이 빠져 분모가 작아진다. 그래프를 믿으려면
        #   이 수치를 같이 봐야 한다.
        npts = [{"d": d, "v": float(len(rates[d]))} for d in sorted(rates) if d >= cut]
        if npts:
            series.append({"name": f"계산 품목 수 · {k}개월", "data": npts})
    return series


def fetch(indicator: dict) -> list[dict]:
    key = bea._api_key()
    p = indicator.get("params") or {}
    thresholds = p.get("thresholds") or [3]
    windows = p.get("windows") or [3, 6, 12]
    start_year = indicator.get("start_year") or (date.today().year - 30)

    price = _rows_by_line(bea.request_table(key, "NIUnderlyingDetail", PRICE_TABLE, "M"))
    nominal = _rows_by_line(bea.request_table(key, "NIUnderlyingDetail", NOMINAL_TABLE, "M"))
    print(f"  [pce_diffusion] {PRICE_TABLE} {len(price)}줄 · {NOMINAL_TABLE} {len(nominal)}줄")
    out = compute(price, nominal, thresholds, windows, start_year)
    cnt = next((x for x in out if x["name"].startswith("계산 품목 수")), None)
    if cnt:
        a, b = cnt["data"][0], cnt["data"][-1]
        print(f"  [pce_diffusion] 계산 품목 수: {a['d'][:7]} {int(a['v'])}개"
              f" → {b['d'][:7]} {int(b['v'])}개")
    print(f"  [pce_diffusion] 시리즈 {len(out)}개")
    return out

"""ISM 종합 PMI 가중치 — 미국 명목 GDP(BEA T10105)에서 제조업·서비스 몫.

두 가지 부호 기준:
  gdp (기본)  국내 '생산' 기준 — GDP 항등식대로 수출 +, 수입 −
      제조업 = 개인소비 재화 + 비주거 고정투자 + 재화 수출 − 재화 수입
      서비스 = 개인소비 서비스           + 서비스 수출 − 서비스 수입
  in  (--sign in)  미국으로 '들어오는' 수요 기준 — 수입 +, 수출 −
      제조업 = 개인소비 재화 + 비주거 고정투자 − 재화 수출 + 재화 수입
      서비스 = 개인소비 서비스           − 서비스 수출 + 서비스 수입
      (미국 안에서 쓰인 재화·서비스 = 국내 흡수. 수입품도 미국 기업이 사들이므로
       ISM 응답 기업의 구매 활동에 잡힌다는 해석)

종합 PMI = (제조업 PMI × w제조 + 서비스 PMI × w서비스) / (w제조 + w서비스)

결과: data/ism_composite_weights.csv (분기별, 두 기준 모두) + 화면 요약(선택 기준)
사용: python tools/ism_weights.py [--sign gdp|in] [--since 2008]
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "data" / "us_gdp.json"
OUT = ROOT / "data" / "ism_composite_weights.csv"

# BEA 줄 이름이 겹치는 것(Goods·Services)은 수집기가 [줄번호]를 붙여 둔다
K = {
    "pce_g": "명목수준 · Goods [3]",
    "pce_s": "명목수준 · Services [6]",
    "nonres": "명목수준 · Nonresidential",
    "ex_g": "명목수준 · Goods [17]",
    "ex_s": "명목수준 · Services [18]",
    "im_g": "명목수준 · Goods [20]",
    "im_s": "명목수준 · Services [21]",
    "gdp": "명목수준 · Gross domestic product",
}
SIGN = {"gdp": (+1, -1), "in": (-1, +1)}        # (수출 부호, 수입 부호)


def split(g, sign):
    ex, im = SIGN[sign]
    mfg = g["pce_g"] + g["nonres"] + ex * g["ex_g"] + im * g["im_g"]
    svc = g["pce_s"] + ex * g["ex_s"] + im * g["im_s"]
    return mfg, svc


def main():
    a = sys.argv
    sign = a[a.index("--sign") + 1] if "--sign" in a else "gdp"
    since = a[a.index("--since") + 1] if "--since" in a else "2008"
    if sign not in SIGN:
        sys.exit("--sign 은 gdp 또는 in")
    d = json.loads(SRC.read_text(encoding="utf-8"))
    S = {s["name"]: {p["d"]: p["v"] for p in s["data"]} for s in d["series"]}
    miss = [v for v in K.values() if v not in S]
    if miss:
        sys.exit(f"us_gdp 에 명목수준 계열이 없습니다: {miss}\n  → python fetch.py us_gdp --full")
    qs = sorted(q for q in S[K["gdp"]] if q[:4] >= since)

    rows = []
    for q in qs:
        g = {k: S[n].get(q) for k, n in K.items()}
        if any(v is None for v in g.values()):
            continue
        r = {"q": q, **g}
        for sg in SIGN:
            m, s = split(g, sg)
            r[sg] = (m, s, m / (m + s) * 100)
        rows.append(r)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["quarter",
                    "생산기준 제조업(십억$)", "생산기준 서비스(십억$)", "생산기준 제조업 비중(%)",
                    "유입기준 제조업(십억$)", "유입기준 서비스(십억$)", "유입기준 제조업 비중(%)",
                    "명목GDP(십억$)"])
        for r in rows:
            w.writerow([r["q"],
                        *[round(r["gdp"][i] / 1e3, 1) for i in (0, 1)], round(r["gdp"][2], 2),
                        *[round(r["in"][i] / 1e3, 1) for i in (0, 1)], round(r["in"][2], 2),
                        round(r["gdp"] if isinstance(r["gdp"], float) else S[K["gdp"]][r["q"]] / 1e3, 1)])

    ql = lambda q: f"{q[:4]}Q{(int(q[5:7]) - 1) // 3 + 1}"
    tb = lambda v: f"{v / 1e6:6.2f}"             # 백만달러 → 조달러
    nm = {"gdp": "생산 기준 (수출 +, 수입 −)", "in": "유입 기준 (수출 −, 수입 +)"}[sign]
    print(f"[{nm}] 단위: 조달러(명목, 연율) · BEA T10105 · {ql(rows[0]['q'])} ~ {ql(rows[-1]['q'])}\n")
    print("── 연도별 (4분기 평균) ──")
    print(f"{'연도':<6}{'제조업':>8}{'서비스':>8}{'제조:서비스':>14}")
    for y in sorted({r["q"][:4] for r in rows}):
        rs = [r for r in rows if r["q"][:4] == y]
        m = sum(r[sign][0] for r in rs) / len(rs); s = sum(r[sign][1] for r in rs) / len(rs)
        wm = sum(r[sign][2] for r in rs) / len(rs)
        print(f"{y + ('*' if len(rs) < 4 else ''):<6}{tb(m):>8}{tb(s):>8}{wm:9.1f} : {100 - wm:4.1f}")
    print("\n── 최근 8분기 ──")
    for r in rows[-8:]:
        m, s, wm = r[sign]
        print(f"{ql(r['q']):<8} 제조 {tb(m)}  서비스 {tb(s)}   {wm:5.1f} : {100 - wm:4.1f}"
              f"   (재화 수입 {tb(r['im_g'])} · 수출 {tb(r['ex_g'])})")
    print("\n── 기간 평균 (제조업 비중) ──")
    for a0, b0 in [("2008", "2026"), ("2010", "2019"), ("2020", "2026"), ("2023", "2026")]:
        rs = [r for r in rows if a0 <= r["q"][:4] <= b0]
        if rs:
            v = sum(r[sign][2] for r in rs) / len(rs)
            lo, hi = min(r[sign][2] for r in rs), max(r[sign][2] for r in rs)
            print(f"  {a0}~{b0}: {v:5.1f} : {100 - v:4.1f}   (범위 {lo:.1f} ~ {hi:.1f})")
    print(f"\n저장: {OUT.relative_to(ROOT)} ({len(rows)}분기, 두 기준 모두)")


if __name__ == "__main__":
    main()

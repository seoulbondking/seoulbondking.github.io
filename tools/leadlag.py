"""선행·후행 상관 검정 — 두 계열 중 어느 쪽이 앞서는지 시차별로 훑는다.

원계열끼리 상관을 재면 둘 다 추세를 갖고 있어 r 이 부풀려진다. 그래서
**12개월 차분**으로 추세를 걷어낸 뒤 시차를 옮겨가며 잰다.
코로나(2020~21)는 모든 관계를 왜곡하므로 제외분도 같이 낸다.

  k > 0  : X 가 Y 를 k개월 선행
  k < 0  : Y 가 X 를 선행 (원인·결과가 뒤집혀 있다는 신호)

**최대값이 시차 범위 끝(!)에 붙으면 그 시차를 믿지 말 것** — 봉우리가 창 밖에
있다는 뜻이다. 범위를 넓혀 다시 볼 것.

사용법:
    python tools/leadlag.py supercore           # 비주거 서비스 vs 임금 (미리 짜둔 묶음)
    python tools/leadlag.py supercore --curve   # 시차별 상관을 전부 (모양 확인)
    python tools/leadlag.py --list              # 쓸 수 있는 계열 이름 보기
    python tools/leadlag.py "임금추적기 전체" "비주거 핵심서비스"

상관은 인과가 아니다. 통제변수가 없고 표본이 사이클 두세 개뿐이라 시대별로
계수가 크게 흔들린다 — 하위 표본 결과를 같이 보고 판단할 것.
"""
import json
import math
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
# 양쪽을 똑같이 넓게 연다. 한쪽만 좁히면 최대값이 벽에 붙어서
# "그 시차가 최적"인지 "창이 짧은"지 구분할 수 없다 (실제로 한 번 당했다).
LAGS = range(-24, 25)
MIN_OBS = 36
COVID = ("2020-01", "2021-12")
# 12개월 차분을 월별로 겹쳐 쓰면 이웃 관측치가 11개월치를 공유한다. 관측치 수만큼
# 독립 정보가 있는 게 아니라서, 유효표본을 n/12 로 잡고 임계 r 을 구한다 (거친 근사).
OVERLAP = 12

# 지표 파일 → 그 안에서 쓸 시리즈 (표시명: 원본명). None 이면 전부.
SOURCES = {
    "us_pce": {
        "비주거 핵심서비스": "물가 · PCE services excluding energy and housing",
        "근원 PCE": "물가 · PCE excluding food and energy",
        "시장기반 근원": "물가 · Market-based PCE excluding food and energy",
        "주거": "물가 · Housing",
        "근원 서비스": "물가 · Services",
        "헤드라인 PCE": "물가 · Personal consumption expenditures (PCE)",
    },
    "us_lmci": {
        "임금추적기 전체": "임금추적기 전체",
        "임금추적기 이직자": "임금추적기 이직자",
        "임금추적기 잔류자": "임금추적기 잔류자",
    },
    "us_ahe": {"AHE 민간전체": "민간 전체"},
    # us_eci 는 분기라 이 월별 시차 틀에 안 맞는다. 넣지 않는다.
    "us_pce_sd": {
        "수요주도 물가": "근원 YoY · 수요",
        "공급주도 물가": "근원 YoY · 공급",
    },
}
# 지수 계열은 전년동월비로 바꿔서 봐야 임금(이미 증가율)과 단위가 맞는다.
AS_YOY = {"비주거 핵심서비스", "근원 PCE", "시장기반 근원", "주거",
          "근원 서비스", "헤드라인 PCE", "AHE 민간전체"}

PRESETS = {
    # 임금 → 비주거 핵심서비스(supercore). 근원 전체로는 임금→물가가 음(−0.29)이었다.
    # 서비스만 떼면 뒤집히는지, 그게 시장기반에서도 남는지가 관건.
    "supercore": (
        ["임금추적기 전체", "임금추적기 이직자", "임금추적기 잔류자", "AHE 민간전체"],
        ["비주거 핵심서비스", "시장기반 근원", "근원 PCE", "주거"],
    ),
    # 이전에 얻은 값(임금→수요물가 −0.29 / 수요물가→임금 +0.51@11개월)을 재현해
    # 스크립트가 같은 계산을 하는지 확인하는 용도.
    "check": (["임금추적기 전체"], ["수요주도 물가", "공급주도 물가", "근원 PCE"]),
}


def load() -> dict:
    """지표 파일들에서 필요한 시리즈만 뽑아 {표시명: {YYYY-MM: 값}} 으로."""
    out = {}
    for ind, want in SOURCES.items():
        p = DATA / f"{ind}.json"
        if not p.exists():
            print(f"  [건너뜀] {ind}.json 없음 — python fetch.py {ind}")
            continue
        raw = {s["name"]: s["data"] for s in json.loads(p.read_text(encoding="utf-8"))["series"]}
        for label, name in want.items():
            d = raw.get(name)
            if d is None:                       # 이름이 접두어와 함께 저장된 경우까지 본다
                d = next((v for k, v in raw.items() if k.endswith(name)), None)
            if d:
                out[label] = {x["d"][:7]: x["v"] for x in d}
            else:
                print(f"  [없음] {ind} / {name}")
    # 지수는 전년동월비로
    for label in list(out):
        if label in AS_YOY:
            m = out[label]
            ks = sorted(m)
            out[label] = {ks[i]: (m[ks[i]] / m[ks[i - 12]] - 1) * 100
                          for i in range(12, len(ks)) if m[ks[i - 12]]}
    return out


def d12(m: dict) -> dict:
    ks = sorted(m)
    return {ks[i]: m[ks[i]] - m[ks[i - 12]] for i in range(12, len(ks))}


def shift(m: dict, k: int) -> dict:
    ks = sorted(m)
    return {ks[i + k]: m[d] for i, d in enumerate(ks) if 0 <= i + k < len(ks)}


def corr(a: dict, b: dict):
    ks = sorted(set(a) & set(b))
    if len(ks) < MIN_OBS:
        return None, len(ks)
    xa = [a[k] for k in ks]
    xb = [b[k] for k in ks]
    ma, mb = sum(xa) / len(ks), sum(xb) / len(ks)
    num = sum((p - ma) * (q - mb) for p, q in zip(xa, xb))
    den = (sum((p - ma) ** 2 for p in xa) * sum((q - mb) ** 2 for q in xb)) ** .5
    return (num / den if den else None), len(ks)


def profile(x: dict, y: dict, ex_covid=False):
    A, B = d12(x), d12(y)
    if ex_covid:
        f = lambda m: {d: v for d, v in m.items() if not (COVID[0] <= d <= COVID[1])}
        A, B = f(A), f(B)
    out = []
    for k in LAGS:
        a, b = (shift(A, k), B) if k >= 0 else (A, shift(B, -k))
        r, n = corr(a, b)
        if r is not None:
            out.append((k, r, n))
    return out


def best(prof):
    return max(prof, key=lambda t: abs(t[1])) if prof else None


def crit_r(n: int) -> float:
    """유효표본 기준 5% 임계 상관 (Fisher z). 겹치는 차분이라 n 을 그대로 못 쓴다."""
    eff = max(n / OVERLAP, 5)
    return math.tanh(1.96 / math.sqrt(eff - 3))


def fmt(t) -> str:
    if t is None:
        return "-"
    k, r, n = t
    mark = "*" if abs(r) >= crit_r(n) else " "      # * = 유효표본 기준 유의
    edge = "!" if k in (LAGS[0], LAGS[-1]) else " "  # ! = 창 끝 (봉우리가 밖일 수 있음)
    return f"{k:>4}개월 r={r:+.2f}{mark}{edge}"


def show(S, xs, ys):
    print(f"\n{'':26}{'전체 표본':>22}{'코로나 제외':>22}")
    for y in ys:
        if y not in S:
            continue
        print(f"\n── → {y}")
        for x in xs:
            if x not in S:
                continue
            b1, b2 = best(profile(S[x], S[y])), best(profile(S[x], S[y], True))
            note = "   ← Y 가 앞선다" if b2 and b2[0] < 0 else ""
            print(f"   {x:<22}{fmt(b1):>22}{fmt(b2):>22}"
                  + (f"  n={b2[2]}" if b2 else "") + note)
    print("\n  * 유효표본(n/12) 기준 5% 유의   ! 시차 범위 끝 — 봉우리가 창 밖일 수 있음")


def flat(S, xs, ys, k=0):
    """같은 시차에서 크기만 비교한다. 최적 시차가 제각각이면 표를 가로로 못 읽는다."""
    print(f"\n[시차 {k:+d}개월 고정, 코로나 제외] — 계열 간 크기 비교용")
    print(f"   {'':22}" + "".join(f"{y[:12]:>14}" for y in ys))
    for x in xs:
        if x not in S:
            continue
        row = ""
        for y in ys:
            if y not in S:
                row += f"{'-':>14}"
                continue
            hit = [t for t in profile(S[x], S[y], True) if t[0] == k]
            if not hit:
                row += f"{'-':>14}"
            else:
                _, r, n = hit[0]
                row += f"{r:+.2f}{'*' if abs(r) >= crit_r(n) else ' '}".rjust(14)
        print(f"   {x:<22}{row}")


def curve(S, xs, ys):
    """시차별 상관을 전부 찍는다 — 최대값 하나만 보면 모양을 놓친다."""
    for y in ys:
        for x in xs:
            if x not in S or y not in S:
                continue
            prof = profile(S[x], S[y], ex_covid=True)
            if not prof:
                continue
            print(f"\n── {x} → {y}  (코로나 제외)")
            top = max(abs(r) for _, r, _ in prof)
            for k, r, _ in prof:
                bar = "#" * round(abs(r) / top * 30)
                mark = " *" if abs(r) == top else ""
                print(f"  {k:>3}개월 {r:+.2f} {'':>2}{bar}{mark}")


def main():
    args = sys.argv[1:]
    want_curve = "--curve" in args
    args = [a for a in args if a != "--curve"]
    S = load()
    if not args or args[0] == "--list":
        print("\n쓸 수 있는 계열:")
        for k, m in sorted(S.items()):
            ks = sorted(m)
            print(f"  {k:<24}{len(ks):>4}개월  {ks[0]} ~ {ks[-1]}")
        print("\n예: python tools/leadlag.py supercore")
        return
    if args[0] in PRESETS:
        xs, ys = PRESETS[args[0]]
    elif len(args) >= 2:
        xs, ys = [args[0]], args[1:]
    else:
        sys.exit("계열 두 개를 주거나 프리셋 이름을 주세요. --list 로 목록 확인.")
    print(f"12개월 차분 · 시차 {LAGS[0]}~{LAGS[-1]}개월 · k>0 이면 X 가 Y 를 k개월 선행")
    if want_curve:
        curve(S, xs, ys)
    else:
        show(S, xs, ys)
        flat(S, xs, ys, 0)
    print("\n※ 상관은 인과가 아닙니다. 통제변수가 없고 표본이 사이클 두세 개뿐입니다.")


if __name__ == "__main__":
    main()

"""ACM (Adrian-Crump-Moench 2013) 기간프리미엄 추정 — 한국 국고채.

아핀 기간구조모형을 최대우도 대신 선형회귀 5단계로 추정한다 (NY Fed가 이 방식으로
미국 기간프리미엄을 매일 공표한다).

    1) 수익률 곡선 주성분 K개 → 상태변수 X
    2) VAR(1):  X(t+1) = mu + Phi·X(t) + v(t+1)
    3) 초과수익률 rx = p(t+1, n-1) − p(t, n) − r(t)
    4) rx ~ [1, v(t+1), X(t)] 회귀 → 위험가격 lambda0, lambda1
    5) 아핀 점화식으로 곡선 복원. lambda=0으로 한 번 더 → 위험중립금리
       기간프리미엄 = 실제금리 − 위험중립금리

소표본(우리는 약 200개월) 에서는 VAR 지속성 Phi가 하향 편의된다. 그러면 위험중립금리가
너무 빨리 평균회귀해 기간프리미엄이 과대추정된다. 이를 Bauer-Rudebusch-Wu(2012)의
부트스트랩 편의보정(indirect inference)으로 교정한 결과도 함께 낸다.

입력은 API가 아니라 이미 수집된 docs/data/kr_yield.json 이다 (파생 지표).
    python fetch.py kr_acm
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"

# 국고채 만기(년). 30년은 유동성이 얇아 제외.
TENORS = {
    "국고채권 3월": 0.25, "국고채권 6월": 0.5, "국고채권 9월": 0.75, "국고채권 1년": 1.0,
    "국고채권 1.5년": 1.5, "국고채권 2년": 2.0, "국고채권 2.5년": 2.5, "국고채권 3년": 3.0,
    "국고채권 4년": 4.0, "국고채권 5년": 5.0, "국고채권 7년": 7.0, "국고채권 10년": 10.0,
}
NMAX = 120                        # 점화식 최장 만기(개월)
NPC = 5                           # 주성분 개수
RX_MATS = [6, 12, 24, 36, 48, 60, 84, 120]   # 초과수익률 대상 만기(개월)
SHOW = [(36, "3년"), (120, "10년")]


class AcmError(RuntimeError):
    pass


def _monthly_panel():
    """kr_yield.json → 월말 영업일의 만기별 파금리 행렬."""
    path = DATA / "kr_yield.json"
    if not path.exists():
        raise AcmError("docs/data/kr_yield.json 이 없습니다. 먼저 python fetch.py kr_yield 를 실행하세요.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    got = {s["name"]: {p["d"]: p["v"] for p in s["data"]}
           for s in payload["series"] if s["name"] in TENORS}
    missing = set(TENORS) - set(got)
    if missing:
        raise AcmError(f"kr_yield 에 없는 만기: {sorted(missing)}")
    common = sorted(set.intersection(*[set(v) for v in got.values()]))
    if len(common) < 60:
        raise AcmError(f"공통 관측일이 너무 적습니다 ({len(common)}일)")
    last_of_month = {}
    for d in common:                       # 정렬돼 있으므로 마지막이 월말 영업일
        last_of_month[d[:7]] = d
    months = sorted(last_of_month)
    days = [last_of_month[m] for m in months]
    names = sorted(TENORS, key=lambda k: TENORS[k])
    ten = np.array([TENORS[n] for n in names])
    par = np.array([[got[n][d] for n in names] for d in days]) / 100.0
    return months, days, ten, par


def _bootstrap_zero(par, ten):
    """파금리 → 무이표(zero) 커브. 반기 이표채가 액면에 발행된다고 보고 할인계수를 순차 산출.

    1년 미만은 순수할인채로 취급한다. 10년 기준 파금리를 그대로 쓰는 것과의 차이는
    1bp 미만이지만, 이론적으로 맞는 쪽을 쓴다.
    """
    grid = np.arange(0.5, 10.0001, 0.5)
    p = np.interp(grid, ten, par)
    disc = np.zeros(len(grid))
    for i in range(len(grid)):
        cpn = p[i] / 2.0
        disc[i] = (1.0 - cpn * disc[:i].sum()) / (1.0 + cpn)
    disc = np.clip(disc, 1e-9, None)
    z_long = -np.log(disc) / grid                       # 연속복리
    t_short = ten[ten < 1.0]
    z_short = np.log1p(np.interp(t_short, ten, par) * t_short) / t_short
    return np.concatenate([t_short, grid]), np.concatenate([z_short, z_long])


def _var_ols(X):
    """X(t+1) = mu + Phi·X(t) + v.  X는 (T+1, K) 시간이 행."""
    x0, x1 = X[:-1], X[1:]
    reg = np.column_stack([np.ones(len(x0)), x0])
    coef, *_ = np.linalg.lstsq(reg, x1, rcond=None)
    mu, phi = coef[0], coef[1:].T
    resid = x1 - reg @ coef
    return mu, phi, resid


def _max_eig(phi):
    return float(np.max(np.abs(np.linalg.eigvals(phi))))


def _brw_correct(X, phi_ols, resid, n_boot=500, n_iter=25, cap=0.999, seed=0):
    """Bauer-Rudebusch-Wu(2012) 부트스트랩 편의보정 (indirect inference).

    참 Phi를 Phi~ 로 놓고 표본을 재생성했을 때 OLS 추정치의 평균이 실제 관측된
    Phi_OLS 와 같아지도록 Phi~ 를 반복 조정한다. 정상성(최대고유값 < cap)을 강제한다.
    """
    rng = np.random.default_rng(seed)
    T, K = len(X) - 1, X.shape[1]
    phi_t = phi_ols.copy()
    x_start = X[0]
    for _ in range(n_iter):
        acc = np.zeros_like(phi_t)
        for _ in range(n_boot):
            idx = rng.integers(0, T, size=T)
            vb = resid[idx]
            sim = np.empty((T + 1, K))
            sim[0] = x_start
            for t in range(T):                       # mu는 0 근처(주성분은 평균 0)
                sim[t + 1] = phi_t @ sim[t] + vb[t]
            acc += _var_ols(sim)[1]
        phi_bar = acc / n_boot
        step = phi_ols - phi_bar                     # 편의만큼 되돌린다
        cand = phi_t + step
        if _max_eig(cand) >= cap:                    # 정상성 위반 → 스텝을 줄여 경계에 붙인다
            lo, hi = 0.0, 1.0
            for _ in range(40):
                mid = (lo + hi) / 2
                if _max_eig(phi_t + mid * step) < cap:
                    lo = mid
                else:
                    hi = mid
            cand = phi_t + lo * step
            phi_t = cand
            break
        if np.max(np.abs(cand - phi_t)) < 1e-6:
            phi_t = cand
            break
        phi_t = cand
    return phi_t


def _acm(X, mu, phi, resid, logp, r1, sig_hint=None):
    """ACM 4~5단계. 실제/위험중립 A, B 계수를 돌려준다."""
    x0 = X[:-1]
    T = len(x0)
    K = X.shape[1]
    rx = np.column_stack([logp[1:, n - 2] - logp[:-1, n - 1] - r1[:-1] for n in RX_MATS])
    W = np.column_stack([np.ones(T), resid, x0])
    G, *_ = np.linalg.lstsq(W, rx, rcond=None)
    a, beta, c = G[0], G[1:1 + K], G[1 + K:]
    err = rx - W @ G
    sig2 = float((err ** 2).sum() / (T * len(RX_MATS)))
    sigma = resid.T @ resid / T
    bstar = np.array([np.outer(beta[:, i], beta[:, i]).ravel() for i in range(len(RX_MATS))])
    bb = beta @ beta.T
    lam0 = np.linalg.solve(bb, beta @ (a + 0.5 * (bstar @ sigma.ravel() + sig2)))
    lam1 = np.linalg.solve(bb, beta @ c.T)
    # 단기금리식 r(t) = d0 + d1'X(t)
    dz, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), r1, rcond=None)
    d0, d1 = dz[0], dz[1:]

    def recur(l0, l1):
        A = np.zeros(NMAX + 1)
        B = np.zeros((NMAX + 1, K))
        for n in range(1, NMAX + 1):
            bp = B[n - 1]
            A[n] = A[n - 1] + bp @ (mu - l0) + 0.5 * (bp @ sigma @ bp + sig2) - d0
            B[n] = bp @ (phi - l1) - d1
        return A, B

    return recur(lam0, lam1), recur(np.zeros(K), np.zeros((K, K)))


def fetch(indicator: dict) -> list[dict]:
    p = indicator.get("params", {}) or {}
    n_boot = int(p.get("boot", 500))
    n_iter = int(p.get("iter", 25))
    cap = float(p.get("cap", 0.999))       # 정상성 상한. 0.999 이상에선 결과가 3bp 내로 안정.
    months, _days, ten, par = _monthly_panel()

    # 무이표 커브 (1~120개월)
    mgrid = np.arange(1, NMAX + 1) / 12.0
    zero = np.empty((len(months), NMAX))
    for i in range(len(months)):
        t, z = _bootstrap_zero(par[i], ten)
        zero[i] = np.interp(mgrid, t, z)

    logp = -(np.arange(1, NMAX + 1) * zero / 12.0)      # 로그가격 (월 단위)
    r1 = -logp[:, 0]                                     # 1개월 무위험수익률

    # 주성분
    pick = [2, 5, 11, 23, 35, 59, 83, 119]               # 3m,6m,1y,2y,3y,5y,7y,10y
    yc = zero[:, pick] - zero[:, pick].mean(0)
    _u, sv, vt = np.linalg.svd(yc, full_matrices=False)
    X = yc @ vt[:NPC].T
    share = (sv ** 2 / (sv ** 2).sum())[:NPC]

    mu, phi, resid = _var_ols(X)
    eig_ols = _max_eig(phi)
    phi_bc = _brw_correct(X, phi, resid, n_boot=n_boot, n_iter=n_iter, cap=cap)
    eig_bc = _max_eig(phi_bc)
    binds = eig_bc >= cap - 1e-6           # 보정이 정상성 경계에 붙었는지 (소표본에선 흔함)
    # 보정된 Phi로 잔차·mu 재계산 (평균 0 유지)
    x0, x1 = X[:-1], X[1:]
    resid_bc = x1 - x0 @ phi_bc.T
    mu_bc = x1.mean(0) - phi_bc @ x0.mean(0)
    resid_bc = resid_bc - resid_bc.mean(0)

    fits = {
        "ACM": _acm(X, mu, phi, resid, logp, r1),
        "편의보정": _acm(X, mu_bc, phi_bc, resid_bc, logp, r1),
    }

    series, diag = [], {}
    for n, lab in SHOW:
        act = zero[:, n - 1] * 100.0
        series.append({"name": f"국고 {lab} 실제",
                       "data": [{"d": months[i] + "-01", "v": round(float(act[i]), 4)}
                                for i in range(len(months))]})
        for tag, ((A, B), (Aq, Bq)) in fits.items():
            fit = -(A[n] + X @ B[n]) / n * 1200.0
            rn = -(Aq[n] + X @ Bq[n]) / n * 1200.0
            tp = fit - rn
            for nm, arr in ((f"국고 {lab} 위험중립 ({tag})", rn), (f"국고 {lab} 기간프리미엄 ({tag})", tp)):
                series.append({"name": nm,
                               "data": [{"d": months[i] + "-01", "v": round(float(arr[i]), 4)}
                                        for i in range(len(months))]})
            diag[f"{lab}_{tag}"] = {
                "rmse_bp": round(float(np.sqrt(((fit - act) ** 2).mean()) * 100), 2),
                "tp_last": round(float(tp[-1]), 3),
                "tp_mean": round(float(tp.mean()), 3),
                "rn_last": round(float(rn[-1]), 3),
            }

    indicator["_acm_meta"] = {
        "months": len(months), "start": months[0], "end": months[-1],
        "pc_share": [round(float(s), 5) for s in share],
        "eig_ols": round(eig_ols, 4), "eig_bc": round(eig_bc, 4),
        "halflife_ols": round(float(np.log(0.5) / np.log(eig_ols)), 1),
        "halflife_bc": round(float(np.log(0.5) / np.log(eig_bc)), 1),
        "boot": n_boot, "iter": n_iter, "cap": cap, "binds": bool(binds), "diag": diag,
    }
    print(f"  [acm] {months[0]}~{months[-1]} {len(months)}개월 · 주성분 {share[0]:.3f}/{share[1]:.3f}/{share[2]:.4f}")
    print(f"  [acm] Phi 최대고유값 OLS {eig_ols:.4f}(반감기 {np.log(0.5)/np.log(eig_ols):.1f}월)"
          f" → 편의보정 {eig_bc:.4f}({np.log(0.5)/np.log(eig_bc):.1f}월)")
    for k, v in diag.items():
        print(f"  [acm] {k:<14} 적합 {v['rmse_bp']:>5.2f}bp · 위험중립 {v['rn_last']:.3f}%"
              f" · TP 최근 {v['tp_last']:+.3f} 평균 {v['tp_mean']:+.3f}")
    return series

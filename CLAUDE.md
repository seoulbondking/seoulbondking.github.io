# Macrobox — 한국·미국 거시경제 대시보드

정적 웹 대시보드. 파이썬 수집기가 공공 API에서 데이터를 받아 `docs/data/*.json`(+ `.js`)로
저장하고, 단일 파일 `docs/index.html`이 그걸 그린다. GitHub Pages로 배포.

```
indicators.yaml          지표 정의 — 여기만 고치면 지표 추가/삭제
fetch.py                 수집 실행 (yaml → 수집기 → JSON)
fetchers/*.py            소스별 수집기
docs/index.html          대시보드 전체 (단일 파일, Chart.js)
docs/data/               수집 결과 (.json + file:// 용 .js)
tools/qa/smoke.js        스모크 테스트 (jsdom) — 작업 후 반드시 실행
tools/leadlag.py         두 계열의 선행·후행 상관 (12개월 차분, 시차 −6~+24)
tools/push.bat           코드 커밋·푸시 (daily_update.bat 은 데이터만 올린다)
```

## 작업 원칙

**숫자를 먼저 확인하고 말한다.** 기억이나 추론으로 단정하지 말 것. 특히 데이터가 이상해
보이면 **설명을 지어내지 말고 의심할 것.** (실제 사례: SEIBro 기관RP가 10배 작게 나왔을 때
"27조는 결제분만"이라는 그럴듯한 설명을 만들어냈다가 철회했다. 단위가 십억원이었다.)

**작업 후 스모크 테스트를 돌린다.** `node tools/qa/smoke.js` — 모든 화면·탭이 렌더되는지 본다.
새 탭을 만들면 smoke.js에도 추가할 것.

**샌드박스는 한국 API를 못 쓴다.** KOSIS·ECOS·부동산원·KRX·FREESIS·SEIBro와 BEA·BLS가
프록시에서 막힌다. 수집 검증은 JM PC에서 실행해 로그를 받는다. FRED·재무부·CFTC·MOF·FRBSF는
샌드박스에서도 열린다.

**분석은 임시 코드로 돌리지 말고 `tools/` 에 스크립트로 남긴다.** 샌드박스가 죽으면
임시 계산은 통째로 날아가지만 스크립트는 JM PC 에서 그대로 돌아가고 나중에 다시 쓸 수 있다.
샌드박스는 편의일 뿐 필수가 아니다 — 파이썬·node 는 JM PC 에 다 있다.

**API 키는 절대 채팅에 붙이지 않는다.** `.env`만 사용. 키가 로그에 섞여 들어오면 재발급을 권할 것.

## 데이터 소스

| source | 대상 | 비고 |
|---|---|---|
| `kosis` | 통계청 (CPI·고용·소매판매·가계부채) | 키 필요 |
| `ecos` / `ecos_xlsx` | 한국은행 (PPI·수입물가·ESI·국제수지) | 키 필요 |
| `reb` | 부동산원 (아파트 매매·전세) | 키 필요 |
| `krx` / `seibro` / `freesis` | 증시·RP·펀드 자금흐름 | 스크랩 |
| `bok` | 한은 일일 금융시장지표 엑셀 | |
| `infomax` | 인포맥스 금리 엑셀 (로컬 파일) | |
| `fred` | FRED (미국 대부분) | 키 필요. `frequency`/`aggregation_method` 로 일별→월별 집계 가능 |
| `bls` | BLS (CPI·고용) | 키 필요 |
| `bea` | BEA NIPA (PCE) | 키 필요. `tables:` 리스트 |
| `cftc` | CFTC COT (엔 투기포지션) | 키 불필요 |
| `mof` | 일본 재무성 JGB 금리 | 키 불필요. **FRED 에 일본 2년물이 없어서 필요** |
| `frbsf` | SF 연준 PCE 수요·공급 분해 | 엑셀 우선, CSV 폴백 |
| `acm` / `nowcast` / `pce_diffusion` | 파생 계산 | 다른 지표에서 계산 |

## 반드시 아는 함정

**단위.** 소스마다 단위가 다르고 화면마다 또 다르다. 과거에 세 번 틀렸다.
- FREESIS 예탁금만 백만원 (`DEPOSIT_TO_EOK = 100`)
- FRED `WTREGEN` 백만달러 (`params.scale`)
- SEIBro 십억원 (`BILLION_TO_EOK = 10`)

**Chart.js 그리기 순서.** 데이터셋은 order 역순으로 그려진다 — **order 가 작을수록 위**.
선이 막대 뒤에 숨으면 이걸 의심할 것. `LINE_POP` 플러그인으로 흰 후광을 줄 수 있다.

**계절조정 비가법성.** 통계청은 산업별·총괄 계절조정을 따로 한다. 산업 합계 ≠ 총괄이
정상이고 증감에서는 ±100천명까지 벌어진다. 표에 차이를 직접 보여줄 것.
**통계청 헤드라인 산업별 증감은 원계열 전년동월비**다.

**FRED 월간 관측치는 기간 첫날**(2026-08-01)로 온다. BLS·BEA 는 월말이라 그대로 섞으면
가로축이 갈라진다. `fred.py._period_end` 가 처리한다.

**증분 수집.** 기존 지표에 시리즈를 새로 추가하면 그 시리즈만 최근 2년치로 짧게 들어온다.
`--full` 로 다시 받아야 한다. 이 경우 fetch.py 가 `[warn]` 을 찍는다.

**이상치 제거는 `drop_before`.** yaml 에 날짜를 적으면 매 수집마다 그 이전을 걸러낸다
(과거 수집분이 다른 통계였을 때).

**추정할 때 표본 길이를 본다.** 한은 BOX 를 재현하며 유의수준 10% 를 그대로 썼더니
표본이 짧아(126개월) 민감 품목이 3배로 부풀었다. 5% 로 조이니 원문과 맞았다.
다중검정(시차 4개 동시 검정)을 고려할 것.

## 화면 구조

`docs/index.html` 하나에 전부 들어 있다. 뷰는 두 종류다.

- **일반 지표 뷰** — 카탈로그에서 고르면 차트/표로 그린다
- **전용 뷰** — 고유 화면 (소비자물가 종합, 미국 고용상황, 자금흐름, 엔캐리 등)

### 전용 뷰를 새로 만들 때 — 다섯 곳을 고쳐야 한다

이걸 세 번 놓쳤다. 하나라도 빠지면 조용히 어긋난다.

1. `const XXX = { id, name, ids }` + `enterXxx()` + `renderXxx()`
2. `refresh()` 안 `const isXxx = view === 'xxx'`
3. `refresh()` 분기 `else if (isXxx) renderXxx();`
4. **컨테이너 표시** — `retailWrap.style.display = (... || isXxx) ? '' : 'none'`
5. **툴바 숨김** — `viewButtons` / `modeButtons` 조건에 `isXxx` 추가, `scrollBtns` 에는 포함

그리고 좌측 메뉴 버튼 생성(`item.id === '...'` 분기)과, 그 화면에서만 쓰는 보조 지표는
`NAV_HIDE` 에 넣어 대그룹 메뉴에서 감춘다.

**스모크 테스트의 빈틈** — `innerHTML` 길이만 재기 때문에 "내용은 채워졌는데 화면에
안 보이는" 4번 실수를 못 잡는다. 컨테이너 `display` 검사를 넣으면 좋다.

### 자주 쓰는 것

- `dateLabel(d)` 날짜 라벨 · `inRange(d)` 기간 선택기 필터 · `periodDates` 가로축
- `setPeriodStart(ym)` 특정 탭 첫 진입 시 기간 이동 · `syncPeriodSel()`
- `anaShell/anaBar/anaRank` 월별 분석 패널 · `anaBasisBar` 전월비/전년동월비 토글
- `SEASON_HUES` / `seasonHue(i, n)` 연도별 색 (겹치는 선이 많을 때)
- `REC_SHADE` NBER 침체 음영 · `LINE_POP` 선 강조
- `sec-head` 섹션 머리 행 (구분선을 **위**에 둔다 — 아래에 두면 섹션과 하위가 갈라진다)

## 알림 배지

좌측 메뉴 '자금흐름' 옆에 5영업일 변동 배지를 띄운다. `FUND_ALERTS` 배열로 관리
(현재 기관REPO ±5조, MMF ±15조). 첫 화면부터 띄우려고 `fetch.py` 가 `docs/data/alerts.js`
(감시 지표의 최근 20영업일, 17KB)를 따로 뽑는다 — `kr_fund_flow.js` 는 1.2MB 라 통째로
받을 수 없다. 분기말 구간이면 '계절 요인' 표시만 하고 억누르지 않는다.

## 현재 상태 / 남은 일

**최근 추가** — 자금흐름 계절성·주간알림, 미국 PCE 시장기반·수요공급분해(Shapiro),
미국 고용 노동이동(CPS flows)·고용압력(LMCI·임금추적기)·JOLTS 서브탭, 한국 고용 분석 패널
(종합·산업별·연령별, MoM/YoY 토글), 엔캐리(미일 2년 금리차·VIX·CFTC 포지션).

**되돌린 것** — 미국 PCE 품목별(`us_pce_items`)·미국 재정(`us_fiscal`/`us_debt`/`us_debt_cost`)
삭제. `fetchers/treasury.py` 도 지웠다(미 재무부 Fiscal Data, 키 불필요 — 재정을 다시
할 거면 새로 만들어야 한다). 비주거 서비스 vs 임금 검정도 중단.

**하다 만 것**
- 자금흐름 '월중 일자별 패턴'. 기관자금이 월중 유입·월초 유출하는 게 MMF 잔액과
  단기금리에 찍히는지. 계절성 탭에서 가로축만 월중 영업일로 바꾸면 된다
- 한국 재정건전성 (국가채무·관리재정수지). ECOS/KOSIS 에 뭐가 있는지 먼저 확인 필요
- 물가확산지수가 공표치(83.7/58.5/56.0)를 재현하지 못한다 — 미해결

## 커밋

```
tools\push.bat "메시지"      # 코드 — pull → add -A → commit → push, lock 가드 포함
tools\daily_update.bat       # 데이터만 (스케줄러 09:00/16:00)
```

`.gitattributes` 로 줄바꿈을 LF 로 정규화한다 (`.bat` 만 CRLF). 안 그러면 CRLF 차이로
파일 전체가 바뀐 것처럼 뜬다.

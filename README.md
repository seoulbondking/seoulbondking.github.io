# KR Macro Dashboard

KOSIS 등 공공 API에서 매크로 지표를 수집해 정적 웹 대시보드로 보여주는 프로젝트.
GitHub Actions가 매일 자동으로 데이터를 갱신하고, GitHub Pages가 대시보드를 호스팅합니다.

## 구조

```
macro-dashboard/
├── indicators.yaml        # 지표 정의 (여기만 수정하면 지표 추가/삭제)
├── fetch.py               # 수집 실행: yaml 읽기 → API 호출 → JSON 저장
├── fetchers/
│   └── kosis.py           # KOSIS API 수집기 (ecos.py, fred.py 등 추가 예정)
├── docs/                  # GitHub Pages가 서빙하는 폴더
│   ├── index.html         # 대시보드 (Chart.js)
│   └── data/              # 수집된 JSON (index.json + 지표별 파일)
└── .github/workflows/update.yml   # 매일 KST 08:00 자동 수집
```

## 로컬 실행

```
cd macro-dashboard
pip install -r requirements.txt
```

이 폴더에 `.env` 파일을 만들고 API 키 입력 (git에는 올라가지 않음):

```
KOSIS_API_KEY=본인의키
ECOS_API_KEY=본인의키
```

수집 후 대시보드 열기:

```
python fetch.py                  # 전체 수집
python fetch.py kr_gdp_real      # 특정 지표만
```

`docs/index.html` 더블클릭으로 바로 열립니다. (데이터를 .js 파일로도 저장하기
때문에 file:// 환경에서도 동작. 단, Chart.js CDN 로드를 위해 인터넷 연결 필요)

## GitHub 배포 (자동 갱신)

1. GitHub에 새 리포지토리를 만들고 이 폴더를 push
2. 리포지토리 Settings → Secrets and variables → Actions → New repository secret
   - `KOSIS_API_KEY`, `ECOS_API_KEY` 두 개 등록
3. Settings → Pages → Source: `Deploy from a branch`, Branch: `main`, 폴더: `/docs`
4. Actions 탭 → "데이터 자동 갱신" → Run workflow 로 첫 수집 실행

이후 매일 KST 08:00에 자동 수집되고, 변경이 있으면 커밋되어 대시보드에 반영됩니다.

## 지표 추가하는 법

`indicators.yaml`에 항목 추가만 하면 됩니다:

```yaml
  - id: kr_retail
    name: 소매판매액지수
    source: kosis
    unit: 지수
    freq: M
    lookback_years: 10
    params:
      orgId: "101"
      tblId: "DT_1K41012"
      itmId: "T1 T2 T3 "
      objL1: "ALL"
```

KOSIS 파라미터는 kosis.kr 통계표 화면의 "OpenAPI" 버튼 → URL 생성기에서 확인.

## 확장 로드맵

- [x] ECOS(한국은행) 수집기: 가계신용, 국제수지, CSI, 기대인플레, 기준금리
- [ ] FRED / BLS / BEA 수집기 (US Macro)
- [ ] GDP 성장 기여도 등 파생지표 계산 (pandas, 전기 비중 방식)
- [ ] 보도자료 PDF 링크 수집

## 주의

- API 키는 절대 코드/yaml에 넣지 말 것 (.env 또는 GitHub Secret만 사용)
- 리포지토리를 public으로 두면 대시보드도 공개됨. 비공개가 필요하면
  private 리포지토리 + Cloudflare Pages 등 대안 검토

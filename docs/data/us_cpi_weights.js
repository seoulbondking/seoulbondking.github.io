// 미국 CPI 상대중요도(Relative Importance) — BLS 공표표에서 옮긴 값.
// 자동 수집이 아니다: BLS 는 RI 를 timeseries API 로 주지 않고 연 1회 표로만 공표한다.
// 갱신: https://www.bls.gov/cpi/tables/relative-importance/home.htm 의 최신 Table 1 을 보고 값을 바꾼다.
window.__US_CPI_RI__={
 "source": "BLS Table 1, Relative importance of components in the CPI-U, U.S. city average, December 2025 (2024 weights)",
 "url": "https://www.bls.gov/cpi/tables/relative-importance/2025.htm",
 "asof": "2025-12",
 "note": "RI 는 %이며 CPI=100. 매년 12월 기준으로 갱신된다(연 1회 가중치 개편). 갱신 시 asof 와 값을 함께 바꿀 것.",
 "ri": {
  "CPI": 100.0,
  "식료품": 13.698,
  "가정식(식료품)": 8.325,
  "외식": 5.373,
  "에너지": 6.383,
  "에너지 상품": 3.12,
  "에너지 서비스": 3.262,
  "전기": 2.489,
  "도시가스": 0.773,
  "Core CPI": 79.919,
  "상품 (식료품·에너지 제외)": 19.176,
  "의류": 2.368,
  "신차": 3.838,
  "중고차": 2.759,
  "서비스 (에너지서비스 제외)": 60.744,
  "주거": 35.625,
  "임차료": 7.84,
  "자가주거비 (OER)": 26.204,
  "의료 서비스": 6.935,
  "교통 서비스": 6.315
 }
};

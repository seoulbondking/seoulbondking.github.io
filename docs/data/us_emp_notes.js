// 미국 고용보고서 월별 해설 노트 (수작업 관리 — fetch.py 가 덮어쓰지 않습니다)
//
//   key   : 'YYYY-MM'  (지표 월. 발표는 보통 그 다음 달 첫째 금요일)
//   rel   : 발표일
//   first : 최초 발표된 비농업 증감(천명). 대시보드 값은 개정 후라 서로 다를 수 있습니다.
//   cons  : 당시 시장 컨센서스(천명)
//   head  : 한 줄 요약
//   pts   : 그달의 포인트
//   src   : [표시명, URL]
//
// 새 달을 추가할 때는 아래 형식 그대로 항목만 붙이면 됩니다.
window.__US_EMP_NOTES__ = {
  '2026-07': {
    rel: '2026-08-07', first: -23, cons: 83,
    head: '컨센서스를 크게 밑돈 감소 전환. 정부 감축과 임금 둔화가 동시에 확인됐습니다.',
    pts: [
      '정부 고용이 −53천으로 헤드라인을 끌어내렸고, 소매·레저접객이 부진했으며 헬스케어 증가폭도 평소보다 작았습니다.',
      '실업률은 4.1%로 내렸지만 취업자·구직자가 함께 줄어든 결과여서 개선으로 보기 어렵습니다.',
      '시간당임금 전년비가 3.2%로 2021년 5월 이후 가장 낮았습니다.',
      '5월 −66천, 6월 −37천 하향 개정. 두 달 합쳐 103천 명이 사라졌습니다.',
    ],
    src: [['CNBC — Jobs report July 2026', 'https://www.cnbc.com/2026/08/07/jobs-report-july-2026.html'],
          ['BLS Employment Situation (M07)', 'https://www.bls.gov/news.release/empsit.nr0.htm']],
  },
  '2026-06': {
    rel: '2026-07-02', first: 57, cons: 110,
    head: '고용 증가폭이 급격히 둔화. 실업률 하락은 노동시장 이탈이 만든 착시였습니다.',
    pts: [
      '경제활동참가율이 0.3%p 급락했습니다. 구직을 포기한 사람이 늘면 실업률은 자동으로 내려갑니다.',
      '27주 이상 장기실업이 190만 명으로 전년 대비 28.6만 명 늘었습니다.',
      '4·5월 합계 74천 명 하향 개정.',
      '물가는 상반기에 되레 올라, 고용 둔화에도 연준이 완화로 돌아서기 어려운 조합이었습니다.',
    ],
    src: [['CNBC — Jobs report June 2026', 'https://www.cnbc.com/2026/07/02/jobs-report-june-2026-.html'],
          ['Axios — Weaker-than-expected hiring', 'https://www.axios.com/2026/07/02/jobs-june-trump-federal-reserve']],
  },
  '2026-05': {
    rel: '2026-06-05', first: 172, cons: 88,
    head: '발표 당시엔 모든 전망을 상회한 서프라이즈였지만, 이후 개정으로 뒤집혔습니다.',
    pts: [
      '최초 +172천으로 컨센서스(+88천)를 크게 웃돌아 "2년 만의 최강 3개월"이라는 평가가 나왔습니다.',
      '3월 +185→+214천, 4월 +115→+179천으로 상향 개정되며 강세론에 힘이 실렸습니다.',
      '실업률은 4.3% 유지.',
      '두 달 뒤 7월 보고서에서 5월이 −66천 하향 개정되며 당시 해석이 상당 부분 무효화됐습니다.',
    ],
    src: [['Bloomberg — US adds 172,000 jobs in May', 'https://www.bloomberg.com/news/articles/2026-06-05/us-adds-172-000-jobs-in-may-beating-all-economists-estimates'],
          ['CNBC — Jobs report May 2026', 'https://www.cnbc.com/2026/06/05/jobs-report-may-2026.html']],
  },
  '2026-04': {
    rel: '2026-05-08', first: 115, cons: 62,
    head: '헤드라인은 예상을 웃돌았지만 참가율 하락이 이어졌습니다.',
    pts: [
      '경제활동참가율 61.8% — 1년 전 62.6%에서 계속 내려왔습니다.',
      '실업률 4.3% 유지.',
      '고용 증가와 노동력 감소가 함께 나타나, 실업률이 안정돼 보이는 구조가 이때부터 굳어졌습니다.',
    ],
    src: [['CNBC — Jobs report April 2026', 'https://www.cnbc.com/2026/05/08/jobs-report-april-2026.html'],
          ['BLS Employment Situation (M04)', 'https://www.bls.gov/news.release/archives/empsit_05082026.htm']],
  },
};

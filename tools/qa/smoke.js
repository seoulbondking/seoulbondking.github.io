/* 대시보드 스모크 테스트 — 모든 화면·탭이 렌더되는지 확인한다.
 *   node tools/qa/smoke.js
 * jsdom 필요:  npm i jsdom   (프로젝트 루트나 전역 어디든)
 * Chart.js 는 스텁으로 대체하고, docs/data/*.js 를 미리 주입해 fetch 없이 돌린다.
 */
const fs = require('fs'), path = require('path');
let JSDOM;
for (const p of ['jsdom', path.resolve(__dirname, '../../node_modules/jsdom')]) {
  try { ({ JSDOM } = require(p)); break; } catch (e) { /* 다음 후보 */ }
}
if (!JSDOM) { console.error('jsdom 이 필요합니다:  npm i jsdom'); process.exit(2); }

const ROOT = path.resolve(__dirname, '../../docs');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true });
const w = dom.window;
w.Chart = function () { this.destroy = () => {}; };
w.Chart.register = () => {};
w.alert = m => console.log('  ALERT:', m);

const dd = path.join(ROOT, 'data');
let pre = '';
for (const f of fs.readdirSync(dd)) if (f.endsWith('.js')) pre += fs.readFileSync(path.join(dd, f), 'utf8') + '\n';
const main = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])
  .reduce((a, b) => a.length > b.length ? a : b);
w.eval(pre);
w.eval(main.replace(/function loadScript\([^)]*\)\s*\{/,
  'function loadScript(){return Promise.resolve();} function __unused(){')
  + '\nfunction __ev(c){ return eval(c); }\n');
const ev = c => w.__ev(c);

let fail = 0;
const chk = (name, elId) => {
  const el = w.document.getElementById(elId);
  const n = el ? el.innerHTML.length : 0;
  const ok = n > 2000;
  if (!ok) fail++;
  console.log('  ' + name.padEnd(26) + String(n).padStart(7) + (ok ? '  OK' : '  ⚠ 비었거나 짧음'));
};

(async () => {
  await ev('enterCard()');
  for (const t of ['month', 'week', 'real']) { ev(`cardTab='${t}'; refresh();`); chk('카드사용액 > ' + t, 'retailWrap'); }
  await ev('enterRetail()');
  for (const t of ['goods', 'type']) { ev(`retailTab='${t}'; refresh();`); chk('소매판매 > ' + t, 'retailWrap'); }
  await ev('enterCpiCombo()');
  for (const t of ['main', 'items', 'seas', 'contrib']) { ev(`cpiTab='${t}'; renderCpiCombo();`); chk('CPI > ' + t, 'multiWrap'); }
  await ev('enterKrEmp()');
  for (const t of ['main', 'industry', 'sub', 'age', 'detail', 'wage', 'vu']) { ev(`krEmpTab='${t}'; refresh();`); chk('고용 > ' + t, 'retailWrap'); }
  if (w.__MACRO__ && w.__MACRO__.us_cpi) {
    await ev('enterUsCpi()');
    for (const t of ['chg', 'idx']) { ev(`usCpiTab='${t}'; refresh();`); chk('미국 소비자물가 > ' + t, 'retailWrap'); }
  } else {
    console.log('  미국 소비자물가              (데이터 없음 — python fetch.py us_cpi us_cpi_nsa)');
  }
  if (w.__MACRO__ && w.__MACRO__.us_ppi) {
    await ev('enterUsPpi()');
    for (const t of ['chg', 'idx', 'ctb']) { ev(`usPpiTab='${t}'; refresh();`); chk('미국 생산자물가 > ' + t, 'retailWrap'); }
  } else { console.log('  미국 생산자물가              (데이터 없음 — python fetch.py us_ppi us_ppi_nsa)'); }
  if (w.__MACRO__ && w.__MACRO__.us_pce) {
    await ev('enterUsPce()');
    for (const t of ['price', 'real', 'income']) { ev(`usPceTab='${t}'; refresh();`); chk('미국 PCE > ' + t, 'retailWrap'); }
  } else { console.log('  미국 PCE                    (데이터 없음 — python fetch.py us_pce)'); }
  await ev('enterFundFlow()');
  for (const m of ['change', 'balance']) { ev(`fundMode='${m}'; renderFundFlow();`); chk('자금흐름 > ' + m, 'retailWrap'); }
  for (const u of ['pct', 'eok']) {
    ev(`fundMode='season'; fundSeasonUnit='${u}'; renderFundFlow();`);
    chk('자금흐름 > season/' + u, 'retailWrap');
  }
  ev(`fundMode='change';`);
  await ev('enterHdebt()');
  for (const t of ['month', 'quarter']) {
    ev(`hdTab='${t}'; hdSetPeriods(); refresh();`);
    for (const m of ['lvl', 'chg']) { ev(`hdMode='${m}'; renderHdebt();`); chk(`가계부채 > ${t}/${m}`, 'retailWrap'); }
  }
  if (w.__MACRO__ && w.__MACRO__.us_fed) {
    await ev('enterFed()'); chk('연준 지급준비금', 'retailWrap');
  } else {
    console.log('  연준 지급준비금              (데이터 없음 — python fetch.py us_fed)');
  }
  await ev('enterTaylor()'); chk('테일러 준칙', 'retailWrap');
  await ev('enterUsEmp()').catch(() => {}); chk('미국 고용', 'retailWrap');

  // nav 에 나와야 할 지표가 빠지지 않았는지
  const src = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
  const own = (src.match(/own: \[(.*?)\]/s) || [, ''])[1].match(/'([^']+)'/g) || [];
  const must = ['kr_gdp_real', 'kr_cpi', 'kr_cpi_core', 'kr_retail'];
  const swallowed = must.filter(id => own.includes(`'${id}'`));
  console.log('\n  nav 흡수 점검 —', swallowed.length ? '⚠ 메뉴에서 사라짐: ' + swallowed.join(', ')
    : '공용 지표가 카드 메뉴에 흡수되지 않음 OK');
  if (swallowed.length) fail++;

  // nav 버튼이 실제로 만들어졌는지 (IIFE 가 eval 시점에 이미 돌았다)
  await new Promise(r => setTimeout(r, 200));
  const btns = [...w.document.querySelectorAll('nav button')].map(b => b.textContent.trim());
  console.log('\n  nav 버튼 ' + btns.length + '개');
  const wantBtn = ['소매판매', '카드사용액', '국내총생산', '주간 아파트 매매&전세 동향'];
  wantBtn.forEach(t => {
    const ok = btns.some(b => b === t || b.indexOf(t) === 0);
    if (!ok) fail++;
    console.log('    ' + (ok ? '있음  ' : '⚠ 없음 ') + t);
  });

  // GDP: 4개 조합 전환 + 순수출 파생
  for (const key of ['real|q', 'nominal|q', 'real|a', 'nominal|a']) {
    const id = ev(`GDP.id['${key}']`);
    await ev(`select('${id}')`);
    const has = ev(`current.series.some(x => x.name === '순수출 (수출 − 수입)')`);
    const sw = w.document.getElementById('gdpSwitch').style.display;
    const ok = has && sw === 'flex';
    if (!ok) fail++;
    console.log('  GDP ' + key.padEnd(11) + (ok ? '  OK' : '  ⚠ 순수출=' + has + ' 전환바=' + sw));
  }

  console.log(fail ? `\n실패 ${fail}건` : '\n전부 통과');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('ERR', e.message, '\n', e.stack.split('\n').slice(0, 3).join('\n')); process.exit(1); });

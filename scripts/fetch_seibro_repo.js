#!/usr/bin/env node
/**
 * SEIBro(예탁결제원) RP 시장현황 — 기관RP 일별 거래·잔고 스크래퍼.
 *
 * 이 페이지는 websquare(JS)로 렌더돼 단순 HTTP로는 표를 못 읽는다.
 * Playwright(헤드리스 크로미움)로 로드→렌더 대기→표의 셀에서
 * "날짜, 거래금액, 잔고금액" 3연속 패턴을 긁어 JSON으로 표준출력한다.
 *
 * 사용:  node scripts/fetch_seibro_repo.js --limit 30
 * 사전:  npm install playwright && npx playwright install chromium
 */
const { chromium } = require("playwright");

const URL =
  "https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/repo/BIP_CNTS09001V.xml&menuNo=233";

function argLimit(argv) {
  const i = argv.indexOf("--limit");
  if (i >= 0 && argv[i + 1]) {
    const n = Number(argv[i + 1]);
    if (Number.isFinite(n) && n > 0) return Math.floor(n);
  }
  return 30;
}

async function scrape(limit) {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(10000);   // websquare 렌더 대기
    const rows = await page.evaluate(() => {
      const isDate = t => /^\d{4}\/\d{2}\/\d{2}$/.test(t);
      const isNum = t => /^[\d,]+$/.test(t);
      const cells = Array.from(document.querySelectorAll("table td"))
        .map(n => (n.textContent || "").trim()).filter(Boolean);
      const out = [];
      for (let i = 0; i < cells.length - 2; i++) {
        if (isDate(cells[i]) && isNum(cells[i + 1]) && isNum(cells[i + 2])) {
          out.push({ date: cells[i], trade: cells[i + 1], balance: cells[i + 2] });
        }
      }
      return out;
    });
    const seen = new Map();
    for (const r of rows) if (!seen.has(r.date)) seen.set(r.date, r);
    return Array.from(seen.values()).slice(0, limit).map(r => ({
      date: r.date.replace(/\//g, "-"),
      trade: Number(String(r.trade).replace(/,/g, "")),
      balance: Number(String(r.balance).replace(/,/g, "")),
    }));
  } finally {
    await browser.close();
  }
}

scrape(argLimit(process.argv.slice(2)))
  .then(rows => process.stdout.write(JSON.stringify(rows) + "\n"))
  .catch(err => { console.error(err.message || String(err)); process.exit(1); });

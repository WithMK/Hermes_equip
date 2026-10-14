// Start AO_TEST_MANAGEMENT=1 python tests/web_demo_server.py first.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1360, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await page.goto('http://127.0.0.1:18650');
    await page.locator('#agent-new').click();
    const id = 'browser-doc-' + Date.now();
    await page.locator('#agent-id').fill(id);
    await page.locator('#agent-name').fill('Browser Agent');
    await page.locator('#agent-role').selectOption('document-agent');
    await page.locator('#agent-instructions').fill('근거와 가설을 구분해주세요.');
    await page.locator('#agent-save').click();
    const row = page.locator('#agents .agent').filter({hasText: id});
    await row.getByRole('button', {name: '시험 호출', exact: true}).click();
    await page.waitForFunction(id => [...document.querySelectorAll('#agents .agent')].some(e => e.textContent.includes(id) && e.textContent.includes('passed')), id);
    await row.getByRole('button', {name: '활성화', exact: true}).click();
    await row.getByRole('button', {name: '비활성화', exact: true}).waitFor();
    await page.locator('#objective').fill('문서 분석 보고서');
    await page.locator('#kind').selectOption('document_task');
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.getElementById('status').textContent === 'completed');
    assert.match(await page.locator('#runs').innerText(), new RegExp(id));
    await row.getByRole('button', {name: '이력', exact: true}).click();
    await page.waitForFunction(() => document.getElementById('agent-history').textContent.includes('enable'));
    await row.getByRole('button', {name: '수정', exact: true}).click();
    await page.locator('#agent-instructions').fill('변경한 지침');
    await page.locator('#agent-save').click();
    await row.getByRole('button', {name: '활성화', exact: true}).waitFor();
    await row.getByRole('button', {name: '삭제', exact: true}).click();
    await row.waitFor({state: 'detached'});
    await page.reload();
    await page.locator('#agent-new').waitFor();
    assert.equal(await row.count(), 0);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('PASS: Agent create/test/activate/run/history/edit/delete/reload/mobile');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

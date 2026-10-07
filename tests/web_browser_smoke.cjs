// Run with tests/web_demo_server.py on port 18650. Playwright is test-only.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1360, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:18650');
    await page.getByText('Browser test · synthetic services', {exact: true}).waitFor();
    await page.locator('#objective').fill('알람 원인을 문서 근거로 분석해주세요.');
    await page.locator('#kind').selectOption('troubleshooting');
    await page.locator('#artifact').check();
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.getElementById('status').textContent === 'completed');
    assert.match(await page.locator('#runs').innerText(), /troubleshooting-agent/);
    assert.match(await page.locator('#evidence').innerText(), /D1/);
    const taskId = await page.locator('#task-id').innerText();
    await page.reload();
    await page.waitForFunction(() => document.getElementById('status').textContent === 'completed');
    assert.equal(await page.locator('#task-id').innerText(), taskId);
    await page.getByRole('button', {name:'보고서 / Diff 보기'}).click();
    await page.waitForFunction(() => !document.querySelector('#artifacts pre').hidden);
    assert.match(await page.locator('#artifacts pre').innerText(), /Evidence/);
    await page.screenshot({path: '/tmp/phase5-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({path:'/tmp/phase5-mobile.png', fullPage: true});
    assert.deepEqual(errors, []);
    console.log('PASS: submit, specialist runs, evidence, artifact preview, reload, mobile, no JS errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

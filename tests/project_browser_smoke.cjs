// Start AO_TEST_MANAGEMENT=1 python tests/web_demo_server.py first.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1360, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:18650');
    const id = 'project-' + Date.now();
    await page.locator('#project-new').click();
    await page.locator('#project-id').fill(id);
    await page.locator('#project-name').fill('기술 자료 검토');
    await page.locator('#project-description').fill('일반 프로젝트 브라우저 검증');
    await page.locator('#project-save').click();
    await page.waitForFunction(id => document.getElementById('project-select').value === id, id);
    await page.locator('#note-content').fill('검토 결과는 담당자 확인 후 확정합니다.');
    await page.locator('#note-save').click();
    await page.getByText('검토 결과는 담당자 확인 후 확정합니다.', {exact: false}).first().waitFor();
    await page.locator('#objective').fill('문서 검토 보고서');
    await page.locator('#kind').selectOption('document_task');
    await page.locator('#artifact').check();
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.getElementById('status').textContent === 'completed');
    assert.match(await page.locator('#task-memory').innerText(), /담당자 확인/);
    await page.locator('#project-artifacts a').first().waitFor();
    await page.locator('#task-followup').click();
    assert.ok(await page.locator('#task-source').inputValue());
    await page.locator('#objective').fill('확인 순서를 더 설명');
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.getElementById('status').textContent === 'completed' && document.getElementById('task-memory').textContent.includes('prior_result'));
    await page.reload();
    await page.waitForFunction(id => document.getElementById('project-select').value === id, id);
    await page.locator('#project-edit').click();
    await page.locator('#project-status').selectOption('archived');
    await page.locator('#project-save').click();
    await page.waitForFunction(() => document.getElementById('submit').disabled);
    await page.locator('#project-select').selectOption('');
    await page.waitForFunction(() => document.getElementById('project-panel').hidden);
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('PASS: project create/memory/task/artifact/followup/reload/archive/mobile');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

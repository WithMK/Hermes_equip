// DOM + real HTTP API smoke. Run AO_TEST_MANAGEMENT=1 python tests/web_demo_server.py first.
// npm install --no-save jsdom@26.1.0
// node tests/assignment_ui_smoke.cjs
// This checks DOM behavior, not browser layout or native dialogs.
const assert = require('node:assert/strict');
const {JSDOM, VirtualConsole} = require('jsdom');
const base = 'http://127.0.0.1:18650';
async function request(path, method = 'GET', body) {
  const response = await fetch(base + path, {method, headers:{'Content-Type':'application/json','X-AO-Request':'1'}, body:body && JSON.stringify(body)});
  assert.ok(response.ok, `${response.status}: ${await response.clone().text()}`);
  return response.json();
}
const wait = async fn => {
  for (let i = 0; i < 200; i++) { if (fn()) return; await new Promise(r => setTimeout(r, 20)); }
  throw Error('UI wait timed out');
};
(async () => {
  const id = 'assignment-' + Date.now(), beta = id + '-beta';
  for (const project_id of [id, beta]) await request('/v1/projects', 'POST', {project_id, name:project_id});
  let dom;
  const errors = [], dialogs = [];
  try {
    const virtualConsole = new VirtualConsole(); virtualConsole.on('jsdomError', e => errors.push(e.message));
    dom = await JSDOM.fromURL(base, {resources:'usable', runScripts:'dangerously', pretendToBeVisual:true, virtualConsole,
      beforeParse(window) {
        window.fetch = (path, options) => fetch(new URL(path, base), options);
        window.crypto.randomUUID = require('node:crypto').randomUUID;
        window.TextEncoder = TextEncoder;
        window.confirm = message => { dialogs.push(message); return false; };
        window.localStorage.setItem('ao-project', id);
        window.HTMLElement.prototype.scrollIntoView = () => {};
      }});
    const w = dom.window, $ = id => w.document.getElementById(id);
    const input = (node, value) => { node.value = value; node.dispatchEvent(new w.Event('input', {bubbles:true})); };
    const submit = () => $('assignment-form').dispatchEvent(new w.Event('submit', {bubbles:true,cancelable:true}));
    await wait(() => $('assignment-status').textContent.includes('설정 v0'));
    assert.equal($('assignment-fields').disabled, false);
    input($('assignment-candidate'), 'document-agent'); $('assignment-add').click();
    input($('assignment-mode'), 'custom'); input($('assignment-default'), 'document-agent');
    let row = $('assignment-rows').querySelector('[data-agent-id="document-agent"]');
    input(row.querySelector('[data-field="instructions"]'), '<img src=x onerror=alert(1)> 근거 확인');
    assert.equal(row.querySelector('img'), null);
    $('refresh').click();
    await new Promise(r => setTimeout(r, 100));
    assert.match($('assignment-rows').querySelector('textarea').value, /근거 확인/);
    input($('project-select'), beta); $('project-select').dispatchEvent(new w.Event('change'));
    assert.equal($('project-select').value, id); assert.ok(dialogs.length);
    submit(); await wait(() => $('assignment-status').textContent.includes('v1 저장 완료'));
    const path = `/v1/projects/${id}/agent-assignments`;
    let saved = await request(path);
    assert.equal(saved.configuration.default_agent_id, 'document-agent');
    assert.equal(saved.runtime_applied, true);
    input($('objective'), '문서 검토'); input($('kind'), 'document_task');
    $('task-form').dispatchEvent(new w.Event('submit', {bubbles:true,cancelable:true}));
    await wait(() => $('status').textContent === 'completed');
    assert.match($('runs').textContent, /시작 시 배정 v1/);
    assert.match($('runs').textContent, /document-agent/);
    assert.match(saved.configuration.agents[0].instructions, /근거 확인/);
    assert.equal((await request(`/v1/projects/${beta}/agent-assignments`)).version, 0);
    // Another editor saves first. A stale save preserves local input and reports conflict.
    await request(path, 'PUT', {version:1, configuration:saved.configuration});
    input($('assignment-rows').querySelector('textarea'), 'retain conflict draft');
    submit(); await wait(() => $('assignment-error').textContent.includes('changed'));
    assert.equal($('assignment-rows').querySelector('textarea').value, 'retain conflict draft');
    w.confirm = () => true;
    $('assignment-reload').click(); await wait(() => $('assignment-status').textContent.includes('설정 v2'));
    assert.match($('assignment-rows').querySelector('textarea').value, /근거 확인/);
    // Remove assignment, save legacy configuration, and ensure the registry still exists.
    $('assignment-rows').querySelector('button').click(); input($('assignment-mode'), 'legacy');
    submit(); await wait(() => $('assignment-status').textContent.includes('v3 저장 완료'));
    assert.equal((await request(path)).configuration.agents.length, 0);
    assert.ok((await request('/v1/agents')).some(a => a.agent_id === 'document-agent'));
    const exported = await request(new URL($('assignment-export').href).pathname);
    exported.configuration.mode = 'custom';
    exported.configuration.default_agent_id = 'document-agent';
    exported.configuration.agents = [{agent_id:'document-agent', assignment:'Imported', instructions:'imported guidance', enabled:true, allow_delegation:true}];
    input($('assignment-import-text'), '{bad json'); $('assignment-preview').click();
    await wait(() => $('assignment-import-message').textContent.includes('올바른 JSON'));
    assert.equal($('assignment-apply-import').disabled, true);
    input($('assignment-import-text'), JSON.stringify(exported)); $('assignment-preview').click();
    await wait(() => !$('assignment-apply-import').disabled);
    assert.match($('assignment-diff').textContent, /Imported/);
    assert.equal((await request(path)).version, 3);
    // Editing JSON invalidates the reviewed preview.
    input($('assignment-import-text'), JSON.stringify(exported));
    assert.equal($('assignment-apply-import').disabled, true);
    $('assignment-preview').click(); await wait(() => !$('assignment-apply-import').disabled);
    $('assignment-apply-import').click(); await wait(() => $('assignment-status').textContent.includes('v4 가져오기 완료'));
    assert.equal((await request(path)).configuration.agents[0].instructions, 'imported guidance');
    let project = await request(`/v1/projects/${id}`);
    await request(`/v1/projects/${id}`, 'PUT', {version:project.version, name:project.name, status:'archived'});
    $('refresh').click(); await wait(() => $('assignment-status').textContent.includes('읽기 전용'));
    assert.equal($('assignment-fields').disabled, true);
    assert.deepEqual(errors, []);
    console.log('PASS: assignment UI, execution, isolation, conflicts, portable JSON preview/apply, remove and archive');
  } finally { if(dom) dom.window.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

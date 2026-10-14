'use strict';
const $ = id => document.getElementById(id);
let selected = localStorage.getItem('ao-task') || '', polling = false, artifactKey = '';
let manageAgents = false, editingAgent = null;
const terminal = new Set(['completed', 'failed', 'interrupted']);
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-AO-Request': '1', ...(options.headers || {}) } });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `요청 실패 (${response.status})`);
  return data;
}
function text(id, value) { $(id).textContent = value || ''; }
function block(parent, className, content) { const item = document.createElement('div'); item.className = className; item.textContent = content; parent.append(item); return item; }
async function listTasks() {
  const tasks = await api('/v1/tasks'); $('tasks').replaceChildren();
  for (const task of tasks) {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = `${task.status} · ${task.objective.slice(0, 65)}`;
    button.setAttribute('aria-current', String(task.task_id === selected));
    button.addEventListener('click', () => { selected = task.task_id; localStorage.setItem('ao-task', selected); refresh().catch(showError); });
    $('tasks').append(button);
  }
  if (!tasks.length) block($('tasks'), 'muted', '아직 실행한 작업이 없습니다.');
}
function showError(error) { text('error', error.message); }
async function detail() {
  if (!selected) return;
  const id = encodeURIComponent(selected);
  const [task, runs] = await Promise.all([api(`/v1/tasks/${id}`), api(`/v1/tasks/${id}/runs`)]);
  if (id !== encodeURIComponent(selected)) return;
  $('detail').hidden = false; text('status', task.status); text('task-id', task.task_id);
  text('request', task.objective); text('answer', task.answer || (terminal.has(task.status) ? '저장된 답변 없음 — 오류 또는 산출물을 확인하세요.' : '작업을 수행하고 있습니다…'));
  text('diagnostic', [task.error, task.failure_reason, task.finish_reason === 'no_evidence' ? '검색 근거가 없어 전문 Agent를 호출하지 않았습니다.' : '', `호출 모드: ${task.delegation_mode}`, task.submission_status === 'interrupted' ? '서버 중단 기록 — 기존 결과를 확인한 후 새 작업을 제출하세요.' : ''].filter(Boolean).join(' / '));
  for (const key of ['runs', 'evidence']) $(key).replaceChildren();
  for (const run of runs) block($('runs'), 'run', `${run.agent_name} · ${run.status}\n${run.summary || run.error || ''}`);
  for (const profile of task.agent_profiles || []) block($('runs'), 'muted', `${profile.role} → ${profile.agent_id}${profile.version ? ` · v${profile.version}` : ''}`);
  for (const source of task.evidence) block($('evidence'), 'source', `[${source.source_id}] ${source.source_type} · ${source.record_id}\n${source.summary}`);
  const nextArtifactKey = task.task_id + JSON.stringify(task.artifacts);
  if (nextArtifactKey === artifactKey) return;
  artifactKey = nextArtifactKey; $('artifacts').replaceChildren();
  for (const artifact of task.artifacts) {
    const line = block($('artifacts'), 'source', `${artifact.artifact_type} · SHA-256 ${artifact.sha256}\n`);
    const link = document.createElement('a'); link.href = artifact.download_url; link.textContent = '검증된 보고서 다운로드'; line.append(link);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = '보고서 / Diff 보기';
    const preview = document.createElement('pre'); preview.hidden = true;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const response = await fetch(artifact.download_url);
        if (!response.ok) throw new Error('산출물 무결성 또는 접근 오류');
        preview.textContent = await response.text(); preview.hidden = false;
      } catch (e) { showError(e); } finally { button.disabled = false; }
    }); line.append(button, preview);
  }
}
async function refresh() { await listTasks(); await detail(); text('connection', 'A/O 연결됨'); }
async function start() {
  const config = await api('/v1/workspace'); text('workspace-name', config.name);
  text('subject-label', `${config.subject_label || 'Equipment'} ID (선택)`);
  $('equipment').placeholder = config.domain_id === 'document' ? '예: 구매절차' : '예: E-024';
  for (const option of Array.from($('kind').options)) {
    if (option.value && !config.allowed_request_kinds.includes(option.value)) option.remove();
  }
  text('mode', `전문 Agent: ${config.specialists_enabled ? '활성' : '비활성 — C/M 직접 호출'} · 단일 순차 작업 큐`);
  $('artifact').disabled = !config.artifacts_enabled;
  $('session').value = localStorage.getItem('ao-session') || '';
  manageAgents = !!config.agent_management_enabled;
  $('agent-new').hidden = !manageAgents;
  text('agent-mode', manageAgents ? '등록 → 시험 호출 → 활성화. 역할별 한 Agent를 사용합니다.' : '등록 정보는 읽기 전용입니다.');
  if (manageAgents) {
    for (const template of await api('/v1/agent-templates')) {
      const option = document.createElement('option'); option.value = template.role; option.textContent = template.role; $('agent-role').append(option);
    }
  }
  await loadAgents();
  await refresh();
}
function editAgent(agent = null) {
  editingAgent = agent; $('agent-editor').hidden = false;
  text('agent-editor-title', agent ? 'Agent 수정' : 'Agent 등록');
  $('agent-id').value = agent?.agent_id || ''; $('agent-id').disabled = !!agent;
  $('agent-name').value = agent?.name || ''; $('agent-role').value = agent?.role || $('agent-role').options[0]?.value || '';
  $('agent-instructions').value = agent?.instructions || '';
  $('agent-editor').scrollIntoView({behavior: 'smooth'});
}
async function loadAgents() {
  const agents = await api('/v1/agents'); $('agents').replaceChildren();
  for (const agent of agents) {
    const row = block($('agents'), 'agent', `${agent.name || agent.agent_id} · ${agent.agent_id}\n${agent.role || ''} · ${agent.enabled ? '활성' : '비활성'}${agent.version ? ` · v${agent.version} · 시험: ${agent.test_status}` : ''}\n${agent.endpoint}\n${agent.policy}`);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = '연결 확인';
    button.addEventListener('click', async () => { button.disabled = true; try { const state = await api(`/v1/agents/${encodeURIComponent(agent.agent_id)}/health`); button.textContent = `${state.status} (추론 미검증)`; } catch (e) { showError(e); } finally { button.disabled = false; } }); row.append(button);
    if (manageAgents) {
      const path = `/v1/agents/${encodeURIComponent(agent.agent_id)}`;
      const action = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.addEventListener('click', async () => { b.disabled = true; text('error', ''); try { await fn(); } catch(e) { showError(e); } finally { b.disabled = false; } }); row.append(b); };
      action('수정', () => editAgent(agent));
      action('시험 호출', async () => { const result = await api(path + '/test', {method: 'POST', body: JSON.stringify({version: agent.version})}); await loadAgents(); if (result.test_status !== 'passed') throw new Error('시험 호출에 실패했습니다. 연결 서버·모델·근거 인용 응답을 확인해주세요.'); });
      action(agent.enabled ? '비활성화' : '활성화', async () => { await api(path + '/enabled', {method: 'POST', body: JSON.stringify({version: agent.version, enabled: !agent.enabled})}); await loadAgents(); });
      action('이력', async () => { text('agent-history', JSON.stringify(await api(path + '/history'), null, 2)); $('agent-history-panel').hidden = false; });
      if (!agent.enabled) action('삭제', async () => { if (confirm(`${agent.name} 설정을 삭제할까요? 변경 이력은 보존됩니다.`)) { await api(path + `?version=${agent.version}`, {method: 'DELETE'}); await loadAgents(); } });
    }
  }
}
$('agent-new').addEventListener('click', () => editAgent());
$('agent-cancel').addEventListener('click', () => { $('agent-editor').hidden = true; });
$('agent-history-close').addEventListener('click', () => { $('agent-history-panel').hidden = true; });
$('agent-editor').addEventListener('submit', async event => {
  event.preventDefault(); $('agent-save').disabled = true;
  const value = {name: $('agent-name').value, role: $('agent-role').value, instructions: $('agent-instructions').value};
  try {
    if (editingAgent) await api(`/v1/agents/${encodeURIComponent(editingAgent.agent_id)}`, {method: 'PUT', body: JSON.stringify({...value, version: editingAgent.version})});
    else await api('/v1/agents', {method: 'POST', body: JSON.stringify({...value, agent_id: $('agent-id').value})});
    $('agent-editor').hidden = true; await loadAgents(); text('error', '');
  } catch(e) { showError(e); } finally { $('agent-save').disabled = false; }
});
$('task-form').addEventListener('submit', async event => {
  event.preventDefault(); text('error', ''); $('submit').disabled = true;
  try {
    if (!$('session').value.trim()) $('session').value = `ui-${crypto.randomUUID()}`;
    localStorage.setItem('ao-session', $('session').value);
    const result = await api('/v1/tasks', { method: 'POST', body: JSON.stringify({objective: $('objective').value, session_id: $('session').value, subject_id: $('equipment').value.trim() || null, request_kind: $('kind').value || null, create_artifact: $('artifact').checked}) });
    selected = result.task_id; localStorage.setItem('ao-task', selected); await refresh();
  } catch (e) { showError(e); } finally { $('submit').disabled = false; }
});
$('refresh').addEventListener('click', () => Promise.all([refresh(), loadAgents()]).catch(showError));
start().catch(showError);
setInterval(async () => { if (polling || document.hidden) return; polling = true; try { await refresh(); } catch (e) { text('connection', '연결 확인 필요'); showError(e); } finally { polling = false; } }, 2500);

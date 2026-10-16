'use strict';
const $ = id => document.getElementById(id);
let selected = localStorage.getItem('ao-task') || '', polling = false, artifactKey = '';
let manageAgents = false, editingAgent = null;
let currentProject = localStorage.getItem('ao-project') || '', projects = [], editingProject = null, editingNote = null;
let workspaceName = '', projectTasks = [], activeTask = null;
let materialUploads = false, materialRows = [], materialBusy = false;
let assignmentPreview = null, assignmentPreviewRequest = 0;
let assignmentState = null, assignmentProfiles = [], assignmentDirty = false, assignmentSaving = false, assignmentLoad = 0;
const terminal = new Set(['completed', 'failed', 'interrupted']);
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-AO-Request': '1', ...(options.headers || {}) } });
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.issues?.join('\n') || `요청 실패 (${response.status})`);
  return data;
}
function text(id, value) { $(id).textContent = value || ''; }
function block(parent, className, content) { const item = document.createElement('div'); item.className = className; item.textContent = content; parent.append(item); return item; }
async function listTasks() {
  const scope = currentProject;
  const tasks = await api('/v1/tasks' + (scope ? `?project_id=${encodeURIComponent(scope)}` : ''));
  if (scope !== currentProject) return;
  projectTasks = tasks; $('tasks').replaceChildren();
  for (const task of tasks) {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = `${task.status} · ${task.objective.slice(0, 65)}`;
    button.setAttribute('aria-current', String(task.task_id === selected));
    button.addEventListener('click', () => { selected = task.task_id; localStorage.setItem('ao-task', selected); refresh().catch(showError); });
    $('tasks').append(button);
  }
  if (!tasks.length) block($('tasks'), 'muted', '아직 실행한 작업이 없습니다.');
  if (selected && !tasks.some(task => task.task_id === selected)) {
    selected = ''; activeTask = null; $('detail').hidden = true; artifactKey = '';
  }
  renderProjectArtifacts();
}
function showError(error) { text('error', error.message); }
async function detail() {
  if (!selected) return;
  const id = encodeURIComponent(selected);
  const [task, runs] = await Promise.all([api(`/v1/tasks/${id}`), api(`/v1/tasks/${id}/runs`)]);
  if (id !== encodeURIComponent(selected)) return;
  activeTask = task;
  $('task-followup').disabled = !currentProject || task.project_id !== currentProject || task.status !== 'completed' || task.finish_reason === 'no_evidence';
  text('task-memory', task.project_memory || '프로젝트 Memory를 사용하지 않았습니다.');
  $('detail').hidden = false; text('status', task.status); text('task-id', task.task_id);
  text('request', task.objective); text('answer', task.answer || (terminal.has(task.status) ? '저장된 답변 없음 — 오류 또는 산출물을 확인하세요.' : '작업을 수행하고 있습니다…'));
  text('diagnostic', [task.error, task.failure_reason, task.finish_reason === 'no_evidence' ? '검색 근거가 없어 전문 Agent를 호출하지 않았습니다.' : '', `호출 모드: ${task.delegation_mode}`, task.submission_status === 'interrupted' ? '서버 중단 기록 — 기존 결과를 확인한 후 새 작업을 제출하세요.' : ''].filter(Boolean).join(' / '));
  for (const key of ['runs', 'evidence']) $(key).replaceChildren();
  for (const run of runs) block($('runs'), 'run', `${run.agent_name} · ${run.status}\n${run.summary || run.error || ''}`);
  if (task.agent_assignment) block($('runs'), 'muted', `시작 시 배정 v${task.agent_assignment.version} · ${task.agent_assignment.execution_mode === 'project' ? '프로젝트 배정' : '기존 방식'} · 기본 담당: ${task.agent_assignment.configuration.default_agent_id || '기존 설정'}`);
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
  workspaceName = config.name;
  materialUploads = !!config.material_uploads_enabled;
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
  text('agent-mode', manageAgents ? '시험 호출 후 기본 활성화 또는 프로젝트 전용 활성화를 선택합니다.' : '등록 정보는 읽기 전용입니다.');
  if (manageAgents) {
    for (const template of await api('/v1/agent-templates')) {
      const option = document.createElement('option'); option.value = template.role; option.textContent = template.role; $('agent-role').append(option);
    }
  }
  await loadAgents();
  await loadProjects();
  await refresh();
}
function resetNote() {
  editingNote = null; text('note-title', '기록 추가'); $('note-content').value = '';
  $('note-source').value = ''; $('note-kind').value = 'decision'; $('note-status').value = 'active';
  $('note-status').disabled = true;
}
async function loadProjects() {
  projects = await api('/v1/projects');
  if (currentProject && !projects.some(p => p.project_id === currentProject)) currentProject = '';
  $('project-select').replaceChildren();
  const all = document.createElement('option'); all.value = ''; all.textContent = '전체 업무 / 프로젝트 미지정 실행'; $('project-select').append(all);
  for (const project of projects) {
    const option = document.createElement('option'); option.value = project.project_id;
    option.textContent = project.name + (project.status === 'archived' ? ' (보관)' : ''); $('project-select').append(option);
  }
  $('project-select').value = currentProject;
  localStorage.setItem('ao-project', currentProject);
  await showProject();
}
async function showProject() {
  materialRows = []; $('materials').replaceChildren(); $('material-file').value = '';
  const project = projects.find(p => p.project_id === currentProject);
  $('project-panel').hidden = !project; $('project-edit').disabled = !project;
  $('use-memory').disabled = !project; $('task-source').disabled = !project;
  $('submit').disabled = project?.status === 'archived';
  $('equipment').value = project?.subject_id || ''; $('equipment').readOnly = !!project?.subject_id;
  text('workspace-name', project ? `${workspaceName} / ${project.name}` : workspaceName);
  resetNote(); $('project-history').hidden = true;
  if (!project) { assignmentState = null; assignmentDirty = false; assignmentLoad++; return; }
  text('project-title', project.name); text('project-summary', project.description);
  text('project-binding', `${project.domain_id} · ${project.status} · 문서 Project: ${project.knowledge_project || '전체'} · 코드 Repository: ${project.repository || '전체'}`);
  $('note-save').disabled = project.status === 'archived';
  $('material-form').hidden = !materialUploads;
  $('material-upload').disabled = project.status === 'archived' || materialBusy;
  $('material-refresh').hidden = !materialUploads;
  text('material-mode', materialUploads ? '준비 완료 자료는 이 프로젝트의 RAG 검색에 사용됩니다. 검색 제외 자료는 원본을 보관하며 복원할 수 있습니다.' : '자료 등록 서버 연결이 설정되지 않았습니다.');
  text('material-message', '');
  await loadAssignments();
  await loadMaterials();
  await loadNotes();
}
async function loadNotes() {
  const scope = currentProject;
  if (!scope) return;
  const notes = await api(`/v1/projects/${encodeURIComponent(scope)}/memory`);
  if (scope !== currentProject) return;
  $('project-notes').replaceChildren();
  for (const note of notes) {
    const row = block($('project-notes'), 'source', `${note.kind === 'decision' ? '사용자 확정 결정' : '미해결 항목'} · ${note.status} · v${note.version}\n${note.content}\n${note.source_task_id || ''}`);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = '수정 / 완료';
    button.disabled = projects.find(p => p.project_id === scope)?.status === 'archived';
    button.addEventListener('click', () => {
      editingNote = note; text('note-title', '기록 수정'); $('note-kind').value = note.kind;
      $('note-content').value = note.content; $('note-source').value = note.source_task_id;
      $('note-status').value = note.status; $('note-status').disabled = false;
      $('note-form').scrollIntoView({behavior: 'smooth'});
    }); row.append(button);
  }
  if (!notes.length) block($('project-notes'), 'muted', '등록한 기록이 없습니다.');
}
function renderProjectArtifacts() {
  $('project-artifacts').replaceChildren();
  for (const task of projectTasks) for (const artifact of task.artifacts) {
    const row = block($('project-artifacts'), 'source', `${task.objective.slice(0, 70)} · ${artifact.artifact_type}\n`);
    const link = document.createElement('a'); link.href = artifact.download_url; link.textContent = '검증된 결과물 다운로드'; row.append(link);
  }
  if (!$('project-artifacts').children.length) block($('project-artifacts'), 'muted', '최근 50개 업무에 저장된 결과물이 없습니다.');
}
function editProject(project = null) {
  editingProject = project; $('project-editor').hidden = false;
  text('project-editor-title', project ? '프로젝트 설정' : '프로젝트 생성');
  $('project-id').value = project?.project_id || ''; $('project-id').disabled = !!project;
  for (const [id, key] of [['project-name', 'name'], ['project-description', 'description'], ['project-subject', 'subject_id'], ['project-knowledge', 'knowledge_project'], ['project-repository', 'repository']]) $(id).value = project?.[key] || '';
  $('project-status').value = project?.status || 'active'; $('project-status').disabled = !project;
  $('project-knowledge').disabled = !!project?.materials_namespace;
  $('project-subject').disabled = !!project?.materials_namespace;
  $('project-editor').scrollIntoView({behavior: 'smooth'});
}
$('project-new').addEventListener('click', () => editProject());
$('project-edit').addEventListener('click', () => editProject(projects.find(p => p.project_id === currentProject)));
$('project-cancel').addEventListener('click', () => { $('project-editor').hidden = true; });
$('project-select').addEventListener('change', async () => {
  if (assignmentSaving || ((assignmentDirty || $('assignment-import-text').value.trim()) && !confirm('저장하지 않은 Agent 배정 변경을 버리고 프로젝트를 전환할까요?'))) {
    $('project-select').value = currentProject; return;
  }
  assignmentDirty = false;
  currentProject = $('project-select').value; localStorage.setItem('ao-project', currentProject);
  selected = ''; artifactKey = ''; activeTask = null; $('detail').hidden = true;
  $('task-source').value = ''; $('session').value = ''; $('project-editor').hidden = true;
  try { await showProject(); await refresh(); } catch(e) { showError(e); }
});
$('project-editor').addEventListener('submit', async event => {
  event.preventDefault(); $('project-save').disabled = true;
  const value = {name: $('project-name').value, description: $('project-description').value, subject_id: $('project-subject').value, knowledge_project: $('project-knowledge').value, repository: $('project-repository').value};
  try {
    const result = editingProject ? await api(`/v1/projects/${encodeURIComponent(editingProject.project_id)}`, {method:'PUT', body:JSON.stringify({...value, version:editingProject.version, status:$('project-status').value})}) : await api('/v1/projects', {method:'POST', body:JSON.stringify({...value, project_id:$('project-id').value})});
    currentProject = result.project_id; selected = ''; $('detail').hidden = true; $('task-source').value = '';
    $('project-editor').hidden = true; await loadProjects(); await refresh(); text('error', '');
  } catch(e) { showError(e); } finally { $('project-save').disabled = false; }
});
$('note-cancel').addEventListener('click', resetNote);
$('note-form').addEventListener('submit', async event => {
  event.preventDefault(); $('note-save').disabled = true;
  const value = {kind:$('note-kind').value, content:$('note-content').value, source_task_id:$('note-source').value};
  const path = `/v1/projects/${encodeURIComponent(currentProject)}/memory`;
  try {
    if (editingNote) await api(path + '/' + encodeURIComponent(editingNote.note_id), {method:'PUT', body:JSON.stringify({...value, version:editingNote.version, status:$('note-status').value})});
    else await api(path, {method:'POST', body:JSON.stringify(value)});
    resetNote(); await loadNotes(); text('error', '');
  } catch(e) { showError(e); } finally { $('note-save').disabled = projects.find(p => p.project_id === currentProject)?.status === 'archived'; }
});
$('project-history-button').addEventListener('click', async () => {
  try { text('project-history', JSON.stringify(await api(`/v1/projects/${encodeURIComponent(currentProject)}/history`), null, 2)); $('project-history').hidden = false; } catch(e) { showError(e); }
});
$('task-followup').addEventListener('click', () => {
  if (!activeTask || activeTask.project_id !== currentProject) return;
  $('task-source').value = activeTask.task_id; $('use-memory').checked = true;
  $('objective').value = ''; $('objective').focus();
});
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
    const row = block($('agents'), 'agent', `${agent.name || agent.agent_id} · ${agent.agent_id}\n${agent.role || ''} · ${agent.enabled ? (agent.default_for_role === false ? '프로젝트 전용 활성' : '기본 활성') : '비활성'}${agent.version ? ` · v${agent.version} · 시험: ${agent.test_status}` : ''}\n${agent.endpoint}\n${agent.policy}`);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = '연결 확인';
    button.addEventListener('click', async () => { button.disabled = true; try { const state = await api(`/v1/agents/${encodeURIComponent(agent.agent_id)}/health`); button.textContent = `${state.status} (추론 미검증)`; } catch (e) { showError(e); } finally { button.disabled = false; } }); row.append(button);
    if (manageAgents) {
      const path = `/v1/agents/${encodeURIComponent(agent.agent_id)}`;
      const action = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.addEventListener('click', async () => { b.disabled = true; text('error', ''); try { await fn(); } catch(e) { showError(e); } finally { b.disabled = false; } }); row.append(b); };
      action('수정', () => editAgent(agent));
      action('시험 호출', async () => { const result = await api(path + '/test', {method: 'POST', body: JSON.stringify({version: agent.version})}); await loadAgents(); if (result.test_status !== 'passed') throw new Error('시험 호출에 실패했습니다. 연결 서버·모델·근거 인용 응답을 확인해주세요.'); });
      action(agent.enabled ? '비활성화' : '활성화', async () => { await api(path + '/enabled', {method: 'POST', body: JSON.stringify({version: agent.version, enabled: !agent.enabled})}); await loadAgents(); });
      if (!agent.enabled) action('프로젝트 전용 활성화', async () => { await api(path + '/enabled', {method:'POST', body:JSON.stringify({version:agent.version, enabled:true, make_default:false})}); await loadAgents(); });
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
    const result = await api('/v1/tasks', { method: 'POST', body: JSON.stringify({objective: $('objective').value, session_id: $('session').value, subject_id: $('equipment').value.trim() || null, request_kind: $('kind').value || null, create_artifact: $('artifact').checked, project_id: currentProject, use_memory: $('use-memory').checked, source_task_id: $('task-source').value.trim()}) });
    selected = result.task_id; localStorage.setItem('ao-task', selected); await refresh();
  } catch (e) { showError(e); } finally { $('submit').disabled = projects.find(p => p.project_id === currentProject)?.status === 'archived'; }
});
$('refresh').addEventListener('click', () => Promise.all([refresh(), loadAgents(), loadProjects()]).catch(showError));
start().catch(showError);
setInterval(async () => { if (polling || document.hidden) return; polling = true; try { await refresh(); await loadMaterials(); } catch (e) { text('connection', '연결 확인 필요'); showError(e); } finally { polling = false; } }, 2500);

async function loadMaterials() {
  const scope = currentProject;
  if (!scope || !materialUploads) { $('materials').replaceChildren(); $('material-watches').replaceChildren(); materialRows = []; return; }
  try {
    const result = await api(`/v1/projects/${encodeURIComponent(scope)}/materials`);
    if (scope !== currentProject) return;
    materialRows = result.documents; $('materials').replaceChildren();
    const labels = {queued:'대기', indexing:'처리 중', ready:'준비 완료', failed:'실패', excluded:'검색 제외', deleted:'삭제 완료'};
    for (const item of materialRows) {
      const goal = {active:'검색 사용', excluded:'검색 제외', deleted:'삭제'}[item.desired_state] || '';
      const row = block($('materials'), 'source', `${item.filename} · ${labels[item.status] || item.status} · v${item.version} · ${item.chunks}개 조각\n${goal}${item.source_key ? ' · 폴더 자료' : ''}\n${item.error || ''}`);
      const busy = ['queued', 'indexing', 'deleted'].includes(item.status);
      const action = (label, operation, confirmText = '') => {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
        button.disabled = busy || projects.find(p => p.project_id === scope)?.status !== 'active';
        button.addEventListener('click', async () => {
          if (confirmText && !confirm(confirmText)) return;
          button.disabled = true;
          try { await api(`/v1/projects/${encodeURIComponent(scope)}/materials/${encodeURIComponent(item.id)}/${operation}`, {method:'POST', body:JSON.stringify({version:item.version})}); await loadMaterials(); }
          catch(e) { text('material-message', e.message); }
          finally { button.disabled = false; }
        }); row.append(button);
      };
      if (item.status === 'failed') action('실패 작업 재시도', 'retry');
      if (item.status !== 'deleted' && item.desired_state !== 'deleted') {
        if (item.desired_state === 'excluded') action('검색 복원', 'restore');
        else {
          action('재인덱싱', 'reindex');
          action('검색 제외', 'exclude');
        }
        action('삭제', 'delete', `${item.filename}의 등록 원본과 검색 자료를 삭제할까요?\n감시 폴더의 원본 파일은 유지됩니다. 이 삭제는 되돌릴 수 없습니다.`);
      }
    }
    if (!materialRows.length) block($('materials'), 'muted', '등록한 자료가 없습니다.');
    await loadWatches(scope);
  } catch(e) { if (scope === currentProject) text('material-message', e.message); }
}
$('material-refresh').addEventListener('click', loadMaterials);
$('material-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (materialBusy || !currentProject) return;
  const scope = currentProject, file = $('material-file').files[0];
  if (!file || !file.size || file.size > 10 * 1024 * 1024) { text('material-message', '1 byte ~ 10 MiB 파일을 선택하세요.'); return; }
  const old = materialRows.find(item => !item.source_key && item.filename.toLowerCase() === file.name.toLowerCase());
  if (old && !confirm(`${file.name} 자료를 확인·교체할까요? 같은 내용이면 기존 자료를 유지합니다.`)) return;
  materialBusy = true; $('material-upload').disabled = true;
  try {
    const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(new Error('파일 읽기 실패')); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.readAsDataURL(file); });
    await api(`/v1/projects/${encodeURIComponent(scope)}/materials`, {method:'POST', body:JSON.stringify({filename:file.name, content_base64:encoded, version:old?.version || 0})});
    if (scope === currentProject) { $('material-file').value = ''; await loadProjects(); text('material-message', '접수되었습니다. 아래 목록에서 처리 결과를 확인하세요.'); }
  } catch(e) {
    if (scope === currentProject) { await loadProjects(); text('material-message', e.message); }
  } finally { materialBusy = false; $('material-upload').disabled = projects.find(p => p.project_id === currentProject)?.status !== 'active'; }
});

async function loadWatches(scope) {
  const result = await api(`/v1/projects/${encodeURIComponent(scope)}/material-watches`);
  if (scope !== currentProject) return;
  $('material-watches').replaceChildren();
  const labels = {waiting:'대기', paused:'일시 정지', archived:'프로젝트 보관', watching:'감시 중', error:'확인 필요', settling:'파일 저장 완료 대기', pending:'인덱싱 대기/진행', synced:'반영 완료', failed:'인덱싱 실패', excluded:'검색 제외 유지', deleted:'삭제 유지', missing:'원본 파일 없음'};
  for (const watch of result.watches) {
    const row = block($('material-watches'), 'source', `${watch.watch_id} · ${labels[watch.status] || watch.status}\n${watch.path}\n${watch.error || ''}`);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = watch.enabled ? '일시 정지' : '감시 재개';
    button.disabled = projects.find(p => p.project_id === scope)?.status !== 'active';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await api(`/v1/projects/${encodeURIComponent(scope)}/material-watches/${encodeURIComponent(watch.watch_id)}/enabled`, {method:'POST', body:JSON.stringify({enabled:!watch.enabled})}); await loadWatches(scope); }
      catch(e) { text('material-message', e.message); }
    }); row.append(button);
    const details = document.createElement('details'), summary = document.createElement('summary');
    summary.textContent = `파일 상태 (${watch.files.length})`; details.append(summary);
    for (const file of watch.files) block(details, 'muted', `${file.relative_path} · ${labels[file.status] || file.status}${file.error ? '\n' + file.error : ''}`);
    row.append(details);
  }
  if (!result.watches.length) block($('material-watches'), 'muted', '지정한 폴더가 없습니다. 운영자가 서버의 폴더 감시 설정을 추가하면 표시됩니다.');
}

function assignmentEditable() {
  return !!assignmentState && assignmentState.project_id === currentProject && manageAgents &&
    projects.find(p => p.project_id === currentProject)?.status === 'active' && !assignmentSaving;
}
function assignmentChanged() {
  clearAssignmentPreview();
  assignmentDirty = true;
  text('assignment-status', '저장하지 않은 변경 사항이 있습니다.');
}
function assignmentOptions(select, entries, selectedValue, emptyLabel) {
  select.replaceChildren();
  const empty = document.createElement('option'); empty.value = ''; empty.textContent = emptyLabel; select.append(empty);
  for (const [value, label] of entries) {
    const option = document.createElement('option'); option.value = value; option.textContent = label; select.append(option);
  }
  if (selectedValue && !entries.some(([value]) => value === selectedValue)) {
    const unavailable = document.createElement('option'); unavailable.value = selectedValue;
    unavailable.textContent = `${selectedValue} (사용 불가 — 다시 선택하세요)`; select.append(unavailable);
  }
  select.value = selectedValue;
}
function refreshAssignmentChoices() {
  const config = assignmentState.configuration;
  const assigned = new Set(config.agents.map(a => a.agent_id));
  assignmentOptions($('assignment-candidate'), assignmentProfiles.filter(p => p.available && !assigned.has(p.agent_id))
    .map(p => [p.agent_id, `${p.name} · ${p.role}${p.enabled ? '' : ' (비활성)'}`]), '', 'Agent 선택');
  assignmentOptions($('assignment-default'), config.agents.filter(a => a.enabled && assignmentProfiles.some(p => p.agent_id === a.agent_id && p.available && p.enabled))
    .map(a => [a.agent_id, assignmentProfiles.find(p => p.agent_id === a.agent_id)?.name || a.agent_id]), config.default_agent_id, '기본 담당 미지정');
  $('assignment-add').disabled = !assignmentEditable() || config.agents.length >= 32 || $('assignment-candidate').options.length < 2;
}
function renderAssignments() {
  const config = assignmentState.configuration;
  $('assignment-fields').disabled = !assignmentEditable();
  $('assignment-import-fields').disabled = !assignmentEditable();
  $('assignment-mode').value = config.mode;
  $('assignment-limit').value = config.max_delegations;
  $('assignment-delegation').checked = config.delegation_enabled;
  $('assignment-rows').replaceChildren();
  for (const item of config.agents) {
    const profile = assignmentProfiles.find(p => p.agent_id === item.agent_id);
    const row = block($('assignment-rows'), 'source', `${profile?.name || item.agent_id} · ${item.agent_id} · ${profile?.role || '등록 정보 없음'}\n${profile?.enabled && profile?.available ? '공통 Agent 활성' : '공통 Agent 비활성 또는 사용 불가'}`);
    row.dataset.agentId = item.agent_id;
    const field = (labelText, property, type, limit) => {
      const label = document.createElement('label'); label.append(document.createTextNode(labelText));
      const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
      input.dataset.field = property;
      if (type === 'checkbox') { input.type = type; input.checked = item[property]; }
      else { input.value = item[property]; input.maxLength = limit; if (type === 'textarea') input.rows = 3; }
      input.addEventListener('input', () => {
        item[property] = type === 'checkbox' ? input.checked : input.value;
        assignmentChanged();
        if (property === 'enabled') refreshAssignmentChoices();
      });
      label.append(input); row.append(label);
    };
    field('이 프로젝트에서 사용', 'enabled', 'checkbox');
    field('자동 위임 대상으로 사용', 'allow_delegation', 'checkbox');
    field('프로젝트 내 역할', 'assignment', 'text', 120);
    field('프로젝트 추가 지침', 'instructions', 'textarea', 4000);
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '배정 해제';
    remove.addEventListener('click', () => {
      config.agents = config.agents.filter(a => a !== item);
      if (config.default_agent_id === item.agent_id) config.default_agent_id = '';
      assignmentChanged(); renderAssignments();
    }); row.append(remove);
  }
  if (!config.agents.length) block($('assignment-rows'), 'muted', '배정된 Agent가 없습니다.');
  refreshAssignmentChoices();
}
async function loadAssignments(force = false) {
  const scope = currentProject;
  if (!scope || assignmentSaving) return;
  // Polls and global refresh must not overwrite a local draft.
  if (!force && (assignmentDirty || $('assignment-import-text').value.trim()) && assignmentState?.project_id === scope) { renderAssignments(); return; }
  clearAssignmentPreview();
  $('assignment-import-text').value = ''; $('assignment-import-file').value = '';
  $('assignment-export').hidden = true; $('assignment-import-fields').disabled = true;
  const request = ++assignmentLoad;
  $('assignment-fields').disabled = true;
  text('assignment-error', ''); text('assignment-status', '배정 설정을 불러오는 중입니다.');
  try {
    const [state, profiles] = await Promise.all([api(`/v1/projects/${encodeURIComponent(scope)}/agent-assignments`), api('/v1/agents')]);
    if (scope !== currentProject || request !== assignmentLoad) return;
    assignmentState = state; assignmentProfiles = profiles; assignmentDirty = false;
    $('assignment-export').href = `/v1/projects/${encodeURIComponent(scope)}/agent-assignments/export`;
    $('assignment-export').hidden = false;
    text('assignment-status', `설정 v${state.version} · ${state.execution_mode === 'project' ? '프로젝트 배정으로 실행' : '기존 방식으로 실행'}${manageAgents ? '' : ' · Agent 관리 연결이 없어 읽기 전용'}${projects.find(p => p.project_id === scope)?.status === 'archived' ? ' · 보관 프로젝트: 읽기 전용' : ''}`);
    text('assignment-error', state.validation_issues.join('\n'));
    renderAssignments();
  } catch (error) {
    if (scope !== currentProject || request !== assignmentLoad) return;
    assignmentState = null; $('assignment-rows').replaceChildren();
    text('assignment-status', '배정 설정을 불러오지 못했습니다.'); text('assignment-error', error.message);
  }
}
$('assignment-add').addEventListener('click', () => {
  if (!assignmentEditable()) return;
  const profile = assignmentProfiles.find(p => p.agent_id === $('assignment-candidate').value);
  if (!profile || assignmentState.configuration.agents.some(a => a.agent_id === profile.agent_id)) return;
  assignmentState.configuration.agents.push({agent_id:profile.agent_id, assignment:'', instructions:'', enabled:!!profile.enabled, allow_delegation:true});
  assignmentChanged(); renderAssignments();
});
for (const [id, property] of [['assignment-mode','mode'], ['assignment-default','default_agent_id'], ['assignment-limit','max_delegations'], ['assignment-delegation','delegation_enabled']]) {
  $(id).addEventListener('input', () => {
    if (!assignmentEditable()) return;
    assignmentState.configuration[property] = id === 'assignment-limit' ? Number($(id).value) : id === 'assignment-delegation' ? $(id).checked : $(id).value;
    assignmentChanged();
  });
}
$('assignment-reload').addEventListener('click', () => {
  if (assignmentSaving || (assignmentDirty && !confirm('편집 중인 변경을 버리고 저장된 설정을 불러올까요?'))) return;
  loadAssignments(true);
});
$('assignment-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!assignmentEditable()) return;
  const scope = currentProject;
  clearAssignmentPreview();
  const payload = JSON.stringify({version:assignmentState.version, configuration:assignmentState.configuration});
  assignmentSaving = true; $('assignment-import-fields').disabled = true; $('assignment-fields').disabled = true; $('assignment-reload').disabled = true;
  text('assignment-error', '');
  try {
    const saved = await api(`/v1/projects/${encodeURIComponent(scope)}/agent-assignments`, {method:'PUT', body:payload});
    if (scope !== currentProject) return;
    assignmentState = saved; assignmentDirty = false;
    text('assignment-status', `설정 v${saved.version} 저장 완료 · ${saved.execution_mode === 'project' ? '다음 업무 시작부터 프로젝트 배정 적용' : '기존 방식으로 실행'}`);
  } catch (error) {
    if (scope === currentProject) text('assignment-error', `${error.message}\n입력 내용은 유지했습니다. 충돌 시 저장된 설정을 다시 불러온 뒤 수정하세요.`);
  } finally {
    assignmentSaving = false; $('assignment-reload').disabled = false;
    if (scope === currentProject && assignmentState) renderAssignments();
  }
});
window.addEventListener('beforeunload', event => {
  if (assignmentDirty || assignmentSaving || $('assignment-import-text').value.trim()) { event.preventDefault(); event.returnValue = ''; }
});

function clearAssignmentPreview() {
  assignmentPreview = null; assignmentPreviewRequest++;
  $('assignment-diff').replaceChildren(); text('assignment-import-message', '');
  $('assignment-apply-import').disabled = true;
}
$('assignment-import-text').addEventListener('input', clearAssignmentPreview);
$('assignment-import-file').addEventListener('change', async () => {
  clearAssignmentPreview();
  const request = assignmentPreviewRequest, scope = currentProject;
  const file = $('assignment-import-file').files[0];
  $('assignment-import-text').value = '';
  if (!file) return;
  if (file.size > 1048576) { text('assignment-import-message', 'JSON 파일은 최대 1 MiB입니다.'); return; }
  try {
    const content = await file.text();
    if (scope !== currentProject || request !== assignmentPreviewRequest) return;
    $('assignment-import-text').value = content;
  } catch { text('assignment-import-message', '파일을 읽을 수 없습니다.'); }
});
$('assignment-preview').addEventListener('click', async () => {
  if (!assignmentEditable()) return;
  if (assignmentDirty && !confirm('가져오기는 저장된 설정과 비교하며, 적용하면 현재 편집 내용을 교체합니다. 계속할까요?')) return;
  clearAssignmentPreview();
  const request = assignmentPreviewRequest, scope = currentProject;
  try {
    const raw = $('assignment-import-text').value.replace(/^\uFEFF/, '');
    if (new TextEncoder().encode(raw).length > 1048576) throw new Error('JSON은 최대 1 MiB입니다.');
    const document = JSON.parse(raw);
    const result = await api(`/v1/projects/${encodeURIComponent(scope)}/agent-assignments/import-preview`,
      {method:'POST', body:JSON.stringify({version:assignmentState.version, document})});
    if (scope !== currentProject || request !== assignmentPreviewRequest) return;
    assignmentPreview = result;
    const labels = {mode:'배정 방식', default_agent_id:'기본 담당', delegation_enabled:'추가 위임 허용', max_delegations:'최대 추가 위임 횟수'};
    for (const change of result.changes) {
      block($('assignment-diff'), 'source', `${labels[change.field] || change.field}\n현재: ${JSON.stringify(change.before, null, 2)}\n가져오기: ${JSON.stringify(change.after, null, 2)}`);
    }
    text('assignment-import-message', result.validation_issues.length ? result.validation_issues.join('\n') : result.changes.length ? '변경 내용을 확인한 뒤 적용하세요. 아직 저장하지 않았습니다.' : '저장된 설정과 같습니다. 적용할 변경이 없습니다.');
    $('assignment-apply-import').disabled = !result.can_apply;
  } catch (error) {
    if (scope === currentProject && request === assignmentPreviewRequest) text('assignment-import-message', error instanceof SyntaxError ? '올바른 JSON을 입력하세요.' : error.message);
  }
});
$('assignment-apply-import').addEventListener('click', async () => {
  if (!assignmentEditable() || !assignmentPreview?.can_apply || assignmentPreview.project_id !== currentProject) return;
  const preview = assignmentPreview, scope = currentProject;
  if (!confirm('확인한 JSON 설정으로 이 프로젝트의 저장된 배정을 교체할까요?')) return;
  assignmentSaving = true; $('assignment-fields').disabled = true; $('assignment-import-fields').disabled = true; $('assignment-reload').disabled = true;
  try {
    const saved = await api(`/v1/projects/${encodeURIComponent(scope)}/agent-assignments`,
      {method:'PUT', body:JSON.stringify({version:preview.version, configuration:preview.configuration})});
    if (scope !== currentProject) return;
    assignmentState = saved; assignmentDirty = false;
    clearAssignmentPreview();
    $('assignment-import-text').value = ''; $('assignment-import-file').value = '';
    text('assignment-status', `설정 v${saved.version} 가져오기 완료 · 다음 업무 시작부터 적용`);
    text('assignment-error', ''); text('assignment-import-message', '가져온 설정을 저장했습니다.');
  } catch (error) {
    if (scope === currentProject) {
      clearAssignmentPreview();
      text('assignment-import-message', `${error.message}\nJSON 입력은 유지했습니다. 최신 상태를 확인하고 다시 비교하세요.`);
    }
  } finally {
    assignmentSaving = false; $('assignment-reload').disabled = false;
    if (scope === currentProject && assignmentState) renderAssignments();
  }
});

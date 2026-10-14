import json
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_equipment_poc.projects import ProjectStore, ProjectConflict, ProjectMissing
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, SingleOrchestrator, MarkdownArtifactStore
from hermes_equipment_poc.web_service import create_app
from test_single_orchestrator import FakeChat, FakeRag

KEY = 'project-test-key-at-least-sixteen'
SOURCE = {'source_id': 'S1', 'source_type': 'document', 'record_id': 'manual', 'text': 'Review the requirements.'}


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'workspace').mkdir()
        self.store = AgentOrchestraStateStore(self.root / 'state.db')
        self.store.create_workspace('W', name='Projects', domain_id='document', root_path=str(self.root / 'workspace'))
        self.rag, self.chat = FakeRag([SOURCE]), FakeChat('검토 결과 [S1].')
        self.engine = SingleOrchestrator(self.store, self.rag, self.chat, domain_id='document',
                                         artifact_store=MarkdownArtifactStore(self.root / 'artifacts'))
        self.app = create_app(self.engine, 'W', openai_api_key=KEY)
        self.client = self.enterContext(TestClient(self.app, base_url='http://localhost'))
        self.headers = {'X-AO-Request': '1'}

    def project(self, project_id='alpha', **fields):
        response = self.client.post('/v1/projects', headers=self.headers, json={'project_id': project_id, 'name': project_id, **fields})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def note(self, project_id='alpha', **fields):
        response = self.client.post(f'/v1/projects/{project_id}/memory', headers=self.headers,
                                    json={'kind': 'decision', 'content': '검수는 내부 시험 후 진행', **fields})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def submit(self, project_id='alpha', **fields):
        response = self.client.post('/v1/tasks', headers=self.headers,
                                    json={'objective': '문서 검토', 'project_id': project_id, **fields})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()['task_id']

    def done(self, task_id):
        for _ in range(200):
            data = self.client.get('/v1/tasks/' + task_id).json()
            if data['submission_status'] in {'completed', 'failed'}:
                return data
            time.sleep(.01)
        self.fail('worker timeout')

    def test_generic_project_persistence_versions_archive_and_reopen(self):
        p = self.project(name='구매 절차 검토', description='설비 외 일반 프로젝트')
        updated = self.client.put('/v1/projects/alpha', headers=self.headers,
                                 json={'name': p['name'], 'version': 1, 'status': 'archived'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.put('/v1/projects/alpha', headers=self.headers,
                                        json={'name': 'stale', 'version': 1}).status_code, 409)
        self.assertEqual(self.client.post('/v1/tasks', headers=self.headers,
                                         json={'objective': '문서', 'project_id': 'alpha'}).status_code, 409)
        self.assertEqual(self.client.post('/v1/projects/alpha/memory', headers=self.headers,
                                         json={'kind': 'decision', 'content': 'test'}).status_code, 409)
        self.client.put('/v1/projects/alpha', headers=self.headers, json={'name': p['name'], 'version': 2})
        data = self.done(self.submit())
        self.assertEqual(data['status'], 'completed')
        worker = self.app.state.worker
        worker.close(); worker.start()
        self.assertEqual(self.client.get('/v1/projects/alpha').json()['version'], 3)
        self.assertEqual(self.client.get('/v1/tasks/' + data['task_id']).json()['project_id'], 'alpha')

    def test_scope_filters_and_memory_reach_model_with_snapshot(self):
        self.project(subject_id='Procurement', knowledge_project='采购', repository='DocsRepo')
        note = self.note()
        data = self.done(self.submit(create_artifact=True))
        self.assertEqual(data['subject_id'], 'Procurement')
        call = self.rag.calls[0]
        self.assertEqual(call['document_filters'], {'equipment': None, 'project': '采购'})
        self.assertEqual(call['code_filters'], {'equipment': None, 'repository': 'DocsRepo'})
        self.assertIn(note['content'], self.chat.calls[0]['messages'][1]['content'])
        self.assertIn('only user_confirmed', self.chat.calls[0]['messages'][1]['content'])
        self.assertEqual(json.loads(data['project_memory'])[1]['note_id'], note['note_id'])
        self.assertEqual(self.client.get(data['artifacts'][0]['download_url']).status_code, 200)
        with closing(self.store._connect()) as db:
            requests = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM checkpoints WHERE task_id=?', (data['task_id'],))]
        saved = next(row['request'] for row in requests if row['phase'] == 'request_saved')
        self.assertEqual(saved['project_memory'], data['project_memory'])

    def test_subject_conflict_missing_project_and_unknown_fields(self):
        self.project(subject_id='P')
        for payload, status in [({'project_id': 'missing'}, 404), ({'project_id': 'alpha', 'subject_id': 'Other'}, 422),
                                ({'project_id': 'alpha', 'project_memory': 'injected'}, 422)]:
            self.assertEqual(self.client.post('/v1/tasks', headers=self.headers,
                                             json={'objective': '文書', **payload}).status_code, status)
        for payload in [{'project_id': 'bad/id', 'name': 'x'}, {'project_id': 'b', 'name': ' '},
                        {'project_id': 'b', 'name': 'b', 'root_path': '/private'}]:
            self.assertEqual(self.client.post('/v1/projects', headers=self.headers, json=payload).status_code, 422)
        self.assertEqual(self.client.post('/v1/projects', headers=self.headers, json={'project_id': 'alpha', 'name': 'x'}).status_code, 409)

    def test_project_task_and_memory_isolation(self):
        self.project('alpha'); self.project('beta')
        self.note('alpha', content='ALPHA PRIVATE DECISION')
        first = self.done(self.submit('alpha'))
        second = self.done(self.submit('beta'))
        self.assertNotIn('ALPHA PRIVATE', second['project_memory'])
        self.assertNotIn(first['task_id'], second['project_memory'])
        self.assertEqual([row['task_id'] for row in self.client.get('/v1/tasks?project_id=beta').json()], [second['task_id']])
        self.assertEqual(self.client.get('/v1/tasks?project_id=missing').status_code, 404)
        response = self.client.post('/v1/tasks', headers=self.headers, json={'objective': '더 설명', 'project_id': 'beta', 'source_task_id': first['task_id']})
        self.assertEqual(response.status_code, 404)
        response = self.client.post('/v1/projects/beta/memory', headers=self.headers,
                                    json={'kind': 'decision', 'content': 'bad reference', 'source_task_id': first['task_id']})
        self.assertEqual(response.status_code, 404)

    def test_related_completed_results_are_unconfirmed_and_explicit_followup(self):
        self.project()
        first = self.done(self.submit(objective='구매절차 문서 검토'))
        second = self.done(self.submit(objective='구매절차 검토 추가'))
        memory = json.loads(second['project_memory'])
        prior = [entry for entry in memory if entry['kind'] == 'prior_result']
        self.assertEqual(prior[0]['task_id'], first['task_id'])
        self.assertEqual(prior[0]['confirmation'], 'unconfirmed_ai_output')
        self.assertNotIn('[S1]', prior[0]['content'])
        self.assertIn('historical reference: S1', prior[0]['content'])
        third = self.done(self.submit(objective='계속해줘', source_task_id=first['task_id']))
        self.assertIn(first['task_id'], third['project_memory'])
        self.assertIn('구매절차 문서 검토', self.rag.calls[-1]['query'])
        self.assertEqual(self.client.get('/v1/projects/alpha/memory').json(), [])
        self.assertEqual(self.store.get_task(third['task_id']).decisions, [])

    def test_disabled_memory_and_sessions_do_not_leak(self):
        self.project(); self.note()
        self.done(self.submit(session_id='same-label'))
        data = self.done(self.submit(use_memory=False, session_id='same-label'))
        self.assertEqual(data['project_memory'], '')
        self.assertNotIn('검수는 내부', self.chat.calls[-1]['messages'][1]['content'])
        self.assertNotEqual(self.chat.calls[0]['session_id'], self.chat.calls[1]['session_id'])
        response = self.client.post('/v1/tasks', headers=self.headers,
                                    json={'objective': 'x', 'source_task_id': data['task_id'], 'use_memory': False, 'project_id': 'alpha'})
        self.assertEqual(response.status_code, 422)

    def test_notes_edit_resolve_history_and_source(self):
        self.project()
        task = self.done(self.submit())
        note = self.note(source_task_id=task['task_id'])
        url = f"/v1/projects/alpha/memory/{note['note_id']}"
        payload = {'version': 1, 'kind': 'open_item', 'content': '試験 완료', 'status': 'resolved'}
        response = self.client.put(url, headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.put(url, headers=self.headers, json=payload).status_code, 409)
        data = self.done(self.submit())
        self.assertNotIn(note['note_id'], data['project_memory'])
        history = self.client.get('/v1/projects/alpha/history').json()
        self.assertIn('note_update', [event['action'] for event in history])
        self.assertIn('검수는 내부', json.dumps(history, ensure_ascii=False))

    def test_no_evidence_and_failed_tasks_are_not_memory(self):
        self.project()
        self.rag.sources = []
        empty = self.done(self.submit())
        self.rag.error = RuntimeError('private-key')
        failed = self.done(self.submit())
        self.rag.error = None; self.rag.sources = [SOURCE]
        result = self.done(self.submit())
        self.assertNotIn(empty['task_id'], result['project_memory'])
        self.assertNotIn(failed['task_id'], result['project_memory'])

    def test_snapshot_frozen_before_execution_and_later_note_edits(self):
        self.project(); note = self.note(content='Original decision')
        gate, release = threading.Event(), threading.Event()
        original = self.engine.run
        def delayed(request):
            gate.set(); release.wait(5)
            return original(request)
        self.engine.run = delayed
        try:
            task_id = self.submit()
            self.assertTrue(gate.wait(2))
            self.client.put(f"/v1/projects/alpha/memory/{note['note_id']}", headers=self.headers,
                            json={'version': 1, 'kind': 'decision', 'content': 'Changed decision'})
        finally:
            release.set()
        data = self.done(task_id)
        self.assertIn('Original decision', data['project_memory'])
        self.assertNotIn('Changed decision', data['project_memory'])

    def test_openwebui_project_models_route_without_custom_options(self):
        self.project(); self.note()
        auth = {'Authorization': 'Bearer ' + KEY}
        models = self.client.get('/v1/models', headers=auth).json()['data']
        model = 'ao/document/W/project/alpha/report'
        self.assertIn(model, [entry['id'] for entry in models])
        response = self.client.post('/v1/chat/completions', headers=auth,
                                    json={'model': model, 'messages': [{'role': 'user', 'content': '문서 검토'}]})
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()['ao']['task_id']
        self.assertEqual(self.client.get('/v1/tasks/' + task_id).json()['project_id'], 'alpha')
        self.assertIn('검수는 내부', self.chat.calls[-1]['messages'][1]['content'])
        response = self.client.post('/v1/chat/completions', headers=auth,
                                    json={'model': model, 'messages': [{'role': 'user', 'content': '文書'}], 'ao': {'project_id': 'beta'}})
        self.assertEqual(response.status_code, 400)
        self.client.put('/v1/projects/alpha', headers=self.headers, json={'name': 'alpha', 'version': 1, 'status': 'archived'})
        self.assertNotIn(model, [entry['id'] for entry in self.client.get('/v1/models', headers=auth).json()['data']])

    def test_schema_csrf_and_catalog_binding(self):
        self.assertEqual(self.client.post('/v1/projects', json={'project_id': 'a', 'name': 'a'}).status_code, 403)
        self.project()
        self.assertEqual(self.client.get('/v1/projects', headers={'Origin': 'http://evil'}).status_code, 403)
        path = self.app.state.worker.projects.path
        with self.assertRaises(ValueError):
            ProjectStore(path, 'Other', 'document')
        with self.assertRaises(ValueError):
            ProjectStore(path, 'W', 'equipment')

    def test_bounded_memory_keeps_full_records_outside_prompt(self):
        self.project(description='D' * 2000)
        for index in range(10):
            self.note(content=f'{index}' + 'N' * 999)
        data = self.done(self.submit())
        self.assertLessEqual(len(data['project_memory']), 12000)
        self.assertEqual(len(self.client.get('/v1/projects/alpha/memory').json()), 10)
        self.assertLessEqual(len(json.loads(data['project_memory'])), 7)

    def test_migration_preserves_existing_unassigned_tasks(self):
        data = self.done(self.submit(''))
        self.assertEqual(data['project_id'], '')
        self.assertEqual(data['project_memory'], '')
        self.project()
        assigned = self.done(self.submit())
        self.assertEqual(len(self.client.get('/v1/tasks').json()), 2)
        self.assertEqual([row['task_id'] for row in self.client.get('/v1/tasks?project_id=alpha').json()], [assigned['task_id']])

    def test_specialist_receives_project_memory(self):
        from hermes_equipment_poc.agent_manager import AgentManager, ManagedDispatcher
        from hermes_equipment_poc.orchestrator import SpecialistAgent
        from test_agent_management import Provider
        self.project(); self.note(content='SPECIALIST PROJECT DECISION')
        manager = AgentManager(self.root / 'agents.db', 'W', [{'role': 'document-agent', 'endpoint': 'synthetic'}], enabled=True)
        provider = Provider()
        self.engine.specialists = ManagedDispatcher(manager, {SpecialistAgent.DOCUMENT: provider}, 'document')
        data = self.done(self.submit())
        self.assertEqual(data['status'], 'completed')
        self.assertIn('SPECIALIST PROJECT DECISION', provider.calls[-1][1]['content'])

    def test_project_named_report_is_not_report_model(self):
        self.project('report')
        auth = {'Authorization': 'Bearer ' + KEY}
        response = self.client.post('/v1/chat/completions', headers=auth,
                                    json={'model': 'ao/document/W/project/report', 'messages': [{'role': 'user', 'content': '문서 검토'}]})
        self.assertEqual(response.status_code, 200)
        task_id = response.json()['ao']['task_id']
        self.assertEqual(self.client.get('/v1/tasks/' + task_id).json()['artifacts'], [])

    def test_old_web_journal_schema_migrates_without_losing_results(self):
        data = self.done(self.submit(''))
        worker = self.app.state.worker
        worker.close()
        with closing(worker.db()) as db, db:
            db.execute('DROP INDEX web_jobs_project')
            db.execute('ALTER TABLE web_jobs DROP COLUMN project_id')
        worker.start()
        restored = self.client.get('/v1/tasks/' + data['task_id']).json()
        self.assertEqual(restored['answer'], data['answer'])
        self.assertEqual(restored['project_id'], '')


if __name__ == '__main__':
    unittest.main()

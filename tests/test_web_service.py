from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from hermes_equipment_poc.orchestrator import (AgentOrchestraStateStore,
    MarkdownArtifactStore, SingleOrchestrator, TaskRecord, TaskStatus)
from test_phase4_workflows import FakeChat, FakeRag


@unittest.skipIf(TestClient is None, 'Install .[web,test] to run HTTP tests')
class WebServiceTests(unittest.TestCase):
    def setUp(self):
        from hermes_equipment_poc.web_service import create_app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        workspace = self.root / 'workspace'
        workspace.mkdir()
        self.store = AgentOrchestraStateStore(self.root / 'state.db')
        self.store.create_workspace('W', name='Test workspace', root_path=str(workspace))
        self.engine = SingleOrchestrator(self.store, FakeRag(), FakeChat(), artifact_store=MarkdownArtifactStore(self.root / 'artifacts'))
        self.app = create_app(self.engine, 'W', agents=[{'agent_id':'document-agent'}], health_checks={'document-agent': lambda: {}})
        self.client = TestClient(self.app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def submit(self, **kwargs):
        return self.client.post('/v1/tasks', json={'objective':'문서 분석', **kwargs}, headers={'X-AO-Request':'1'})

    def done(self, task_id):
        for _ in range(150):
            data = self.client.get('/v1/tasks/' + task_id).json()
            if data.get('submission_status') in {'completed', 'failed'}:
                return data
            time.sleep(.01)
        self.fail('worker timeout')

    def test_task_evidence_runs_and_verified_download(self):
        response = self.submit(create_artifact=True)
        self.assertEqual(response.status_code, 202)
        task_id = response.json()['task_id']
        data = self.done(task_id)
        self.assertEqual(data['status'], 'completed')
        self.assertIn('[D1]', data['answer'])
        self.assertEqual(data['delegation_mode'], 'direct')
        self.assertEqual(len(self.client.get(f'/v1/tasks/{task_id}/runs').json()), 1)
        self.assertEqual(len(self.client.get(f'/v1/tasks/{task_id}/evidence').json()), 1)
        download = self.client.get(data['artifacts'][0]['download_url'])
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment', download.headers['content-disposition'])

    def test_integrity_failure_rejected(self):
        data = self.done(self.submit(create_artifact=True).json()['task_id'])
        artifact = self.store.get_task(data['task_id']).artifacts[0]
        Path(artifact.path).write_text('tampered', encoding='utf-8')
        self.assertEqual(self.client.get(data['artifacts'][0]['download_url']).status_code, 409)

    def test_artifact_outside_root_rejected(self):
        from hermes_equipment_poc.orchestrator import ArtifactReference
        import hashlib
        self.store.create_task(TaskRecord('outside', 'W', 'test'))
        file = self.root / 'private.txt'
        file.write_text('private', encoding='utf-8')
        self.store.add_artifact('outside', ArtifactReference(str(file), 'report', hashlib.sha256(file.read_bytes()).hexdigest()))
        self.assertEqual(self.client.get('/v1/tasks/outside/artifacts/0').status_code, 409)

    def test_csrf_and_host_rejected(self):
        self.assertEqual(self.client.post('/v1/tasks', json={'objective':'test'}).status_code, 403)
        self.assertEqual(self.client.get('/v1/tasks', headers={'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/v1/tasks', headers={'Host':'evil.example'}).status_code, 400)

    def test_schema_and_large_body_rejected(self):
        for extra in ({'commit':True}, {'request_kind':'invalid'}, {'objective':' '}, {'create_artifact':'true'}, {'knowledge_scopes':['99']}):
            self.assertEqual(self.submit(**extra).status_code, 422)
        response = self.client.post('/v1/tasks', content='x'*65537, headers={'X-AO-Request':'1'})
        self.assertEqual(response.status_code, 413)

    def test_unknown_and_cross_workspace_hidden(self):
        self.store.create_workspace('Other', name='Other')
        self.store.create_task(TaskRecord('secret', 'Other', 'private'))
        for path in ['/v1/tasks/missing', '/v1/tasks/secret', '/v1/tasks/secret/runs', '/v1/tasks/secret/artifacts']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_agent_registry_readonly_and_health(self):
        self.assertEqual(self.client.get('/v1/agents').json()[0]['agent_id'], 'document-agent')
        self.assertEqual(self.client.get('/v1/agents/document-agent/health').json()['status'], 'reachable')
        self.assertEqual(self.client.get('/v1/agents/missing/health').status_code, 404)
        self.assertEqual(self.client.post('/v1/agents', json={}, headers={'X-AO-Request':'1'}).status_code, 405)

    def test_static_offline_and_no_mutation_routes(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        js = self.client.get('/assets/app.js')
        self.assertNotIn('innerHTML', js.text)
        self.assertIn("frame-ancestors 'none'", js.headers['content-security-policy'])
        for path in ['/v1/proposals', '/v1/commit', '/assets/private.txt']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_endpoint_error_is_sanitized(self):
        class BrokenRag:
            def retrieve(self, **kwargs):
                raise RuntimeError('secret-api-key')
        self.engine.rag = BrokenRag()
        data = self.done(self.submit().json()['task_id'])
        self.assertEqual(data['status'], 'failed')
        self.assertNotIn('secret-api-key', json.dumps(data))
        self.assertNotIn('secret-api-key', self.client.get(f"/v1/tasks/{data['task_id']}/runs").text)

    def test_queue_capacity_and_immediate_response(self):
        entered, release = threading.Event(), threading.Event()
        original = self.engine.run
        def delayed(request):
            entered.set()
            release.wait(5)
            return original(request)
        self.engine.run = delayed
        self.app.state.worker.capacity = 1
        try:
            first = self.submit()
            self.assertEqual(first.status_code, 202)
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.submit().status_code, 429)
        finally:
            release.set()
        self.done(first.json()['task_id'])

    def test_single_worker_lock(self):
        from hermes_equipment_poc.web_service import TaskWorker
        other = TaskWorker(self.engine, 'W', self.app.state.worker.path)
        with self.assertRaises(FileExistsError):
            other.start()

    def test_results_survive_restart(self):
        data = self.done(self.submit().json()['task_id'])
        worker = self.app.state.worker
        worker.close()
        worker.start()
        self.assertEqual(self.client.get('/v1/tasks/' + data['task_id']).json()['answer'], data['answer'])

    def test_no_evidence_reason_and_specialist_route(self):
        from test_specialist_delegation import FakeSpecialists
        self.engine.specialists = FakeSpecialists()
        data = self.done(self.submit(request_kind='troubleshooting').json()['task_id'])
        runs = self.client.get('/v1/tasks/' + data['task_id'] + '/runs').json()
        self.assertIn('troubleshooting-agent', [r['agent_name'] for r in runs])
        self.assertEqual(data['delegation_mode'], 'specialists')
        class EmptyRag:
            def retrieve(self, **kwargs):
                return {'sources': []}
        self.engine.rag = EmptyRag()
        data = self.done(self.submit(request_kind='troubleshooting').json()['task_id'])
        self.assertEqual(data['finish_reason'], 'no_evidence')
        self.assertEqual(len(self.client.get('/v1/tasks/' + data['task_id'] + '/runs').json()), 1)

    def test_cli_task_and_comparison_artifact_visible(self):
        self.store.create_task(TaskRecord('cli-proposal', 'W', 'CLI proposal'))
        artifact = self.engine.artifact_store.create_report(task_id='cli-proposal', title='Comparison', result='Build PASS\nDiff\n- before\n+ after\ncommitted=false', evidence=(), artifact_type='code_change_comparison')
        self.store.add_artifact('cli-proposal', artifact)
        data = self.client.get('/v1/tasks/cli-proposal').json()
        self.assertEqual(data['artifacts'][0]['artifact_type'], 'code_change_comparison')
        self.assertIn('committed=false', self.client.get(data['artifacts'][0]['download_url']).text)
        self.assertIn('cli-proposal', [t['task_id'] for t in self.client.get('/v1/tasks').json()])

    def test_interrupted_submission_not_replayed(self):
        worker = self.app.state.worker
        worker.close()
        with closing(worker.db()) as db, db:
            db.execute("INSERT INTO web_jobs(id,request,status) VALUES(?,?,'queued')", ('interrupted', json.dumps({'objective':'test', 'session_id':''})))
        worker.start()
        data = self.client.get('/v1/tasks/interrupted').json()
        self.assertEqual(data['status'], 'interrupted')
        self.assertEqual(self.store.list_tasks('W'), [])

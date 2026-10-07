import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_equipment_poc.agent_manager import AgentManager, ManagedDispatcher, AgentConflict, AgentMissing
from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore, SingleOrchestrator, OrchestratorRequest,
    OrchestratorExecutionError, SpecialistAgent, ChatCompletionResult,
)
from hermes_equipment_poc.web_service import create_app
from test_single_orchestrator import FakeRag, FakeChat

ROLE = 'document-agent'
TEMPLATES = [{'role': ROLE, 'endpoint': 'http://127.0.0.1:8642'}]
SOURCE = {'source_id': 'S1', 'record_id': 'doc-1', 'source_type': 'document', 'text': 'Check input.'}


class Provider:
    def __init__(self):
        self.calls = []
        self.fail = False

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError('private-token-not-for-API')
        citation = 'TEST1' if 'Synthetic' in messages[1]['content'] or 'synthetic' in messages[1]['content'] else 'S1'
        return ChatCompletionResult(f'확인 결과 [{citation}].', model='fake')


class AgentManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = AgentManager(self.root / 'agents.db', 'W', TEMPLATES, enabled=True)
        self.provider = Provider()
        self.dispatcher = ManagedDispatcher(self.manager, {SpecialistAgent.DOCUMENT: self.provider}, 'document')
        self.store = AgentOrchestraStateStore(self.root / 'state.db')
        self.store.create_workspace('W', name='Docs', domain_id='document')
        self.rag = FakeRag([SOURCE])
        self.engine = SingleOrchestrator(self.store, self.rag, FakeChat(), domain_id='document', specialists=self.dispatcher)

    def create(self):
        return self.manager.create('reviewer', '문서 검토자', ROLE, '검토 순서를 표로 제시해주세요.')

    def activate(self):
        profile = self.create()
        tested = self.manager.test(profile['agent_id'], profile['version'], self.dispatcher)
        self.assertEqual(tested['test_status'], 'passed')
        return self.manager.set_enabled(tested['agent_id'], tested['version'], True)

    def test_create_requires_test_and_activation_replaces_role(self):
        profile = self.create()
        self.assertFalse(profile['enabled'])
        with self.assertRaises(AgentConflict):
            self.manager.set_enabled('reviewer', 1, True)
        self.manager.test('reviewer', 1, self.dispatcher)
        active = self.manager.set_enabled('reviewer', 1, True)
        self.assertTrue(active['enabled'])
        self.assertEqual([p['agent_id'] for p in self.manager.list() if p['enabled']], ['reviewer'])

    def test_runtime_instructions_and_version_are_saved_with_task(self):
        profile = self.activate()
        result = self.engine.run(OrchestratorRequest('W', '문서 검토'))
        self.assertEqual(result.delegations[0].agent_id, 'reviewer')
        self.assertEqual(result.delegations[0].agent_version, profile['version'])
        self.assertIn('검토 순서를 표로', self.provider.calls[-1][1]['content'])
        self.assertIn('Execution permission: analysis', self.provider.calls[-1][1]['content'])
        checkpoint = self.store.latest_checkpoint(result.task_id)['payload']
        self.assertEqual(checkpoint['agent_profiles'][0]['agent_id'], 'reviewer')
        with closing(self.store._connect()) as db:
            rows = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM checkpoints WHERE task_id=?', (result.task_id,))]
        snapshot = next(row for row in rows if row['phase'] == 'agent_configuration')
        self.assertEqual(snapshot['agents'][0]['version'], profile['version'])

    def test_edit_disables_and_invalidates_test_and_stale_write(self):
        profile = self.activate()
        updated = self.manager.update('reviewer', profile['version'], '수정본', ROLE, 'new prompt')
        self.assertFalse(updated['enabled'])
        self.assertIsNone(updated['tested_version'])
        with self.assertRaises(AgentConflict):
            self.manager.update('reviewer', profile['version'], '오래된 편집', ROLE, '')
        with self.assertRaises(AgentConflict):
            self.manager.set_enabled('reviewer', updated['version'], True)

    def test_delete_preserves_history_and_prevents_id_reuse(self):
        profile = self.activate()
        with self.assertRaises(AgentConflict):
            self.manager.delete('reviewer', profile['version'])
        disabled = self.manager.set_enabled('reviewer', profile['version'], False)
        self.manager.delete('reviewer', disabled['version'])
        self.assertNotIn('reviewer', [p['agent_id'] for p in self.manager.list()])
        self.assertEqual(self.manager.history('reviewer')[0]['action'], 'delete')
        with self.assertRaises(AgentConflict):
            self.create()

    def test_restart_preserves_disabled_and_deleted_default(self):
        self.manager.set_enabled(ROLE, 1, False)
        self.manager.delete(ROLE, 2)
        again = AgentManager(self.root / 'agents.db', 'W', TEMPLATES, enabled=True)
        self.assertEqual(again.list(), [])

    def test_endpoint_change_requires_retest(self):
        self.activate()
        again = AgentManager(self.root / 'agents.db', 'W', [{'role': ROLE, 'endpoint': 'http://127.0.0.1:9000'}], enabled=True)
        self.assertFalse(any(p['enabled'] for p in again.list()))
        self.assertEqual(again.history('reviewer')[0]['action'], 'endpoint_changed')

    def test_failed_trial_sanitized_and_disables_profile(self):
        profile = self.activate()
        self.provider.fail = True
        result = self.manager.test('reviewer', profile['version'], self.dispatcher)
        self.assertEqual(result['test_status'], 'failed')
        self.assertFalse(result['enabled'])
        self.assertNotIn('private-token', json.dumps(self.manager.history('reviewer')))

    def test_mutation_is_rejected_during_execution(self):
        entered, release = threading.Event(), threading.Event()
        def hold():
            with self.dispatcher.execution_scope():
                entered.set()
                release.wait(5)
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(AgentConflict):
                self.create()
        finally:
            release.set()
            thread.join(2)

    def test_missing_enabled_role_fails_without_fallback(self):
        self.manager.set_enabled(ROLE, 1, False)
        with self.assertRaises(OrchestratorExecutionError):
            self.engine.run(OrchestratorRequest('W', '문서 검토'))
        self.assertEqual(self.provider.calls, [])

    def test_workspace_binding_and_role_validation(self):
        with self.assertRaises(ValueError):
            AgentManager(self.root / 'agents.db', 'other', TEMPLATES)
        with self.assertRaises(ValueError):
            self.manager.create('code', 'code', 'code-development-agent')

    def test_api_rejects_manager_from_different_workspace(self):
        other = AgentManager(self.root / 'other-agents.db', 'other', TEMPLATES)
        dispatcher = ManagedDispatcher(other, {SpecialistAgent.DOCUMENT: self.provider}, 'document')
        with self.assertRaises(ValueError):
            create_app(self.engine, 'W', agent_manager=other, managed_dispatcher=dispatcher)

    def test_api_crud_trial_and_csrf(self):
        app = create_app(self.engine, 'W', agent_manager=self.manager, managed_dispatcher=self.dispatcher)
        with TestClient(app, base_url='http://localhost') as client:
            headers = {'X-AO-Request': '1'}
            payload = {'agent_id': 'api-doc', 'name': '검토자', 'role': ROLE, 'instructions': '간결히'}
            self.assertEqual(client.post('/v1/agents', json=payload).status_code, 403)
            self.assertEqual(client.post('/v1/agents', headers=headers, json={**payload, 'api_key': 'secret'}).status_code, 422)
            self.assertEqual(client.post('/v1/agents', headers=headers, json=payload).status_code, 201)
            trial = client.post('/v1/agents/api-doc/test', headers=headers, json={'version': 1})
            self.assertEqual(trial.json()['test_status'], 'passed')
            active = client.post('/v1/agents/api-doc/enabled', headers=headers, json={'version': 1, 'enabled': True})
            self.assertEqual(active.status_code, 200)
            self.assertTrue(active.json()['enabled'])
            self.assertEqual(client.put('/v1/agents/api-doc', headers=headers, json={'version': 1, 'name': 'stale', 'role': ROLE}).status_code, 409)
            self.assertEqual(client.delete('/v1/agents/api-doc?version=2', headers=headers).status_code, 409)
            client.post('/v1/agents/api-doc/enabled', headers=headers, json={'version': 2, 'enabled': False})
            self.assertEqual(client.delete('/v1/agents/api-doc?version=3', headers=headers).status_code, 204)
            self.assertEqual(client.get('/v1/agents/api-doc/history').json()[0]['action'], 'delete')
            self.assertTrue(client.get('/v1/workspace').json()['agent_management_enabled'])

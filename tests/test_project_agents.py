import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient
from hermes_equipment_poc.agent_manager import AgentManager, ManagedDispatcher
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, SingleOrchestrator, SpecialistAgent
from hermes_equipment_poc.projects import ProjectStore
from hermes_equipment_poc.web_service import create_app
from test_agent_management import TEMPLATES, Provider
from test_single_orchestrator import FakeChat, FakeRag


class ProjectAgentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.manager = AgentManager(self.root / 'agents.db', 'W', TEMPLATES, enabled=True)
        dispatcher = ManagedDispatcher(self.manager, {SpecialistAgent.DOCUMENT: Provider()}, 'document')
        store = AgentOrchestraStateStore(self.root / 'state.db')
        store.create_workspace('W', name='W', domain_id='document')
        engine = SingleOrchestrator(store, FakeRag(), FakeChat(), domain_id='document', specialists=dispatcher)
        self.app = create_app(engine, 'W', agent_manager=self.manager, managed_dispatcher=dispatcher)
        self.client = self.enterContext(TestClient(self.app, base_url='http://localhost'))
        self.headers = {'X-AO-Request':'1'}
        for identity in ('alpha', 'beta'):
            self.client.post('/v1/projects', headers=self.headers, json={'project_id':identity, 'name':identity})
        self.path = '/v1/projects/alpha/agent-assignments'
        self.config = {'mode':'custom', 'default_agent_id':'document-agent', 'agents':[
            {'agent_id':'document-agent', 'assignment':'문서 검토', 'instructions':'근거를 확인한다.'}]}

    def save(self, config=None, version=0):
        return self.client.put(self.path, headers=self.headers, json={'version':version, 'configuration':config or self.config})

    def test_persist_isolate_history_and_legacy_execution_status(self):
        initial = self.client.get(self.path).json()
        self.assertEqual(initial['version'], 0)
        self.assertEqual(initial['configuration']['mode'], 'legacy')
        result = self.save()
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertTrue(data['runtime_applied'])
        self.assertEqual(data['execution_mode'], 'project')
        reopened = ProjectStore(self.app.state.worker.projects.path, 'W', 'document')
        self.assertEqual(reopened.agent_assignments('alpha')['configuration'], data['configuration'])
        self.assertEqual(self.client.get('/v1/projects/beta/agent-assignments').json()['version'], 0)
        history = self.client.get('/v1/projects/alpha/history').json()
        self.assertIn('agent_assignments_update', str(history))
        self.assertNotIn('http://', json.dumps(data))
        self.assertEqual(self.save().status_code, 409)

    def test_invalid_config_is_atomic_and_strict(self):
        bad = [dict(self.config, default_agent_id='missing'),
               dict(self.config, agents=[{'agent_id':'missing'}]),
               dict(self.config, agents=self.config['agents'] * 2),
               dict(self.config, endpoint='http://injected'),
               dict(self.config, max_delegations=True),
               dict(self.config, schema_version=True),
               dict(self.config, max_delegations=0),
               dict(self.config, agents=[{'agent_id':'document-agent', 'enabled':False}])]
        for config in bad:
            self.assertEqual(self.save(config).status_code, 422, config)
        self.assertEqual(self.client.get(self.path).json()['version'], 0)

    def test_registry_changes_report_stale_assignments_without_replacement(self):
        self.assertEqual(self.save().status_code, 200)
        self.manager.set_enabled('document-agent', 1, False)
        data = self.client.get(self.path).json()
        self.assertTrue(data['validation_issues'])
        self.assertEqual(data['configuration']['default_agent_id'], 'document-agent')
        self.assertEqual(self.save(version=1).status_code, 422)
        self.manager.delete('document-agent', 2)
        self.assertIn('Agent not found', str(self.client.get(self.path).json()['validation_issues']))

    def test_csrf_missing_and_archived_project(self):
        self.assertEqual(self.client.put(self.path, json={'version':0, 'configuration':self.config}).status_code, 403)
        self.assertEqual(self.client.get('/v1/projects/missing/agent-assignments').status_code, 404)
        project = self.app.state.worker.projects.get('alpha')
        self.app.state.worker.projects.update('alpha', project['version'], name='Alpha', status='archived')
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.client.get(self.path).status_code, 200)

    def test_schema_one_upgrade_keeps_project_and_closes_connections(self):
        path = self.root / 'legacy.db'
        original = ProjectStore(path, 'W', 'document')
        original.create('legacy', name='Legacy')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('DROP TABLE agent_assignments')
            db.execute('PRAGMA user_version=1')
        restored = ProjectStore(path, 'W', 'document')
        self.assertEqual(restored.get('legacy')['name'], 'Legacy')
        self.assertEqual(restored.agent_assignments('legacy')['version'], 0)
        path.unlink()  # Windows requires every connection to be explicitly closed.


if __name__ == '__main__':
    unittest.main()

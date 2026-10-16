import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from hermes_equipment_poc.agent_manager import AgentManager, ManagedDispatcher
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, SingleOrchestrator, SpecialistAgent, OrchestratorRequest
from hermes_equipment_poc.project_runtime import prepare_project_execution, ProjectExecutionError, ProjectPlanner
from hermes_equipment_poc.web_service import create_app
from test_agent_management import Provider, SOURCE
from test_single_orchestrator import FakeChat, FakeRag


class ProjectRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.manager = AgentManager(self.root/'agents.db', 'W',
            [{'role':role.value, 'endpoint':'fixture'} for role in SpecialistAgent], enabled=True)
        self.provider = Provider()
        self.dispatcher = ManagedDispatcher(self.manager, {role:self.provider for role in SpecialistAgent}, 'equipment')
        self.store = AgentOrchestraStateStore(self.root/'state.db')
        self.store.create_workspace('W', name='W')
        self.rag, self.chat = FakeRag([SOURCE]), FakeChat()
        self.engine = SingleOrchestrator(self.store, self.rag, self.chat, specialists=self.dispatcher)
        self.app = create_app(self.engine, 'W', agent_manager=self.manager, managed_dispatcher=self.dispatcher, openai_api_key='test-key-project-runtime-123')
        self.client = self.enterContext(TestClient(self.app, base_url='http://localhost'))
        self.projects = self.app.state.worker.projects
        self.headers = {'X-AO-Request':'1'}
        for name in ('alpha', 'beta'):
            self.projects.create(name, name=name)

    def config(self, identity='document-agent', guidance='alpha guidance'):
        return dict(schema_version=1, mode='custom', default_agent_id=identity,
                    agents=[dict(agent_id=identity, enabled=True, allow_delegation=True, assignment='review', instructions=guidance)],
                    delegation_enabled=True, max_delegations=4)

    def submit(self, project='alpha', kind='document_task'):
        response = self.client.post('/v1/tasks', headers=self.headers,
            json={'project_id':project, 'objective':'Review document', 'request_kind':kind})
        self.assertEqual(response.status_code, 202, response.text)
        identity = response.json()['task_id']
        for _ in range(200):
            task = self.client.get('/v1/tasks/'+identity).json()
            if task['submission_status'] in ('completed','failed'):
                return task
            time.sleep(.01)
        self.fail('Task did not complete')

    def add_project_profile(self):
        self.manager.create('reviewer', 'Reviewer', 'document-agent', 'shared guidance')
        self.manager.test('reviewer', 1, self.dispatcher)
        return self.manager.set_enabled('reviewer', 1, True, make_default=False)

    def test_two_projects_use_different_profiles_and_legacy_default_survives(self):
        self.add_project_profile()
        self.projects.save_agent_assignments('alpha', 0, self.config('reviewer'))
        self.projects.save_agent_assignments('beta', 0, self.config(guidance='beta guidance'))
        alpha, beta = self.submit(), self.submit('beta')
        self.assertEqual(alpha['submission_status'], 'completed', alpha)
        self.assertEqual(beta['submission_status'], 'completed', beta)
        self.assertEqual(alpha['agent_profiles'][0]['agent_id'], 'reviewer')
        self.assertEqual(beta['agent_profiles'][0]['agent_id'], 'document-agent')
        self.assertEqual(alpha['agent_assignment']['version'], 1)
        self.assertEqual(alpha['delegation_mode'], 'project')
        self.assertNotIn('endpoint', json.dumps(alpha['agent_assignment']))
        self.assertIn('alpha guidance', str(self.provider.calls))
        self.assertIn('beta guidance', str(self.provider.calls))
        legacy = self.engine.run(OrchestratorRequest('W', '문서 검토'))
        self.assertEqual(legacy.delegations[0].agent_id, 'document-agent')

    def test_snapshot_survives_profile_and_assignment_edits(self):
        profile = self.add_project_profile()
        self.projects.save_agent_assignments('alpha', 0, self.config('reviewer', 'original project instructions'))
        local, snapshot = prepare_project_execution(self.engine, self.projects, 'alpha')
        self.projects.save_agent_assignments('alpha', 1, self.config(guidance='new project instructions'))
        self.manager.update('reviewer', profile['version'], 'Changed', 'document-agent', 'new common instructions')
        result = local.run(OrchestratorRequest('W', '문서 검토'))
        self.assertEqual(result.delegations[0].agent_id, 'reviewer')
        self.assertEqual(snapshot['version'], 1)
        self.assertIn('original project instructions', str(self.provider.calls[-1]))
        self.assertNotIn('new common instructions', str(self.provider.calls[-1]))
        next_local, _ = prepare_project_execution(self.engine, self.projects, 'alpha')
        self.assertEqual(next_local.specialists.profiles[0]['agent_id'], 'document-agent')

    def test_disabled_profile_fails_without_fallback(self):
        profile = self.add_project_profile()
        self.projects.save_agent_assignments('alpha', 0, self.config('reviewer'))
        self.manager.set_enabled('reviewer', profile['version'], False)
        count = len(self.provider.calls)
        task = self.submit()
        self.assertEqual(task['submission_status'], 'failed', task)
        self.assertIn('disabled', task['error'])
        self.assertEqual(len(self.provider.calls), count)
        self.assertFalse(self.chat.calls)

    def test_no_evidence_and_general_question_do_not_bypass_project_policy(self):
        self.projects.save_agent_assignments('alpha', 0, self.config())
        task = self.submit(kind='question')
        self.assertEqual(task['agent_profiles'][0]['agent_id'], 'document-agent')
        self.rag.sources = []
        count = len(self.provider.calls)
        task = self.submit()
        self.assertEqual(task['finish_reason'], 'no_evidence')
        self.assertEqual(len(self.provider.calls), count)
        self.assertFalse(self.chat.calls)

    def test_delegation_allowlist_and_limit(self):
        config = self.config()
        for role in ('code-analysis-agent','troubleshooting-agent'):
            config['agents'].append(dict(agent_id=role, enabled=True, allow_delegation=True, assignment='', instructions=''))
        profiles = [p for p in self.manager.list() if p['agent_id'] in {a['agent_id'] for a in config['agents']}]
        from hermes_equipment_poc.orchestrator.models import EvidenceReference
        evidence = [EvidenceReference('S1','doc','document','x'), EvidenceReference('S2','code','code','x')]
        config['max_delegations'] = 1
        self.assertEqual(ProjectPlanner(config, profiles).plan('troubleshooting', evidence),
                         (SpecialistAgent.DOCUMENT, SpecialistAgent.CODE_ANALYSIS))
        config['agents'][1]['allow_delegation'] = False
        self.assertEqual(ProjectPlanner(config, profiles).plan('troubleshooting', evidence),
                         (SpecialistAgent.DOCUMENT, SpecialistAgent.TROUBLESHOOTING))
        config['delegation_enabled'] = False
        self.assertEqual(ProjectPlanner(config, profiles).plan('troubleshooting', evidence), (SpecialistAgent.DOCUMENT,))

    def test_legacy_mode_preserves_original_engine_and_archive_stops_start(self):
        local, snapshot = prepare_project_execution(self.engine, self.projects, 'alpha')
        self.assertIs(local, self.engine)
        self.assertFalse(snapshot['runtime_applied'])
        self.projects.update('alpha', 1, name='Alpha', status='archived')
        with self.assertRaises(ProjectExecutionError):
            prepare_project_execution(self.engine, self.projects, 'alpha')

    def test_actual_delegation_and_openwebui_use_project_configuration(self):
        config = self.config()
        config['agents'].append(dict(agent_id='troubleshooting-agent', enabled=True,
                                    allow_delegation=True, assignment='review', instructions='special review'))
        self.projects.save_agent_assignments('alpha', 0, config)
        task = self.submit(kind='troubleshooting')
        self.assertEqual(task['submission_status'], 'completed', task)
        self.assertEqual([p['agent_id'] for p in task['agent_profiles']], ['document-agent', 'troubleshooting-agent'])
        config['delegation_enabled'] = False
        self.projects.save_agent_assignments('alpha', 1, config)
        response = self.client.post('/v1/chat/completions', headers={'Authorization':'Bearer test-key-project-runtime-123'},
            json={'model':'ao/equipment/W/project/alpha', 'messages':[{'role':'user','content':'문서 검토'}]})
        self.assertEqual(response.status_code, 200, response.text)
        task = self.client.get('/v1/tasks/' + response.headers['X-AO-Task-ID']).json()
        self.assertEqual(task['agent_assignment']['version'], 2)
        self.assertEqual([p['agent_id'] for p in task['agent_profiles']], ['document-agent'])

    def test_incompatible_primary_evidence_has_explicit_error(self):
        self.projects.save_agent_assignments('alpha', 0, self.config('code-analysis-agent'))
        task = self.submit()
        self.assertEqual(task['submission_status'], 'failed', task)
        self.assertIn('검색 근거가 없습니다', task['error'])
        self.assertFalse(self.chat.calls)

import base64
import tempfile
import unittest
import urllib.error
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_equipment_poc.http_client import AdapterError
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, SingleOrchestrator
from hermes_equipment_poc.web_service import create_app
from test_single_orchestrator import FakeChat, FakeRag


class FakeMaterials:
    def __init__(self):
        self.calls = []
        self.failure = False

    def get(self, path):
        self.calls.append(('GET', path))
        return {'documents': []}

    def post(self, path, payload):
        self.calls.append(('POST', path, payload))
        if self.failure:
            try:
                raise urllib.error.HTTPError('http://private', 409, 'conflict', {}, None)
            except urllib.error.HTTPError as exc:
                raise AdapterError('private upstream error') from exc
        return {'status': 'queued', 'version': 1}


class MaterialApiTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = AgentOrchestraStateStore(root / 'state.db')
        self.store.create_workspace('W', name='Documents', domain_id='document', root_path=str(root))
        self.engine = SingleOrchestrator(self.store, FakeRag(), FakeChat(), domain_id='document')
        self.materials = FakeMaterials()
        self.app = create_app(self.engine, 'W', material_client=self.materials)
        self.client = self.enterContext(TestClient(self.app, base_url='http://localhost'))
        self.headers = {'X-AO-Request':'1'}
        for name in ['alpha', 'beta']:
            self.client.post('/v1/projects', headers=self.headers, json={'project_id':name, 'name':name, 'subject_id':'Purchasing'})
        self.upload = {'filename':'계획.md', 'content_base64':base64.b64encode(b'hello ' * 20000).decode()}

    def test_upload_beyond_old_body_limit_binds_and_isolates_search(self):
        for name in ['alpha', 'beta']:
            response = self.client.post(f'/v1/projects/{name}/materials', headers=self.headers, json=self.upload)
            self.assertEqual(response.status_code, 202, response.text)
        alpha = self.client.get('/v1/projects/alpha').json()
        beta = self.client.get('/v1/projects/beta').json()
        self.assertNotEqual(alpha['materials_namespace'], beta['materials_namespace'])
        call = self.materials.calls[0]
        self.assertIn(alpha['materials_namespace'], call[1])
        self.assertEqual(call[2]['project'], alpha['knowledge_project'])
        self.assertEqual(call[2]['equipment'], '')  # Generic subject is not an equipment filter.
        self.assertNotIn('content_base64', str(alpha))
        self.assertEqual(self.client.get('/v1/projects/alpha/materials').status_code, 200)
        self.assertIn(alpha['materials_namespace'], self.materials.calls[-1][1])
        response = self.client.put('/v1/projects/alpha', headers=self.headers,
            json={'name':'alpha', 'version':alpha['version'], 'subject_id':'Purchasing', 'knowledge_project':'wrong'})
        self.assertEqual(response.status_code, 409)

    def test_archived_read_only_retry_validation_and_csrf(self):
        self.client.post('/v1/projects/alpha/materials', headers=self.headers, json=self.upload)
        project = self.client.get('/v1/projects/alpha').json()
        self.client.put('/v1/projects/alpha', headers=self.headers,
            json={k: project[k] for k in ('name','version','description','subject_id','knowledge_project','repository')} | {'status':'archived'})
        self.assertEqual(self.client.post('/v1/projects/alpha/materials', headers=self.headers, json=self.upload).status_code, 409)
        self.assertEqual(self.client.get('/v1/projects/alpha/materials').status_code, 200)
        self.assertEqual(self.client.post('/v1/projects/alpha/materials/' + 'a'*64 + '/retry', headers=self.headers, json={'version':1}).status_code, 409)
        self.assertEqual(self.client.post('/v1/projects/beta/materials', json=self.upload).status_code, 403)
        self.assertEqual(self.client.post('/v1/projects/beta/materials', headers={**self.headers, 'Origin':'https://foreign'}, json=self.upload).status_code, 403)
        self.assertEqual(self.client.post('/v1/projects/beta/materials/bad/retry', headers=self.headers, json={'version':1}).status_code, 404)

    def test_failure_retains_binding_for_network_retry_and_sanitizes_errors(self):
        self.materials.failure = True
        response = self.client.post('/v1/projects/alpha/materials', headers=self.headers, json=self.upload)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('private', response.text)
        first = self.client.get('/v1/projects/alpha').json()
        self.materials.failure = False
        self.client.post('/v1/projects/alpha/materials', headers=self.headers, json=self.upload)
        self.assertEqual(first['materials_namespace'], self.client.get('/v1/projects/alpha').json()['materials_namespace'])
        self.assertEqual(self.materials.calls[0][1], self.materials.calls[1][1])

    def test_invalid_upload_does_not_reserve_binding(self):
        for patch in [{'filename':'../x.md'}, {'content_base64':'!'}, {'project':'injected'}, {'version':True}]:
            response = self.client.post('/v1/projects/alpha/materials', headers=self.headers, json={**self.upload, **patch})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn('materials_namespace', self.client.get('/v1/projects/alpha').json())
        self.assertEqual(self.materials.calls, [])

    def test_upload_feature_off_by_default(self):
        # Route closure resolves the provided operator client, never a URL from a request.
        self.assertTrue(self.client.get('/v1/workspace').json()['material_uploads_enabled'])
        self.app.state.worker.close()
        with TestClient(create_app(self.engine, 'W'), base_url='http://localhost') as disabled:
            self.assertFalse(disabled.get('/v1/workspace').json()['material_uploads_enabled'])
            self.assertEqual(disabled.get('/v1/projects/alpha/materials').status_code, 503)


if __name__ == '__main__':
    unittest.main()

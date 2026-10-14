"""Real socket smoke test with synthetic providers; no external services required."""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'PYTHONPATH': str(root / 'src'), 'AO_TEST_API_KEY': 'synthetic-smoke-key-only', 'AO_TEST_MANAGEMENT': '1'}
    process = subprocess.Popen([sys.executable, str(root / 'tests/web_demo_server.py')],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url='http://127.0.0.1:18650', trust_env=False, timeout=2) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('test server stopped before startup')
                try:
                    if client.get('/health').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.05)
            admin = {'X-AO-Request': '1'}
            project = client.post('/v1/projects', headers=admin, json={'project_id': 'smoke-project', 'name': 'General project'}).json()
            assert project['domain_id'] == 'equipment', project
            assert client.post('/v1/projects/smoke-project/memory', headers=admin, json={'kind': 'decision', 'content': '검수 결과는 내부 확인 후 확정'}).status_code == 201
            profile = client.post('/v1/agents', headers=admin, json={'agent_id': 'smoke-doc', 'name': 'Smoke document agent', 'role': 'document-agent'}).json()
            trial = client.post('/v1/agents/smoke-doc/test', headers=admin, json={'version': profile['version']}).json()
            assert trial['test_status'] == 'passed', trial
            assert client.post('/v1/agents/smoke-doc/enabled', headers=admin, json={'version': trial['version'], 'enabled': True}).status_code == 200
            response = client.post('/v1/tasks', headers={'X-AO-Request':'1'}, json={
                'objective':'문서 근거로 알람 분석', 'request_kind':'troubleshooting', 'create_artifact':True, 'project_id': 'smoke-project'})
            assert response.status_code == 202, response.text
            task_id = response.json()['task_id']
            for _ in range(100):
                data = client.get('/v1/tasks/' + task_id).json()
                if data['submission_status'] == 'completed':
                    break
                time.sleep(.05)
            assert data['status'] == 'completed', data
            assert data['agent_profiles'][0]['agent_id'] == 'smoke-doc', data
            assert data['project_id'] == 'smoke-project', data
            assert '검수 결과는 내부' in data['project_memory'], data
            assert len(client.get('/v1/tasks?project_id=smoke-project').json()) == 1
            runs = client.get('/v1/tasks/' + task_id + '/runs').json()
            assert 'troubleshooting-agent' in [run['agent_name'] for run in runs]
            assert client.get(data['artifacts'][0]['download_url']).status_code == 200
            assert client.get('/assets/app.js').status_code == 200
            auth = {'Authorization': 'Bearer synthetic-smoke-key-only'}
            assert client.get('/v1/models', headers=auth).json()['data'][0]['id'] == 'ao/equipment/demo'
            with client.stream('POST', '/v1/chat/completions', headers=auth, json={
                'model': 'ao/equipment/demo/project/smoke-project/report', 'stream': True,
                'messages': [{'role': 'user', 'content': '문서 보고서'}]}) as response:
                assert response.status_code == 200
                chunks = list(response.iter_lines())
                assert 'data: [DONE]' in chunks
                assert any('/artifacts/0' in line for line in chunks)
                assert response.headers['x-ao-task-id']
            print('PASS: actual HTTP authenticated model discovery, SSE chat, report link, DONE')
            print('PASS: actual HTTP 202, specialist execution, persisted completion, artifact, static assets')
            print('PASS: project CRUD, user memory, scoped tasks and project-specific OpenWebUI SSE model')
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

"""Local-only control UI. One process, one bounded sequential worker, no write tools."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import asynccontextmanager, closing
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .orchestrator import OrchestratorRequest, RequestKind, StateNotFoundError, TaskStatus


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    objective: str = Field(min_length=1, max_length=20000)
    session_id: str = Field(default="", max_length=500)
    equipment_id: str | None = Field(default=None, max_length=200)
    domain_id: str | None = None
    subject_id: str | None = Field(default=None, max_length=200)
    request_kind: str | None = None
    create_artifact: bool = False
    knowledge_scopes: list[str] = Field(default_factory=list, max_length=8)


class TaskWorker:
    """Durable submission/result journal alongside (not instead of) A/O state."""

    def __init__(self, engine, workspace_id: str, path: Path, capacity: int = 20):
        self.engine = engine
        self.store = engine.state_store
        self.workspace_id = workspace_id
        self.path = path
        self.capacity = capacity
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = None
        self.lock_path = Path(str(path) + ".worker.lock")

    def db(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Never automatically steal a possibly live worker's lock.
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(self.db()) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS web_config (workspace_id TEXT NOT NULL)')
                configured = db.execute('SELECT workspace_id FROM web_config').fetchone()
                if configured and configured[0] != self.workspace_id:
                    raise ValueError('Web journal is bound to another workspace')
                if not configured:
                    db.execute('INSERT INTO web_config VALUES(?)', (self.workspace_id,))
                db.execute("CREATE TABLE IF NOT EXISTS web_jobs (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT, mode TEXT NOT NULL DEFAULT 'unknown', submitted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')))")
                rows = db.execute("SELECT id FROM web_jobs WHERE status IN ('queued','running')").fetchall()
                for row in rows:
                    try:
                        task = self.store.get_task(row['id'])
                        if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                            for run in self.store.list_agent_runs(task.task_id):
                                if run['status'] == 'running':
                                    self.store.finish_agent_run(run['run_id'], status='failed', error='Web worker interrupted')
                            self.store.transition_task(task.task_id, TaskStatus.FAILED, expected_version=task.version, failure_reason='Web worker interrupted; explicit resubmission required')
                    except StateNotFoundError:
                        pass
                db.execute("UPDATE web_jobs SET status='interrupted', error='Worker interrupted; inspect Task before resubmitting' WHERE status IN ('queued','running')")
            self.stop.clear()
            self.thread = threading.Thread(target=self._loop, name="ao-web-worker", daemon=False)
            self.thread.start()
        except BaseException:
            self.lock_path.unlink(missing_ok=True)
            raise

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join()  # adapter timeouts bound in-flight request duration
        self.lock_path.unlink(missing_ok=True)

    def submit(self, value: TaskInput, *, conversation=(), temperature=0.1, max_tokens=1200):
        task_id = 'web-' + uuid4().hex
        request = OrchestratorRequest(
            workspace_id=self.workspace_id, task_id=task_id,
            objective=value.objective, session_id=value.session_id,
            equipment_id=value.equipment_id,
            conversation=conversation, temperature=temperature, max_tokens=max_tokens,
            domain_id=value.domain_id,
            subject_id=value.subject_id,
            request_kind=RequestKind(value.request_kind) if value.request_kind else None,
            create_artifact=value.create_artifact, knowledge_scopes=tuple(value.knowledge_scopes),
        )
        request = self.engine.validate_request(request)
        if request.create_artifact and self.engine.artifact_store is None:
            raise ValueError('Artifact store is not configured')
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("SELECT count(*) FROM web_jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= self.capacity:
                raise HTTPException(429, 'Task queue is full')
            mode = 'specialists' if self.engine.specialists is not None else 'direct'
            db.execute("INSERT INTO web_jobs(id,request,status,mode) VALUES(?,?,'queued',?)", (task_id, json.dumps(asdict(request)), mode))
        self.wake.set()
        return task_id

    def job(self, task_id):
        with closing(self.db()) as db:
            row = db.execute('SELECT * FROM web_jobs WHERE id=?', (task_id,)).fetchone()
        return dict(row) if row else None

    def _loop(self):
        while not self.stop.is_set():
            self.wake.clear()
            with closing(self.db()) as db, db:
                row = db.execute("SELECT * FROM web_jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE web_jobs SET status='running' WHERE id=?", (row['id'],))
            if not row:
                self.wake.wait(1)
                continue
            try:
                data = json.loads(row['request'])
                if data['request_kind']:
                    data['request_kind'] = RequestKind(data['request_kind'])
                result = self.engine.run(OrchestratorRequest(**data))
                status, output, error = 'completed', json.dumps(asdict(result)), None
            except Exception as exc:
                # Upstream error bodies may contain credentials; never expose them in API.
                status, output, error = 'failed', None, type(exc).__name__ + ': execution failed'
            with closing(self.db()) as db, db:
                db.execute('UPDATE web_jobs SET status=?,result=?,error=? WHERE id=?', (status, output, error, row['id']))


def create_app(engine, workspace_id: str, *, agents: list[dict] | None = None,
               health_checks: dict | None = None, queue_capacity: int = 20,
               openai_api_key: str = "", chat_wait_seconds: float = 600):
    store = engine.state_store
    workspace = store.get_workspace(workspace_id)
    if workspace['domain_id'] != engine.domain.domain_id:
        raise ValueError('workspace domain differs from configured domain')
    worker = TaskWorker(engine, workspace_id, Path(str(store.path) + '.web.db'), queue_capacity)
    static = Path(__file__).parent / 'web_static'
    agents = agents or []
    health_checks = health_checks or {}

    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        try:
            yield
        finally:
            await asyncio.to_thread(worker.close)

    app = FastAPI(title='Hermes A/O Control', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.worker = worker
    if openai_api_key:
        from .openai_api import install_openai_api
        install_openai_api(app, worker, openai_api_key, chat_wait_seconds)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get('origin')
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Cross-origin access forbidden'}, status_code=403)
        if request.method not in {'GET', 'HEAD'}:
            if request.url.path != '/v1/chat/completions' and request.headers.get('x-ao-request') != '1':
                return JSONResponse({'detail': 'X-AO-Request required'}, status_code=403)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    return JSONResponse({'detail': 'Request too large'}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def index():
        return FileResponse(static / 'index.html')

    @app.get('/assets/{name}')
    def asset(name: str):
        if name not in {'app.js', 'app.css'}:
            raise HTTPException(404)
        return FileResponse(static / name)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': 'local-single-user', 'worker_alive': bool(worker.thread and worker.thread.is_alive())}

    @app.get('/v1/workspace')
    def workspace_info():
        return {'workspace_id': workspace_id, 'name': workspace['name'],
                'domain_id': engine.domain.domain_id,
                'subject_label': engine.domain.subject_label,
                'allowed_request_kinds': engine.domain.allowed_kinds,
                'specialists_enabled': engine.specialists is not None,
                'artifacts_enabled': engine.artifact_store is not None}

    @app.get('/v1/agents')
    def agent_list():
        return agents

    @app.get('/v1/agents/{agent_id}/health')
    def agent_health(agent_id: str):
        if agent_id not in {a['agent_id'] for a in agents}:
            raise HTTPException(404)
        if agent_id not in health_checks:
            return {'status': 'disabled', 'inference_verified': False}
        try:
            health_checks[agent_id]()
            return {'status': 'reachable', 'inference_verified': False}
        except Exception:
            return {'status': 'unavailable', 'inference_verified': False}

    @app.post('/v1/tasks', status_code=202)
    def submit(value: TaskInput):
        try:
            task_id = worker.submit(value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {'task_id': task_id, 'status': 'accepted'}

    def task_data(task_id):
        job = worker.job(task_id)
        try:
            task = store.get_task(task_id)
            if task.workspace_id != workspace_id:
                raise HTTPException(404)
            data = asdict(task)
            if data['failure_reason']:
                data['failure_reason'] = 'Execution failed; inspect operator-side logs/state'
            # Paths are not download capabilities; expose registered index URLs only.
            data['artifacts'] = [{'artifact_type': a.artifact_type, 'sha256': a.sha256,
                'download_url': f'/v1/tasks/{task_id}/artifacts/{i}'} for i, a in enumerate(task.artifacts)]
        except StateNotFoundError:
            if not job:
                raise HTTPException(404)
            value = json.loads(job['request'])
            data = {'task_id': task_id, 'objective': value['objective'], 'status': job['status'], 'evidence': [], 'artifacts': []}
        checkpoint = store.latest_checkpoint(task_id) if 'version' in data else None
        data['answer'] = (checkpoint or {}).get('payload', {}).get('answer', '')
        data['submission_status'] = job['status'] if job else None
        data['error'] = job['error'] if job else None
        result = json.loads(job['result']) if job and job['result'] else {}
        data['finish_reason'] = result.get('finish_reason', '')
        data['delegation_mode'] = job['mode'] if job else 'unknown (CLI task)'
        data['created_at'] = data.get('created_at') or (job['submitted_at'] if job else '')
        data['session_id'] = json.loads(job['request'])['session_id'] if job else ''
        return data

    @app.get('/v1/tasks')
    def tasks(limit: int = 50):
        if not 1 <= limit <= 100:
            raise HTTPException(422, 'limit must be 1-100')
        with closing(store._connect()) as db:
            rows = db.execute('SELECT task_id FROM tasks WHERE workspace_id=? ORDER BY rowid DESC LIMIT ?', (workspace_id, limit)).fetchall()
        with closing(worker.db()) as db:
            jobs = db.execute('SELECT id FROM web_jobs ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
        ids = list(dict.fromkeys([r['id'] for r in jobs] + [r['task_id'] for r in rows]))
        return sorted([task_data(i) for i in ids], key=lambda item: item['created_at'], reverse=True)[:limit]

    @app.get('/v1/tasks/{task_id}')
    def task(task_id: str):
        return task_data(task_id)

    @app.get('/v1/tasks/{task_id}/runs')
    def runs(task_id: str):
        data = task_data(task_id)
        if 'version' not in data:
            return []
        values = store.list_agent_runs(task_id)
        for value in values:
            if value.get('error'):
                value['error'] = 'Agent execution failed'
        return values

    @app.get('/v1/tasks/{task_id}/evidence')
    def evidence(task_id: str):
        return task_data(task_id)['evidence']

    @app.get('/v1/tasks/{task_id}/artifacts')
    def artifacts(task_id: str):
        return task_data(task_id)['artifacts']

    @app.get('/v1/tasks/{task_id}/artifacts/{index}')
    def download(task_id: str, index: int):
        data = task_data(task_id)
        if not 0 <= index < len(data['artifacts']) or engine.artifact_store is None:
            raise HTTPException(404)
        artifact = store.get_task(task_id).artifacts[index]
        try:
            path = Path(artifact.path).resolve(strict=True)
            path.relative_to(engine.artifact_store.root.resolve())
            if path.stat().st_size > 2_000_000:
                raise ValueError('too large')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != artifact.sha256:
                raise ValueError('hash mismatch')
        except (OSError, ValueError):
            raise HTTPException(409, 'Artifact unavailable or integrity check failed')
        return Response(content, media_type='text/plain; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="report.md"'})

    return app

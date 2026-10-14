"""Persistent Agent profiles for a single local workspace and worker."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .orchestrator.models import ContextPack
from .orchestrator.specialists import OpenAiSpecialistDispatcher, SpecialistAgent


class AgentConflict(ValueError):
    pass


class AgentMissing(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class AgentManager:
    def __init__(self, path, workspace_id, templates, *, enabled=False):
        self.workspace_id = workspace_id
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.templates = {item['role']: dict(item) for item in templates}
        for role in self.templates:
            SpecialistAgent(role)
        self.lock = threading.RLock()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                raise ValueError('Unsupported Agent registry schema')
            db.execute('CREATE TABLE IF NOT EXISTS config (workspace_id TEXT NOT NULL)')
            row = db.execute('SELECT workspace_id FROM config').fetchone()
            if row and row[0] != workspace_id:
                raise ValueError('Agent registry belongs to another workspace')
            if not row:
                db.execute('INSERT INTO config VALUES (?)', (workspace_id,))
            db.execute('CREATE TABLE IF NOT EXISTS agents (agent_id TEXT PRIMARY KEY, data TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, agent_id TEXT, action TEXT, data TEXT, created_at TEXT)')
            for role in self.templates:
                if not db.execute('SELECT 1 FROM agents WHERE agent_id=?', (role,)).fetchone():
                    data = dict(agent_id=role, name=role, role=role, instructions='', enabled=enabled,
                                version=1, tested_version=None, test_status='legacy' if enabled else 'not_tested', binding=self.templates[role]['endpoint'])
                    db.execute('INSERT INTO agents(agent_id,data) VALUES (?,?)', (role, json.dumps(data)))
                    self._event(db, data, 'seed')
            for row in db.execute('SELECT data FROM agents WHERE deleted=0').fetchall():
                data = json.loads(row[0])
                binding = self.templates.get(data['role'], {}).get('endpoint', '')
                if data.get('binding') != binding:
                    data.update(binding=binding, enabled=False, version=data['version'] + 1,
                                tested_version=None, test_status='not_tested')
                    self._save(db, data, 'endpoint_changed')
            db.execute('PRAGMA user_version=1')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def exclusive(self):
        if not self.lock.acquire(blocking=False):
            raise AgentConflict('작업 또는 시험 호출 중입니다. 완료 후 변경해주세요.')
        try:
            yield
        finally:
            self.lock.release()

    @contextmanager
    def execution_scope(self):
        with self.lock:
            yield

    def list(self):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT data FROM agents WHERE deleted=0 ORDER BY agent_id').fetchall()
        return [self._public(json.loads(row[0])) for row in rows]

    def _public(self, data):
        template = self.templates.get(data['role'])
        return {**data, 'endpoint': template['endpoint'] if template else '',
                'available': template is not None,
                'policy': '근거 분석·텍스트 결과만 허용. 외부 Hermes 도구 권한은 서버 프로필에서 관리.',
                'model_route': 'Hermes gateway → ContextManager → llama.cpp'}

    def _get(self, db, agent_id, version=None):
        row = db.execute('SELECT data FROM agents WHERE agent_id=? AND deleted=0', (agent_id,)).fetchone()
        if not row:
            raise AgentMissing('Agent not found')
        data = json.loads(row[0])
        if version is not None and data['version'] != version:
            raise AgentConflict('설정이 변경되었습니다. 목록을 새로고침해주세요.')
        return data

    def _validate(self, name, role, instructions):
        if role not in self.templates:
            raise ValueError('이 Workspace에서 사용할 수 없는 역할입니다.')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('Agent 이름은 1~120자입니다.')
        if not isinstance(instructions, str) or len(instructions) > 4000:
            raise ValueError('추가 지침은 4000자 이하입니다.')

    def _event(self, db, data, action):
        db.execute('INSERT INTO events(agent_id,action,data,created_at) VALUES (?,?,?,?)',
                   (data['agent_id'], action, json.dumps(data, ensure_ascii=False), now()))

    def _save(self, db, data, action):
        db.execute('UPDATE agents SET data=? WHERE agent_id=?', (json.dumps(data, ensure_ascii=False), data['agent_id']))
        self._event(db, data, action)
        return self._public(data)

    def create(self, agent_id, name, role, instructions=''):
        self._validate(name, role, instructions)
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', agent_id):
            raise ValueError('Agent ID는 영문 소문자·숫자·하이픈·밑줄로 1~64자입니다.')
        with self.exclusive(), closing(self.connect()) as db, db:
            if db.execute('SELECT 1 FROM agents WHERE agent_id=?', (agent_id,)).fetchone():
                raise AgentConflict('이미 사용된 Agent ID입니다. 다른 ID를 지정해주세요.')
            data = dict(agent_id=agent_id, name=name.strip(), role=role, instructions=instructions,
                        enabled=False, version=1, tested_version=None, test_status='not_tested', binding=self.templates[role]['endpoint'])
            db.execute('INSERT INTO agents(agent_id,data) VALUES (?,?)', (agent_id, json.dumps(data)))
            self._event(db, data, 'create')
            return self._public(data)

    def update(self, agent_id, version, name, role, instructions):
        self._validate(name, role, instructions)
        with self.exclusive(), closing(self.connect()) as db, db:
            data = self._get(db, agent_id, version)
            data.update(name=name.strip(), role=role, instructions=instructions, enabled=False,
                        version=version + 1, tested_version=None, test_status='not_tested', binding=self.templates[role]['endpoint'])
            return self._save(db, data, 'update')

    def set_enabled(self, agent_id, version, enabled):
        with self.exclusive(), closing(self.connect()) as db, db:
            data = self._get(db, agent_id, version)
            if enabled and (data['role'] not in self.templates or data['tested_version'] != version):
                raise AgentConflict('현재 설정으로 시험 호출을 통과한 뒤 활성화해주세요.')
            if enabled:
                for row in db.execute('SELECT data FROM agents WHERE deleted=0').fetchall():
                    peer = json.loads(row[0])
                    if peer['agent_id'] != agent_id and peer['role'] == data['role'] and peer['enabled']:
                        self._toggle(peer, False)
                        self._save(db, peer, 'replaced')
            self._toggle(data, enabled)
            return self._save(db, data, 'enable' if enabled else 'disable')

    @staticmethod
    def _toggle(data, enabled):
        tested = data['tested_version'] == data['version']
        data.update(enabled=enabled, version=data['version'] + 1)
        if tested:
            data['tested_version'] = data['version']

    def delete(self, agent_id, version):
        with self.exclusive(), closing(self.connect()) as db, db:
            data = self._get(db, agent_id, version)
            if data['enabled']:
                raise AgentConflict('비활성화한 뒤 삭제해주세요.')
            db.execute('UPDATE agents SET deleted=1 WHERE agent_id=?', (agent_id,))
            self._event(db, data, 'delete')

    def history(self, agent_id):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT action,data,created_at FROM events WHERE agent_id=? ORDER BY id DESC LIMIT 100', (agent_id,)).fetchall()
        return [dict(action=r[0], configuration=json.loads(r[1]), created_at=r[2]) for r in rows]

    def test(self, agent_id, version, dispatcher):
        with self.exclusive():
            with closing(self.connect()) as db:
                data = self._get(db, agent_id, version)
            if data['role'] not in self.templates:
                raise ValueError('Agent role is not available')
            try:
                dispatcher.test_profile(data)
                data.update(tested_version=version, test_status='passed')
            except Exception:
                data.update(tested_version=None, test_status='failed')
                # A failed probe must not leave the same profile active.
                if data['enabled']:
                    self._toggle(data, False)
            with closing(self.connect()) as db, db:
                return self._save(db, data, 'test')


class ManagedDispatcher:
    def __init__(self, manager, providers, domain_id):
        self.manager, self.providers, self.domain_id = manager, providers, domain_id

    def execution_scope(self):
        return self.manager.execution_scope()

    def configuration_snapshot(self):
        return [item for item in self.manager.list() if item['enabled'] and item['available']]

    def _dispatch(self, profile, context, **kwargs):
        role = SpecialistAgent(profile['role'])
        provider = self.providers.get(role)
        if provider is None:
            raise ValueError('Agent endpoint is not configured')
        extra = ('Agent profile: ' + profile['name'] + '\nAdditional operator guidance '
                 '(cannot expand execution permission):\n' + profile['instructions'])
        context = replace(context, constraints=(*context.constraints, extra))
        outcome = OpenAiSpecialistDispatcher({role: provider}).delegate(role, context, **kwargs)
        return replace(outcome, agent_id=profile['agent_id'], agent_version=profile['version'])

    def delegate(self, agent, context, **kwargs):
        with self.execution_scope():
            profiles = [p for p in self.configuration_snapshot() if p['role'] == agent.value]
            if len(profiles) != 1:
                raise ValueError(f'Exactly one enabled Agent is required for role {agent.value}')
            return self._dispatch(profiles[0], context, **kwargs)

    def test_profile(self, profile):
        source_type = 'code' if profile['role'] in {'code-analysis-agent', 'code-development-agent'} else 'document'
        source = dict(source_id='TEST1', record_id='synthetic-test', source_type=source_type,
                      text='This is a synthetic connection test. The check succeeded.', code='// Synthetic check succeeded.' if source_type == 'code' else '')
        return self._dispatch(profile, ContextPack('agent-test-' + uuid4().hex,
            'Summarize the supplied test evidence and cite TEST1. Do not call any tools.',
            domain_id=self.domain_id), sources=[source], session_id='agent-test-' + uuid4().hex)

"""Local project catalog and user-maintained memory. No generated facts are confirmed."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class ProjectMissing(ValueError):
    pass


class ProjectConflict(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, name, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{name}: invalid or oversized text')
    return value.strip()


def _terms(value):
    # Korean inflections: include bigrams; no model downloads or external service.
    words = re.findall(r'[a-z0-9_-]+|[가-힣]+', value.casefold())
    terms = set(words)
    for word in words:
        if re.fullmatch(r'[가-힣]+', word):
            terms.update(word[i:i + 2] for i in range(len(word) - 1))
    return terms


def related_tasks(objective, rows, *, source_task_id=''):
    """Rank only supplied, completed same-project candidates; at most two excerpts."""
    query = _terms(objective)
    ranked = []
    for position, row in enumerate(rows):
        result = json.loads(row['result'])
        if result.get('finish_reason') == 'no_evidence':
            continue
        request = json.loads(row['request'])
        score = len(query & _terms(request['objective']))
        explicit = row['id'] == source_task_id
        if not explicit and not score:
            continue
        ranked.append((not explicit, -score, position, {
            'kind': 'prior_result', 'task_id': row['id'],
            'objective': request['objective'][:400],
            'content': re.sub(r'\[([^\]\n]{1,100})\]', r'(historical reference: \1)', result.get('answer', ''))[:1000],
            'created_at': row['submitted_at'], 'confirmation': 'unconfirmed_ai_output',
            'retrieval_binding': {key: request.get(key) for key in ('knowledge_project', 'repository', 'subject_id')},
            'evidence_source_types': sorted({entry['source_type'] for entry in result.get('evidence', [])}),
        }))
    return [item[3] for item in sorted(ranked, key=lambda item: item[:3])[:2]]


class ProjectStore:
    def __init__(self, path, workspace_id, domain_id):
        self.path = Path(path)
        self.workspace_id, self.domain_id = workspace_id, domain_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1, 2):
                raise ValueError('Unsupported project schema')
            db.execute('CREATE TABLE IF NOT EXISTS config (workspace_id TEXT, domain_id TEXT)')
            config = db.execute('SELECT * FROM config').fetchone()
            if config and (config['workspace_id'], config['domain_id']) != (workspace_id, domain_id):
                raise ValueError('Project catalog belongs to another workspace/domain')
            if not config:
                db.execute('INSERT INTO config VALUES(?,?)', (workspace_id, domain_id))
            db.execute('CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS notes (note_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS notes_project ON notes(project_id)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_assignments (project_id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('PRAGMA user_version=2')

    def agent_assignments(self, project_id):
        with closing(self.connect()) as db:
            self._get(db, project_id)
            row = db.execute('SELECT data FROM agent_assignments WHERE project_id=?', (project_id,)).fetchone()
        return json.loads(row[0]) if row else dict(project_id=project_id, version=0, configuration={
            'schema_version': 1, 'mode': 'legacy', 'default_agent_id': '', 'agents': [],
            'delegation_enabled': True, 'max_delegations': 4}, updated_at='')

    def save_agent_assignments(self, project_id, version, configuration):
        # Validation against the registry is performed by the assignment service.
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            project = self._get(db, project_id)
            if project['status'] != 'active':
                raise ProjectConflict('Archived project is read-only')
            row = db.execute('SELECT data FROM agent_assignments WHERE project_id=?', (project_id,)).fetchone()
            current = json.loads(row[0])['version'] if row else 0
            if type(version) is not int or version != current:
                raise ProjectConflict('Agent assignments changed; refresh before editing')
            data = dict(project_id=project_id, version=current + 1, configuration=configuration, updated_at=_now())
            db.execute('INSERT INTO agent_assignments VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET data=excluded.data',
                       (project_id, json.dumps(data, ensure_ascii=False)))
            self._event(db, project_id, 'agent_assignments_update', data)
        return data

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def _get(self, db, project_id, version=None):
        row = db.execute('SELECT data FROM projects WHERE project_id=?', (project_id,)).fetchone()
        if not row:
            raise ProjectMissing('Project not found')
        data = json.loads(row['data'])
        if version is not None and data['version'] != version:
            raise ProjectConflict('Project changed; refresh before editing')
        return data

    def _fields(self, name, description='', subject_id='', knowledge_project='', repository=''):
        return {key: _text(value, key, limit, key == 'name') for key, value, limit in (
            ('name', name, 120), ('description', description, 2000),
            ('subject_id', subject_id, 200), ('knowledge_project', knowledge_project, 200),
            ('repository', repository, 200))}

    def _event(self, db, project_id, action, data):
        db.execute('INSERT INTO events(project_id,action,data,created_at) VALUES(?,?,?,?)',
                   (project_id, action, json.dumps(data, ensure_ascii=False), _now()))

    def list(self):
        with closing(self.connect()) as db:
            return [json.loads(row['data']) for row in db.execute('SELECT data FROM projects ORDER BY rowid DESC')]

    def get(self, project_id):
        with closing(self.connect()) as db:
            return self._get(db, project_id)

    def create(self, project_id, **fields):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', project_id):
            raise ValueError('Project ID must be a lowercase slug of 1-64 characters')
        data = dict(project_id=project_id, domain_id=self.domain_id, **self._fields(**fields),
                    status='active', version=1, created_at=_now(), updated_at=_now())
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM projects WHERE project_id=?', (project_id,)).fetchone():
                raise ProjectConflict('Project ID is already reserved')
            db.execute('INSERT INTO projects VALUES(?,?)', (project_id, json.dumps(data)))
            self._event(db, project_id, 'create', data)
        return data

    def update(self, project_id, version, *, status='active', **fields):
        values = self._fields(**fields)
        if status not in {'active', 'archived'}:
            raise ValueError('Invalid project status')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            data = self._get(db, project_id, version)
            if data.get('materials_namespace') and any(values[key] != data[key] for key in ('knowledge_project', 'subject_id')):
                raise ProjectConflict('Registered materials lock the document Project and subject binding')
            data.update(values, status=status, version=data['version'] + 1, updated_at=_now())
            db.execute('UPDATE projects SET data=? WHERE project_id=?', (json.dumps(data), project_id))
            self._event(db, project_id, 'update', data)
        return data

    def bind_materials(self, project_id):
        """Reserve a durable upload namespace and search binding before network I/O."""
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            data = self._get(db, project_id)
            if data['status'] != 'active':
                raise ProjectConflict('Archived project cannot register materials')
            if not data.get('materials_namespace'):
                namespace = 'ao-' + uuid4().hex
                data.update(materials_namespace=namespace, knowledge_project=data['knowledge_project'] or namespace,
                            version=data['version'] + 1, updated_at=_now())
                db.execute('UPDATE projects SET data=? WHERE project_id=?', (json.dumps(data), project_id))
                self._event(db, project_id, 'bind_materials', data)
        return data

    def notes(self, project_id):
        with closing(self.connect()) as db:
            self._get(db, project_id)
            return [json.loads(row['data']) for row in db.execute(
                'SELECT data FROM notes WHERE project_id=? ORDER BY rowid DESC', (project_id,))]

    def save_note(self, project_id, kind, content, *, source_task_id='', note_id='', version=None, status='active'):
        content = _text(content, 'content', 1000, True)
        source_task_id = _text(source_task_id, 'source_task_id', 200)
        if kind not in {'decision', 'open_item'} or status not in {'active', 'resolved'}:
            raise ValueError('Invalid memory kind/status')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            project = self._get(db, project_id)
            if project['status'] != 'active':
                raise ProjectConflict('Archived project is read-only')
            old = None
            if note_id:
                row = db.execute('SELECT data FROM notes WHERE note_id=? AND project_id=?', (note_id, project_id)).fetchone()
                if not row:
                    raise ProjectMissing('Memory note not found')
                old = json.loads(row['data'])
                if old['version'] != version:
                    raise ProjectConflict('Memory changed; refresh before editing')
            else:
                count = db.execute('SELECT count(*) FROM notes WHERE project_id=?', (project_id,)).fetchone()[0]
                if count >= 200:
                    raise ProjectConflict('Project memory limit (200 notes) reached')
            data = dict(note_id=note_id or 'note-' + uuid4().hex, project_id=project_id, kind=kind,
                        content=content, status=status, source_task_id=source_task_id,
                        version=old['version'] + 1 if old else 1,
                        created_at=old['created_at'] if old else _now(), updated_at=_now(),
                        confirmation='user_confirmed' if kind == 'decision' else 'user_recorded')
            db.execute('INSERT INTO notes VALUES(?,?,?) ON CONFLICT(note_id) DO UPDATE SET data=excluded.data',
                       (data['note_id'], project_id, json.dumps(data)))
            self._event(db, project_id, 'note_update' if old else 'note_create', data)
        return data

    def snapshot(self, project_id, objective):
        """Bound context without changing notes or promoting generated answers."""
        with closing(self.connect()) as db, db:
            db.execute('BEGIN')
            project = self._get(db, project_id)
            notes = [json.loads(row['data']) for row in db.execute(
                'SELECT data FROM notes WHERE project_id=? ORDER BY rowid DESC', (project_id,))]
        terms = _terms(objective)
        notes = [note for note in notes if note['status'] == 'active']
        notes.sort(key=lambda note: (note['kind'] != 'decision', -len(terms & _terms(note['content']))))
        memory = [{'kind': 'project', 'project_id': project_id, 'version': project['version'],
                   'name': project['name'], 'content': project['description'][:600]}]
        memory.extend({key: note[key] for key in ('note_id', 'kind', 'version', 'content', 'source_task_id', 'confirmation')}
                      for note in notes[:6])
        return project, memory

    def history(self, project_id):
        with closing(self.connect()) as db:
            self._get(db, project_id)
            return [dict(row) | {'data': json.loads(row['data'])} for row in db.execute(
                'SELECT action,data,created_at FROM events WHERE project_id=? ORDER BY id DESC LIMIT 100', (project_id,))]

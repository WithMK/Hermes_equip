"""Operator-configured folder polling; uploads bytes, never writes source files."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .material_api import MAX_FILE_BYTES
from .http_client import AdapterError

EXTENSIONS = {'.md', '.txt', '.pdf', '.docx', '.pptx', '.xlsx'}


def load_watch_config(path):
    """This local configuration is operator-owned; HTTP requests cannot choose paths."""
    if path is None:
        return []
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, list) or len(data) > 32:
        raise ValueError('Watch config must be a list of at most 32 folders')
    seen = set()
    entries = []
    for item in data:
        if not isinstance(item, dict) or set(item) - {'watch_id', 'project_id', 'path', 'recursive'}:
            raise ValueError('Invalid watch configuration fields')
        identity, project = item.get('watch_id', ''), item.get('project_id', '')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', identity) or identity in seen:
            raise ValueError('Watch ID must be unique and contain 1-64 letters, digits, _ or -')
        if not isinstance(project, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', project):
            raise ValueError('Invalid watch project ID')
        folder = item.get('path')
        if not isinstance(folder, str) or not Path(folder).is_absolute():
            raise ValueError('Watch path must be absolute')
        if type(item.get('recursive', True)) is not bool:
            raise ValueError('recursive must be boolean')
        entries.append(dict(watch_id=identity, project_id=project, path=str(Path(folder)), recursive=item.get('recursive', True)))
        seen.add(identity)
    return entries


def _now():
    return datetime.now(timezone.utc).isoformat()


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _stamp(info):
    return [info.st_size, info.st_mtime_ns, info.st_ino]


class MaterialWatcher:
    def __init__(self, path, projects, client, entries, *, interval=10):
        if entries and client is None:
            raise ValueError('Folder watching requires document uploads')
        if not 1 <= interval <= 3600:
            raise ValueError('Watch interval must be between 1 and 3600 seconds')
        self.path, self.projects, self.client = Path(path), projects, client
        self.entries, self.interval = entries, interval
        self.stop = threading.Event()
        self.thread = None
        self.lock = threading.RLock()
        self.observed = {}  # Stability observations deliberately reset after restart.
        self.reports = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, config TEXT NOT NULL, enabled INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS files (watch_id TEXT NOT NULL, relative_path TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(watch_id, relative_path))')
            for entry in entries:
                raw = json.dumps(entry, sort_keys=True)
                old = db.execute('SELECT config FROM watches WHERE id=?', (entry['watch_id'],)).fetchone()
                if old and old[0] != raw:
                    raise ValueError('A watch ID is bound to its original folder/project; use a new ID for a new binding')
                db.execute('INSERT OR IGNORE INTO watches VALUES(?,?,1)', (entry['watch_id'], raw))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Watcher already started')
        self.thread = threading.Thread(target=self._run, name='material-folder-watch', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()

    def _run(self):
        while not self.stop.is_set():
            self.scan_once()
            self.stop.wait(self.interval)

    def _enabled(self, identity):
        with closing(self.connect()) as db:
            return bool(db.execute('SELECT enabled FROM watches WHERE id=?', (identity,)).fetchone()[0])

    def set_enabled(self, project_id, identity, enabled):
        entry = next((e for e in self.entries if e['watch_id'] == identity and e['project_id'] == project_id), None)
        if entry is None:
            raise KeyError('Watch not found')
        # A completed pause guarantees no new upload can start until resumed.
        with self.lock, closing(self.connect()) as db, db:
            db.execute('UPDATE watches SET enabled=? WHERE id=?', (int(enabled), identity))
            self.reports[identity] = dict(status='waiting' if enabled else 'paused', error='', checked_at=_now())

    def snapshot(self, project_id):
        with self.lock, closing(self.connect()) as db:
            result = []
            for entry in self.entries:
                if entry['project_id'] != project_id:
                    continue
                files = [json.loads(row[0]) for row in db.execute('SELECT data FROM files WHERE watch_id=? ORDER BY relative_path', (entry['watch_id'],))]
                result.append({**entry, 'enabled': self._enabled(entry['watch_id']),
                               **self.reports.get(entry['watch_id'], {'status':'waiting', 'error':'', 'checked_at':''}),
                               'files': files})
            return result

    def _save(self, identity, relative, data):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)', (identity, relative, json.dumps(data)))

    def scan_once(self):
        for entry in self.entries:
            if self.stop.is_set():
                return
            identity = entry['watch_id']
            try:
                with self.lock:
                    if not self._enabled(identity):
                        self.reports[identity] = dict(status='paused', error='', checked_at=_now())
                        continue
                self._scan(entry)
            except Exception:
                logging.exception('Folder scan failed: %s', identity)
                with self.lock:
                    self.reports[identity] = dict(status='error', error='폴더 접근 또는 RAG 연결을 확인하세요. 기존 자료는 유지됩니다.', checked_at=_now())

    def _paths(self, entry):
        root = Path(entry['path'])
        # Do not follow symlinks or Windows junctions, including configured ancestors.
        if any(_linked(part) for part in (root, *root.parents)) or not root.is_dir():
            raise ValueError('Watch root is missing or linked')
        paths = []
        def walk(folder):
            for path in sorted(folder.iterdir()):
                if path.name.startswith(('.', '~$')) or _linked(path):
                    continue
                if path.is_dir() and entry['recursive']:
                    walk(path)
                elif path.is_file() and path.suffix.lower() in EXTENSIONS:
                    paths.append(path)
                    if len(paths) > 1000:
                        raise ValueError('Watch folder exceeds 1000 supported files')
        walk(root)
        return root, paths

    def _scan(self, entry):
        identity = entry['watch_id']
        project = self.projects.get(entry['project_id'])
        if project['status'] != 'active':
            self.reports[identity] = dict(status='archived', error='', checked_at=_now())
            return
        root, paths = self._paths(entry)
        # Bind only after the configured folder is readable.
        project = self.projects.bind_materials(entry['project_id'])
        api_path = f"/v1/ingestion/{project['materials_namespace']}/documents"
        remote = {item.get('source_key'): item for item in self.client.get(api_path)['documents'] if item.get('source_key')}
        seen = set()
        for path in paths:
            if self.stop.is_set() or not self._enabled(identity):
                return
            relative = path.relative_to(root).as_posix()
            seen.add(relative)
            key = (identity, relative)
            source_key = f"watch:{identity}:" + hashlib.sha256(relative.encode()).hexdigest()
            data = dict(relative_path=relative, source_key=source_key, status='waiting', error='', checked_at=_now())
            existing = remote.get(source_key)
            data['change_kind'] = 'unknown' if existing else 'new'
            if existing:
                data.update(document_id=existing['id'], document_status=existing['status'])
            try:
                info = path.stat()
                stamp = _stamp(info)
                previous = self.observed.get(key)
                self.observed[key] = stamp
                if info.st_size < 1 or info.st_size > MAX_FILE_BYTES:
                    raise ValueError('파일 크기는 1 byte ~ 10 MiB여야 합니다.')
                if previous != stamp:
                    data['status'] = 'settling'
                elif existing and existing.get('desired_state') in {'excluded', 'deleted'}:
                    data['status'] = 'excluded' if existing['desired_state'] == 'excluded' else 'deleted'
                elif existing and existing['status'] in {'queued', 'indexing'}:
                    data['status'] = 'pending'
                else:
                    # Recheck containment/reparse points before reading a stable file.
                    if any(_linked(p) for p in (path, *path.parents)) or not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError('링크 경로는 등록하지 않습니다.')
                    with path.open('rb') as stream:
                        opened = os.fstat(stream.fileno())
                        if _stamp(opened) != stamp:
                            raise ValueError('파일이 변경 중입니다.')
                        content = stream.read(MAX_FILE_BYTES + 1)
                    if _stamp(path.stat()) != stamp or len(content) != info.st_size:
                        raise ValueError('파일이 변경 중입니다.')
                    digest = hashlib.sha256(content).hexdigest()
                    data['sha256'] = digest
                    data['change_kind'] = 'unchanged' if existing and existing['sha256'] == digest else ('changed' if existing else 'new')
                    if existing and existing['sha256'] == digest:
                        data['status'] = 'failed' if existing['status'] == 'failed' else 'synced'
                        data['error'] = existing.get('error', '')
                    else:
                        with self.lock:
                            if not self._enabled(identity) or self.projects.get(entry['project_id'])['status'] != 'active':
                                return
                            result = self.client.post(api_path, dict(filename=path.name, content_base64=base64.b64encode(content).decode(),
                                project=project['knowledge_project'], equipment=project['subject_id'] if project['domain_id'] == 'equipment' else '',
                                source_key=source_key, version=existing['version'] if existing else 0))
                        data.update(status='pending', document_id=result['id'])
            except ValueError as exc:
                data.update(status='error', error=str(exc))
            except AdapterError as exc:
                code = getattr(exc.__cause__, 'code', None)
                data.update(status='error', error='파일 형식 또는 자료 상태를 확인하세요.' if code in {409, 413, 422} else 'RAG 연결을 확인하세요.')
                self._save(identity, relative, data)
                if code not in {409, 413, 422}:
                    raise
            except Exception:
                logging.exception('Watched file could not be uploaded: %s / %s', identity, relative)
                data.update(status='error', error='파일 접근 또는 전송 실패. 다음 점검에서 다시 확인합니다.')
                self._save(identity, relative, data)
                raise  # Avoid one network timeout per file during an outage.
            self._save(identity, relative, data)
        # Missing originals are informational. Do not delete or exclude RAG material.
        with closing(self.connect()) as db, db:
            for relative, raw in db.execute('SELECT relative_path,data FROM files WHERE watch_id=?', (identity,)).fetchall():
                if relative not in seen:
                    self.observed.pop((identity, relative), None)
                    data = json.loads(raw)
                    data.update(status='missing', error='원본 파일 없음. 등록 자료는 유지됩니다.', checked_at=_now())
                    db.execute('UPDATE files SET data=? WHERE watch_id=? AND relative_path=?', (json.dumps(data), identity, relative))
        self.reports[identity] = dict(status='watching' if self._enabled(identity) else 'paused', error='', checked_at=_now())

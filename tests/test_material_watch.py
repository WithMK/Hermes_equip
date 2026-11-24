import base64
import hashlib
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from hermes_equipment_poc.http_client import AdapterError
from hermes_equipment_poc.material_watch import MaterialWatcher, load_watch_config
from hermes_equipment_poc.projects import ProjectStore


class Remote:
    def __init__(self):
        self.rows = {}
        self.uploads = 0

    def get(self, path):
        return {'documents': list(self.rows.values())}

    def post(self, path, value):
        if value['filename'] == 'bad.pdf':
            try:
                raise urllib.error.HTTPError('http://internal', 422, 'invalid', {}, None)
            except urllib.error.HTTPError as exc:
                raise AdapterError('private') from exc
        key = value['source_key']
        old = self.rows.get(key)
        assert value['version'] == (old['version'] if old else 0)
        self.uploads += 1
        result = dict(value, id=hashlib.sha256(key.encode()).hexdigest(),
                      version=value['version'] + 1, desired_state='active', status='ready',
                      sha256=hashlib.sha256(base64.b64decode(value['content_base64'])).hexdigest())
        self.rows[key] = result
        return result


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.folder = self.root / 'input'
        self.folder.mkdir()
        self.projects = ProjectStore(self.root / 'projects.db', 'W', 'document')
        self.projects.create('alpha', name='Alpha')
        self.remote = Remote()
        self.entries = [dict(watch_id='docs', project_id='alpha', path=str(self.folder), recursive=True)]
        self.watcher = self.new_watcher()

    def new_watcher(self):
        return MaterialWatcher(self.root / 'watch.db', self.projects, self.remote, self.entries)

    def scan(self):
        self.watcher.scan_once()
        self.watcher.scan_once()

    def test_stability_changes_duplicate_names_and_missing_original(self):
        first = self.folder / 'guide.md'
        first.write_text('original')
        (self.folder / 'sub').mkdir()
        (self.folder / 'sub' / 'guide.md').write_text('other')
        self.watcher.scan_once()
        self.assertEqual(self.remote.uploads, 0)
        self.assertTrue(all(f['change_kind']=='new' for f in self.watcher.snapshot('alpha')[0]['files']))
        self.watcher.scan_once()
        self.assertEqual(len(self.remote.rows), 2)
        self.scan()
        self.assertEqual(self.remote.uploads, 2)
        first.write_text('replacement longer')
        self.scan()
        self.assertEqual(self.remote.uploads, 3)
        self.assertEqual(self.watcher.snapshot('alpha')[0]['files'][0]['change_kind'], 'changed')
        first.unlink()
        self.scan()
        self.assertEqual(len(self.remote.rows), 2)
        self.assertEqual(self.watcher.snapshot('alpha')[0]['files'][0]['status'], 'missing')

    def test_pause_persists_and_scope_is_checked(self):
        (self.folder / 'guide.md').write_text('hello')
        self.watcher.set_enabled('alpha', 'docs', False)
        with self.assertRaises(KeyError):
            self.watcher.set_enabled('other', 'docs', True)
        self.watcher = self.new_watcher()
        self.scan()
        self.assertEqual(self.remote.uploads, 0)
        self.assertFalse(self.watcher.snapshot('alpha')[0]['enabled'])
        self.watcher.set_enabled('alpha', 'docs', True)
        self.scan()
        self.assertEqual(self.remote.uploads, 1)
        self.watcher = self.new_watcher()
        self.scan()
        self.assertEqual(self.remote.uploads, 1)

    def test_excluded_deleted_and_archived_are_not_resurrected(self):
        file = self.folder / 'guide.md'
        file.write_text('hello')
        self.scan()
        row = next(iter(self.remote.rows.values()))
        for desired in ('excluded', 'deleted'):
            row['desired_state'] = desired
            row['status'] = desired
            file.write_text(desired)
            self.scan()
            self.assertEqual(self.remote.uploads, 1)
        project = self.projects.get('alpha')
        self.projects.update('alpha', project['version'], name='Alpha', status='archived', knowledge_project=project['knowledge_project'])
        (self.folder / 'new.md').write_text('new')
        self.scan()
        self.assertEqual(self.remote.uploads, 1)
        self.assertEqual(self.watcher.snapshot('alpha')[0]['status'], 'archived')

    def test_invalid_file_does_not_block_other_uploads_and_missing_root_keeps_records(self):
        (self.folder / 'bad.pdf').write_bytes(b'not pdf')
        (self.folder / 'good.md').write_text('valid')
        self.scan()
        self.assertEqual(self.remote.uploads, 1)
        report = self.watcher.snapshot('alpha')[0]
        self.assertEqual(report['files'][0]['status'], 'error')
        self.assertNotIn('private', str(report))
        self.folder.rename(self.root / 'moved')
        with self.assertLogs(level='ERROR'):
            self.watcher.scan_once()
        self.assertEqual(len(self.remote.rows), 1)
        self.assertEqual(self.watcher.snapshot('alpha')[0]['status'], 'error')

    def test_link_escape_and_hidden_files_are_skipped(self):
        outside = self.root / 'private.md'
        outside.write_text('private')
        try:
            (self.folder / 'link.md').symlink_to(outside)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        (self.folder / '.hidden.md').write_text('hidden')
        self.scan()
        self.assertEqual(self.remote.uploads, 0)

    def test_config_validation_and_binding_immutability(self):
        config = self.root / 'watch.json'
        config.write_text(json.dumps(self.entries))
        self.assertEqual(load_watch_config(config), self.entries)
        for change in ({'path':'relative'}, {'recursive':'yes'}, {'project_id':'../alpha'}):
            config.write_text(json.dumps([{**self.entries[0], **change}]))
            with self.assertRaises(ValueError):
                load_watch_config(config)
        self.entries[0]['recursive'] = False
        with self.assertRaises(ValueError):
            self.new_watcher()


if __name__ == '__main__':
    unittest.main()

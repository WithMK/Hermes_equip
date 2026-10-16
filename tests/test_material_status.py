import unittest
from hermes_equipment_poc.material_status import material_status


def doc(identity='a', status='ready', **values):
    return dict(id=identity, status=status, desired_state='active', source_key='',
                sha256='current', indexed_sha256='current', chunks=2, **values)


def watch(*files, status='watching', enabled=True):
    return dict(watch_id='docs', status=status, enabled=enabled, checked_at='last-poll', files=list(files))


class MaterialStatusTests(unittest.TestCase):
    def test_counts_document_states_and_keeps_deleted_separate(self):
        docs = [doc(str(i), state) for i,state in enumerate(['ready','queued','indexing','failed','excluded','deleted'])]
        docs[-2]['desired_state']='excluded'; docs[-1]['desired_state']='deleted'
        summary = material_status(docs, [])
        self.assertEqual(summary['registered'], 5)
        self.assertTrue(all(value == 1 for value in summary['counts'].values()))
        self.assertEqual(summary['needs_update'], 3)
        self.assertFalse(summary['coverage_complete'])

    def test_folder_change_and_queued_document_are_counted_once(self):
        item = doc(status='queued'); item['source_key']='watch:one'; item['sha256']='old'
        file = dict(source_key='watch:one', status='pending', change_kind='changed', sha256='new')
        result = material_status([item], [watch(file)])
        self.assertEqual(result['needs_update'], 1)
        self.assertEqual(result['folder']['changed'], 1)

    def test_latest_completion_overrides_stale_folder_pending(self):
        item = doc(); item['source_key']='watch:one'
        file = dict(source_key='watch:one', status='pending', change_kind='new', sha256='current')
        result = material_status([item], [watch(file)])
        self.assertEqual(result['needs_update'], 0)
        self.assertEqual(result['folder']['new'], 0)
        self.assertTrue(result['coverage_complete'])

    def test_unregistered_files_and_unverified_changes_are_distinct(self):
        new = dict(source_key='new', status='settling', change_kind='new')
        unknown = dict(source_key='existing', status='settling', change_kind='unknown')
        result = material_status([], [watch(new, unknown)])
        self.assertEqual(result['needs_update'], 1)
        self.assertEqual(result['folder']['new'], 1)
        self.assertEqual(result['folder']['check_pending'], 1)
        self.assertFalse(result['coverage_complete'])

    def test_excluded_deleted_missing_and_paused_are_not_assumed_current(self):
        item = doc(); item.update(source_key='excluded', desired_state='excluded', status='excluded')
        excluded = dict(source_key='excluded', status='settling', change_kind='changed', sha256='new')
        missing = dict(source_key='missing', status='missing')
        result = material_status([item], [watch(excluded, missing, status='paused', enabled=False)])
        self.assertEqual(result['needs_update'], 0)
        self.assertEqual(result['folder']['missing'], 1)
        self.assertFalse(result['coverage_complete'])

    def test_unknown_file_error_is_not_reported_as_confirmed_update(self):
        error = dict(source_key='unreadable', status='error', change_kind='unknown')
        result = material_status([], [watch(error, status='error')])
        self.assertEqual(result['needs_update'], 0)
        self.assertEqual(result['folder']['errors'], 1)
        self.assertEqual(result['folder']['check_pending'], 1)

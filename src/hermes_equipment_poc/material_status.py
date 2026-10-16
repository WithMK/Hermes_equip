"""Read-only project status from RAG records and the last folder observations."""
from datetime import datetime, timezone


def material_status(documents, watches):
    counts = {s:0 for s in ('queued','indexing','ready','failed','excluded','deleted')}
    required = set()
    def identity(item):
        return item.get('source_key') or 'document:' + item['id']
    for item in documents:
        counts[item['status']] = counts.get(item['status'], 0) + 1
        if item.get('desired_state', 'active') == 'active' and (
                item['status'] in {'queued','indexing','failed'} or
                item.get('indexed_sha256') != item.get('sha256')):
            required.add(identity(item))
    by_source = {d['source_key']:d for d in documents if d.get('source_key')}
    folder = dict(new=0, changed=0, check_pending=0, errors=0, missing=0)
    for watch in watches:
        for file in watch['files']:
            status, key = file['status'], file['source_key']
            remote = by_source.get(key)
            if status == 'missing':
                folder['missing'] += 1
                continue
            if remote and remote.get('desired_state') in {'excluded','deleted'}:
                continue
            if status in {'excluded','deleted'}:
                continue
            # A recent RAG completion can be newer than the cached watch observation.
            matches = remote and file.get('sha256') and remote.get('sha256') == file['sha256']
            if matches:
                continue
            if status in {'error','failed'}:
                folder['errors'] += 1
            kind = file.get('change_kind', 'unknown')
            if kind == 'new' and not remote:
                folder['new'] += 1
                required.add(key)
            elif kind == 'changed' and file.get('sha256'):
                folder['changed'] += 1
                required.add(key)
            elif status in {'waiting','settling','error','pending'}:
                folder['check_pending'] += 1
    return dict(scope='project_managed_documents_and_configured_watches',
        observed_at=datetime.now(timezone.utc).isoformat(), counts=counts,
        registered=len(documents)-counts['deleted'], needs_update=len(required),
        chunks=sum(item.get('chunks',0) for item in documents), folder=folder,
        watches=[dict(watch_id=w['watch_id'], enabled=w['enabled'], status=w['status'],
                      checked_at=w.get('checked_at',''), error=w.get('error','')) for w in watches],
        coverage_complete=bool(watches) and not folder['check_pending'] and not folder['errors'] and all(w['enabled'] and w['status']=='watching' for w in watches),
        note='Only registered documents and observed files in configured folders are included. Folder data is from the last poll; unscanned files and CLI indexes are not counted.')

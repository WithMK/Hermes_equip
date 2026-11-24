"""Run against an EquipmentRAG checkout: real HTTP/Chroma/FTS, synthetic embedding/chat.

python tests/material_integration_smoke.py --rag-root ../EquipmentRAG
No model download or external LLM is used. This does not measure answer quality.
"""
import argparse
import base64
import gc
import socket
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import uvicorn

from hermes_equipment_poc.http_client import JsonApiClient
from hermes_equipment_poc.knowledge import EquipmentRagKnowledgeProvider
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, SingleOrchestrator
from hermes_equipment_poc.service_clients import EquipmentRagClient
from hermes_equipment_poc.web_service import create_app
from test_single_orchestrator import FakeChat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rag-root', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.rag_root.resolve()))
    sys.path.insert(0, str(args.rag_root.resolve() / 'tests'))
    from app.api import ApiApplication, EquipmentRagHttpServer
    from app.config import ChromaConfig
    from app.document_indexer import IncrementalDocumentIndexer
    from app.models.document_models import DocumentChunkMetadata
    from app.rag_service import RagService
    from app.retrieval.document_retriever import DocumentRetriever
    from app.retrieval.sqlite_fts import SQLiteFtsStore
    from app.vectorstore.chroma_store import PersistentChromaStore
    from test_api import _config
    from test_document_indexer import FakeEmbedding

    class Embedding(FakeEmbedding):
        def embed_query(self, text):
            return [1., 0., 0.]

    class EmptyCode:
        def search(self, *args, **kwargs):
            return []

    with ExitStack() as stack:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        config = _config(root)
        config = replace(config, search=replace(config.search, mode='hybrid', lexical_backend='sqlite_fts5', lexical_path=root / 'fts.db'))
        embedding = Embedding()
        vector = PersistentChromaStore(ChromaConfig(config.chromadb.path, config.document.collection_name), 3, metadata_type=DocumentChunkMetadata)
        def stop_chroma():
            if vector._client is not None:
                system = vector._client._system
                vector._client = None; vector._collection = None
                system.stop()
                from chromadb.api.client import SharedSystemClient
                SharedSystemClient.clear_system_cache()
                gc.collect()
        stack.callback(stop_chroma)
        fts = SQLiteFtsStore(root / 'fts.db')
        stack.callback(fts.close)
        indexer = IncrementalDocumentIndexer(config, embedding=embedding, vector_store=vector, lexical_store=fts)
        retriever = DocumentRetriever(config, embedding=embedding, vector_store=vector)
        key = 'smoke-test-ingestion-key-012345'
        rag_app = ApiApplication(config, ingestion_root=root / 'uploads', ingestion_key=key, ingestion_indexer=indexer,
            service_factory=lambda cfg, source: RagService(cfg, source_type=source, code_search=EmptyCode(), document_search=retriever, lexical_store=fts))
        server = EquipmentRagHttpServer(('127.0.0.1', 0), rag_app)
        rag_thread = threading.Thread(target=server.serve_forever, daemon=True)
        rag_thread.start()
        def stop_rag():
            server.shutdown(); server.server_close(); rag_thread.join(); rag_app.ingestion.close()
        stack.callback(stop_rag)
        rag_app.ingestion.start()
        rag_url = f'http://127.0.0.1:{server.server_port}'
        state = AgentOrchestraStateStore(root / 'state.db')
        state.create_workspace('W', name='Integration', domain_id='document', root_path=str(root))
        chat = FakeChat('내부 검토 후 승인합니다 [S1].')
        engine = SingleOrchestrator(state, chat=chat, knowledge_provider=EquipmentRagKnowledgeProvider(EquipmentRagClient(JsonApiClient(rag_url))), domain_id='document')
        app = create_app(engine, 'W', material_client=JsonApiClient(rag_url, api_key=key, retry_count=0))
        sock = stack.enter_context(socket.socket())
        sock.bind(('127.0.0.1', 0))
        runner = uvicorn.Server(uvicorn.Config(app, log_level='error', proxy_headers=False))
        ao_thread = threading.Thread(target=runner.run, kwargs={'sockets':[sock]}, daemon=True)
        ao_thread.start()
        def stop_ao():
            runner.should_exit = True; ao_thread.join(10)
            assert not ao_thread.is_alive(), 'A/O shutdown timeout'
        stack.callback(stop_ao)
        for _ in range(100):
            if runner.started:
                break
            time.sleep(.02)
        assert runner.started
        api = JsonApiClient(f'http://127.0.0.1:{sock.getsockname()[1]}', api_key='1', api_key_header='X-AO-Request', api_key_prefix='', retry_count=0)
        for name in ('alpha', 'beta'):
            api.post('/v1/projects', {'project_id':name, 'name':name})
        path = '/v1/projects/alpha/materials'
        upload = {'filename':'procedure.md', 'content_base64':base64.b64encode('E-024 구매 승인 전 내부 검토를 실시합니다.'.encode()).decode()}
        api.post(path, upload)
        for _ in range(200):
            document = api.get(path)['documents'][0]
            if document['status'] in {'ready', 'failed'}:
                break
            time.sleep(.02)
        assert document['status'] == 'ready', document
        summary = api.get(path + '/summary')
        assert summary['counts']['ready'] == 1 and summary['needs_update'] == 0, summary
        assert api.post(path, upload)['version'] == 1
        assert api.get('/v1/projects/beta/materials') == {'documents':[]}
        task = api.post('/v1/tasks', {'project_id':'alpha', 'objective':'E-024 구매 승인 전 절차?', 'request_kind':'document_task'})
        for _ in range(200):
            result = api.get('/v1/tasks/' + task['task_id'])
            if result['submission_status'] in {'completed', 'failed'}:
                break
            time.sleep(.02)
        assert result['status'] == 'completed', result
        assert result['evidence'] and '내부 검토' in str(chat.calls), result
        # Verify the filter with real retrieval, not merely the registration list.
        binding = api.get('/v1/projects/alpha')['knowledge_project']
        namespace = api.get('/v1/projects/alpha')['materials_namespace']
        direct = JsonApiClient(rag_url, api_key=key).get('/v1/ingestion/' + namespace + '/summary')
        assert direct['counts']['ready'] == 1 and direct['needs_indexing'] == 0, direct
        raw = JsonApiClient(rag_url)
        assert raw.post('/v1/retrieve', {'query':'E-024', 'source_type':'document', 'filters':{'document':{'project':binding}}, 'include_content':True})['result_count'] > 0
        assert raw.post('/v1/retrieve', {'query':'E-024', 'source_type':'document', 'filters':{'document':{'project':'other-project'}}})['result_count'] == 0
        query = {'query':'E-024', 'source_type':'document', 'filters':{'document':{'project':binding}}}
        def wait_document(identity, expected):
            for _ in range(300):
                value = next(d for d in api.get(path)['documents'] if d['id'] == identity)
                if value['status'] in {expected, 'failed'}:
                    break
                time.sleep(.02)
            assert value['status'] == expected, value
            return value
        for action, status, count in [('exclude','excluded',0), ('restore','ready',1), ('reindex','ready',1), ('delete','deleted',0)]:
            api.post(path + '/' + document['id'] + '/' + action, {'version': document['version']})
            document = wait_document(document['id'], status)
            assert bool(raw.post('/v1/retrieve', query)['result_count']) == bool(count), action
        # Deterministic polls exercise the watcher against the real authenticated RAG API.
        from hermes_equipment_poc.material_watch import MaterialWatcher
        folder = root / 'watched'; folder.mkdir()
        source = folder / 'guide.md'; source.write_text('E-024 watched original', encoding='utf-8')
        watcher = MaterialWatcher(root / 'watch.db', app.state.worker.projects,
            JsonApiClient(rag_url, api_key=key, retry_count=0),
            [dict(watch_id='smoke', project_id='alpha', path=str(folder), recursive=True)])
        watcher.scan_once(); watcher.scan_once()
        watched = next(d for d in api.get(path)['documents'] if d.get('source_key'))
        watched = wait_document(watched['id'], 'ready')
        assert raw.post('/v1/retrieve', query)['result_count'] > 0
        source.write_text('E-024 watched replacement longer', encoding='utf-8')
        watcher.scan_once(); watcher.scan_once()
        watched = wait_document(watched['id'], 'ready')
        assert watched['version'] == 2
        api.post(path + '/' + watched['id'] + '/delete', {'version':2})
        wait_document(watched['id'], 'deleted')
        watcher.scan_once(); watcher.scan_once()
        assert source.exists()
        assert raw.post('/v1/retrieve', query)['result_count'] == 0
        assert len(api.get(path)['documents']) == 2
        print('PASS: real HTTP/Chroma/FTS upload, scoped evidence, exclude/restore/reindex/delete, watched replacement and no resurrection')


if __name__ == '__main__':
    main()

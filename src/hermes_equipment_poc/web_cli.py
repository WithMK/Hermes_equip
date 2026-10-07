"""Start the single-user local A/O interface; no external bind option by design."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from .http_client import JsonApiClient
from .knowledge import EquipmentRagKnowledgeProvider
from .orchestrator import (AgentOrchestraStateStore, ContextManagerChatClient,
    MarkdownArtifactStore, SingleOrchestrator, SpecialistAgent, StateNotFoundError)
from .orchestrator_cli import _parser, _specialist_dispatcher
from .service_clients import EquipmentRagClient


def main(argv=None):
    parser = _parser()
    parser.description = 'Local A/O web interface (one process, http://127.0.0.1:8650)'
    parser.add_argument('--port', type=int, default=8650)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('invalid port')
    if not args.workspace_root:
        parser.error('--workspace-root is required')
    root = Path(args.workspace_root).resolve(strict=True)
    store = AgentOrchestraStateStore(args.state_db)
    try:
        workspace = store.get_workspace(args.workspace_id)
        if Path(workspace['root_path']).resolve() != root:
            parser.error('stored workspace root differs from --workspace-root')
    except StateNotFoundError:
        store.create_workspace(args.workspace_id, name=args.workspace_name, root_path=str(root))
    artifacts = MarkdownArtifactStore(args.artifact_root) if args.artifact_root else None
    if artifacts and artifacts.root.is_relative_to(root):
        parser.error('artifact root must be outside workspace')
    def client(url, key, timeout=args.timeout_seconds):
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error('service URL must be HTTP(S), without credentials/query/fragment')
        return JsonApiClient(url, os.environ.get(key, ''), timeout, retry_count=0)
    rag = EquipmentRagClient(client(args.equipment_rag_base_url, 'EQUIPMENT_RAG_API_KEY'), retrieve_path=args.equipment_rag_retrieve_path)
    chat = ContextManagerChatClient(client(args.context_manager_base_url, 'CONTEXT_MANAGER_API_KEY'), args.context_model, chat_path=args.context_chat_path, session_field=args.context_session_field)
    entries, checks = [], {}
    for agent in SpecialistAgent:
        prefix = agent.value.replace('-', '_')
        url = getattr(args, prefix + '_base_url')
        probe = client(url, 'HERMES_' + prefix.upper() + '_API_KEY', 3.0)
        entries.append({'agent_id': agent.value, 'role': agent.value,
            'endpoint': url, 'enabled': args.enable_specialists,
            'model_route': 'Hermes profile → ContextManager → llama.cpp',
            'policy': 'Read-only profile expected; live tool permissions not verified',
            'health': 'not_checked'})
        if args.enable_specialists:
            checks[agent.value] = lambda c=probe: c.get('/v1/models')
    engine = SingleOrchestrator(store, chat=chat, knowledge_provider=EquipmentRagKnowledgeProvider(rag), specialists=_specialist_dispatcher(args), artifact_store=artifacts)
    from .web_service import create_app
    import uvicorn
    uvicorn.run(create_app(engine, args.workspace_id, agents=entries, health_checks=checks),
                host='127.0.0.1', port=args.port, workers=1, proxy_headers=False)


if __name__ == '__main__':
    main()

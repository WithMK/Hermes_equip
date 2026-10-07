"""Synthetic browser-test server. Not a production service or integration proof."""
import tempfile
import os
from pathlib import Path

import uvicorn
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, MarkdownArtifactStore, SingleOrchestrator
from hermes_equipment_poc.web_service import create_app
from test_phase4_workflows import FakeChat, FakeRag
from test_specialist_delegation import FakeSpecialists


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        workspace = root / 'workspace'
        workspace.mkdir()
        store = AgentOrchestraStateStore(root / 'state.db')
        store.create_workspace('demo', name='Browser test · synthetic services', root_path=str(workspace))
        engine = SingleOrchestrator(store, FakeRag(), FakeChat(), specialists=FakeSpecialists(), artifact_store=MarkdownArtifactStore(root / 'artifacts'))
        agents = [{'agent_id': name, 'endpoint': 'synthetic fixture', 'enabled': True, 'policy': 'Browser test only'} for name in ('document-agent','code-analysis-agent','troubleshooting-agent','code-development-agent')]
        app = create_app(engine, 'demo', agents=agents, openai_api_key=os.environ.get('AO_TEST_API_KEY', ''))
        uvicorn.run(app, host='127.0.0.1', port=18650)

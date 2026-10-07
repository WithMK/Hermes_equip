from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .http_client import JsonApiClient
from .knowledge import EquipmentRagKnowledgeProvider
from .orchestrator import (
    AgentOrchestraStateStore,
    ContextManagerChatClient,
    MarkdownArtifactStore,
    OpenAiSpecialistDispatcher,
    OrchestratorExecutionError,
    OrchestratorRequest,
    RequestKind,
    SingleOrchestrator,
    SpecialistAgent,
    StateNotFoundError,
)
from .service_clients import EquipmentRagClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one bounded Agent Orchestra request"
    )
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--workspace-name", default="Equipment workspace")
    parser.add_argument("--workspace-root", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--objective", default="")
    parser.add_argument("--decision-task-id", action="append", default=[])
    parser.add_argument("--create-artifact", action="store_true")
    parser.add_argument("--artifact-root", default="")
    parser.add_argument("--restart-task-id", default="")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--confirm-worker-stopped", action="store_true")
    parser.add_argument("--equipment-id")
    parser.add_argument("--domain", choices=["equipment", "document"], default="equipment")
    parser.add_argument("--subject-id")
    parser.add_argument("--request-kind", choices=[item.value for item in RequestKind])
    parser.add_argument("--knowledge-scope", action="append", default=[])
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--equipment-rag-base-url", required=True)
    parser.add_argument("--equipment-rag-retrieve-path", default="/v1/retrieve")
    parser.add_argument("--context-manager-base-url", required=True)
    parser.add_argument("--context-chat-path", default="/v1/chat/completions")
    parser.add_argument(
        "--context-model", default="Qwen3.8-27B-UD-Q5_K_XL.gguf",
        help="Model ID forwarded through ContextManager to llama.cpp; override for server --alias",
    )
    parser.add_argument("--context-session-field", default="session_id")
    parser.add_argument(
        "--enable-specialists",
        action="store_true",
        help="Delegate non-question requests to the four Hermes specialist gateways",
    )
    parser.add_argument(
        "--document-agent-base-url", default="http://127.0.0.1:8642"
    )
    parser.add_argument(
        "--code-analysis-agent-base-url", default="http://127.0.0.1:8643"
    )
    parser.add_argument(
        "--troubleshooting-agent-base-url", default="http://127.0.0.1:8644"
    )
    parser.add_argument(
        "--code-development-agent-base-url", default="http://127.0.0.1:8645"
    )
    parser.add_argument("--specialist-chat-path", default="/v1/chat/completions")
    parser.add_argument("--specialist-session-field", default="")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def _specialist_dispatcher(args: argparse.Namespace) -> OpenAiSpecialistDispatcher | None:
    if not args.enable_specialists:
        return None
    settings = {
        SpecialistAgent.DOCUMENT: (
            args.document_agent_base_url,
            "HERMES_DOCUMENT_AGENT_API_KEY",
        ),
        SpecialistAgent.CODE_ANALYSIS: (
            args.code_analysis_agent_base_url,
            "HERMES_CODE_ANALYSIS_AGENT_API_KEY",
        ),
        SpecialistAgent.TROUBLESHOOTING: (
            args.troubleshooting_agent_base_url,
            "HERMES_TROUBLESHOOTING_AGENT_API_KEY",
        ),
        SpecialistAgent.CODE_DEVELOPMENT: (
            args.code_development_agent_base_url,
            "HERMES_CODE_DEVELOPMENT_AGENT_API_KEY",
        ),
    }
    providers = {
        agent: ContextManagerChatClient(
            JsonApiClient(
                base_url,
                os.environ.get(api_key_name, ""),
                args.timeout_seconds,
            ),
            agent.value,
            chat_path=args.specialist_chat_path,
            session_field=args.specialist_session_field,
        )
        for agent, (base_url, api_key_name) in settings.items()
    }
    return OpenAiSpecialistDispatcher(providers)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = AgentOrchestraStateStore(Path(args.state_db))
        try:
            workspace = store.get_workspace(args.workspace_id)
            if workspace["domain_id"] != args.domain:
                raise ValueError("stored workspace domain differs from --domain")
        except StateNotFoundError:
            store.create_workspace(
                args.workspace_id,
                name=args.workspace_name,
                root_path=args.workspace_root,
                domain_id=args.domain,
            )
        rag = EquipmentRagClient(
            JsonApiClient(
                args.equipment_rag_base_url,
                os.environ.get("EQUIPMENT_RAG_API_KEY", ""),
                args.timeout_seconds,
            ),
            retrieve_path=args.equipment_rag_retrieve_path,
        )
        chat = ContextManagerChatClient(
            JsonApiClient(
                args.context_manager_base_url,
                os.environ.get("CONTEXT_MANAGER_API_KEY", ""),
                args.timeout_seconds,
            ),
            args.context_model,
            chat_path=args.context_chat_path,
            session_field=args.context_session_field,
        )
        artifact_store = None
        if args.artifact_root:
            artifact_store = MarkdownArtifactStore(args.artifact_root)
        if args.create_artifact and artifact_store is None:
            raise ValueError("--artifact-root is required with --create-artifact")
        if args.create_artifact:
            if not args.workspace_root:
                raise ValueError("--workspace-root is required with --create-artifact")
            workspace_root = Path(args.workspace_root).resolve(strict=True)
            try:
                artifact_store.root.relative_to(workspace_root)  # type: ignore[union-attr]
            except ValueError:
                pass
            else:
                raise ValueError("artifact root must be outside workspace root")
        orchestrator = SingleOrchestrator(
            store,
            chat=chat,
            knowledge_provider=EquipmentRagKnowledgeProvider(rag),
            domain_id=args.domain,
            specialists=_specialist_dispatcher(args),
            artifact_store=artifact_store,
        )
        if args.restart_task_id:
            if not args.confirm_worker_stopped or args.expected_version is None:
                raise ValueError("restart requires --confirm-worker-stopped and --expected-version")
            if store.get_task(args.restart_task_id).workspace_id != args.workspace_id:
                raise ValueError("restart workspace mismatch")
            result = orchestrator.restart(args.restart_task_id, expected_version=args.expected_version)
            print(json.dumps({"ok": True, **asdict(result)}, ensure_ascii=False, indent=2))
            return 0
        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id=args.workspace_id,
                objective=args.objective,
                task_id=args.task_id,
                session_id=args.session_id,
                equipment_id=args.equipment_id,
                domain_id=args.domain,
                subject_id=args.subject_id,
                request_kind=(
                    RequestKind(args.request_kind) if args.request_kind else None
                ),
                constraints=tuple(args.constraint),
                decisions=tuple(args.decision),
                knowledge_scopes=tuple(args.knowledge_scope),
                top_k=args.top_k,
                decision_task_ids=tuple(args.decision_task_id),
                create_artifact=args.create_artifact,
            )
        )
        print(json.dumps({"ok": True, **asdict(result)}, ensure_ascii=False, indent=2))
        return 0
    except OrchestratorExecutionError as exc:
        print(
            json.dumps(
                {"ok": False, "task_id": exc.task_id, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from .audit import AuditWriter
from .build_tools import BuildTools
from .file_tools import FileTools
from .git_tools import GitTools
from .http_client import JsonApiClient
from .knowledge_tools import KnowledgeTools
from .merge_broker import MergeApprovalBroker
from .service_clients import (
    DEFAULT_TAXONOMY_DOCUMENT_TYPES,
    ContextManagerClient,
    EquipmentRagClient,
)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


def _register(ctx: Any, name: str, toolset: str, handler: Callable[..., Any], description: str,
              properties: dict[str, Any], required: list[str] | None = None) -> None:
    ctx.register_tool(
        name=name,
        toolset=toolset,
        schema=_schema(name, description, properties, required),
        handler=handler,
        description=description,
    )


def register(ctx: Any) -> None:
    workspace_root = Path(str(ctx.get_config("workspace_root", "."))).expanduser().resolve(strict=True)
    rag_http = JsonApiClient(
        str(ctx.get_config("equipment_rag.base_url", "http://127.0.0.1:8765")),
        os.environ.get("EQUIPMENT_RAG_API_KEY", ""),
        float(ctx.get_config("equipment_rag.timeout_seconds", 20)),
        int(ctx.get_config("equipment_rag.retry_count", 1)),
        int(ctx.get_config("equipment_rag.max_response_bytes", 2_000_000)),
        str(ctx.get_config("equipment_rag.api_key_header", "Authorization")),
        str(ctx.get_config("equipment_rag.api_key_prefix", "Bearer ")),
    )
    context_http = JsonApiClient(
        str(ctx.get_config("context_manager.base_url", "http://127.0.0.1:8091")),
        os.environ.get("CONTEXT_MANAGER_API_KEY", ""),
        float(ctx.get_config("context_manager.timeout_seconds", 20)),
        int(ctx.get_config("context_manager.retry_count", 1)),
        int(ctx.get_config("context_manager.max_response_bytes", 2_000_000)),
        str(ctx.get_config("context_manager.api_key_header", "Authorization")),
        str(ctx.get_config("context_manager.api_key_prefix", "Bearer ")),
    )
    raw_taxonomy_map = ctx.get_config(
        "equipment_rag.taxonomy_document_types", DEFAULT_TAXONOMY_DOCUMENT_TYPES
    )
    if not isinstance(raw_taxonomy_map, dict):
        raise ValueError("equipment_rag.taxonomy_document_types must be an object")
    rag = EquipmentRagClient(
        rag_http,
        str(ctx.get_config("equipment_rag.retrieve_path", "/v1/retrieve")),
        str(ctx.get_config("equipment_rag.health_path", "/health")),
        {str(key).zfill(2): str(value) for key, value in raw_taxonomy_map.items()},
    )
    context = ContextManagerClient(
        context_http,
        str(ctx.get_config("context_manager.paths.get_context", "/context")),
        str(ctx.get_config("context_manager.paths.get_project_context", "/context/project")),
        str(ctx.get_config("context_manager.paths.get_equipment_context", "/context/equipment")),
        str(ctx.get_config("context_manager.paths.resolve_entity", "/context/resolve-entity")),
        str(ctx.get_config("context_manager.paths.health", "/health")),
    )
    knowledge = KnowledgeTools(rag, context)
    git = GitTools(workspace_root, int(ctx.get_config("git.timeout_seconds", 60)))
    approval_store_value = ctx.get_config("git.approval_store")
    if not approval_store_value:
        raise ValueError("plugins.entries.hermes-equipment-platform.settings.git.approval_store is required")
    approval_store = Path(str(approval_store_value)).expanduser().resolve(strict=False)
    try:
        approval_store.relative_to(workspace_root)
    except ValueError:
        pass
    else:
        raise ValueError("git.approval_store must be outside workspace_root")
    merge_broker = MergeApprovalBroker(approval_store, git)
    allowed_build_targets = ctx.get_config("build.allowed_targets", [])
    if not isinstance(allowed_build_targets, list):
        raise ValueError("build.allowed_targets must be an array")
    build = BuildTools(
        workspace_root,
        int(ctx.get_config("build.timeout_seconds", 600)),
        [str(value) for value in allowed_build_targets],
    )
    files = FileTools(workspace_root, int(ctx.get_config("files.max_bytes", 2_000_000)))
    audit = AuditWriter(
        Path(str(ctx.get_config("audit.path", workspace_root / ".poc-audit" / "events.jsonl"))),
        ctx.profile_name,
    )

    query_prop = {
        "query": {"type": "string"},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
        "include_content": {"type": "boolean"},
    }
    code_prop = {**query_prop, **{
        key: {"type": "string"} for key in
        ("equipment", "repository", "relative_path", "class_name", "method_name")
    }}
    document_prop = {**query_prop, **{
        key: {"type": "string"} for key in
        ("project", "equipment", "unit", "revision", "document_status")
    }, "is_latest": {"type": "boolean"}}
    scope_prop = {
        **document_prop,
        "repository": {"type": "string"},
        "knowledge_scope": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(DEFAULT_TAXONOMY_DOCUMENT_TYPES)},
            "minItems": 1,
            "uniqueItems": True,
        },
    }
    _register(ctx, "search_code", "equipment_rag_code", knowledge.search_code, "Search C# equipment control code evidence through EquipmentRAG /v1/retrieve.", code_prop, ["query"])
    _register(ctx, "search_document", "equipment_rag_document", knowledge.search_document, "Search equipment documents within selected taxonomy scopes.", scope_prop, ["query", "knowledge_scope"])
    _register(ctx, "retrieve_evidence", "equipment_rag_document", knowledge.retrieve_evidence, "Retrieve combined code and document evidence with source identifiers.", scope_prop, ["query", "knowledge_scope"])

    _register(ctx, "get_context", "context_manager", knowledge.get_context, "Read current persistent work context.", {"session_id": {"type": "string"}})
    _register(ctx, "get_project_context", "context_manager", knowledge.get_project_context, "Read current project context.", {"project_id": {"type": "string"}})
    _register(ctx, "get_equipment_context", "context_manager", knowledge.get_equipment_context, "Read current equipment context.", {"equipment_id": {"type": "string"}})
    _register(ctx, "resolve_recent_entity", "context_manager", knowledge.resolve_recent_entity, "Resolve a follow-up reference using persistent context.", {"session_id": {"type": "string"}, "utterance": {"type": "string"}}, ["utterance"])

    taxonomy_path = Path(__file__).resolve().parent / "resources" / "equipment_taxonomy.md"

    def get_knowledge_taxonomy(params: dict[str, Any], **_: Any) -> dict[str, Any]:
        del params
        return {"path": str(taxonomy_path), "content": taxonomy_path.read_text(encoding="utf-8")}

    _register(ctx, "get_knowledge_taxonomy", "knowledge_taxonomy", get_knowledge_taxonomy, "Load the canonical equipment knowledge taxonomy before selecting retrieval scope.", {})

    path_prop = {"path": {"type": "string", "description": "Path under configured workspace root"}}
    _register(ctx, "read_workspace_file", "workspace_read", files.read_workspace_file, "Read a bounded UTF-8 text file under the configured workspace root.", path_prop, ["path"])
    _register(ctx, "write_workspace_file", "workspace_write", files.write_workspace_file, "Create or compare-and-swap overwrite a UTF-8 text file under the workspace root.", {**path_prop, "content": {"type": "string"}, "expected_sha256": {"type": "string"}}, ["path", "content"])
    _register(ctx, "search_log", "log_read", files.search_log, "Search a bounded set of lines in an allowlisted log file.", {**path_prop, "pattern": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, ["path", "pattern"])

    repo_prop = {"repo": {"type": "string", "description": "Repository path under configured workspace root"}}
    _register(ctx, "git_get_status", "git_read", git.get_status, "Get repository status.", repo_prop)
    _register(ctx, "git_get_diff", "git_read", git.get_diff, "Get working tree or staged diff.", {**repo_prop, "staged": {"type": "boolean"}})
    _register(ctx, "git_get_log", "git_read", git.get_log, "Get bounded Git history.", {**repo_prop, "limit": {"type": "integer", "minimum": 1, "maximum": 100}})
    _register(ctx, "git_list_branches", "git_read", git.list_branches, "List local branches.", repo_prop)

    _register(ctx, "git_create_branch", "git_write", git.create_branch, "Create and checkout a non-protected work branch.", {**repo_prop, "name": {"type": "string"}}, ["name"])
    _register(ctx, "git_checkout_work_branch", "git_write", git.checkout_work_branch, "Checkout an existing non-protected work branch.", {**repo_prop, "name": {"type": "string"}}, ["name"])
    _register(ctx, "git_stage_files", "git_write", git.stage_files, "Stage explicit files only.", {**repo_prop, "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, ["paths"])
    _register(ctx, "git_commit_work_branch", "git_write", git.commit_work_branch, "Commit staged changes on a non-protected work branch.", {**repo_prop, "message": {"type": "string"}}, ["message"])
    _register(ctx, "request_main_merge", "git_merge_request", merge_broker.request, "Create a one-time human approval request for an exact source SHA. This tool cannot execute a merge.", {**repo_prop, "source_branch": {"type": "string"}, "expected_sha": {"type": "string"}}, ["source_branch", "expected_sha"])

    build_prop = {"solution": {"type": "string"}, "configuration": {"type": "string", "enum": ["Debug", "Release"]}}
    _register(ctx, "build_solution", "dotnet_build", build.build_solution, "Build an allowlisted .NET solution or project without arbitrary shell.", build_prop, ["solution"])
    _register(ctx, "run_tests", "dotnet_build", build.run_tests, "Run dotnet tests for an allowlisted solution or project.", build_prop, ["solution"])

    ctx.register_hook("pre_tool_call", audit.pre_tool_call)
    ctx.register_hook("post_tool_call", audit.post_tool_call)
    ctx.register_hook("on_skill_lifecycle", audit.skill_lifecycle)
    ctx.register_hook("pre_approval_request", audit.approval_request)
    ctx.register_hook("post_approval_response", audit.approval_response)

from __future__ import annotations

from typing import Any

from .service_clients import ContextManagerClient, EquipmentRagClient


VALID_SCOPES = {f"{i:02d}" for i in range(8)}


class KnowledgeTools:
    def __init__(self, rag: EquipmentRagClient, context: ContextManagerClient):
        self.rag = rag
        self.context = context

    @staticmethod
    def _query(params: dict[str, Any]) -> str:
        query = str(params.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        return query

    @staticmethod
    def _scopes(params: dict[str, Any]) -> list[str]:
        raw = params.get("knowledge_scope") or []
        scopes = [str(item).zfill(2) for item in raw]
        invalid = sorted(set(scopes) - VALID_SCOPES)
        if invalid:
            raise ValueError(f"invalid knowledge scopes: {invalid}")
        return scopes

    def search_code(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.rag.retrieve(
            query=self._query(params),
            source_type="code",
            top_k=int(params.get("top_k", 8)),
            include_content=bool(params.get("include_content", True)),
            code_filters={key: params.get(key) for key in (
                "equipment", "repository", "relative_path", "class_name", "method_name"
            )},
        )

    def search_document(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.rag.retrieve(
            query=self._query(params),
            source_type="document",
            top_k=int(params.get("top_k", 8)),
            include_content=bool(params.get("include_content", True)),
            document_filters={key: params.get(key) for key in (
                "project", "equipment", "unit", "revision", "document_status", "is_latest"
            )},
            knowledge_scopes=self._scopes(params),
        )

    def retrieve_evidence(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.rag.retrieve(
            query=self._query(params),
            source_type="all",
            top_k=int(params.get("top_k", 12)),
            include_content=bool(params.get("include_content", True)),
            code_filters={key: params.get(key) for key in ("equipment", "repository")},
            document_filters={key: params.get(key) for key in (
                "project", "equipment", "unit", "revision", "document_status", "is_latest"
            )},
            knowledge_scopes=self._scopes(params),
        )

    def get_context(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.context.get_context(str(params.get("session_id", "")))

    def get_project_context(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.context.get_project_context(str(params.get("project_id", "")))

    def get_equipment_context(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.context.get_equipment_context(str(params.get("equipment_id", "")))

    def resolve_recent_entity(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self.context.resolve_entity(
            str(params.get("session_id", "")),
            str(params.get("utterance", "")).strip(),
        )

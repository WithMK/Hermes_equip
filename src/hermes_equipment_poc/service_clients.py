from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .http_client import JsonApiClient


DEFAULT_TAXONOMY_DOCUMENT_TYPES = {
    "00": "00 External",
    "01": "01 Equipment Requirement / Specification",
    "02": "02 Design Change / Risk",
    "03": "03 Meeting / Issue",
    "04": "04 Equipment Decision",
    "05": "05 Test / Experiment / Result",
    "06": "06 Operation / Trouble / Alarm",
    "07": "07 Deliverable / Report",
}


@dataclass(frozen=True)
class EquipmentRagClient:
    """Client for WithMK/EquipmentRAG's read-only v1 API."""

    http: JsonApiClient
    retrieve_path: str = "/v1/retrieve"
    health_path: str = "/health"
    taxonomy_document_types: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_TAXONOMY_DOCUMENT_TYPES)
    )

    def health(self) -> dict[str, Any]:
        return self.http.get(self.health_path)

    def retrieve(
        self,
        *,
        query: str,
        source_type: str,
        top_k: int,
        include_content: bool = False,
        code_filters: dict[str, Any] | None = None,
        document_filters: dict[str, Any] | None = None,
        knowledge_scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        if source_type not in {"code", "document", "all"}:
            raise ValueError("source_type must be code, document, or all")
        scopes = knowledge_scopes or []
        if not scopes:
            return self._retrieve_once(
                query, source_type, top_k, include_content, code_filters, document_filters
            )

        responses: list[dict[str, Any]] = []
        for scope in scopes:
            mapped_type = self.taxonomy_document_types.get(scope)
            if not mapped_type:
                raise ValueError(f"No EquipmentRAG document_type mapping for scope {scope}")
            scoped_document = dict(document_filters or {})
            scoped_document["document_type"] = mapped_type
            responses.append(
                self._retrieve_once(
                    query,
                    source_type,
                    top_k,
                    include_content,
                    code_filters,
                    scoped_document,
                )
            )
        return _merge_retrieval_responses(query, source_type, top_k, responses)

    def _retrieve_once(
        self,
        query: str,
        source_type: str,
        top_k: int,
        include_content: bool,
        code_filters: dict[str, Any] | None,
        document_filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if source_type in {"code", "all"} and code_filters:
            filters["code"] = _without_empty(code_filters)
        if source_type in {"document", "all"} and document_filters:
            filters["document"] = _without_empty(document_filters)
        payload: dict[str, Any] = {
            "query": query,
            "source_type": source_type,
            "top_k": top_k,
            "include_content": include_content,
        }
        if filters:
            payload["filters"] = filters
        return self.http.post(self.retrieve_path, payload)


def _without_empty(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "")}


def _merge_retrieval_responses(
    query: str, source_type: str, top_k: int, responses: list[dict[str, Any]]
) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    for response in responses:
        for source in response.get("sources", []):
            if not isinstance(source, dict):
                continue
            identity = str(source.get("record_id") or source.get("source_id") or source)
            existing = by_id.get(identity)
            if existing is None or float(source.get("score", 0)) > float(existing.get("score", 0)):
                by_id[identity] = source
    sources = sorted(by_id.values(), key=lambda item: float(item.get("score", 0)), reverse=True)[:top_k]
    for index, source in enumerate(sources, 1):
        source["source_id"] = f"S{index}"
    return {
        "query": query,
        "source_type": source_type,
        "result_count": len(sources),
        "sources": sources,
        "scope_requests": len(responses),
    }

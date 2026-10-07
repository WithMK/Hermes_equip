"""Read-only knowledge boundary; no LLM, indexing, or workspace authorization here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class KnowledgeQuery:
    query: str
    source_type: str = "all"
    top_k: int = 8
    subject_id: str | None = None
    scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("knowledge query is required")
        if self.source_type not in {"all", "code", "document"}:
            raise ValueError("unsupported knowledge source type")
        if type(self.top_k) is not int or not 1 <= self.top_k <= 20:
            raise ValueError("knowledge top_k must be between 1 and 20")


@dataclass(frozen=True)
class KnowledgeResult:
    provider_id: str
    sources: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("knowledge provider_id is required")
        seen: set[str] = set()
        copied = []
        for source in self.sources:
            item = dict(source)
            source_id = item.get("source_id")
            if not isinstance(source_id, str) or not source_id.strip() or source_id in seen:
                raise ValueError("knowledge source_id must be non-empty and unique")
            if item.get("source_type") not in {"code", "document"}:
                raise ValueError("unsupported knowledge source type")
            seen.add(source_id)
            copied.append(item)
        object.__setattr__(self, "sources", tuple(copied))


class KnowledgeProvider(Protocol):
    """Return cited code/document evidence, not a generated answer.

    Provider selection is operator-owned. subject_id is a retrieval filter,
    NOT a tenant or authorization boundary. Providers must not silently ignore
    unsupported filters. Source IDs are unique within a result; record IDs are
    provider-local. Content uses text/code and labels use file_name/relative_path.
    """

    def search(self, request: KnowledgeQuery) -> KnowledgeResult: ...


class RetrievalProvider(Protocol):
    """Legacy EquipmentRAG client contract retained for existing integrations."""

    def retrieve(
        self, *, query: str, source_type: str, top_k: int,
        include_content: bool = False,
        code_filters: dict[str, Any] | None = None,
        document_filters: dict[str, Any] | None = None,
        knowledge_scopes: list[str] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EquipmentRagKnowledgeProvider:
    """Translate the generic query to the existing EquipmentRAG v1 API."""

    client: RetrievalProvider
    provider_id: str = "equipment-rag"

    def search(self, request: KnowledgeQuery) -> KnowledgeResult:
        response = self.client.retrieve(
            query=request.query, source_type=request.source_type,
            top_k=request.top_k, include_content=True,
            code_filters={"equipment": request.subject_id},
            document_filters={"equipment": request.subject_id},
            knowledge_scopes=list(request.scopes),
        )
        raw = response.get("sources")
        if not isinstance(raw, list):
            raise ValueError("EquipmentRAG sources must be an array")
        sources = []
        for index, source in enumerate(raw, 1):
            if not isinstance(source, dict):
                raise ValueError("EquipmentRAG source must be an object")
            item = dict(source)
            item["source_id"] = str(item.get("source_id") or f"S{index}").strip()
            # Compatibility with old servers omitting source_type.
            item.setdefault("source_type", "document" if "text" in item else "code")
            sources.append(item)
        result = KnowledgeResult(self.provider_id, tuple(sources))
        return KnowledgeResult(result.provider_id, result.sources[:request.top_k])

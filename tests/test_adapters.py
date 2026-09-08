from __future__ import annotations

import unittest
from typing import Any

from hermes_equipment_poc.knowledge_tools import KnowledgeTools
from hermes_equipment_poc.service_clients import ContextManagerClient, EquipmentRagClient


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def get(self, path: str) -> dict[str, Any]:
        self.calls.append(("GET", path, None))
        return {"status": "ok"}

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", path, payload))
        if "source_type" not in payload:
            return {"status": "ok", "session_id": payload.get("session_id")}
        document_type = payload.get("filters", {}).get("document", {}).get("document_type", "")
        suffix = document_type[:2] if document_type else payload["source_type"]
        return {
            "query": payload["query"],
            "source_type": payload["source_type"],
            "result_count": 1,
            "sources": [{"record_id": f"record-{suffix}", "source_id": "S1", "score": 0.8}],
        }


class EquipmentRagAdapterTests(unittest.TestCase):
    def test_uses_repository_v1_contract_for_code(self) -> None:
        http = FakeHttp()
        tools = KnowledgeTools(EquipmentRagClient(http), ContextManagerClient(http))  # type: ignore[arg-type]

        result = tools.search_code({"query": "Vacuum", "top_k": 4, "class_name": "Loader"})

        self.assertEqual(result["result_count"], 1)
        method, path, payload = http.calls[0]
        self.assertEqual((method, path), ("POST", "/v1/retrieve"))
        assert payload is not None
        self.assertEqual(payload["source_type"], "code")
        self.assertEqual(payload["filters"]["code"]["class_name"], "Loader")

    def test_multiple_taxonomy_scopes_are_merged_and_deduplicated(self) -> None:
        http = FakeHttp()
        tools = KnowledgeTools(EquipmentRagClient(http), ContextManagerClient(http))  # type: ignore[arg-type]

        result = tools.search_document({
            "query": "Alarm",
            "knowledge_scope": ["03", "06"],
            "top_k": 5,
        })

        self.assertEqual(result["scope_requests"], 2)
        self.assertEqual(result["result_count"], 2)
        self.assertEqual(
            http.calls[0][2]["filters"]["document"]["document_type"],  # type: ignore[index]
            "03 Meeting / Issue",
        )
        self.assertEqual(
            http.calls[1][2]["filters"]["document"]["document_type"],  # type: ignore[index]
            "06 Operation / Trouble / Alarm",
        )

    def test_context_paths_can_be_replaced_without_code_change(self) -> None:
        http = FakeHttp()
        context = ContextManagerClient(
            http,  # type: ignore[arg-type]
            get_context_path="/api/session/read",
            resolve_entity_path="/api/entity/resolve",
        )

        context.get_context("s1")
        context.resolve_entity("s1", "그 센서")

        self.assertEqual(http.calls[0], ("POST", "/api/session/read", {"session_id": "s1"}))
        self.assertEqual(
            http.calls[1],
            ("POST", "/api/entity/resolve", {"session_id": "s1", "utterance": "그 센서"}),
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_equipment_poc.knowledge import (
    EquipmentRagKnowledgeProvider, KnowledgeQuery, KnowledgeResult,
)
from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore, ContextManagerChatClient, OrchestratorExecutionError,
    OrchestratorRequest, RequestKind, SingleOrchestrator, TaskStatus,
)
from hermes_equipment_poc.orchestrator_cli import _parser
from hermes_equipment_poc.service_clients import EquipmentRagClient
from test_single_orchestrator import FakeChat, FakeRag


SOURCE = {"source_id": "S1", "record_id": "manual-1", "source_type": "document",
          "file_name": "guide.md", "text": "Review the input before proceeding."}


class FakeProvider:
    def __init__(self, sources=(SOURCE,)):
        self.sources = sources
        self.calls = []

    def search(self, request):
        self.calls.append(request)
        return KnowledgeResult("document-library", self.sources)


class KnowledgeProviderTests(unittest.TestCase):
    def test_existing_http_contract_and_subject_scope_mapping(self):
        class Http:
            def post(self, path, payload):
                self.path, self.payload = path, payload
                return {"sources": [SOURCE]}
        http = Http()
        provider = EquipmentRagKnowledgeProvider(EquipmentRagClient(http))
        result = provider.search(KnowledgeQuery("alarm", "document", 3, "E-024", ("06",)))
        self.assertEqual(http.path, "/v1/retrieve")
        self.assertEqual(http.payload, {
            "query": "alarm", "source_type": "document", "top_k": 3, "include_content": True,
            "filters": {"document": {"equipment": "E-024", "document_type": "06 Operation / Trouble / Alarm"}},
        })
        self.assertEqual(result.provider_id, "equipment-rag")
        self.assertEqual(result.sources[0]["record_id"], "manual-1")
        self.assertEqual(SOURCE["source_id"], "S1")

    def test_invalid_scope_fails_before_http(self):
        provider = EquipmentRagKnowledgeProvider(EquipmentRagClient(None))
        with self.assertRaises(ValueError):
            provider.search(KnowledgeQuery("test", scopes=("unknown",)))

    def test_query_validation(self):
        for kwargs in ({"query": " "}, {"query": "x", "top_k": 0},
                       {"query": "x", "top_k": True}, {"query": "x", "source_type": "sql"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                KnowledgeQuery(**kwargs)

    def test_bad_results_fail_closed(self):
        for raw in (None, "bad", [None], [SOURCE, SOURCE], [{**SOURCE, "source_type": "sql"}]):
            class Client:
                def retrieve(self, **kwargs):
                    return {"sources": raw}
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                EquipmentRagKnowledgeProvider(Client()).search(KnowledgeQuery("x"))

    def test_legacy_missing_source_type_and_top_k(self):
        rag = FakeRag([{"text": "first"}, {"text": "second"}])
        result = EquipmentRagKnowledgeProvider(rag).search(KnowledgeQuery("x", top_k=1))
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0]["source_id"], "S1")
        self.assertEqual(result.sources[0]["source_type"], "document")

    def test_alternative_provider_completes_without_equipment_rag(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AgentOrchestraStateStore(Path(folder) / "state.db")
            store.create_workspace("docs", name="Documents")
            provider, chat = FakeProvider(), FakeChat("Review the input [S1].")
            engine = SingleOrchestrator(store, chat=chat, knowledge_provider=provider)
            result = engine.run(OrchestratorRequest(
                "docs", "Summarize the guide", request_kind=RequestKind.DOCUMENT_TASK))
            self.assertEqual(result.evidence[0].record_id, "manual-1")
            self.assertEqual(provider.calls[0].source_type, "document")
            self.assertIsNone(provider.calls[0].subject_id)
            self.assertEqual(store.get_task(result.task_id).status, TaskStatus.COMPLETED)

    def test_empty_provider_does_not_call_llm(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AgentOrchestraStateStore(Path(folder) / "state.db")
            store.create_workspace("docs", name="Documents")
            chat = FakeChat()
            result = SingleOrchestrator(store, chat=chat, knowledge_provider=FakeProvider(())).run(
                OrchestratorRequest("docs", "Summarize", request_kind=RequestKind.DOCUMENT_TASK))
            self.assertEqual(result.finish_reason, "no_evidence")
            self.assertEqual(chat.calls, [])

    def test_provider_error_fails_task_without_llm_fallback(self):
        class Broken:
            def search(self, request):
                raise RuntimeError("provider unavailable")
        with tempfile.TemporaryDirectory() as folder:
            store = AgentOrchestraStateStore(Path(folder) / "state.db")
            store.create_workspace("docs", name="Documents")
            chat = FakeChat()
            with self.assertRaises(OrchestratorExecutionError):
                SingleOrchestrator(store, chat=chat, knowledge_provider=Broken()).run(
                    OrchestratorRequest("docs", "Summarize", task_id="failed", request_kind=RequestKind.DOCUMENT_TASK))
            self.assertEqual(store.get_task("failed").status, TaskStatus.FAILED)
            self.assertEqual(chat.calls, [])

    def test_ambiguous_or_missing_provider_rejected(self):
        for kwargs in ({}, {"rag": FakeRag(), "knowledge_provider": FakeProvider()}):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                SingleOrchestrator(None, chat=FakeChat(), **kwargs)

    def test_llama_cpp_default_and_alias_forwarded_to_context_manager(self):
        base = ["--state-db", "state.db", "--workspace-id", "docs",
                "--equipment-rag-base-url", "http://127.0.0.1:8765",
                "--context-manager-base-url", "http://127.0.0.1:8091"]
        for extra, model in (([], "Qwen3.8-27B-UD-Q5_K_XL.gguf"),
                             (["--context-model", "local-qwen"], "local-qwen")):
            args = _parser().parse_args(base + extra)
            class Http:
                def post(self, path, payload):
                    self.path, self.payload = path, payload
                    return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
            http = Http()
            ContextManagerChatClient(http, args.context_model).complete(
                [{"role": "user", "content": "Hello"}], session_id="session-1")
            self.assertEqual(http.path, "/v1/chat/completions")
            self.assertEqual(http.payload["model"], model)
            self.assertEqual(http.payload["session_id"], "session-1")

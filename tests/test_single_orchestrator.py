from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore,
    ChatCompletionResult,
    OrchestratorExecutionError,
    OrchestratorRequest,
    RequestClassifier,
    RequestKind,
    SingleOrchestrator,
    TaskStatus,
)


class FakeRag:
    def __init__(self, sources: list[dict[str, Any]] | None = None) -> None:
        self.sources = sources or []
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"result_count": len(self.sources), "sources": self.sources}


class FakeChat:
    def __init__(self, content: str = "일반 답변") -> None:
        self.result = ChatCompletionResult(
            content=content,
            model="local-model",
            finish_reason="stop",
            usage={"total_tokens": 42},
        )
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session_id: str = "",
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> ChatCompletionResult:
        self.calls.append(
            {
                "messages": list(messages),
                "session_id": session_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.result


class SingleOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AgentOrchestraStateStore(Path(self.temp.name) / "orchestra.db")
        self.store.create_workspace("trim-project", name="MLCC trimming")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def document_source() -> dict[str, Any]:
        return {
            "source_id": "S1",
            "record_id": "doc-1",
            "source_type": "document",
            "file_name": "vacuum-manual.md",
            "section": "Alarm recovery",
            "text": "Check Vacuum Sensor input before replacing the valve.",
        }

    def test_troubleshooting_request_retrieves_cites_and_completes(self) -> None:
        rag = FakeRag([self.document_source()])
        chat = FakeChat("Vacuum Sensor 입력을 먼저 확인하세요 [S1].")
        orchestrator = SingleOrchestrator(self.store, rag, chat)

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-1",
                session_id="conversation-1",
                objective="Loader Vacuum 알람 원인과 조치 방법을 분석해줘",
                equipment_id="E-024",
                constraints=("설비를 직접 제어하지 않는다",),
                decisions=("Vacuum Sensor 입력을 우선 확인한다",),
                knowledge_scopes=("06",),
            )
        )

        task = self.store.get_task("TASK-1")
        self.assertEqual(result.request_kind, RequestKind.TROUBLESHOOTING)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual([item.source_id for item in task.evidence], ["S1"])
        self.assertEqual(task.decisions, ["Vacuum Sensor 입력을 우선 확인한다"])
        self.assertEqual(chat.calls[0]["session_id"], "conversation-1")
        self.assertIn("[S1]", chat.calls[0]["messages"][1]["content"])
        self.assertEqual(rag.calls[0]["source_type"], "all")
        self.assertEqual(rag.calls[0]["knowledge_scopes"], ["06"])
        self.assertTrue(rag.calls[0]["include_content"])
        self.assertEqual(
            self.store.latest_checkpoint("TASK-1")["payload"]["phase"],  # type: ignore[index]
            "validated",
        )
        self.assertEqual(self.store.list_agent_runs("TASK-1")[0]["status"], "completed")

    def test_general_question_skips_rag_and_uses_context_manager(self) -> None:
        rag = FakeRag()
        chat = FakeChat("안녕하세요. 무엇을 도와드릴까요?")
        orchestrator = SingleOrchestrator(self.store, rag, chat)

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-2",
                objective="안녕하세요",
            )
        )

        self.assertEqual(result.request_kind, RequestKind.QUESTION)
        self.assertEqual(rag.calls, [])
        self.assertEqual(len(chat.calls), 1)
        self.assertEqual(self.store.get_task("TASK-2").status, TaskStatus.COMPLETED)

    def test_equipment_identifier_requires_retrieval_for_plain_question(self) -> None:
        rag = FakeRag([self.document_source()])
        chat = FakeChat("관련 자료는 다음과 같습니다 [S1].")
        orchestrator = SingleOrchestrator(self.store, rag, chat)

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-E024",
                objective="E-024의 최근 자료를 알려줘",
            )
        )

        self.assertEqual(result.request_kind, RequestKind.QUESTION)
        self.assertEqual(rag.calls[0]["source_type"], "all")

    def test_empty_grounded_retrieval_returns_safe_answer_without_llm(self) -> None:
        rag = FakeRag()
        chat = FakeChat("should not be used")
        orchestrator = SingleOrchestrator(self.store, rag, chat)

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-3",
                objective="E-024 알람 원인을 분석해줘",
            )
        )

        self.assertEqual(chat.calls, [])
        self.assertEqual(result.finish_reason, "no_evidence")
        self.assertIn("검색된", result.answer)
        self.assertEqual(self.store.get_task("TASK-3").status, TaskStatus.COMPLETED)

    def test_missing_citation_fails_task_and_agent_run(self) -> None:
        rag = FakeRag([self.document_source()])
        chat = FakeChat("근거 표기 없는 답변")
        orchestrator = SingleOrchestrator(self.store, rag, chat)

        with self.assertRaises(OrchestratorExecutionError) as raised:
            orchestrator.run(
                OrchestratorRequest(
                    workspace_id="trim-project",
                    task_id="TASK-4",
                    objective="Vacuum 알람 원인 분석",
                )
            )

        task = self.store.get_task("TASK-4")
        self.assertEqual(raised.exception.task_id, "TASK-4")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("does not cite", task.failure_reason or "")
        self.assertEqual(self.store.list_agent_runs("TASK-4")[0]["status"], "failed")

    def test_retrieval_failure_is_persisted(self) -> None:
        rag = FakeRag()
        rag.error = RuntimeError("RAG unavailable")
        orchestrator = SingleOrchestrator(self.store, rag, FakeChat())

        with self.assertRaises(OrchestratorExecutionError):
            orchestrator.run(
                OrchestratorRequest(
                    workspace_id="trim-project",
                    task_id="TASK-5",
                    objective="알람 원인 분석",
                )
            )

        task = self.store.get_task("TASK-5")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("RAG unavailable", task.failure_reason or "")

    def test_classifier_prioritizes_change_over_generic_code_terms(self) -> None:
        classifier = RequestClassifier()
        base = {"workspace_id": "trim-project"}

        self.assertEqual(
            classifier.classify(
                OrchestratorRequest(**base, objective="이 C# 코드를 수정해줘")
            ),
            RequestKind.CODE_CHANGE,
        )
        self.assertEqual(
            classifier.classify(
                OrchestratorRequest(**base, objective="Loader Sequence 코드 분석")
            ),
            RequestKind.CODE_ANALYSIS,
        )
        self.assertEqual(
            classifier.classify(
                OrchestratorRequest(**base, objective="사양서 내용을 정리해줘")
            ),
            RequestKind.DOCUMENT_TASK,
        )

    def test_request_rejects_unbounded_or_blank_context_items(self) -> None:
        with self.assertRaisesRegex(ValueError, "top_k"):
            OrchestratorRequest(
                workspace_id="trim-project",
                objective="test",
                top_k=21,
            )
        with self.assertRaisesRegex(ValueError, "constraints"):
            OrchestratorRequest(
                workspace_id="trim-project",
                objective="test",
                constraints=("",),
            )


if __name__ == "__main__":
    unittest.main()

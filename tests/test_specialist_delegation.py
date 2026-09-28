from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore,
    AgentResult,
    ChatCompletionResult,
    ContextPack,
    EvidenceReference,
    OpenAiSpecialistDispatcher,
    OrchestratorExecutionError,
    OrchestratorRequest,
    SequentialDelegationPlanner,
    SingleOrchestrator,
    SpecialistAgent,
    SpecialistOutcome,
    TaskStatus,
)


class FakeRag:
    def __init__(self, sources: list[dict[str, Any]]) -> None:
        self.sources = sources

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        return {"result_count": len(self.sources), "sources": self.sources}


class FakeChat:
    def __init__(self, content: str = "direct response") -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session_id: str = "",
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> ChatCompletionResult:
        self.calls.append({"messages": messages, "session_id": session_id})
        return ChatCompletionResult(self.content, model="local-model")


class FakeSpecialists:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_on: SpecialistAgent | None = None
        self.omit_citation_on: SpecialistAgent | None = None

    def delegate(
        self,
        agent: SpecialistAgent,
        context: ContextPack,
        *,
        sources: Sequence[Mapping[str, Any]],
        previous: Sequence[SpecialistOutcome] = (),
        session_id: str = "",
    ) -> SpecialistOutcome:
        self.calls.append(
            {
                "agent": agent,
                "context": context,
                "sources": list(sources),
                "previous": list(previous),
                "session_id": session_id,
            }
        )
        if agent is self.fail_on:
            raise RuntimeError("specialist unavailable")
        source_ids = tuple(str(item["source_id"]) for item in sources)
        cited_ids = () if agent is self.omit_citation_on else source_ids
        citations = " ".join(f"[{item}]" for item in cited_ids)
        return SpecialistOutcome(
            agent,
            AgentResult(
                status="completed",
                summary=f"{agent.value} result {citations}".strip(),
                evidence_ids=cited_ids,
            ),
            model=f"model-{agent.value}",
            finish_reason="stop",
        )


class FakeProvider(FakeChat):
    pass


def document_source() -> dict[str, Any]:
    return {
        "source_id": "D1",
        "record_id": "doc-1",
        "source_type": "document",
        "file_name": "vacuum-manual.md",
        "text": "Check the vacuum sensor input.",
    }


def code_source() -> dict[str, Any]:
    return {
        "source_id": "C1",
        "record_id": "code-1",
        "source_type": "code",
        "relative_path": "LoaderSequence.cs",
        "method_name": "CheckVacuum",
        "code": "if (!vacuum) Raise(ALM_204);",
    }


class DelegationPlannerTests(unittest.TestCase):
    def test_plans_bounded_sequences_from_request_and_evidence(self) -> None:
        planner = SequentialDelegationPlanner()
        evidence = (
            EvidenceReference("D1", "doc-1", "document"),
            EvidenceReference("C1", "code-1", "code"),
        )

        self.assertEqual(
            planner.plan("troubleshooting", evidence),
            (
                SpecialistAgent.DOCUMENT,
                SpecialistAgent.CODE_ANALYSIS,
                SpecialistAgent.TROUBLESHOOTING,
            ),
        )
        self.assertEqual(
            planner.plan("code_change", evidence),
            (SpecialistAgent.CODE_ANALYSIS, SpecialistAgent.CODE_DEVELOPMENT),
        )
        self.assertEqual(planner.plan("question", evidence), ())

    def test_filters_sources_by_specialty(self) -> None:
        planner = SequentialDelegationPlanner()
        sources = [document_source(), code_source()]
        self.assertEqual(
            [item["source_id"] for item in planner.sources_for(
                SpecialistAgent.DOCUMENT, sources
            )],
            ["D1"],
        )
        self.assertEqual(
            [item["source_id"] for item in planner.sources_for(
                SpecialistAgent.TROUBLESHOOTING, sources
            )],
            ["D1", "C1"],
        )


class OpenAiSpecialistDispatcherTests(unittest.TestCase):
    def test_builds_bounded_handoff_and_extracts_citations(self) -> None:
        provider = FakeProvider("문서 근거 분석 [D1]")
        dispatcher = OpenAiSpecialistDispatcher(
            {SpecialistAgent.DOCUMENT: provider}
        )
        context = ContextPack(
            task_id="TASK-1",
            objective="진공 알람 분석",
            constraints=("설비를 조작하지 않는다",),
            evidence=(EvidenceReference("D1", "doc-1", "document"),),
            requested_output="문서 분석",
        )

        outcome = dispatcher.delegate(
            SpecialistAgent.DOCUMENT,
            context,
            sources=[document_source()],
            session_id="TASK-1:document-agent",
        )

        self.assertEqual(outcome.result.evidence_ids, ("D1",))
        self.assertIn("mutation is not authorized", provider.calls[0]["messages"][1]["content"])
        self.assertIn("[D1]", provider.calls[0]["messages"][1]["content"])
        self.assertEqual(provider.calls[0]["session_id"], "TASK-1:document-agent")

    def test_rejects_unconfigured_specialist(self) -> None:
        dispatcher = OpenAiSpecialistDispatcher({})
        with self.assertRaisesRegex(ValueError, "not configured"):
            dispatcher.delegate(
                SpecialistAgent.CODE_ANALYSIS,
                ContextPack(task_id="T", objective="analyze"),
                sources=[],
            )


class SpecialistProfileBoundaryTests(unittest.TestCase):
    @staticmethod
    def profile(name: str) -> str:
        root = Path(__file__).resolve().parents[1]
        return (root / "config" / "profiles" / name / "config.yaml").read_text(
            encoding="utf-8"
        )

    def test_specialists_cannot_repeat_orchestrator_rag_retrieval(self) -> None:
        for name in (
            "document-agent",
            "code-analysis-agent",
            "troubleshooting-agent",
            "code-development-agent",
        ):
            enabled = self.profile(name).split("agent:", 1)[0]
            self.assertNotIn("equipment_rag_code", enabled, name)
            self.assertNotIn("equipment_rag_document", enabled, name)

    def test_code_development_is_read_only_in_delegation_milestone(self) -> None:
        enabled = self.profile("code-development-agent").split("agent:", 1)[0]
        for toolset in (
            "workspace_write",
            "git_write",
            "git_merge_request",
            "dotnet_build",
        ):
            self.assertNotIn(toolset, enabled)


class SequentialSpecialistOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = AgentOrchestraStateStore(Path(self.temp.name) / "state.db")
        self.store.create_workspace("trim-project", name="MLCC trimming")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_troubleshooting_delegates_sequentially_and_persists_lineage(self) -> None:
        specialists = FakeSpecialists()
        direct_chat = FakeChat()
        orchestrator = SingleOrchestrator(
            self.store,
            FakeRag([document_source(), code_source()]),
            direct_chat,
            specialists=specialists,
        )

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-DELEGATE",
                session_id="conversation-1",
                objective="E-024 Loader Vacuum 알람 원인을 분석해줘",
            )
        )

        expected = [
            SpecialistAgent.DOCUMENT,
            SpecialistAgent.CODE_ANALYSIS,
            SpecialistAgent.TROUBLESHOOTING,
        ]
        self.assertEqual([item.agent for item in result.delegations], expected)
        self.assertEqual([item["agent"] for item in specialists.calls], expected)
        self.assertEqual(len(specialists.calls[1]["previous"]), 0)
        self.assertEqual(len(specialists.calls[2]["previous"]), 2)
        self.assertEqual(direct_chat.calls, [])
        self.assertEqual(result.answer, result.delegations[-1].result.summary)
        self.assertEqual(self.store.get_task("TASK-DELEGATE").status, TaskStatus.COMPLETED)

        runs = self.store.list_agent_runs("TASK-DELEGATE")
        parent = next(item for item in runs if item["agent_name"] == "single-orchestrator")
        children = [item for item in runs if item["agent_name"] != "single-orchestrator"]
        self.assertEqual(len(children), 3)
        self.assertTrue(all(item["parent_run_id"] == parent["run_id"] for item in children))
        self.assertTrue(all(item["status"] == "completed" for item in runs))
        self.assertEqual(
            self.store.latest_checkpoint("TASK-DELEGATE")["payload"]["delegated_agents"],  # type: ignore[index]
            [item.value for item in expected],
        )

    def test_normalizes_missing_source_identity_before_delegation(self) -> None:
        specialists = FakeSpecialists()
        source = {
            "record_id": "doc-without-explicit-type",
            "file_name": "manual.md",
            "text": "Vacuum recovery procedure",
        }
        orchestrator = SingleOrchestrator(
            self.store,
            FakeRag([source]),
            FakeChat(),
            specialists=specialists,
        )

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-NORMALIZE",
                objective="진공 매뉴얼 문서를 정리해줘",
            )
        )

        self.assertEqual(result.evidence[0].source_id, "S1")
        self.assertEqual(result.evidence[0].source_type, "document")
        self.assertEqual(specialists.calls[0]["sources"][0]["source_id"], "S1")
        self.assertEqual(specialists.calls[0]["sources"][0]["source_type"], "document")

    def test_code_change_ends_with_read_only_development_plan(self) -> None:
        specialists = FakeSpecialists()
        direct_chat = FakeChat()
        orchestrator = SingleOrchestrator(
            self.store,
            FakeRag([code_source()]),
            direct_chat,
            specialists=specialists,
        )

        result = orchestrator.run(
            OrchestratorRequest(
                workspace_id="trim-project",
                task_id="TASK-CHANGE-PLAN",
                objective="Loader Sequence 코드를 수정해줘",
            )
        )

        self.assertEqual(
            [item.agent for item in result.delegations],
            [SpecialistAgent.CODE_ANALYSIS, SpecialistAgent.CODE_DEVELOPMENT],
        )
        self.assertIn(
            "change plan only",
            specialists.calls[-1]["context"].requested_output,
        )
        self.assertEqual(len(specialists.calls[-1]["previous"]), 1)
        self.assertEqual(direct_chat.calls, [])

    def test_specialist_failure_fails_child_parent_and_task(self) -> None:
        specialists = FakeSpecialists()
        specialists.fail_on = SpecialistAgent.CODE_ANALYSIS
        orchestrator = SingleOrchestrator(
            self.store,
            FakeRag([code_source()]),
            FakeChat(),
            specialists=specialists,
        )

        with self.assertRaises(OrchestratorExecutionError):
            orchestrator.run(
                OrchestratorRequest(
                    workspace_id="trim-project",
                    task_id="TASK-FAIL",
                    objective="Loader Sequence 코드 분석",
                )
            )

        self.assertEqual(self.store.get_task("TASK-FAIL").status, TaskStatus.FAILED)
        runs = self.store.list_agent_runs("TASK-FAIL")
        self.assertEqual({item["status"] for item in runs}, {"failed"})
        self.assertTrue(any("specialist unavailable" in item["error"] for item in runs))

    def test_missing_specialist_citation_fails_closed(self) -> None:
        specialists = FakeSpecialists()
        specialists.omit_citation_on = SpecialistAgent.DOCUMENT
        orchestrator = SingleOrchestrator(
            self.store,
            FakeRag([document_source()]),
            FakeChat(),
            specialists=specialists,
        )

        with self.assertRaises(OrchestratorExecutionError) as raised:
            orchestrator.run(
                OrchestratorRequest(
                    workspace_id="trim-project",
                    task_id="TASK-NOCITE",
                    objective="진공 매뉴얼 문서를 정리해줘",
                )
            )

        self.assertIn("does not cite any retrieved source", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

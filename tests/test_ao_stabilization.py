import tempfile
import unittest
from pathlib import Path

from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore, ChatCompletionResult, ContextPack,
    OpenAiSpecialistDispatcher, OrchestratorExecutionError, OrchestratorRequest,
    SingleOrchestrator, SpecialistAgent, StateConflictError, TaskRecord, TaskStatus,
)


class Chat:
    def __init__(self, answer="result [D1]", reason="stop"):
        self.answer, self.reason = answer, reason
        self.messages = []

    def complete(self, messages, **kwargs):
        self.messages = messages
        return ChatCompletionResult(self.answer, finish_reason=self.reason)


class Rag:
    def retrieve(self, **kwargs):
        return {"sources": [{"source_id": "D1", "source_type": "document", "text": "known fact"}]}


class StabilizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AgentOrchestraStateStore(Path(self.tmp.name) / "state.db")
        self.store.create_workspace("W", name="Workspace")

    def request(self, task_id="T", **kwargs):
        return OrchestratorRequest("W", "문서 분석", task_id=task_id, **kwargs)

    def test_fake_citation_rejected_in_single_path(self):
        with self.assertRaisesRegex(OrchestratorExecutionError, "unknown evidence"):
            SingleOrchestrator(self.store, Rag(), Chat("result [D1] [FAKE99]")).run(self.request())
        self.assertEqual(self.store.get_task("T").status, TaskStatus.FAILED)

    def test_fake_citation_rejected_in_real_dispatcher(self):
        dispatcher = OpenAiSpecialistDispatcher({SpecialistAgent.DOCUMENT: Chat("[D1] [FAKE99]")})
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            dispatcher.delegate(SpecialistAgent.DOCUMENT, ContextPack("T", "read"), sources=Rag().retrieve()["sources"])

    def test_truncated_single_completion_rejected(self):
        with self.assertRaisesRegex(OrchestratorExecutionError, "incomplete completion"):
            SingleOrchestrator(self.store, Rag(), Chat(reason="length")).run(self.request())

    def test_truncated_specialist_completion_rejected(self):
        dispatcher = OpenAiSpecialistDispatcher({SpecialistAgent.DOCUMENT: Chat(reason="length")})
        with self.assertRaisesRegex(ValueError, "incomplete completion"):
            dispatcher.delegate(SpecialistAgent.DOCUMENT, ContextPack("T", "read"), sources=Rag().retrieve()["sources"])

    def test_hidden_source_cannot_be_cited(self):
        chat = Chat("[D1] [D2]")
        dispatcher = OpenAiSpecialistDispatcher({SpecialistAgent.DOCUMENT: chat}, evidence_character_budget=1000)
        sources = Rag().retrieve()["sources"] + [{"source_id": "D2", "text": "x" * 2000}]
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            dispatcher.delegate(SpecialistAgent.DOCUMENT, ContextPack("T", "read"), sources=sources)
        self.assertNotIn("[D2]", chat.messages[1]["content"])

    def test_empty_content_is_not_grounded_evidence(self):
        class EmptyRag:
            def retrieve(self, **kwargs):
                return {"sources": [{"source_id": "D1", "source_type": "document"}]}
        chat = Chat()
        result = SingleOrchestrator(self.store, EmptyRag(), chat).run(self.request())
        self.assertEqual(result.finish_reason, "no_evidence")
        self.assertEqual(chat.messages, [])

    def test_sessions_isolate_task_and_workspace(self):
        make = SingleOrchestrator._specialist_session_id
        a = SpecialistAgent.DOCUMENT
        ids = {make("S", "T1", a, workspace_id="W"), make("S", "T2", a, workspace_id="W"), make("S", "T1", a, workspace_id="W2")}
        self.assertEqual(len(ids), 3)

    def test_decisions_loaded_only_from_explicit_completed_task(self):
        engine = SingleOrchestrator(self.store, Rag(), Chat())
        engine.run(self.request("SOURCE", decisions=("Use sensor A",)))
        engine.run(self.request("NEXT", decision_task_ids=("SOURCE",)))
        self.assertEqual(self.store.get_task("NEXT").decisions, ["Use sensor A"])
        engine.run(self.request("OTHER"))
        self.assertEqual(self.store.get_task("OTHER").decisions, [])

    def test_cross_equipment_decision_loading_rejected(self):
        engine = SingleOrchestrator(self.store, Rag(), Chat())
        engine.run(self.request("SOURCE", equipment_id="E-1", decisions=("Use sensor A",)))
        with self.assertRaisesRegex(ValueError, "same workspace/equipment"):
            engine.run(self.request("NEXT", equipment_id="E-2", decision_task_ids=("SOURCE",)))

    def test_failed_task_restart_preserves_original_and_lineage(self):
        engine = SingleOrchestrator(self.store, Rag(), Chat("no citation"))
        with self.assertRaises(OrchestratorExecutionError):
            engine.run(self.request())
        old = self.store.get_task("T")
        engine.chat = Chat()
        result = engine.restart("T", expected_version=old.version)
        self.assertNotEqual(result.task_id, "T")
        self.assertEqual(self.store.get_task("T").version, old.version)
        self.assertEqual(self.store.get_task(result.task_id).status, TaskStatus.COMPLETED)

    def test_completed_restart_rejected(self):
        engine = SingleOrchestrator(self.store, Rag(), Chat())
        engine.run(self.request())
        with self.assertRaises(StateConflictError):
            engine.restart("T", expected_version=self.store.get_task("T").version)

    def test_restart_rejects_stale_version_and_legacy_task(self):
        self.store.create_task(TaskRecord("T", "W", "legacy"))
        with self.assertRaisesRegex(StateConflictError, "version conflict"):
            self.store.interrupt_for_restart("T", expected_version=99)
        with self.assertRaisesRegex(StateConflictError, "no saved request"):
            self.store.interrupt_for_restart("T", expected_version=0)

    def test_interrupted_task_runs_are_closed(self):
        from dataclasses import asdict
        self.store.create_task(TaskRecord("T", "W", "문서 분석"))
        self.store.save_checkpoint("T", {"phase": "request_saved", "request": asdict(self.request())})
        task = self.store.transition_task("T", TaskStatus.PLANNING)
        run = self.store.start_agent_run("T", "single-orchestrator")
        result = SingleOrchestrator(self.store, Rag(), Chat()).restart("T", expected_version=task.version)
        self.assertEqual(self.store.get_agent_run(run["run_id"])["status"], "failed")
        self.assertEqual(self.store.get_task(result.task_id).status, TaskStatus.COMPLETED)

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore, MarkdownArtifactStore, OrchestratorRequest,
    OrchestratorExecutionError, RequestKind, SingleOrchestrator, SpecialistAgent,
)
from hermes_equipment_poc.orchestrator.state_store import _SCHEMA_V1
from test_single_orchestrator import FakeChat, FakeRag
from test_specialist_delegation import FakeSpecialists


SOURCE = {"source_id": "S1", "record_id": "guide-1", "source_type": "document",
          "text": "Record the purchase decision and its evidence.", "file_name": "purchasing.md"}


class DomainPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "workspace").mkdir()
        self.store = AgentOrchestraStateStore(self.root / "state.db")
        self.store.create_workspace("docs", name="Documents", domain_id="document", root_path=str(self.root / "workspace"))
        self.rag, self.chat = FakeRag([SOURCE]), FakeChat("Record the decision [S1].")

    def engine(self, **kwargs):
        return SingleOrchestrator(self.store, self.rag, self.chat, domain_id="document", **kwargs)

    def test_document_report_without_equipment_and_with_specialist(self):
        specialists = FakeSpecialists()
        result = self.engine(specialists=specialists, artifact_store=MarkdownArtifactStore(self.root / "artifacts")).run(
            OrchestratorRequest("docs", "구매 절차 보고서", subject_id="PUR-01", create_artifact=True))
        task = self.store.get_task(result.task_id)
        self.assertEqual((task.domain_id, task.subject_id, task.equipment_id), ("document", "PUR-01", None))
        self.assertEqual(self.rag.calls[0]["source_type"], "document")
        self.assertIsNone(self.rag.calls[0]["document_filters"]["equipment"])
        self.assertIn("PUR-01", self.rag.calls[0]["query"])
        self.assertEqual([c["agent"] for c in specialists.calls], [SpecialistAgent.DOCUMENT])
        self.assertEqual(specialists.calls[0]["context"].domain_id, "document")
        path = Path(result.artifacts[0].path)
        self.assertIn("[S1]", path.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result.artifacts[0].sha256)

    def test_direct_prompt_and_scoped_session_are_generic(self):
        engine = self.engine()
        request = OrchestratorRequest("docs", "설명", subject_id="policy", session_id="same")
        engine.run(request)
        engine.run(request)
        self.assertEqual(self.chat.calls[0]["session_id"], self.chat.calls[1]["session_id"])
        self.assertNotEqual(self.chat.calls[0]["session_id"], "same")
        self.assertIn("general document", self.chat.calls[0]["messages"][0]["content"])
        self.assertNotIn("Equipment:", self.chat.calls[0]["messages"][1]["content"])
        engine.run(OrchestratorRequest("docs", "설명", subject_id="other", session_id="same"))
        self.assertNotEqual(self.chat.calls[0]["session_id"], self.chat.calls[2]["session_id"])

    def test_domain_override_and_unsupported_operations_rejected_before_search(self):
        for kwargs in ({"domain_id": "equipment"}, {"equipment_id": "E-01"},
                       {"request_kind": RequestKind.CODE_CHANGE}, {"knowledge_scopes": ("06",)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.engine().run(OrchestratorRequest("docs", "test", **kwargs))
        self.assertEqual(self.rag.calls, [])

    def test_empty_documents_skip_llm(self):
        self.rag.sources = []
        result = self.engine().run(OrchestratorRequest("docs", "안내"))
        self.assertEqual(result.finish_reason, "no_evidence")
        self.assertNotIn("설비", result.answer)
        self.assertEqual(self.chat.calls, [])

    def test_code_evidence_is_not_accepted_in_document_domain(self):
        self.rag.sources = [{**SOURCE, "source_type": "code"}]
        with self.assertRaises(OrchestratorExecutionError):
            self.engine().run(OrchestratorRequest("docs", "안내"))
        self.assertEqual(self.chat.calls, [])

    def test_equipment_subject_alias_and_conflict(self):
        self.store.create_workspace("equip", name="Equipment")
        engine = SingleOrchestrator(self.store, self.rag, self.chat)
        result = engine.run(OrchestratorRequest("equip", "설명", subject_id="E-024"))
        task = self.store.get_task(result.task_id)
        self.assertEqual((task.equipment_id, task.subject_id), ("E-024", "E-024"))
        self.assertEqual(self.rag.calls[0]["document_filters"]["equipment"], "E-024")
        with self.assertRaises(ValueError):
            OrchestratorRequest("equip", "x", equipment_id="E-01", subject_id="E-02")

    def test_decisions_cannot_cross_subjects(self):
        engine = self.engine()
        source = engine.run(OrchestratorRequest("docs", "설명", subject_id="one", decisions=("confirmed",)))
        with self.assertRaises(ValueError):
            engine.run(OrchestratorRequest("docs", "설명", subject_id="two", decision_task_ids=(source.task_id,)))

    def test_workspace_domain_cannot_be_changed_by_engine(self):
        with self.assertRaises(ValueError):
            SingleOrchestrator(self.store, self.rag, self.chat).run(OrchestratorRequest("docs", "x"))

    def test_custom_planner_cannot_call_code_agent_for_document_work(self):
        class Planner:
            def plan(self, *args):
                return (SpecialistAgent.CODE_DEVELOPMENT,)
        specialists = FakeSpecialists()
        with self.assertRaises(OrchestratorExecutionError):
            self.engine(specialists=specialists, delegation_planner=Planner()).run(OrchestratorRequest("docs", "안내"))
        self.assertEqual(specialists.calls, [])

    def test_wrong_domain_restart_does_not_mutate_task(self):
        result = self.engine().run(OrchestratorRequest("docs", "안내"))
        before = self.store.get_task(result.task_id)
        with self.assertRaises(ValueError):
            SingleOrchestrator(self.store, self.rag, self.chat).restart(result.task_id, expected_version=before.version)
        self.assertEqual(self.store.get_task(result.task_id), before)

    def test_v1_migration_preserves_tasks_and_is_repeatable(self):
        path = self.root / "old.db"
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(_SCHEMA_V1)
            db.execute("PRAGMA user_version=1")
            db.execute("INSERT INTO workspaces VALUES ('old','Old','', 'before','before')")
            db.execute("INSERT INTO tasks(task_id,workspace_id,objective,equipment_id,status,version,created_at,updated_at) VALUES ('task','old','test','E-024','received',0,'before','before')")
        for _ in range(2):
            store = AgentOrchestraStateStore(path)
            self.assertEqual(store.get_workspace("old")["domain_id"], "equipment")
            task = store.get_task("task")
            self.assertEqual((task.subject_id, task.domain_id, task.version), ("E-024", "equipment", 0))
        path.rename(self.root / "closed.db")


try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "Install .[web,test]")
class DomainApiTests(unittest.TestCase):
    setUp = DomainPackTests.setUp
    engine = DomainPackTests.engine

    def test_api_exposes_domain_and_rejects_switch_before_enqueue(self):
        from hermes_equipment_poc.web_service import create_app
        with TestClient(create_app(self.engine(), "docs"), base_url="http://localhost") as client:
            config = client.get("/v1/workspace").json()
            self.assertEqual(config["domain_id"], "document")
            self.assertNotIn("code_change", config["allowed_request_kinds"])
            for payload in ({"domain_id": "equipment"}, {"request_kind": "code_change"}, {"equipment_id": "E-01"}):
                response = client.post("/v1/tasks", headers={"X-AO-Request": "1"}, json={"objective": "test", **payload})
                self.assertEqual(response.status_code, 422, response.text)
            response = client.post("/v1/tasks", headers={"X-AO-Request": "1"}, json={"objective": "안내", "subject_id": "policy"})
            self.assertEqual(response.status_code, 202, response.text)
            task_id = response.json()["task_id"]
            for _ in range(100):
                task = client.get("/v1/tasks/" + task_id).json()
                if task.get("status") in {"completed", "failed"}:
                    break
                time.sleep(.01)
            self.assertEqual(task["status"], "completed", task)
            self.assertEqual((task["domain_id"], task["subject_id"]), ("document", "policy"))

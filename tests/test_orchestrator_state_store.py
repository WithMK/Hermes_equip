from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore,
    ArtifactReference,
    EvidenceReference,
    StateConflictError,
    StateNotFoundError,
    StateStoreError,
    TaskRecord,
    TaskStatus,
)


class AgentOrchestraStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state" / "orchestra.db"
        self.store = AgentOrchestraStateStore(self.path)
        self.store.create_workspace(
            "trim-project", name="MLCC trimming", root_path="D:/EquipmentSW"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_task(self, task_id: str = "TASK-1") -> TaskRecord:
        return self.store.create_task(
            TaskRecord(
                task_id,
                "trim-project",
                "Analyze repeated E-024 Loader Vacuum alarms",
                equipment_id="E-024",
            )
        )

    def test_workspace_and_task_persist_across_store_restart(self) -> None:
        created = self.create_task()
        reopened = AgentOrchestraStateStore(self.path)

        workspace = reopened.get_workspace("trim-project")
        task = reopened.get_task(created.task_id)

        self.assertEqual(workspace["name"], "MLCC trimming")
        self.assertEqual(task.status, TaskStatus.RECEIVED)
        self.assertEqual(task.equipment_id, "E-024")
        self.assertTrue(task.created_at)
        with self.assertRaises(StateConflictError):
            reopened.create_workspace("trim-project", name="duplicate")
        with self.assertRaises(StateNotFoundError):
            reopened.get_task("missing")

    def test_transition_uses_optimistic_version_and_blocks_terminal_mutation(self) -> None:
        task = self.create_task()
        task = self.store.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
            expected_version=task.version,
            assigned_agent="orchestrator",
        )
        self.assertEqual(task.version, 1)
        self.assertEqual(task.assigned_agent, "orchestrator")

        with self.assertRaisesRegex(StateConflictError, "version conflict"):
            self.store.transition_task(
                task.task_id,
                TaskStatus.RETRIEVING,
                expected_version=0,
            )

        for status in (
            TaskStatus.DELEGATED,
            TaskStatus.VALIDATING,
            TaskStatus.COMPLETED,
        ):
            task = self.store.transition_task(task.task_id, status)

        with self.assertRaisesRegex(StateConflictError, "terminal task"):
            self.store.add_decision(task.task_id, "Late mutation")
        with self.assertRaisesRegex(ValueError, "invalid task transition"):
            self.store.transition_task(task.task_id, TaskStatus.PLANNING)

    def test_failure_requires_reason(self) -> None:
        task = self.create_task()
        with self.assertRaisesRegex(ValueError, "failure_reason"):
            self.store.transition_task(task.task_id, TaskStatus.FAILED)

        failed = self.store.transition_task(
            task.task_id,
            TaskStatus.FAILED,
            failure_reason="ContextManager timeout",
        )
        self.assertEqual(failed.failure_reason, "ContextManager timeout")

    def test_evidence_artifacts_and_decisions_are_attached_to_task(self) -> None:
        task = self.create_task()
        evidence = EvidenceReference("S1", "record-1", "document", "Alarm manual")
        artifact = ArtifactReference(
            "reports/E-024-vacuum.md", "markdown_report", "a" * 64
        )

        self.store.add_evidence(task.task_id, evidence)
        self.store.add_artifact(task.task_id, artifact)
        decision = self.store.add_decision(
            task.task_id, "Inspect the Vacuum Sensor input before replacing the valve."
        )
        loaded = self.store.get_task(task.task_id)

        self.assertEqual(loaded.evidence, [evidence])
        self.assertEqual(loaded.artifacts, [artifact])
        self.assertEqual(loaded.decisions, [decision["content"]])
        with self.assertRaisesRegex(StateConflictError, "evidence source"):
            self.store.add_evidence(task.task_id, evidence)
        with self.assertRaisesRegex(StateConflictError, "artifact path"):
            self.store.add_artifact(task.task_id, artifact)

    def test_latest_checkpoint_restores_json_payload(self) -> None:
        task = self.create_task()
        self.assertIsNone(self.store.latest_checkpoint(task.task_id))

        self.store.save_checkpoint(task.task_id, {"step": 1, "query": "Vacuum alarm"})
        latest = self.store.save_checkpoint(
            task.task_id,
            {"step": 2, "sources": ["S1", "S2"], "ready": True},
        )

        self.assertEqual(self.store.latest_checkpoint(task.task_id), latest)
        with self.assertRaisesRegex(ValueError, "JSON serializable"):
            self.store.save_checkpoint(task.task_id, {"invalid": object()})

    def test_agent_run_is_one_time_and_parent_is_task_scoped(self) -> None:
        task = self.create_task()
        parent = self.store.start_agent_run(task.task_id, "orchestrator")
        child = self.store.start_agent_run(
            task.task_id,
            "troubleshooting-agent",
            parent_run_id=parent["run_id"],
        )
        completed = self.store.finish_agent_run(
            child["run_id"], status="completed", summary="Report prepared"
        )

        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["completed_at"])
        self.assertEqual(
            [item["run_id"] for item in self.store.list_agent_runs(task.task_id)],
            [parent["run_id"], child["run_id"]],
        )
        with self.assertRaisesRegex(StateConflictError, "already finished"):
            self.store.finish_agent_run(child["run_id"], status="completed")

        other = self.store.create_task(
            TaskRecord("TASK-2", "trim-project", "Review Loader sequence")
        )
        with self.assertRaisesRegex(StateNotFoundError, "parent run"):
            self.store.start_agent_run(
                other.task_id,
                "code-analysis-agent",
                parent_run_id=parent["run_id"],
            )

    def test_list_tasks_filters_status(self) -> None:
        first = self.create_task("TASK-1")
        second = self.create_task("TASK-2")
        self.store.transition_task(first.task_id, TaskStatus.PLANNING)

        planning = self.store.list_tasks(
            "trim-project", statuses=[TaskStatus.PLANNING]
        )
        all_tasks = self.store.list_tasks("trim-project")

        self.assertEqual([item.task_id for item in planning], [first.task_id])
        self.assertEqual(
            {item.task_id for item in all_tasks}, {first.task_id, second.task_id}
        )

    def test_newer_schema_is_rejected(self) -> None:
        path = Path(self.temp.name) / "future.db"
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA user_version = 999")

        with self.assertRaisesRegex(StateStoreError, "newer than supported"):
            AgentOrchestraStateStore(path)


if __name__ == "__main__":
    unittest.main()

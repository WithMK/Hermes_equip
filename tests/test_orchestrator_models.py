from __future__ import annotations

import unittest

from hermes_equipment_poc.orchestrator import (
    AgentResult,
    ContextPack,
    EvidenceReference,
    TaskRecord,
    TaskStatus,
)


class OrchestratorModelTests(unittest.TestCase):
    def test_task_follows_bounded_success_path(self) -> None:
        task = TaskRecord("TASK-1", "trim-project", "Analyze E-024 vacuum alarm")

        for status in (
            TaskStatus.PLANNING,
            TaskStatus.RETRIEVING,
            TaskStatus.DELEGATED,
            TaskStatus.VALIDATING,
            TaskStatus.COMPLETED,
        ):
            task.transition(status)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        with self.assertRaisesRegex(ValueError, "invalid task transition"):
            task.transition(TaskStatus.PLANNING)

    def test_validation_can_replan_or_wait_for_approval(self) -> None:
        task = TaskRecord("TASK-2", "trim-project", "Prepare a safe code change")
        task.transition(TaskStatus.PLANNING)
        task.transition(TaskStatus.DELEGATED)
        task.transition(TaskStatus.VALIDATING)
        task.transition(TaskStatus.PLANNING)
        task.transition(TaskStatus.DELEGATED)
        task.transition(TaskStatus.VALIDATING)
        task.transition(TaskStatus.WAITING_APPROVAL)

        self.assertEqual(task.status, TaskStatus.WAITING_APPROVAL)

    def test_context_pack_rejects_ambiguous_evidence_identity(self) -> None:
        evidence = EvidenceReference("S1", "record-1", "document", "Alarm manual")
        with self.assertRaisesRegex(ValueError, "source_id values must be unique"):
            ContextPack(
                task_id="TASK-3",
                objective="Analyze alarm",
                evidence=(evidence, evidence),
            )

    def test_agent_result_has_small_closed_status_contract(self) -> None:
        result = AgentResult(
            status="completed",
            summary="Root-cause candidates were documented.",
            evidence_ids=("S1", "S2"),
        )
        self.assertEqual(result.evidence_ids, ("S1", "S2"))
        with self.assertRaisesRegex(ValueError, "status must be"):
            AgentResult(status="running", summary="Not a terminal handoff")


if __name__ == "__main__":
    unittest.main()

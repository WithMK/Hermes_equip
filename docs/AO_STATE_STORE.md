# Agent Orchestra State Store

## Responsibility

The SQLite State Store persists structured work state owned by Agent Orchestra:

- Workspace and Task identity
- bounded Task status and optimistic version
- parent/child Agent Run history
- EquipmentRAG evidence identifiers
- confirmed decisions
- generated artifact paths and hashes
- recovery checkpoints

It does not store conversation history, ContextManager summaries, model credentials, raw model
weights, large source files or unrestricted Tool output.

## Default placement

Use a path outside source repositories and Agent-writeable workspaces.

```text
C:\ProgramData\HermesEquipment\state\orchestra.db
```

Runtime database files must not be committed. The repository ignores `.ao-state/` for local
development.

## Safety rules

- SQLite foreign keys are enabled for every connection.
- WAL mode and a bounded busy timeout are enabled.
- Task transitions use an integer version for optimistic conflict detection.
- `completed` and `failed` Tasks are terminal and reject new evidence, decisions, artifacts,
  checkpoints and Agent Runs.
- Agent Runs can be completed only once.
- A child Agent Run must reference a parent from the same Task.
- Agent Run history remains queryable in start order after restart.
- A database with a newer schema version fails closed.

## Schema version 1

| Table | Purpose |
|---|---|
| `workspaces` | Project/workspace identity and allowed root description |
| `tasks` | Objective, equipment, status, Agent and optimistic version |
| `agent_runs` | Sequential delegation history and parent Run |
| `evidence` | EquipmentRAG `source_id` and `record_id` references |
| `decisions` | Confirmed structured work decisions |
| `artifacts` | Generated report/code artifact path, type and optional SHA-256 |
| `checkpoints` | JSON-serializable recovery payload and Task status |

## Python contract

```python
from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore,
    EvidenceReference,
    TaskRecord,
    TaskStatus,
)

store = AgentOrchestraStateStore(r"C:\ProgramData\HermesEquipment\state\orchestra.db")
store.create_workspace("trim-project", name="MLCC trimming")
task = store.create_task(
    TaskRecord("TASK-1", "trim-project", "Analyze E-024 Vacuum alarm")
)
task = store.transition_task(
    task.task_id,
    TaskStatus.PLANNING,
    expected_version=task.version,
)
store.add_evidence(
    task.task_id,
    EvidenceReference("S1", "record-1", "document", "Alarm manual"),
)
store.save_checkpoint(task.task_id, {"next_step": "delegate_troubleshooting"})
```

## Backup and recovery

Do not copy only the main database file while the service is writing. Stop A/O first or use the
SQLite backup API so the main database and WAL state are captured consistently. Database restore
does not automatically resume execution. Operator-triggered cold restart from a saved request is
documented in `AO_STABILIZATION.md`; last-step checkpoint continuation is not implemented.

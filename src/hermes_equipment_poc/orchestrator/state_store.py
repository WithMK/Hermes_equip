from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .models import ArtifactReference, EvidenceReference, TaskRecord, TaskStatus


SCHEMA_VERSION = 2
_TERMINAL_TASK_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}
_AGENT_RUN_STATUSES = {"running", "completed", "failed"}


class StateStoreError(RuntimeError):
    pass


class StateNotFoundError(StateStoreError):
    pass


class StateConflictError(StateStoreError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


class AgentOrchestraStateStore:
    """SQLite persistence for Agent Orchestra work state.

    The store contains structured work state only. Conversation history and token
    budgeting remain ContextManager responsibilities.
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.path = Path(path).expanduser().resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.timeout_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise StateStoreError(
                    f"state database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            if current == 0:
                connection.executescript(_SCHEMA_V1)
                connection.execute("PRAGMA user_version = 1")
                current = 1
            if current == 1:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("ALTER TABLE workspaces ADD COLUMN domain_id TEXT NOT NULL DEFAULT 'equipment'")
                connection.execute("ALTER TABLE tasks ADD COLUMN domain_id TEXT NOT NULL DEFAULT 'equipment'")
                connection.execute("ALTER TABLE tasks ADD COLUMN subject_id TEXT")
                connection.execute("UPDATE tasks SET subject_id = equipment_id")
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def create_workspace(
        self, workspace_id: str, *, name: str, root_path: str = "", domain_id: str = "equipment"
    ) -> dict[str, Any]:
        workspace_id = _required(workspace_id, "workspace_id")
        from ..domains import get_domain
        get_domain(domain_id)
        name = _required(name, "name")
        created_at = _now()
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO workspaces(
                        workspace_id, name, root_path, created_at, updated_at, domain_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (workspace_id, name, root_path.strip(), created_at, created_at, domain_id),
                )
        except sqlite3.IntegrityError as exc:
            raise StateConflictError(f"workspace already exists: {workspace_id}") from exc
        return self.get_workspace(workspace_id)

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?",
                (_required(workspace_id, "workspace_id"),),
            ).fetchone()
        if row is None:
            raise StateNotFoundError(f"workspace not found: {workspace_id}")
        return dict(row)

    def create_task(self, task: TaskRecord) -> TaskRecord:
        if self.get_workspace(task.workspace_id)["domain_id"] != task.domain_id:
            raise ValueError("task domain differs from workspace")
        if task.status is not TaskStatus.RECEIVED or task.version != 0:
            raise ValueError("new tasks must start at received with version 0")
        created_at = _now()
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO tasks(
                        task_id, workspace_id, objective, equipment_id, status,
                        assigned_agent, failure_reason, version, created_at, updated_at,
                        domain_id, subject_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.workspace_id,
                        task.objective,
                        task.equipment_id,
                        task.status.value,
                        task.assigned_agent,
                        task.failure_reason,
                        created_at,
                        created_at,
                        task.domain_id,
                        task.subject_id if task.subject_id is not None else task.equipment_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StateConflictError(
                f"task already exists or workspace is unknown: {task.task_id}"
            ) from exc
        return self.get_task(task.task_id)

    def get_task(self, task_id: str) -> TaskRecord:
        task_id = _required(task_id, "task_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise StateNotFoundError(f"task not found: {task_id}")
            evidence = [
                EvidenceReference(
                    item["source_id"],
                    item["record_id"],
                    item["source_type"],
                    item["summary"],
                )
                for item in connection.execute(
                    "SELECT * FROM evidence WHERE task_id = ? ORDER BY id", (task_id,)
                )
            ]
            artifacts = [
                ArtifactReference(item["path"], item["artifact_type"], item["sha256"])
                for item in connection.execute(
                    "SELECT * FROM artifacts WHERE task_id = ? ORDER BY id", (task_id,)
                )
            ]
            decisions = [
                item["content"]
                for item in connection.execute(
                    "SELECT content FROM decisions WHERE task_id = ? ORDER BY id", (task_id,)
                )
            ]
        return TaskRecord(
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            objective=row["objective"],
            status=TaskStatus(row["status"]),
            equipment_id=row["equipment_id"],
            assigned_agent=row["assigned_agent"],
            evidence=evidence,
            artifacts=artifacts,
            decisions=decisions,
            failure_reason=row["failure_reason"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            domain_id=row["domain_id"],
            subject_id=row["subject_id"],
        )

    def list_tasks(
        self,
        workspace_id: str,
        *,
        statuses: Iterable[TaskStatus] | None = None,
    ) -> list[TaskRecord]:
        workspace_id = _required(workspace_id, "workspace_id")
        values = tuple(status.value for status in (statuses or ()))
        query = "SELECT task_id FROM tasks WHERE workspace_id = ?"
        parameters: list[Any] = [workspace_id]
        if values:
            query += f" AND status IN ({','.join('?' for _ in values)})"
            parameters.extend(values)
        query += " ORDER BY created_at, task_id"
        with closing(self._connect()) as connection:
            task_ids = [
                row["task_id"] for row in connection.execute(query, parameters).fetchall()
            ]
        return [self.get_task(task_id) for task_id in task_ids]

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        expected_version: int | None = None,
        assigned_agent: str | None = None,
        failure_reason: str | None = None,
    ) -> TaskRecord:
        task_id = _required(task_id, "task_id")
        if target is TaskStatus.FAILED:
            failure_reason = _required(failure_reason or "", "failure_reason")
        elif failure_reason is not None:
            raise ValueError("failure_reason is only valid for failed tasks")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, version FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise StateNotFoundError(f"task not found: {task_id}")
            current_version = int(row["version"])
            if expected_version is not None and expected_version != current_version:
                raise StateConflictError(
                    f"task version conflict: expected {expected_version}, current {current_version}"
                )
            probe = TaskRecord(
                task_id,
                "transition-check",
                "transition-check",
                TaskStatus(row["status"]),
            )
            probe.transition(target)
            updated = connection.execute(
                """
                UPDATE tasks
                SET status = ?, assigned_agent = COALESCE(?, assigned_agent),
                    failure_reason = ?, version = version + 1, updated_at = ?
                WHERE task_id = ? AND version = ?
                """,
                (
                    target.value,
                    assigned_agent.strip() if assigned_agent else None,
                    failure_reason,
                    _now(),
                    task_id,
                    current_version,
                ),
            )
            if updated.rowcount != 1:
                raise StateConflictError(f"task changed concurrently: {task_id}")
        return self.get_task(task_id)

    def add_evidence(self, task_id: str, evidence: EvidenceReference) -> TaskRecord:
        with closing(self._connect()) as connection, connection:
            self._require_mutable_task(connection, task_id)
            try:
                connection.execute(
                    """
                    INSERT INTO evidence(
                        task_id, source_id, record_id, source_type, summary, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        evidence.source_id,
                        evidence.record_id,
                        evidence.source_type,
                        evidence.summary,
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StateConflictError(
                    f"evidence source already exists for task: {evidence.source_id}"
                ) from exc
        return self.get_task(task_id)

    def add_artifact(
        self,
        task_id: str,
        artifact: ArtifactReference,
    ) -> TaskRecord:
        with closing(self._connect()) as connection, connection:
            self._require_mutable_task(connection, task_id)
            try:
                connection.execute(
                    """
                    INSERT INTO artifacts(
                        task_id, path, artifact_type, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        artifact.path,
                        artifact.artifact_type,
                        artifact.sha256,
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StateConflictError(
                    f"artifact path already exists for task: {artifact.path}"
                ) from exc
        return self.get_task(task_id)

    def add_decision(self, task_id: str, content: str) -> dict[str, Any]:
        content = _required(content, "content")
        decision_id = f"decision-{uuid4().hex}"
        created_at = _now()
        with closing(self._connect()) as connection, connection:
            self._require_mutable_task(connection, task_id)
            connection.execute(
                """
                INSERT INTO decisions(decision_id, task_id, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (decision_id, task_id, content, created_at),
            )
        return {
            "decision_id": decision_id,
            "task_id": task_id,
            "content": content,
            "created_at": created_at,
        }

    def save_checkpoint(
        self, task_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        checkpoint_id = f"checkpoint-{uuid4().hex}"
        try:
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("checkpoint payload must be JSON serializable") from exc
        created_at = _now()
        with closing(self._connect()) as connection, connection:
            status = self._require_mutable_task(connection, task_id)
            connection.execute(
                """
                INSERT INTO checkpoints(
                    checkpoint_id, task_id, task_status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (checkpoint_id, task_id, status.value, payload_json, created_at),
            )
        return {
            "checkpoint_id": checkpoint_id,
            "task_id": task_id,
            "task_status": status.value,
            "payload": dict(payload),
            "created_at": created_at,
        }

    def latest_checkpoint(self, task_id: str) -> dict[str, Any] | None:
        task_id = _required(task_id, "task_id")
        with closing(self._connect()) as connection:
            self._require_task(connection, task_id)
            row = connection.execute(
                """
                SELECT * FROM checkpoints
                WHERE task_id = ? ORDER BY id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "checkpoint_id": row["checkpoint_id"],
            "task_id": row["task_id"],
            "task_status": row["task_status"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def start_agent_run(
        self, task_id: str, agent_name: str, *, parent_run_id: str | None = None
    ) -> dict[str, Any]:
        agent_name = _required(agent_name, "agent_name")
        run_id = f"run-{uuid4().hex}"
        started_at = _now()
        with closing(self._connect()) as connection, connection:
            self._require_mutable_task(connection, task_id)
            if parent_run_id is not None:
                parent = connection.execute(
                    "SELECT task_id FROM agent_runs WHERE run_id = ?", (parent_run_id,)
                ).fetchone()
                if parent is None or parent["task_id"] != task_id:
                    raise StateNotFoundError(
                        f"parent run not found for task: {parent_run_id}"
                    )
            connection.execute(
                """
                INSERT INTO agent_runs(
                    run_id, task_id, parent_run_id, agent_name, status, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (run_id, task_id, parent_run_id, agent_name, started_at),
            )
        return self.get_agent_run(run_id)

    def interrupt_for_restart(self, task_id: str, *, expected_version: int) -> dict[str, Any]:
        """Operator-only recovery after the worker has stopped, not a live takeover."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise StateNotFoundError(f"task not found: {task_id}")
            if row["version"] != expected_version:
                raise StateConflictError("task version conflict during restart")
            if row["status"] in {"completed", "waiting_approval"}:
                raise StateConflictError("completed/approval task cannot be restarted")
            snapshots = connection.execute(
                "SELECT payload_json FROM checkpoints WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
            request = next((payload["request"] for item in snapshots
                if (payload := json.loads(item["payload_json"])).get("phase") == "request_saved"), None)
            if request is None:
                raise StateConflictError("no saved request; legacy tasks require a new explicit request")
            if row["status"] != "failed":
                connection.execute(
                    "UPDATE tasks SET status='failed', failure_reason=?, version=version+1, updated_at=? WHERE task_id=?",
                    ("Interrupted by explicit operator restart", _now(), task_id),
                )
            connection.execute(
                "UPDATE agent_runs SET status='failed', error=?, completed_at=? WHERE task_id=? AND status='running'",
                ("Interrupted by explicit operator restart", _now(), task_id),
            )
        request["restart_of"] = task_id
        return request

    def finish_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        if status not in _AGENT_RUN_STATUSES - {"running"}:
            raise ValueError("finished agent run status must be completed or failed")
        if status == "failed":
            error = _required(error, "error")
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, summary = ?, error = ?, completed_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (status, summary.strip(), error.strip(), _now(), _required(run_id, "run_id")),
            )
            if updated.rowcount != 1:
                raise StateConflictError(f"agent run is missing or already finished: {run_id}")
        return self.get_agent_run(run_id)

    def get_agent_run(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?",
                (_required(run_id, "run_id"),),
            ).fetchone()
        if row is None:
            raise StateNotFoundError(f"agent run not found: {run_id}")
        return dict(row)

    def list_agent_runs(self, task_id: str) -> list[dict[str, Any]]:
        task_id = _required(task_id, "task_id")
        with closing(self._connect()) as connection:
            self._require_task(connection, task_id)
            rows = connection.execute(
                """
                SELECT * FROM agent_runs
                WHERE task_id = ? ORDER BY rowid
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _require_task(connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        task_id = _required(task_id, "task_id")
        row = connection.execute(
            "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise StateNotFoundError(f"task not found: {task_id}")
        return row

    @classmethod
    def _require_mutable_task(
        cls, connection: sqlite3.Connection, task_id: str
    ) -> TaskStatus:
        status = TaskStatus(cls._require_task(connection, task_id)["status"])
        if status in _TERMINAL_TASK_STATUSES:
            raise StateConflictError(f"terminal task cannot be changed: {task_id}")
        return status


_SCHEMA_V1 = """
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE RESTRICT,
    objective TEXT NOT NULL,
    equipment_id TEXT,
    status TEXT NOT NULL CHECK(status IN (
        'received', 'planning', 'retrieving', 'delegated', 'validating',
        'waiting_approval', 'completed', 'failed'
    )),
    assigned_agent TEXT,
    failure_reason TEXT,
    version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX tasks_workspace_status_idx ON tasks(workspace_id, status);

CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    parent_run_id TEXT REFERENCES agent_runs(run_id) ON DELETE RESTRICT,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    summary TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX agent_runs_task_idx ON agent_runs(task_id, started_at);

CREATE TABLE evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('code', 'document')),
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(task_id, source_id)
);

CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(task_id, path)
);

CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    task_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX checkpoints_task_idx ON checkpoints(task_id, id);
"""

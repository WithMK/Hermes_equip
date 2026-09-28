from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    RECEIVED = "received"
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    DELEGATED = "delegated"
    VALIDATING = "validating"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.RECEIVED: frozenset({TaskStatus.PLANNING, TaskStatus.FAILED}),
    TaskStatus.PLANNING: frozenset(
        {TaskStatus.RETRIEVING, TaskStatus.DELEGATED, TaskStatus.FAILED}
    ),
    TaskStatus.RETRIEVING: frozenset(
        {TaskStatus.PLANNING, TaskStatus.DELEGATED, TaskStatus.FAILED}
    ),
    TaskStatus.DELEGATED: frozenset(
        {TaskStatus.VALIDATING, TaskStatus.FAILED}
    ),
    TaskStatus.VALIDATING: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.FAILED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
}


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


@dataclass(frozen=True)
class EvidenceReference:
    source_id: str
    record_id: str
    source_type: str
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))
        object.__setattr__(self, "record_id", _required(self.record_id, "record_id"))
        if self.source_type not in {"code", "document"}:
            raise ValueError("source_type must be code or document")


@dataclass(frozen=True)
class ArtifactReference:
    path: str
    artifact_type: str
    sha256: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _required(self.path, "path"))
        object.__setattr__(
            self, "artifact_type", _required(self.artifact_type, "artifact_type")
        )
        digest = self.sha256.strip().lower()
        if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True)
class ContextPack:
    task_id: str
    objective: str
    equipment_id: str | None = None
    constraints: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    requested_output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _required(self.task_id, "task_id"))
        object.__setattr__(self, "objective", _required(self.objective, "objective"))
        if self.equipment_id is not None:
            object.__setattr__(
                self, "equipment_id", _required(self.equipment_id, "equipment_id")
            )
        source_ids = [item.source_id for item in self.evidence]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("evidence source_id values must be unique")


@dataclass
class TaskRecord:
    task_id: str
    workspace_id: str
    objective: str
    status: TaskStatus = TaskStatus.RECEIVED
    equipment_id: str | None = None
    assigned_agent: str | None = None
    evidence: list[EvidenceReference] = field(default_factory=list)
    artifacts: list[ArtifactReference] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    version: int = 0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.task_id = _required(self.task_id, "task_id")
        self.workspace_id = _required(self.workspace_id, "workspace_id")
        self.objective = _required(self.objective, "objective")
        if self.version < 0:
            raise ValueError("version must not be negative")

    def transition(self, target: TaskStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid task transition: {self.status} -> {target}")
        self.status = target


@dataclass(frozen=True)
class AgentResult:
    status: str
    summary: str
    evidence_ids: tuple[str, ...] = ()
    artifacts: tuple[ArtifactReference, ...] = ()
    next_actions: tuple[str, ...] = ()
    requires_approval: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed", "needs_input"}:
            raise ValueError("status must be completed, failed, or needs_input")
        object.__setattr__(self, "summary", _required(self.summary, "summary"))

"""Agent Orchestra domain contracts."""

from .models import (
    AgentResult,
    ArtifactReference,
    ContextPack,
    EvidenceReference,
    TaskRecord,
    TaskStatus,
)
from .state_store import (
    AgentOrchestraStateStore,
    StateConflictError,
    StateNotFoundError,
    StateStoreError,
)
from .chat_client import ChatCompletionResult, ContextManagerChatClient
from .artifacts import ArtifactStore, MarkdownArtifactStore
from .specialists import (
    OpenAiSpecialistDispatcher,
    SequentialDelegationPlanner,
    SpecialistAgent,
    SpecialistDispatcher,
    SpecialistOutcome,
)
from .single import (
    OrchestratorExecutionError,
    OrchestratorRequest,
    OrchestratorResult,
    RequestClassifier,
    RequestKind,
    ResultValidationError,
    SingleOrchestrator,
)
from .proposal_workflow import (
    CodeChangeProposal,
    CodeProposalWorkflow,
    ProposalWorkflowError,
    ProposalWorkflowRequest,
    ProposalWorkflowResult,
    ProposedFileChange,
)

__all__ = [
    "AgentResult",
    "ArtifactReference",
    "ContextPack",
    "EvidenceReference",
    "TaskRecord",
    "TaskStatus",
    "AgentOrchestraStateStore",
    "StateConflictError",
    "StateNotFoundError",
    "StateStoreError",
    "ChatCompletionResult",
    "ContextManagerChatClient",
    "ArtifactStore",
    "MarkdownArtifactStore",
    "OpenAiSpecialistDispatcher",
    "SequentialDelegationPlanner",
    "SpecialistAgent",
    "SpecialistDispatcher",
    "SpecialistOutcome",
    "OrchestratorExecutionError",
    "OrchestratorRequest",
    "OrchestratorResult",
    "RequestClassifier",
    "RequestKind",
    "ResultValidationError",
    "SingleOrchestrator",
    "CodeChangeProposal",
    "CodeProposalWorkflow",
    "ProposalWorkflowError",
    "ProposalWorkflowRequest",
    "ProposalWorkflowResult",
    "ProposedFileChange",
]

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol
from uuid import uuid4

from ..build_tools import BuildTools
from ..file_tools import FileTools
from ..git_tools import GitTools
from ..path_guard import PolicyError, resolve_under
from .artifacts import ArtifactStore
from .models import ArtifactReference, TaskRecord, TaskStatus
from .state_store import AgentOrchestraStateStore


@dataclass(frozen=True)
class ProposedFileChange:
    path: str
    content: str
    expected_sha256: str

    def __post_init__(self) -> None:
        if (not self.path.strip() or Path(self.path).is_absolute()
                or any(ord(char) < 32 for char in self.path) or " -> " in self.path):
            raise ValueError("change path must be a relative repository path")
        digest = self.expected_sha256.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("existing-file expected_sha256 is required")
        object.__setattr__(self, "path", Path(self.path).as_posix())
        object.__setattr__(self, "expected_sha256", digest)


@dataclass(frozen=True)
class CodeChangeProposal:
    repo: str
    branch_name: str
    build_target: str
    changes: tuple[ProposedFileChange, ...]
    configuration: str = "Debug"
    run_tests: bool = True
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.repo.strip() or Path(self.repo).is_absolute():
            raise ValueError("repo must be relative to workspace root")
        if not 1 <= len(self.changes) <= 20:
            raise ValueError("proposal must contain 1-20 file changes")
        paths = [item.path.casefold() for item in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("proposal change paths must be unique")
        if self.configuration not in {"Debug", "Release"}:
            raise ValueError("configuration must be Debug or Release")
        if len(self.rationale) > 20_000:
            raise ValueError("rationale is too long")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CodeChangeProposal":
        allowed = {
            "repo", "branch_name", "build_target", "changes",
            "configuration", "run_tests", "rationale",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown proposal fields: {sorted(unknown)}")
        raw_changes = value.get("changes")
        if not isinstance(raw_changes, list):
            raise ValueError("changes must be an array")
        changes = []
        for item in raw_changes:
            if not isinstance(item, dict) or set(item) != {"path", "content", "expected_sha256"}:
                raise ValueError("each change requires path, content and expected_sha256 only")
            changes.append(ProposedFileChange(**item))
        if "run_tests" in value and not isinstance(value["run_tests"], bool):
            raise ValueError("run_tests must be boolean")
        return cls(
            repo=str(value.get("repo", "")),
            branch_name=str(value.get("branch_name", "")),
            build_target=str(value.get("build_target", "")),
            changes=tuple(changes),
            configuration=str(value.get("configuration", "Debug")),
            run_tests=value.get("run_tests", True),
            rationale=str(value.get("rationale", "")),
        )


@dataclass(frozen=True)
class ProposalWorkflowRequest:
    workspace_id: str
    objective: str
    proposal: CodeChangeProposal
    task_id: str = ""
    equipment_id: str | None = None


@dataclass(frozen=True)
class ProposalWorkflowResult:
    task_id: str
    status: str
    branch: str
    base_sha: str
    changed_paths: tuple[str, ...]
    diff: str
    build: dict[str, Any]
    tests: dict[str, Any] | None
    artifacts: tuple[ArtifactReference, ...] = ()
    committed: bool = False


class ProposalWorkflowError(RuntimeError):
    def __init__(self, task_id: str, message: str):
        super().__init__(message)
        self.task_id = task_id


class BuildProvider(Protocol):
    def build_solution(self, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def run_tests(self, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


class CodeProposalWorkflow:
    """Apply a review proposal without staging, committing, pushing or merging."""

    _TEXT_EXTENSIONS = {
        ".cs", ".csproj", ".props", ".targets", ".json", ".xml", ".config", ".md"
    }

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        state_store: AgentOrchestraStateStore,
        artifact_store: ArtifactStore,
        allowed_change_paths: Iterable[str],
        allowed_build_targets: Iterable[str],
        git: GitTools | None = None,
        files: FileTools | None = None,
        build: BuildProvider | None = None,
    ):
        self.workspace_root = Path(workspace_root).expanduser().resolve(strict=True)
        self.state_store = state_store
        self.artifact_store = artifact_store
        self.allowed_change_paths = {
            Path(value).as_posix().casefold() for value in allowed_change_paths
        }
        self.allowed_build_targets = tuple(allowed_build_targets)
        if not self.allowed_change_paths:
            raise ValueError("allowed_change_paths must not be empty")
        if not self.allowed_build_targets:
            raise ValueError("allowed_build_targets must not be empty")
        if not hasattr(artifact_store, "root"):
            raise ValueError("artifact_store must expose an external root")
        self.artifact_root = Path(artifact_store.root).resolve(strict=True)
        try:
            self.artifact_root.relative_to(self.workspace_root)
        except ValueError:
            pass
        else:
            raise ValueError("artifact root must be outside workspace root")
        self.git = git or GitTools(self.workspace_root)
        self.files = files or FileTools(self.workspace_root)
        self.build = build or BuildTools(
            self.workspace_root, allowed_targets=self.allowed_build_targets
        )

    def execute(self, request: ProposalWorkflowRequest) -> ProposalWorkflowResult:
        task_id = request.task_id.strip() or f"proposal-{uuid4().hex}"
        task = self.state_store.create_task(TaskRecord(
            task_id, request.workspace_id, request.objective,
            equipment_id=request.equipment_id,
        ))
        run_id = ""
        branch = request.proposal.branch_name
        base_sha = ""
        lock: tuple[Path, str] | None = None
        try:
            lock = self._acquire_repo_lock(request.proposal.repo)
            self._validate_proposal(request.proposal)
            task = self.state_store.transition_task(
                task_id, TaskStatus.PLANNING, expected_version=task.version,
                assigned_agent="code-proposal-workflow",
            )
            run = self.state_store.start_agent_run(task_id, "code-proposal-workflow")
            run_id = run["run_id"]
            self.state_store.save_checkpoint(task_id, {
                "phase": "proposal_validated",
                "branch": branch,
                "paths": [item.path for item in request.proposal.changes],
                "build_target": request.proposal.build_target,
            })
            self._verify_original_hashes(request.proposal)
            prepared = self.git.prepare_proposal_branch({
                "repo": request.proposal.repo, "name": branch,
            })
            base_sha = prepared["base_sha"]
            task = self.state_store.transition_task(
                task_id, TaskStatus.DELEGATED, expected_version=task.version,
            )
            self.state_store.save_checkpoint(task_id, {
                "phase": "proposal_branch_created", **prepared,
            })
            applied = self._apply_changes(request.proposal)
            self.state_store.save_checkpoint(task_id, {
                "phase": "proposal_files_applied",
                "branch": branch,
                "files": applied,
                "committed": False,
            })
            build_params = {
                "solution": request.proposal.build_target,
                "configuration": request.proposal.configuration,
            }
            build_result = self.build.build_solution(build_params)
            test_result = None
            if build_result.get("ok") and request.proposal.run_tests:
                test_result = self.build.run_tests(build_params)
            comparison = self.git.get_proposal_diff({
                "repo": request.proposal.repo,
                "branch": branch,
                "base_sha": base_sha,
                "expected_paths": [item.path for item in request.proposal.changes],
            })
            task = self.state_store.transition_task(
                task_id, TaskStatus.VALIDATING, expected_version=task.version,
            )
            succeeded = bool(build_result.get("ok")) and (
                test_result is None or bool(test_result.get("ok"))
            )
            report = self._comparison_report(
                request.proposal, comparison, build_result, test_result, succeeded
            )
            artifact = self.artifact_store.create_report(
                task_id=task_id,
                title="Code Change Comparison",
                result=report,
                evidence=(),
                artifact_type="code_change_comparison",
            )
            try:
                self.state_store.add_artifact(task_id, artifact)
            except Exception:
                self.artifact_store.discard(artifact)
                raise
            self.state_store.save_checkpoint(task_id, {
                "phase": "proposal_compared",
                "branch": branch,
                "base_sha": base_sha,
                "changed_paths": comparison["changed_paths"],
                "file_hashes": applied,
                "build_ok": bool(build_result.get("ok")),
                "tests_ok": None if test_result is None else bool(test_result.get("ok")),
                "artifact_path": artifact.path,
                "committed": False,
            })
            if not succeeded:
                reason = "build failed" if not build_result.get("ok") else "tests failed"
                raise RuntimeError(reason)
            self.state_store.finish_agent_run(
                run_id, status="completed", summary="Proposal ready for human review; no commit created"
            )
            task = self.state_store.get_task(task_id)
            self.state_store.transition_task(
                task_id, TaskStatus.COMPLETED, expected_version=task.version
            )
            return ProposalWorkflowResult(
                task_id=task_id,
                status="ready_for_review",
                branch=branch,
                base_sha=base_sha,
                changed_paths=tuple(comparison["changed_paths"]),
                diff=comparison["diff"],
                build=build_result,
                tests=test_result,
                artifacts=(artifact,),
                committed=False,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {str(exc)[:500]}"
            if run_id:
                try:
                    self.state_store.finish_agent_run(run_id, status="failed", error=reason)
                except Exception:
                    pass
            try:
                current = self.state_store.get_task(task_id)
                if current.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                    self.state_store.transition_task(
                        task_id, TaskStatus.FAILED,
                        expected_version=current.version, failure_reason=reason,
                    )
            except Exception:
                pass
            raise ProposalWorkflowError(task_id, reason) from exc
        finally:
            if lock is not None:
                self._release_repo_lock(*lock)

    def _validate_proposal(self, proposal: CodeChangeProposal) -> None:
        repo = resolve_under(self.workspace_root, proposal.repo)
        for change in proposal.changes:
            target = resolve_under(repo, change.path)
            relative = target.relative_to(repo).as_posix()
            if relative.casefold() not in self.allowed_change_paths:
                raise PolicyError(f"Change path is not allowlisted: {relative}")
            if target.suffix.lower() not in self._TEXT_EXTENSIONS:
                raise PolicyError(f"Unsupported change file type: {target.suffix}")
            if not target.is_file():
                raise PolicyError("Phase 4B supports existing text files only")
        target = Path(proposal.build_target).as_posix().casefold()
        allowed = {Path(value).as_posix().casefold() for value in self.allowed_build_targets}
        if target not in allowed:
            raise PolicyError("Build target is not allowlisted")

    def _acquire_repo_lock(self, repo_value: str) -> tuple[Path, str]:
        repo = resolve_under(self.workspace_root, repo_value)
        digest = hashlib.sha256(str(repo).casefold().encode("utf-8")).hexdigest()
        lock_dir = self.artifact_root / ".proposal-locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{digest}.lock"
        token = uuid4().hex
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise PolicyError(
                f"Another proposal workflow holds the repository lock: {lock_path}"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        return lock_path, token

    @staticmethod
    def _release_repo_lock(lock_path: Path, token: str) -> None:
        try:
            if lock_path.read_text(encoding="utf-8") == token:
                lock_path.unlink()
        except FileNotFoundError:
            pass

    def _verify_original_hashes(self, proposal: CodeChangeProposal) -> None:
        for change in proposal.changes:
            path = f"{Path(proposal.repo).as_posix()}/{change.path}"
            current = self.files.read_workspace_file({"path": path})
            if current["sha256"] != change.expected_sha256:
                raise PolicyError(f"File changed since proposal was prepared: {change.path}")

    def _apply_changes(self, proposal: CodeChangeProposal) -> list[dict[str, str]]:
        applied: list[dict[str, str]] = []
        for change in proposal.changes:
            path = f"{Path(proposal.repo).as_posix()}/{change.path}"
            result = self.files.write_workspace_file({
                "path": path,
                "content": change.content,
                "expected_sha256": change.expected_sha256,
            })
            applied.append({
                "path": change.path,
                "before_sha256": change.expected_sha256,
                "after_sha256": result["sha256"],
            })
        return applied

    @staticmethod
    def _comparison_report(
        proposal: CodeChangeProposal,
        comparison: dict[str, Any],
        build: dict[str, Any],
        tests: dict[str, Any] | None,
        succeeded: bool,
    ) -> str:
        def result_block(label: str, value: dict[str, Any] | None) -> str:
            if value is None:
                return f"### {label}\n\nNot requested."
            return (
                f"### {label}\n\n- Success: `{bool(value.get('ok'))}`\n"
                f"- Exit code: `{value.get('exit_code', '')}`\n\n"
                f"```text\n{str(value.get('stdout', ''))[-8000:]}\n"
                f"{str(value.get('stderr', ''))[-4000:]}\n```"
            )
        return "\n\n".join([
            f"- Review status: `{'READY' if succeeded else 'FAILED'}`",
            f"- Branch: `{comparison['branch']}`",
            f"- Base/HEAD: `{comparison['base_sha']}` (unchanged; no commit)",
            f"- Changed files: {', '.join(comparison['changed_paths'])}",
            f"- Rationale: {proposal.rationale or 'not supplied'}",
            result_block("Build", build),
            result_block("Tests", tests),
            f"### Diff against base\n\n```diff\n{comparison['diff']}\n```",
            "No file was staged or committed. Human review is required.",
        ])

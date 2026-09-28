from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes_equipment_poc.orchestrator import (
    AgentOrchestraStateStore,
    ChatCompletionResult,
    CodeChangeProposal,
    CodeProposalWorkflow,
    MarkdownArtifactStore,
    OrchestratorRequest,
    ProposalWorkflowError,
    ProposalWorkflowRequest,
    ProposedFileChange,
    SingleOrchestrator,
    TaskStatus,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, text=True, capture_output=True,
    )
    return result.stdout.strip()


class FakeRag:
    def retrieve(self, **_: Any) -> dict[str, Any]:
        return {"sources": [{
            "source_id": "D1", "record_id": "doc-1", "source_type": "document",
            "file_name": "manual.md", "text": "Check sensor input first.",
        }]}


class FakeChat:
    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        **_: Any,
    ) -> ChatCompletionResult:
        return ChatCompletionResult("Sensor 입력을 확인한다 [D1].", finish_reason="stop")


class FakeBuild:
    def __init__(self, *, build_ok: bool = True, tests_ok: bool = True):
        self.build_ok = build_ok
        self.tests_ok = tests_ok
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def build_solution(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.calls.append(("build", dict(params)))
        return {"ok": self.build_ok, "exit_code": 0 if self.build_ok else 1,
                "stdout": "build output", "stderr": ""}

    def run_tests(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.calls.append(("test", dict(params)))
        return {"ok": self.tests_ok, "exit_code": 0 if self.tests_ok else 1,
                "stdout": "test output", "stderr": ""}


class MarkdownArtifactTests(unittest.TestCase):
    def test_orchestrator_creates_hash_verified_registered_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            store = AgentOrchestraStateStore(root / "state.db")
            store.create_workspace("W", name="Workspace", root_path=str(workspace))
            artifacts = MarkdownArtifactStore(root / "artifacts")
            result = SingleOrchestrator(
                store, FakeRag(), FakeChat(), artifact_store=artifacts
            ).run(OrchestratorRequest(
                "W", "진공 알람 문서를 분석해줘", task_id="TASK/unsafe",
                create_artifact=True,
            ))

            self.assertEqual(len(result.artifacts), 1)
            artifact = result.artifacts[0]
            path = Path(artifact.path)
            self.assertTrue(path.is_file())
            self.assertTrue(path.is_relative_to(root / "artifacts"))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact.sha256)
            self.assertEqual(store.get_task(result.task_id).artifacts, [artifact])
            self.assertIn("[D1]", path.read_text(encoding="utf-8"))

    def test_orchestrator_rejects_artifact_root_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            store = AgentOrchestraStateStore(root / "state.db")
            store.create_workspace("W", name="Workspace", root_path=str(workspace))
            engine = SingleOrchestrator(
                store, FakeRag(), FakeChat(),
                artifact_store=MarkdownArtifactStore(workspace / "artifacts"),
            )
            with self.assertRaisesRegex(Exception, "outside workspace"):
                engine.run(OrchestratorRequest(
                    "W", "문서 분석", task_id="T", create_artifact=True,
                ))
            self.assertEqual(store.get_task("T").status, TaskStatus.FAILED)

    def test_artifact_is_exclusive_create_and_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = MarkdownArtifactStore(temp)
            first = artifacts.create_report(
                task_id="T", title="Report", result="first", evidence=()
            )
            with self.assertRaises(FileExistsError):
                artifacts.create_report(
                    task_id="T", title="Report", result="second", evidence=()
                )
            self.assertIn("first", Path(first.path).read_text(encoding="utf-8"))

    def test_artifact_type_cannot_escape_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "unsafe"):
                MarkdownArtifactStore(temp).create_report(
                    task_id="T", title="Report", result="result", evidence=(),
                    artifact_type="../escape",
                )


class CodeProposalWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "PoC Test")
        git(self.repo, "config", "user.email", "poc@example.invalid")
        self.code = self.repo / "Machine.cs"
        self.code.write_text("class Machine { int Timeout = 10; }\n", encoding="utf-8")
        (self.repo / "Equipment.csproj").write_text("<Project />\n", encoding="utf-8")
        git(self.repo, "add", "Machine.cs", "Equipment.csproj")
        git(self.repo, "commit", "-m", "initial")
        self.store = AgentOrchestraStateStore(self.root / "state.db")
        self.store.create_workspace("W", name="Workspace", root_path=str(self.workspace))
        self.artifacts = MarkdownArtifactStore(self.root / "artifacts")

    def proposal(self, **overrides: Any) -> CodeChangeProposal:
        values = {
            "repo": "repo",
            "branch_name": "work/ao-timeout-change",
            "build_target": "repo/Equipment.csproj",
            "changes": (ProposedFileChange(
                "Machine.cs",
                "class Machine { int Timeout = 20; }\n",
                hashlib.sha256(self.code.read_bytes()).hexdigest(),
            ),),
            "rationale": "Increase bounded timeout after review",
        }
        values.update(overrides)
        return CodeChangeProposal(**values)

    def workflow(self, build: FakeBuild | None = None, **kwargs: Any) -> CodeProposalWorkflow:
        return CodeProposalWorkflow(
            workspace_root=self.workspace,
            state_store=self.store,
            artifact_store=self.artifacts,
            allowed_change_paths=kwargs.get("allowed_change_paths", ["Machine.cs"]),
            allowed_build_targets=kwargs.get("allowed_build_targets", ["repo/Equipment.csproj"]),
            build=build or FakeBuild(),
        )

    def test_apply_build_test_and_compare_without_stage_or_commit(self) -> None:
        base = git(self.repo, "rev-parse", "HEAD")
        build = FakeBuild()
        proposal = self.proposal()
        result = self.workflow(build).execute(ProposalWorkflowRequest(
            "W", "Timeout 변경 제안", proposal, task_id="P1",
        ))

        self.assertEqual(result.status, "ready_for_review")
        self.assertEqual(result.base_sha, base)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), base)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "work/ao-timeout-change")
        self.assertEqual(git(self.repo, "diff", "--cached"), "")
        self.assertIn("Timeout = 20", result.diff)
        self.assertFalse(result.committed)
        self.assertEqual([item[0] for item in build.calls], ["build", "test"])
        self.assertEqual(self.store.get_task("P1").status, TaskStatus.COMPLETED)
        self.assertEqual(len(self.store.get_task("P1").artifacts), 1)
        self.assertIn("No file was staged or committed", Path(result.artifacts[0].path).read_text())
        hashes = self.store.latest_checkpoint("P1")["payload"]["file_hashes"]  # type: ignore[index]
        self.assertEqual(hashes[0]["before_sha256"], proposal.changes[0].expected_sha256)
        self.assertEqual(hashes[0]["after_sha256"], hashlib.sha256(self.code.read_bytes()).hexdigest())

    def test_build_failure_leaves_review_branch_uncommitted_and_fails_task(self) -> None:
        base = git(self.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ProposalWorkflowError, "build failed"):
            self.workflow(FakeBuild(build_ok=False)).execute(ProposalWorkflowRequest(
                "W", "Failing proposal", self.proposal(), task_id="P2",
            ))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), base)
        self.assertEqual(git(self.repo, "diff", "--cached"), "")
        self.assertIn("Timeout = 20", self.code.read_text())
        task = self.store.get_task("P2")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(len(task.artifacts), 1)

    def test_disallowed_file_rejected_before_branch_creation(self) -> None:
        with self.assertRaisesRegex(ProposalWorkflowError, "not allowlisted"):
            self.workflow(allowed_change_paths=["Other.cs"]).execute(
                ProposalWorkflowRequest("W", "proposal", self.proposal(), task_id="P3")
            )
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(self.store.get_task("P3").status, TaskStatus.FAILED)

    def test_stale_hash_rejected_before_branch_creation(self) -> None:
        stale = self.proposal(changes=(ProposedFileChange(
            "Machine.cs", "changed\n", "0" * 64,
        ),))
        with self.assertRaisesRegex(ProposalWorkflowError, "changed since proposal"):
            self.workflow().execute(ProposalWorkflowRequest(
                "W", "proposal", stale, task_id="P4",
            ))
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")

    def test_dirty_base_is_rejected_and_user_change_is_preserved(self) -> None:
        self.code.write_text("user work\n", encoding="utf-8")
        changed_hash = hashlib.sha256(self.code.read_bytes()).hexdigest()
        proposal = self.proposal(changes=(ProposedFileChange(
            "Machine.cs", "agent work\n", changed_hash,
        ),))
        with self.assertRaisesRegex(ProposalWorkflowError, "must be clean"):
            self.workflow().execute(ProposalWorkflowRequest(
                "W", "proposal", proposal, task_id="P5",
            ))
        self.assertEqual(self.code.read_text(), "user work\n")

    def test_unexpected_build_generated_file_fails_comparison(self) -> None:
        class GeneratingBuild(FakeBuild):
            def build_solution(inner_self, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                (self.repo / "generated.tmp").write_text("unexpected", encoding="utf-8")
                return super().build_solution(params, **kwargs)
        with self.assertRaisesRegex(ProposalWorkflowError, "Working tree differs"):
            self.workflow(GeneratingBuild()).execute(ProposalWorkflowRequest(
                "W", "proposal", self.proposal(), task_id="P6",
            ))

    def test_artifact_root_inside_workspace_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside workspace"):
            CodeProposalWorkflow(
                workspace_root=self.workspace,
                state_store=self.store,
                artifact_store=MarkdownArtifactStore(self.workspace / "artifacts"),
                allowed_change_paths=["Machine.cs"],
                allowed_build_targets=["repo/Equipment.csproj"],
                build=FakeBuild(),
            )

    def test_proposal_json_rejects_ambiguous_boolean_and_unknown_fields(self) -> None:
        base = {
            "repo": "repo",
            "branch_name": "work/ao-change",
            "build_target": "repo/Equipment.csproj",
            "changes": [{
                "path": "Machine.cs", "content": "new",
                "expected_sha256": "0" * 64,
            }],
        }
        with self.assertRaisesRegex(ValueError, "run_tests must be boolean"):
            CodeChangeProposal.from_dict({**base, "run_tests": "false"})
        with self.assertRaisesRegex(ValueError, "unknown proposal fields"):
            CodeChangeProposal.from_dict({**base, "commit": True})

    def test_repository_lock_blocks_concurrent_proposal(self) -> None:
        first = self.workflow()
        lock = first._acquire_repo_lock("repo")
        try:
            with self.assertRaisesRegex(ProposalWorkflowError, "repository lock"):
                self.workflow().execute(ProposalWorkflowRequest(
                    "W", "proposal", self.proposal(), task_id="P7",
                ))
        finally:
            first._release_repo_lock(*lock)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")


if __name__ == "__main__":
    unittest.main()

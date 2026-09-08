from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

from .path_guard import PolicyError, reject_git_metadata, resolve_under


PROTECTED_BRANCHES = {"main", "master"}


class GitTools:
    def __init__(self, workspace_root: str | Path, timeout_seconds: int = 60):
        self.workspace_root = Path(workspace_root).expanduser().resolve(strict=True)
        self.timeout_seconds = timeout_seconds

    def _repo(self, value: Any) -> Path:
        repo = resolve_under(self.workspace_root, str(value or "."))
        if not (repo / ".git").exists():
            raise PolicyError(f"Not a Git repository: {repo}")
        return repo

    def _run(self, repo: Path, args: Sequence[str], *, check: bool = True) -> dict[str, Any]:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        result = {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-20000:],
            "stderr": completed.stderr[-8000:],
        }
        if check and completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args[:2])} failed: {completed.stderr.strip()}")
        return result

    def _branch(self, repo: Path) -> str:
        result = self._run(repo, ["branch", "--show-current"])
        branch = result["stdout"].strip()
        if not branch:
            raise PolicyError("Detached HEAD is not allowed for write operations")
        return branch

    def get_status(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._run(self._repo(params.get("repo")), ["status", "--short", "--branch"])

    def get_diff(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        args = ["diff"]
        if bool(params.get("staged")):
            args.append("--cached")
        args.extend(["--", "."])
        return self._run(self._repo(params.get("repo")), args)

    def get_log(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        limit = max(1, min(int(params.get("limit", 20)), 100))
        return self._run(self._repo(params.get("repo")), ["log", f"-{limit}", "--oneline", "--decorate"])

    def list_branches(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._run(self._repo(params.get("repo")), ["branch", "--list", "--format=%(refname:short)"])

    def create_branch(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        repo = self._repo(params.get("repo"))
        name = str(params.get("name", "")).strip()
        if not name or name.lower() in PROTECTED_BRANCHES or name.startswith("-"):
            raise PolicyError("A non-protected work branch name is required")
        return self._run(repo, ["switch", "-c", name])

    def checkout_work_branch(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        repo = self._repo(params.get("repo"))
        name = str(params.get("name", "")).strip()
        if not name or name.lower() in PROTECTED_BRANCHES or name.startswith("-"):
            raise PolicyError("Checkout of a protected branch is not allowed through this tool")
        return self._run(repo, ["switch", name])

    def stage_files(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        repo = self._repo(params.get("repo"))
        if self._branch(repo).lower() in PROTECTED_BRANCHES:
            raise PolicyError("Staging on a protected branch is forbidden")
        raw_paths = params.get("paths") or []
        if not raw_paths:
            raise ValueError("paths is required; implicit stage-all is forbidden")
        relative_paths: list[str] = []
        for raw in raw_paths:
            path = resolve_under(repo, str(raw))
            reject_git_metadata(path, repo)
            relative_paths.append(str(path.relative_to(repo)))
        return self._run(repo, ["add", "--", *relative_paths])

    def commit_work_branch(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        repo = self._repo(params.get("repo"))
        branch = self._branch(repo)
        if branch.lower() in PROTECTED_BRANCHES:
            raise PolicyError("Direct commit to a protected branch is forbidden")
        message = str(params.get("message", "")).strip()
        if not 3 <= len(message) <= 200 or "\n" in message:
            raise ValueError("Commit message must be a single line of 3-200 characters")
        self._run(repo, ["diff", "--cached", "--quiet"], check=False)
        result = self._run(repo, ["commit", "-m", message])
        result["branch"] = branch
        result["commit"] = self._run(repo, ["rev-parse", "HEAD"])["stdout"].strip()
        return result

    def _execute_main_merge(self, params: dict[str, Any]) -> dict[str, Any]:
        """Private executor. It is intentionally never registered as a Hermes tool."""
        repo = self._repo(params.get("repo"))
        source = str(params.get("source_branch", "")).strip()
        expected_sha = str(params.get("expected_sha", "")).strip().lower()
        if not source or source.lower() in PROTECTED_BRANCHES or source.startswith("-"):
            raise PolicyError("A non-protected source branch is required")
        actual_sha = self._run(repo, ["rev-parse", source])["stdout"].strip().lower()
        if not expected_sha or actual_sha != expected_sha:
            raise PolicyError("Source branch SHA does not match the approved request")
        if self._run(repo, ["status", "--porcelain"])["stdout"].strip():
            raise PolicyError("Working tree must be clean before merge")
        self._run(repo, ["switch", "main"])
        if self._run(repo, ["rev-parse", source])["stdout"].strip().lower() != expected_sha:
            raise PolicyError("Source branch changed after approval")
        result = self._run(repo, ["merge", "--no-ff", source, "-m", f"Merge {source}"])
        result["target_branch"] = "main"
        result["source_sha"] = expected_sha
        result["merge_commit"] = self._run(repo, ["rev-parse", "HEAD"])["stdout"].strip()
        return result

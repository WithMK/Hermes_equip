from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .git_tools import GitTools
from .path_guard import PolicyError


class MergeApprovalBroker:
    """File-backed one-time approval queue kept outside the agent workspace."""

    def __init__(self, store: str | Path, git_tools: GitTools):
        self.store = Path(store).expanduser().resolve(strict=False)
        self.git_tools = git_tools
        self.store.mkdir(parents=True, exist_ok=True)

    def request(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        repo = self.git_tools._repo(params.get("repo"))
        source = str(params.get("source_branch", "")).strip()
        expected_sha = str(params.get("expected_sha", "")).strip().lower()
        if not source or source.lower() in {"main", "master"} or source.startswith("-"):
            raise PolicyError("A non-protected source branch is required")
        actual_sha = self.git_tools._run(repo, ["rev-parse", source])["stdout"].strip().lower()
        if not expected_sha or actual_sha != expected_sha:
            raise PolicyError("Source branch SHA does not match the merge request")
        request_id = uuid.uuid4().hex
        record = {
            "request_id": request_id,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "repo": str(repo),
            "source_branch": source,
            "source_sha": expected_sha,
            "target_branch": "main",
        }
        path = self.store / f"{request_id}.pending.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        return {**record, "approval_required": True, "executed": False,
                "message": "A human must approve this request outside the Hermes agent runtime."}

    def approve_and_execute(self, request_id: str) -> dict[str, Any]:
        if not request_id or not request_id.isalnum() or len(request_id) > 64:
            raise PolicyError("Invalid request id")
        pending = self.store / f"{request_id}.pending.json"
        processing = self.store / f"{request_id}.processing.json"
        try:
            os.replace(pending, processing)
        except FileNotFoundError as exc:
            raise PolicyError("Pending merge request does not exist or was already consumed") from exc
        try:
            record = json.loads(processing.read_text(encoding="utf-8"))
            result = self.git_tools._execute_main_merge({
                "repo": record["repo"],
                "source_branch": record["source_branch"],
                "expected_sha": record["source_sha"],
            })
            completed = {**record, "status": "completed",
                         "approved_at": datetime.now(timezone.utc).isoformat(), "result": result}
            completed_path = self.store / f"{request_id}.completed.json"
            completed_path.write_text(json.dumps(completed, ensure_ascii=False, indent=2), encoding="utf-8")
            processing.unlink()
            return completed
        except Exception as exc:
            failed = self.store / f"{request_id}.failed.json"
            processing.replace(failed)
            raise RuntimeError(f"Approved merge failed: {type(exc).__name__}: {exc}") from exc


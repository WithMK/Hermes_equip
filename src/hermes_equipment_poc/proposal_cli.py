from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .orchestrator import AgentOrchestraStateStore, MarkdownArtifactStore, StateNotFoundError
from .orchestrator.proposal_workflow import (
    CodeChangeProposal,
    CodeProposalWorkflow,
    ProposalWorkflowError,
    ProposalWorkflowRequest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply an allowlisted code proposal on an uncommitted work branch"
    )
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--workspace-name", default="Equipment workspace")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--equipment-id")
    parser.add_argument("--objective", required=True)
    parser.add_argument("--proposal-json", required=True)
    parser.add_argument("--allowed-change-path", action="append", default=[])
    parser.add_argument("--allowed-build-target", action="append", default=[])
    parser.add_argument("--confirm-proposal-apply", action="store_true")
    return parser


def _load_proposal(path_value: str) -> CodeChangeProposal:
    path = Path(path_value).expanduser().resolve(strict=True)
    if path.stat().st_size > 2_000_000:
        raise ValueError("proposal JSON exceeds 2 MB")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("proposal JSON must be an object")
    return CodeChangeProposal.from_dict(value)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.confirm_proposal_apply:
            raise ValueError("--confirm-proposal-apply is required")
        store = AgentOrchestraStateStore(args.state_db)
        try:
            store.get_workspace(args.workspace_id)
        except StateNotFoundError:
            store.create_workspace(
                args.workspace_id,
                name=args.workspace_name,
                root_path=str(Path(args.workspace_root).resolve(strict=True)),
            )
        workflow = CodeProposalWorkflow(
            workspace_root=args.workspace_root,
            state_store=store,
            artifact_store=MarkdownArtifactStore(args.artifact_root),
            allowed_change_paths=args.allowed_change_path,
            allowed_build_targets=args.allowed_build_target,
        )
        result = workflow.execute(ProposalWorkflowRequest(
            workspace_id=args.workspace_id,
            objective=args.objective,
            proposal=_load_proposal(args.proposal_json),
            task_id=args.task_id,
            equipment_id=args.equipment_id,
        ))
        print(json.dumps({"ok": True, **asdict(result)}, ensure_ascii=False, indent=2))
        return 0
    except ProposalWorkflowError as exc:
        print(json.dumps(
            {"ok": False, "task_id": exc.task_id, "error": str(exc)},
            ensure_ascii=False, indent=2,
        ))
        return 1
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "error_type": type(exc).__name__, "error": str(exc)},
            ensure_ascii=False, indent=2,
        ))
        return 1


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .git_tools import GitTools
from .merge_broker import MergeApprovalBroker


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve and execute one pending main merge request")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--approval-store", required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    git = GitTools(Path(args.workspace_root))
    broker = MergeApprovalBroker(Path(args.approval_store), git)
    pending = Path(args.approval_store).expanduser().resolve() / f"{args.request_id}.pending.json"
    record = json.loads(pending.read_text(encoding="utf-8"))
    print(json.dumps(record, ensure_ascii=False, indent=2))
    confirmation = input(f"Type APPROVE {args.request_id} to merge into main: ").strip()
    if confirmation != f"APPROVE {args.request_id}":
        print("Denied. No merge was executed.")
        return 2
    result = broker.approve_and_execute(args.request_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


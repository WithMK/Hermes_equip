from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditWriter:
    def __init__(self, path: str | Path, agent_id: str):
        self.path = Path(path)
        self.agent_id = agent_id
        self._lock = threading.Lock()

    def write(self, event: str, **payload: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "agent_id": self.agent_id,
            **payload,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def pre_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> dict[str, str] | None:
        self.write("pre_tool_call", tool_name=tool_name, tool_input=args, **_ids(kwargs))
        return None

    def post_tool_call(self, tool_name: str, args: dict[str, Any], result: str, **kwargs: Any) -> None:
        self.write(
            "post_tool_call",
            tool_name=tool_name,
            tool_input=args,
            tool_result=result,
            duration_ms=kwargs.get("duration_ms"),
            status=kwargs.get("status"),
            error=kwargs.get("error_message"),
            **_ids(kwargs),
        )

    def skill_lifecycle(self, action: str, skill_name: str, **kwargs: Any) -> None:
        self.write("skill_lifecycle", action=action, skill_id=skill_name, **_ids(kwargs))

    def approval_request(self, command: str, description: str, **kwargs: Any) -> None:
        self.write("approval_request", command=command, description=description, **_ids(kwargs))

    def approval_response(self, command: str, description: str, choice: str, **kwargs: Any) -> None:
        self.write(
            "approval_response",
            command=command,
            description=description,
            approval=choice,
            **_ids(kwargs),
        )


def _ids(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: values.get(key)
        for key in ("task_id", "session_id", "turn_id", "tool_call_id", "api_request_id")
        if values.get(key) not in (None, "")
    }

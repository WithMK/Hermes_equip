from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..http_client import JsonApiClient
from .validation import validate_finish


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    model: str = ""
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("chat completion content is required")


@dataclass(frozen=True)
class ContextManagerChatClient:
    """OpenAI-compatible client for the external ContextManager proxy."""

    http: JsonApiClient
    model: str
    chat_path: str = "/v1/chat/completions"
    session_field: str = "session_id"

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        session_id: str = "",
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> ChatCompletionResult:
        model = self.model.strip()
        if not model:
            raise ValueError("ContextManager model is required")
        if not messages:
            raise ValueError("messages are required")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        normalized: list[dict[str, str]] = []
        for index, message in enumerate(messages):
            role = str(message.get("role", "")).strip()
            content = str(message.get("content", "")).strip()
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"messages[{index}].role is invalid")
            if not content:
                raise ValueError(f"messages[{index}].content is required")
            normalized.append({"role": role, "content": content})
        payload: dict[str, Any] = {
            "model": model,
            "messages": normalized,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if session_id.strip() and self.session_field.strip():
            payload[self.session_field.strip()] = session_id.strip()
        response = self.http.post(self.chat_path, payload)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("ContextManager response has no completion choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("ContextManager response has no message content")
        usage = response.get("usage")
        validate_finish(str(choice.get("finish_reason", "")))
        if message.get("tool_calls"):
            raise ValueError("unresolved tool calls in completion")
        return ChatCompletionResult(
            content=message["content"].strip(),
            model=str(response.get("model", model)),
            finish_reason=str(choice.get("finish_reason", "")),
            usage=dict(usage) if isinstance(usage, dict) else {},
        )

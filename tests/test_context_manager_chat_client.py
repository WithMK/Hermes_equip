from __future__ import annotations

import unittest
from typing import Any

from hermes_equipment_poc.orchestrator import ContextManagerChatClient


class FakeHttp:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, payload))
        return self.response


class ContextManagerChatClientTests(unittest.TestCase):
    def test_posts_openai_payload_with_configurable_session_field(self) -> None:
        http = FakeHttp(
            {
                "model": "qwen-local",
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 12},
            }
        )
        client = ContextManagerChatClient(  # type: ignore[arg-type]
            http,
            "qwen-local",
            session_field="conversation_id",
        )

        result = client.complete(
            [{"role": "user", "content": "test"}],
            session_id="session-1",
            max_tokens=64,
        )

        path, payload = http.calls[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(payload["conversation_id"], "session-1")
        self.assertEqual(payload["max_tokens"], 64)
        self.assertEqual(result.content, "done")
        self.assertEqual(result.usage["total_tokens"], 12)

    def test_can_omit_nonstandard_session_field(self) -> None:
        http = FakeHttp(
            {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )
        client = ContextManagerChatClient(  # type: ignore[arg-type]
            http,
            "qwen-local",
            session_field="",
        )

        client.complete([{"role": "user", "content": "test"}], session_id="ignored")

        self.assertNotIn("session_id", http.calls[0][1])

    def test_rejects_malformed_completion(self) -> None:
        client = ContextManagerChatClient(  # type: ignore[arg-type]
            FakeHttp({"choices": []}),
            "qwen-local",
        )
        with self.assertRaisesRegex(ValueError, "no completion choice"):
            client.complete([{"role": "user", "content": "test"}])


if __name__ == "__main__":
    unittest.main()

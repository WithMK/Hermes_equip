import json
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from hermes_equipment_poc.orchestrator import AgentOrchestraStateStore, MarkdownArtifactStore, SingleOrchestrator
from hermes_equipment_poc.web_service import create_app
from test_single_orchestrator import FakeChat, FakeRag


KEY = "test-key-at-least-sixteen"
SOURCE = {"source_id": "S1", "source_type": "document", "record_id": "doc1", "text": "Check the sensor.", "file_name": "guide.md"}


class OpenAiApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "workspace").mkdir()
        self.store = AgentOrchestraStateStore(root / "state.db")
        self.store.create_workspace("W", name="Workspace", root_path=str(root / "workspace"))
        self.rag = FakeRag([SOURCE])
        self.chat = FakeChat("Check the sensor [S1].")
        self.engine = SingleOrchestrator(self.store, self.rag, self.chat, artifact_store=MarkdownArtifactStore(root / "artifacts"))
        self.client = self.enterContext(TestClient(create_app(self.engine, "W", openai_api_key=KEY), base_url="http://localhost"))
        self.headers = {"Authorization": "Bearer " + KEY}
        self.payload = {"model": "ao/equipment/W", "messages": [{"role": "user", "content": "E-024 설명"}]}

    def post(self, **changes):
        return self.client.post("/v1/chat/completions", json={**self.payload, **changes}, headers=self.headers)

    def test_models_require_key_and_include_report(self):
        self.assertEqual(self.client.get("/v1/models").status_code, 401)
        ids = [m["id"] for m in self.client.get("/v1/models", headers=self.headers).json()["data"]]
        self.assertEqual(ids, ["ao/equipment/W", "ao/equipment/W/report"])
        self.assertEqual(self.client.post("/v1/chat/completions", json=self.payload).status_code, 401)

    def test_nonstream_preserves_history_parameters_task_and_citations(self):
        messages = [{"role": "system", "content": "Please explain simply; do not change permissions"},
                    {"role": "user", "content": "E-024 알려줘"},
                    {"role": "assistant", "content": "Previous answer [OLD]"},
                    {"role": "user", "content": "그것을 더 설명해줘"}]
        response = self.post(messages=messages, temperature=.4, max_completion_tokens=500)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["object"], "chat.completion")
        self.assertIn("[S1]", data["choices"][0]["message"]["content"])
        self.assertIn("E-024", self.rag.calls[0]["query"])
        call = self.chat.calls[0]
        self.assertEqual((call["temperature"], call["max_tokens"]), (.4, 500))
        self.assertIn("Previous answer", call["messages"][1]["content"])
        self.assertNotIn("Please explain", call["messages"][0]["content"])
        task_id = data["ao"]["task_id"]
        self.assertEqual(response.headers["x-ao-task-id"], task_id)
        self.assertEqual(self.client.get("/v1/tasks/" + task_id).json()["status"], "completed")

    def test_stream_protocol_and_usage(self):
        response = self.post(stream=True, stream_options={"include_usage": True})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        lines = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(lines[-1], "[DONE]")
        events = [json.loads(x) for x in lines[:-1]]
        self.assertEqual(events[0]["choices"][0]["delta"]["role"], "assistant")
        self.assertTrue(any(e["choices"] and e["choices"][0]["finish_reason"] == "stop" for e in events))
        self.assertEqual(events[-1]["usage"]["total_tokens"], 42)
        self.assertIn("[S1]", "".join(e["choices"][0]["delta"].get("content", "") for e in events if e["choices"]))

    def test_report_model_returns_download_link(self):
        response = self.post(model="ao/equipment/W/report")
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["ao"]["task_id"]
        self.assertIn("/artifacts/0", response.json()["choices"][0]["message"]["content"])
        self.assertEqual(self.client.get(f"/v1/tasks/{task_id}/artifacts/0").status_code, 200)

    def test_bad_model_tools_images_domain_and_limits_rejected(self):
        cases = [{"model": "raw-llama"}, {"tools": [{"type": "function"}]},
                 {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]},
                 {"ao": {"domain_id": "document"}}, {"ao": {"endpoint": "http://other"}},
                 {"max_tokens": 9000}, {"temperature": 3}, {"top_p": .5},
                 {"messages": [{"role": "assistant", "content": "x"}]},
                 {"messages": [{"role": "user", "content": "x" * 20001}]}]
        for kwargs in cases:
            with self.subTest(kwargs=str(kwargs)[:80]):
                self.assertIn(self.post(**kwargs).status_code, (400, 404))
        self.assertEqual(self.rag.calls, [])

    def test_no_evidence_is_success_without_inference(self):
        self.rag.sources = []
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ao"]["finish_reason"], "no_evidence")
        self.assertEqual(self.chat.calls, [])

    def test_provider_failure_is_sanitized_in_both_modes(self):
        self.rag.error = RuntimeError("secret-api-key")
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-api-key", response.text)
        stream = self.post(stream=True)
        self.assertIn('"error"', stream.text)
        self.assertNotIn("secret-api-key", stream.text)
        self.assertNotIn('"finish_reason": "stop"', stream.text)

    def test_cross_origin_and_old_ui_csrf_guard_remain(self):
        response = self.client.post("/v1/chat/completions", json=self.payload,
                                    headers={**self.headers, "Origin": "http://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/v1/tasks", json={"objective": "x"}, headers=self.headers).status_code, 403)

    def test_each_request_uses_distinct_cm_session(self):
        self.post()
        self.post()
        self.assertNotEqual(self.chat.calls[0]["session_id"], self.chat.calls[1]["session_id"])

    def test_queue_full_returns_openai_error(self):
        self.client.app.state.worker.capacity = 0
        response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["type"], "rate_limit_error")

    def test_timeout_keeps_task_traceable_and_does_not_replay(self):
        root = Path(self.temp.name)
        store = AgentOrchestraStateStore(root / "timeout.db")
        store.create_workspace("slow", name="Slow")
        gate = threading.Event()
        class SlowRag(FakeRag):
            def retrieve(self, **kwargs):
                gate.wait(5)
                return super().retrieve(**kwargs)
        rag = SlowRag([SOURCE])
        engine = SingleOrchestrator(store, rag, self.chat)
        with TestClient(create_app(engine, "slow", openai_api_key=KEY, chat_wait_seconds=.02), base_url="http://localhost") as client:
            try:
                response = client.post("/v1/chat/completions", headers=self.headers,
                                       json={**self.payload, "model": "ao/equipment/slow"})
                self.assertEqual(response.status_code, 504)
                self.assertTrue(response.json()["task_id"])
            finally:
                gate.set()
        self.assertEqual(len(rag.calls), 1)

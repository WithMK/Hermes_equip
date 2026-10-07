"""Local authenticated OpenAI chat facade over the durable A/O worker."""
from __future__ import annotations

import asyncio
import hmac
import json
import time
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=30000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str
    messages: list[Message] = Field(min_length=1, max_length=41)
    stream: bool = False
    stream_options: dict | None = None
    temperature: float = Field(default=.1, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=1, le=8192)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=8192)
    user: str | None = None
    metadata: dict | None = None
    # Default OpenAI knobs are accepted; non-default unsupported features fail explicitly.
    top_p: float = 1
    frequency_penalty: float = 0
    presence_penalty: float = 0
    n: int = 1
    tools: list | None = None
    tool_choice: str | dict | None = None
    response_format: dict | None = None
    stop: str | list[str] | None = None
    seed: int | None = None
    logit_bias: dict | None = None
    ao: dict = Field(default_factory=dict)


def error(message: str, status: int = 400, code: str = "invalid_request_error", task_id: str = ""):
    payload = {"error": {"message": message, "type": code, "code": code}}
    if task_id:
        payload["task_id"] = task_id
    return JSONResponse(payload, status_code=status)


def install_openai_api(app, worker, api_key: str, wait_seconds: float):
    from .web_service import TaskInput

    if len(api_key) < 16 or api_key != api_key.strip():
        raise ValueError("AO_API_KEY must be at least 16 characters without surrounding whitespace")
    if not 0 < wait_seconds <= 3600:
        raise ValueError("chat wait timeout must be between 0 and 3600 seconds")
    model_id = f"ao/{worker.engine.domain.domain_id}/{worker.workspace_id}"
    models = [model_id]
    if worker.engine.artifact_store is not None:
        models.append(model_id + "/report")

    def authorized(request):
        return hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + api_key).encode())

    @app.get("/v1/models")
    async def list_models(request: Request):
        if not authorized(request):
            return error("Invalid API key", 401, "authentication_error")
        return {"object": "list", "data": [{"id": m, "object": "model", "created": 0, "owned_by": "hermes-ao"} for m in models]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        if not authorized(request):
            return error("Invalid API key", 401, "authentication_error")
        try:
            value = ChatInput.model_validate(await request.json())
            if value.model not in models:
                return error("Unknown A/O model", 404, "model_not_found")
            if value.n != 1 or value.top_p != 1 or value.frequency_penalty or value.presence_penalty or value.tools or value.tool_choice not in (None, "none") or value.response_format or value.stop or value.seed is not None or value.logit_bias:
                return error("Only text chat, n=1, temperature and token limits are supported; tools/structured output and other sampling controls are unavailable")
            if value.stream_options is not None and (set(value.stream_options) - {"include_usage"} or type(value.stream_options.get("include_usage", False)) is not bool):
                return error("Only stream_options.include_usage is supported")
            if value.messages[-1].role != "user" or any(not m.content.strip() for m in value.messages):
                return error("Messages must contain non-empty text and end with a user message")
            if set(value.ao) - {"subject_id", "equipment_id", "request_kind", "create_artifact", "knowledge_scopes", "domain_id"}:
                return error("Unsupported A/O option")
            options = dict(value.ao)
            if value.model == model_id + "/report":
                options["create_artifact"] = True
                options.setdefault("request_kind", "document_task")
            # OpenWebUI sends full history. Use a fresh C/M session per request to
            # avoid accumulating the same history twice or mixing unrelated chats.
            task = TaskInput(objective=value.messages[-1].content,
                             session_id="owui-" + uuid4().hex, **options)
            task_id = worker.submit(task, conversation=tuple(m.model_dump() for m in value.messages[:-1]),
                                    temperature=value.temperature,
                                    max_tokens=value.max_completion_tokens or value.max_tokens)
        except (ValidationError, ValueError, TypeError):
            return error("Invalid or oversized chat request; check supported text fields and domain options")
        except HTTPException as exc:
            return error(str(exc.detail), exc.status_code, "rate_limit_error")

        started = time.monotonic()
        completion_id = "chatcmpl-" + task_id
        created = int(time.time())
        base = str(request.base_url).rstrip("/")
        headers = {"X-AO-Task-ID": task_id}

        async def wait_result():
            while time.monotonic() - started < wait_seconds:
                row = await asyncio.to_thread(worker.job, task_id)
                if row and row["status"] == "completed":
                    return json.loads(row["result"]), None
                if row and row["status"] in {"failed", "interrupted"}:
                    return None, "A/O execution failed; inspect the task in the local console"
                await asyncio.sleep(.1)
            return None, "A/O response timed out; task may still be running. Inspect the task before retrying"

        def render(result):
            text = result["answer"]
            text += f"\n\n---\nA/O Task: `{task_id}` · [작업 정보]({base}/v1/tasks/{task_id}) · [운영 화면]({base}/)"
            for index, item in enumerate(result.get("artifacts", [])):
                text += f"\n\n[보고서 {index + 1}]({base}/v1/tasks/{task_id}/artifacts/{index})"
            return text

        def usage(result):
            # A/O is a multi-call workflow. These counts describe only its final completion.
            raw = result.get("usage", {})
            return {key: raw.get(key, 0) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}

        def chunk(delta, finish=None):
            return {"id": completion_id, "object": "chat.completion.chunk", "created": created,
                    "model": value.model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        def sse(data):
            return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"

        if value.stream:
            async def events():
                pending = asyncio.create_task(wait_result())
                try:
                    yield sse(chunk({"role": "assistant", "content": ""}))
                    while not pending.done():
                        done, _ = await asyncio.wait({pending}, timeout=5)
                        if not done:
                            yield ": A/O working\n\n"
                    result, failure = await pending
                    if failure:
                        yield sse({"error": {"message": failure, "type": "server_error"}, "task_id": task_id})
                    else:
                        content = render(result)
                        for start in range(0, len(content), 256):
                            yield sse(chunk({"content": content[start:start + 256]}))
                        yield sse(chunk({}, "stop"))
                        if value.stream_options and value.stream_options.get("include_usage"):
                            event = chunk({})
                            event.update(choices=[], usage=usage(result))
                            yield sse(event)
                    yield "data: [DONE]\n\n"
                finally:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
            return StreamingResponse(events(), media_type="text/event-stream",
                                     headers={**headers, "X-Accel-Buffering": "no"})
        result, failure = await wait_result()
        if failure:
            return error(failure, 504 if "timed out" in failure else 502, "server_error", task_id)
        return JSONResponse({"id": completion_id, "object": "chat.completion", "created": created,
                             "model": value.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": render(result)}, "finish_reason": "stop"}],
                             "usage": usage(result), "ao": {"task_id": task_id, "evidence": result.get("evidence", []), "finish_reason": result.get("finish_reason"), "usage_scope": "final_completion_only"}}, headers=headers)

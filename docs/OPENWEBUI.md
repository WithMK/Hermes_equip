# OpenWebUI → A/O → C/M → llama.cpp

Version 0.5.0 exposes a local, authenticated OpenAI-compatible **text chat subset**
on the same A/O server as the task console. The KnowledgeProvider/RAG branch and
existing specialist/workflow validation remain in the A/O execution path.

## Setup on the target Windows PC

1. Stop the older A/O service, back up the state DB, install the new package with
   `py -m pip install -e ".[web]"` (or prepare/install the updated offline bundle).
2. Set a private API key in the server's PowerShell session:

   ```powershell
   $env:AO_API_KEY = "REPLACE_WITH_A_PRIVATE_RANDOM_KEY_AT_LEAST_16_CHARACTERS"
   ```

3. Start `hermes_equipment_poc.web_cli` with the existing workspace, RAG and C/M
   options. The default local console/API address is `http://127.0.0.1:8650`.
   `--domain equipment` is the default; `--domain document` uses the document pack.
   `--artifact-root` enables the report model. `--enable-specialists` enables the
   configured Hermes gateways. C/M still points at llama.cpp and the model ID/alias
   remains `Qwen3.8-27B-UD-Q5_K_XL.gguf` unless overridden.
4. In **OpenWebUI → Admin Settings → Connections**, add an **OpenAI-compatible** connection:

   | Field | Value |
   |---|---|
   | Base URL | `http://127.0.0.1:8650/v1` |
   | API key | The same value as `AO_API_KEY` |
   | Model | Discovered via `/v1/models`: `ao/<domain>/<workspace-id>` |

   For example, workspace `trim-project` in equipment mode appears as
   `ao/equipment/trim-project`. With artifact storage enabled, select
   `ao/equipment/trim-project/report` for a grounded document report and download link.
   The model shown in OpenWebUI selects the A/O workspace, not a raw GGUF file.

OpenWebUI's backend must run on this PC and reach the loopback address. This setup
does not enable LAN exposure, Docker networking, direct cross-origin browser connections
or multi-user isolation. Keep OpenWebUI's native tool execution/file-image attachments
disabled for this connection. Title/tag/follow-up generation calls also create A/O tasks;
disable those auxiliary tasks or assign them a separate model to avoid unnecessary runs.
Authentication applies to the two OpenAI endpoints; the pre-existing local console
remains a single-user loopback application, not a remote authenticated service.

Official connection reference:
https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/

## API and behavior

- `GET /v1/models`: Bearer key required. Only the configured workspace is listed.
- `POST /v1/chat/completions`: Bearer key required; no `X-AO-Request` header needed.
  Existing console POST routes continue requiring that header. Cross-origin/Host/body
  limits still apply. No permissive CORS is enabled. Without `AO_API_KEY`, the OpenAI
  endpoints are disabled. Keys shorter than 16 characters fail startup.
- Supports string-content `system`, `user`, `assistant` messages ending in a user message,
  `stream`, `stream_options.include_usage`, `temperature`, `max_tokens` or
  `max_completion_tokens`, and `n=1`. Non-default unsupported sampling settings, tools,
  images/audio, structured output, and unknown fields return explicit errors.
- Each request enters the same bounded, durable sequential queue as the local UI.
  Queue overflow returns 429. Responses include `X-AO-Task-ID`; the response text links
  to the task API/console and any artifact. Non-stream JSON adds an `ao` metadata object.
- The `/report` model enables Markdown output and defaults to a document task. The optional
  `ao` request object accepts `subject_id`, legacy `equipment_id`, `domain_id` (must match),
  `request_kind`, `knowledge_scopes`, `create_artifact`. Normal OpenWebUI requires none of them.
- Client history and system messages are passed as **untrusted contextual text**, not
  elevated A/O instructions or new tool permissions. Only current retrieval citations
  validate as evidence. The last three prior user messages can inform follow-up retrieval.
- OpenWebUI sends full history on each turn. Each request therefore gets a fresh C/M
  session so the same history is not stored/appended twice and separate chats cannot
  accidentally share a guessed session ID. Conversation continuity comes from `messages`.
  This is not stable OpenWebUI-chat-ID mapping. Requests/history remain in the A/O journal
  and checkpoint; use external C/M retention policies for per-request session cleanup.
- Maximum input is 64 KiB JSON, with up to 40 prior messages/30,000 prior characters and
  a 20,000-character latest question. Oversized input fails explicitly rather than silently
  discarding conversation. C/M manages the final model token budget.
- Temperature/token options apply to direct C/M responses. Specialist agents retain their
  own bounded completion settings. Usage reports describe the final completion only,
  not total RAG/specialist token consumption.

## Streaming, errors and cancellation

SSE begins with an assistant-role event and sends keepalive comments while A/O runs.
After evidence/result validation, the answer is emitted in chunks followed by `stop`
and `[DONE]`. This is **validated-result streaming**, not live llama.cpp token forwarding.
An optional final usage chunk has empty choices. Failures emit an error event and `[DONE]`,
never a successful final stop event. Non-stream failures return 502 with sanitized messages.

The default response wait is 600 seconds. Non-stream timeout returns 504 and task ID.
Timeout/disconnect stops waiting, not the persisted task; it may still finish in the console.
Inspect that task before retrying. Automatic cancellation, idempotent retries and live
progress UI are not provided in this phase.

## Target-PC acceptance

Verify model discovery; ask about an indexed equipment/document; send a follow-up referring
to it; confirm citations and the matching task; select `/report` and open the Markdown link;
check streaming and a bad API key; then inspect history after server restart. Real
OpenWebUI/C/M/llama.cpp inference and the Windows offline install must be verified there.
Local API tests use synthetic providers and cannot certify the model's answer quality.

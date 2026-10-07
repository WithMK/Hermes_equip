# Phase 5 — local A/O API and control interface

This is a local, single-user task console, not a multi-user service or an Agent lifecycle manager.
It reuses SingleOrchestrator, the fixed specialist dispatcher, SQLite state and registered artifacts.
No change to the Hermes upstream runtime, EquipmentRAG or ContextManager is required.

## Install and start (Windows)

From this repository, using the same Python environment as the integration:

```powershell
py -m pip install -e ".[web]"
py -m hermes_equipment_poc.web_cli `
  --state-db C:\ProgramData\HermesEquipment\state\orchestra.db `
  --workspace-id trim-project `
  --workspace-name "Equipment workspace" `
  --workspace-root D:\EquipmentSW `
  --artifact-root C:\ProgramData\HermesEquipment\artifacts `
  --equipment-rag-base-url http://127.0.0.1:8765 `
  --context-manager-base-url http://127.0.0.1:8091 `
  --context-model Qwen3.8-27B-UD-Q5_K_XL.gguf `
  --enable-specialists
```

Open **http://127.0.0.1:8650**. Override the four specialist URLs with the same
`--document-agent-base-url`, `--code-analysis-agent-base-url`,
`--troubleshooting-agent-base-url`, `--code-development-agent-base-url` CLI options.
Hermes specialist servers must already be running; this service does not start them.
The intended inference route is A/O → ContextManager → llama.cpp (not Ollama).
The model above is the CLI default; if llama.cpp uses `--alias`, pass that served model ID
with `--context-model` and configure the same upstream model in the Hermes profiles.
See [KnowledgeProvider integration](KNOWLEDGE_PROVIDER.md) for the retrieval boundary.
Service API keys use the existing environment variables and are not included in registry responses.
The stored workspace root must match the launch argument. One workspace is served per state database.

For Phase 5 offline bundles, the preparation and installation scripts now resolve the `[web]`
extra (current package version 0.4.0). Prepare the bundle on Windows; an old 0.2.0 wheelhouse is insufficient.
The UI uses only bundled HTML/CSS/JavaScript: no CDN, Node build, Docker or external fonts.
Wheelhouse resolution and installation on the real Windows target still require acceptance testing.

## API

| Method / path | Purpose |
|---|---|
| `GET /health` | HTTP/worker liveness, not external service readiness |
| `GET /v1/workspace` | Selected workspace and feature flags |
| `POST /v1/tasks` | Validate, persist submission and return 202 + task_id |
| `GET /v1/tasks?limit=50` | Recent web and CLI tasks in this workspace (maximum 100) |
| `GET /v1/tasks/{id}` | State, persisted answer, execution mode, safe error summary |
| `GET /v1/tasks/{id}/runs` | Parent/child Agent Run order and results |
| `GET /v1/tasks/{id}/evidence` | Source identity and summary |
| `GET /v1/tasks/{id}/artifacts` | Registered artifact metadata and index-based URLs |
| `GET /v1/tasks/{id}/artifacts/{index}` | Root-bound, SHA-256 verified plaintext download |
| `GET /v1/agents` | Fixed configured Agent registry (read-only) |
| `GET /v1/agents/{id}/health` | Probe configured `/v1/models`; not inference/tool authorization proof |

POST requires `Content-Type: application/json` and `X-AO-Request: 1`.
Only these fields are accepted: `objective`, `session_id`, `equipment_id`, `request_kind`,
`create_artifact`, `knowledge_scopes`, `domain_id`, `subject_id`. Domain must match the
operator-configured workspace; see [Domain Packs](DOMAIN_PACKS.md). Workspace, endpoint, file path and tool permissions are
server configuration, never browser input. Unknown fields fail validation.

The UI generates a session ID if omitted and retains it locally. Reusing it forwards the same
session identifier to C/M; conversation interpretation still depends on the configured C/M contract.
The UI is a task-oriented prompt/history console, not a separate conversation-memory implementation.

## Execution and recovery

- One sequential worker; at most 20 queued/running submissions. Overflow returns 429.
- The web submission journal is `<state-db>.web.db`, separate from A/O domain tables.
- A 202 acknowledges persisted submission, not successful execution. A/O Task creation follows in
  the worker; queued submissions remain queryable before that point.
- Refresh/reopen preserves Task/results. The browser polls every 2.5 seconds.
- Normal shutdown waits for the current bounded service calls; queued work is not drained.
- On the next start, unfinished web submissions become `interrupted`, active child Runs/Tasks are
  failed, and nothing is automatically replayed. Inspect existing answers/artifacts before resubmission.
- A lock `<state-db>.web.db.worker.lock` rejects a second worker process. After a crash, an operator
  must verify the old process has stopped before removing that exact stale lock. Never use multiple
  Uvicorn workers or reload mode with this service.
- Upstream raw exception bodies are not returned in the API. Detailed legacy state errors remain
  in the operator's local state DB; do not distribute the DB without reviewing/redacting it.

## UI capabilities and limits

The page shows task history, prompt input, status, Agent runs, evidence, answers and artifact
downloads/previews. Model output uses textContent/plaintext, not executable HTML/Markdown.
Specialist-disabled and no-evidence paths are displayed explicitly.

4B is **read-only in the web interface**: run the operator-confirmed proposal CLI against the same
workspace/state DB and artifact root, then view its comparison report (diff/build/test) in the UI.
No proposal apply, stage, commit, push, merge, arbitrary file download, Agent create/delete,
process start/stop or equipment control API exists. Agent tool policies shown are expectations,
not a live audit of Hermes's registered tools. Agent version/model/tool discovery is deferred.

Security boundary: bind to `127.0.0.1` only, same-origin requests, Host allowlist, no permissive CORS,
custom POST header, 64 KiB body limit, restrictive CSP and verified artifact reads. This is **not
authentication against other local users/processes**. Do not expose it via reverse proxy, port
forwarding or LAN; remote/multi-user operation needs authentication and authorization first.

## Tests

```powershell
py -m pip install -e ".[web,test]"
py -m unittest discover -s tests -v
py -m compileall -q src tests
py tests/web_http_smoke.py
```

Optional browser regression (Node + Playwright and Chromium, test machines only): run
`tests/web_demo_server.py` with `src` on PYTHONPATH, then `node tests/web_browser_smoke.cjs`.
It uses **synthetic RAG/LLM/specialists**, not real-service integration. It checks submit, specialist
history, evidence, report preview, reload, mobile layout and JavaScript errors.
`web_http_smoke.py` starts its own test server and verifies real HTTP submission, specialist runs,
artifact download and static assets without needing a browser. Port 18650 must be available.

Target-PC acceptance: launch real services; test general question, grounded troubleshooting with
specialists enabled, no evidence, endpoint outage, page reload, 4A report download, existing 4B
comparison report, graceful stop and interrupted recovery. Windows CI and target-PC tests are
separate from Linux Work validation; do not infer Windows acceptance from Linux success.

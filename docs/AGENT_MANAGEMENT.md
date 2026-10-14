# Agent management — version 0.6.0

The local A/O console now manages named Agent profiles: create, edit, trial inference,
activate, deactivate, delete, and inspect configuration history. OpenWebUI chat and
console tasks use the same managed specialist dispatcher in the web server.

## Workflow

1. Start `web_cli` with the existing workspace, endpoint and model arguments.
   Add `--enable-specialists` to execute specialist workflows.
2. Open `http://127.0.0.1:8650` and click **Agent 등록**.
3. Choose a unique ID, display name, role template and supplementary instructions.
4. Save (the profile starts disabled), then click **시험 호출**.
5. After a passed result, click **활성화**. The previously active profile for that
   role is deactivated atomically. There is at most one active profile per role.
6. Submit a task in the console or OpenWebUI. The result shows the profile ID/version
   used alongside the specialist role. Profile selection happens when a task starts.

Available templates follow the Domain Pack: equipment supports document, code analysis,
troubleshooting and code development (change proposal); document supports document only.
Additional instructions are appended to the specialist's context alongside the existing
role/citation/permission constraints. They cannot configure new tools or endpoints.

Editing a profile disables it and clears its successful trial. Test the new version
before activation. A failed trial also disables an active profile. A trial sends a small
synthetic evidence sample to the configured gateway and validates its answer/citation;
it does not certify real-data quality or audit the gateway's tool permissions.

Delete requires an inactive profile. Deletion hides the configuration but preserves its
audit history and reserves the ID. Use a new ID if you want to recreate an Agent.
If a required role has no active profile, the task fails explicitly rather than silently
using a different Agent. Keep the necessary roles enabled for your selected workflow.

## Deployment and persistence

- Existing CLI gateway URLs, credential environment variables and role model IDs remain
  the operator-owned presets. Model routing stays Hermes gateway → C/M → llama.cpp.
  The web form selects a role preset, not a raw model or arbitrary API endpoint.
- `<state-db>.agents.db` stores profiles, versions and audit events, bound to one workspace.
  Back it up along with the A/O state DB and web journal. Connections are explicitly closed
  for Windows compatibility. The main A/O state schema does not change in this release.
- The first start seeds the existing role profiles, preserving `--enable-specialists`
  behavior. Those active legacy entries are labeled `legacy`, not falsely marked tested.
  Subsequent starts retain edited/disabled/deleted state. Endpoint changes invalidate the
  affected profiles and require a new trial and activation.
- `--enable-specialists` remains a global execution switch. Without it, the UI can prepare
  and test profiles, but tasks use the existing direct C/M route. Enabling a profile in the
  UI does not override that startup switch.
- During managed task execution or a trial, configuration writes return 409; refresh/retry
  after it finishes. Version numbers reject stale edits. The single-process/one-worker
  deployment restriction still applies. Stop the previous server before changing startup
  endpoint settings; stale worker locks require the existing operator recovery procedure.
- Task checkpoints retain the active configuration snapshot. Completed results record
  the actual profile ID/version for each delegation. Later edits do not rewrite past runs.
- The standalone `orchestrator_cli` retains its static specialist configuration. Managed
  profiles apply to `web_cli` (both console and OpenWebUI), not independent CLI processes.

## API

All mutations use the existing same-origin/Host/64 KiB body checks and `X-AO-Request: 1`.
These endpoints belong to the local single-user console; `AO_API_KEY` only authenticates
the OpenAI chat facade and does not grant access to a remotely exposed admin service.
Unknown input fields, including endpoint/API key/tool settings, are rejected.

| Route | Purpose |
|---|---|
| GET `/v1/agent-templates` | Operator-configured role presets |
| GET `/v1/agents` | Profiles with role, version, enabled and trial status |
| POST `/v1/agents` | Create with agent_id/name/role/instructions |
| PUT `/v1/agents/{id}` | Edit with version/name/role/instructions |
| POST `/v1/agents/{id}/test` | Trial inference with version |
| POST `/v1/agents/{id}/enabled` | Set enabled with version and boolean |
| DELETE `/v1/agents/{id}?version=N` | Tombstone an inactive profile |
| GET `/v1/agents/{id}/history` | Last 100 audit events, including deleted profiles |
| GET `/v1/agents/{id}/health` | Endpoint reachability only |

## Scope and acceptance

This release manages A/O profiles using the existing four role templates. It does not
install/start/stop Hermes processes, create new workflow role types, edit external Hermes
tool permissions, switch raw LLM models, or introduce parallel Agent teams. Those need
separate runtime/workflow controls.

On the target PC: register a document profile, test and activate it, submit an OpenWebUI
document request, verify its ID/version in the console, restart and confirm persistence,
then deactivate/delete it and inspect history. Confirm your real Hermes/C/M/llama.cpp
gateway returns valid citations. Local tests use synthetic providers.

Automated browser script (test-only Playwright required): set `AO_TEST_MANAGEMENT=1`,
start `python tests/web_demo_server.py`, and run `node tests/agent_browser_smoke.cjs`.
The Work browser run was blocked by a truncated Chromium download; browser/visual
acceptance is pending. Unit/API tests and the real HTTP smoke can run without Chromium.

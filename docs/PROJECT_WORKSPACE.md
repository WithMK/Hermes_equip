# Project workspace and memory — version 0.7.0

The local A/O console manages generic projects inside the operator-bound Workspace.
A project has a name, goal/description, optional subject and RAG metadata filters;
it groups web tasks, their verified artifacts, user decisions and open items.
It works with both built-in equipment and document Domain Packs. No external C/M,
Hermes Core or EquipmentRAG change is required for this step.

## Use

1. Start `web_cli` with the existing service/Workspace arguments. For general
   document work, use a document Workspace and `--domain document`.
2. Open the console, click **프로젝트 생성**, and enter a unique ID, name and goal.
3. Optionally set default subject, document **Project** and code **Repository**.
   The latter two must match the metadata already indexed in RAG exactly. They
   are retrieval filters, not local directory paths or security permissions.
4. Add **확정 결정** or **미해결 항목**. Only the user creates confirmed decisions;
   generated answers are never automatically promoted to decisions.
5. Submit a task. It uses the project binding and, unless disabled, a bounded
   project memory snapshot. View the exact snapshot under the execution result.
6. Click **이 작업 이어가기** to include a specific completed result as historical
   context. Registered report downloads also appear in the project result area.
7. Mark a note resolved to stop reusing it. Archive a project to stop new tasks
   and note changes; its history and results remain available. Reopen in settings.

No project selected means the console lists all Workspace tasks and new submissions
remain unassigned, preserving the existing workflow. Existing CLI/web tasks are not
silently moved into projects. CLI-created tasks remain outside the project catalog.

## Memory behavior

- Snapshot at submission, not at execution: up to six active user notes and up to
  two relevant completed project results, plus a short project description.
- The initial selector uses words and Korean bigrams over objectives, with no new
  embedding model. It examines the latest 200 completed web jobs. An explicit
  source task can be older and takes priority. Unrelated results are omitted.
- Selected past objectives also inform the new RAG query; current evidence is
  retrieved again instead of treating the old answer as fresh proof.
- Prior answers are labeled `unconfirmed_ai_output`, carry their source task and
  original retrieval binding, and have old square-bracket citations replaced with
  historical-reference labels. They are not current RAG evidence or tool authority.
- Failed/interrupted/no-evidence results are excluded from automatic selection.
  A user may still record an explicit decision independently.
- Notes retain their full contents; the prompt includes a selected subset. Each
  note is at most 1,000 characters, with a 200-note limit per project. Serialized
  memory is at most 12,000 characters; context/token budgeting remains C/M's job.
- `use_memory=false` omits memory while retaining project assignment and retrieval
  filters. `source_task_id` requires memory enabled and a completed same-project job.
- Project tasks always use a new C/M session derived from Workspace/project/task
  identity. Reusing a UI session label cannot expose another project's C/M history.
- The frozen snapshot is in the web journal and A/O `request_saved` checkpoint.
  Editing a note or project later does not rewrite prior runs or queued requests.
- User decisions/open items can be corrected or resolved with optimistic versions;
  their previous contents remain in the audit history.

## OpenWebUI

Refresh OpenWebUI's model list after creating a project. In addition to the existing
Workspace models, `/v1/models` advertises active projects as:

```
ao/<domain>/<workspace>/project/<project-id>
ao/<domain>/<workspace>/project/<project-id>/report
```

Select the project model for normal chat: no custom request extension is needed.
The report variant requires an artifact store. Archived projects disappear from
discovery. Programmatic clients may also pass `ao.project_id`, `ao.use_memory`
and `ao.source_task_id`; a project option cannot contradict the selected model.
The OpenWebUI chat history is client-supplied context; start separate chats for
different projects. Server Memory separation cannot remove data a client sends.

## API and persistence

| Route | Purpose |
|---|---|
| GET/POST `/v1/projects` | List/create generic projects |
| GET/PUT `/v1/projects/{id}` | Inspect/edit/archive/reopen with version |
| GET/POST `/v1/projects/{id}/memory` | List/add user decisions and open items |
| PUT `/v1/projects/{id}/memory/{note}` | Correct/resolve with version |
| GET `/v1/projects/{id}/history` | Last 100 configuration/memory events |
| GET `/v1/tasks?project_id={id}` | Project tasks with evidence and artifacts |
| POST `/v1/tasks` | Add project_id/use_memory/source_task_id to existing input |

All administration retains local same-origin/Host/body-size checks and requires
`X-AO-Request: 1`. Browsers cannot configure arbitrary roots, model endpoints or tools.
Unknown fields are rejected. Source task references in notes must be completed in
the same project. There is no project delete operation: use archive to preserve records.

Back up `<state-db>.projects.db` with the A/O state, `.web.db` journal, Agent registry
and artifact directory. Catalog binding is Workspace + domain. SQLite connections
close explicitly. The web journal adds an indexed project_id column with an empty
default; existing rows remain valid. The core state schema is unchanged.

## Boundaries and acceptance

Projects on this server share one operator-controlled filesystem root, Domain Pack,
KnowledgeProvider and active Agent configuration. They organize work and Memory;
they are not independent tenants. Domain switching, project-specific Agent assignment,
file upload/automatic indexing, arbitrary dataset extraction and semantic long-term
memory search remain future steps. RAG filters are only as good as indexed metadata;
blank fields do not restrict that channel. For equipment/document mixed retrieval,
set both document Project and code Repository when both channels should be scoped.

The target PC should verify: create two generic projects; record separate decisions;
run a report and follow-up in each; verify no automatic cross-project memory; inspect
actual RAG metadata filtering; restart; correct/resolve notes; archive/reopen; select
project models from OpenWebUI with the real Hermes/C/M/llama.cpp services.

Synthetic checks: `python -m unittest discover -s tests -q` and
`python tests/web_http_smoke.py`. For browser acceptance, install test-only Playwright,
start `AO_TEST_MANAGEMENT=1 python tests/web_demo_server.py`, then run
`node tests/project_browser_smoke.cjs`. Browser/visual acceptance is pending in Work:
Chromium downloads returned truncated archives. HTTP tests use actual sockets with
synthetic providers and do not certify real-service answer quality.

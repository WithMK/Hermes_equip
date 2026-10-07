# Phase 6B — equipment and document Domain Packs

The built-in `equipment` and `document` packs define classification, retrieval planning,
allowed request kinds/scopes/specialists, prompt identity, subject label and no-evidence text.
They are operator-selected Python policies in `domains.py`, not downloadable plugins or
LLM-generated executable manifests. Common Task/Run/evidence/artifact handling is shared.

| Behavior | equipment (default) | document |
|---|---|---|
| Automatic classification | Existing equipment rules | Document task |
| Retrieval | Code/document/all based on request | Always document-only |
| Specialists | Existing four roles | Document Agent only |
| Subject | Equipment identifier | Document topic/reference |
| Scopes | Existing 00–07 | No equipment taxonomy |
| Outputs | Existing workflows | Cited answer or Markdown report |

## Launch on Windows

Use the same launcher as Phase 5 and add `--domain document`. Use a new workspace and
prefer a separate state DB for the document deployment. Example (replace paths/endpoints):

```powershell
py -m hermes_equipment_poc.web_cli `
  --state-db C:\ProgramData\HermesEquipment\documents\orchestra.db `
  --workspace-id general-documents `
  --workspace-name "General documents" `
  --workspace-root D:\Documents `
  --artifact-root C:\ProgramData\HermesEquipment\document-artifacts `
  --domain document `
  --equipment-rag-base-url http://127.0.0.1:8765 `
  --context-manager-base-url http://127.0.0.1:8091 `
  --context-model Qwen3.8-27B-UD-Q5_K_XL.gguf
```

Add `--enable-specialists` when the existing Document Agent gateway is running; override
`--document-agent-base-url` if needed. For direct CLI execution, add `--objective`,
optionally `--subject-id` and `--create-artifact`. Inference remains C/M → llama.cpp.
The configured model ID must match the server alias when one is used.

The web form displays the workspace's supported request kinds and subject label.
Workspace domain is fixed by the operator; the browser cannot switch the deployment.
`GET /v1/workspace` now returns `domain_id`, `subject_label`, `allowed_request_kinds`.
Task POST accepts optional `domain_id` (must match), `subject_id`, and legacy `equipment_id`.

## Compatibility and persistence

- SQLite schema 1 automatically migrates to schema 2. Workspaces/tasks become `equipment`;
  old task equipment IDs are copied to subject IDs. Existing task/run/artifact IDs are kept.
- Stop the previous worker and back up its DB before upgrading. A schema-1 executable will
  reject a migrated DB; rollback requires the backup, not a manual schema version downgrade.
- Existing `equipment_id` requests still work. Equipment-domain `subject_id` is an alias;
  conflicting aliases are rejected. Document-domain requests reject `equipment_id`.
- The workspace's persisted domain must match the launched engine. Use another workspace
  to adopt a different domain. No web endpoint changes an existing workspace's domain.
- Domain/subject are saved in Tasks, ContextPacks and request checkpoints. Decision reuse
  requires the same workspace/domain/subject. Restart checks domain before interrupting state.
- Document-domain C/M sessions are namespaced by workspace/domain/subject/session. Equipment
  sessions retain the existing IDs to preserve deployed conversation continuity.

## Knowledge boundaries

EquipmentRAG and C/M need no server changes. The launcher still selects EquipmentRAG via
the 6A KnowledgeProvider adapter. A custom provider can be injected when composing an engine.
The document pack uses `/v1/retrieve` with `source_type=document`; `subject_id` is prepended
to the search query, NOT mapped to the equipment filter and NOT an exact metadata filter.
EquipmentRAG may apply its deployment's default equipment/index scope. Configure a suitable
document index/endpoint; this change does not create a cross-tenant document repository.

Invalid domain/kind/scope fails before queue submission. Empty evidence skips inference;
code evidence in document mode fails closed. Citation and artifact integrity rules still apply.
The specialist gateway must use its read-only deployment profile; Domain Pack selection does
not rewrite the external Hermes runtime's tool permissions or ContextManager settings.

## Acceptance

Automated tests exercise old-schema migration/reopen, equipment aliases, document-only
retrieval, specialist/report creation, generic prompts, session separation, cross-subject
decision rejection, domain mismatch and API validation. Existing 1–6A regression tests remain.

On the target PC, verify both deployments: equipment troubleshooting and ordinary document
analysis; check the UI labels/options, citations, downloaded Markdown report, same-session
follow-up through C/M/llama.cpp and history after restart. Work tests use synthetic services;
they do not establish real model or browser acceptance.

Dynamic Agent creation/deletion, arbitrary Domain Pack installation, OpenWebUI-compatible
chat facade, multi-provider fusion and dataset automation remain later phases.

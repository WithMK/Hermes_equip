# Single Orchestrator

## Scope

The single Orchestrator implements one bounded request without specialist delegation:

```text
classify -> plan -> retrieve -> build Context Pack -> call ContextManager
         -> validate citations -> persist -> complete
```

- General questions without equipment context skip EquipmentRAG.
- Document, code, troubleshooting and change requests retrieve explicit evidence.
- An evidence-required request with no results returns a deterministic safe answer without calling
  the LLM.
- A grounded answer must cite at least one supplied Source ID.
- Retrieval, completion and validation failures are stored on both Task and Agent Run.

## ContextManager boundary

ContextManager remains the OpenAI-compatible conversation/token/LLM proxy. The A/O client posts to
`/v1/chat/completions`. Its non-standard session field is configurable because the external service
contract may use a different field or no request-body session field.

ContextManager automatic RAG must be disabled for the A/O route. A/O already selects and embeds the
exact EquipmentRAG evidence; enabling both paths would duplicate retrieval and make source auditing
ambiguous.

## CLI smoke test

```powershell
$env:EQUIPMENT_RAG_API_KEY = ""
$env:CONTEXT_MANAGER_API_KEY = ""

py -m hermes_equipment_poc.orchestrator_cli `
  --state-db C:\ProgramData\HermesEquipment\state\orchestra.db `
  --workspace-id trim-project `
  --workspace-name "MLCC Trimming" `
  --task-id TASK-E024-001 `
  --session-id USER-SESSION-001 `
  --objective "Loader Vacuum 알람 원인과 조치 방법을 분석해줘" `
  --equipment-id E-024 `
  --knowledge-scope 06 `
  --equipment-rag-base-url http://RAG_PC_IP:8765 `
  --context-manager-base-url http://CONTEXT_PC_IP:8091 `
  --context-model REPLACE_MODEL_NAME
```

If ContextManager does not accept `session_id` in the OpenAI request body, pass an empty value:

```powershell
--context-session-field ""
```

The command emits JSON and returns exit code `0` only after the Task reaches `completed`. It returns
exit code `1` with the persisted `task_id` when orchestration fails.

## Request classification

| Kind | Retrieval |
|---|---|
| `question` | none unless Equipment, equipment identifier or knowledge scope is supplied |
| `document_task` | document |
| `code_analysis` | code |
| `troubleshooting` | code + document |
| `code_change` | code + document; this phase returns a plan only |

The caller can set `request_kind` explicitly. Otherwise a bounded deterministic classifier is used.
Model-based planning and specialist delegation are deferred to the next milestone.

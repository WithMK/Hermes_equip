# Sequential Specialist Delegation

## Scope

Milestone 4 adds deterministic specialist handoff on top of the Single Orchestrator:

```text
classify -> retrieve once -> build Context Pack -> fixed specialist chain
         -> validate every handoff -> persist lineage -> complete
```

The Agent Orchestra still owns Task state, retrieval selection and evidence identity. Each Hermes
specialist API server receives a bounded Context Pack, only the evidence relevant to its role and
the earlier specialist results needed for synthesis. ContextManager remains behind each profile as
the conversation/token/LLM proxy.

## Fixed routes

| Request kind | Sequential route |
|---|---|
| `question` | No specialist; direct bounded C/M completion |
| `document_task` | Document Agent |
| `code_analysis` | Code Analysis Agent |
| `troubleshooting` | Document Agent when document evidence exists, Code Analysis Agent when code evidence exists, then Troubleshooting Agent |
| `code_change` | Code Analysis Agent when code evidence exists, then Code Development Agent |

Dynamic Agent creation, parallel delegation and free-form Agent-to-Agent messaging are not used.
EquipmentRAG is called once by A/O; specialists receive the selected evidence instead of performing
an implicit second retrieval.

## Fail-closed validation

- Every child Agent Run is linked to the parent Orchestrator Run.
- Each specialist must finish with `completed` and cite at least one supplied Source ID when it was
  given evidence.
- Unknown Source IDs, missing citations, endpoint errors and malformed results fail both the child
  and parent Run and move the Task to `failed`.
- Each completed handoff is checkpointed with its agent name, sequence number and evidence IDs.
- Prior specialist text and retrieved content are explicitly marked as untrusted data.

## Phase boundary

Code Development is read-only in this milestone. Its profile can inspect code and Git history, but
`workspace_write`, `git_write`, `git_merge_request` and `dotnet_build` are disabled. It returns a
change plan only. File changes, build/test, work-branch commit and external merge approval are the
next production-workflow milestone.

## CLI smoke test

Start the four Hermes profile API servers on ports 8642 through 8645, then add
`--enable-specialists` to the existing Orchestrator command:

```powershell
py -m hermes_equipment_poc.orchestrator_cli `
  --state-db C:\ProgramData\HermesEquipment\state\orchestra.db `
  --workspace-id trim-project `
  --objective "E-024 Loader Vacuum 알람 원인을 분석해줘" `
  --equipment-rag-base-url http://RAG_PC_IP:8765 `
  --context-manager-base-url http://CONTEXT_PC_IP:8091 `
  --context-model REPLACE_MODEL_NAME `
  --enable-specialists
```

Default specialist endpoints are `127.0.0.1:8642` through `127.0.0.1:8645`. Override them with
the corresponding `--*-agent-base-url` arguments when Hermes runs on another host. API keys are
read from `HERMES_DOCUMENT_AGENT_API_KEY`, `HERMES_CODE_ANALYSIS_AGENT_API_KEY`,
`HERMES_TROUBLESHOOTING_AGENT_API_KEY` and `HERMES_CODE_DEVELOPMENT_AGENT_API_KEY`.

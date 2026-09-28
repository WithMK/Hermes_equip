# Hermes Equipment Agent PoC Status

Updated: 2026-09-28

## Overall

Status: **Sequential specialist delegation implemented / target-PC integration pending**

## Completed

| Item | Result | Evidence |
|---|---|---|
| Hermes upstream pin | Pass | `v2026.9.7`, commit `2237be355906fbe6065ce1815711eee52b2d646e` |
| Approval source path inspection | Pass | Plugin approval and Runs approval code present |
| Core modification | Pass | No upstream source changes |
| PoC package import | Pass | Editable package import successful |
| Actual PluginManager load | Pass | Enabled, no plugin error, expected tools registered |
| Profile YAML validation | Pass | Orchestrator and four specialist profiles have bounded toolsets |
| Arbitrary terminal exclusion | Pass | All profiles globally disable `terminal` |
| Equipment control tool exclusion | Pass | Motion/Servo/PLC/IO/Recipe/Run/Stop tools absent |
| Protected branch direct commit | Pass | Unit test rejects commit on `main` |
| Work branch commit | Pass | Unit test creates commit on work branch |
| Merge SHA binding | Pass | Wrong SHA rejected; exact SHA rechecked |
| Merge replay prevention | Pass | One-time request cannot execute twice |
| Workspace escape | Pass | Out-of-root path rejected |
| File overwrite race | Pass | Existing file requires matching SHA-256 |
| Audit JSONL | Pass | Agent/session/tool/result/duration fields recorded |
| Windows Native | User verified | Windows environment operational |
| llama.cpp chat/tool call | User verified | Chat completion and structured tool call operational |
| EquipmentRAG service | User verified | Code/document/all retrieval operational |
| ContextManager service | User verified | OpenAI proxy, bounded session context and token management operational |
| EquipmentRAG API alignment | Pass | `/health`, `/v1/retrieve`, `code/document/all` implemented |
| Remote endpoint configuration | Pass | RAG Tool URL and C/M model URL are independently configurable |
| A/O domain contract | Pass | Task transitions, Context Pack, evidence and artifact contracts |
| A/O State Store | Pass | SQLite WAL, optimistic version, Task/Run/Evidence/Decision/Artifact/Checkpoint persistence |
| Single Orchestrator | Pass | classify, plan, retrieve, C/M completion, citation validation and persistence |
| Specialist delegation | Pass | Fixed sequential routes, role-scoped evidence and parent/child Run lineage |
| Specialist validation | Pass | Missing/unknown citation and endpoint failure stop child, parent and Task |
| Code Development phase boundary | Pass | Read-only plan mode; write/build/Git mutation toolsets disabled |
| Build target allowlist | Pass | Empty/unlisted target fails closed |

## Security decision

Hermes upstream은 `--yolo` 세션에서 Plugin approval gate를 우회하도록 설계되어 있다.
따라서 `request_main_merge` handler에는 merge 기능이 없다. 이 Tool은 Agent Workspace 밖의
승인 저장소에 요청만 생성한다. 실제 merge executor는 Hermes Tool registry에 등록되지 않고
사용자가 별도 CLI에서 one-time 요청 ID를 확인한 뒤 실행한다.

이 구조에서 `--yolo`가 활성화되어도 Agent는 main merge를 직접 실행할 수 없다.

## Automated tests

```text
Ran 64 tests
OK
```

Test coverage:

- Workspace boundary
- Plugin tool surface
- Merge executor non-exposure
- Compare-and-swap file write
- Main direct commit denial
- Work branch commit
- Exact-SHA merge approval
- Approval replay denial
- Audit event fields
- EquipmentRAG v1 request mapping
- Multi-scope taxonomy merge
- ContextManager is used as the OpenAI-compatible model provider, not a domain-context Tool
- Bounded A/O task-state transitions
- SQLite restart persistence and newer-schema rejection
- Optimistic Task version conflict and terminal-state mutation denial
- Agent Run parent scope, one-time completion and Checkpoint recovery
- Request classification and optional RAG fast path
- ContextManager session-field forwarding and OpenAI response validation
- no-evidence safe answer and citation/adapter failure persistence
- Fixed specialist route planning and role-specific evidence filtering
- Specialist profiles cannot repeat A/O-owned RAG retrieval
- Sequential prior-result handoff and parent/child Agent Run lineage
- Specialist failure and missing-citation fail-closed behavior
- Build target allowlist

## Pending target-PC acceptance

Milestones 1–3 hardening is documented in `AO_STABILIZATION.md`: complete-block evidence budgets,
all-citation validation, incomplete-response rejection, Task-isolated specialist sessions, explicit
decision reuse and operator-triggered cold restart. Automatic checkpoint continuation is NOT implemented.

RAG와 C/M의 기존 직접 연동은 사용자 환경에서 확인됐다. 다음 단계에서는 A/O가 네 개의
Hermes 전문 Agent API Server를 순차 호출하고 각 Profile이 C/M을 model provider로 사용하는
전체 경로를 시험한다.

```powershell
.\scripts\Test-ExternalServices.ps1 `
  -EquipmentRagBaseUrl http://RAG_PC_IP:8765 `
  -ContextManagerBaseUrl http://CONTEXT_PC_IP:8091 `
  -ContextModel REPLACE_MODEL_NAME `
  > external-services.json
```

그 다음 `docs/FINAL_ACCEPTANCE.md`의 Agent 권한, 개발 Workflow, 부정 보안 시험과 폐쇄망
재설치를 수행한다.

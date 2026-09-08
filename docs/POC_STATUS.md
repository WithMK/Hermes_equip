# Hermes Equipment Agent PoC Status

Updated: 2026-09-08

## Overall

Status: **Phase 1 accepted / Integrated Phase 2 ready for target-PC acceptance**

## Completed

| Item | Result | Evidence |
|---|---|---|
| Hermes upstream pin | Pass | `v2026.9.7`, commit `2237be355906fbe6065ce1815711eee52b2d646e` |
| Approval source path inspection | Pass | Plugin approval and Runs approval code present |
| Core modification | Pass | No upstream source changes |
| PoC package import | Pass | Editable package import successful |
| Actual PluginManager load | Pass | Enabled, no plugin error, expected tools registered |
| Profile YAML validation | Pass | Four profiles parsed; enabled/disabled sets do not overlap |
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
| ContextManager service | User verified | Session continuity and pronoun resolution operational |
| EquipmentRAG API alignment | Pass | `/health`, `/v1/retrieve`, `code/document/all` implemented |
| Remote endpoint configuration | Pass | RAG/Context URL, auth and paths are profile settings |
| Build target allowlist | Pass | Empty/unlisted target fails closed |

## Security decision

Hermes upstream은 `--yolo` 세션에서 Plugin approval gate를 우회하도록 설계되어 있다.
따라서 `request_main_merge` handler에는 merge 기능이 없다. 이 Tool은 Agent Workspace 밖의
승인 저장소에 요청만 생성한다. 실제 merge executor는 Hermes Tool registry에 등록되지 않고
사용자가 별도 CLI에서 one-time 요청 ID를 확인한 뒤 실행한다.

이 구조에서 `--yolo`가 활성화되어도 Agent는 main merge를 직접 실행할 수 없다.

## Automated tests

```text
Ran 12 tests
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
- Configurable ContextManager paths
- Build target allowlist

## Pending target-PC acceptance

현재 개발 환경에서는 내부 EquipmentRAG와 ContextManager에 접근할 수 없으므로 서비스에
접근 가능한 Windows PC에서 다음 결과를 확보한다.

```powershell
.\scripts\Test-ExternalServices.ps1 `
  -EquipmentRagBaseUrl http://RAG_PC_IP:8765 `
  -ContextManagerBaseUrl http://CONTEXT_PC_IP:8091 `
  > external-services.json
```

그 다음 `docs/FINAL_ACCEPTANCE.md`의 Agent 권한, 개발 Workflow, 부정 보안 시험과 폐쇄망
재설치를 수행한다.

# Hermes Equipment Agent PoC

Hermes Agent를 Runtime으로 사용해 EquipmentRAG, ContextManager와 제한형 개발 Tool을
조정하는 사내 설비제어SW Agent Orchestra PoC이다.

## 고정 원칙

- Hermes Core는 수정하지 않는다.
- EquipmentRAG는 Knowledge Retrieval Service로 유지한다.
- ContextManager는 짧은 대화 연속성, 요약, 토큰 예산과 Local LLM Proxy만 담당한다.
- Agent Orchestra는 Project/Equipment/Task, 결정, 근거와 산출물 상태를 소유한다.
- Agent에는 arbitrary shell command를 제공하지 않는다.
- 실제 설비제어, production 배포, force push 기능은 제공하지 않는다.
- Hermes Tool은 main merge를 실행할 수 없고 승인 요청만 생성한다.
- 실제 main merge는 Agent에 노출되지 않은 one-time 사용자 승인 실행기만 수행한다.

## 기준 Hermes

- Tag: `v2026.9.7`
- Commit: `2237be355906fbe6065ce1815711eee52b2d646e`
- Upstream: <https://github.com/NousResearch/hermes-agent>

## 디렉터리

```text
docs/                 Gap Analysis, Architecture, Test Matrix
config/profiles/      Agent별 Hermes 설정 예시
src/.../resources/    8계통 공통 Taxonomy
plugin/               Hermes Plugin 진입점
src/                   Adapter와 제한형 Tool 구현
tests/                 정책 및 Tool 단위 테스트
scripts/               Windows PoC 실행/검증 스크립트
```

## 현재 범위

통합 Phase 2 기준선을 A/O 구조로 정리하는 개발본이다. Windows, EquipmentRAG,
ContextManager의 실제 연결은
대상 PC에서 수행하며 이 저장소에는 내부 주소나 Credential을 포함하지 않는다.

- WithMK/EquipmentRAG의 `GET /health`, `POST /v1/retrieve` 계약 지원
- EquipmentRAG `/v1/retrieve` Tool과 ContextManager `/v1/chat/completions` 모델 경로 분리
- SQLite A/O State Store의 Task, Agent Run, 근거, 결정, 산출물과 Checkpoint 영속화
- 코드/문서/통합 검색과 8계통 `document_type` 매핑
- Orchestrator와 4개 전문 Agent별 Toolset 최소 권한
- 제한형 File/Git/Build/Log Tool
- 작업 branch commit과 외부 main merge 승인
- Tool/Skill/Approval Audit JSONL

Hermes의 `--yolo`가 Plugin 승인 게이트도 우회할 수 있으므로, merge 실행 권한을 Hermes
밖으로 분리했다. 실제 사내 Endpoint 주소나 Credential은 포함하지 않는다.

승인 실행 예시:

```powershell
py -m hermes_equipment_poc.approve_merge `
  --workspace-root D:\EquipmentSW `
  --approval-store C:\ProgramData\HermesEquipment\approvals `
  --request-id REPLACE_REQUEST_ID
```

## 개발 테스트

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 다른 PC의 서비스 연결

```powershell
.\scripts\Test-ExternalServices.ps1 `
  -EquipmentRagBaseUrl http://RAG_PC_IP:8765 `
  -ContextManagerBaseUrl http://CONTEXT_PC_IP:8091 `
  -ContextModel REPLACE_MODEL_NAME
```

상세 설정은 `docs/REMOTE_INTEGRATION.md`, 최종 시험 순서는 `docs/FINAL_ACCEPTANCE.md`를
참고한다. A/O 단계별 구현 범위는 `docs/AO_DEVELOPMENT_PLAN.md`에 정리한다.
State Store 운영 경계와 복구 방법은 `docs/AO_STATE_STORE.md`를 따른다.
단일 Orchestrator 실행 방법은 `docs/SINGLE_ORCHESTRATOR.md`를 참고한다.

## 폐쇄망 설치 번들

인터넷 연결 Windows PC에서 아래 스크립트를 실행하면 Hermes Core, MCP, Windows x64
의존성, PortableGit과 이 PoC를 포함한 자체 완결 ZIP을 만든다.

```powershell
.\scripts\Prepare-HermesOfflineBundle.ps1
```

폐쇄망 PC에서는 ZIP을 압축 해제한 후 포함된 `Install-HermesOffline.ps1`을 실행한다.
설치 스크립트는 전체 파일 SHA-256을 검증하고, `pip --no-index`를 강제한다. 상세 절차와
제외 기능은 `docs/OFFLINE_INSTALL.md`를 참고한다.

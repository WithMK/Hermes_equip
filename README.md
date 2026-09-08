# Hermes Equipment Agent PoC

Hermes Agent를 범용 Runtime으로 사용하면서 기존 EquipmentRAG와 ContextManager를
Adapter로 연결하기 위한 사내 설비제어SW PoC이다.

## 고정 원칙

- Hermes Core는 수정하지 않는다.
- EquipmentRAG는 Knowledge Retrieval Service로 유지한다.
- ContextManager는 Persistent Work Context의 소유자로 유지한다.
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

통합 Phase 2 구현본이다. Windows, llama.cpp, EquipmentRAG, ContextManager의 실제 연결은
대상 PC에서 수행하며 이 저장소에는 내부 주소나 Credential을 포함하지 않는다.

- WithMK/EquipmentRAG의 `GET /health`, `POST /v1/retrieve` 계약 지원
- 원격 EquipmentRAG/ContextManager URL, 인증 Header, Endpoint 경로 설정
- 코드/문서/통합 검색과 8계통 `document_type` 매핑
- 4개 Agent별 Toolset 최소 권한
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
  -ContextManagerBaseUrl http://CONTEXT_PC_IP:8091
```

상세 설정은 `docs/REMOTE_INTEGRATION.md`, 최종 시험 순서는 `docs/FINAL_ACCEPTANCE.md`를
참고한다.

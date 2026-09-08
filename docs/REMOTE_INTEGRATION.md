# Remote EquipmentRAG / ContextManager Integration

## EquipmentRAG contract

기준 저장소는 `WithMK/EquipmentRAG` commit
`81604a3aa10777cd516db646e3efbfe6c12efba9`이다.

Adapter는 저장소의 read-only API를 그대로 사용한다.

| Operation | Request |
|---|---|
| Health | `GET /health` |
| Code search | `POST /v1/retrieve`, `source_type=code` |
| Document search | `POST /v1/retrieve`, `source_type=document` |
| Combined evidence | `POST /v1/retrieve`, `source_type=all` |

EquipmentRAG PC에서는 원격 접근을 명시적으로 허용해야 한다.

```powershell
python -m app serve `
  --config config\config.local.yaml `
  --host 0.0.0.0 `
  --port 8765 `
  --allow-remote
```

EquipmentRAG API 자체에는 인증과 TLS가 없으므로 신뢰된 사내 VLAN과 Windows Firewall
허용 목록 안에서만 노출한다. 망 경계를 넘으면 인증/TLS Reverse Proxy가 필요하다.

## Taxonomy mapping

공통 8계통 scope는 EquipmentRAG의 `document_type` filter로 변환한다. 하나의 질문이 여러
scope를 선택하면 scope별 검색 결과를 `record_id`로 중복 제거하고 score 순으로 다시
정렬한다. 실제 Index의 `document_type` 값이 다르면 `config/integration.example.yaml`의
`taxonomy_document_types`만 변경한다.

## ContextManager contract

ContextManager 내부 구현은 이 저장소 범위가 아니다. 다음 POST endpoint 경로를 모두
profile 설정으로 교체할 수 있다.

- Health
- Session context
- Project context
- Equipment context
- Recent entity resolution

인증값은 설정 파일에 기록하지 않고 `CONTEXT_MANAGER_API_KEY` 환경변수로 전달한다.
Bearer가 아닌 인증 방식을 쓰면 `api_key_header`와 `api_key_prefix`를 변경한다.

## 다른 PC에서 연결 확인

PoC wheel 설치 후 다음 명령을 실행한다.

```powershell
$env:EQUIPMENT_RAG_API_KEY = ""  # Reverse Proxy 인증 사용 시에만 입력
$env:CONTEXT_MANAGER_API_KEY = ""

.\scripts\Test-ExternalServices.ps1 `
  -EquipmentRagBaseUrl http://RAG_PC_IP:8765 `
  -ContextManagerBaseUrl http://CONTEXT_PC_IP:8091 `
  -SessionId hermes-poc-smoke
```

ContextManager 경로가 다르면 `ContextHealthPath`, `ContextGetPath`,
`ContextResolvePath` 인자로 실제 경로를 전달한다. 출력에는 응답 본문 대신 상태,
결과 수와 key 목록만 기록한다.

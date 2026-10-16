# 프로젝트별 Agent 배정 — 1단계: 저장 및 API

이 단계는 배정 설정의 저장·검증 기반입니다. UI와 실제 실행 적용은 후속 단계입니다.
응답의 `runtime_applied: false`, `execution_mode: legacy`가 이를 표시합니다.
custom 설정을 저장해도 현재 업무 실행과 위임 방식은 바뀌지 않습니다.

## API

- GET `/v1/projects/{project_id}/agent-assignments`: 저장 설정 및 현재 Agent 유효성 조회
- PUT 같은 경로: 전체 설정 교체. 기존 웹 API의 동일 출처 정책과 `X-AO-Request: 1` 필요
- 최초 저장은 version 0, 이후에는 조회한 배정 version 전달. 충돌은 409
- 활성 프로젝트에서만 변경 가능. 보관 프로젝트는 조회만 가능
- Agent 관리 연결이 없는 경우 조회는 가능하며 저장은 503

```json
{
  "version": 0,
  "configuration": {
    "schema_version": 1,
    "mode": "custom",
    "default_agent_id": "document-agent",
    "agents": [
      {
        "agent_id": "document-agent",
        "assignment": "문서 검토",
        "instructions": "근거 누락을 확인한다.",
        "enabled": true,
        "allow_delegation": true
      }
    ],
    "delegation_enabled": true,
    "max_delegations": 4
  }
}
```

배정 최대 32개, Agent ID 중복 금지, 지침 최대 4,000자, 위임 횟수 0~8입니다.
위임 활성 시 횟수는 1 이상이어야 합니다. custom 모드는 활성 배정 중 기본 담당을
지정해야 합니다. 활성 배정은 현재 사용 가능한 활성 Agent만 참조할 수 있습니다.
비활성 배정도 존재하는 Agent ID를 참조해야 합니다. 서비스 주소·인증키·새 도구 권한은
입력할 수 없습니다. 역할 설명은 표시/지침용이며 실행 도구를 생성하지 않습니다.

배정 저장은 Agent 공통 프로필을 변경하지 않습니다. 이후 공통 Agent가 비활성화되거나
삭제되면 GET의 validation_issues에 표시하고 원래 배정은 보존합니다. 대체 Agent를
자동 선택하지 않습니다. 현재 공통 레지스트리는 역할별 활성 Agent 한 개를 지원하므로,
프로젝트마다 같은 역할의 서로 다른 프로필을 실행하는 기능은 3단계에서 확장합니다.

배정은 기존 `.projects.db`의 별도 테이블에 저장합니다. 프로젝트 기본 정보 버전과
배정 버전은 독립적입니다. 변경 이력은 프로젝트 history에 남습니다.
schema 1→2 자동 마이그레이션을 수행하므로 업데이트 전에 상태 DB를 백업하세요.

## 후속 단계

2. 프로젝트 화면에서 배정 편집 및 저장
3. 프로젝트별 프로필 선택, 실행 시작 시 설정 고정, 실제 위임 적용 및 결과 표시
4. JSON 가져오기/내보내기와 적용 전 비교, 대상 PC 통합 검증

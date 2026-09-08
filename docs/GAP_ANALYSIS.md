# Gap Analysis

## A. 그대로 사용하는 기능

- Agent loop와 tool calling
- Profiles와 profile별 session/state 분리
- Skill progressive disclosure
- MCP stdio/HTTP client 및 tool include/exclude
- OpenAI-compatible API Server
- Plugin tool/hook 등록
- SQLite session storage

## B. 설정이 필요한 기능

- 사내 GLM 및 llama.cpp custom model endpoint
- Profile별 toolset allowlist
- `agent.disabled_toolsets` global deny
- API key, bind address, CORS
- Session retention/prune
- Hermes memory tool 비활성화

## C. Adapter가 필요한 기능

- EquipmentRAG REST/MCP Adapter
- ContextManager REST/MCP Adapter
- ContextManager turn context injection
- Audit event sink
- 외부 Frontend용 approval client
- Agent 외부 one-time main merge approval executor

## D. 별도 Tool이 필요한 기능

- 제한형 Git read/write Tool
- `request_main_merge`
- main merge request store와 human approval CLI
- 고정형 Build/Test Tool
- Log read/search Tool

## E. Core 수정 가능성이 있는 기능

현재 계획에는 없다. 다음이 Plugin/Adapter로 해결되지 않을 때만 재평가한다.

- Runs API approval transport의 fail-closed 승인 흐름
- Profile/toolset 격리
- Approval과 merge 대상 commit SHA의 결합

## F. 위험 또는 범위 밖 기능

- arbitrary terminal
- Motion/Servo/PLC/IO/Recipe/Run/Stop Tool
- production 배포
- force push
- Agent가 접근 가능한 설비망 Credential
- Prompt만으로 구현한 보안 정책
- Hermes `--yolo`를 main merge 보안 경계로 허용

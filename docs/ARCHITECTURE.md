# PoC Architecture

```text
OpenWebUI / Approval Client
          |
Agent Orchestra / Hermes API Server
          |
Hermes Agent Loop + Skills + Toolset allowlist
          |
Hermes Equipment Plugin
  |                    |          |
RAG Adapter        Git/Build  Audit Hook
  |                    Tools
EquipmentRAG

Agent Orchestra -> SQLite State Store

Hermes model provider -> ContextManager /v1/chat/completions -> llama.cpp/Ollama
```

## Responsibility

| Component | Responsibility |
|---|---|
| Agent Orchestra | Project/Equipment/Task, planning, delegation, evidence and artifact state |
| A/O State Store | Task, Agent Run, decision, evidence, artifact and recovery checkpoint |
| Hermes | Agent loop, skills, tool dispatch and approval transport |
| EquipmentRAG | Code/document retrieval, embedding, vector/hybrid search, evidence |
| ContextManager | Bounded conversation, summary, token budget and Local LLM proxy |
| Skills | 업무 수행 절차와 판단 기준 |
| Plugin Tools | 제한된 파일, Git, Build, Log 기능 |
| Audit Hook | Tool, Skill, Approval event 기록 |

ContextManager는 Hermes Plugin Tool이 아니다. 각 Profile의 OpenAI-compatible model
`base_url`이 ContextManager `/v1`을 가리킨다. A/O는 EquipmentRAG를 명시적으로 호출해
선택한 근거만 model message에 넣으며, C/M은 이 입력과 짧은 대화 이력을 토큰 예산 안에서
llama.cpp/Ollama로 전달한다.

## Approval boundary

Hermes의 `request_main_merge`는 merge를 실행하지 않고, Agent Workspace 밖의 승인 저장소에
one-time 요청만 생성한다. 실제 merge executor는 Hermes Tool registry에 등록되지 않는다.
사용자가 별도 승인 CLI에서 요청 ID를 확인하고 정확한 확인 문구를 입력해야 실행된다.
Executor는 승인 요청의 `expected_sha`를 merge 직전 다시 검증하고 요청을 원자적으로
소비하므로 재사용할 수 없다.

Hermes Runs approval은 다른 위험 Tool의 UX 보조 수단으로 검증할 수 있지만 main merge의
최종 보안 경계로 사용하지 않는다. Upstream 동작상 `--yolo`가 Plugin approval을 건너뛸 수
있기 때문이다.

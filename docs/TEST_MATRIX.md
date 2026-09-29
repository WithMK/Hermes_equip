# PoC Test Matrix

| ID | 영역 | 검증 | 합격 조건 |
|---|---|---|---|
| WIN-01 | Windows | Native CLI/API 실행 | Docker/WSL 없이 실행 |
| WIN-02 | Windows | 재부팅 후 Gateway 복구 | 동일 Profile/API 정상 |
| LLM-01 | llama.cpp | chat completion | 응답 성공 |
| LLM-02 | llama.cpp | structured tool call | 인자 손실 없이 호출 |
| LLM-03 | GLM | chat completion | 응답 성공 |
| LLM-04 | GLM | structured tool call | 인자 손실 없이 호출 |
| API-01 | API | OpenAI chat endpoint | OpenWebUI 질의 성공 |
| API-02 | API | Runs SSE | tool lifecycle 수신 |
| RAG-01 | RAG | search_code | evidence/source 반환 |
| RAG-02 | RAG | search_document | taxonomy scope 반영 |
| RAG-03 | RAG | retrieve_evidence | source_type=all 근거 반환 |
| CTX-01 | Context | OpenAI chat proxy | `/v1/chat/completions` 응답 성공 |
| CTX-02 | Context | bounded conversation | 후속 질문이 끊기지 않고 토큰 한도 유지 |
| AO-01 | Orchestra | Task 상태 전이 | 허용 경로만 성공하고 완료 후 변경 거부 |
| AO-02 | Orchestra | Context Pack | Task·제약·근거 ID가 전문 Agent에 전달 |
| AO-03 | Orchestra | SQLite 재시작 | Task·근거·결정·산출물·Checkpoint 유지 |
| AO-04 | Orchestra | 동시 상태 변경 | 오래된 version 변경 요청 거부 |
| AO-05 | Orchestra | Terminal Task | 완료·실패 후 업무 상태 추가 변경 거부 |
| AO-06 | Orchestra | 요청 분류 | 질문·문서·코드·Trouble·변경 유형 선택 |
| AO-07 | Orchestra | 검색 없는 질문 | RAG를 호출하지 않고 C/M 응답 |
| AO-08 | Orchestra | 근거 기반 응답 | 사용한 Source ID 인용 후 완료 |
| AO-09 | Orchestra | 검색/검증 실패 | Task와 Agent Run이 `failed`로 영속화 |
| AO-10 | Orchestra | 전문 Agent 순차 위임 | 고정 순서와 parent/child Run 계보 유지 |
| AO-11 | Orchestra | 역할별 근거 분리 | Document는 문서, Code Analysis는 코드 근거만 수신 |
| AO-12 | Orchestra | 위임 실패/허위 인용 | child·parent Run과 Task가 fail-closed |
| ART-01 | Artifact | Markdown 보고서 | exclusive-create, SHA-256, Task 등록 |
| ART-02 | Artifact | 저장 위치 | Agent Workspace 밖으로 제한 |
| DEV-01 | Proposal | Clean main에서 작업 branch 생성 | `work/ao-*`, Base SHA 고정 |
| DEV-02 | Proposal | 파일 변경 | 운영자 allowlist + CAS SHA가 모두 일치 |
| DEV-03 | Proposal | Build/Test | allowlist 대상만 실행하고 결과 기록 |
| DEV-04 | Proposal | 비교 | Base Diff와 전후 SHA Artifact 생성 |
| DEV-05 | Proposal | Git 경계 | stage/commit/push/merge 0건, HEAD 불변 |
| DEV-06 | Proposal | 예상 밖 파일 | Build 생성 파일 포함 즉시 실패 |
| ACL-01 | 권한 | Profile별 tool 목록 | 미허용 Tool schema 부재 |
| ACL-02 | 권한 | Workspace 외부 접근 | fail-closed 거부 |
| GIT-01 | Git | 작업 branch commit | 성공 및 audit 기록 |
| GIT-02 | Git | main 직접 commit | 실행 전 거부 |
| BLD-01 | Build | allowlist solution build/test | 등록 대상만 실행 |
| BLD-02 | Build | unlisted target | 실행 전 거부 |
| SEC-01 | OS | Hermes 계정 설비망 접근 | Windows Firewall/ACL 차단 |
| GIT-03 | Git | force push | Tool 자체가 존재하지 않음 |
| APR-01 | 승인 | main merge 승인 전 | merge 0건 |
| APR-02 | 승인 | 승인 거부/timeout | merge 0건 |
| APR-03 | 승인 | 승인된 SHA 변경 | 승인 무효/거부 |
| APR-04 | 승인 | `--yolo` 우회 시도 | Hermes에 merge executor가 없어 실행 불가 |
| APR-05 | 승인 | 승인 요청 재사용 | 두 번째 실행 거부 |
| AUD-01 | Audit | 중요 Tool 호출 | 요구 필드 기록 |
| OFF-01 | Offline | 깨끗한 PC 재설치 | 인터넷 요청 없이 성공 |
| EQP-01 | 설비 | 설비 명령/망 접근 | Tool/Route/Credential 모두 부재 |
# Phase 5 web acceptance additions

- Persisted HTTP submission, immediate 202, bounded sequential queue and 429 overflow
- Same-origin / Host / custom-header guards and strict bounded input validation
- Cross-workspace task hiding and sanitized upstream failures
- Task/Run/Evidence/Artifact retrieval, specialist route and no-evidence diagnosis
- Artifact root/hash checks and read-only CLI proposal comparison visibility
- Restart persistence, interrupted-job non-replay and exclusive worker lock
- Offline static assets and no mutation/Agent lifecycle API
- Windows SQLite explicit close in normal and newer-schema exception paths
- Browser/target-PC acceptance remains pending; `tests/web_browser_smoke.cjs` provided

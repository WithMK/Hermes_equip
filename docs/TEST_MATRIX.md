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
| CTX-01 | Context | recent entity 해석 | 후속 대명사 해소 |
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

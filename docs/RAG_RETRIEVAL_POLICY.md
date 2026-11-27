# RAG 검색 정책

## 변경 이유

기존 equipment 도메인의 일반 질문은 설비 ID, 자료 범위 또는 특정 키워드가
없으면 검색을 생략했다. 따라서 RAG에 자료가 있어도 A/O가 검색을 호출하지 않아
C/M에 근거가 전달되지 않을 수 있었다.

이제 기본값은 `retrieval_mode=required`이다. 일반 질문도 RAG를 검색하고,
검색된 근거를 C/M으로 전달한다. 코드 분석은 code, 문서 작업은 document,
일반 질문은 all 검색을 사용한다. 기존 프로젝트·저장소·설비·자료 범위 필터는 유지된다.
RAG 서버나 C/M의 API 변경, SQLite 스키마 변경은 필요하지 않다.

## 정책 선택

| 값 | 동작 |
| --- | --- |
| `required` (기본) | 일반 질문도 검색한다. 근거가 없으면 `no_evidence`로 완료하고 LLM을 호출하지 않는다. 인사말도 이 정책을 따른다. |
| `auto` | 기존 분류 기준을 사용한다. 조건 없는 일반 대화는 검색을 생략할 수 있다. 설비 ID·자료 범위·업무 유형·프로젝트 설정 등에 따라 검색이 필요하면 실행한다. 검색 비활성화 옵션은 아니다. |

웹 UI의 작업 입력에서 **RAG 검색 정책**을 선택한다. 초기 선택은 서버 기본값을 따른다.

CLI 단일 실행과 웹 서버 시작 명령은 `--retrieval-mode required` 또는
`--retrieval-mode auto`를 받는다. 생략하면 required이다.

웹 API 예시 (`POST /v1/tasks`, 기존 `X-AO-Request: 1` 헤더 필요):

```json
{"objective": "작동 방식을 설명해주세요", "retrieval_mode": "required"}
```

OpenWebUI 등 OpenAI 호환 API 클라이언트 예시
(`POST /v1/chat/completions`, 기존 Bearer 인증 필요):

```json
{
  "model": "ao/equipment/W",
  "messages": [{"role": "user", "content": "작동 방식을 설명해주세요"}],
  "ao": {"retrieval_mode": "required"}
}
```

`W`는 실제 workspace ID로 바꾼다. document 도메인은 해당 모델 ID를 사용한다.
`ao`를 보내지 못하는 클라이언트도 서버 기본값 required를 적용받는다.
요청별 설정은 서버 기본값보다 우선한다. Python의 `create_app(..., retrieval_mode='auto')`도 지원한다.

자료를 좁힐 때만 실제 `equipment_id` 또는 `knowledge_scopes`를 전달한다.
웹·OpenAI API의 필드명은 `knowledge_scopes`이며 `scopes`가 아니다.
검색을 유도하려고 임의 설비 ID를 넣으면 오히려 필터 때문에 근거가 없어질 수 있다.

## 확인

작업 상세의 진단과 `GET /v1/tasks/{task_id}`의 `retrieval_mode`에서 적용 정책을 확인한다.
이 값은 정책 설정이며 호출 성공 여부는 아니다. 실제 근거는 작업 evidence 목록과
RAG 요청 로그로 확인한다. 정책이 저장되기 전의 웹 작업은 기존 방식인 auto로 표시된다.

자동 검증은 일반 질문 검색, C/M으로 본문 전달, 근거 없음 시 LLM 생략,
명시적 auto, 서버 auto 기본값과 요청별 required 우선 적용, 유형별 검색 유지,
웹 API 및 OpenAI 호환 API 경로를 포함한다. 실제 llama.cpp 답변 품질과 사내 PC
네트워크 연결은 대상 환경에서 확인한다.

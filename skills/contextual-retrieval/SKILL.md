---
name: contextual-retrieval
description: Resolve project, equipment, task and follow-up references through ContextManager before searching EquipmentRAG.
version: 0.1.0
platforms: [windows]
metadata:
  hermes:
    category: equipment
    requires_toolsets: [context_manager]
---

# Contextual Retrieval

## Why

Hermes Session은 현재 실행의 단기 문맥만 담당하고, Project/Equipment/Task 및 대명사 의미는
ContextManager가 소유한다. EquipmentRAG에 대화 Memory 책임을 중복시키지 않는다.

## When to use

- 설비, Project 또는 Task 범위가 검색 정확도에 영향을 줄 때
- “그 센서”, “이 변경”, “이전 문제” 같은 후속 표현이 있을 때
- 이전 대화의 대상을 사용해 코드·문서·통합 검색을 수행할 때

## Procedure

1. 현재 `session_id`로 ContextManager context를 조회한다.
2. Project/Equipment가 필요한데 확정되지 않았으면 전용 context를 조회한다.
3. 후속 표현이 있으면 `resolve_recent_entity`로 의미를 확정한다.
4. 해석된 Entity와 Task를 포함한 standalone query를 작성한다.
5. Agent에 허용된 EquipmentRAG Tool로 standalone query를 검색한다.
6. 응답에 해석된 대상, 검색 범위와 source identifier를 남긴다.

## Error handling

ContextManager가 응답하지 않으면 대명사를 임의 해석하지 않는다. 사용자가 명시한 문장만으로
안전하게 검색할 수 있으면 제한사항을 밝히고 진행하고, 그렇지 않으면 대상을 질문한다.

## Completion

- 대명사 또는 생략된 대상이 standalone query에서 명시됨
- Context와 RAG의 책임이 분리됨
- 검색 근거와 미확인 Context가 구분됨

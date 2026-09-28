---
name: contextual-retrieval
description: Rewrite the current request into a standalone EquipmentRAG query using the bounded conversation and task context supplied by the Agent Orchestrator.
version: 0.2.0
platforms: [windows]
metadata:
  hermes:
    category: equipment
---

# Contextual Retrieval

## Why

ContextManager는 짧은 대화의 연속성과 토큰 예산만 관리한다. Project, Equipment, Task,
의사결정과 산출물의 구조화된 업무 문맥은 Agent Orchestrator가 소유한다. EquipmentRAG는
검색 근거만 반환하며 어느 문맥을 사용할지 결정하지 않는다.

## When to use

- 설비, Project 또는 Task 범위가 검색 정확도에 영향을 줄 때
- “그 센서”, “이 변경”, “이전 문제” 같은 후속 표현이 있을 때
- 이전 대화의 대상을 사용해 코드·문서·통합 검색을 수행할 때

## Procedure

1. Orchestrator가 전달한 현재 Task, Equipment, 결정과 최근 대화만 확인한다.
2. 후속 표현이 가리키는 대상이 이 범위에서 하나로 확정되는지 검사한다.
3. 확정된 Entity와 Task를 포함한 standalone query를 작성한다.
4. Agent에 허용된 EquipmentRAG Tool로 standalone query를 검색한다.
5. 응답에 해석된 대상, 검색 범위와 source identifier를 남긴다.

## Error handling

제공된 문맥만으로 대상을 하나로 확정할 수 없으면 임의 해석하지 않는다. 사용자가 명시한
문장만으로 안전하게 검색할 수 있으면 제한사항을 밝히고 진행하고, 그렇지 않으면 대상을
질문한다.

## Completion

- 대명사 또는 생략된 대상이 standalone query에서 명시됨
- Orchestrator 문맥과 RAG의 책임이 분리됨
- 검색 근거와 미확인 Context가 구분됨

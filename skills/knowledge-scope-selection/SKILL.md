---
name: knowledge-scope-selection
description: Select the smallest relevant equipment knowledge taxonomy scope before any document or combined evidence retrieval.
version: 0.1.0
platforms: [windows]
metadata:
  hermes:
    category: equipment
    requires_toolsets: [knowledge_taxonomy]
---

# Knowledge Scope Selection

## Why

검색 범위를 무조건 전체로 넓히면 서로 다른 설비·시점·의사결정의 문서가 혼합될 수 있다.
따라서 검색 전에 공통 Taxonomy를 확인하고 현재 Task에 필요한 최소 계통만 선택한다.

## When to use

- `search_document` 또는 `retrieve_evidence` 호출 전
- 사양, 변경, 의사결정, 테스트, 장애 문서를 함께 비교할 때
- 기존 범위에서 근거가 부족해 검색 범위를 확장할 때

## Procedure

1. `get_knowledge_taxonomy`를 호출해 현재 공통 기준을 읽는다.
2. Task 목적에 직접 필요한 계통만 선택한다.
3. 선택 근거를 한 문장으로 정리한다.
4. 선택한 `knowledge_scope`로 검색한다.
5. 근거 부족이 확인된 경우에만 인접 계통으로 확장한다.

## Completion

- 사용한 scope code가 응답에 기록됨
- 근거의 source identifier가 보존됨
- 전체 범위 확장 시 이유가 기록됨


---
name: code-development
description: Implement a bounded equipment-control software change on a work branch and finish with build, test, diff review, and commit evidence.
version: 0.1.0
platforms: [windows]
metadata:
  hermes:
    category: equipment
    requires_toolsets: [git_read, git_write, workspace_read, workspace_write, dotnet_build]
---

# Code Development

## Why

코드 변경은 요구사항 근거, 변경 범위, Build/Test 결과와 Git 이력이 함께 남아야 검토 가능하다.

## When to use

- 사용자가 명시적으로 코드 수정을 요청한 경우
- 작업 저장소와 완료 조건이 확인된 경우

## Procedure

1. Context와 요구사항 근거를 확인한다.
2. `git_get_status`로 기존 변경을 확인하고 사용자 변경을 보존한다.
3. 관련 코드와 영향 범위를 조사한다.
4. 보호 브랜치가 아닌 작업 브랜치를 생성한다.
5. 파일을 읽고 반환된 SHA를 사용해 비교 후 쓰기를 수행한다.
6. Solution을 Build하고 관련 Test를 실행한다.
7. Diff를 검토하고 명시적 파일만 stage한다.
8. 작업 브랜치에 commit한다.
9. 변경, 검증, 잔여 위험을 보고한다.

## Stop conditions

- 요구사항 또는 대상 저장소가 불명확함
- 기존 사용자 변경과 충돌함
- Build/Test 실패 원인이 작업 범위를 벗어남
- main 직접 commit 또는 force push가 필요함
- 실제 설비 또는 production 접근이 필요함

## Main merge

`request_main_merge`는 별도 사용자 승인이 있을 때만 호출한다. 승인 요청에는 source branch와
정확한 commit SHA를 포함한다. 승인 이후 SHA가 바뀌면 새 승인을 받아야 한다.

